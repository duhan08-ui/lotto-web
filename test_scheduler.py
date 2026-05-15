#!/usr/bin/env python3
"""
스케줄러 테스트 스크립트
스케줄 기능이 정상 작동하는지 확인합니다.
"""

import sys
import logging
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

# 프로젝트 경로 설정
PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("SchedulerTest")

KST = ZoneInfo("Asia/Seoul")


def test_imports():
    """필요한 모듈 임포트 테스트"""
    logger.info("=" * 70)
    logger.info("1️⃣  모듈 임포트 테스트")
    logger.info("=" * 70)
    
    try:
        import schedule
        logger.info("✅ schedule 모듈 임포트 성공")
    except ImportError:
        logger.error("❌ schedule 모듈 없음. 설치: pip install schedule")
        return False
    
    try:
        from schedule_manager import (
            is_schedule_time, 
            check_and_run_if_needed, 
            run_scheduled_auto_generation
        )
        logger.info("✅ schedule_manager 모듈 임포트 성공")
    except ImportError as e:
        logger.error(f"❌ schedule_manager 임포트 실패: {e}")
        return False
    
    try:
        from auto_log_generator import generate_auto_logs
        logger.info("✅ auto_log_generator 모듈 임포트 성공")
    except ImportError as e:
        logger.error(f"❌ auto_log_generator 임포트 실패: {e}")
        return False
    
    return True


def test_time_checks():
    """시간 확인 함수 테스트"""
    logger.info("\n" + "=" * 70)
    logger.info("2️⃣  시간 확인 함수 테스트")
    logger.info("=" * 70)
    
    from schedule_manager import is_schedule_time
    
    now = datetime.now(KST)
    logger.info(f"현재 시간: {now.strftime('%Y-%m-%d %H:%M:%S (%A)')}")
    
    is_weekday_result = now.weekday() <= 4
    logger.info(f"평일 여부: {is_weekday_result} {'✅' if is_weekday_result else '❌'}")
    
    is_schedule_result = is_schedule_time()
    logger.info(f"저녁 6시 여부: {is_schedule_result} {'✅' if is_schedule_result else '⏰ (현재 시간이 아님)'}")
    
    return True


def test_schedule_config():
    """스케줄 설정 파일 테스트"""
    logger.info("\n" + "=" * 70)
    logger.info("3️⃣  스케줄 설정 파일 테스트")
    logger.info("=" * 70)
    
    from schedule_manager import load_schedule_config
    
    try:
        config = load_schedule_config(PROJECT_DIR)
        logger.info(f"✅ 설정 로드 성공")
        logger.info(f"   - enabled: {config.get('enabled')}")
        logger.info(f"   - target_log_count: {config.get('target_log_count')}")
        logger.info(f"   - prediction_count: {config.get('prediction_count')}")
        logger.info(f"   - probability_count: {config.get('probability_count')}")
        logger.info(f"   - last_run: {config.get('last_run')}")
        logger.info(f"   - last_run_success: {config.get('last_run_success')}")
        return True
    except Exception as e:
        logger.error(f"❌ 설정 로드 실패: {e}")
        return False


def test_should_run():
    """스케줄 실행 여부 판단 테스트"""
    logger.info("\n" + "=" * 70)
    logger.info("4️⃣  스케줄 실행 여부 판단 테스트")
    logger.info("=" * 70)
    
    from schedule_manager import should_run_now, load_schedule_config
    
    config = load_schedule_config(PROJECT_DIR)
    should_run = should_run_now(config)
    logger.info(f"현재 실행 여부: {should_run}")
    
    if should_run:
        logger.info("✅ 현재 조건에서 자동 생성이 실행됩니다.")
    else:
        logger.info("⏰ 현재 조건에서는 자동 생성이 실행되지 않습니다.")
        logger.info("   (저녁 6시, 평일, 오늘 미실행 시에만 실행됨)")
    
    return True


def test_log_database():
    """로그 데이터베이스 테스트"""
    logger.info("\n" + "=" * 70)
    logger.info("5️⃣  로그 데이터베이스 테스트")
    logger.info("=" * 70)
    
    from auto_log_generator import get_log_count
    
    log_dir = PROJECT_DIR / "logs"
    try:
        count = get_log_count(log_dir)
        logger.info(f"✅ 현재 로그 건수: {count}건")
        logger.info(f"   - 목표 건수: 200건")
        logger.info(f"   - 필요한 생성: {max(0, 200 - count)}건")
        return True
    except Exception as e:
        logger.error(f"❌ 로그 건수 조회 실패: {e}")
        return False


def test_excel_file():
    """엑셀 파일 테스트"""
    logger.info("\n" + "=" * 70)
    logger.info("6️⃣  엑셀 파일 테스트")
    logger.info("=" * 70)
    
    excel_path = PROJECT_DIR / "lotto.xlsx"
    
    if not excel_path.exists():
        logger.error(f"❌ 엑셀 파일 없음: {excel_path}")
        return False
    
    try:
        import pandas as pd
        df = pd.read_excel(excel_path)
        logger.info(f"✅ 엑셀 파일 읽기 성공")
        logger.info(f"   - 행 수: {len(df):,}")
        logger.info(f"   - 열 수: {len(df.columns)}")
        
        if "회차" in df.columns:
            latest_round = pd.to_numeric(df['회차'], errors='coerce').dropna().max()
            logger.info(f"   - 최신 회차: {int(latest_round)}회")
        
        return True
    except Exception as e:
        logger.error(f"❌ 엑셀 파일 처리 실패: {e}")
        return False


def test_manual_run():
    """수동 실행 테스트"""
    logger.info("\n" + "=" * 70)
    logger.info("7️⃣  수동 실행 테스트")
    logger.info("=" * 70)
    
    from schedule_manager import run_scheduled_auto_generation
    
    excel_path = PROJECT_DIR / "lotto.xlsx"
    
    if not excel_path.exists():
        logger.warning("⚠️  엑셀 파일이 없어 수동 실행 테스트를 건너뜁니다.")
        return True
    
    logger.info("강제 실행 테스트를 시작합니다...")
    
    try:
        success = run_scheduled_auto_generation(PROJECT_DIR, excel_path)
        if success:
            logger.info("✅ 수동 실행 성공")
        else:
            logger.info("⏰ 수동 실행: 조건 미충족 (로그 건수 >= 200 또는 오늘 이미 실행)")
        return True
    except Exception as e:
        logger.error(f"❌ 수동 실행 실패: {e}")
        return False


def main():
    """메인 테스트 함수"""
    logger.info("\n")
    logger.info("🧪 로또 스케줄러 테스트 시작")
    logger.info(f"프로젝트 경로: {PROJECT_DIR}")
    logger.info(f"현재 시간: {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S (%A)')}")
    logger.info("")
    
    tests = [
        ("모듈 임포트", test_imports),
        ("시간 확인", test_time_checks),
        ("설정 파일", test_schedule_config),
        ("실행 여부", test_should_run),
        ("로그 DB", test_log_database),
        ("엑셀 파일", test_excel_file),
        ("수동 실행", test_manual_run),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            logger.error(f"❌ {name} 테스트 중 예외 발생: {e}")
            results.append((name, False))
    
    # 결과 요약
    logger.info("\n" + "=" * 70)
    logger.info("📊 테스트 결과 요약")
    logger.info("=" * 70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"{status}: {name}")
    
    logger.info(f"\n총 {passed}/{total} 테스트 통과")
    
    if passed == total:
        logger.info("\n🎉 모든 테스트 통과! 스케줄러가 정상 작동합니다.")
        return 0
    else:
        logger.warning(f"\n⚠️  {total - passed}개 테스트 실패. 위 오류를 확인하세요.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
