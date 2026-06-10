# -*- coding: utf-8 -*-
import json
import pandas as pd
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np

class PerformanceAnalyzer:
    def __init__(self, project_dir):
        self.project_dir = Path(project_dir)
        self.lotto_xlsx = self.project_dir / 'lotto.xlsx'
        self.prediction_log   = self.project_dir / 'logs' / 'prediction_log.jsonl'
        self.probability_log  = self.project_dir / 'logs' / 'probability_log.jsonl'
        self.manual_score_log = self.project_dir / 'logs' / 'manual_score_log.jsonl'
        self.winner_log = self.project_dir / 'logs' / 'weekly_winner_log.jsonl'
        self.performance_log = self.project_dir / 'logs' / 'performance_log.jsonl'
        self.reports_dir = self.project_dir / 'reports'
        self.reports_dir.mkdir(exist_ok=True)
        self.universe = list(range(1, 46))
        
    def load_history(self, limit=200):
        df = pd.read_excel(self.lotto_xlsx)
        number_cols = []
        for col in df.columns:
            if str(col).startswith('번호') and len(number_cols) < 6:
                number_cols.append(col)
        number_cols = sorted(number_cols, key=lambda x: int(''.join(c for c in str(x) if c.isdigit()) or 999))[:6]

        # 실제 회차 컬럼 확인
        has_round_col = '회차' in df.columns

        history = []
        for _, row in df.head(limit).iterrows():
            nums = []
            for col in number_cols:
                try:
                    nums.append(int(row[col]))
                except:
                    pass
            if len(nums) == 6:
                # 엑셀의 실제 회차 사용, 없으면 순번
                if has_round_col:
                    try:
                        round_num = int(row['회차'])
                    except:
                        round_num = len(history) + 1
                else:
                    round_num = len(history) + 1
                history.append({'round': round_num, 'numbers': sorted(nums)})
        return history
    
    def load_predictions(self):
        """prediction / probability / manual_score 3개 로그 파일을 모두 읽는다."""
        predictions = []
        log_files = [
            self.prediction_log,
            self.probability_log,
            self.manual_score_log,
        ]
        for log_path in log_files:
            if not log_path.exists():
                continue
            with open(log_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        predictions.append(json.loads(line))
                    except:
                        pass
        return predictions
    
    def load_weekly_history(self):
        history = []
        if self.winner_log.exists():
            with open(self.winner_log, 'r', encoding='utf-8') as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        history.append(json.loads(line))
                    except:
                        pass
        return sorted(history, key=lambda x: x.get('timestamp', ''), reverse=True)
    
    def analyze_all_rounds(self, max_rounds=None):  # None = 전체 누적 (제한 없음)
        history = self.load_history()
        predictions = self.load_predictions()

        # ── target_round 기준으로 인덱싱 ──────────────────────────────────
        # 핵심 수정: 예측은 반드시 해당 target_round 회차와만 비교해야 함.
        # 기존 코드는 run_id 그룹으로만 묶어 모든 회차와 크로스 비교했으므로
        # 잘못된(부풀려진) 적중 수치가 생성됨.
        # {target_round: [entry, ...]} 형태로 재구성
        preds_by_round = defaultdict(list)
        for p in predictions:
            tr = p.get('target_round')
            if tr:
                preds_by_round[int(tr)].append(p)

        results = []

        for actual in (history if max_rounds is None else history[:max_rounds]):
            round_num   = actual['round']
            actual_nums = actual['numbers']

            round_result = {
                'round': round_num,
                'actual_numbers': actual_nums,
                'total_predictions': 0,
                'match_6': 0,
                'match_5': 0,
                'match_4': 0,
                'match_3': 0,
                'match_2': 0,
                'match_1': 0,
                'best_match': 0,
                'best_numbers': None,
                'top5_hits': 0
            }

            # 이 회차를 target으로 한 예측만 비교
            entries = preds_by_round.get(round_num, [])
            bonus = None  # 보너스 번호는 lotto.xlsx 에서 별도 로드 필요 (현재 history에 미포함)

            for entry in entries:
                pred_nums = entry.get('numbers', [])
                if not pred_nums or len(pred_nums) != 6:
                    continue

                round_result['total_predictions'] += 1
                matches = len(set(pred_nums) & set(actual_nums))

                if matches == 6:
                    round_result['match_6'] += 1
                elif matches == 5:
                    round_result['match_5'] += 1
                elif matches == 4:
                    round_result['match_4'] += 1
                elif matches == 3:
                    round_result['match_3'] += 1
                elif matches == 2:
                    round_result['match_2'] += 1
                elif matches == 1:
                    round_result['match_1'] += 1

                if matches > round_result['best_match']:
                    round_result['best_match'] = matches
                    round_result['best_numbers'] = pred_nums

            # Top5 순위(candidate_rank 1~5) 중 4개 이상 일치 여부
            top5 = sorted(
                [e for e in entries if isinstance(e.get('candidate_rank'), int) and e['candidate_rank'] <= 5],
                key=lambda x: x['candidate_rank']
            )
            for top in top5:
                if top.get('numbers'):
                    if len(set(top['numbers']) & set(actual_nums)) >= 4:
                        round_result['top5_hits'] += 1
                        break

            results.append(round_result)

        return results
    
    def calculate_performance_metrics(self, results, recent_weeks=20):
        """성능 지표 계산
        
        로또 등수 기준 (match_N = N개 일치):
          1등 = match_6  (6개 일치)
          2등 = match_5 + 보너스  ← performance_analyzer에서 보너스 미집계 → 별도 표기
          3등 = match_5  (5개 일치, 보너스 미일치)
          4등 = match_4  (4개 일치)
          5등 = match_3  (3개 일치)
        
        [BUG FIX] 기존 코드:
          total_4th = match_5  (올바름: 5개 일치 → 실제 3등, 주석이 4등으로 잘못됨)
          total_5th = match_4  (올바름: 4개 일치 → 실제 4등, 주석이 5등으로 잘못됨)
          total_3rd = match_3  ← 오류: 3개 일치는 5등(당첨 최저)이지, 3등이 아님!
        
        실제 3등(5개 일치)은 match_5 필드에 있음.
        """
        total_rounds = len(results)

        # ── 올바른 등수 매핑 ──────────────────────────────────────────────
        # match_5 = 5개 일치 → 3등 (보너스 미구분이므로 2등 포함 가능하나 보수적으로 3등 처리)
        # match_4 = 4개 일치 → 4등
        # match_3 = 3개 일치 → 5등
        total_3rd = sum(r['match_5'] for r in results)   # 5개 일치 = 3등
        total_4th = sum(r['match_4'] for r in results)   # 4개 일치 = 4등
        total_5th = sum(r['match_3'] for r in results)   # 3개 일치 = 5등

        rounds_with_3rd = len([r for r in results if r['match_5'] > 0])
        rounds_with_4th = len([r for r in results if r['match_4'] > 0])
        rounds_with_5th = len([r for r in results if r['match_3'] > 0])
        rounds_with_top5_hit = len([r for r in results if r['top5_hits'] > 0])

        # 최근 N주 통계
        recent_results = results[:recent_weeks] if len(results) >= recent_weeks else results

        recent_3rd = sum(r['match_5'] for r in recent_results)
        recent_4th = sum(r['match_4'] for r in recent_results)
        recent_5th = sum(r['match_3'] for r in recent_results)
        recent_rounds_with_3rd = len([r for r in recent_results if r['match_5'] > 0])
        recent_rounds_with_4th = len([r for r in recent_results if r['match_4'] > 0])
        recent_rounds_with_5th = len([r for r in recent_results if r['match_3'] > 0])
        recent_top5_hits = len([r for r in recent_results if r['top5_hits'] > 0])

        avg_predictions = sum(r['total_predictions'] for r in results) / max(total_rounds, 1)

        hit_rate_3rd  = (rounds_with_3rd  / max(total_rounds, 1)) * 100
        hit_rate_4th  = (rounds_with_4th  / max(total_rounds, 1)) * 100
        hit_rate_5th  = (rounds_with_5th  / max(total_rounds, 1)) * 100
        hit_rate_top5 = (rounds_with_top5_hit / max(total_rounds, 1)) * 100

        recent_hit_rate_3rd  = (recent_rounds_with_3rd  / max(len(recent_results), 1)) * 100
        recent_hit_rate_4th  = (recent_rounds_with_4th  / max(len(recent_results), 1)) * 100
        recent_hit_rate_5th  = (recent_rounds_with_5th  / max(len(recent_results), 1)) * 100
        recent_hit_rate_top5 = (recent_top5_hits / max(len(recent_results), 1)) * 100

        metrics = {
            'total': {
                'rounds': total_rounds,
                'total_3rd_hits': total_3rd,        # 5개 일치 (3등)
                'total_4th_hits': total_4th,        # 4개 일치 (4등)
                'total_5th_hits': total_5th,        # 3개 일치 (5등)
                'rounds_with_3rd': rounds_with_3rd,
                'rounds_with_4th': rounds_with_4th,
                'rounds_with_5th': rounds_with_5th,
                'rounds_with_top5_hit': rounds_with_top5_hit,
                'hit_rate_3rd':  round(hit_rate_3rd,  1),
                'hit_rate_4th':  round(hit_rate_4th,  1),
                'hit_rate_5th':  round(hit_rate_5th,  1),
                'hit_rate_top5': round(hit_rate_top5, 1),
                'avg_predictions_per_round': round(avg_predictions, 1)
            },
            'recent': {
                'weeks': len(recent_results),
                '3rd_hits': recent_3rd,
                '4th_hits': recent_4th,
                '5th_hits': recent_5th,
                'rounds_with_3rd': recent_rounds_with_3rd,
                'rounds_with_4th': recent_rounds_with_4th,
                'rounds_with_5th': recent_rounds_with_5th,
                'top5_hits': recent_top5_hits,
                'hit_rate_3rd':  round(recent_hit_rate_3rd,  1),
                'hit_rate_4th':  round(recent_hit_rate_4th,  1),
                'hit_rate_5th':  round(recent_hit_rate_5th,  1),
                'hit_rate_top5': round(recent_hit_rate_top5, 1),
            }
        }

        return metrics, results
    
    def analyze_number_patterns(self, results):
        # 가장 많이 적중된 번호 분석
        hit_numbers = defaultdict(int)
        miss_numbers = defaultdict(int)
        
        for r in results:
            actual = r['actual_numbers']
            if r['best_numbers']:
                matched = set(r['best_numbers']) & set(actual)
                for n in matched:
                    hit_numbers[n] += 1
                for n in r['best_numbers']:
                    if n not in matched:
                        miss_numbers[n] += 1
        
        hit_freq = sorted(hit_numbers.items(), key=lambda x: x[1], reverse=True)
        miss_freq = sorted(miss_numbers.items(), key=lambda x: x[1], reverse=True)
        
        return {
            'most_hit_numbers': hit_freq[:15],
            'most_miss_numbers': miss_freq[:10]
        }
    
    def generate_performance_report(self, metrics, results, patterns):
        report = []
        report.append('=' * 75)
        report.append('📊 AI 추천 번호 적중률 분석 리포트')
        report.append('=' * 75)
        report.append('')
        report.append('생성일시: ' + datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        report.append('')

        total = metrics['total']
        report.append('-' * 75)
        report.append('📈 누적 성능 (전체 ' + str(total['rounds']) + '회차 분석)')
        report.append('-' * 75)
        report.append('')
        report.append('  🥉 3등 달성률 (5개 일치): ' + str(total['hit_rate_3rd']) + '% (' + str(total['rounds_with_3rd']) + '/' + str(total['rounds']) + '회차)')
        report.append('  🎯 4등 달성률 (4개 일치): ' + str(total['hit_rate_4th']) + '% (' + str(total['rounds_with_4th']) + '/' + str(total['rounds']) + '회차)')
        report.append('  ✨ 5등 달성률 (3개 일치): ' + str(total['hit_rate_5th']) + '% (' + str(total['rounds_with_5th']) + '/' + str(total['rounds']) + '회차)')
        report.append('  ⭐ Top5 추천 적중률: ' + str(total['hit_rate_top5']) + '% (' + str(total['rounds_with_top5_hit']) + '/' + str(total['rounds']) + '회차)')
        report.append('')
        report.append('  총 3등 당첨 (5개 일치): ' + str(total['total_3rd_hits']) + '건')
        report.append('  총 4등 당첨 (4개 일치): ' + str(total['total_4th_hits']) + '건')
        report.append('  총 5등 당첨 (3개 일치): ' + str(total['total_5th_hits']) + '건')
        report.append('')
        report.append('  평균 예측 수/회차: ' + str(total['avg_predictions_per_round']) + '개')
        report.append('')

        recent = metrics['recent']
        report.append('-' * 75)
        report.append('📉 최근 ' + str(recent['weeks']) + '주 성능')
        report.append('-' * 75)
        report.append('')
        report.append('  🥉 3등 달성률: ' + str(recent['hit_rate_3rd']) + '% (' + str(recent['rounds_with_3rd']) + '/' + str(recent['weeks']) + '회차)')
        report.append('  🎯 4등 달성률: ' + str(recent['hit_rate_4th']) + '% (' + str(recent['rounds_with_4th']) + '/' + str(recent['weeks']) + '회차)')
        report.append('  ✨ 5등 달성률: ' + str(recent['hit_rate_5th']) + '% (' + str(recent['rounds_with_5th']) + '/' + str(recent['weeks']) + '회차)')
        report.append('  ⭐ Top5 적중률: ' + str(recent['hit_rate_top5']) + '% (' + str(recent['top5_hits']) + '/' + str(recent['weeks']) + '회차)')
        report.append('')
        report.append('  최근 3등: ' + str(recent['3rd_hits']) + '건')
        report.append('  최근 4등: ' + str(recent['4th_hits']) + '건')
        report.append('  최근 5등: ' + str(recent['5th_hits']) + '건')
        report.append('')

        # 추세 분석
        if recent['hit_rate_3rd'] > total['hit_rate_3rd']:
            report.append('  📈 3등 달성률 추세: 상승 중 (+' + str(round(recent['hit_rate_3rd'] - total['hit_rate_3rd'], 1)) + '%)')
        elif recent['hit_rate_3rd'] < total['hit_rate_3rd']:
            report.append('  📉 3등 달성률 추세: 하락 중 (' + str(round(recent['hit_rate_3rd'] - total['hit_rate_3rd'], 1)) + '%)')
        else:
            report.append('  ➡️ 3등 달성률 추세: 안정')

        if recent['hit_rate_4th'] > total['hit_rate_4th']:
            report.append('  📈 4등 달성률 추세: 상승 중')
        elif recent['hit_rate_4th'] < total['hit_rate_4th']:
            report.append('  📉 4등 달성률 추세: 하락 중')
        else:
            report.append('  ➡️ 4등 달성률 추세: 안정')

        if recent['hit_rate_5th'] > total['hit_rate_5th']:
            report.append('  📈 5등 달성률 추세: 상승 중')
        elif recent['hit_rate_5th'] < total['hit_rate_5th']:
            report.append('  📉 5등 달성률 추세: 하락 중')
        else:
            report.append('  ➡️ 5등 달성률 추세: 안정')
        report.append('')

        # 상세 히스토리
        report.append('-' * 75)
        report.append('📋 최근 20주 상세 내역')
        report.append('-' * 75)
        report.append('')
        report.append('회차 | 당첨번호                    | 최고일치 | 3등 | 4등 | 5등 | Top5')
        report.append('-' * 75)

        for r in results[:20]:
            actual = ', '.join('{:02d}'.format(n) for n in r['actual_numbers'])
            top5 = '✅' if r['top5_hits'] > 0 else '-'
            report.append(' {:3d} | {} | {:2d}개     | {} | {}  | {}  | {}'.format(
                r['round'], actual, r['best_match'],
                '+' if r['match_5'] > 0 else '-',   # 3등: 5개 일치
                '+' if r['match_4'] > 0 else '-',   # 4등: 4개 일치
                '+' if r['match_3'] > 0 else '-',   # 5등: 3개 일치
                top5
            ))

        report.append('')

        # 번호 패턴
        report.append('-' * 75)
        report.append('🔮 적중 번호 패턴 분석')
        report.append('-' * 75)
        report.append('')
        report.append('가장 많이 적중된 번호:')
        hit_nums = patterns.get('most_hit_numbers', [])[:10]
        report.append(', '.join(['{:02d}({}회)'.format(n, c) for n, c in hit_nums]))
        report.append('')
        report.append('가장 많이 놓친 번호:')
        miss_nums = patterns.get('most_miss_numbers', [])[:5]
        report.append(', '.join(['{:02d}({}회)'.format(n, c) for n, c in miss_nums]))
        report.append('')

        report.append('=' * 75)

        return '\n'.join(report)
    
    def save_results(self, metrics, results, patterns, report):
        # JSON 저장
        output = {
            'timestamp': datetime.now().isoformat(),
            'metrics': metrics,
            'patterns': patterns,
            'detailed_results': results  # 전체 누적 저장 (제한 없음)
        }
        
        json_path = self.reports_dir / 'performance_analysis.json'
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        
        # 리포트 텍스트 저장
        report_path = self.reports_dir / 'performance_report.txt'
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report)
        
        # 성능 로그 저장
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'hit_rate_4th': metrics['total']['hit_rate_4th'],
            'hit_rate_5th': metrics['total']['hit_rate_5th'],
            'hit_rate_top5': metrics['total']['hit_rate_top5'],
            'recent_hit_rate_4th': metrics['recent']['hit_rate_4th'],
            'recent_hit_rate_5th': metrics['recent']['hit_rate_5th']
        }
        
        with open(self.performance_log, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
        
        return json_path, report_path
    
    def get_performance_trend(self):
        # 성능 추이 데이터
        trend = []
        if self.performance_log.exists():
            with open(self.performance_log, 'r', encoding='utf-8') as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        trend.append(json.loads(line))
                    except:
                        pass
        return trend
    
    def run(self, max_rounds=None, recent_weeks=20):
        print('')
        print('=' * 75)
        print('📊 AI 추천 번호 적중률 분석 시스템 실행')
        print('=' * 75)
        print('')
        
        # 전체 분석
        results = self.analyze_all_rounds(max_rounds)
        
        # 성능 지표 계산
        metrics, all_results = self.calculate_performance_metrics(results, recent_weeks)
        
        # 패턴 분석
        patterns = self.analyze_number_patterns(results)
        
        # 리포트 생성
        report = self.generate_performance_report(metrics, all_results, patterns)
        print(report)
        
        # 결과 저장
        json_path, report_path = self.save_results(metrics, all_results, patterns, report)
        
        print('')
        print('💾 결과 저장 완료:')
        print('   JSON: ' + str(json_path))
        print('   리포트: ' + str(report_path))
        
        return metrics, results, patterns

if __name__ == '__main__':
    analyzer = PerformanceAnalyzer(Path(__file__).resolve().parent)
    metrics, results, patterns = analyzer.run(max_rounds=None, recent_weeks=20)