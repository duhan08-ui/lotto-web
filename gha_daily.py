#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gha_daily.py - GitHub Actions 매일 오전 9시 루틴
1. 패턴 추천 100개 생성 → Supabase 저장
2. 확률 추천 100개 생성 → Supabase 저장
3. 수동(안티패턴) 100개 생성 → Supabase 저장
4. performance_analyzer 실행 → reports/performance_analysis.json 갱신
   (Supabase에서 기존 로그를 받아와 당첨번호와 비교)

실행: python3 gha_daily.py
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

# 프로젝트 루트를 sys.path에 추가
PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

KST = ZoneInfo('Asia/Seoul')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [GHA-DAILY] %(levelname)s %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger('GHA_Daily')


def main():
    logger.info('=' * 60)
    logger.info('GitHub Actions 일일 루틴 시작')
    logger.info('실행 시각: %s (KST)' % datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S'))
    logger.info('=' * 60)

    # Supabase 연동 확인
    url = os.getenv('LOTTO_SUPABASE_URL', '')
    key = os.getenv('LOTTO_SUPABASE_KEY', '')
    if not url or not key:
        logger.error('LOTTO_SUPABASE_URL / LOTTO_SUPABASE_KEY 환경변수 미설정')
        logger.error('GitHub 저장소 Settings → Secrets and variables → Actions 에서 추가하세요.')
        sys.exit(1)
    logger.info('Supabase 연동 확인: %s' % url[:40])

    excel_path = PROJECT_DIR / 'lotto.xlsx'
    if not excel_path.exists():
        logger.error('lotto.xlsx 없음: %s' % excel_path)
        sys.exit(1)

    # ── 0. 당첨번호 최신화 (lotto.xlsx 갱신) ───────────────────────────
    # 저장소의 lotto.xlsx가 오래되면 회차 계산이 어긋나고 StatScore가
    # 최신 추첨을 반영하지 못함 → 매일 루틴 시작 시 최신 당첨번호 수집.
    # (실패해도 get_round_context의 날짜 기반 보정으로 회차는 올바르게 계산됨)
    import importlib.util
    try:
        spec_u = importlib.util.spec_from_file_location('update_lotto', PROJECT_DIR / 'update_lotto.py')
        ul = importlib.util.module_from_spec(spec_u)
        spec_u.loader.exec_module(ul)
        _df_updated, _update_msg = ul.update_excel(excel_path)
        logger.info('당첨번호 갱신: %s' % _update_msg)
    except Exception as e:
        logger.warning('당첨번호 갱신 실패 (회차는 날짜 기반 보정으로 계산됨): %s' % e)

    # ── 1. 로그 디렉토리 준비 ──────────────────────────────────────────
    from log_utils import ensure_runtime_dirs, bootstrap_remote_runtime_if_needed
    bootstrap_remote_runtime_if_needed(PROJECT_DIR)
    log_dir, report_dir = ensure_runtime_dirs(PROJECT_DIR)
    logger.info('로그 디렉토리: %s' % log_dir)

    # ── 2. 자동 로그 생성 (패턴 100 + 확률 100 + 수동 100) ─────────────
    import importlib.util

    spec = importlib.util.spec_from_file_location('auto_log_generator', PROJECT_DIR / 'auto_log_generator.py')
    alg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(alg)

    logger.info('로그 생성 시작 (패턴 100 + 확률 100 + 수동 100)...')
    success = alg.generate_auto_logs(
        PROJECT_DIR, excel_path,
        prediction_count=100,
        probability_count=100,
        manual_count=100,
        force_regenerate=False,  # 오늘 이미 실행했으면 건너뜀
    )
    if success:
        logger.info('로그 생성 완료')
    else:
        logger.error('로그 생성 실패')

    # ── 2-b. 오늘 TOP5 추출 → top5_log.jsonl 저장 + top5.json 갱신 ───────
    logger.info('TOP5 로그 저장 시작...')
    try:
        from zoneinfo import ZoneInfo as _ZI
        from datetime import datetime as _dt
        import json as _json
        _KST = _ZI('Asia/Seoul')
        today_kst = _dt.now(_KST).strftime('%Y-%m-%d')

        # log_utils에서 top5 저장 함수 로드
        spec_lu = importlib.util.spec_from_file_location('log_utils', PROJECT_DIR / 'log_utils.py')
        lu2 = importlib.util.module_from_spec(spec_lu)
        spec_lu.loader.exec_module(lu2)

        # lotto_core 로드 (predictor 재사용)
        spec_lc = importlib.util.spec_from_file_location('lotto_core', PROJECT_DIR / 'lotto_core.py')
        lc = importlib.util.module_from_spec(spec_lc)
        spec_lc.loader.exec_module(lc)

        predictor2 = lc.LottoPredictor(str(excel_path))
        ctx = lu2.get_round_context(excel_path)
        source_round = ctx.get('source_round') or 0
        target_round = ctx.get('target_round') or (source_round + 1)
        sim_count = 5000

        # 패턴 TOP5 생성 & 저장
        pattern_top5 = predictor2.predict(sets=5, simulation_count=sim_count)
        for i, r in enumerate(pattern_top5, 1):
            lu2.persist_top5_log_record(
                base_dir=PROJECT_DIR,
                log_type='prediction',
                candidate_rank=i,
                numbers=[int(n) for n in r['sorted']],
                score=float(r.get('score', 0)),
                source_round=source_round,
                target_round=target_round,
                created_date_kst=today_kst,
            )
        logger.info('  패턴 TOP5 저장 완료')

        # 확률 TOP5 생성 & 저장
        prob_top5 = predictor2.predict_probability_only(sets=5, simulation_count=sim_count)
        for i, r in enumerate(prob_top5, 1):
            lu2.persist_top5_log_record(
                base_dir=PROJECT_DIR,
                log_type='probability',
                candidate_rank=i,
                numbers=[int(n) for n in r['sorted']],
                score=float(r.get('score', 0)),
                source_round=source_round,
                target_round=target_round,
                created_date_kst=today_kst,
            )
        logger.info('  확률 TOP5 저장 완료')

        # 수동 TOP5 생성 & 저장
        _generate_anti_pattern_manual = lc._generate_anti_pattern_manual_numbers
        manual_top5 = []
        previous_numbers = None
        for rank in range(1, 6):
            numbers = _generate_anti_pattern_manual(
                excel_path=excel_path, previous_numbers=previous_numbers
            )
            previous_numbers = numbers
            result = predictor2.score_manual_combination(numbers)
            score = float(result.get('best_score', result.get('score', 0)))
            lu2.persist_top5_log_record(
                base_dir=PROJECT_DIR,
                log_type='manual',
                candidate_rank=rank,
                numbers=[int(n) for n in numbers],
                score=score,
                source_round=source_round,
                target_round=target_round,
                created_date_kst=today_kst,
            )
            manual_top5.append({'rank': rank, 'numbers': list(numbers), 'score': score})
        logger.info('  수동 TOP5 저장 완료')

        # round_XXXX_top5.json 갱신 (created_date_kst 포함 → 만료 감지용)
        reports_dir = PROJECT_DIR / 'reports'
        reports_dir.mkdir(exist_ok=True)
        top5_path = reports_dir / ('round_%d_top5.json' % target_round)
        top5_data = {
            'generated_at': _dt.now(_KST).isoformat(),
            'created_date_kst': today_kst,
            'source_round': source_round,
            'target_round': target_round,
            'pattern_top5': [
                {'rank': i+1, 'numbers': r['sorted'], 'score': r.get('score', 0)}
                for i, r in enumerate(pattern_top5)
            ],
            'probability_top5': [
                {'rank': i+1, 'numbers': r['sorted'], 'score': r.get('score', 0)}
                for i, r in enumerate(prob_top5)
            ],
            'manual_top5': manual_top5,
        }
        with open(top5_path, 'w', encoding='utf-8') as fp:
            _json.dump(top5_data, fp, ensure_ascii=False, indent=2)
        logger.info('  top5.json 갱신 완료 → %s' % top5_path.name)

    except Exception as e:
        logger.error('TOP5 로그 저장 실패: %s' % e, exc_info=True)

    # ── 3. AI 지능형 추천 분석 (CompositeScore 기반 TOP5 재정렬) ──────────
    logger.info('AI 지능형 추천 분석 시작...')
    ai_success = False
    try:
        spec_ai = importlib.util.spec_from_file_location(
            'ai_intelligent_analyzer', PROJECT_DIR / 'ai_intelligent_analyzer.py'
        )
        ai_mod = importlib.util.module_from_spec(spec_ai)
        spec_ai.loader.exec_module(ai_mod)

        ai_analyzer = ai_mod.AIIntelligentAnalyzer(PROJECT_DIR)
        ai_result = ai_analyzer.run_analysis()

        # 결과 요약 로그
        for line in ai_result.splitlines():
            if any(k in line for k in ('순위:', 'CompositeScore', '누적 로그 반영', '생성일시', '신규성')):
                logger.info('  %s' % line.strip())
        ai_success = True
        logger.info('AI 지능형 추천 분석 완료')
    except Exception as e:
        logger.error('AI 지능형 추천 분석 실패: %s' % e, exc_info=True)

    # ── 3-b. is_intelligent 레코드 생성 검증 (대시보드 표시 보장) ─────────
    try:
        import json as _vj
        from log_utils import get_round_context as _grc
        _tr = (_grc(PROJECT_DIR / 'lotto.xlsx') or {}).get('target_round') or 0
        _cnt = 0
        _pred_log = PROJECT_DIR / 'logs' / 'prediction_log.jsonl'
        if _pred_log.exists():
            with open(_pred_log, 'r', encoding='utf-8') as _f:
                for _line in _f:
                    _line = _line.strip()
                    if not _line:
                        continue
                    try:
                        _d = _vj.loads(_line)
                        if _d.get('is_intelligent') and _d.get('target_round') == _tr:
                            _cnt += 1
                    except Exception:
                        continue
        logger.info('검증: %d회차 is_intelligent 레코드 %d건 (5건 필요)' % (_tr, _cnt))
        if _cnt < 5:
            ai_success = False
            logger.error('❌ AI 지능형 레코드가 부족합니다. 대시보드에 AI 추천이 표시되지 않습니다!')
    except Exception as e:
        logger.error('is_intelligent 검증 실패: %s' % e)

    # ── 4. 성능 분석 (예측 로그 ↔ 실제 당첨번호 비교) ─────────────────
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
        logger.info('성능 분석 완료:')
        logger.info('  분석 회차: %d회' % t.get('rounds', 0))
        logger.info('  3등(5개일치): %d건' % t.get('total_3rd_hits', 0))
        logger.info('  4등(4개일치): %d건' % t.get('total_4th_hits', 0))
        logger.info('  5등(3개일치): %d건' % t.get('total_5th_hits', 0))
    except Exception as e:
        logger.error('성능 분석 실패: %s' % e, exc_info=True)

    # ── 5. 결과 요약 ──────────────────────────────────────────────────
    logger.info('=' * 60)
    logger.info('일일 루틴 완료: %s' % datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S'))
    logger.info('=' * 60)

    # AI 지능형 분석이 실패했으면 워크플로우를 실패로 표시
    # → Actions 화면에서 빨간색으로 즉시 인지 가능 (기존엔 실패해도 초록색이었음)
    if not ai_success:
        logger.error('AI 지능형 추천 분석이 실패했으므로 종료 코드 1로 종료합니다.')
        logger.error('위 로그의 "AI 지능형 추천 분석 실패" Traceback을 확인하세요.')
        sys.exit(1)


if __name__ == '__main__':
    main()
