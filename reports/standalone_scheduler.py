#!/usr/bin/env python3
# -*- coding: utf-8 -*-
'''
독립형 스케줄러 - 백그라운드에서 실행 (웹 로그인 불필요)
1. 매일 오전 6시: Manus AI 번호 추출 (1~5순위, 수동 로그에만 저장)
2. 매일 오전 9시: 패턴/확률/수동 추천 100개씩 자동 생성 (각 로그에 저장)

사용법:
  python3 standalone_scheduler.py        # 백그라운드 실행
  python3 standalone_scheduler.py --once # 즉시 1회 실행 후 종료
  python3 standalone_scheduler.py --test # 테스트 모드 (무조건 실행)

장점:
  - 웹 앱 로그인 없이 독립 실행
  - Streamlit 의존성 없음
  - 1분마다 체크하여 정시에 실행
'''

import os
import sys
import logging
import time
import json
import signal
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

# 프로젝트 경로 설정
PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

# 로깅 설정
log_dir = PROJECT_DIR / 'logs'
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / 'scheduler.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('StandaloneScheduler')

# 한국 시간대
KST = ZoneInfo('Asia/Seoul')

# 스케줄 설정
SCHEDULES = {
    'manus_ai':        {'hour': 6,  'minute': 0, 'time_window': 120},  # 오전 6시 (2시간 윈도우)
    'auto_generation': {'hour': 9,  'minute': 0, 'time_window': 120},  # 오전 9시 (2시간 윈도우)
}


def load_auto_schedule_config() -> dict:
    '''스케줄 설정 로드'''
    config_path = log_dir / 'auto_schedule_config.json'

    default_config = {
        'enabled': True,
        'run_time': '09:00',
        'manus_time': '06:00',
        'prediction_count': 100,
        'probability_count': 100,
        'manual_count': 100,
        'last_run': None,
        'last_manus_run': None,
        'last_run_success': None,
        'last_manus_run_success': None,
        'last_source_round': None,        # [B안] 마지막 생성 시 source_round
        'top5_generated_round': None,     # [B안] 1~5순위 생성된 source_round
        'last_saturday_update': None,     # 토요일 당첨번호 수집 마지막 실행일
        'last_perf_analysis': None,       # 성능 분석 마지막 실행일
    }

    if config_path.exists():
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return {**default_config, **json.load(f)}
        except Exception as e:
            logger.warning('설정 파일 로드 실패: %s' % e)

    return default_config


def save_auto_schedule_config(config: dict):
    '''스케줄 설정 저장'''
    config_path = log_dir / 'auto_schedule_config.json'
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error('설정 파일 저장 실패: %s' % e)


def is_time_to_run(scheduled_hour: int, scheduled_minute: int, time_window_minutes: int = 120) -> bool:
    '''현재 시간이 스케줄 실행 시간인지 확인'''
    now = datetime.now(KST)
    scheduled_time = now.replace(hour=scheduled_hour, minute=scheduled_minute, second=0, microsecond=0)
    diff = abs((now - scheduled_time).total_seconds())
    return diff <= time_window_minutes * 60


def should_run_today(config: dict, key: str) -> bool:
    '''오늘 이미 실행했는지 확인
    
    [BUG FIX] datetime.fromisoformat(last_run).replace(tzinfo=KST) 대신
    astimezone(KST) 사용 - replace()는 기존 timezone을 강제 교체하여
    UTC ISO string을 KST로 잘못 해석함
    '''
    last_run = config.get(key)
    if not last_run:
        return True

    try:
        if isinstance(last_run, str):
            dt = datetime.fromisoformat(last_run)
            # timezone 정보가 없으면 KST로 간주, 있으면 KST로 변환
            if dt.tzinfo is None:
                from datetime import timezone as _tz
                dt = dt.replace(tzinfo=KST)
            else:
                dt = dt.astimezone(KST)
            last_run_date = dt.date()
        else:
            last_run_date = datetime.fromisoformat(str(last_run)).astimezone(KST).date()
        today = datetime.now(KST).date()
        return last_run_date != today
    except Exception as e:
        logger.warning('last_run 날짜 파싱 실패 (%s): %s - 재실행 허용' % (key, e))
        return True



def get_current_source_round(excel_path: Path):
    '''현재 엑셀 파일의 최신 회차(source_round) 반환'''
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location('log_utils', PROJECT_DIR / 'log_utils.py')
        lu = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lu)
        ctx = lu.get_round_context(excel_path)
        return ctx.get('source_round')
    except Exception as e:
        logger.warning('source_round 조회 실패: %s' % e)
        return None


def is_new_round(config: dict, excel_path: Path) -> tuple:
    '''[B안] 회차 변경 감지
    Returns: (changed: bool, current_round: int|None, prev_round: int|None)
    '''
    current_round = get_current_source_round(excel_path)
    prev_round = config.get('last_source_round')

    if current_round is None:
        return False, None, prev_round

    if prev_round is None:
        return False, current_round, None

    changed = int(current_round) != int(prev_round)
    return changed, current_round, int(prev_round)


def run_top5_generation(excel_path: Path, source_round: int) -> bool:
    '''[B안] 회차 변경 시 1~5순위 AI 추천번호 재생성
    패턴 TOP5 + 확률 TOP5를 prediction_log / probability_log 에 저장하고
    reports/round_{N}_top5.json 에 별도 리포트 기록.
    '''
    import importlib.util
    import json as _json

    logger.info('=' * 60)
    logger.info('[B안] 회차 변경 감지 → 1~5순위 AI 추천번호 재생성')
    logger.info('  대상 회차: %d회차' % (source_round + 1))
    logger.info('  실행 시간: %s' % datetime.now(KST).isoformat())

    try:
        spec = importlib.util.spec_from_file_location('lotto_core', PROJECT_DIR / 'lotto_core.py')
        core_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(core_module)
        LottoPredictor = core_module.LottoPredictor

        spec2 = importlib.util.spec_from_file_location('log_utils', PROJECT_DIR / 'log_utils.py')
        lu = importlib.util.module_from_spec(spec2)
        spec2.loader.exec_module(lu)

        predictor = LottoPredictor(str(excel_path))
        sim_count = 8000

        # 패턴 1~5순위
        pattern_top5 = predictor.predict(sets=5, simulation_count=sim_count)
        lu.log_prediction_results(
            base_dir=PROJECT_DIR, excel_path=excel_path, predictor=predictor,
            results=pattern_top5, log_type='prediction', simulation_count=sim_count,
        )
        logger.info('  패턴 TOP5 생성 완료:')
        for i, r in enumerate(pattern_top5, 1):
            nums_str = ', '.join('%02d' % n for n in sorted(r['sorted']))
            logger.info('    %d순위: [%s] (score: %.4f)' % (i, nums_str, r.get('score', 0)))

        # 확률 1~5순위
        prob_top5 = predictor.predict_probability_only(sets=5, simulation_count=sim_count)
        lu.log_prediction_results(
            base_dir=PROJECT_DIR, excel_path=excel_path, predictor=predictor,
            results=prob_top5, log_type='probability', simulation_count=sim_count,
        )
        logger.info('  확률 TOP5 생성 완료:')
        for i, r in enumerate(prob_top5, 1):
            nums_str = ', '.join('%02d' % n for n in sorted(r['sorted']))
            logger.info('    %d순위: [%s] (score: %.4f)' % (i, nums_str, r.get('score', 0)))

        # reports/round_{N}_top5.json 저장
        reports_dir = PROJECT_DIR / 'reports'
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_path = reports_dir / ('round_%d_top5.json' % (source_round + 1))
        report_data = {
            'generated_at': datetime.now(KST).isoformat(),
            'created_date_kst': datetime.now(KST).strftime('%Y-%m-%d'),
            'source_round': source_round,
            'target_round': source_round + 1,
            'pattern_top5': [
                {'rank': i+1, 'numbers': r['sorted'], 'score': r.get('score',0),
                 'ensemble_score': r.get('ensemble_score',0), 'entropy_score': r.get('entropy_score',0)}
                for i, r in enumerate(pattern_top5)
            ],
            'probability_top5': [
                {'rank': i+1, 'numbers': r['sorted'], 'score': r.get('score',0),
                 'ensemble_score': r.get('ensemble_score',0), 'entropy_score': r.get('entropy_score',0)}
                for i, r in enumerate(prob_top5)
            ],
        }
        with open(report_path, 'w', encoding='utf-8') as f:
            _json.dump(report_data, f, ensure_ascii=False, indent=2)
        logger.info('  리포트 저장: %s' % report_path.name)
        logger.info('=' * 60)
        return True

    except Exception as e:
        logger.error('[B안] TOP5 재생성 실패: %s' % e, exc_info=True)
        logger.info('=' * 60)
        return False


def run_performance_analysis(excel_path: Path) -> bool:
    '''performance_analyzer 실행 → performance_analysis.json 갱신
    - 매일 오전 9시 로그 생성 직후 자동 호출
    - 토요일 21시 당첨번호 수집 후 자동 호출
    '''
    logger.info('=' * 60)
    logger.info('성능 분석 시작 (예측 로그 ↔ 실제 당첨번호 비교)')
    logger.info('실행 시간: %s' % datetime.now(KST).isoformat())

    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'performance_analyzer', PROJECT_DIR / 'performance_analyzer.py'
        )
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)

        analyzer = m.PerformanceAnalyzer(PROJECT_DIR)
        results = analyzer.analyze_all_rounds(max_rounds=50)
        metrics, all_results = analyzer.calculate_performance_metrics(results)
        patterns = analyzer.analyze_number_patterns(results)
        report = analyzer.generate_performance_report(metrics, all_results, patterns)
        analyzer.save_results(metrics, all_results, patterns, report)

        total = metrics.get('total', {})
        logger.info('성능 분석 완료:')
        logger.info('  분석 회차: %d회' % total.get('rounds', 0))
        logger.info('  3등(5개일치): %d건' % total.get('total_3rd_hits', 0))
        logger.info('  4등(4개일치): %d건' % total.get('total_4th_hits', 0))
        logger.info('  5등(3개일치): %d건' % total.get('total_5th_hits', 0))
        logger.info('=' * 60)
        return True

    except Exception as e:
        logger.error('성능 분석 실패: %s' % e, exc_info=True)
        logger.info('=' * 60)
        return False


def run_saturday_winner_update(excel_path: Path) -> bool:
    '''토요일 21시: 최신 당첨번호 수집 → 엑셀 갱신 → 성능 분석 자동 실행'''
    logger.info('=' * 60)
    logger.info('토요일 당첨번호 수집 시작')
    logger.info('실행 시간: %s' % datetime.now(KST).isoformat())

    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'update_lotto', PROJECT_DIR / 'update_lotto.py'
        )
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        m.update_excel(excel_path)
        logger.info('당첨번호 엑셀 갱신 완료')
    except Exception as e:
        logger.error('엑셀 갱신 실패: %s' % e, exc_info=True)
        logger.info('=' * 60)
        return False

    # 엑셀 갱신 후 성능 분석 즉시 실행
    success = run_performance_analysis(excel_path)
    logger.info('토요일 루틴 완료 (분석: %s)' % ('성공' if success else '실패'))
    logger.info('=' * 60)
    return success


def run_manus_analysis(excel_path: Path) -> bool:
    '''Manus AI 번호 추출 실행 (오전 6시) - 1~5순위 수동 로그(manual_score_log.jsonl)에만 저장'''
    logger.info('=' * 60)
    logger.info('Manus AI 번호 추출 시작 (오전 6시 스케줄)')
    logger.info('실행 시간: %s' % datetime.now(KST).isoformat())

    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_DIR / '.env', override=True)
    except ImportError:
        pass  # dotenv 없어도 환경변수에서 직접 읽음
    manus_api_key = os.getenv('MANUS_API_KEY')

    if not manus_api_key:
        logger.warning('MANUS_API_KEY 미설정 - Manus AI 분석 건너뜀')
        logger.warning('  -> .env 파일에 MANUS_API_KEY=your_key_here 를 추가하세요.')
        logger.info('=' * 60)
        return False

    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location('manus_ai_analyzer', PROJECT_DIR / 'manus_ai_analyzer.py')
        manus_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(manus_module)

        analyzer = manus_module.ManusAIAnalyzer(PROJECT_DIR)
        result = analyzer.run_analysis(
            custom_instructions='매일 오전 6시 자동 분석 - 1순위~5순위 번호 추출 (수동 로그 저장)',
            use_manus=True,
            save_results=True
        )

        if result.get('success'):
            sets = result.get('recommended_sets', [])
            logger.info('Manus AI 분석 완료: %d개 세트 추천 (수동 로그에 저장됨)' % len(sets))
            for i, nums in enumerate(sets, 1):
                nums_str = ', '.join('%02d' % n for n in sorted(nums))
                logger.info('  %d순위: %s' % (i, nums_str))
        else:
            raw = result.get('raw_response', '')
            if 'Host not in allowlist' in raw or '403' in raw:
                logger.warning('Manus AI 실패: 현재 서버 IP가 Manus API 허용 목록에 없음')
                logger.warning('  -> Manus 콘솔에서 이 서버의 IP를 whitelist에 추가하세요.')
            elif '에러: API 키가 없습니다' in raw:
                logger.warning('Manus AI 실패: API 키 미설정')
            elif raw.startswith('에러:'):
                logger.warning('Manus AI 실패: %s' % raw[:200])
            else:
                logger.warning('Manus AI 분석 결과 없음 (응답 파싱 실패) - raw: %s' % raw[:200])

        logger.info('=' * 60)
        return result.get('success', False)

    except Exception as e:
        logger.error('Manus AI 분석 실패: %s' % e, exc_info=True)
        logger.info('=' * 60)
        return False


def run_auto_generation(excel_path: Path, force_run: bool = False) -> bool:
    '''자동 로그 생성 실행 (오전 9시) - 패턴/확률/수동 각 100개씩 각 로그에 저장'''
    logger.info('=' * 60)
    if force_run:
        logger.info('자동 로그 생성 시작 (테스트/강제 모드 - 무조건 재생성)')
    else:
        logger.info('자동 로그 생성 시작 (오전 9시 스케줄)')
    logger.info('실행 시간: %s' % datetime.now(KST).isoformat())

    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location('auto_log_generator', PROJECT_DIR / 'auto_log_generator.py')
        auto_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(auto_module)

        config = load_auto_schedule_config()

        success = auto_module.generate_auto_logs(
            PROJECT_DIR, excel_path,
            prediction_count=config.get('prediction_count', 100),
            probability_count=config.get('probability_count', 100),
            manual_count=config.get('manual_count', 100),
            force_regenerate=force_run,  # --test 모드에서는 무조건 재생성
        )

        result_str = '성공' if success else '실패'
        logger.info('자동 로그 생성 %s' % result_str)

        # [BUG FIX] 생성 결과 상세 로그 - 각 로그 파일 건수 확인
        if success:
            _log_generation_summary(PROJECT_DIR / 'logs')

        logger.info('=' * 60)
        return success

    except Exception as e:
        logger.error('자동 로그 생성 실패: %s' % e, exc_info=True)
        logger.info('=' * 60)
        return False


def _log_generation_summary(log_dir: Path):
    '''생성된 로그 파일의 오늘 건수를 스케줄러 로그에 기록'''
    try:
        import json
        from datetime import date

        today_str = datetime.now(KST).strftime('%Y-%m-%d')
        log_files = {
            'prediction': 'prediction_log.jsonl',
            'probability': 'probability_log.jsonl',
            'manual': 'manual_score_log.jsonl',
        }
        for log_type, filename in log_files.items():
            fpath = log_dir / filename
            if not fpath.exists():
                logger.info('  [%s] 로그 파일 없음: %s' % (log_type, filename))
                continue
            today_count = 0
            total_count = 0
            with open(fpath, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    total_count += 1
                    try:
                        record = json.loads(line)
                        # timestamp는 UTC ISO string → KST 날짜로 변환해서 비교
                        ts = record.get('timestamp', '')
                        if ts:
                            dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                            kst_date = dt.astimezone(KST).strftime('%Y-%m-%d')
                            if kst_date == today_str:
                                today_count += 1
                    except Exception:
                        continue
            logger.info('  [%s] 오늘(%s) 생성: %d건 / 전체: %d건 (파일: %s)' % (
                log_type, today_str, today_count, total_count, filename
            ))
    except Exception as e:
        logger.warning('로그 건수 집계 실패: %s' % e)


def run_scheduler_check(force_run: bool = False):
    '''1분마다 실행되는 스케줄 체크 함수'''
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location('log_utils', PROJECT_DIR / 'log_utils.py')
        log_utils = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(log_utils)
        log_utils.ensure_runtime_dirs(PROJECT_DIR)

        excel_path = PROJECT_DIR / 'lotto.xlsx'
        config = load_auto_schedule_config()

        now = datetime.now(KST)
        logger.info('[스케줄 체크] %s (KST)' % now.strftime('%Y-%m-%d %H:%M:%S'))

        results = {}

        # force_run 모드: 테스트용으로 무조건 실행
        if force_run:
            logger.info('[테스트 모드] force_run=True - 모든 스케줄 무조건 실행')

        # ── 오전 6시: Manus AI 번호 추출 (수동 로그에만 저장) ──
        if config.get('enabled', True):
            manus_condition = is_time_to_run(6, 0) and should_run_today(config, 'last_manus_run')

            if force_run or manus_condition:
                logger.info('▶ 오전 6시 Manus AI 분석 조건 충족')
                success = run_manus_analysis(excel_path)
                config['last_manus_run'] = datetime.now(KST).isoformat()
                config['last_manus_run_success'] = success
                save_auto_schedule_config(config)  # [BUG FIX] 즉시 저장
                results['manus_ai'] = success
            else:
                if is_time_to_run(6, 0):
                    logger.info('  - 시간: 6시 윈도우 내 ✓')
                else:
                    now_m = now.hour * 60 + now.minute
                    target_m = 6 * 60
                    diff = abs(now_m - target_m)
                    logger.info('  - 시간: 6시에서 %d분 차이가 남 (윈도우: 120분)' % diff)

                if should_run_today(config, 'last_manus_run'):
                    logger.info('  - Manus AI: 오늘 아직 실행 안함 ✓')
                else:
                    logger.info('  - Manus AI: 오늘 이미 실행됨 ✗')
                results['manus_ai'] = None

        # ── 오전 9시: 패턴/확률/수동 추천 100개씩 자동 생성 ──
        if config.get('enabled', True):
            auto_condition = is_time_to_run(9, 0) and should_run_today(config, 'last_run')

            if force_run or auto_condition:
                logger.info('▶ 오전 9시 자동 로그 생성 조건 충족')
                success = run_auto_generation(excel_path, force_run=force_run)

                # [BUG FIX] 성공 여부와 무관하게 last_run 저장 (중복 실행 방지)
                # 실패해도 오늘은 재실행하지 않음 (원하면 --test로 강제 재실행 가능)
                config['last_run'] = datetime.now(KST).isoformat()
                config['last_run_success'] = success
                # 현재 회차도 기록
                current_round = get_current_source_round(excel_path)
                if current_round is not None:
                    config['last_source_round'] = current_round
                save_auto_schedule_config(config)  # [BUG FIX] 즉시 저장
                results['auto_generation'] = success
            else:
                if is_time_to_run(9, 0):
                    logger.info('  - 시간: 9시 윈도우 내 ✓')
                else:
                    now_m = now.hour * 60 + now.minute
                    target_m = 9 * 60
                    diff = abs(now_m - target_m)
                    logger.info('  - 시간: 9시에서 %d분 차이가 남 (윈도우: 120분)' % diff)

                if should_run_today(config, 'last_run'):
                    logger.info('  - 자동 생성: 오늘 아직 실행 안함 ✓')
                else:
                    logger.info('  - 자동 생성: 오늘 이미 실행됨 ✗')
                results['auto_generation'] = None

        # ── [B안] 회차 변경 감지 → 즉시 1~5순위 재생성 ──────────────────
        if config.get('enabled', True):
            round_changed, current_round, prev_round = is_new_round(config, excel_path)
            top5_generated_round = config.get('top5_generated_round')

            if force_run and current_round is not None:
                # 테스트 모드: 무조건 재생성
                logger.info('▶ [B안] 테스트 모드 - TOP5 재생성 강제 실행')
                success = run_top5_generation(excel_path, current_round)
                config['last_source_round'] = current_round
                config['top5_generated_round'] = current_round
                save_auto_schedule_config(config)
                results['top5_round_change'] = success

            elif round_changed and (
                top5_generated_round is None
                or int(top5_generated_round) != int(current_round)
            ):
                logger.info('▶ [B안] 회차 변경 감지! %s회 → %s회 (대상: %s회차)' % (
                    prev_round, current_round, current_round + 1
                ))
                success = run_top5_generation(excel_path, current_round)
                config['last_source_round'] = current_round
                config['top5_generated_round'] = current_round
                save_auto_schedule_config(config)
                results['top5_round_change'] = success

            else:
                if current_round is not None:
                    if round_changed:
                        logger.info('  - [B안] 회차 변경(%s→%s) but 이미 TOP5 생성됨 ✗' % (prev_round, current_round))
                    else:
                        logger.info('  - [B안] 회차 미변경 (현재: %s회차) ✗' % current_round)
                    # 최초 실행 시 last_source_round 초기화
                    if prev_round is None and current_round is not None:
                        config['last_source_round'] = current_round
                        save_auto_schedule_config(config)
                results['top5_round_change'] = None
        # ──────────────────────────────────────────────────────────────────

        # ── 토요일 21시: 당첨번호 수집 + 성능 분석 자동 실행 ──────────────
        if config.get('enabled', True):
            is_saturday = (now.weekday() == 5)  # 0=월 ~ 5=토 ~ 6=일
            saturday_condition = (
                is_saturday
                and is_time_to_run(21, 0, time_window_minutes=60)
                and should_run_today(config, 'last_saturday_update')
            )

            if force_run or saturday_condition:
                logger.info('▶ 토요일 21시 당첨번호 수집 + 성능 분석 시작')
                success = run_saturday_winner_update(excel_path)
                config['last_saturday_update'] = datetime.now(KST).isoformat()
                config['last_perf_analysis'] = datetime.now(KST).isoformat()
                save_auto_schedule_config(config)
                results['saturday_update'] = success
            else:
                if is_saturday and is_time_to_run(21, 0, time_window_minutes=60):
                    logger.info('  - 토요일 21시 윈도우 내 ✓')
                elif is_saturday:
                    logger.info('  - 토요일이지만 21시 윈도우 아님 ✗')
                else:
                    logger.info('  - 토요일 아님 ✗')
                results['saturday_update'] = None
        # ──────────────────────────────────────────────────────────────────

        # ── 매일 오전 9시 로그 생성 직후 성능 분석 자동 갱신 ───────────────
        # auto_generation 성공 후 당일 성능 분석이 아직 안 됐으면 실행
        if config.get('enabled', True):
            auto_just_succeeded = results.get('auto_generation') is True
            perf_not_done_today = should_run_today(config, 'last_perf_analysis')

            if force_run or (auto_just_succeeded and perf_not_done_today):
                logger.info('▶ 오전 9시 로그 생성 후 성능 분석 자동 실행')
                success = run_performance_analysis(excel_path)
                config['last_perf_analysis'] = datetime.now(KST).isoformat()
                save_auto_schedule_config(config)
                results['perf_analysis'] = success
            else:
                if not auto_just_succeeded:
                    logger.info('  - 성능 분석: 오늘 로그 생성 미완료 → 건너뜀')
                else:
                    logger.info('  - 성능 분석: 오늘 이미 실행됨 ✗')
                results['perf_analysis'] = None
        # ──────────────────────────────────────────────────────────────────

        # 결과 로깅
        for task_name, result in results.items():
            if result is not None:
                status = '성공' if result else '실패'
                logger.info('  %s: %s' % (task_name, status))
            else:
                if force_run:
                    logger.info('  %s: 테스트 모드에서 건너뜀' % task_name)
                else:
                    logger.info('  %s: 조건 미충족 또는 이미 실행됨' % task_name)

    except Exception as e:
        logger.error('스케줄 체크 중 오류: %s' % e, exc_info=True)


def run_once(force_run: bool = False):
    '''즉시 1회 실행 후 종료 (--once 옵션용)'''
    logger.info('=' * 60)
    logger.info('스케줄러 1회 실행 모드 (--once)')
    if force_run:
        logger.info('[테스트 모드] force_run=True - 모든 스케줄 무조건 실행')
    else:
        logger.info('[일반 모드] 오늘 이미 실행했으면 건너뜀')
    logger.info('=' * 60)
    run_scheduler_check(force_run=force_run)
    logger.info('=' * 60)
    logger.info('실행 완료 - 종료')


def run_daemon():
    '''백그라운드 데몬 모드'''
    logger.info('=' * 60)
    logger.info('독립형 스케줄러 데몬 시작')
    logger.info('PID: %d' % os.getpid())
    logger.info('실행 시간: 매분 정시 체크')
    logger.info('  - 오전 06시: Manus AI 번호 추출 (1~5순위, 수동 로그에만 저장)')
    logger.info('  - 오전 09시: 패턴/확률/수동 추천 100개씩 생성 (각 로그에 저장)')
    logger.info('  - 윈도우: 실행 시간 ± 120분 내')
    logger.info('Ctrl+C 로 종료')
    logger.info('=' * 60)

    def signal_handler(sig, frame):
        logger.info('스케줄러 종료 요청됨 - 안전 종료')
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    last_minute = -1
    while True:
        now = datetime.now(KST)
        current_minute = now.minute

        if current_minute != last_minute:
            last_minute = current_minute
            run_scheduler_check()

        time.sleep(30)


def main():
    '''메인 함수'''
    import argparse

    parser = argparse.ArgumentParser(description='독립형 로또 스케줄러 (웹 로그인 불필요)')
    parser.add_argument('--once', action='store_true', help='1회만 실행 후 종료')
    parser.add_argument('--test', action='store_true', help='테스트 모드 (무조건 실행, 조건 무시)')
    args = parser.parse_args()

    if args.test:
        run_once(force_run=True)
    elif args.once:
        run_once(force_run=False)
    else:
        run_daemon()


if __name__ == '__main__':
    main()