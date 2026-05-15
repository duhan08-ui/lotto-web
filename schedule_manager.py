#!/usr/bin/env python3
# -*- coding: utf-8 -*-
'''스케줄 관리자 - 발전하는 피드백 루프 연동'''

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_DIR = Path(__file__).resolve().parent
from feedback_store import FeedbackStore

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(PROJECT_DIR / 'logs' / 'scheduler.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

KST = ZoneInfo('Asia/Seoul')


def load_schedule_config(project_dir: Path) -> dict:
    '''스케줄 설정 로드'''
    if isinstance(project_dir, str):
        project_dir = Path(project_dir)
    config_path = project_dir / 'logs' / 'auto_schedule_config.json'
    
    default_config = {
        'enabled': True,
        'run_time': '17:00',
        'ai_report_time': '10:00',
        'saturday_check_time': '20:00',
        'target_log_count': 200,
        'prediction_count': 100,
        'probability_count': 100,
        'last_run': None,
        'last_ai_report_run': None,
        'last_saturday_check': None,
        'feedback_enabled': True
    }
    
    if config_path.exists():
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return {**default_config, **json.load(f)}
        except Exception as e:
            logger.error('설정 파일 로드 실패: %s' % e)
    
    return default_config


def save_schedule_config(project_dir: Path, config: dict):
    '''스케줄 설정 저장'''
    config_path = project_dir / 'logs' / 'auto_schedule_config.json'
    config_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error('설정 파일 저장 실패: %s' % e)


def is_schedule_time(run_time_str: str = '18:00', time_window_minutes: int = 5) -> bool:
    '''현재 시간이 스케줄 실행 시간인지 확인'''
    now = datetime.now(KST)
    
    try:
        hour, minute = map(int, run_time_str.split(':'))
        scheduled_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        diff = abs((now - scheduled_time).total_seconds())
        return diff <= time_window_minutes * 60
    except Exception as e:
        logger.error('시간 비교 실패: %s' % e)
        return False


def should_run_now(config: dict, run_key: str = 'last_run', time_key: str = 'run_time') -> bool:
    '''지금 스케줄을 실행해야 하는지 판단'''
    if not config.get('enabled', True):
        return False
    
    if not is_schedule_time(config.get(time_key, '17:00')):
        return False
    
    last_run = config.get(run_key)
    if last_run:
        try:
            last_run_date = datetime.fromisoformat(last_run).date()
            today = datetime.now(KST).date()
            if last_run_date == today:
                return False
        except Exception as e:
            logger.warning('마지막 실행 시간 파싱 실패: %s' % e)
    
    return True


def should_run_saturday_check(config: dict) -> bool:
    '''토요일 저녁 결과 비교 실행 여부'''
    if not config.get('enabled', True):
        return False
    
    now = datetime.now(KST)
    
    if now.weekday() != 5:
        return False
    
    if not is_schedule_time(config.get('saturday_check_time', '20:00'), time_window_minutes=30):
        return False
    
    last_check = config.get('last_saturday_check')
    if last_check:
        try:
            last_check_date = datetime.fromisoformat(last_check).date()
            if last_check_date == now.date():
                return False
        except Exception:
            pass
    
    return True


def run_scheduled_auto_generation(project_dir: Path, excel_path: Path) -> bool:
    '''스케줄된 자동 로그 생성 실행 (매일 오후 5시)'''
    project_dir = Path(project_dir)
    excel_path = Path(excel_path)
    
    try:
        from auto_log_generator import generate_auto_logs
    except ImportError as e:
        logger.error('auto_log_generator import 실패: %s' % e)
        return False
    
    logger.info('=' * 60)
    logger.info('자동 로그 생성 스케줄 실행 시작 (오후 5시)')
    logger.info('실행 시간: %s' % datetime.now(KST).isoformat())
    
    config = load_schedule_config(project_dir)
    
    success = generate_auto_logs(
        project_dir, excel_path,
        target_count=config.get('target_log_count', 200),
        prediction_count=config.get('prediction_count', 100),
        probability_count=config.get('probability_count', 100),
    )
    
    if success and config.get('feedback_enabled', True):
        try:
            feedback_store = FeedbackStore(project_dir)
            _save_predictions_to_feedback(feedback_store, project_dir, config)
        except Exception as e:
            logger.error('피드백 저장 실패: %s' % e)
    
    config['last_run'] = datetime.now(KST).isoformat()
    config['last_run_success'] = success
    save_schedule_config(project_dir, config)
    
    result_str = '성공' if success else '실패'
    logger.info('자동 로그 생성 %s' % result_str)
    logger.info('=' * 60)
    return success


def _save_predictions_to_feedback(feedback_store, project_dir: Path, config: dict):
    '''예측 로그를 피드백 스토어에 저장'''
    prediction_log = project_dir / 'logs' / 'prediction_log.jsonl'
    
    if not prediction_log.exists():
        logger.warning('prediction_log.jsonl 없음 - 피드백 저장 건너뜀')
        return
    
    try:
        with open(prediction_log, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        recent_predictions = []
        for line in reversed(lines[-50:]):
            try:
                data = json.loads(line.strip())
                recent_predictions.append({
                    'numbers': data.get('numbers', []),
                    'score': data.get('score', 0),
                    'anti_score': data.get('anti_score', 0),
                    'crowd_proxy': data.get('crowd_proxy', 0),
                    'target_round': data.get('target_round'),
                    'method': data.get('method', 'local_engine')
                })
            except json.JSONDecodeError:
                continue
        
        if recent_predictions:
            target_round = recent_predictions[0].get('target_round', 0)
            feedback_store.save_predictions_batch(recent_predictions[:20], 0, target_round)
            logger.info('피드백 스토어에 %d개 예측 저장 완료' % len(recent_predictions[:20]))
        
    except Exception as e:
        logger.error('예측 -> 피드백 저장 중 오류: %s' % e)


def run_scheduled_ai_report(project_dir: Path) -> bool:
    '''스케줄된 AI 리포트 생성 실행 (매일 오전 10시)'''
    
    logger.info('=' * 60)
    logger.info('AI 지능형 분석 리포트 스케줄 실행 시작 (오전 10시)')
    
    try:
        from manus_ai_analyzer import ManusAIAnalyzer
        
        analyzer = ManusAIAnalyzer(project_dir)
        result = analyzer.run_analysis(
            custom_instructions='매일 오전 분석',
            use_manus=os.getenv('MANUS_API_KEY') is not None,
            save_results=True
        )
        
        config = load_schedule_config(project_dir)
        config['last_ai_report_run'] = datetime.now(KST).isoformat()
        save_schedule_config(project_dir, config)
        
        set_count = len(result.get('recommended_sets', []))
        logger.info('AI 분석 완료: %d개 세트 추천' % set_count)
        logger.info('=' * 60)
        return True
        
    except Exception as e:
        logger.error('AI 리포트 생성 중 오류 발생: %s' % e)
        logger.info('=' * 60)
        return False


def run_saturday_feedback_check(project_dir: Path, excel_path: Path) -> bool:
    '''토요일 저녁 피드백 루프 실행'''
    project_dir = Path(project_dir)
    excel_path = Path(excel_path)
    
    logger.info('=' * 60)
    logger.info('토요일 피드백 루프 실행 시작 (결과 비교)')
    logger.info('실행 시간: %s' % datetime.now(KST).isoformat())
    
    try:
        feedback_store = FeedbackStore(project_dir)
        
        logger.info('1단계: Excel에서 실제 결과 로드...')
        saved_count = feedback_store.update_lotto_excel_to_feedback(excel_path)
        logger.info('   실제 결과 %d개 저장 완료' % saved_count)
        
        logger.info('2단계: 예측 vs 실제 비교 분석...')
        compare_result = feedback_store.compare_and_analyze_all_pending()
        logger.info('   비교 결과: %s' % compare_result)
        
        logger.info('3단계: 피드백 리포트 생성...')
        report_path = feedback_store.generate_feedback_report()
        logger.info('   리포트 저장: %s' % report_path)
        
        logger.info('4단계: 피드백 데이터 CSV 내보내기...')
        csv_path = feedback_store.export_feedback_csv()
        logger.info('   CSV 저장: %s' % csv_path)
        
        config = load_schedule_config(project_dir)
        config['last_saturday_check'] = datetime.now(KST).isoformat()
        config['last_saturday_success'] = True
        save_schedule_config(project_dir, config)
        
        summary = feedback_store.get_stats_summary()
        logger.info('\n피드백 통계 요약:')
        logger.info('   총 예측 수: %d' % summary['total_predictions'])
        logger.info('   총 실제 결과: %d' % summary['total_actual_results'])
        logger.info('   총 피드백 분석: %d' % summary['total_feedbacks'])
        logger.info('   평균 적중 수: %.2f' % summary['average_matches'])
        
        logger.info('토요일 피드백 루프 완료!')
        logger.info('=' * 60)
        return True
        
    except Exception as e:
        logger.error('토요일 피드백 루프 오류: %s' % e)
        
        config = load_schedule_config(project_dir)
        config['last_saturday_check'] = datetime.now(KST).isoformat()
        config['last_saturday_success'] = False
        save_schedule_config(project_dir, config)
        
        logger.info('=' * 60)
        return False


def check_and_run_if_needed(project_dir: Path, excel_path: Path) -> dict:
    '''스케줄 실행 조건 확인 및 실행'''
    config = load_schedule_config(project_dir)
    
    results = {
        'auto_generation': None,
        'ai_report': None,
        'saturday_feedback': None
    }
    
    if should_run_now(config, 'last_run', 'run_time'):
        logger.info('자동 로그 생성 스케줄 감지')
        results['auto_generation'] = run_scheduled_auto_generation(project_dir, excel_path)
    
    if should_run_now(config, 'last_ai_report_run', 'ai_report_time'):
        logger.info('AI 분석 스케줄 감지')
        results['ai_report'] = run_scheduled_ai_report(project_dir)
    
    if should_run_saturday_check(config):
        logger.info('토요일 피드백 루프 감지')
        results['saturday_feedback'] = run_saturday_feedback_check(project_dir, excel_path)
    
    return results


def run_simulation(project_dir: Path = None, excel_path: Path = None) -> dict:
    '''가상 테스트 실행'''
    project_dir = project_dir or PROJECT_DIR
    excel_path = excel_path or (project_dir / 'lotto.xlsx')
    
    logger.info('=' * 60)
    logger.info('스케줄 시뮬레이션 테스트 시작')
    logger.info('=' * 60)
    
    results = {}
    
    logger.info('\n[1/3] 자동 로그 생성 시뮬레이션...')
    try:
        results['auto_generation'] = run_scheduled_auto_generation(project_dir, excel_path)
    except Exception as e:
        logger.error('자동 생성 실패: %s' % e)
        results['auto_generation'] = False
    
    logger.info('\n[2/3] AI 분석 시뮬레이션...')
    try:
        results['ai_report'] = run_scheduled_ai_report(project_dir)
    except Exception as e:
        logger.error('AI 분석 실패: %s' % e)
        results['ai_report'] = False
    
    logger.info('\n[3/3] 피드백 루프 시뮬레이션...')
    try:
        results['saturday_feedback'] = run_saturday_feedback_check(project_dir, excel_path)
    except Exception as e:
        logger.error('피드백 루프 실패: %s' % e)
        results['saturday_feedback'] = False
    
    logger.info('\n' + '=' * 60)
    logger.info('시뮬레이션 결과 요약')
    logger.info('=' * 60)
    
    for key, value in results.items():
        status = '성공' if value else '실패'
        logger.info('  %s: %s' % (key, status))
    
    all_success = all(v for v in results.values() if v is not None)
    overall = '모두 성공' if all_success else '일부 실패'
    logger.info('\n전체 결과: %s' % overall)
    logger.info('=' * 60)
    
    return results


def manual_trigger_feedback_update(excel_path: Path = None):
    '''수동으로 피드백 업데이트 트리거'''
    project_dir = PROJECT_DIR
    excel_path = excel_path or (project_dir / 'lotto.xlsx')
    
    logger.info('=' * 60)
    logger.info('수동 피드백 업데이트 트리거')
    logger.info('=' * 60)
    
    feedback_store = FeedbackStore(project_dir)
    
    logger.info('1단계: Excel에서 실제 결과 로드...')
    saved = feedback_store.update_lotto_excel_to_feedback(excel_path)
    logger.info('   저장 완료: %d개' % saved)
    
    logger.info('2단계: 예측 vs 실제 비교...')
    result = feedback_store.compare_and_analyze_all_pending()
    logger.info('   비교 완료: %s' % result)
    
    logger.info('3단계: 리포트 생성...')
    report = feedback_store.generate_feedback_report()
    logger.info('   리포트: %s' % report)
    
    summary = feedback_store.get_stats_summary()
    logger.info('\n최종 통계: %s' % summary)
    
    logger.info('=' * 60)
    return summary


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='스케줄 관리자')
    parser.add_argument('--simulate', action='store_true', help='시뮬레이션 테스트 실행')
    parser.add_argument('--update-feedback', action='store_true', help='피드백 업데이트만 실행')
    parser.add_argument('--excel-path', type=str, help='Excel 파일 경로')
    
    args = parser.parse_args()
    
    excel_path = Path(args.excel_path) if args.excel_path else PROJECT_DIR / 'lotto.xlsx'
    
    if args.simulate:
        run_simulation(PROJECT_DIR, excel_path)
    elif args.update_feedback:
        manual_trigger_feedback_update(excel_path)
    else:
        results = check_and_run_if_needed(PROJECT_DIR, excel_path)
        print('스케줄 실행 결과: %s' % results)