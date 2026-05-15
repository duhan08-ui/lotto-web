"""
자동 로그 생성 모듈
평일(월~금) 저녁 6시에 달력 건수가 200건 미만이면 
패턴추천 100건 + 확률추천 100건을 자동으로 생성합니다.
"""

import json
import logging
import random
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from log_utils import persist_log_record, log_prediction_results

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_log_count(log_dir: Path) -> int:
    """달력에 표시되는 로그 건수 조회 (analysis 제외)"""
    db_path = log_dir / "lotto_history.db"
    
    if not db_path.exists():
        return 0
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # analysis 로그 타입 제외하고 카운트
        cursor.execute("""
            SELECT COUNT(*) FROM log_records 
            WHERE log_type IN ('prediction', 'probability', 'manual')
        """)
        
        count = cursor.fetchone()[0]
        conn.close()
        return count
    except Exception as e:
        logger.error(f"로그 건수 조회 실패: {e}")
        return 0


def generate_random_numbers(count: int = 6, max_num: int = 45) -> list[int]:
    """무작위 번호 생성"""
    return sorted(random.sample(range(1, max_num + 1), count))


def create_prediction_record(
    log_type: str,
    candidate_rank: int,
    source_round: int,
    target_round: int,
    simulation_count: int = 10000,
) -> dict[str, Any]:
    """예측 로그 레코드 생성"""
    numbers = generate_random_numbers()
    
    # 점수 생성 (0~100 범위, 평균 50 근처)
    score = round(random.gauss(50, 15), 2)
    score = max(0, min(100, score))  # 0~100 범위로 제한
    
    # gap factor와 확률 가중치 생성
    avg_gap_factor = round(random.uniform(0.3, 0.8), 6)
    avg_probability_weight = round(random.uniform(0.2, 0.9), 6)
    
    timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    run_id = f"{log_type}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
    
    return {
        "timestamp": timestamp,
        "run_id": run_id,
        "log_type": log_type,
        "candidate_rank": candidate_rank,
        "source_round": source_round,
        "target_round": target_round,
        "simulation_count": simulation_count,
        "numbers": numbers,
        "ordered_numbers": numbers,
        "score": score,
        "avg_gap_factor": avg_gap_factor,
        "avg_probability_weight": avg_probability_weight,
    }


def generate_auto_logs(
    project_dir: Path,
    excel_path: Path,
    target_count: int = 200,
    prediction_count: int = 100,
    probability_count: int = 100,
) -> bool:
    """자동 로그 생성 메인 함수 (실제 분석 기반)"""
    try:
        project_dir = Path(project_dir)
        excel_path = Path(excel_path)
        log_dir = project_dir / "logs"
        
        # 로그 디렉토리 생성
        log_dir.mkdir(parents=True, exist_ok=True)
        
        # 현재 로그 건수 확인 (로그 기록용)
        current_count = get_log_count(log_dir)
        logger.info(f"현재 로그 건수: {current_count}")
        
        # 매일 200개씩 신규 생성을 위해 target_count만큼 생성
        needed_count = target_count
        logger.info(f"신규 생성할 로그 건수: {needed_count}")
        
        # 순환 참조 방지를 위해 함수 내에서 임포트
        from app import LottoPredictor
        
        # 분석기 초기화
        predictor = LottoPredictor(str(excel_path))
        simulation_count = 5000 # 자동 생성용 시뮬레이션 횟수
        
        # 패턴추천 로그 생성 (실제 분석 기반)
        pred_to_gen = min(prediction_count, needed_count // 2)
        if pred_to_gen > 0:
            logger.info(f"패턴 추천 번호 {pred_to_gen}개 생성 중...")
            pattern_results = predictor.predict(sets=pred_to_gen, simulation_count=simulation_count)
            log_prediction_results(
                base_dir=project_dir,
                excel_path=excel_path,
                predictor=predictor,
                results=pattern_results,
                log_type="prediction",
                simulation_count=simulation_count
            )
        
        # 확률추천 로그 생성 (실제 분석 기반)
        prob_to_gen = min(probability_count, needed_count - pred_to_gen)
        if prob_to_gen > 0:
            logger.info(f"확률 추천 번호 {prob_to_gen}개 생성 중...")
            prob_results = predictor.predict_probability_only(sets=prob_to_gen, simulation_count=simulation_count)
            log_prediction_results(
                base_dir=project_dir,
                excel_path=excel_path,
                predictor=predictor,
                results=prob_results,
                log_type="probability",
                simulation_count=simulation_count
            )
        
        total_generated = pred_to_gen + prob_to_gen
        logger.info(f"자동 로그 생성 완료: 총 {total_generated}건 (패턴 {pred_to_gen}, 확률 {prob_to_gen})")
        
        return True
        
    except Exception as e:
        logger.error(f"자동 로그 생성 실패: {e}")
        return False


if __name__ == "__main__":
    # 테스트 실행
    project_dir = Path(__file__).resolve().parent
    excel_path = project_dir / "lotto.xlsx"
    
    success = generate_auto_logs(project_dir, excel_path)
    print(f"자동 로그 생성 {'성공' if success else '실패'}")
