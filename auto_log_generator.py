#!/usr/bin/env python3
# -*- coding: utf-8 -*-
'''
자동 로그 생성 모듈
매일 오전 9시에 패턴추천 100건 + 확률추천 100건 + 나혼자 당첨 100건을 자동으로 생성합니다.
중복 방지: 같은 날에는 추가 생성하지 않음 (스케줄러에서 이미 체크하지만 이중 안전장치)
'''

import json
import logging
import random
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from log_utils import persist_log_record, log_prediction_results, log_manual_score

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 한국 시간대
KST = ZoneInfo('Asia/Seoul')


def get_today() -> str:
    '''오늘 날짜 반환 (KST)'''
    return datetime.now(KST).strftime('%Y-%m-%d')


def get_log_count(log_dir: Path) -> int:
    '''달력에 표시되는 로그 건수 조회 (analysis 제외)'''
    db_path = log_dir / 'lotto_history.db'

    if not db_path.exists():
        return 0

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # analysis 로그 타입 제외하고 카운트
        cursor.execute('''
            SELECT COUNT(*) FROM log_records 
            WHERE log_type IN ('prediction', 'probability', 'manual')
        ''')

        count = cursor.fetchone()[0]
        conn.close()
        return count
    except Exception as e:
        logger.error('로그 건수 조회 실패: %s' % e)
        return 0


def check_today_logs(log_dir: Path, log_type: str) -> int:
    '''오늘 해당 로그 타입의 건수 조회 (KST 날짜 기준)
    
    [BUG FIX] timestamp는 UTC ISO string으로 저장되므로
    KST로 변환한 날짜와 비교해야 함
    '''
    log_file_map = {
        'prediction': 'prediction_log.jsonl',
        'probability': 'probability_log.jsonl',
        'manual': 'manual_score_log.jsonl'
    }

    filename = log_file_map.get(log_type)
    if not filename:
        return 0

    log_file = log_dir / filename
    if not log_file.exists():
        return 0

    today_kst = get_today()
    count = 0

    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    ts = record.get('timestamp', '')
                    if ts:
                        # UTC → KST 변환 후 날짜 비교
                        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                        kst_date = dt.astimezone(KST).strftime('%Y-%m-%d')
                        if kst_date == today_kst:
                            count += 1
                except Exception:
                    continue
    except Exception as e:
        logger.error('%s 로그 읽기 실패: %s' % (log_type, e))

    return count


def generate_random_numbers(count: int = 6, max_num: int = 45) -> list:
    '''무작위 번호 생성'''
    return sorted(random.sample(range(1, max_num + 1), count))


def load_schedule_config(log_dir: Path) -> dict:
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
    }

    if config_path.exists():
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return {**default_config, **json.load(f)}
        except Exception as e:
            logger.warning('설정 파일 로드 실패: %s' % e)

    return default_config


def save_schedule_config(log_dir: Path, config: dict):
    '''스케줄 설정 저장'''
    config_path = log_dir / 'auto_schedule_config.json'
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error('설정 파일 저장 실패: %s' % e)


def generate_auto_logs(
    project_dir: Path,
    excel_path: Path,
    target_count: int = 300,
    prediction_count: int = 100,
    probability_count: int = 100,
    manual_count: int = 100,
    force_regenerate: bool = False,
) -> bool:
    '''자동 로그 생성 메인 함수 (실제 분석 기반)

    Args:
        force_regenerate: True이면 오늘 데이터가 있어도 무조건 재생성 (기본값: False)
    '''
    try:
        project_dir = Path(project_dir)
        excel_path = Path(excel_path)
        log_dir = project_dir / 'logs'

        # 로그 디렉토리 생성
        log_dir.mkdir(parents=True, exist_ok=True)

        # 설정 파일 로드
        config = load_schedule_config(log_dir)

        # 오늘 날짜 확인 (KST 기준)
        today = get_today()
        last_run = config.get('last_run', '')

        # 오늘 이미 실행했는지 확인 (이중 안전장치)
        if not force_regenerate:
            # [BUG FIX] last_run이 ISO timezone string일 때 KST 날짜로 올바르게 변환
            last_run_date = ''
            if last_run:
                try:
                    dt = datetime.fromisoformat(last_run)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=KST)
                    else:
                        dt = dt.astimezone(KST)
                    last_run_date = dt.strftime('%Y-%m-%d')
                except Exception:
                    last_run_date = last_run[:10] if last_run else ''

            if last_run_date == today:
                # 이미 오늘 실행했음 - 실제 로그 건수도 확인
                today_pred = check_today_logs(log_dir, 'prediction')
                today_prob = check_today_logs(log_dir, 'probability')
                today_manual = check_today_logs(log_dir, 'manual')
                logger.info(
                    '오늘(%s) 이미 자동 생성 실행 완료: 패턴 %d건, 확률 %d건, 수동 %d건' % (
                        today, today_pred, today_prob, today_manual
                    )
                )
                logger.info('추가 생성을 건너뜁니다. (force_regenerate=True 로 강제 재생성 가능)')
                return True

        # 현재 로그 건수 확인 (로그 기록용)
        current_count = get_log_count(log_dir)
        logger.info('현재 누적 로그 건수: %d' % current_count)

        # 매일 요청된 건수만큼 신규 생성
        logger.info(
            '신규 생성할 로그 건수: 패턴 %d, 확률 %d, 수동 %d' % (
                prediction_count, probability_count, manual_count
            )
        )

        # lotto_core 동적 로드 (streamlit 의존성 없는 독립 모듈)
        import sys
        import importlib.util
        if str(project_dir) not in sys.path:
            sys.path.insert(0, str(project_dir))

        # lotto_core.py 경로: project_dir에 없으면 auto_log_generator.py와 같은 디렉토리
        core_path = project_dir / 'lotto_core.py'
        if not core_path.exists():
            core_path = Path(__file__).resolve().parent / 'lotto_core.py'
        if not core_path.exists():
            raise FileNotFoundError(f'lotto_core.py를 찾을 수 없습니다: {core_path}')
        spec = importlib.util.spec_from_file_location('lotto_core', core_path)
        core_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(core_module)
        LottoPredictor = core_module.LottoPredictor
        _generate_anti_pattern_manual_numbers = core_module._generate_anti_pattern_manual_numbers

        # 분석기 초기화
        predictor = LottoPredictor(str(excel_path))
        simulation_count = 5000  # 자동 생성용 시뮬레이션 횟수

        generated_pred = 0
        generated_prob = 0
        generated_manual = 0

        # ── 패턴추천 로그 생성 (실제 분석 기반) ──
        pred_to_gen = max(0, int(prediction_count or 0))
        if pred_to_gen > 0:
            logger.info('패턴 추천 번호 %d개 생성 중...' % pred_to_gen)
            pattern_results = predictor.predict(sets=pred_to_gen, simulation_count=simulation_count)
            log_prediction_results(
                base_dir=project_dir,
                excel_path=excel_path,
                predictor=predictor,
                results=pattern_results,
                log_type='prediction',
                simulation_count=simulation_count
            )
            generated_pred = len(pattern_results)
            logger.info('  → prediction_log.jsonl 에 %d건 저장 완료' % generated_pred)

        # ── 확률추천 로그 생성 (실제 분석 기반) ──
        prob_to_gen = max(0, int(probability_count or 0))
        if prob_to_gen > 0:
            logger.info('확률 추천 번호 %d개 생성 중...' % prob_to_gen)
            prob_results = predictor.predict_probability_only(sets=prob_to_gen, simulation_count=simulation_count)
            log_prediction_results(
                base_dir=project_dir,
                excel_path=excel_path,
                predictor=predictor,
                results=prob_results,
                log_type='probability',
                simulation_count=simulation_count
            )
            generated_prob = len(prob_results)
            logger.info('  → probability_log.jsonl 에 %d건 저장 완료' % generated_prob)

        # ── 나혼자 당첨(수동) 로그 생성 ──
        manual_to_gen = max(0, int(manual_count or 0))
        if manual_to_gen > 0:
            logger.info('나혼자 당첨 번호 %d개 생성 중...' % manual_to_gen)
            previous_numbers = None
            for rank in range(1, manual_to_gen + 1):
                numbers = _generate_anti_pattern_manual_numbers(
                    excel_path=excel_path, previous_numbers=previous_numbers
                )
                previous_numbers = numbers
                result = predictor.score_manual_combination(numbers)
                log_manual_score(
                    base_dir=project_dir,
                    excel_path=excel_path,
                    predictor=predictor,
                    numbers=numbers,
                    result=result,
                    candidate_rank=rank,
                )
            generated_manual = manual_to_gen
            logger.info('  → manual_score_log.jsonl 에 %d건 저장 완료' % generated_manual)

        total_generated = generated_pred + generated_prob + generated_manual
        logger.info(
            '자동 로그 생성 완료: 총 %d건 (패턴 %d, 확률 %d, 수동 %d)' % (
                total_generated, generated_pred, generated_prob, generated_manual
            )
        )

        # [BUG FIX] 성공 시에만 last_run 업데이트 (실패 시 다음날 재실행 가능)
        # standalone_scheduler에서도 last_run을 저장하므로 여기서는 저장하지 않음
        # (standalone_scheduler가 최종 저장하여 중복 저장 방지)

        return True

    except Exception as e:
        logger.error('자동 로그 생성 실패: %s' % e, exc_info=True)
        return False


if __name__ == '__main__':
    # 테스트 실행
    project_dir = Path(__file__).resolve().parent
    excel_path = project_dir / 'lotto.xlsx'

    success = generate_auto_logs(project_dir, excel_path, force_regenerate=True)
    print('자동 로그 생성 %s' % ('성공' if success else '실패'))
