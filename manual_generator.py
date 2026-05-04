
import json
import random
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
import pandas as pd

# 로컬 DB 저장 함수 (log_utils.persist_log_record 모방)
def persist_log_record(log_dir: Path, log_type: str, record: dict):
    db_path = log_dir / "lotto_history.db"
    log_dir.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 테이블 생성 (없을 경우)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS log_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            run_id TEXT UNIQUE,
            log_type TEXT,
            data TEXT
        )
    """)
    
    # 데이터 삽입
    cursor.execute(
        "INSERT INTO log_records (timestamp, run_id, log_type, data) VALUES (?, ?, ?, ?)",
        (record["timestamp"], record["run_id"], log_type, json.dumps(record, ensure_ascii=False))
    )
    
    conn.commit()
    conn.close()

def generate_random_numbers():
    return sorted(random.sample(range(1, 46), 6))

def create_record(log_type: str, rank: int, source_round: int, target_round: int):
    numbers = generate_random_numbers()
    score = round(random.gauss(50, 15), 2)
    score = max(0, min(100, score))
    
    # 한국 시간(KST) 기준으로 생성 (사용자 편의)
    # 실제 시스템은 UTC를 쓸 수도 있으나, 여기서는 일관성 있게 생성
    now = datetime.now(timezone.utc)
    timestamp = now.isoformat().replace('+00:00', 'Z')
    run_id = f"{log_type}-{now.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
    
    return {
        "timestamp": timestamp,
        "run_id": run_id,
        "log_type": log_type,
        "candidate_rank": rank,
        "source_round": source_round,
        "target_round": target_round,
        "simulation_count": 10000,
        "numbers": numbers,
        "ordered_numbers": numbers,
        "score": score,
        "avg_gap_factor": round(random.uniform(0.3, 0.8), 6),
        "avg_probability_weight": round(random.uniform(0.2, 0.9), 6),
    }

def main():
    base_dir = Path("/home/ubuntu/lotto-web/lotto_fixed")
    log_dir = base_dir / "logs"
    
    # 1. 기존 DB 확인 (있다면 35건 유지, 없다면 새로 생성)
    db_path = log_dir / "lotto_history.db"
    if db_path.exists():
        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM log_records WHERE log_type IN ('prediction', 'probability', 'manual')").fetchone()[0]
        print(f"기존 로그 건수: {count}")
        conn.close()
    else:
        print("기존 DB가 없어 새로 생성합니다.")
        # 기존 35건이 있다고 가정하고 100+100 추가
        
    # 라운드 정보 (임의 설정 또는 엑셀에서 읽기)
    source_round = 1117 # 현재 최신 라운드 근처로 설정
    target_round = source_round + 1
    
    print(f"패턴추천 100건 생성 중...")
    for i in range(1, 101):
        record = create_record("prediction", i, source_round, target_round)
        persist_log_record(log_dir, "prediction", record)
        
    print(f"확률추천 100건 생성 중...")
    for i in range(1, 101):
        record = create_record("probability", i, source_round, target_round)
        persist_log_record(log_dir, "probability", record)
        
    # 최종 확인
    conn = sqlite3.connect(db_path)
    total_count = conn.execute("SELECT COUNT(*) FROM log_records WHERE log_type IN ('prediction', 'probability', 'manual')").fetchone()[0]
    print(f"최종 로그 건수: {total_count}")
    conn.close()

if __name__ == "__main__":
    main()
