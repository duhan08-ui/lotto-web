import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd

# 프로젝트 경로 설정
PROJECT_DIR = Path(__file__).resolve().parent
sys.path.append(str(PROJECT_DIR))

# 기존 모듈 임포트
from app import LottoPredictor
from log_utils import ensure_runtime_dirs, log_prediction_results, KST
from update_lotto import update_excel
from analysis import analyze_logs

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(PROJECT_DIR / "logs" / "ai_scheduler.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("AI_Scheduler")

def run_ai_analysis(use_manus=False):
    """AI 분석 및 추천 번호 생성 실행 (저녁 6시 자동 생성 이후 호출 권장)"""
    if use_manus and os.getenv("MANUS_API_KEY"):
        try:
            from manus_ai_analyzer import run_manus_intelligent_analysis
            result = run_manus_intelligent_analysis()
            # Manus 분석 후에도 전체 로그 요약 갱신
            try:
                analyze_logs(PROJECT_DIR, PROJECT_DIR / "lotto.xlsx")
            except:
                pass
            return result
        except Exception as e:
            logger.error(f"Manus AI 분석 실패, 기본 분석으로 전환: {e}")

    logger.info("AI 지능형 분석 시작 (축적된 로그 기반)...")
    
    excel_path = PROJECT_DIR / "lotto.xlsx"
    
    # 1. 데이터 업데이트 (최신 회차 수집)
    try:
        update_excel(excel_path)
        logger.info("데이터 업데이트 완료")
    except Exception as e:
        logger.error(f"데이터 업데이트 중 오류 발생: {e}")
    
    # 2. 분석기 초기화
    predictor = LottoPredictor(str(excel_path))
    
    # 3. AI 분석 실행 (패턴 및 확률 기반)
    # 저녁 6시에 이미 100개씩 생성되어 로그에 축적되어 있으므로, 
    # 여기서는 리포트용 TOP 5만 별도로 추출하거나 기존 로그에서 가져올 수 있습니다.
    # 현재는 일관성을 위해 직접 5개를 새로 생성하여 로그에 추가합니다.
    simulation_count = 10000
    
    # 패턴 추천 번호 5개 생성 및 로그 축적
    pattern_results = predictor.predict(sets=5, simulation_count=simulation_count)
    log_prediction_results(
        base_dir=PROJECT_DIR,
        excel_path=excel_path,
        predictor=predictor,
        results=pattern_results,
        log_type="prediction",
        simulation_count=simulation_count
    )
    
    # 확률 추천 번호 5개 생성 및 로그 축적
    prob_results = predictor.predict_probability_only(sets=5, simulation_count=simulation_count)
    log_prediction_results(
        base_dir=PROJECT_DIR,
        excel_path=excel_path,
        predictor=predictor,
        results=prob_results,
        log_type="probability",
        simulation_count=simulation_count
    )
    
    # 4. 분석 리포트 생성
    summary = analyze_logs(PROJECT_DIR, excel_path)
    
    # 4.1 지능형 분석 엔진(고도화 모델) 실행
    try:
        from ai_intelligent_analyzer import AIIntelligentAnalyzer
        intel_analyzer = AIIntelligentAnalyzer(PROJECT_DIR)
        intel_analyzer.run_analysis()
        logger.info("지능형 분석 엔진(고도화 모델) 실행 완료")
    except Exception as e:
        logger.error(f"지능형 분석 엔진 실행 중 오류 발생: {e}")

    # 5. 결과 메시지 구성
    target_round = summary.get("latest_source_round", 0) + 1
    
    message = f"🎰 [AI 지능형 분석 결과 - {target_round}회차] 🎰\n\n"
    message += f"📅 분석 일시: {datetime.now(KST).strftime('%Y-%m-%d %H:%M')}\n"
    message += f"🎯 분석 기반: 패턴 가중치, 마르코프 전이확률, 누적 로그 분석\n"
    message += f"💳 본 분석은 AI 크레딧을 사용하여 생성되었습니다.\n\n"
    
    message += "💎 [패턴 추천 번호 TOP 5] 💎\n"
    for i, res in enumerate(pattern_results, 1):
        nums = ", ".join(f"{n:02d}" for n in sorted(res['sorted']))
        message += f"{i}순위: {nums} (점수: {res['score']:.2f})\n"
    
    message += "\n📊 [확률 추천 번호 TOP 5] 📊\n"
    for i, res in enumerate(prob_results, 1):
        nums = ", ".join(f"{n:02d}" for n in sorted(res['sorted']))
        message += f"{i}순위: {nums} (점수: {res['score']:.2f})\n"
    
    rec_threshold = summary.get("recommended_threshold")
    if rec_threshold:
        message += f"\n💡 [AI 분석 팁]\n현재 데이터 기준, AI 권장 임계 점수는 {rec_threshold['threshold']}점 이상입니다. 이 점수 이상의 조합이 당첨 확률이 높습니다.\n"
    
    logger.info("분석 완료 및 결과 생성 성공")
    
    # 결과 파일 저장
    result_path = PROJECT_DIR / "reports" / "weekly_ai_recommendation.txt"
    with open(result_path, "w", encoding="utf-8") as f:
        f.write(message)
    
    # 알림 전송 비활성화 (사용자 요청)
    # send_notification(message)
    
    return message

def send_notification(message):
    """알림 전송 비활성화됨"""
    pass

if __name__ == "__main__":
    run_ai_analysis()
