from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import requests

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib

LOG_FILE_MAP = {
    "prediction": "prediction_log.jsonl",
    "probability": "probability_log.jsonl",
    "manual": "manual_score_log.jsonl",
    "analysis": "analysis_summary_log.jsonl",
}

LEGACY_LOG_FILE_MAP = {
    "prediction": ["번호추천로그.jsonl", "#Ubc88#Ud638#Ucd94#Ucc9c#Ub85c#Uadf8.jsonl", "패턴분석로그.jsonl", "패턴 분석 로그.jsonl"],
    "probability": ["확률분석로그.jsonl", "#Ud655#Ub960#Ubd84#Uc11d#Ub85c#Uadf8.jsonl"],
    "manual": ["수동번호점수로그.jsonl", "#Uc218#Ub3d9#Ubc88#Ud638#Uc810#Uc218#Ub85c#Uadf8.jsonl"],
    "analysis": ["분석요약로그.jsonl", "#Ubd84#Uc11d#Uc694#Uc57d#Ub85c#Uadf8.jsonl"],
}

APP_STATE_FILE = "app_state.json"
LOG_DB_FILE = "lotto_history.db"
KST = ZoneInfo("Asia/Seoul")

REPORT_FILE_MAP = {
    "match": "prediction_actual_match.csv",
    "threshold": "threshold_analysis.csv",
    "timeseries": "score_timeseries.csv",
    "daily_summary": "daily_log_summary.csv",
    "weekly_summary": "weekly_log_summary.csv",
    "monthly_summary": "monthly_log_summary.csv",
    "weekday_summary": "weekday_log_summary.csv",
    "log_type_summary": "log_type_summary.csv",
    "summary_json": "analysis_summary.json",
    "summary_txt": "analysis_summary.txt",
    "score_chart": "score_timeseries.png",
    "gap_chart": "gap_factor_timeseries.png",
}

_RUNTIME_MIGRATION_SIGNATURES: dict[str, tuple[Any, ...]] = {}
_RUNTIME_SQLITE_SYNC_SIGNATURES: dict[str, tuple[Any, ...]] = {}
_RUNTIME_REMOTE_BOOTSTRAP_DONE: set[str] = set()


SQLITE_UPSERT = """
INSERT OR REPLACE INTO log_records (
    record_uid, timestamp_utc, timestamp_kst, log_type, run_id, source_round, target_round,
    candidate_rank, score_metric, score, best_score, average_score, probability_score,
    input_order_score, avg_gap_factor, avg_probability_weight, numbers_json, input_numbers_json,
    best_order_json, matched_numbers_json, payload_json
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _default_app_state() -> dict[str, Any]:
    return {
        "counts": {"prediction": 0, "probability": 0, "manual": 0},
        "unlock_granted": True,
        "data_access_granted": False,
        "updated_at": None,
        "simulation_count": None,
    }


def _sanitize_counts(value: Any) -> dict[str, int]:
    raw = value if isinstance(value, dict) else {}
    return {
        "prediction": max(int(raw.get("prediction", 0) or 0), 0),
        "probability": max(int(raw.get("probability", 0) or 0), 0),
        "manual": max(int(raw.get("manual", 0) or 0), 0),
    }


def _secrets_file_candidates(base_dir: Path) -> list[Path]:
    return [
        base_dir / ".streamlit" / "secrets.toml",
        Path.cwd() / ".streamlit" / "secrets.toml",
        Path.home() / ".streamlit" / "secrets.toml",
    ]


@lru_cache(maxsize=16)
def _load_secrets_mapping(base_dir_str: str) -> dict[str, Any]:
    base_dir = Path(base_dir_str)
    for candidate in _secrets_file_candidates(base_dir):
        if not candidate.exists():
            continue
        try:
            with candidate.open("rb") as fp:
                loaded = tomllib.load(fp)
            return loaded if isinstance(loaded, dict) else {}
        except Exception:
            continue
    return {}


@lru_cache(maxsize=16)
def _persistence_config(base_dir_str: str) -> dict[str, Any]:
    base_dir = Path(base_dir_str)
    secrets = _load_secrets_mapping(str(base_dir.resolve()))
    persistence_section = secrets.get("persistence") if isinstance(secrets.get("persistence"), dict) else {}

    def resolve(name: str, section_key: str, default: Any = None) -> Any:
        env_value = os.getenv(name)
        if env_value not in {None, ""}:
            return env_value
        if section_key in persistence_section:
            return persistence_section.get(section_key)
        return secrets.get(name, default)

    backend = str(resolve("LOTTO_PERSISTENCE_BACKEND", "backend", "auto") or "auto").strip().lower()
    url = str(resolve("LOTTO_SUPABASE_URL", "supabase_url", "") or "").strip().rstrip("/")
    key = str(resolve("LOTTO_SUPABASE_KEY", "supabase_key", "") or "").strip()
    state_table = str(resolve("LOTTO_SUPABASE_STATE_TABLE", "state_table", "lotto_app_state") or "lotto_app_state").strip()
    log_table = str(resolve("LOTTO_SUPABASE_LOG_TABLE", "log_table", "lotto_log_records") or "lotto_log_records").strip()
    state_key = str(resolve("LOTTO_SUPABASE_STATE_KEY", "state_key", "main") or "main").strip()
    enabled = backend in {"auto", "supabase"} and bool(url and key)
    return {
        "backend": backend,
        "enabled": enabled,
        "url": url,
        "key": key,
        "state_table": state_table,
        "log_table": log_table,
        "state_key": state_key,
    }


def _supabase_headers(config: dict[str, Any], *, upsert: bool = False) -> dict[str, str]:
    headers = {
        "apikey": str(config["key"]),
        "Authorization": f"Bearer {config['key']}",
        "Content-Type": "application/json",
    }
    if upsert:
        headers["Prefer"] = "return=minimal,resolution=merge-duplicates"
    return headers


def _supabase_request(
    method: str,
    url: str,
    *,
    config: dict[str, Any],
    params: dict[str, Any] | None = None,
    json_payload: Any | None = None,
) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.request(
                method,
                url,
                headers=_supabase_headers(config, upsert=method.upper() in {"POST", "PATCH"}),
                params=params,
                json=json_payload,
                timeout=15,
            )
            if response.status_code in {200, 201, 204, 206}:
                return response
            if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                time.sleep(0.6 * (attempt + 1))
                continue
            response.raise_for_status()
            return response
        except requests.RequestException as exc:  # pragma: no cover - network failure path
            last_error = exc
            if attempt >= 2:
                raise
            time.sleep(0.6 * (attempt + 1))
    if last_error:
        raise last_error
    raise RuntimeError("Supabase request failed")


def _supabase_row_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    timestamp_utc = payload.get("timestamp") or payload.get("generated_at_utc")
    score_metric = payload.get("score")
    if score_metric is None:
        score_metric = payload.get("best_score")
    return {
        "record_uid": _record_uid(payload),
        "timestamp_utc": timestamp_utc,
        "timestamp_kst": _timestamp_to_kst(timestamp_utc),
        "log_type": payload.get("log_type"),
        "run_id": payload.get("run_id"),
        "source_round": payload.get("source_round"),
        "target_round": payload.get("target_round") or payload.get("next_target_round"),
        "candidate_rank": payload.get("candidate_rank"),
        "score_metric": score_metric,
        "score": payload.get("score"),
        "best_score": payload.get("best_score"),
        "average_score": payload.get("average_score"),
        "probability_score": payload.get("probability_score"),
        "input_order_score": payload.get("input_order_score"),
        "avg_gap_factor": payload.get("avg_gap_factor"),
        "avg_probability_weight": payload.get("avg_probability_weight"),
        "numbers_json": payload.get("numbers") or [],
        "input_numbers_json": payload.get("input_numbers") or [],
        "best_order_json": payload.get("best_order") or [],
        "matched_numbers_json": payload.get("matched_numbers") or [],
        "payload_json": payload,
    }


def _payload_from_remote_row(row: dict[str, Any]) -> dict[str, Any] | None:
    payload = row.get("payload_json")
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str) and payload.strip():
        try:
            loaded = json.loads(payload)
            if isinstance(loaded, dict):
                return loaded
        except json.JSONDecodeError:
            return None
    return None


def _load_remote_app_state(base_dir: Path) -> dict[str, Any] | None:
    config = _persistence_config(str(base_dir.resolve()))
    if not config["enabled"]:
        return None
    url = f"{config['url']}/rest/v1/{config['state_table']}"
    try:
        response = _supabase_request(
            "GET",
            url,
            config=config,
            params={
                "state_key": f"eq.{config['state_key']}",
                "select": "payload_json,updated_at",
                "limit": 1,
            },
        )
        rows = response.json()
    except Exception:
        return None
    if not rows:
        return None
    payload = rows[0].get("payload_json")
    return payload if isinstance(payload, dict) else None


def _save_remote_app_state(base_dir: Path, state: dict[str, Any]) -> None:
    config = _persistence_config(str(base_dir.resolve()))
    if not config["enabled"]:
        return
    url = f"{config['url']}/rest/v1/{config['state_table']}"
    row = {
        "state_key": config["state_key"],
        "updated_at": state.get("updated_at") or utc_now_iso(),
        "payload_json": state,
    }
    try:
        _supabase_request("POST", url, config=config, json_payload=[row])
    except Exception:
        return


def _fetch_remote_log_payloads(base_dir: Path) -> list[dict[str, Any]]:
    config = _persistence_config(str(base_dir.resolve()))
    if not config["enabled"]:
        return []
    url = f"{config['url']}/rest/v1/{config['log_table']}"
    offset = 0
    page_size = 1000
    payloads: list[dict[str, Any]] = []
    try:
        while True:
            response = _supabase_request(
                "GET",
                url,
                config=config,
                params={
                    "select": "payload_json,timestamp_utc,log_type,candidate_rank",
                    "order": "timestamp_utc.asc,candidate_rank.asc.nullslast",
                    "offset": offset,
                    "limit": page_size,
                },
            )
            rows = response.json()
            if not rows:
                break
            for row in rows:
                payload = _payload_from_remote_row(row)
                if payload:
                    payloads.append(payload)
            if len(rows) < page_size:
                break
            offset += page_size
    except Exception:
        return []
    return payloads


def _upsert_remote_log_payload(base_dir: Path, payload: dict[str, Any]) -> None:
    config = _persistence_config(str(base_dir.resolve()))
    if not config["enabled"]:
        return
    url = f"{config['url']}/rest/v1/{config['log_table']}"
    try:
        _supabase_request("POST", url, config=config, json_payload=[_supabase_row_from_payload(payload)])
    except Exception:
        return


def _write_grouped_jsonl_from_payloads(log_dir: Path, payloads: list[dict[str, Any]]) -> None:
    grouped = {log_type: [] for log_type in LOG_FILE_MAP}
    for payload in payloads:
        log_type = str(payload.get("log_type") or "").strip()
        if log_type not in grouped:
            continue
        grouped[log_type].append(payload)

    for log_type, file_name in LOG_FILE_MAP.items():
        file_path = log_dir / file_name
        with file_path.open("w", encoding="utf-8") as fp:
            for row in grouped[log_type]:
                fp.write(json.dumps(row, ensure_ascii=False) + "\n")


def _should_replace_local_state(local_state: dict[str, Any], remote_state: dict[str, Any]) -> bool:
    local_updated_at = str(local_state.get("updated_at") or "")
    remote_updated_at = str(remote_state.get("updated_at") or "")
    if not local_updated_at:
        return True
    if not remote_updated_at:
        return False
    return remote_updated_at >= local_updated_at


def bootstrap_remote_runtime_if_needed(base_dir: Path | str) -> None:
    base_dir = Path(base_dir)
    config = _persistence_config(str(base_dir.resolve()))
    if not config["enabled"]:
        return

    log_dir = base_dir / "logs"
    cache_key = str(log_dir.resolve())
    if cache_key in _RUNTIME_REMOTE_BOOTSTRAP_DONE:
        return

    log_dir.mkdir(parents=True, exist_ok=True)
    remote_state = _load_remote_app_state(base_dir)
    remote_payloads = _fetch_remote_log_payloads(base_dir)

    local_state_path = log_dir / APP_STATE_FILE
    local_state = _default_app_state()
    if local_state_path.exists():
        try:
            loaded = json.loads(local_state_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                local_state = loaded
        except Exception:
            pass

    if remote_state and _should_replace_local_state(local_state, remote_state):
        local_state_path.write_text(json.dumps(remote_state, ensure_ascii=False, indent=2), encoding="utf-8")

    if remote_payloads:
        _write_grouped_jsonl_from_payloads(log_dir, remote_payloads)
        db_path = _log_db_path(log_dir)
        if db_path.exists():
            db_path.unlink()
        ensure_log_database(log_dir)
        _upsert_payloads_to_sqlite(db_path, remote_payloads)
        _set_runtime_sqlite_signature(log_dir)

    _RUNTIME_REMOTE_BOOTSTRAP_DONE.add(cache_key)


def reset_runtime_persistence_caches() -> None:
    _RUNTIME_REMOTE_BOOTSTRAP_DONE.clear()
    _RUNTIME_MIGRATION_SIGNATURES.clear()
    _RUNTIME_SQLITE_SYNC_SIGNATURES.clear()
    _load_secrets_mapping.cache_clear()
    _persistence_config.cache_clear()


def load_app_state(base_dir: Path | str) -> dict[str, Any]:
    base_dir = Path(base_dir)
    bootstrap_remote_runtime_if_needed(base_dir)
    log_dir, _ = ensure_runtime_dirs(base_dir)
    state_path = log_dir / APP_STATE_FILE
    state = _default_app_state()
    if not state_path.exists():
        return state

    try:
        loaded = json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return state

    state["counts"] = _sanitize_counts(loaded.get("counts"))
    state["unlock_granted"] = bool(loaded.get("unlock_granted", True))
    state["data_access_granted"] = bool(loaded.get("data_access_granted", False))
    state["updated_at"] = loaded.get("updated_at")
    simulation_count = loaded.get("simulation_count")
    try:
        state["simulation_count"] = int(simulation_count) if simulation_count is not None else None
    except (TypeError, ValueError):
        state["simulation_count"] = None
    return state


def save_app_state(
    base_dir: Path | str,
    *,
    counts: dict[str, Any] | None = None,
    unlock_granted: bool | None = None,
    data_access_granted: bool | None = None,
    simulation_count: int | None = None,
) -> dict[str, Any]:
    base_dir = Path(base_dir)
    log_dir, _ = ensure_runtime_dirs(base_dir)
    state_path = log_dir / APP_STATE_FILE
    state = load_app_state(base_dir)

    if counts is not None:
        state["counts"] = _sanitize_counts(counts)
    if unlock_granted is not None:
        state["unlock_granted"] = bool(unlock_granted)
    if data_access_granted is not None:
        state["data_access_granted"] = bool(data_access_granted)
    if simulation_count is not None:
        try:
            state["simulation_count"] = max(int(simulation_count), 1000)
        except (TypeError, ValueError):
            pass

    state["updated_at"] = utc_now_iso()
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    _save_remote_app_state(base_dir, state)
    return state


def _candidate_log_names(log_type: str) -> list[str]:
    return [LOG_FILE_MAP[log_type], *LEGACY_LOG_FILE_MAP.get(log_type, [])]


def _candidate_log_paths(log_dir: Path, log_type: str) -> list[Path]:
    paths: list[Path] = []
    seen: set[str] = set()
    for file_name in _candidate_log_names(log_type):
        if file_name in seen:
            continue
        seen.add(file_name)
        paths.append(log_dir / file_name)
    return paths


def _file_signature(path: Path) -> tuple[str, int, int]:
    if not path.exists():
        return (path.name, 0, 0)
    stat = path.stat()
    return (path.name, stat.st_mtime_ns, stat.st_size)


def _log_files_signature(log_dir: Path) -> tuple[Any, ...]:
    signature: list[Any] = []
    for log_type in LOG_FILE_MAP:
        for path in _candidate_log_paths(log_dir, log_type):
            signature.append(_file_signature(path))
    return tuple(signature)


def _set_runtime_sqlite_signature(log_dir: Path) -> None:
    _RUNTIME_SQLITE_SYNC_SIGNATURES[str(log_dir.resolve())] = _log_files_signature(log_dir)


def ensure_log_seed_files(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    for file_name in LOG_FILE_MAP.values():
        (log_dir / file_name).touch(exist_ok=True)


def _log_db_path(log_dir: Path) -> Path:
    return log_dir / LOG_DB_FILE


def ensure_log_database(log_dir: Path) -> Path:
    db_path = _log_db_path(log_dir)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS log_records (
                record_uid TEXT PRIMARY KEY,
                timestamp_utc TEXT,
                timestamp_kst TEXT,
                log_type TEXT,
                run_id TEXT,
                source_round INTEGER,
                target_round INTEGER,
                candidate_rank INTEGER,
                score_metric REAL,
                score REAL,
                best_score REAL,
                average_score REAL,
                probability_score REAL,
                input_order_score REAL,
                avg_gap_factor REAL,
                avg_probability_weight REAL,
                numbers_json TEXT,
                input_numbers_json TEXT,
                best_order_json TEXT,
                matched_numbers_json TEXT,
                payload_json TEXT
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_log_records_timestamp ON log_records(timestamp_utc DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_log_records_type_timestamp ON log_records(log_type, timestamp_utc DESC)"
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


def _safe_json_text(value: Any) -> str:
    return json.dumps(value if value is not None else [], ensure_ascii=False)


def _timestamp_to_kst(timestamp_value: Any) -> str | None:
    if not timestamp_value:
        return None
    try:
        return (
            datetime.fromisoformat(str(timestamp_value).replace("Z", "+00:00"))
            .astimezone(KST)
            .strftime("%Y-%m-%d %H:%M:%S")
        )
    except Exception:
        return None


def _record_uid(record: dict[str, Any]) -> str:
    explicit_uid = record.get("record_uid")
    if explicit_uid:
        return str(explicit_uid)

    stable_key = "|".join(
        [
            str(record.get("run_id") or "-"),
            str(record.get("log_type") or "-"),
            str(record.get("candidate_rank") or "-"),
            str(record.get("timestamp") or record.get("generated_at_utc") or "-"),
        ]
    )
    if stable_key.replace("|", "") != "----":
        return hashlib.sha256(stable_key.encode("utf-8")).hexdigest()
    payload = json.dumps(record, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _prepare_record_for_persistence(record: dict[str, Any], log_type: str) -> dict[str, Any]:
    payload = dict(record)
    payload.setdefault("log_type", log_type)
    if not payload.get("record_uid"):
        payload["record_uid"] = uuid.uuid4().hex
    payload.setdefault("logged_at_utc", utc_now_iso())
    return payload


def _sqlite_row_from_payload(payload: dict[str, Any]) -> tuple[Any, ...]:
    timestamp_utc = payload.get("timestamp") or payload.get("generated_at_utc")
    score_metric = payload.get("score")
    if score_metric is None:
        score_metric = payload.get("best_score")
    return (
        _record_uid(payload),
        timestamp_utc,
        _timestamp_to_kst(timestamp_utc),
        payload.get("log_type"),
        payload.get("run_id"),
        payload.get("source_round"),
        payload.get("target_round") or payload.get("next_target_round"),
        payload.get("candidate_rank"),
        score_metric,
        payload.get("score"),
        payload.get("best_score"),
        payload.get("average_score"),
        payload.get("probability_score"),
        payload.get("input_order_score"),
        payload.get("avg_gap_factor"),
        payload.get("avg_probability_weight"),
        _safe_json_text(payload.get("numbers")),
        _safe_json_text(payload.get("input_numbers")),
        _safe_json_text(payload.get("best_order")),
        _safe_json_text(payload.get("matched_numbers")),
        json.dumps(payload, ensure_ascii=False),
    )


def _upsert_payloads_to_sqlite(db_path: Path, payloads: list[dict[str, Any]]) -> None:
    if not payloads:
        return
    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(SQLITE_UPSERT, [_sqlite_row_from_payload(payload) for payload in payloads])
        conn.commit()
    finally:
        conn.close()


def persist_log_record(log_dir: Path, log_type: str, record: dict[str, Any]) -> None:
    payload = _prepare_record_for_persistence(record, log_type)
    append_jsonl(log_dir / LOG_FILE_MAP[log_type], payload)

    db_path = ensure_log_database(log_dir)
    _upsert_payloads_to_sqlite(db_path, [payload])
    _set_runtime_sqlite_signature(log_dir)
    _upsert_remote_log_payload(log_dir.parent, payload)


def backfill_log_database(log_dir: Path) -> None:
    sync_log_database_if_needed(log_dir, force=True)


def persist_log_record_only_sqlite(log_dir: Path, log_type: str, record: dict[str, Any]) -> None:
    payload = _prepare_record_for_persistence(record, log_type)
    db_path = ensure_log_database(log_dir)
    _upsert_payloads_to_sqlite(db_path, [payload])


def _sqlite_record_count(db_path: Path) -> int:
    if not db_path.exists():
        return 0
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT COUNT(*) FROM log_records").fetchone()
        return int(row[0] or 0)
    finally:
        conn.close()


def sync_log_database_if_needed(log_dir: Path, *, force: bool = False) -> None:
    db_path = ensure_log_database(log_dir)
    signature = _log_files_signature(log_dir)
    cache_key = str(log_dir.resolve())
    if not force and _RUNTIME_SQLITE_SYNC_SIGNATURES.get(cache_key) == signature and _sqlite_record_count(db_path) > 0:
        return

    payloads: list[dict[str, Any]] = []
    for log_type in LOG_FILE_MAP.keys():
        for row in read_log_records(log_dir, log_type):
            payload = dict(row)
            payload.setdefault("log_type", log_type)
            payloads.append(payload)
    _upsert_payloads_to_sqlite(db_path, payloads)
    _RUNTIME_SQLITE_SYNC_SIGNATURES[cache_key] = signature


def ensure_runtime_dirs(base_dir: Path) -> tuple[Path, Path]:
    bootstrap_remote_runtime_if_needed(base_dir)
    log_dir = base_dir / "logs"
    report_dir = base_dir / "reports"
    ensure_log_seed_files(log_dir)
    migrate_legacy_log_files(log_dir)
    ensure_log_database(log_dir)
    sync_log_database_if_needed(log_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    return log_dir, report_dir


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def build_dataset_signature(excel_path: Path) -> str:
    if not excel_path.exists():
        return "missing"
    digest = hashlib.sha256(excel_path.read_bytes()).hexdigest()
    return digest[:16]


def get_round_context(excel_path: Path) -> dict[str, Any]:
    if not excel_path.exists():
        return {
            "source_round": None,
            "target_round": None,
            "draw_count": 0,
            "dataset_signature": "missing",
            "excel_modified_at": None,
        }

    df = pd.read_excel(excel_path)
    draw_count = len(df)
    source_round = None
    if "회차" in df.columns and not df.empty:
        source_round = int(pd.to_numeric(df["회차"], errors="coerce").dropna().max())

    return {
        "source_round": source_round,
        "target_round": (source_round + 1) if source_round is not None else None,
        "draw_count": int(draw_count),
        "dataset_signature": build_dataset_signature(excel_path),
        "excel_modified_at": datetime.fromtimestamp(excel_path.stat().st_mtime, tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat(),
    }


def append_jsonl(file_path: Path, payload: dict[str, Any]) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(payload, ensure_ascii=False) + "\n")


def read_jsonl(file_path: Path) -> list[dict[str, Any]]:
    if not file_path.exists():
        return []
    records: list[dict[str, Any]] = []
    with file_path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def read_log_records(log_dir: Path, log_type: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for file_path in _candidate_log_paths(log_dir, log_type):
        if not file_path.exists():
            continue
        for row in read_jsonl(file_path):
            signature = json.dumps(row, ensure_ascii=False, sort_keys=True)
            if signature in seen:
                continue
            seen.add(signature)
            records.append(row)
    return records


def migrate_legacy_log_files(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    cache_key = str(log_dir.resolve())
    signature = _log_files_signature(log_dir)
    if _RUNTIME_MIGRATION_SIGNATURES.get(cache_key) == signature:
        return

    for log_type, canonical_name in LOG_FILE_MAP.items():
        canonical_path = log_dir / canonical_name
        legacy_paths = [log_dir / name for name in LEGACY_LOG_FILE_MAP.get(log_type, [])]
        existing_legacy = [path for path in legacy_paths if path.exists()]
        if not existing_legacy:
            canonical_path.touch(exist_ok=True)
            continue

        merged_records = read_log_records(log_dir, log_type)
        if not merged_records:
            canonical_path.touch(exist_ok=True)
            continue
        with canonical_path.open("w", encoding="utf-8") as fp:
            for row in merged_records:
                fp.write(json.dumps(row, ensure_ascii=False) + "\n")

    _RUNTIME_MIGRATION_SIGNATURES[cache_key] = _log_files_signature(log_dir)


def _average_gap_factor(predictor: Any, numbers: list[int]) -> float:
    return round(sum(predictor._current_gap_factor(n) for n in numbers) / len(numbers), 6)


def _average_probability_weight(predictor: Any, numbers: list[int]) -> float:
    return round(sum(predictor._probability_only_weight(n) for n in numbers) / len(numbers), 6)


def _safe_json_loads(value: Any) -> list[Any]:
    if not value:
        return []
    try:
        loaded = json.loads(value)
        return loaded if isinstance(loaded, list) else []
    except Exception:
        return []


def _payload_value(payload_json: Any, key: str) -> Any:
    if not payload_json:
        return None
    try:
        payload = json.loads(payload_json)
    except Exception:
        return None
    return payload.get(key)


def load_combined_log_history(base_dir: Path | str) -> pd.DataFrame:
    base_dir = Path(base_dir)
    log_dir, _ = ensure_runtime_dirs(base_dir)
    db_path = ensure_log_database(log_dir)

    query = """
    SELECT
        record_uid,
        log_type,
        timestamp_utc AS timestamp,
        run_id,
        source_round,
        target_round,
        candidate_rank,
        score_metric,
        score,
        best_score,
        average_score,
        probability_score,
        input_order_score,
        avg_gap_factor,
        avg_probability_weight,
        numbers_json,
        input_numbers_json,
        best_order_json,
        matched_numbers_json,
        payload_json
    FROM log_records
    ORDER BY timestamp_utc DESC, log_type ASC, CASE WHEN candidate_rank IS NULL THEN 1 ELSE 0 END ASC, candidate_rank ASC
    """

    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(query, conn)
    finally:
        conn.close()

    if df.empty:
        return df

    df["file_name"] = df["log_type"].map(LOG_FILE_MAP)
    df["line_no"] = range(1, len(df) + 1)
    df["numbers"] = df["numbers_json"].map(_safe_json_loads)
    df["input_numbers"] = df["input_numbers_json"].map(_safe_json_loads)
    df["best_order"] = df["best_order_json"].map(_safe_json_loads)
    df["matched_numbers"] = df["matched_numbers_json"].map(_safe_json_loads)
    df["numbers_text"] = df["numbers"].map(lambda nums: ", ".join(f"{int(n):02d}" for n in nums) if nums else "-")
    df["input_numbers_text"] = df["input_numbers"].map(lambda nums: ", ".join(f"{int(n):02d}" for n in nums) if nums else "-")
    df["best_order_text"] = df["best_order"].map(lambda nums: ", ".join(f"{int(n):02d}" for n in nums) if nums else "-")
    df["matched_numbers_text"] = df["matched_numbers"].map(lambda nums: ", ".join(f"{int(n):02d}" for n in nums) if nums else "-")
    df["resolved_match_rows"] = df["payload_json"].map(lambda payload: _payload_value(payload, "resolved_match_rows"))
    df["time_series_rows"] = df["payload_json"].map(lambda payload: _payload_value(payload, "time_series_rows"))

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df["target_round"] = pd.to_numeric(df["target_round"], errors="coerce")
    df["source_round"] = pd.to_numeric(df["source_round"], errors="coerce")
    df["candidate_rank"] = pd.to_numeric(df["candidate_rank"], errors="coerce")
    df["score_metric"] = pd.to_numeric(df["score_metric"], errors="coerce")
    df["input_order_score"] = pd.to_numeric(df["input_order_score"], errors="coerce")
    df["avg_gap_factor"] = pd.to_numeric(df["avg_gap_factor"], errors="coerce")
    df["avg_probability_weight"] = pd.to_numeric(df["avg_probability_weight"], errors="coerce")

    valid_ts = df["timestamp"].notna()
    if valid_ts.any():
        ts_kst = df.loc[valid_ts, "timestamp"].dt.tz_convert("Asia/Seoul")
        df.loc[valid_ts, "timestamp_kst"] = ts_kst.dt.strftime("%Y-%m-%d %H:%M:%S")
        df.loc[valid_ts, "date_kst"] = ts_kst.dt.strftime("%Y-%m-%d")
        iso = ts_kst.dt.isocalendar()
        df.loc[valid_ts, "week_kst"] = iso["year"].astype(str) + "-W" + iso["week"].astype(str).str.zfill(2)
        df.loc[valid_ts, "month_kst"] = ts_kst.dt.strftime("%Y-%m")
    df["timestamp_kst"] = df.get("timestamp_kst", pd.Series(index=df.index, dtype="object")).fillna("-")
    df["date_kst"] = df.get("date_kst", pd.Series(index=df.index, dtype="object")).fillna("-")
    df["week_kst"] = df.get("week_kst", pd.Series(index=df.index, dtype="object")).fillna("-")
    df["month_kst"] = df.get("month_kst", pd.Series(index=df.index, dtype="object")).fillna("-")

    return df.reset_index(drop=True)


def build_log_status_table(base_dir: Path | str) -> pd.DataFrame:
    base_dir = Path(base_dir)
    log_dir, _ = ensure_runtime_dirs(base_dir)
    db_path = ensure_log_database(log_dir)

    conn = sqlite3.connect(db_path)
    try:
        stats_rows = conn.execute(
            """
            SELECT log_type, COUNT(*) AS records, MAX(timestamp_utc) AS last_saved_at
            FROM log_records
            GROUP BY log_type
            """
        ).fetchall()
    finally:
        conn.close()

    stats_map = {
        str(log_type): {"records": int(records or 0), "last_saved_at": last_saved_at or "-"}
        for log_type, records, last_saved_at in stats_rows
    }

    rows: list[dict[str, Any]] = []
    for log_type, file_name in LOG_FILE_MAP.items():
        file_path = log_dir / file_name
        stat_row = stats_map.get(log_type, {"records": 0, "last_saved_at": "-"})
        rows.append(
            {
                "log_type": log_type,
                "file_name": file_name,
                "records": stat_row["records"],
                "size_bytes": int(file_path.stat().st_size) if file_path.exists() else 0,
                "size_kb": round((file_path.stat().st_size / 1024.0), 3) if file_path.exists() else 0.0,
                "last_saved_at": stat_row["last_saved_at"],
                "path": f"logs/{file_name}",
            }
        )
    return pd.DataFrame(rows)


def log_prediction_results(
    *,
    base_dir: Path,
    excel_path: Path,
    predictor: Any,
    results: list[dict[str, Any]],
    log_type: str,
    simulation_count: int,
) -> list[dict[str, Any]]:
    if log_type not in {"prediction", "probability"}:
        raise ValueError(f"지원하지 않는 로그 타입: {log_type}")

    log_dir, _ = ensure_runtime_dirs(base_dir)
    context = get_round_context(excel_path)
    run_id = f"{log_type}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
    timestamp = utc_now_iso()
    records: list[dict[str, Any]] = []

    for rank, item in enumerate(results, start=1):
        sorted_numbers = [int(n) for n in item.get("sorted", [])]
        ordered_numbers = item.get("ordered")
        record = {
            "timestamp": timestamp,
            "run_id": run_id,
            "log_type": log_type,
            "candidate_rank": rank,
            "source_round": context["source_round"],
            "target_round": context["target_round"],
            "draw_count": context["draw_count"],
            "dataset_signature": context["dataset_signature"],
            "excel_modified_at": context["excel_modified_at"],
            "simulation_count": simulation_count,
            "numbers": sorted_numbers,
            "ordered_numbers": ordered_numbers,
            "score": float(item["score"]),
            "avg_gap_factor": _average_gap_factor(predictor, sorted_numbers),
            "avg_probability_weight": _average_probability_weight(predictor, sorted_numbers),
        }
        persist_log_record(log_dir, log_type, record)
        records.append(record)
    return records


def log_manual_score(
    *,
    base_dir: Path,
    excel_path: Path,
    predictor: Any,
    numbers: list[int],
    result: dict[str, Any],
) -> dict[str, Any]:
    log_dir, _ = ensure_runtime_dirs(base_dir)
    context = get_round_context(excel_path)
    sorted_numbers = [int(n) for n in sorted(numbers)]
    record = {
        "timestamp": utc_now_iso(),
        "run_id": f"manual-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}",
        "log_type": "manual",
        "source_round": context["source_round"],
        "target_round": context["target_round"],
        "draw_count": context["draw_count"],
        "dataset_signature": context["dataset_signature"],
        "excel_modified_at": context["excel_modified_at"],
        "numbers": sorted_numbers,
        "input_numbers": [int(n) for n in numbers],
        "best_order": [int(n) for n in result.get("best_order", sorted_numbers)],
        "best_score": float(result["best_score"]),
        "average_score": float(result["average_score"]),
        "input_order_score": float(result.get("input_order_score", result["best_score"])),
        "probability_score": float(result["probability_score"]),
        "avg_gap_factor": _average_gap_factor(predictor, sorted_numbers),
        "avg_probability_weight": _average_probability_weight(predictor, sorted_numbers),
    }
    persist_log_record(log_dir, "manual", record)
    return record
