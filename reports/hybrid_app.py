# -*- coding: utf-8 -*-
import json
import pandas as pd
import numpy as np
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
import random

class HybridWinningSystem:
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
        if self.prediction_log.exists():
            with open(self.prediction_log, 'r', encoding='utf-8') as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        predictions.append(json.loads(line))
                    except:
                        pass
        return predictions
    
    def calculate_ac(self, numbers):
        diffs = set()
        sorted_nums = sorted(numbers)
        for i in range(len(sorted_nums)):
            for j in range(i + 1, len(sorted_nums)):
                diffs.add(sorted_nums[j] - sorted_nums[i])
        return len(diffs) - 5
    
    def analyze_past_success(self):
        history = self.load_history()
        predictions = self.load_predictions()
        
        runs = defaultdict(list)
        for p in predictions:
            run_id = p.get('run_id', p.get('timestamp', 'unknown'))
            runs[run_id].append(p)
        
        match_result = {'rank3': 0, 'rank4': 0, 'rank5': 0, 'rank6': 0}
        winning_combos = []
        
        recent = history[:50]
        
        for actual in recent:
            best_match = 0
            best_pred = None
            
            for run_id, entries in runs.items():
                for entry in entries:
                    pred = entry.get('numbers', [])
                    if pred and len(pred) == 6:
                        matches = len(set(pred) & set(actual))
                        if matches > best_match:
                            best_match = matches
                            best_pred = pred
            
            if best_match == 6:
                match_result['rank6'] += 1
            elif best_match == 5:
                match_result['rank5'] += 1
                winning_combos.append({'actual': actual, 'pred': best_pred, 'matches': best_match})
            elif best_match == 4:
                match_result['rank4'] += 1
                winning_combos.append({'actual': actual, 'pred': best_pred, 'matches': best_match})
            elif best_match == 3:
                match_result['rank3'] += 1
        
        return match_result, winning_combos, history
    
    def extract_winning_formula(self, winning_combos, history):
        patterns = {
            'hot_numbers': [],
            'cold_numbers': [],
            'winning_hot': [],
            'gap_data': {}
        }
        
        all_nums = []
        for h in history[:150]:
            all_nums.extend(h)
        
        freq = Counter(all_nums)
        sorted_freq = sorted(freq.items(), key=lambda x: x[1], reverse=True)
        
        patterns['hot_numbers'] = [n for n, c in sorted_freq[:18]]
        patterns['cold_numbers'] = [n for n, c in sorted_freq[-18:]]
        
        if winning_combos:
            winning_nums = []
            for wc in winning_combos:
                winning_nums.extend(wc['pred'])
            
            win_freq = Counter(winning_nums)
            patterns['winning_hot'] = [n for n, c in win_freq.most_common(12)]
        
        gap_data = defaultdict(int)
        for i in range(len(history) - 1):
            for n in history[i]:
                if n in history[i + 1]:
                    gap_data[n] += 1
        
        patterns['gap_data'] = dict(gap_data)
        
        return patterns
    
    def calculate_score(self, numbers, patterns, stats):
        score = 0.0
        sorted_nums = sorted(numbers)
        
        hot_nums = patterns.get('hot_numbers', [])
        cold_nums = patterns.get('cold_numbers', [])
        win_hot = patterns.get('winning_hot', [])
        
        hot_count = len([n for n in numbers if n in hot_nums])
        cold_count = len([n for n in numbers if n in cold_nums])
        
        if 3 <= hot_count <= 4:
            score += 25.0
        elif hot_count == 2 or hot_count == 5:
            score += 15.0
        else:
            score += 8.0
        
        if 1 <= cold_count <= 2:
            score += 15.0
        elif cold_count == 0 or cold_count == 3:
            score += 8.0
        else:
            score += 3.0
        
        winning_hit = len([n for n in numbers if n in win_hot])
        score += winning_hit * 6.0
        
        ac = self.calculate_ac(numbers)
        if 7 <= ac <= 10:
            score += 18.0
        elif 6 <= ac <= 11:
            score += 12.0
        elif 5 <= ac <= 12:
            score += 6.0
        
        total = sum(numbers)
        if 100 <= total <= 170:
            score += 15.0
        elif 85 <= total <= 185:
            score += 10.0
        
        odd_count = len([n for n in numbers if n % 2 == 1])
        even_count = 6 - odd_count
        if str(odd_count) + ':' + str(even_count) in ['2:4', '3:3', '4:2']:
            score += 12.0
        elif str(odd_count) + ':' + str(even_count) in ['1:5', '5:1']:
            score += 5.0
        
        ranges = [0] * 5
        for n in numbers:
            if n <= 10: ranges[0] += 1
            elif n <= 20: ranges[1] += 1
            elif n <= 30: ranges[2] += 1
            elif n <= 40: ranges[3] += 1
            else: ranges[4] += 1
        
        ext_zones = len([r for r in ranges if r == 0])
        if 1 <= ext_zones <= 2:
            score += 10.0
        elif ext_zones == 0:
            score += 4.0
        
        gap_data = patterns.get('gap_data', {})
        gap_score = sum(max(0, 20 - gap_data.get(n, 20)) for n in numbers)
        score += min(gap_score * 0.3, 8.0)
        
        consecutive = sum(1 for i in range(len(sorted_nums)-1) if sorted_nums[i+1] - sorted_nums[i] == 1)
        if consecutive <= 1:
            score += 6.0
        elif consecutive == 2:
            score += 2.0
        else:
            score -= 3.0
        
        tails = [n % 10 for n in numbers]
        if max(Counter(tails).values()) <= 2:
            score += 5.0
        else:
            score -= 2.0
        
        if stats and 'latest' in stats:
            overlap = len(set(numbers) & set(stats['latest']))
            if overlap <= 2:
                score += 6.0
            elif overlap >= 4:
                score -= 5.0
        
        return score
    
    def generate_recommendations(self, count=5, iterations=15000):
        match_result, winning_combos, history = self.analyze_past_success()
        patterns = self.extract_winning_formula(winning_combos, history)
        
        stats = {'latest': history[0] if history else [], 'history': history}
        
        all_candidates = {}
        
        for _ in range(iterations):
            hot = patterns.get('hot_numbers', [])[:20]
            cold = patterns.get('cold_numbers', [])[-20:]
            win_hot = patterns.get('winning_hot', [])[:10]
            
            selected = []
            
            if win_hot:
                n1 = random.choice(win_hot[:8])
                selected.append(n1)
                if random.random() > 0.4:
                    n2 = random.choice([n for n in win_hot[:8] if n != n1])
                    selected.append(n2)
            
            remaining_hot = [n for n in hot if n not in selected]
            if remaining_hot:
                hot_picks = random.sample(remaining_hot[:12], min(2, len(remaining_hot)))
                selected.extend(hot_picks)
            
            remaining_cold = [n for n in cold if n not in selected]
            if remaining_cold:
                cold_picks = random.sample(remaining_cold[:12], min(2, len(remaining_cold)))
                selected.extend(cold_picks)
            
            while len(selected) < 6:
                extra = random.choice([n for n in self.universe if n not in selected])
                selected.append(extra)
            
            if len(selected) >= 6:
                combo = tuple(sorted(random.sample(selected, 6)))
                
                if combo not in all_candidates:
                    score = self.calculate_score(list(combo), patterns, stats)
                    all_candidates[combo] = score
        
        sorted_candidates = sorted(all_candidates.items(), key=lambda x: x[1], reverse=True)
        
        final_recommendations = []
        selected_sets = []
        
        for combo, score in sorted_candidates:
            nums = list(combo)
            
            is_duplicate = False
            for existing in selected_sets:
                if len(set(nums) & set(existing)) >= 5:
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                ac = self.calculate_ac(nums)
                odd_count = len([n for n in nums if n % 2 == 1])
                hot_nums = patterns.get('hot_numbers', [])
                win_hot = patterns.get('winning_hot', [])
                
                final_recommendations.append({
                    'rank': len(final_recommendations) + 1,
                    'numbers': nums,
                    'score': round(score, 2),
                    'ac': ac,
                    'sum': sum(nums),
                    'odd_even': str(odd_count) + ':' + str(6 - odd_count),
                    'hot_count': len([n for n in nums if n in hot_nums[:15]]),
                    'winning_hit': len([n for n in nums if n in win_hot[:10]]),
                    'cold_count': len([n for n in nums if n in patterns.get('cold_numbers', [])[-15:]])
                })
                selected_sets.append(nums)
            
            if len(final_recommendations) >= count:
                break
        
        return final_recommendations, patterns, match_result

def run_hybrid_analysis():
    project_dir = Path(__file__).resolve().parent
    system = HybridWinningSystem(project_dir)
    
    recommendations, patterns, match_result = system.generate_recommendations(5)
    
    result = {
        'match_result': match_result,
        'recommendations': recommendations,
        'patterns': {
            'hot_numbers': patterns.get('hot_numbers', [])[:15],
            'cold_numbers': patterns.get('cold_numbers', [])[-10:],
            'winning_hot': patterns.get('winning_hot', [])[:10]
        }
    }
    
    return result

if __name__ == '__main__':
    result = run_hybrid_analysis()
    print(json.dumps(result, ensure_ascii=False, indent=2))