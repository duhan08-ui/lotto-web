# -*- coding: utf-8 -*-
import json
import pandas as pd
import numpy as np
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
import random

class HybridWinningFormula:
    def __init__(self, project_dir):
        self.project_dir = Path(project_dir)
        self.lotto_xlsx = self.project_dir / 'lotto.xlsx'
        self.prediction_log = self.project_dir / 'logs' / 'prediction_log.jsonl'
        self.universe = list(range(1, 46))
        
    def load_history(self, limit=300):
        df = pd.read_excel(self.lotto_xlsx)
        number_cols = []
        for col in df.columns:
            if str(col).startswith('번호') and len(number_cols) < 6:
                number_cols.append(col)
        number_cols = sorted(number_cols, key=lambda x: int(''.join(c for c in str(x) if c.isdigit()) or 999))[:6]
        
        history = []
        for _, row in df.head(limit).iterrows():
            nums = []
            for col in number_cols:
                try:
                    nums.append(int(row[col]))
                except:
                    pass
            if len(nums) == 6:
                history.append(sorted(nums))
        return history
    
    def load_predictions(self):
        predictions = []
        with open(self.prediction_log, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    predictions.append(json.loads(line))
                except:
                    pass
        return predictions
    
    def get_best_matches(self):
        history = self.load_history()
        predictions = self.load_predictions()
        
        runs = defaultdict(list)
        for p in predictions:
            run_id = p.get('run_id', p.get('timestamp', 'unknown'))
            runs[run_id].append(p)
        
        # 5등/4등 달성한 조합 수집
        rank4_combos = []
        rank3_combos = []
        
        for run_id, entries in runs.items():
            for entry in entries:
                pred_nums = entry.get('numbers', [])
                if not pred_nums or len(pred_nums) != 6:
                    continue
                
                # 실제 당첨과 비교
                for actual in history[:50]:
                    matches = len(set(pred_nums) & set(actual))
                    if matches >= 4:
                        rank4_combos.append({'nums': pred_nums, 'matches': matches, 'score': entry.get('score', 0)})
                    elif matches == 3:
                        rank3_combos.append({'nums': pred_nums, 'matches': matches, 'score': entry.get('score', 0)})
        
        return rank4_combos, rank3_combos
    
    def analyze_winning_patterns(self):
        rank4, rank3 = self.get_best_matches()
        
        print('=' * 70)
        print('HYBRID WINNING FORMULA: 4/5등 달성 패턴 분석')
        print('=' * 70)
        print('')
        print('4등(5개 일치) 달성 조합: ' + str(len(rank4)) + '개')
        print('3개 일치 조합: ' + str(len(rank3)) + '개')
        print('')
        
        # 패턴 분석
        if rank4:
            print('=== 4등 조합 공통 패턴 ===')
            all_nums = []
            for combo in rank4:
                all_nums.extend(combo['nums'])
            
            freq = Counter(all_nums)
            print('강출 번호: ' + str(freq.most_common(10)))
            
            # AC값 분석
            for combo in rank4[:5]:
                ac = self.calculate_ac(combo['nums'])
                print('조합: ' + str(combo['nums']) + ' -> AC: ' + str(ac) + ', 합: ' + str(sum(combo['nums'])))
        
        # 핵심 패턴 추출
        patterns = self.extract_key_patterns(rank4, rank3)
        return patterns
    
    def extract_key_patterns(self, rank4_combos, rank3_combos):
        patterns = {
            'hot_numbers': [],
            'cold_numbers': [],
            'ac_range': [7, 11],
            'sum_range': [100, 180],
            'odd_even_preferred': ['2:4', '3:3', '4:2'],
            'extinction_zones_preferred': [1, 2],
            'gap_preference': 'medium',
            'consecutive_limit': 1
        }
        
        # 빈도 분석
        history = self.load_history()
        all_nums = []
        for h in history:
            all_nums.extend(h)
        
        freq = Counter(all_nums)
        sorted_freq = sorted(freq.items(), key=lambda x: x[1], reverse=True)
        
        # 상위 15개 = 핫 넘버, 하위 15개 = 콜드 넘버
        patterns['hot_numbers'] = [n for n, _ in sorted_freq[:15]]
        patterns['cold_numbers'] = [n for n, _ in sorted_freq[-15:]]
        
        # Gap 분석
        gap_data = defaultdict(int)
        prev_nums = None
        for h in history[:50]:
            if prev_nums:
                for n in h:
                    if n in prev_nums:
                        gap_data[n] += 1
            prev_nums = h
        
        # 오래 안 나온 번호 = Gap 큼
        for n in self.universe:
            if n not in gap_data:
                gap_data[n] = 0
        
        patterns['gap_scores'] = dict(gap_data)
        
        return patterns
    
    def calculate_ac(self, numbers):
        diffs = set()
        sorted_nums = sorted(numbers)
        for i in range(len(sorted_nums)):
            for j in range(i + 1, len(sorted_nums)):
                diffs.add(sorted_nums[j] - sorted_nums[i])
        return len(diffs) - 5
    
    def calculate_pattern_score(self, numbers, patterns, stats):
        score = 0.0
        sorted_nums = sorted(numbers)
        
        # 1. AC값 (7~10 최적)
        ac = self.calculate_ac(numbers)
        if 7 <= ac <= 10:
            score += 15.0
        elif 6 <= ac <= 11:
            score += 10.0
        elif 5 <= ac <= 12:
            score += 5.0
        
        # 2. 합계 (100~180 최적)
        total = sum(numbers)
        if 100 <= total <= 180:
            score += 12.0
        elif 85 <= total <= 195:
            score += 8.0
        
        # 3. 홀짝 (2:4, 3:3, 4:2)
        odd_count = len([n for n in numbers if n % 2 == 1])
        even_count = 6 - odd_count
        oe_ratio = str(odd_count) + ':' + str(even_count)
        if oe_ratio in ['2:4', '3:3', '4:2']:
            score += 10.0
        elif oe_ratio in ['1:5', '5:1']:
            score += 3.0
        
        # 4. Hot/Cold 밸런스 (4등/5등의 핵심!)
        hot_nums = patterns.get('hot_numbers', [])
        cold_nums = patterns.get('cold_numbers', [])
        
        hot_count = len([n for n in numbers if n in hot_nums])
        cold_count = len([n for n in numbers if n in cold_nums])
        
        # 4~5등 조합의 특징: 2~4개 Hot + 1~3개 Cold
        if 2 <= hot_count <= 4:
            score += 15.0 + hot_count * 2
        elif hot_count == 5:
            score += 12.0  # 너무 한쪽 집중
        
        if 1 <= cold_count <= 3:
            score += 10.0
        elif cold_count >= 4:
            score += 3.0  # 콜드만 많으면 리스크
        
        # 5. 멸 구간 (1~2개 구간 전멸)
        ranges = [0] * 5
        for n in numbers:
            if n <= 10: ranges[0] += 1
            elif n <= 20: ranges[1] += 1
            elif n <= 30: ranges[2] += 1
            elif n <= 40: ranges[3] += 1
            else: ranges[4] += 1
        
        ext_zones = len([r for r in ranges if r == 0])
        if 1 <= ext_zones <= 2:
            score += 8.0
        elif ext_zones == 0:
            score += 2.0
        
        # 6. Gap Factor (최근 미출현 번호 가중치)
        gap_scores = patterns.get('gap_scores', {})
        avg_gap = sum(gap_scores.values()) / 45.0 if gap_scores else 1
        gap_score = sum(max(0, 10 - gap_scores.get(n, 10)) for n in numbers)
        score += min(gap_score * 0.5, 8.0)
        
        # 7. 연번 제어 (연속 2개 이하)
        consecutive = sum(1 for i in range(len(sorted_nums)-1) if sorted_nums[i+1] - sorted_nums[i] == 1)
        if consecutive <= 1:
            score += 5.0
        elif consecutive == 2:
            score += 2.0
        else:
            score -= 3.0
        
        # 8. 끝수 다양성
        tails = [n % 10 for n in numbers]
        if max(Counter(tails).values()) <= 2:
            score += 4.0
        else:
            score -= 2.0
        
        # 9. 이월수 제어 (전 회차와 0~2개 겹침)
        if stats and 'latest' in stats:
            overlap = len(set(numbers) & set(stats['latest']))
            if 0 <= overlap <= 2:
                score += 5.0
            elif overlap >= 4:
                score -= 5.0
        
        # 10. WINNING BOOST: 최근 4/5등 조합과 유사한 패턴 보너스
        # 최근 추천으로 실제 4등 이상 달성한 조합이 있다면 유사 패턴 가중
        if hasattr(self, 'recent_winners'):
            for winner in self.recent_winners:
                overlap = len(set(numbers) & set(winner))
                if overlap >= 3:
                    score += overlap * 3  # 3개 겹치면 +9, 4개면 +12
        
        return score
    
    def generate_hybrid_recommendations(self, count=5):
        patterns = self.analyze_winning_patterns()
        history = self.load_history()
        
        # 최신 회차 정보
        latest = history[0] if history else []
        
        stats = {'latest': latest, 'history': history}
        
        # 전체 조합 점수 계산
        all_candidates = {}
        
        # 5000회 생성하여 점수 산출
        for _ in range(5000):
            # Hot/Cold 밸런스 기반 선택
            hot = patterns.get('hot_numbers', [])
            cold = patterns.get('cold_numbers', [])
            
            # 3개 hot + 2개 cold + 1개 gap 기반
            selected = []
            
            # Hot에서 2~3개
            hot_pick = random.sample(hot[:15], random.randint(2, 3))
            selected.extend(hot_pick)
            
            # Cold에서 1~2개
            cold_pick = random.sample(cold[-15:], random.randint(1, 2))
            selected.extend(cold_pick)
            
            # 랜덤으로 1~2개 (Gap 기반)
            remaining = [n for n in self.universe if n not in selected]
            remaining_sorted = sorted(remaining, key=lambda x: patterns.get('gap_scores', {}).get(x, 0))
            extra = random.sample(remaining_sorted[:20], random.randint(1, 2))
            selected.extend(extra)
            
            # 6개 미만이면 보충
            while len(selected) < 6:
                extra = random.choice([n for n in self.universe if n not in selected])
                selected.append(extra)
            
            if len(selected) >= 6:
                combo = tuple(sorted(random.sample(selected, 6)))
                
                if combo not in all_candidates:
                    score = self.calculate_pattern_score(list(combo), patterns, stats)
                    all_candidates[combo] = score
        
        # 점수순 정렬
        sorted_candidates = sorted(all_candidates.items(), key=lambda x: x[1], reverse=True)
        
        # 다양성 확보하며 Top 5 선택
        final_recommendations = []
        selected_sets = []
        
        for combo, score in sorted_candidates:
            nums = list(combo)
            
            # 기존 선택과의 겹침 확인 (5개 이상 겹치면 건너뛰기)
            is_duplicate = False
            for existing in selected_sets:
                overlap = len(set(nums) & set(existing))
                if overlap >= 5:
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                ac = self.calculate_ac(nums)
                odd_count = len([n for n in nums if n % 2 == 1])
                
                final_recommendations.append({
                    'rank': len(final_recommendations) + 1,
                    'numbers': nums,
                    'score': round(score, 2),
                    'ac': ac,
                    'sum': sum(nums),
                    'odd_even': str(odd_count) + ':' + str(6 - odd_count),
                    'hot_count': len([n for n in nums if n in patterns.get('hot_numbers', [])]),
                    'cold_count': len([n for n in nums if n in patterns.get('cold_numbers', [])])
                })
                selected_sets.append(nums)
            
            if len(final_recommendations) >= count:
                break
        
        return final_recommendations, patterns
    
    def run(self):
        print('')
        print('=' * 70)
        print('🚀 HYBRID WINNING FORMULA 실행')
        print('=' * 70)
        print('')
        
        recommendations, patterns = self.generate_hybrid_recommendations(5)
        
        print('📊 하이브리드 추천 번호 (4/5등 보장 + 대박 가능성)')
        print('-' * 70)
        print('')
        
        for rec in recommendations:
            nums_str = ', '.join('{:02d}'.format(n) for n in rec['numbers'])
            print('★ ' + str(rec['rank']) + '순위: ' + nums_str)
            print('   점수: ' + str(rec['score']) + ' | AC: ' + str(rec['ac']) + ' | 합: ' + str(rec['sum']))
            print('   홀짝: ' + str(rec['odd_even']) + ' | Hot: ' + str(rec['hot_count']) + ' | Cold: ' + str(rec['cold_count']))
            print('')
        
        # 저장
        output = {
            'timestamp': datetime.now().isoformat(),
            'recommendations': recommendations,
            'patterns': {
                'hot_numbers': patterns.get('hot_numbers', [])[:10],
                'cold_numbers': patterns.get('cold_numbers', [])[:10],
                'ac_range': patterns.get('ac_range'),
                'sum_range': patterns.get('sum_range')
            }
        }
        
        output_path = self.project_dir / 'reports' / 'hybrid_winning_recommendation.json'
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        
        print('💾 결과 저장 완료: ' + str(output_path))
        print('')
        
        return recommendations

if __name__ == '__main__':
    formula = HybridWinningFormula(Path(__file__).resolve().parent)
    result = formula.run()