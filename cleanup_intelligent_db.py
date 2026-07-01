#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cleanup_intelligent_db.py - AI(is_intelligent) 중복 레코드 정리 (1회성/유지보수용)

배경
----
AI 지능형 추천(run_analysis)은 하루에 여러 번 실행될 수 있다
(LogWatcher 파일 감지 + 09시 스케줄러 + GHA). 과거 버전은 매 실행마다
record_uid 가 매번 달라져서 같은 (회차, 순위)의 is_intelligent 레코드가
SQLite DB(lotto_history.db)에 무한 누적됐다.

대시보드/달력의 "추출 건수"는 JSONL 이 아니라 DB 를 기준으로 집계하므로,
하루 추출량이 의도한 300건(패턴100+확률100+나혼자100)을 훨씬 넘는 것처럼
(예: 평일 635 / 일요일 945) 보였다.

이 스크립트는 (log_type, target_round, candidate_rank) 조합마다
is_intelligent 레코드를 1건만 남기고 나머지 중복을 삭제한다.
가능하면 고정 uid(현재 코드가 쓰는 값)를 우선 보존한다.

사용
----
    python3 cleanup_intelligent_db.py            # logs/lotto_history.db 정리
    python3 cleanup_intelligent_db.py --dry-run  # 삭제 없이 현황만 출력
"""

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
DB_PATH = PROJECT_DIR / "logs" / "lotto_history.db"
INTELLIGENT_TYPES = ("prediction", "probability", "manual")


def _fixed_uid(target_round, rank, log_type) -> str:
    return hashlib.sha256(
        f"intelligent|{log_type}|{target_round}|{rank}".encode()
    ).hexdigest()


def _is_intelligent(payload_json: str) -> bool:
    if not payload_json:
        return False
    try:
        return bool(json.loads(payload_json).get("is_intelligent"))
    except Exception:
        # JSON 파싱 실패 시 문자열 매칭으로 보수적 판정
        normalized = payload_json.replace(" ", "").replace("\t", "")
        return '"is_intelligent":true' in normalized


def cleanup(db_path: Path, dry_run: bool = False) -> dict:
    if not db_path.exists():
        print(f"[건너뜀] DB 파일 없음: {db_path}")
        return {"deleted": 0, "kept": 0}

    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT record_uid, log_type, target_round, candidate_rank, "
            "timestamp_utc, payload_json FROM log_records"
        )
        rows = cur.fetchall()

        # (log_type, target_round, candidate_rank) -> [(uid, timestamp), ...]
        groups: dict = defaultdict(list)
        for uid, log_type, tr, rank, ts, payload in rows:
            if log_type not in INTELLIGENT_TYPES:
                continue
            if not _is_intelligent(payload):
                continue
            groups[(log_type, tr, rank)].append((uid, ts or ""))

        to_delete: list[str] = []
        kept = 0
        for (log_type, tr, rank), members in groups.items():
            if len(members) <= 1:
                kept += len(members)
                continue
            preferred = _fixed_uid(tr, rank, log_type)
            uids = {uid for uid, _ in members}
            if preferred in uids:
                keep_uid = preferred
            else:
                # 고정 uid 가 없으면 가장 최근(timestamp) 1건 보존
                keep_uid = max(members, key=lambda m: m[1])[0]
            kept += 1
            to_delete.extend(uid for uid, _ in members if uid != keep_uid)

        print(f"DB: {db_path}")
        print(f"  is_intelligent 그룹 수 (회차·순위·유형): {len(groups)}")
        print(f"  보존: {kept}건  /  삭제 대상(중복): {len(to_delete)}건")

        if dry_run:
            print("  [dry-run] 실제 삭제는 수행하지 않았습니다.")
        elif to_delete:
            cur.executemany(
                "DELETE FROM log_records WHERE record_uid = ?",
                [(uid,) for uid in to_delete],
            )
            conn.commit()
            print(f"  ✓ {len(to_delete)}건 삭제 완료")
        else:
            print("  중복 없음 - 변경 사항 없습니다.")

        return {"deleted": 0 if dry_run else len(to_delete), "kept": kept}
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="AI 중복 레코드 정리")
    parser.add_argument("--db", default=str(DB_PATH), help="lotto_history.db 경로")
    parser.add_argument("--dry-run", action="store_true", help="삭제 없이 현황만 출력")
    args = parser.parse_args()
    result = cleanup(Path(args.db), dry_run=args.dry_run)
    return 0 if result is not None else 1


if __name__ == "__main__":
    sys.exit(main())
