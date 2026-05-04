#!/usr/bin/env python3
"""
독립형 스케줄러 - 백그라운드에서 실행
1. 매일 오전 10시: AI 지능형 분석 리포트 생성
2. 매일 저녁 6시: 패턴/확률 번호 100개씩 자동 생성

사용법:
  python3 standalone_scheduler.py
"""

import os
import sys
import logging
import time
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

# 프로젝트 경로 설정
PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

# 로깅 설정
log_dir = PROJECT_DIR / "logs"
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / "scheduler.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("StandaloneScheduler")

# 한국 시간대
KST = ZoneInfo("Asia/Seoul")


def run_scheduled_task():
    """스케줄된 작업 실행 (체크 및 실행)"""
    try:
        from schedule_manager import check_and_run_if_needed
        from log_utils import ensure_runtime_dirs
        
        excel_path = PROJECT_DIR / "lotto.xlsx"
        
        # 디렉토리 확인
        ensure_runtime_dirs(PROJECT_DIR)
        
        logger.info(f"⏰ 스케줄 체크 시작 ({datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')})")
        
        # check_and_run_if_needed 내부에서 오전 10시와 저녁 6시 조건을 모두 체크합니다.
        check_and_run_if_needed(PROJECT_DIR, excel_path)
        
    except Exception as e:
        logger.error(f"❌ 스케줄 작업 실행 중 오류: {e}", exc_info=True)


def main():
    """메인 함수"""
    logger.info(f"스탠드얼론 스케줄러 시작 (PID: {os.getpid()})")
    
    try:
        import schedule
        
        # 1분마다 체크하여 실행 조건이 맞으면 실행
        schedule.every(1).minutes.do(run_scheduled_task)
        
        logger.info("✅ 스케줄러 등록 완료: 1분마다 실행 조건 체크")
        logger.info("   - 오전 10시: AI 지능형 분석 리포트 생성")
        logger.info("   - 저녁 6시: 패턴/확률 번호 100개씩 자동 생성")
        logger.info("스케줄러가 실행 중입니다. Ctrl+C로 종료할 수 있습니다.")
        
        # 스케줄러 루프
        while True:
            schedule.run_pending()
            time.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("스케줄러 종료 (사용자 요청)")
    except Exception as e:
        logger.error(f"스케줄러 오류: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
