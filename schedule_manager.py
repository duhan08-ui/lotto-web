import json
import logging
import os
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")

def load_schedule_config(project_dir: Path) -> dict:
    """스케줄 설정 로드"""
    config_path = project_dir / "logs" / "auto_schedule_config.json"
    default_config = {
        "enabled": True,
        "run_time": "18:00",
        "ai_report_time": "10:00",
        "target_log_count": 200,
        "prediction_count": 100,
        "probability_count": 100,
        "last_run": None,
        "last_run_success": False,
        "last_ai_report_run": None
    }
    
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return {**default_config, **json.load(f)}
        except Exception as e:
            logger.error(f"설정 파일 로드 실패: {e}")
    
    return default_config

def save_schedule_config(project_dir: Path, config: dict):
    """스케줄 설정 저장"""
    config_path = project_dir / "logs" / "auto_schedule_config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"설정 파일 저장 실패: {e}")

def is_schedule_time(run_time_str: str = "18:00") -> bool:
    """현재 시간이 스케줄 실행 시간인지 확인"""
    now = datetime.now(KST)
    
    # 설정된 시간 이후인지 확인
    try:
        hour, minute = map(int, run_time_str.split(':'))
        scheduled_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        # 현재 시간이 설정된 시간 이후이고, 같은 날인지 확인
        return now >= scheduled_time
    except Exception as e:
        logger.error(f"시간 비교 실패: {e}")
        return False

def should_run_now(config: dict) -> bool:
    """지금 스케줄을 실행해야 하는지 판단"""
    if not config.get("enabled", True):
        return False
    
    if not is_schedule_time(config.get("run_time", "18:00")):
        return False
    
    # 오늘 이미 실행했는지 확인
    last_run = config.get("last_run")
    if last_run:
        try:
            last_run_date = datetime.fromisoformat(last_run).date()
            today = datetime.now(KST).date()
            if last_run_date == today:
                return False
        except Exception as e:
            logger.warning(f"마지막 실행 시간 파싱 실패: {e}")
    
    return True

def run_scheduled_auto_generation(project_dir: Path, excel_path: Path) -> bool:
    """스케줄된 자동 로그 생성 실행"""
    project_dir = Path(project_dir)
    excel_path = Path(excel_path)
    
    # 순환 참조 방지를 위해 함수 내에서 임포트
    from auto_log_generator import generate_auto_logs
    
    logger.info("="*60)
    logger.info("⏰ 자동 로그 생성 스케줄 실행 시작")
    logger.info(f"실행 시간: {datetime.now(KST).isoformat()}")
    
    # 설정 로드
    config = load_schedule_config(project_dir)
    
    # 자동 생성 실행
    success = generate_auto_logs(
        project_dir,
        excel_path,
        target_count=config.get("target_log_count", 200),
        prediction_count=config.get("prediction_count", 100),
        probability_count=config.get("probability_count", 100),
    )
    
    # 설정 업데이트
    config["last_run"] = datetime.now(KST).isoformat()
    config["last_run_success"] = success
    save_schedule_config(project_dir, config)
    
    logger.info(f"자동 로그 생성 {'성공' if success else '실패'}")
    
    # 저녁 6시에는 번호 추출만 수행하고, AI 리포트 갱신은 오전 10시 스케줄에서 별도로 수행합니다.
    # if success:
    #     try:
    #         from ai_scheduler import run_ai_analysis
    #         run_ai_analysis()
    #     except Exception as e:
    #         logger.error(f"AI 리포트 갱신 중 오류 발생: {e}")
            
    logger.info("="*60)
    return success

# check_and_run_if_needed 함수는 파일 하단에 통합된 버전이 사용됩니다.

def should_run_ai_report(config: dict) -> bool:
    """오전 10시 AI 리포트를 실행해야 하는지 판단"""
    if not config.get("enabled", True):
        return False
    
    if not is_schedule_time(config.get("ai_report_time", "10:00")):
        return False
    
    # 오늘 이미 실행했는지 확인
    last_run = config.get("last_ai_report_run")
    if last_run:
        try:
            last_run_date = datetime.fromisoformat(last_run).date()
            today = datetime.now(KST).date()
            if last_run_date == today:
                return False
        except Exception as e:
            logger.warning(f"마지막 AI 리포트 실행 시간 파싱 실패: {e}")
    
    return True

def run_scheduled_ai_report(project_dir: Path) -> bool:
    """스케줄된 AI 리포트 생성 실행"""
    from ai_scheduler import run_ai_analysis
    
    logger.info("="*60)
    logger.info("⏰ AI 지능형 분석 리포트 스케줄 실행 시작 (오전 10시)")
    
    try:
        # Manus API 사용 여부 확인
        use_manus = os.getenv("MANUS_API_KEY") is not None
        run_ai_analysis(use_manus=use_manus)
        
        # 설정 업데이트
        config = load_schedule_config(project_dir)
        config["last_ai_report_run"] = datetime.now(KST).isoformat()
        save_schedule_config(project_dir, config)
        
        logger.info("AI 지능형 분석 리포트 생성 완료")
        logger.info("="*60)
        return True
    except Exception as e:
        logger.error(f"AI 리포트 생성 중 오류 발생: {e}")
        logger.info("="*60)
        return False

def check_and_run_if_needed(project_dir: Path, excel_path: Path) -> bool:
    """스케줄 실행 조건 확인 및 실행 (app.py에서 호출)"""
    config = load_schedule_config(project_dir)
    
    # 1. 저녁 6시 번호 추출 스케줄 체크
    if should_run_now(config):
        run_scheduled_auto_generation(project_dir, excel_path)
    
    # 2. 오전 10시 AI 리포트 스케줄 체크
    if should_run_ai_report(config):
        run_scheduled_ai_report(project_dir)
    
    return True
