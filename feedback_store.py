#!/usr/bin/env python3
# -*- coding: utf-8 -*-
'''피드백 데이터 관리 시스템 - 예측 저장 / 실제 결과 비교 / 적중 통계 계산'''

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent

# 앱 시작 시 로그 디렉토리 자동 생성
(PROJECT_DIR / 'logs').mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(PROJECT_DIR / 'logs' / 'feedback_store.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('FeedbackStore')

KST = ZoneInfo('Asia/Seoul')


class FeedbackStore:
    '''피드백 데이터를 관리하는 클래스'''
    
    def __init__(self, project_dir: Path = None):
        self.project_dir = project_dir or PROJECT_DIR
        self.log_dir = self.project_dir / 'logs'
        self.reports_dir = self.project_dir / 'reports'
        self.feedback_db_path = self.log_dir / 'feedback_history.db'
        self._ensure_directories()
        self._init_database()
    
    def _ensure_directories(self):
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
    
    def _init_database(self):
        conn = sqlite3.connect(self.feedback_db_path)
        try:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prediction_round INTEGER,
                    predicted_numbers TEXT,
                    predicted_at TEXT,
                    prediction_score REAL,
                    prediction_method TEXT,
                    pattern_features TEXT,
                    anti_score REAL,
                    crowd_proxy REAL,
                    target_round INTEGER
                )
            ''')
            
            conn.execute('''
                CREATE TABLE IF NOT EXISTS actual_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    draw_round INTEGER UNIQUE,
                    winning_numbers TEXT,
                    drawn_at TEXT,
                    bonus_number INTEGER
                )
            ''')
            
            conn.execute('''
                CREATE TABLE IF NOT EXISTS feedback_analysis (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prediction_round INTEGER,
                    target_round INTEGER,
                    predicted_numbers TEXT,
                    actual_numbers TEXT,
                    matched_count INTEGER,
                    matched_numbers TEXT,
                    analysis_timestamp TEXT,
                    pattern_summary TEXT,
                    success_score REAL
                )
            ''')
            
            conn.execute('CREATE INDEX IF NOT EXISTS idx_predictions_round ON predictions(prediction_round)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_actual_results_round ON actual_results(draw_round)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_feedback_round ON feedback_analysis(target_round)')
            
            conn.commit()
        finally:
            conn.close()
    
    def utc_now_iso(self) -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    
    # 예측 저장
    def save_prediction(
        self,
        prediction_round: int,
        numbers: list,
        target_round: int,
        prediction_score: float = 0.0,
        prediction_method: str = 'local_engine',
        pattern_features: dict = None,
        anti_score: float = 0.0,
        crowd_proxy: float = 0.0
    ) -> int:
        conn = sqlite3.connect(self.feedback_db_path)
        try:
            cursor = conn.execute('''
                INSERT INTO predictions (
                    prediction_round, predicted_numbers, predicted_at,
                    prediction_score, prediction_method, pattern_features,
                    anti_score, crowd_proxy, target_round
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                prediction_round,
                json.dumps(numbers, ensure_ascii=False),
                self.utc_now_iso(),
                prediction_score,
                prediction_method,
                json.dumps(pattern_features or {}, ensure_ascii=False),
                anti_score,
                crowd_proxy,
                target_round
            ))
            conn.commit()
            logger.info('예측 저장 완료: 회차 %d, 번호 %s' % (target_round, numbers))
            return cursor.lastrowid
        finally:
            conn.close()
    
    def save_predictions_batch(self, predictions: list, prediction_round: int, target_round: int) -> int:
        conn = sqlite3.connect(self.feedback_db_path)
        saved_count = 0
        try:
            for pred in predictions:
                conn.execute('''
                    INSERT INTO predictions (
                        prediction_round, predicted_numbers, predicted_at,
                        prediction_score, prediction_method, pattern_features,
                        anti_score, crowd_proxy, target_round
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    prediction_round,
                    json.dumps(pred.get('numbers', []), ensure_ascii=False),
                    self.utc_now_iso(),
                    pred.get('score', 0.0),
                    pred.get('method', 'local_engine'),
                    json.dumps(pred.get('features', {}), ensure_ascii=False),
                    pred.get('anti_score', 0.0),
                    pred.get('crowd_proxy', 0.0),
                    target_round
                ))
                saved_count += 1
            conn.commit()
            logger.info('배치 예측 저장 완료: %d개, 대상 회차 %d' % (saved_count, target_round))
            return saved_count
        finally:
            conn.close()
    
    # 실제 결과 저장
    def save_actual_result(self, draw_round: int, winning_numbers: list, bonus_number: int = 0, drawn_at: str = None) -> int:
        conn = sqlite3.connect(self.feedback_db_path)
        try:
            cursor = conn.execute('''
                INSERT OR REPLACE INTO actual_results (draw_round, winning_numbers, drawn_at, bonus_number)
                VALUES (?, ?, ?, ?)
            ''', (draw_round, json.dumps(winning_numbers, ensure_ascii=False), drawn_at or self.utc_now_iso(), bonus_number))
            conn.commit()
            logger.info('실제 결과 저장 완료: 회차 %d, 번호 %s' % (draw_round, winning_numbers))
            return cursor.lastrowid
        finally:
            conn.close()
    
    def update_lotto_excel_to_feedback(self, excel_path: Path) -> int:
        if not excel_path.exists():
            logger.warning('Excel 파일 없음: %s' % excel_path)
            return 0
        
        try:
            df = pd.read_excel(excel_path)
            if '회차' not in df.columns:
                logger.warning('회차 컬럼 없음')
                return 0
            
            number_cols = [col for col in df.columns if str(col).startswith('번호')]
            if len(number_cols) < 6:
                logger.warning('번호 컬럼 부족: %d' % len(number_cols))
                return 0
            
            saved_count = 0
            for _, row in df.iterrows():
                round_num = int(row['회차'])
                numbers = [int(row[col]) for col in number_cols[:6] if pd.notna(row[col])]
                if len(numbers) == 6:
                    self.save_actual_result(round_num, numbers)
                    saved_count += 1
            
            logger.info('Excel에서 %d개 실제 결과 저장 완료' % saved_count)
            return saved_count
        except Exception as e:
            logger.error('Excel 읽기 오류: %s' % e)
            return 0
    
    # 피드백 분석
    def analyze_prediction_vs_actual(self, prediction_round: int, target_round: int, 
                                      predicted_numbers: list, actual_numbers: list) -> dict:
        predicted_set = set(predicted_numbers)
        actual_set = set(actual_numbers)
        matched = predicted_set & actual_set
        matched_count = len(matched)
        
        predicted_sum = sum(predicted_numbers)
        actual_sum = sum(actual_numbers)
        predicted_high = sum(1 for n in predicted_numbers if n >= 32)
        actual_high = sum(1 for n in actual_numbers if n >= 32)
        
        pattern_summary = {
            'predicted_sum': predicted_sum,
            'actual_sum': actual_sum,
            'predicted_high_count': predicted_high,
            'actual_high_count': actual_high,
            'sum_diff': abs(predicted_sum - actual_sum),
            'high_count_diff': abs(predicted_high - actual_high)
        }
        
        success_score = matched_count * 20
        
        return {
            'prediction_round': prediction_round,
            'target_round': target_round,
            'predicted_numbers': predicted_numbers,
            'actual_numbers': actual_numbers,
            'matched_count': matched_count,
            'matched_numbers': list(matched),
            'pattern_summary': pattern_summary,
            'success_score': success_score
        }
    
    def save_feedback_analysis(self, prediction_round: int, target_round: int,
                                predicted_numbers: list, actual_numbers: list) -> int:
        analysis = self.analyze_prediction_vs_actual(prediction_round, target_round, predicted_numbers, actual_numbers)
        
        conn = sqlite3.connect(self.feedback_db_path)
        try:
            cursor = conn.execute('''
                INSERT INTO feedback_analysis (
                    prediction_round, target_round, predicted_numbers, actual_numbers,
                    matched_count, matched_numbers, analysis_timestamp, pattern_summary, success_score
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                analysis['prediction_round'], analysis['target_round'],
                json.dumps(analysis['predicted_numbers'], ensure_ascii=False),
                json.dumps(analysis['actual_numbers'], ensure_ascii=False),
                analysis['matched_count'],
                json.dumps(analysis['matched_numbers'], ensure_ascii=False),
                self.utc_now_iso(),
                json.dumps(analysis['pattern_summary'], ensure_ascii=False),
                analysis['success_score']
            ))
            conn.commit()
            msg = '피드백 분석 저장 완료: 회차 %d, 적중 %d개' % (target_round, analysis['matched_count'])
            logger.info(msg)
            return cursor.lastrowid
        finally:
            conn.close()
    
    def compare_and_analyze_all_pending(self) -> dict:
        conn = sqlite3.connect(self.feedback_db_path)
        results = {'compared': 0, 'matched_3_plus': 0, 'total_matches': 0}
        
        try:
            predictions = conn.execute('''
                SELECT id, target_round, predicted_numbers 
                FROM predictions 
                WHERE target_round IS NOT NULL
                AND id NOT IN (SELECT prediction_round FROM feedback_analysis WHERE prediction_round IS NOT NULL)
            ''').fetchall()
            
            for pred_id, target_round, pred_numbers_json in predictions:
                predicted_numbers = json.loads(pred_numbers_json)
                actual_row = conn.execute(
                    'SELECT winning_numbers FROM actual_results WHERE draw_round = ?', (target_round,)
                ).fetchone()
                
                if actual_row:
                    actual_numbers = json.loads(actual_row[0])
                    self.save_feedback_analysis(pred_id, target_round, predicted_numbers, actual_numbers)
                    matched_count = len(set(predicted_numbers) & set(actual_numbers))
                    results['compared'] += 1
                    results['total_matches'] += matched_count
                    if matched_count >= 3:
                        results['matched_3_plus'] += 1
            
            logger.info('일괄 비교 완료: %s' % results)
            return results
        finally:
            conn.close()
    
    # 통계 조회
    def get_prediction_stats(self, limit: int = 30) -> list:
        conn = sqlite3.connect(self.feedback_db_path)
        try:
            rows = conn.execute('''
                SELECT fa.prediction_round, fa.target_round, fa.predicted_numbers, fa.actual_numbers,
                       fa.matched_count, fa.success_score, fa.pattern_summary, p.anti_score, p.crowd_proxy, p.prediction_score
                FROM feedback_analysis fa
                LEFT JOIN predictions p ON fa.prediction_round = p.prediction_round
                ORDER BY fa.target_round DESC LIMIT ?
            ''', (limit,)).fetchall()
            
            stats = []
            for row in rows:
                stats.append({
                    'round': row[0], 'target_round': row[1],
                    'predicted_numbers': json.loads(row[2]) if row[2] else [],
                    'actual_numbers': json.loads(row[3]) if row[3] else [],
                    'matched_count': row[4] or 0, 'success_score': row[5] or 0,
                    'pattern_summary': json.loads(row[6]) if row[6] else {},
                    'anti_score': row[7] or 0, 'crowd_proxy': row[8] or 0, 'prediction_score': row[9] or 0
                })
            return stats
        finally:
            conn.close()
    
    def get_successful_patterns(self, min_hits: int = 3, limit: int = 50) -> list:
        conn = sqlite3.connect(self.feedback_db_path)
        try:
            rows = conn.execute('''
                SELECT fa.pattern_summary, fa.matched_count, p.anti_score, p.prediction_score, fa.predicted_numbers
                FROM feedback_analysis fa LEFT JOIN predictions p ON fa.prediction_round = p.prediction_round
                WHERE fa.matched_count >= ? ORDER BY fa.matched_count DESC, fa.success_score DESC LIMIT ?
            ''', (min_hits, limit)).fetchall()
            
            patterns = []
            for row in rows:
                patterns.append({
                    'pattern': json.loads(row[0]) if row[0] else {},
                    'matched_count': row[1], 'anti_score': row[2] or 0,
                    'prediction_score': row[3] or 0,
                    'numbers': json.loads(row[4]) if row[4] else []
                })
            return patterns
        finally:
            conn.close()
    
    def get_learning_data_for_manus(self, limit: int = 20) -> dict:
        prediction_stats = self.get_prediction_stats(limit)
        layer1_data = []
        for stat in prediction_stats:
            if stat['actual_numbers']:
                layer1_data.append({
                    'round': stat['target_round'],
                    'predicted': stat['predicted_numbers'],
                    'actual': stat['actual_numbers'],
                    'matched': stat['matched_count'],
                    'sum': stat['pattern_summary'].get('predicted_sum', 0),
                    'high_count': stat['pattern_summary'].get('predicted_high_count', 0),
                    'anti_score': stat['anti_score']
                })
        
        layer2_data = self._calculate_winning_pattern_stats()
        layer3_data = self._get_latest_candidates()
        
        return {
            'layer1_prediction_feedback': layer1_data,
            'layer2_winning_pattern_stats': layer2_data,
            'layer3_today_candidates': layer3_data,
            'generated_at': self.utc_now_iso()
        }
    
    def _calculate_winning_pattern_stats(self, recent_count: int = 30) -> dict:
        conn = sqlite3.connect(self.feedback_db_path)
        try:
            rows = conn.execute(
                'SELECT winning_numbers FROM actual_results ORDER BY draw_round DESC LIMIT ?', (recent_count,)
            ).fetchall()
            
            if not rows:
                return self._get_default_pattern_stats()
            
            sums, high_counts, odd_counts, consecutive_pairs = [], [], [], []
            
            for row in rows:
                numbers = json.loads(row[0])
                sums.append(sum(numbers))
                high_counts.append(sum(1 for n in numbers if n >= 32))
                odd_counts.append(sum(1 for n in numbers if n % 2 == 1))
                sorted_nums = sorted(numbers)
                pairs = sum(1 for i in range(5) if sorted_nums[i+1] == sorted_nums[i] + 1)
                consecutive_pairs.append(pairs)
            
            return {
                'recent_count': len(rows),
                'avg_sum': round(sum(sums) / len(sums), 1),
                'avg_high_count': round(sum(high_counts) / len(high_counts), 1),
                'avg_odd_count': round(sum(odd_counts) / len(odd_counts), 1),
                'avg_consecutive_pairs': round(sum(consecutive_pairs) / len(consecutive_pairs), 1),
                'high_range_ratio': round(sum(1 for h in high_counts if h >= 2) / len(high_counts), 2)
            }
        finally:
            conn.close()
    
    def _get_default_pattern_stats(self) -> dict:
        return {
            'recent_count': 0, 'avg_sum': 138.4, 'avg_high_count': 1.8,
            'avg_odd_count': 3.0, 'avg_consecutive_pairs': 0.8, 'high_range_ratio': 0.6
        }
    
    def _get_latest_candidates(self, limit: int = 20) -> list:
        conn = sqlite3.connect(self.feedback_db_path)
        try:
            rows = conn.execute('''
                SELECT predicted_numbers, anti_score, crowd_proxy, prediction_score
                FROM predictions ORDER BY predicted_at DESC LIMIT ?
            ''', (limit,)).fetchall()
            
            candidates = []
            for row in rows:
                candidates.append({
                    'numbers': json.loads(row[0]) if row[0] else [],
                    'anti_score': row[1] or 0, 'crowd_proxy': row[2] or 0,
                    'prediction_score': row[3] or 0
                })
            return candidates
        finally:
            conn.close()
    
    # 리포트 생성
    def generate_feedback_report(self, output_path: Path = None) -> Path:
        if output_path is None:
            output_path = self.reports_dir / 'feedback_analysis_report.txt'
        
        stats = self.get_prediction_stats(50)
        successful = self.get_successful_patterns(3, 20)
        
        content = []
        content.append('=' * 60)
        content.append('피드백 분석 리포트')
        date_str = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
        content.append('생성일시: ' + date_str)
        content.append('=' * 60)
        
        total_predictions = len(stats)
        avg_matched = sum(s['matched_count'] for s in stats) / max(total_predictions, 1)
        matched_3_plus = sum(1 for s in stats if s['matched_count'] >= 3)
        
        content.append('\n[ 전체 통계 ]')
        content.append('  - 총 예측 횟수: %d' % total_predictions)
        content.append('  - 평균 적중 수: %.2f' % avg_matched)
        content.append('  - 3개 이상 적중: %d회' % matched_3_plus)
        
        if successful:
            content.append('\n[ 성공 패턴 분석 (3개 이상 적중) ]')
            content.append('-' * 40)
            for i, sp in enumerate(successful[:10], 1):
                pattern = sp['pattern']
                content.append('%d. 적중 %d개 | 합계 %s | 고범위 %s개 | anti_score: %.2f' % (
                    i, sp['matched_count'],
                    pattern.get('predicted_sum', '?'),
                    pattern.get('predicted_high_count', '?'),
                    sp['anti_score']
                ))
        
        content.append('\n[ 최근 예측 결과 ]')
        content.append('-' * 40)
        for s in stats[:10]:
            pred_str = ', '.join(str(n) for n in s['predicted_numbers'])
            actual_str = ', '.join(str(n) for n in s['actual_numbers'])
            content.append('회차 %s: 예측 [%s] -> 실제 [%s] | 적중 %d개' % (
                s['target_round'], pred_str, actual_str, s['matched_count']
            ))
        
        content.append('\n' + '=' * 60)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(content))
        
        logger.info('피드백 리포트 저장: %s' % output_path)
        return output_path
    
    def get_stats_summary(self) -> dict:
        conn = sqlite3.connect(self.feedback_db_path)
        try:
            pred_count = conn.execute('SELECT COUNT(*) FROM predictions').fetchone()[0]
            actual_count = conn.execute('SELECT COUNT(*) FROM actual_results').fetchone()[0]
            feedback_count = conn.execute('SELECT COUNT(*) FROM feedback_analysis').fetchone()[0]
            
            avg_match = 0
            if feedback_count > 0:
                result = conn.execute('SELECT AVG(matched_count) FROM feedback_analysis').fetchone()
                avg_match = result[0] if result and result[0] else 0
            
            return {
                'total_predictions': pred_count,
                'total_actual_results': actual_count,
                'total_feedbacks': feedback_count,
                'average_matches': round(avg_match, 2)
            }
        finally:
            conn.close()
    
    def export_feedback_csv(self, output_path: Path = None) -> Path:
        if output_path is None:
            output_path = self.reports_dir / 'feedback_export.csv'
        
        stats = self.get_prediction_stats(100)
        
        with open(output_path, 'w', encoding='utf-8-sig', newline='') as f:
            f.write('예측회차,대상회차,예측번호,실제번호,적중수,성공점수,합계,고범위수,anti_score\n')
            for s in stats:
                pred_nums = ','.join(str(n) for n in s['predicted_numbers'])
                actual_nums = ','.join(str(n) for n in s['actual_numbers'])
                pattern = s['pattern_summary']
                f.write('%s,%s,%s,%s,%d,%.1f,%s,%s,%.2f\n' % (
                    s['round'], s['target_round'], pred_nums, actual_nums,
                    s['matched_count'], s['success_score'],
                    pattern.get('predicted_sum', ''),
                    pattern.get('predicted_high_count', ''),
                    s['anti_score']
                ))
        
        logger.info('피드백 CSV 내보내기 완료: %s' % output_path)
        return output_path


if __name__ == '__main__':
    store = FeedbackStore()
    print('=' * 50)
    print('피드백 스토어 테스트')
    print('=' * 50)
    
    summary = store.get_stats_summary()
    print('\n현재 통계:', summary)
    
    learning_data = store.get_learning_data_for_manus()
    print('1층 (예측 피드백):', len(learning_data['layer1_prediction_feedback']), '개')
    print('2층 (당첨 패턴):', learning_data['layer2_winning_pattern_stats'])
    print('3층 (오늘 후보):', len(learning_data['layer3_today_candidates']), '개')
    
    print('\n피드백 스토어 초기화 완료')