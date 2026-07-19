from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone, timedelta
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
    "top5": "top5_log.jsonl",
}

# 히스토리(SQLite) 로드 시 가져올 최대 행 수.
# 하루 약 325건씩 쌓이므로 120,000 이면 약 1년치까지 커버한다. (캘린더가 4월부터 보이도록)
# 데이터가 수십만 건으로 커져 느려지면, 이 값을 낮추거나 '선택한 날짜만 조회'식으로 바꾸는 것을 검토.
HISTORY_LOAD_ROW_LIMIT = 120000

LEGACY_LOG_FILE_MAP = {
    "prediction": ["번호추천로그.jsonl", "#Ubc88#Ud638#Ucd94#Ucc9c#Ub85c#Uadf8.jsonl", "패턴분석로그.jsonl", "패턴 분석 로그.jsonl"],
    "probability": ["확률분석로그.jsonl", "#Ud655#Ub960#Ubd84#Uc11d#Ub85c#Uadf8.jsonl"],
    "manual": ["수동번호점수로그.jsonl", "#Uc218#Ub3d9#Ubc88#Ud638#Uc810#Uc218#Ub85c#Uadf8.jsonl"],
    "analysis": ["분석요약로그.jsonl", "#Ubd84#Uc11d#Uc694#Uc57d#Ub85c#Uadf8.jsonl"],
}

APP_STATE_FILE = "app_state.json"
LOG_DB_FILE = "lotto_history.db"
# [성능] 마지막으로 원격과 맞춘 로그의 최신 timestamp_utc 를 저장하는 파일.
# 콜드스타트 때 원격 최신 timestamp 와 같으면 전체 다운로드/재빌드를 건너뛴다.
LOG_SYNC_STATE_FILE = ".log_sync_state.json"
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

# [성능/UX] 로컬 우선 렌더용 플래그. True면 원격 부트스트랩(네트워크+DB 재빌드)을
# 건너뛰고 로컬 데이터로 즉시 화면을 그린다. 첫 세션 렌더가 끝난 뒤 앱이 이 값을
# False 로 바꾸고 실제 동기화를 수행한다(=화면을 막지 않는 "백그라운드" 동기화 효과).
_DEFER_REMOTE_BOOTSTRAP: bool = False


def set_defer_remote_bootstrap(flag: bool) -> None:
    """원격 부트스트랩 지연 여부를 설정한다(로컬 우선 렌더)."""
    global _DEFER_REMOTE_BOOTSTRAP
    _DEFER_REMOTE_BOOTSTRAP = bool(flag)

# 마지막으로 원격(Supabase) 동기화를 완료한 시각(monotonic) 캐시.
_RUNTIME_REMOTE_LAST_SYNC: dict[str, float] = {}
# 원격 재동기화 최소 간격(초). 이 시간 안에는 재fetch/DB 재빌드를 건너뛴다.
REMOTE_RESYNC_MIN_INTERVAL_SEC = 1800.0  # [성능] 90초→30분. 로그분석 진입 후 세션 내 잦은
# 재동기화(Supabase fetch 2회 + SQLite 전체 재빌드 + 캐시 재계산, 매번 30초~1분)를 막아
# 클릭이 즉시 반응하게 한다. 새 원격 데이터는 다음 앱 재시작/소스 갱신 시 반영된다.


def invalidate_remote_bootstrap_if_stale(
    base_dir: "Path | str",
    min_interval_sec: float = REMOTE_RESYNC_MIN_INTERVAL_SEC,
) -> None:
    """마지막 원격 동기화로부터 min_interval_sec 이상 지났을 때만 재동기화를 허용한다.

    기존에는 매 rerun(캘린더 날짜 클릭·탭 전환 포함)마다 BOOTSTRAP_DONE 캐시를
    무조건 비워서, Supabase 네트워크 fetch 2회 + SQLite DB 전체 재빌드가 반복돼
    화면이 멈추듯 느려졌다. 일정 간격 안에서는 캐시를 비우지 않아 재동기화를 막는다.
    """
    log_dir = Path(base_dir) / "logs"
    cache_key = str(log_dir.resolve())
    now = time.monotonic()
    last = _RUNTIME_REMOTE_LAST_SYNC.get(cache_key)
    if last is None or (now - last) >= min_interval_sec:
        _RUNTIME_REMOTE_BOOTSTRAP_DONE.discard(cache_key)


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
        "unlock_granted": False,
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
    # [성능] 재시도 3→2, 타임아웃 15→10초. 정상 응답은 1초 미만이라 영향 없고,
    # 네트워크 불가/cold-start 시 최악 대기(기존 ~45초/호출)를 ~20초/호출로 단축한다.
    for attempt in range(2):
        try:
            response = requests.request(
                method,
                url,
                headers=_supabase_headers(config, upsert=method.upper() in {"POST", "PATCH"}),
                params=params,
                json=json_payload,
                timeout=10,
            )
            if response.status_code in {200, 201, 204, 206}:
                return response
            if response.status_code in {429, 500, 502, 503, 504} and attempt < 1:
                time.sleep(0.6 * (attempt + 1))
                continue
            response.raise_for_status()
            return response
        except requests.RequestException as exc:  # pragma: no cover - network failure path
            last_error = exc
            if attempt >= 1:
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
    row = [_supabase_row_from_payload(payload)]
    # record_uid 기준 병합(중복 누적 방지). 테이블에 record_uid UNIQUE/PK 제약이
    # 있어야 동작하므로, 제약이 아직 없으면 일반 저장으로 안전하게 폴백한다.
    try:
        _supabase_request("POST", url, config=config,
                          params={"on_conflict": "record_uid"}, json_payload=row)
    except Exception:
        try:
            _supabase_request("POST", url, config=config, json_payload=row)
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


def _log_sync_state_path(log_dir: Path) -> Path:
    return log_dir / LOG_SYNC_STATE_FILE


def _load_log_sync_ts(log_dir: Path) -> str | None:
    """마지막으로 원격과 동기화한 로그의 최신 timestamp_utc 를 읽는다."""
    try:
        raw = _log_sync_state_path(log_dir).read_text(encoding="utf-8")
        data = json.loads(raw)
        ts = data.get("last_log_ts")
        return str(ts) if ts else None
    except (OSError, json.JSONDecodeError, AttributeError):
        return None


def _save_log_sync_ts(log_dir: Path, ts: str | None) -> None:
    if not ts:
        return
    try:
        _log_sync_state_path(log_dir).write_text(
            json.dumps({"last_log_ts": str(ts)}, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass


def _remote_max_log_ts(base_dir: Path) -> str | None:
    """원격 로그 테이블의 최신 timestamp_utc 1건만 싸게 조회한다.

    오류/불확실 시 None 을 반환하며, 호출부는 None 이면 전체 재로드로 폴백한다.
    """
    config = _persistence_config(str(base_dir.resolve()))
    if not config["enabled"]:
        return None
    url = f"{config['url']}/rest/v1/{config['log_table']}"
    try:
        response = _supabase_request(
            "GET",
            url,
            config=config,
            params={
                "select": "timestamp_utc",
                "order": "timestamp_utc.desc.nullslast",
                "limit": 1,
            },
        )
        rows = response.json()
    except Exception:
        return None
    if not rows:
        return None
    ts = rows[0].get("timestamp_utc")
    return str(ts) if ts else None


def _should_skip_full_log_sync(local_ready: bool, stored_ts: str | None, remote_ts: str | None) -> bool:
    """로컬이 준비돼 있고, 저장된 최신 ts 가 원격 최신 ts 와 같으면 전체 재로드를 건너뛴다.

    remote_ts 가 None(조회 실패/빈 테이블)이거나 stored_ts 가 없으면 절대 건너뛰지 않는다
    → 불확실할 때는 항상 전체 재로드(데이터 유실 위험 0).
    """
    return bool(local_ready and remote_ts and stored_ts and stored_ts == remote_ts)


def bootstrap_remote_runtime_if_needed(base_dir: Path | str) -> None:
    # [성능/UX] 로컬 우선 렌더 중에는 원격 동기화를 건너뛴다(화면 즉시 표시).
    # done 표시를 하지 않으므로, 지연 해제 후 호출하면 정상적으로 동기화된다.
    if _DEFER_REMOTE_BOOTSTRAP:
        return
    base_dir = Path(base_dir)
    config = _persistence_config(str(base_dir.resolve()))
    if not config["enabled"]:
        return

    log_dir = base_dir / "logs"
    cache_key = str(log_dir.resolve())
    if cache_key in _RUNTIME_REMOTE_BOOTSTRAP_DONE:
        return

    log_dir.mkdir(parents=True, exist_ok=True)

    # [성능/안정성] 원격 동기화 실패(네트워크 불가/타임아웃/쿨다운)에도 DONE/LAST_SYNC 를
    # 반드시 기록한다. 그렇지 않으면 실패 시 매 rerun(캘린더 날짜 클릭 등)마다 수십초~2분
    # 짜리 네트워크 재시도가 반복되어 화면이 멈춘다. 실패 시엔 로컬 데이터로 진행하고,
    # 다음 재동기화는 REMOTE_RESYNC_MIN_INTERVAL_SEC(30분) 뒤에 한 번만 다시 시도한다.
    try:
        remote_state = _load_remote_app_state(base_dir)

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

        # [성능] 원격 로그가 지난 동기화 이후 바뀌지 않았으면(최신 timestamp 동일)
        # 전체 다운로드+DB 재빌드를 통째로 건너뛴다. 불확실하면 전체 재로드로 폴백.
        db_path = _log_db_path(log_dir)
        local_ready = db_path.exists() and any(
            (log_dir / fname).exists() for fname in LOG_FILE_MAP.values()
        )
        remote_ts = _remote_max_log_ts(base_dir)
        stored_ts = _load_log_sync_ts(log_dir)
        if _should_skip_full_log_sync(local_ready, stored_ts, remote_ts):
            pass  # 로컬이 이미 원격 최신 상태 → 재다운로드/재빌드 자체를 생략(전체 다운로드 안 함)
        else:
            remote_payloads = _fetch_remote_log_payloads(base_dir)
            if remote_payloads:
                _write_grouped_jsonl_from_payloads(log_dir, remote_payloads)
                _purge_db_files(db_path)
                ensure_log_database(log_dir)
                _upsert_payloads_to_sqlite(db_path, remote_payloads)
                _set_runtime_sqlite_signature(log_dir)
                _save_log_sync_ts(log_dir, remote_ts)
    except Exception as exc:  # 네트워크/원격 실패 → 로컬 데이터로 진행
        import logging as _logging
        _logging.getLogger(__name__).warning(f"원격 동기화 실패, 로컬 데이터로 진행합니다: {exc}")
    finally:
        # 성공/실패와 무관하게 기록 → 매 rerun 재시도 폭주 방지(30분 뒤 1회만 재시도)
        _RUNTIME_REMOTE_BOOTSTRAP_DONE.add(cache_key)
        _RUNTIME_REMOTE_LAST_SYNC[cache_key] = time.monotonic()


def remote_persistence_enabled(base_dir: Path | str) -> bool:
    """Supabase 원격 영속화가 설정되어 있는지 여부.
    (부트스트랩이 원격 상태를 실제로 당겨올 수 있는 환경인지 판단할 때 사용)"""
    try:
        return bool(_persistence_config(str(Path(base_dir).resolve()))["enabled"])
    except Exception:
        return False


def reset_runtime_persistence_caches() -> None:
    _RUNTIME_REMOTE_BOOTSTRAP_DONE.clear()
    _RUNTIME_REMOTE_LAST_SYNC.clear()
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
    state["unlock_granted"] = bool(loaded.get("unlock_granted", False))
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
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except (OSError, PermissionError):
        return
    for file_name in LOG_FILE_MAP.values():
        try:
            (log_dir / file_name).touch(exist_ok=True)
        except (OSError, PermissionError):
            pass


def _log_db_path(log_dir: Path) -> Path:
    return log_dir / LOG_DB_FILE


def _connect_log_db(path, **kwargs):
    """SQLite 연결 헬퍼. mmap 을 끈다(PRAGMA mmap_size=0).

    SQLite 는 기본적으로 DB 파일을 메모리 매핑(mmap)해서 읽는데, 파일이
    손상(malformed)된 경우 mmap 페이지 접근이 곧바로 Bus error(SIGBUS) 네이티브
    크래시를 일으킨다(try/except 로 못 잡음). mmap 을 끄면 손상 시 SIGBUS 대신
    sqlite3.DatabaseError('database disk image is malformed') 예외가 발생해
    파이썬 레벨에서 잡아 복구할 수 있다.
    """
    conn = sqlite3.connect(path, **kwargs)
    try:
        conn.execute("PRAGMA mmap_size=0")
    except Exception:
        pass
    return conn


def _purge_db_files(db_path) -> None:
    """손상된 SQLite DB 와 사이드카(-wal/-shm/-journal)를 함께 삭제한다.

    .db 만 지우고 -wal/-shm 을 남기면, 새로 만든 DB 에 stale WAL 이 적용되며
    곧바로 다시 malformed 로 인식되는 문제가 있어 사이드카까지 모두 제거한다.
    """
    db_path = Path(db_path)
    for suffix in ("", "-wal", "-shm", "-journal"):
        target = Path(str(db_path) + suffix)
        try:
            if target.exists():
                target.unlink()
        except Exception:
            pass


def ensure_log_database(log_dir: Path) -> Path:
    db_path = _log_db_path(log_dir)
    
    def _create_db():
        conn = _connect_log_db(db_path)
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
    
    try:
        _create_db()
    except sqlite3.OperationalError as e:
        error_msg = str(e).lower()
        # 디스크 I/O 에러 또는 손상된 DB 파일 처리
        if any(keyword in error_msg for keyword in ['disk', 'i/o', 'readonly', 'permission', 'corrupt', 'malformed']):
            _purge_db_files(db_path)
            _create_db()
        else:
            raise
    
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
    
    # 데이터베이스 파일 손상 여부 확인 및 복구 로직
    def try_upsert(path: Path, data: list[dict[str, Any]], retry: bool = True):
        conn = None
        try:
            conn = _connect_log_db(path, timeout=30.0)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executemany(SQLITE_UPSERT, [_sqlite_row_from_payload(payload) for payload in data])
            conn.commit()
        except (sqlite3.DatabaseError, sqlite3.OperationalError) as e:
            error_msg = str(e).lower()
            if conn:
                try:
                    conn.close()
                except:
                    pass
            
            # DB 파일 손상(malformed) 또는 읽기 전용 에러 발생 시 처리
            if retry and ("malformed" in error_msg or "readonly" in error_msg or "disk image" in error_msg):
                _purge_db_files(path)  # 손상된 DB + WAL/SHM 사이드카까지 정리
                # 재시도 (파일이 삭제되었으므로 ensure_log_database가 새로 생성할 것임)
                ensure_log_database(path.parent)
                try_upsert(path, data, retry=False)
            else:
                # 더 이상 복구 불가 시 에러 로그만 남기고 중단 (시스템 중단 방지)
                print(f"CRITICAL SQLITE ERROR: {e}")
        finally:
            if conn:
                try:
                    conn.close()
                except:
                    pass

    try_upsert(db_path, payloads)


def persist_log_record(log_dir: Path, log_type: str, record: dict[str, Any]) -> None:
    payload = _prepare_record_for_persistence(record, log_type)
    try:
        append_jsonl(log_dir / LOG_FILE_MAP[log_type], payload)
    except (OSError, PermissionError):
        pass

    try:
        db_path = ensure_log_database(log_dir)
        _upsert_payloads_to_sqlite(db_path, [payload])
        _set_runtime_sqlite_signature(log_dir)
    except Exception:
        pass
    _upsert_remote_log_payload(log_dir.parent, payload)


def persist_top5_log_record(
    base_dir: Path | str,
    log_type: str,          # "prediction" | "probability" | "manual"
    candidate_rank: int,
    numbers: list[int],
    score: float,
    source_round: int,
    target_round: int,
    created_date_kst: str,  # "YYYY-MM-DD"
    extra: dict | None = None,
) -> None:
    """매일 TOP5 전용 로그 (top5_log.jsonl) 에 1건 추가."""
    base_dir = Path(base_dir)
    log_dir, _ = ensure_runtime_dirs(base_dir)
    payload: dict[str, Any] = {
        "timestamp": utc_now_iso(),
        "log_type": "top5",
        "top5_type": log_type,
        "candidate_rank": candidate_rank,
        "numbers": numbers,
        "score": score,
        "source_round": source_round,
        "target_round": target_round,
        "created_date_kst": created_date_kst,
    }
    if extra:
        payload.update(extra)
    try:
        append_jsonl(log_dir / LOG_FILE_MAP["top5"], payload)
    except Exception as e:
        import logging as _logging
        _logging.getLogger(__name__).warning("top5 로그 저장 실패: %s", e)
    _upsert_remote_log_payload(base_dir, payload)


def load_top5_log(base_dir: Path | str) -> list[dict]:
    """top5_log.jsonl 전체 로드. 없으면 빈 리스트."""
    base_dir = Path(base_dir)
    log_dir = base_dir / "logs"
    path = log_dir / LOG_FILE_MAP["top5"]
    records: list[dict] = []
    if not path.exists():
        return records
    try:
        with open(path, "r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        pass
    return records


def backfill_log_database(log_dir: Path) -> None:
    sync_log_database_if_needed(log_dir, force=True)


def persist_log_record_only_sqlite(log_dir: Path, log_type: str, record: dict[str, Any]) -> None:
    payload = _prepare_record_for_persistence(record, log_type)
    db_path = ensure_log_database(log_dir)
    _upsert_payloads_to_sqlite(db_path, [payload])


def _sqlite_record_count(db_path: Path) -> int:
    if not db_path.exists():
        return 0
    conn = _connect_log_db(db_path)
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
    try:
        migrate_legacy_log_files(log_dir)
    except Exception:
        pass
    try:
        ensure_log_database(log_dir)
    except Exception:
        pass
    try:
        sync_log_database_if_needed(log_dir)
    except Exception:
        pass
    try:
        report_dir.mkdir(parents=True, exist_ok=True)
    except (OSError, PermissionError):
        pass
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

    now = datetime.now(KST)

    # 1. 엑셀 기준 마지막 회차
    target_round = (source_round + 1) if source_round is not None else None

    # 2. [v3.4 FIX] 날짜 기반 회차 보정
    #    기존 로직은 '토요일 21시 이후 또는 일요일'에만 +1 하는 요일 꼼수라서,
    #    lotto.xlsx가 한 주 이상 갱신되지 않으면 평일에는 회차가 1 이상 어긋났음.
    #    (예: 6/6(토) 추첨분 미반영 상태로 수요일 실행 → 1227로 잘못 계산,
    #     반면 일요일에 실행된 로그는 1228로 기록 → AI 추천이 대시보드에서 필터링됨)
    #    수정: 마지막으로 기록된 추첨일 이후 '토요일 21:00 KST' 추첨이
    #    몇 번 지났는지 세어 그만큼 회차를 가산 → 엑셀이 아무리 오래돼도
    #    GHA/Streamlit/로컬 어디서든 동일한 회차가 계산됨.
    if target_round is not None and not df.empty and "추첨일" in df.columns:
        try:
            idx = pd.to_numeric(df["회차"], errors="coerce").idxmax()
            latest_draw_date = pd.to_datetime(df.loc[idx]["추첨일"]).date()
            # 기록된 추첨일 다음 날부터 첫 토요일을 찾고,
            # 그 토요일 21:00부터 매주 단위로 현재까지 지난 추첨 횟수를 센다
            d = latest_draw_date + timedelta(days=1)
            while d.weekday() != 5:  # 5 = 토요일
                d += timedelta(days=1)
            draw_dt = datetime(d.year, d.month, d.day, 21, 0, tzinfo=KST)
            passed = 0
            while draw_dt <= now:
                passed += 1
                draw_dt += timedelta(days=7)
            target_round += passed
        except Exception:
            # 추첨일 파싱 실패 시 보정 없이 source+1 유지 (보수적 처리)
            pass
    return {
        "source_round": source_round,
        "target_round": target_round,
        "draw_count": int(draw_count),
        "dataset_signature": build_dataset_signature(excel_path),
        "excel_modified_at": datetime.fromtimestamp(excel_path.stat().st_mtime, tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat(),
    }


def append_jsonl(file_path: Path, payload: dict[str, Any]) -> None:
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with file_path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except (OSError, PermissionError) as exc:
        import logging as _logging
        _logging.getLogger(__name__).warning("append_jsonl 쓰기 실패 (%s): %s", file_path, exc)


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

    # [성능] 예전엔 호출할 때마다 BOOTSTRAP_DONE 캐시를 무조건 비워 매 rerun마다
    # Supabase 재fetch + DB 재빌드가 일어나 화면이 멈추듯 느려졌다.
    # 이제 최소 간격(REMOTE_RESYNC_MIN_INTERVAL_SEC)이 지났을 때만 재동기화를 허용한다.
    # GHA가 저장한 최신 데이터는 그 간격 뒤(또는 새로고침 시) 자동 반영된다.
    invalidate_remote_bootstrap_if_stale(base_dir)

    log_dir, _ = ensure_runtime_dirs(base_dir)

    # ── SQLite에서 읽기 시도 ───────────────────────────────────────────────
    df = _load_history_from_sqlite(log_dir)

    # ── DB가 비어있으면 JSONL 파일에서 직접 읽어 DB 재동기화 ─────────────
    if df.empty:
        try:
            sync_log_database_if_needed(log_dir, force=True)
            df = _load_history_from_sqlite(log_dir)
        except Exception:
            pass

    # ── 그래도 비어있으면 JSONL 파일에서 직접 DataFrame 구성 ─────────────
    if df.empty:
        df = _load_history_from_jsonl_fallback(log_dir)

    if df.empty:
        return df

    return _postprocess_history_df(df)


def _load_history_from_sqlite(log_dir: Path) -> pd.DataFrame:
    """SQLite DB에서 로그 레코드를 읽어 raw DataFrame 반환."""
    try:
        db_path = ensure_log_database(log_dir)
    except Exception:
        return pd.DataFrame()

    # 하루 약 325건(자동 300 + TOP5 + AI)씩 쌓이므로, 예전 10,000 상한은 약 30일치(=최근
    # 한 달)만 남아 캘린더에 4·5월 로그가 안 보였다. 누적 데이터를 모두 보이도록 상향한다.
    # (로드는 _load_enriched_history_cached 로 캐시되어 파일 변경 시에만 재계산됨)
    history_row_limit = HISTORY_LOAD_ROW_LIMIT
    query = f"""
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
        matched_numbers_json
        -- [성능] payload_json(행당 최대 수백B, 12만행이면 수십MB)은 로드 후
        -- 어떤 뷰/분석도 읽지 않으므로 SELECT에서 제외해 IO·메모리를 절감한다.
    FROM log_records
    ORDER BY timestamp_utc DESC, log_type ASC, CASE WHEN candidate_rank IS NULL THEN 1 ELSE 0 END ASC, candidate_rank ASC
    LIMIT {int(history_row_limit)}
    """
    try:
        conn = _connect_log_db(db_path)
        try:
            df = pd.read_sql_query(query, conn)
        finally:
            conn.close()
        return df
    except Exception as e:
        # 손상(malformed/disk image) 감지 시 DB+사이드카를 정리해 다음 로드에서
        # JSONL/원격으로부터 깨끗이 재생성되게 한다. (mmap 을 꺼서 여기서 SIGBUS 대신
        # 잡히는 예외가 발생하므로 복구가 가능하다)
        msg = str(e).lower()
        if "malformed" in msg or "disk image" in msg or "corrupt" in msg:
            _purge_db_files(db_path)
        return pd.DataFrame()


def _load_history_from_jsonl_fallback(log_dir: Path) -> pd.DataFrame:
    """JSONL 파일에서 직접 DataFrame을 구성하는 fallback."""
    records: list[dict] = []
    for log_type in LOG_FILE_MAP:
        for row in read_log_records(log_dir, log_type):
            row.setdefault("log_type", log_type)
            records.append(row)
    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)

    # SQLite 컬럼명에 맞춰 정규화
    col_map = {
        "timestamp": "timestamp",
        "generated_at_utc": "timestamp",
        "logged_at_utc": "timestamp",
    }
    for src, dst in col_map.items():
        if src in df.columns and dst not in df.columns:
            df[dst] = df[src]

    # numbers 필드 JSON 직렬화
    for col, json_col in [
        ("numbers", "numbers_json"),
        ("input_numbers", "input_numbers_json"),
        ("best_order", "best_order_json"),
        ("matched_numbers", "matched_numbers_json"),
    ]:
        if json_col not in df.columns:
            if col in df.columns:
                df[json_col] = df[col].map(
                    lambda v: json.dumps(v, ensure_ascii=False) if isinstance(v, list) else "[]"
                )
            else:
                df[json_col] = "[]"

    if "payload_json" not in df.columns:
        df["payload_json"] = df.apply(
            lambda r: json.dumps({k: v for k, v in r.items() if k not in df.columns}, ensure_ascii=False),
            axis=1,
        )

    return df


def _postprocess_history_df(df: pd.DataFrame) -> pd.DataFrame:
    """load_combined_log_history 공통 후처리."""
    df = df.copy()
    df["file_name"] = df["log_type"].map(LOG_FILE_MAP)
    df["line_no"] = range(1, len(df) + 1)
    df["numbers"] = df["numbers_json"].map(_safe_json_loads)
    df["input_numbers"] = df["input_numbers_json"].map(_safe_json_loads)
    df["best_order"] = df["best_order_json"].map(_safe_json_loads)
    df["matched_numbers"] = df["matched_numbers_json"].map(_safe_json_loads)
    df["numbers_text"] = df["numbers"].map(lambda nums: ", ".join(f"{int(n):02d}" for n in nums) if nums else "-")
    df["input_numbers_text"] = df["input_numbers"].map(lambda nums: ", ".join(f"{int(n):02d}" for n in nums) if nums else "-")
    df["matched_numbers_text"] = df["matched_numbers"].map(lambda nums: ", ".join(f"{int(n):02d}" for n in nums) if nums else "-")
    # [성능] best_order_text / resolved_match_rows / time_series_rows 컬럼은
    # 어디서도 읽지 않아(요약 수치는 analysis.py에서 별도 계산) 제거했다.
    # 특히 payload_json(가장 큰 컬럼)을 행마다 2번 파싱하던 죽은 작업을 없앤다.

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

    stats_map: dict[str, dict] = {}
    try:
        db_path = ensure_log_database(log_dir)
        conn = _connect_log_db(db_path)
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
    except Exception:
        # DB 접근 실패 시 JSONL 파일에서 카운트
        for log_type in LOG_FILE_MAP:
            records = read_log_records(log_dir, log_type)
            stats_map[log_type] = {"records": len(records), "last_saved_at": "-"}

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
    candidate_rank: int | None = None,
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
    # 인기조합 회피 점수(0~100, 높을수록 비인기=배당 분할 유리) 부착.
    # 확률을 바꾸지 않고 '당첨 시 몫'에만 관련된 참고 지표.
    try:
        from popularity_score import score_breakdown as _pop_breakdown
        _bd = _pop_breakdown(sorted_numbers)
        record["unpopularity_score"] = _bd["unpopularity_score"]
        record["popularity_breakdown"] = _bd["penalties"]
    except Exception:
        pass
    if candidate_rank is not None:
        record["candidate_rank"] = int(candidate_rank)
    persist_log_record(log_dir, "manual", record)
    return record
