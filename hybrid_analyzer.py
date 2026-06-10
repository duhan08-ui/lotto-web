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
        
        # run_id별로 그룹화
        runs = defaultdict(list)
        for p in predictions:
            run_id = p.get('run_id', p.get('timestamp', 'unknown'))
            runs[run_id].append(p)
        
        # 각 run의 예측 번호 가져오기 (상위 5개)
        run_predictions = {}
        for run_id, entries in runs.items():
            top5 = sorted([e for e in entries if e.get('candidate_rank', 0) <= 5], 
                         key=lambda x: x.get('candidate_rank', 0))
            run_predictions[run_id] = top5
        
        # 실제 회차 결과와 매칭 분석
        # 가장 최근 회차와 예측 비교
        print('=' * 60)
        print('📊 당첨 결과 vs 추천 번호 매칭 분석')
        print('=' * 60)
        
        match_stats = {
            'rank5': [],  # 5개 맞은 횟수 (4등)
            'rank4': [],  # 4개 맞은 횟수 (5등)
            'rank3': [],  # 3개 맞은 횟수
            'rank2': [],  # 2개 맞은 횟수
        }
        
        # 최근 20회차 분석
        recent_history = history[:20]
        
        print(f'\n최근 {len(recent_history)}회차 분석 결과:')
        print('-' * 60)
        
        for hist in recent_history:
            round_num = hist['round']
            actual = hist['numbers']
            
            # 모든 런에서 이 회차 예측한 것들 찾기
            best_match = 0
            best_pred = None
            
            for run_id, preds in run_predictions.items():
                target_round = None
                for p in preds:
                    if p.get('target_round'):
                        target_round = p.get('target_round')
                        break
                
                # 예측 대상 회차가 맞는지 확인
                # 여기서는 예측 수와 실제 번호 매칭만 확인
                for p in preds:
                    pred_nums = p.get('numbers', [])
                    if pred_nums:
                        matches = self.calculate_match_count(pred_nums, actual)
                        if matches > best_match:
                            best_match = matches
                            best_pred = pred_nums
            
            if best_match >= 3:
                print(f'회차 {round_num}: 실제 {actual} vs 최고매칭 {best_match}개')
                if best_match == 5:
                    match_stats['rank5'].append(round_num)
                elif best_match == 4:
                    match_stats['rank4'].append(round_num)
                elif best_match == 3:
                    match_stats['rank3'].append(round_num)
        
        print(f'\n✅ 4등(5개 일치) 달성: {len(match_stats["rank5"])}회')
        print(f'✅ 5등(4개 일치) 달성: {len(match_stats["rank4"])}회')
        print(f'✅ 기타(3개 일치): {len(match_stats["rank3"])}회')
        
        return match_stats, run_predictions, recent_history

if __name__ == '__main__':
    analyzer = HybridWinningAnalyzer(Path(__file__).resolve().parent)
    result = analyzer.analyze_match_history()
    print(result)