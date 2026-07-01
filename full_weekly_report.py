# -*- coding: utf-8 -*-
import json
import pandas as pd
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

class FullWeeklyAnalyzer:
    def __init__(self, project_dir):
        self.project_dir = Path(project_dir)
        self.lotto_xlsx = self.project_dir / 'lotto.xlsx'
        self.prediction_log = self.project_dir / 'logs' / 'prediction_log.jsonl'
        self.reports_dir = self.project_dir / 'reports'
        self.reports_dir.mkdir(exist_ok=True)
        
    def load_history(self, limit=100):
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
                history.append({'round': len(history) + 1, 'numbers': sorted(nums)})
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
    
    def analyze_performance(self, max_rounds=None):
        history = self.load_history(max_rounds)
        predictions = self.load_predictions()
        
        runs = defaultdict(list)
        for p in predictions:
            run_id = p.get('run_id', p.get('timestamp', 'unknown'))
            runs[run_id].append(p)
        
        results = []
        
        for i, actual in enumerate(history if max_rounds is None else history[:max_rounds]):
            round_num = actual['round']
            actual_nums = actual['numbers']
            
            r = {
                'round': round_num,
                'actual': actual_nums,
                'total_pred': 0,
                'match_5': 0,
                'match_4': 0,
                'match_3': 0,
                'best_match': 0,
                'top5_hit': False
            }
            
            for run_id, entries in runs.items():
                for entry in entries:
                    pred = entry.get('numbers', [])
                    if not pred or len(pred) != 6:
                        continue
                    
                    r['total_pred'] += 1
                    matches = len(set(pred) & set(actual_nums))
                    
                    if matches == 5:
                        r['match_5'] += 1
                    elif matches == 4:
                        r['match_4'] += 1
                    elif matches == 3:
                        r['match_3'] += 1
                    
                    if matches > r['best_match']:
                        r['best_match'] = matches
                
                top5 = sorted([e for e in entries if e.get('candidate_rank', 0) <= 5],
                             key=lambda x: x.get('candidate_rank', 0))
                for top in top5:
                    if top.get('numbers'):
                        if len(set(top['numbers']) & set(actual_nums)) >= 4:
                            r['top5_hit'] = True
                            break
            
            results.append(r)
        
        return results
    
    def calculate_metrics(self, results, recent_weeks=20):
        total = len(results)
        recent = results[:recent_weeks] if len(results) >= recent_weeks else results
        
        total_4th = sum(r['match_5'] for r in results)
        total_5th = sum(r['match_4'] for r in results)
        total_3rd = sum(r['match_3'] for r in results)
        
        rounds_4th = len([r for r in results if r['match_5'] > 0])
        rounds_5th = len([r for r in results if r['match_4'] > 0])
        rounds_top5 = len([r for r in results if r['top5_hit']])
        
        recent_4th = sum(r['match_5'] for r in recent)
        recent_5th = sum(r['match_4'] for r in recent)
        recent_3rd = sum(r['match_3'] for r in recent)
        recent_4th_rounds = len([r for r in recent if r['match_5'] > 0])
        recent_5th_rounds = len([r for r in recent if r['match_4'] > 0])
        recent_top5 = len([r for r in recent if r['top5_hit']])
        
        metrics = {
            'total_rounds': total,
            'total_4th': total_4th, 'total_5th': total_5th, 'total_3rd': total_3rd,
            'rounds_4th': rounds_4th, 'rounds_5th': rounds_5th, 'rounds_top5': rounds_top5,
            'rate_4th': round(rounds_4th / max(total, 1) * 100, 1),
            'rate_5th': round(rounds_5th / max(total, 1) * 100, 1),
            'rate_top5': round(rounds_top5 / max(total, 1) * 100, 1),
            'recent_weeks': len(recent),
            'recent_4th': recent_4th, 'recent_5th': recent_5th, 'recent_3rd': recent_3rd,
            'recent_4th_rounds': recent_4th_rounds,
            'recent_5th_rounds': recent_5th_rounds,
            'recent_top5': recent_top5,
            'recent_rate_4th': round(recent_4th_rounds / max(len(recent), 1) * 100, 1),
            'recent_rate_5th': round(recent_5th_rounds / max(len(recent), 1) * 100, 1),
            'recent_rate_top5': round(recent_top5 / max(len(recent), 1) * 100, 1)
        }
        
        return metrics
    
    def generate_full_report(self, metrics, results):
        report = []
        report.append('')
        report.append('╔' + '═' * 73 + '╗')
        report.append('║' + '📊 FULL 주간 성능 분석 리포트'.center(71) + '║')
        report.append('╚' + '═' * 73 + '╝')
        report.append('')
        report.append('📅 생성일시: ' + datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        report.append('')
        
        # 누적 성능
        report.append('┌' + '─' * 71 + '┐')
        report.append('│' + '📈 누적 성능 (총 ' + str(metrics['total_rounds']) + '회차 분석)'.ljust(71) + '│')
        report.append('├' + '─' * 71 + '┤')
        
        # 달성률
        report.append('│' + ('').ljust(71) + '│')
        report.append('│  🎯 4등 달성률 (5개 일치): ' + str(metrics['rate_4th']).rjust(6) + '%  │ ' + str(metrics['rounds_4th']).rjust(3) + '회차에서 달성 (' + str(metrics['total_4th']) + '건)'.ljust(25) + '│')
        report.append('│  ✨ 5등 달성률 (4개 일치): ' + str(metrics['rate_5th']).rjust(6) + '%  │ ' + str(metrics['rounds_5th']).rjust(3) + '회차에서 달성 (' + str(metrics['total_5th']) + '건)'.ljust(25) + '│')
        report.append('│  ⭐ Top5 추천 적중률:     ' + str(metrics['rate_top5']).rjust(6) + '%  │ ' + str(metrics['rounds_top5']).rjust(3) + '회차에서 달성'.ljust(30) + '│')
        report.append('│' + ('').ljust(71) + '│')
        report.append('│  총 3개 일치: ' + str(metrics['total_3rd']) + '건'.ljust(40) + '│')
        report.append('└' + '─' * 71 + '┘')
        report.append('')
        
        # 최근 20주
        report.append('┌' + '─' * 71 + '┐')
        report.append('│' + '📉 최근 ' + str(metrics['recent_weeks']) + '주 성능'.ljust(71) + '│')
        report.append('├' + '─' * 71 + '┤')
        report.append('│' + ('').ljust(71) + '│')
        report.append('│  🎯 4등 달성률: ' + str(metrics['recent_rate_4th']).rjust(6) + '% (' + str(metrics['recent_4th_rounds']) + '/' + str(metrics['recent_weeks']) + '회차)  │  최근 4등: ' + str(metrics['recent_4th']) + '건'.ljust(20) + '│')
        report.append('│  ✨ 5등 달성률: ' + str(metrics['recent_rate_5th']).rjust(6) + '% (' + str(metrics['recent_5th_rounds']) + '/' + str(metrics['recent_weeks']) + '회차)  │  최근 5등: ' + str(metrics['recent_5th']) + '건'.ljust(20) + '│')
        report.append('│  ⭐ Top5 적중률: ' + str(metrics['recent_rate_top5']).rjust(6) + '% (' + str(metrics['recent_top5']) + '/' + str(metrics['recent_weeks']) + '회차)  │'.ljust(50) + '│')
        report.append('│' + ('').ljust(71) + '│')
        
        # 추세
        diff_4th = metrics['recent_rate_4th'] - metrics['rate_4th']
        diff_5th = metrics['recent_rate_5th'] - metrics['rate_5th']
        
        trend_4th = '📈 상승' if diff_4th > 0 else ('📉 하락' if diff_4th < 0 else '➡️ 안정')
        trend_5th = '📈 상승' if diff_5th > 0 else ('📉 하락' if diff_5th < 0 else '➡️ 안정')
        
        report.append('│  추세: 4등 ' + trend_4th + ' | 5등 ' + trend_5th + ''.ljust(40) + '│')
        report.append('└' + '─' * 71 + '┘')
        report.append('')
        
        # 상세 내역
        report.append('┌' + '─' * 71 + '┐')
        report.append('│' + '📋 최근 20주 상세 내역'.ljust(71) + '│')
        report.append('├' + '─' * 18 + '┬' + '─' * 28 + '┬' + '─' * 9 + '┬' + '─' * 6 + '┬' + '─' * 6 + '┤')
        report.append('│' + '회차'.center(16) + '│' + '당첨번호'.center(26) + '│' + '최고일치'.center(7) + '│' + '4등'.center(4) + '│' + '5등'.center(4) + '│')
        report.append('├' + '─' * 18 + '┼' + '─' * 28 + '┼' + '─' * 9 + '┼' + '─' * 6 + '┼' + '─' * 6 + '┤')
        
        for r in results[:20]:
            nums = ' '.join('{:02d}'.format(n) for n in r['actual'])
            top5_icon = '✅' if r['top5_hit'] else '  '
            r4_icon = '🎯' if r['match_5'] > 0 else '  '
            r5_icon = '✨' if r['match_4'] > 0 else '  '
            report.append('│' + str(r['round']).center(16) + '│' + nums.center(26) + '│' + str(r['best_match']).center(7) + '│' + r4_icon.center(4) + '│' + r5_icon.center(4) + '│')
        
        report.append('└' + '─' * 18 + '┴' + '─' * 28 + '┴' + '─' * 9 + '┴' + '─' * 6 + '┴' + '─' * 6 + '┘')
        report.append('')
        
        # 요약
        report.append('┌' + '─' * 71 + '┐')
        report.append('│' + '💡 요약'.ljust(71) + '│')
        report.append('├' + '─' * 71 + '┤')
        report.append('│' + ('').ljust(71) + '│')
        report.append('│  • 총 ' + str(metrics['total_rounds']) + '회차 분석 결과, 4등 달성률 ' + str(metrics['rate_4th']) + '%'.ljust(60) + '│')
        report.append('│  • 최근 ' + str(metrics['recent_weeks']) + '주간 4등 달성률 ' + str(metrics['recent_rate_4th']) + '%' + (' (개선 중!)' if diff_4th > 0 else (' (주의 필요)' if diff_4th < 0 else '')).ljust(50) + '│')
        report.append('│  • 5등 안정적 달성률 ' + str(metrics['rate_5th']) + '% 유지'.ljust(50) + '│')
        report.append('│' + ('').ljust(71) + '│')
        report.append('└' + '─' * 71 + '┘')
        report.append('')
        
        return '\n'.join(report)
    
    def save_report(self, metrics, results, report_text):
        output = {
            'timestamp': datetime.now().isoformat(),
            'metrics': metrics,
            'results': results  # 전체 누적
        }
        
        json_path = self.reports_dir / 'full_performance_analysis.json'
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        
        text_path = self.reports_dir / 'full_performance_report.txt'
        with open(text_path, 'w', encoding='utf-8') as f:
            f.write(report_text)
        
        return json_path, text_path
    
    def run(self, max_rounds=None, recent_weeks=20):
        print('')
        print('=' * 75)
        print('FULL 주간 성능 분석 실행')
        print('=' * 75)
        
        results = self.analyze_performance(max_rounds)
        metrics = self.calculate_metrics(results, recent_weeks)
        report = self.generate_full_report(metrics, results)
        
        print(report)
        
        json_path, text_path = self.save_report(metrics, results, report)
        
        print('')
        print('=' * 75)
        print('💾 저장 완료:')
        print('   JSON: ' + str(json_path))
        print('   리포트: ' + str(text_path))
        print('=' * 75)
        
        return metrics, results

if __name__ == '__main__':
    analyzer = FullWeeklyAnalyzer(Path(__file__).resolve().parent)
    metrics, results = analyzer.run(max_rounds=None, recent_weeks=20)