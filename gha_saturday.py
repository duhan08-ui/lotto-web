#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gha_saturday.py - GitHub Actions 토요일 오후 9시 루틴
1. update_lotto.py → lotto.xlsx 최신 당첨번호 수집
2. performance_analyzer → 적중률 분석 갱신
3. B안: 회차 변경 감지 → TOP5 재생성 + reports/round_{N}_top5.json 저장

실행: python3 gha_saturday.py
환경변수:
  LOTTO_SUPABASE_URL  - Supabase 프로젝트 URL
  LOTTO_SUPABASE_KEY  - Supabase service role key
  LOTTO_PERSISTENCE_BACKEND=supabase
"""

import os
import sys
import logging
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

KST = ZoneInfo('Asia/Seoul')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [GHA-SAT] %(levelname)s %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger('GHA_Saturday')


def main():
    logger.info('=' * 60)
    logger.info('GitHub Actions 토요일 루틴 시작')
    logger.info('실행 시각: %s (KST)' % datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S'))
    logger.info('=' * 60)

    url = os.getenv('LOTTO_SUPABASE_URL', '')
    key = os.getenv('LOTTO_SUPABASE_KEY', '')
    if not url or not key:
        logger.error('LOTTO_SUPABASE_URL / LOTTO_SUPABASE_KEY 환경변수 미설정')
        sys.exit(1)
    logger.info('Supabase 연동 확인: %s' % url[:40])

    excel_path = PROJECT_DIR / 'lotto.xlsx'
    import importlib.util

    # ── 1. 최신 당첨번호 수집 (lotto.xlsx 갱신) ────────────────────────
    logger.info('당첨번호 수집 시작...')
    prev_round = _get_source_round(excel_path)
    try:
        spec = importlib.util.spec_from_file_location('update_lotto', PROJECT_DIR / 'update_lotto.py')
        ul = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ul)
        ul.update_excel(excel_path)
        new_round = _get_source_round(excel_path)
        logger.info('엑셀 갱신 완료: %s회 → %s회' % (prev_round, new_round))
    except Exception as e:
        logger.error('엑셀 갱신 실패: %s' % e)
        new_round = prev_round

    # ── 2. 성능 분석 ──────────────────────────────────────────────────
    from log_utils import ensure_runtime_dirs, bootstrap_remote_runtime_if_needed
    bootstrap_remote_runtime_if_needed(PROJECT_DIR)
    ensure_runtime_dirs(PROJECT_DIR)

    logger.info('성능 분석 시작...')
    try:
        spec2 = importlib.util.spec_from_file_location('performance_analyzer', PROJECT_DIR / 'performance_analyzer.py')
        pa = importlib.util.module_from_spec(spec2)
        spec2.loader.exec_module(pa)

        analyzer = pa.PerformanceAnalyzer(PROJECT_DIR)
        results = analyzer.analyze_all_rounds(max_rounds=None)
        metrics, all_results = analyzer.calculate_performance_metrics(results)
        patterns = analyzer.analyze_number_patterns(results)
        report = analyzer.generate_performance_report(metrics, all_results, patterns)
        analyzer.save_results(metrics, all_results, patterns, report)

        t = metrics['total']
        logger.info('성능 분석 완료: 3등 %d건 / 4등 %d건 / 5등 %d건' % (
            t.get('total_3rd_hits', 0),
            t.get('total_4th_hits', 0),
            t.get('total_5th_hits', 0),
        ))
    except Exception as e:
        logger.error('성능 분석 실패: %s' % e, exc_info=True)

    # ── 3. 회차 변경 감지 → TOP5 재생성 ──────────────────────────────
    if new_round and prev_round and int(new_round) != int(prev_round):
        logger.info('회차 변경 감지: %s → %s' % (prev_round, new_round))
        logger.info('TOP5 추천번호 재생성 시작...')
        try:
            spec3 = importlib.util.spec_from_file_location('lotto_core', PROJECT_DIR / 'lotto_core.py')
            lc = importlib.util.module_from_spec(spec3)
            spec3.loader.exec_module(lc)

            spec4 = importlib.util.spec_from_file_location('log_utils', PROJECT_DIR / 'log_utils.py')
            lu = importlib.util.module_from_spec(spec4)
            spec4.loader.exec_module(lu)

            predictor = lc.LottoPredictor(str(excel_path))
            sim_count = 8000

            pattern_top5 = predictor.predict(sets=5, simulation_count=sim_count)
            lu.log_prediction_results(
                base_dir=PROJECT_DIR, excel_path=excel_path, predictor=predictor,
                results=pattern_top5, log_type='prediction', simulation_count=sim_count,
            )

            prob_top5 = predictor.predict_probability_only(sets=5, simulation_count=sim_count)
            lu.log_prediction_results(
                base_dir=PROJECT_DIR, excel_path=excel_path, predictor=predictor,
                results=prob_top5, log_type='probability', simulation_count=sim_count,
            )

            # reports/round_{N}_top5.json 저장
            import json
            reports_dir = PROJECT_DIR / 'reports'
            reports_dir.mkdir(exist_ok=True)
            report_path = reports_dir / ('round_%d_top5.json' % (new_round + 1))
            report_data = {
                'generated_at': datetime.now(KST).isoformat(),
                'created_date_kst': datetime.now(KST).strftime('%Y-%m-%d'),
                'source_round': new_round,
                'target_round': new_round + 1,
                'pattern_top5': [
                    {'rank': i+1, 'numbers': r['sorted'], 'score': r.get('score', 0),
                     'ensemble_score': r.get('ensemble_score', 0)}
                    for i, r in enumerate(pattern_top5)
                ],
                'probability_top5': [
                    {'rank': i+1, 'numbers': r['sorted'], 'score': r.get('score', 0),
                     'ensemble_score': r.get('ensemble_score', 0)}
                    for i, r in enumerate(prob_top5)
                ],
            }
            with open(report_path, 'w', encoding='utf-8') as f:
                json.dump(report_data, f, ensure_ascii=False, indent=2)

            logger.info('TOP5 재생성 완료 → %s' % report_path.name)
            for i, r in enumerate(pattern_top5, 1):
                logger.info('  패턴 %d순위: %s (score: %.4f)' % (
                    i, ', '.join('%02d' % n for n in r['sorted']), r.get('score', 0)
                ))
            for i, r in enumerate(prob_top5, 1):
                logger.info('  확률 %d순위: %s (score: %.4f)' % (
                    i, ', '.join('%02d' % n for n in r['sorted']), r.get('score', 0)
                ))
        except Exception as e:
            logger.error('TOP5 재생성 실패: %s' % e, exc_info=True)
    else:
        logger.info('회차 변경 없음 (현재: %s회) → TOP5 재생성 건너뜀' % new_round)

    logger.info('=' * 60)
    logger.info('토요일 루틴 완료: %s' % datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S'))
    logger.info('=' * 60)


def _get_source_round(excel_path: Path):
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location('log_utils', PROJECT_DIR / 'log_utils.py')
        lu = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lu)
        return lu.get_round_context(excel_path).get('source_round')
    except Exception:
        return None


if __name__ == '__main__':
    main()
