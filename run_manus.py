#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from datetime import datetime
from pathlib import Path
import sys

project_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(project_dir))

from manus_ai_analyzer import ManusAIAnalyzer

print('=' * 60)
print('Manus AI 분석기 실행 - ' + datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
print('=' * 60)

analyzer = ManusAIAnalyzer(project_dir)

print('\n[1] Manus API 호출 중...')
result = analyzer.run_analysis(use_manus=True, save_results=True)

print('\n[2] 분석 결과:')
print('  성공 여부:', result['success'])
print('  추천 세트 수:', len(result['recommended_sets']))

if result['success']:
    print('\n[3] 추천 번호 Top 5:')
    for i, nums in enumerate(result['recommended_sets'], 1):
        nums_str = ', '.join('{:02d}'.format(n) for n in sorted(nums))
        print('  ' + str(i) + '순위: ' + nums_str)
else:
    print('\n  원본 응답:')
    print(result['raw_response'][:500] if result['raw_response'] else '응답 없음')

print('\n[4] 로그 파일 상태 확인:')
import os
for f in ['prediction_log.jsonl', 'probability_log.jsonl', 'manual_score_log.jsonl']:
    path = project_dir / 'logs' / f
    size = os.path.getsize(path) if path.exists() else 0
    records = 0
    if path.exists() and size > 0:
        with open(path, 'r', encoding='utf-8') as file:
            records = sum(1 for line in file if line.strip())
    print('  ' + f + ': ' + str(size) + ' bytes, ' + str(records) + ' records')

print('\n[5] 보고서 파일 확인:')
for f in ['intelligent_analysis_report.md', 'weekly_ai_recommendation.txt', 'recommended_sets.json']:
    path = project_dir / 'reports' / f
    if path.exists():
        print('  ' + f + ': 존재함')
        if f.endswith('.md') or f.endswith('.txt'):
            with open(path, 'r', encoding='utf-8') as file:
                content = file.read(300)
                print('    미리보기: ' + content[:200] + '...')
    else:
        print('  ' + f + ': 없음')

print('\n' + '=' * 60)
print('실행 완료')
print('=' * 60)