# -*- coding: utf-8 -*-
import json
from collections import defaultdict

runs = defaultdict(list)
with open('logs/prediction_log.jsonl', 'r', encoding='utf-8') as f:
    for line in f:
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            run_id = data.get('run_id', data.get('timestamp', 'unknown'))
            runs[run_id].append(data)
        except Exception as e:
            pass

print(f'총 {len(runs)}개의 분석 실행 로그 있음')

# 가장 큰 rank 찾기
max_rank = 0
for run_id, entries in runs.items():
    for e in entries:
        max_rank = max(max_rank, e.get('candidate_rank', 0))
print(f'최대 candidate_rank: {max_rank}')

# 최근 Run의 top candidates 확인
sorted_runs = sorted(runs.keys(), reverse=True)
for run_id in sorted_runs[:5]:
    entries = sorted(runs[run_id], key=lambda x: x.get('candidate_rank', 0))
    top5 = [e for e in entries if e.get('candidate_rank', 0) <= 5]
    print(f'\n=== {run_id} ===')
    for e in top5:
        nums = e.get('numbers', [])
        rank = e.get('candidate_rank', 0)
        score = e.get('score', 0)
        print(f'  Rank {rank}: {nums} (score: {score:.2f})')

# 순위 변동 분석
print('\n=== 순위 변동 분석 ===')
# 각 회차별로 1순위가 어떻게 변했는지
by_target_round = defaultdict(list)
for run_id, entries in runs.items():
    for e in entries:
        target = e.get('target_round', 0)
        by_target_round[target].append((run_id, e))

for target_round in sorted(by_target_round.keys(), reverse=True)[:2]:
    entries = by_target_round[target_round]
    print(f'\n{target_round}회차 대상 분석들:')
    for run_id, e in entries:
        rank = e.get('candidate_rank', 0)
        if rank <= 5:
            nums = e.get('numbers', [])
            score = e.get('score', 0)
            print(f'  Run: {run_id[:30]}... -> Rank {rank}: {nums} (score: {score:.2f})')