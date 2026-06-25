# -*- coding: utf-8 -*-
import json
import pandas as pd
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

class WeeklyWinnerChecker:
    def __init__(self, project_dir):
        self.project_dir = Path(project_dir)
        self.lotto_xlsx = self.project_dir / 'lotto.xlsx'
        self.prediction_log = self.project_dir / 'logs' / 'prediction_log.jsonl'
        self.winner_log = self.project_dir / 'logs' / 'weekly_winner_log.jsonl'
        self.reports_dir = self.project_dir / 'reports'
        self.reports_dir.mkdir(exist_ok=True)
        self.universe = list(range(1, 46))
        
    def load_latest_lotto(self):
        df = pd.read_excel(self.lotto_xlsx)
        number_cols = []
        for col in df.columns:
            if str(col).startswith('번호') and len(number_cols) < 6:
                number_cols.append(col)
        number_cols = sorted(number_cols, key=lambda x: int(''.join(c for c in str(x) if c.isdigit()) or 999))[:6]
        
        if df.empty or len(number_cols) < 6:
            return None, None
        
        # 첫 번째 행이 최신 회차
        latest_row = df.iloc[0]
        round_num = len(df)  # 대략적인 회차
        
        # 회차 번호 추출 (컬럼명이 '1226회' 같은 경우)
        for col in df.columns:
            if '회' in str(col):
                try:
                    round_num = int(''.join(c for c in str(col) if c.isdigit()))
                    break
                except:
                    pass
        
        nums = []
        for col in number_cols:
            try:
                nums.append(int(latest_row[col]))
            except:
                pass
        
        if len(nums) == 6:
            return round_num, sorted(nums)
        return None, None
    
    def load_predictions_for_round(self, target_round):
        predictions = []
        if self.prediction_log.exists():
            with open(self.prediction_log, 'r', encoding='utf-8') as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        # target_round와 일치하는 예측만 필터
                        if data.get('target_round') == target_round:
                            predictions.append(data)
                    except:
                        pass
        return predictions
    
    def load_recent_recommendations(self):
        # 최근 추천 번호 로드 (prediction_log에서)
        recommendations = []
        if self.prediction_log.exists():
            with open(self.prediction_log, 'r', encoding='utf-8') as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        if data.get('candidate_rank', 0) <= 10:
                            recommendations.append(data)
                    except:
                        pass
        return recommendations
    
    def check_winners(self):
        round_num, winning_nums = self.load_latest_lotto()
        
        if not winning_nums:
            return {'status': 'error', 'message': '로또 데이터를 불러올 수 없습니다'}
        
        predictions = self.load_predictions_for_round(round_num)
        recommendations = self.load_recent_recommendations()
        
        # 결과 분석
        result = {
            'check_date': datetime.now().isoformat(),
            'lotto_round': round_num,
            'winning_numbers': winning_nums,
            'predictions_checked': 0,
            'matches': {
                'rank6': [],  # 6개 일치 (1등)
                'rank5': [],  # 5개 일치 (4등)
                'rank4': [],  # 4개 일치 (5등)
                'rank3': [],  # 3개 일치 (安慰奖)
                'rank2': []   # 2개 일치
            },
            'best_match': {'count': 0, 'predictions': []},
            'status': 'success'
        }
        
        # prediction_log에서 당첨 확인
        for pred in predictions:
            pred_nums = pred.get('numbers', [])
            if not pred_nums or len(pred_nums) != 6:
                continue
            
            matches = len(set(pred_nums) & set(winning_nums))
            result['predictions_checked'] += 1
            
            if matches >= 3:
                match_info = {
                    'rank': pred.get('candidate_rank', 0),
                    'numbers': pred_nums,
                    'matches': matches,
                    'score': pred.get('score', 0),
                    'run_id': pred.get('run_id', '')[:30]
                }
                
                if matches == 6:
                    result['matches']['rank6'].append(match_info)
                elif matches == 5:
                    result['matches']['rank5'].append(match_info)
                elif matches == 4:
                    result['matches']['rank4'].append(match_info)
                elif matches == 3:
                    result['matches']['rank3'].append(match_info)
                else:
                    result['matches']['rank2'].append(match_info)
                
                if matches > result['best_match']['count']:
                    result['best_match'] = {'count': matches, 'predictions': [match_info]}
                elif matches == result['best_match']['count']:
                    result['best_match']['predictions'].append(match_info)
        
        return result
    
    def generate_weekly_report(self, result):
        report = []
        report.append('=' * 70)
        report.append('📅 주간 당첨 확인 보고서')
        report.append('=' * 70)
        report.append('')
        report.append('검사일시: ' + result['check_date'])
        report.append('대상 회차: ' + str(result['lotto_round']) + '회차')
        report.append('당첨 번호: ' + str(result['winning_numbers']))
        report.append('')
        report.append('-' * 70)
        
        # 요약
        r6 = len(result['matches']['rank6'])
        r5 = len(result['matches']['rank5'])
        r4 = len(result['matches']['rank4'])
        r3 = len(result['matches']['rank3'])
        
        report.append('')
        report.append('📊 당첨 매칭 결과')
        report.append('')
        report.append('  1등 (6개 일치): ' + str(r6) + '건')
        report.append('  4등 (5개 일치): ' + str(r5) + '건')
        report.append('  5등 (4개 일치): ' + str(r4) + '건')
        report.append('  기타 (3개 일치): ' + str(r3) + '건')
        report.append('')
        
        # 최고 매칭 상세
        best = result['best_match']
        report.append('🏆 최고 매칭: ' + str(best['count']) + '개')
        report.append('')
        
        for pred in best['predictions'][:5]:
            nums_str = ', '.join('{:02d}'.format(n) for n in pred['numbers'])
            report.append('  추천 번호: ' + nums_str)
            report.append('  일치: ' + str(pred['matches']) + '/6 | 순위: ' + str(pred['rank']) + ' | 점수: ' + str(pred['score']))
            report.append('')
        
        # 4/5등 상세
        if result['matches']['rank5']:
            report.append('🎯 4등 달성 조합:')
            for match in result['matches']['rank5'][:3]:
                nums_str = ', '.join('{:02d}'.format(n) for n in match['numbers'])
                report.append('  ' + nums_str + ' (순위: ' + str(match['rank']) + ')')
            report.append('')
        
        if result['matches']['rank4']:
            report.append('✨ 5등 달성 조합:')
            for match in result['matches']['rank4'][:5]:
                nums_str = ', '.join('{:02d}'.format(n) for n in match['numbers'])
                report.append('  ' + nums_str + ' (순위: ' + str(match['rank']) + ')')
            report.append('')
        
        report.append('-' * 70)
        report.append('총 ' + str(result['predictions_checked']) + '개의 추천 번호 검사 완료')
        report.append('=' * 70)
        
        return '\n'.join(report)
    
    def save_result(self, result, report_text):
        # JSON 저장
        json_path = self.reports_dir / 'weekly_winner_result.json'
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        # 텍스트 리포트 저장
        report_path = self.reports_dir / 'weekly_winner_report.txt'
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report_text)
        
        # 로그 저장
        log_entry = {
            'timestamp': result['check_date'],
            'lotto_round': result['lotto_round'],
            'winning_numbers': result['winning_numbers'],
            'best_match_count': result['best_match']['count'],
            'rank6_count': len(result['matches']['rank6']),
            'rank5_count': len(result['matches']['rank5']),
            'rank4_count': len(result['matches']['rank4']),
            'rank3_count': len(result['matches']['rank3'])
        }
        
        with open(self.winner_log, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
        
        return json_path, report_path
    
    def get_dashboard_data(self):
        # 대시보드용 데이터 로드
        dashboard = {
            'latest_result': None,
            'history': [],
            'stats': {
                'total_weeks': 0,
                'rank6_weeks': 0,
                'rank5_weeks': 0,
                'rank4_weeks': 0,
                'best_record': {'count': 0, 'round': 0}
            }
        }
        
        # 최신 결과
        json_path = self.reports_dir / 'weekly_winner_result.json'
        if json_path.exists():
            with open(json_path, 'r', encoding='utf-8') as f:
                dashboard['latest_result'] = json.load(f)
        
        # 히스토리
        if self.winner_log.exists():
            with open(self.winner_log, 'r', encoding='utf-8') as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        dashboard['history'].append(json.loads(line))
                    except:
                        pass
        
        # 통계
        if dashboard['history']:
            dashboard['stats']['total_weeks'] = len(dashboard['history'])
            for h in dashboard['history']:
                if h['rank6_count'] > 0:
                    dashboard['stats']['rank6_weeks'] += 1
                if h['rank5_count'] > 0:
                    dashboard['stats']['rank5_weeks'] += 1
                if h['rank4_count'] > 0:
                    dashboard['stats']['rank4_weeks'] += 1
                if h['best_match_count'] > dashboard['stats']['best_record']['count']:
                    dashboard['stats']['best_record'] = {
                        'count': h['best_match_count'],
                        'round': h['lotto_round']
                    }
        
        return dashboard
    
    def run(self):
        print('')
        print('=' * 70)
        print('🎰 주간 당첨 확인 시스템 실행')
        print('=' * 70)
        print('')
        
        result = self.check_winners()
        
        if result['status'] == 'error':
            print('오류: ' + result['message'])
            return result
        
        report = self.generate_weekly_report(result)
        print(report)
        
        json_path, report_path = self.save_result(result, report)
        
        print('')
        print('💾 결과 저장 완료:')
        print('   JSON: ' + str(json_path))
        print('   리포트: ' + str(report_path))
        
        return result

if __name__ == '__main__':
    checker = WeeklyWinnerChecker(Path(__file__).resolve().parent)
    checker.run()