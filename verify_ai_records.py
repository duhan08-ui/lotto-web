#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_ai_records.py — AI 지능형 추천 레코드 진단 스크립트

Supabase(또는 로컬 logs/)에 어떤 회차의 로그/AI 추천이 존재하는지 한눈에 확인합니다.
"대시보드에 AI 추천이 안 나온다"고 할 때 어디서 끊겼는지 즉시 파악할 수 있습니다.

실행:
  python3 verify_ai_records.py

환경변수(있으면 Supabase 원격 조회, 없으면 로컬 logs/만 조회):
  LOTTO_SUPABASE_URL, LOTTO_SUPABASE_KEY, LOTTO_PERSISTENCE_BACKEND=supabase
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))


def main():
    from log_utils import (get_round_context, _persistence_config,
                           _fetch_remote_log_payloads)

    print('=' * 62)
    print('AI 지능형 추천 레코드 진단')
    print('=' * 62)

    # 1. 현재 회차 컨텍스트
    ctx = get_round_context(PROJECT_DIR / 'lotto.xlsx')
    print(f"lotto.xlsx 기준  : 마지막 회차 {ctx.get('source_round')} → "
          f"대상 회차 {ctx.get('target_round')}")

    # 2. Supabase 설정 여부
    config = _persistence_config(str(PROJECT_DIR.resolve()))
    remote_enabled = bool(config.get('enabled'))
    print(f"Supabase 연동    : {'활성화' if remote_enabled else '비활성화 (로컬 logs/만 조회)'}")

    # 3. 레코드 수집 (원격 우선, 실패 시 로컬)
    payloads = []
    source = '로컬 logs/'
    if remote_enabled:
        payloads = _fetch_remote_log_payloads(PROJECT_DIR)
        if payloads:
            source = 'Supabase 원격'
        else:
            print('⚠️  Supabase 조회 결과가 비어있거나 실패 → 로컬 logs/로 폴백')

    if not payloads:
        for name in ('prediction_log.jsonl', 'probability_log.jsonl',
                     'manual_score_log.jsonl'):
            p = PROJECT_DIR / 'logs' / name
            if not p.exists():
                continue
            with open(p, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        payloads.append(json.loads(line))
                    except Exception:
                        continue

    print(f'데이터 출처      : {source} (총 {len(payloads)}건)')
    print('-' * 62)

    # 4. 회차별 집계
    by_round = defaultdict(lambda: {'normal': 0, 'intelligent': 0,
                                    'dates': Counter()})
    for d in payloads:
        tr = d.get('target_round') or d.get('source_round') or 0
        key = 'intelligent' if d.get('is_intelligent') else 'normal'
        by_round[tr][key] += 1
        ts = str(d.get('timestamp') or d.get('logged_at_utc') or '')[:10]
        if ts:
            by_round[tr]['dates'][ts] += 1

    print(f"{'회차':>6} | {'일반로그':>8} | {'AI지능형':>8} | 일자별 건수")
    for tr in sorted(by_round):
        info = by_round[tr]
        dates = ', '.join(f'{d}:{c}' for d, c in sorted(info['dates'].items()))
        print(f"{tr:>6} | {info['normal']:>8} | {info['intelligent']:>8} | {dates}")

    # 5. 판정
    print('-' * 62)
    target = ctx.get('target_round') or 0
    intel = by_round.get(target, {}).get('intelligent', 0)
    normal = by_round.get(target, {}).get('normal', 0)
    if intel >= 5:
        print(f'✅ {target}회차 AI 지능형 레코드 {intel}건 존재 → 대시보드에 AI 추천 표시됨')
    elif normal > 0:
        print(f'❌ {target}회차 일반 로그는 {normal}건 있으나 AI 지능형 레코드가 없음')
        print('   → gha_daily.py의 "AI 지능형 추천 분석" 단계가 실패했거나 실행되지 않음')
        print('   → GitHub Actions 실행 로그에서 해당 단계의 에러를 확인하거나,')
        print('     로컬에서 `python3 ai_intelligent_analyzer.py` 를 직접 실행해 보세요.')
    else:
        print(f'❌ {target}회차 로그가 전혀 없음')
        print('   → gha_daily.py(로그 생성)가 아직 실행되지 않았거나 회차 인식이 어긋남')
    print('=' * 62)


if __name__ == '__main__':
    main()
