# -*- coding: utf-8 -*-
import json
import pandas as pd
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
import schedule
import time
import threading

class AutoWeeklyWinnerChecker:
    def __init__(self, project_dir):
        self.project_dir = Path(project_dir)
        self.lotto_xlsx = self.project_dir / 'lotto.xlsx'
        self.prediction_log = self.project_dir / 'logs' / 'prediction_log.jsonl'
        self.winner_log = self.project_dir / 'logs' / 'weekly_winner_log.jsonl'
        self.config_file = self.project_dir / 'logs' / 'auto_weekly_config.json'
        self.reports_dir = self.project_dir / 'reports'
        self.reports_dir.mkdir(exist_ok=True)
        self.universe = list(range(1, 46))
        
        self.load_config()
    
    def load_config(self):
        default_config = {
            'enabled': True,
            'check_day': 5,  # 0=월요일, 5=토요일
            'check_hour': 21,  # 오후 9시
            'check_minute': 0,
            'last_check': None,
            'notification_enabled': False
        }
        
        if self.config_file.exists():
            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.config = {**default_config, **json.load(f)}
        else:
            self.config = default_config
            self.save_config()
    
    def save_config(self):
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, ensure_ascii=False, indent=2)
    
    def load_latest_lotto(self):
        df = pd.read_excel(self.lotto_xlsx)
        number_cols = []
        for col in df.columns:
            if str(col).startswith('번호') and len(number_cols) < 6:
                number_cols.append(col)
        number_cols = sorted(number_cols, key=lambda x: int(''.join(c for c in str(x) if c.isdigit()) or 999))[:6]
        
        if df.empty or len(number_cols) < 6:
            return None, None
        
        latest_row = df.iloc[0]
        round_num = len(df)
        
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
                        if data.get('target_round') == target_round:
                            predictions.append(data)
                    except:
                        pass
        return predictions
    
    def check_winners(self):
        round_num, winning_nums = self.load_latest_lotto()
        
        if not winning_nums:
            return {'status': 'error', 'message': '로또 데이터를 불러올 수 없습니다'}
        
        predictions = self.load_predictions_for_round(round_num)
        
        result = {
            'check_date': datetime.now().isoformat(),
            'lotto_round': round_num,
            'winning_numbers': winning_nums,
            'predictions_checked': 0,
            'matches': {
                'rank6': [],
                'rank5': [],
                'rank4': [],
                'rank3': []
            },
            'best_match': {'count': 0, 'predictions': []},
            'status': 'success'
        }
        
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
                    'score': pred.get('score', 0)
                }
                
                if matches == 6:
                    result['matches']['rank6'].append(match_info)
                elif matches == 5:
                    result['matches']['rank5'].append(match_info)
                elif matches == 4:
                    result['matches']['rank4'].append(match_info)
                elif matches == 3:
                    result['matches']['rank3'].append(match_info)
                
                if matches > result['best_match']['count']:
                    result['best_match'] = {'count': matches, 'predictions': [match_info]}
                elif matches == result['best_match']['count']:
                    result['best_match']['predictions'].append(match_info)
        
        return result
    
    def generate_report(self, result):
        report = []
        report.append('=' * 70)
        report.append('📅 AUTO 주간 당첨 확인 보고서 (자동 실행)')
        report.append('=' * 70)
        report.append('')
        report.append('검사일시: ' + result['check_date'])
        report.append('대상 회차: ' + str(result['lotto_round']) + '회차')
        report.append('당첨 번호: ' + str(result['winning_numbers']))
        report.append('')
        report.append('-' * 70)
        report.append('')
        report.append('📊 당첨 매칭 결과')
        report.append('')
        report.append('  1등 (6개 일치): ' + str(len(result['matches']['rank6'])) + '건')
        report.append('  4등 (5개 일치): ' + str(len(result['matches']['rank5'])) + '건')
        report.append('  5등 (4개 일치): ' + str(len(result['matches']['rank4'])) + '건')
        report.append('  기타 (3개 일치): ' + str(len(result['matches']['rank3'])) + '건')
        report.append('')
        
        best = result['best_match']
        report.append('🏆 최고 매칭: ' + str(best['count']) + '개 일치')
        report.append('')
        
        for pred in best['predictions'][:5]:
            nums_str = ', '.join('{:02d}'.format(n) for n in pred['numbers'])
            report.append('  추천: ' + nums_str + ' | 점수: ' + str(pred['score']))
        
        report.append('')
        report.append('-' * 70)
        report.append('총 ' + str(result['predictions_checked']) + '개 추천 번호 검사 완료')
        report.append('=' * 70)
        
        return '\n'.join(report)
    
    def save_result(self, result, report):
        # 결과 저장
        json_path = self.reports_dir / 'auto_weekly_result.json'
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        report_path = self.reports_dir / 'auto_weekly_report.txt'
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report)
        
        # 로그 업데이트
        log_entry = {
            'timestamp': result['check_date'],
            'lotto_round': result['lotto_round'],
            'best_match_count': result['best_match']['count'],
            'rank6': len(result['matches']['rank6']),
            'rank5': len(result['matches']['rank5']),
            'rank4': len(result['matches']['rank4']),
            'rank3': len(result['matches']['rank3']),
            'auto': True
        }
        
        with open(self.winner_log, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
        
        # 설정 업데이트
        self.config['last_check'] = result['check_date']
        self.save_config()
        
        return json_path, report_path
    
    def run_check(self):
        print('')
        print('=' * 70)
        print('🎰 자동 주간 당첨 확인 실행 (' + datetime.now().strftime('%Y-%m-%d %H:%M:%S') + ')')
        print('=' * 70)
        print('')
        
        result = self.check_winners()
        
        if result['status'] == 'error':
            print('오류: ' + result['message'])
            return
        
        report = self.generate_report(result)
        print(report)
        
        json_path, report_path = self.save_result(result, report)
        
        print('')
        print('💾 자동 저장 완료:')
        print('   결과: reports/auto_weekly_result.json')
        print('   리포트: reports/auto_weekly_report.txt')
    
    def start_scheduler(self):
        import schedule
        import time
        
        # 토요일 저녁 9시 실행 설정
        day_names = ['월요일', '화요일', '수요일', '목요일', '금요일', '토요일', '일요일']
        check_day = self.config.get('check_day', 5)
        check_hour = self.config.get('check_hour', 21)
        
        print('')
        print('=' * 70)
        print('📅 자동 스케줄러 시작')
        print('=' * 70)
        print('')
        print('실행 설정: 매주 ' + day_names[check_day] + ' ' + str(check_hour) + ':00')
        print('')
        
        # 주기적 실행
        schedule.every().friday.at('20:00').do(self.run_check)
        
        print('스케줄러 실행 중... (Ctrl+C로 종료)')
        print('')
        
        while self.config.get('enabled', True):
            schedule.run_pending()
            time.sleep(60)

def run_auto_checker():
    checker = AutoWeeklyWinnerChecker(Path(__file__).resolve().parent)
    checker.run_check()

if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == '--daemon':
        checker = AutoWeeklyWinnerChecker(Path(__file__).resolve().parent)
        checker.start_scheduler()
    else:
        checker = AutoWeeklyWinnerChecker(Path(__file__).resolve().parent)
        checker.run_check()