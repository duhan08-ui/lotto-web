# -*- coding: utf-8 -*-
import json
import pandas as pd
import numpy as np
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

class HybridWinningAnalyzer:
    def __init__(self, project_dir):
        self.project_dir = Path(project_dir)
        self.lotto_xlsx = self.project_dir / 'lotto.xlsx'
        self.prediction_log = self.project_dir / 'logs' / 'prediction_log.jsonl'
        self.output_dir = self.project_dir / 'reports'
        self.output_dir.mkdir(exist_ok=True)
        
    def load_lotto_history(self, limit=200):
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
                history.append({'round': len(history)+1, 'numbers': sorted(nums)})
        return history
    
    def load_predictions(self):
        predictions = []
        with open(self.prediction_log, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    predictions.append(data)
                except:
                    pass
        return predictions
    
    def calculate_match_count(self, pred_nums, actual_nums):
        return len(set(pred_nums) & set(actual_nums))
    
    def analyze_match_history(self):
        history = self.load_lotto_history()
        predictions = self.load_predictions()
        
        if not predictions:
            print('예측 로그가 없습니다.')
            return None
        
        runs = defaultdict(list)
        for p in predictions:
            run_id = p.get('run_id', p.get('timestamp', 'unknown'))
            runs[run_id].append(p)
        
        run_predictions = {}
        for run_id, entries in runs.items():
            top5 = sorted([e for e in entries if e.get('candidate_rank', 0) <= 5], 
                         key=lambda x: x.get('candidate_rank', 0))
            run_predictions[run_id] = top5
        
        print('=' * 60)
        print('ANALYSIS: 당첨 결과 vs 추천 번호 매칭 분석')
        print('=' * 60)
        
        match_stats = {'rank5': [], 'rank4': [], 'rank3': [], 'rank2': []}
        recent_history = history[:20]
        
        print('')
        print('최근 ' + str(len(recent_history)) + '회차 분석 결과:')
        print('-' * 60)
        
        for hist in recent_history:
            round_num = hist['round']
            actual = hist['numbers']
            
            best_match = 0
            best_pred = None
            
            for run_id, preds in run_predictions.items():
                for p in preds:
                    pred_nums = p.get('numbers', [])
                    if pred_nums:
                        matches = self.calculate_match_count(pred_nums, actual)
                        if matches > best_match:
                            best_match = matches
                            best_pred = pred_nums
            
            if best_match >= 3:
                print('회차 ' + str(round_num) + ': 실제 ' + str(actual) + ' vs 최고매칭 ' + str(best_match) + '개')
                if best_match == 5:
                    match_stats['rank5'].append(round_num)
                elif best_match == 4:
                    match_stats['rank4'].append(round_num)
                elif best_match == 3:
                    match_stats['rank3'].append(round_num)
        
        r5 = len(match_stats['rank5'])
        r4 = len(match_stats['rank4'])
        r3 = len(match_stats['rank3'])
        print('')
        print('4등(5개 일치) 달성: ' + str(r5) + '회')
        print('5등(4개 일치) 달성: ' + str(r4) + '회')
        print('기타(3개 일치): ' + str(r3) + '회')
        
        return match_stats, run_predictions, recent_history

if __name__ == '__main__':
    analyzer = HybridWinningAnalyzer(Path(__file__).resolve().parent)
    result = analyzer.analyze_match_history()