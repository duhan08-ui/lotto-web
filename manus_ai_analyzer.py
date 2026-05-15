#!/usr/bin/env python3
# -*- coding: utf-8 -*-
'''Manus AI 분석기 - 발전하는 피드백 루프, 3층 구조 프롬프트'''

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

PROJECT_DIR = Path(__file__).resolve().parent
import sys
sys.path.append(str(PROJECT_DIR))

from feedback_store import FeedbackStore
from log_utils import persist_log_record, utc_now_iso

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(PROJECT_DIR / 'logs' / 'manus_ai.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('ManusAIAnalyzer')

KST = ZoneInfo('Asia/Seoul')
MANUS_API_KEY = os.getenv('MANUS_API_KEY')
API_BASE_URL = 'https://api.manus.ai/v2'


class ManusAIAnalyzer:
    '''Manus API 기반 지능형 분석기 (3층 피드백 루프)'''
    
    def __init__(self, project_dir: Path = None):
        self.project_dir = project_dir or PROJECT_DIR
        self.feedback_store = FeedbackStore(project_dir)
        self.log_dir = self.project_dir / 'logs'
        self.reports_dir = self.project_dir / 'reports'
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
    
    def utc_now_iso(self) -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    
    def load_today_candidates(self, limit: int = 20) -> list:
        '''오늘의 로컬 엔진 후보 로드'''
        prediction_log = self.log_dir / 'prediction_log.jsonl'
        
        if not prediction_log.exists():
            logger.warning('prediction_log.jsonl 없음 - 기본 데이터 반환')
            return self._get_default_candidates()
        
        candidates = []
        try:
            with open(prediction_log, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                for line in lines[-limit:]:
                    try:
                        data = json.loads(line.strip())
                        numbers = data.get('numbers', [])
                        if len(numbers) == 6:
                            candidates.append({
                                'numbers': numbers,
                                'score': data.get('score', 0),
                                'anti_score': data.get('anti_score', 0),
                                'crowd_proxy': data.get('crowd_proxy', 0)
                            })
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error('예측 로그 읽기 오류: %s' % e)
        
        if not candidates:
            return self._get_default_candidates()
        
        return candidates[:limit]
    
    def _get_default_candidates(self) -> list:
        '''기본 후보 (테스트/초기 데이터용)'''
        return [
            {'numbers': [3, 17, 24, 32, 38, 44], 'score': 7.8, 'anti_score': 8.2, 'crowd_proxy': 12.1},
            {'numbers': [7, 19, 25, 33, 40, 45], 'score': 7.5, 'anti_score': 7.9, 'crowd_proxy': 11.8},
            {'numbers': [5, 14, 22, 31, 37, 42], 'score': 7.2, 'anti_score': 7.5, 'crowd_proxy': 13.2},
            {'numbers': [9, 16, 26, 35, 39, 43], 'score': 6.9, 'anti_score': 8.1, 'crowd_proxy': 10.5},
            {'numbers': [2, 18, 27, 34, 41, 44], 'score': 6.8, 'anti_score': 7.7, 'crowd_proxy': 11.3},
        ]
    
    def build_layer1_prompt(self) -> str:
        '''1층: 과거 예측 피드백 데이터 프롬프트'''
        learning_data = self.feedback_store.get_learning_data_for_manus(limit=20)
        layer1 = learning_data.get('layer1_prediction_feedback', [])
        
        if not layer1:
            return '''
[1층 - 과거 예측 피드백 데이터]
아직 축적된 피드백 데이터가 없습니다.
첫 예측부터 데이터가 쌓이기 시작하면 이 층이 강화됩니다.
'''
        
        prompt = '[1층 - 과거 예측 피드백 데이터]\n'
        prompt += '총 %d회차의 예측 vs 실제 비교 데이터:\n\n' % len(layer1)
        
        for item in layer1[:15]:
            pred_nums = ', '.join('%02d' % n for n in item['predicted'])
            actual_nums = ', '.join('%02d' % n for n in item['actual'])
            prompt += '- 회차%d: 예측[%s] -> 실제[%s] | 적중%d개 | 합계%d, 고범위%d개\n' % (
                item['round'], pred_nums, actual_nums, item['matched'],
                item['sum'], item['high_count']
            )
        
        successful = [item for item in layer1 if item['matched'] >= 3]
        if successful:
            avg_sum = sum(item['sum'] for item in successful) / len(successful)
            avg_high = sum(item['high_count'] for item in successful) / len(successful)
            prompt += '\n[3개 이상 적중 패턴 특징]\n'
            prompt += '  - 평균 합계: %.1f\n' % avg_sum
            prompt += '  - 평균 고범위(32+) 개수: %.1f\n' % avg_high
        
        return prompt
    
    def build_layer2_prompt(self) -> str:
        '''2층: 당첨 패턴 통계 프롬프트'''
        learning_data = self.feedback_store.get_learning_data_for_manus()
        layer2 = learning_data.get('layer2_winning_pattern_stats', {})
        
        if not layer2 or layer2.get('recent_count', 0) == 0:
            return '''
[2층 - 당첨 패턴 통계]
아직 당첨 데이터가 충분하지 않습니다.
'''
        
        prompt = '[2층 - 최근 당첨 패턴 통계]\n'
        prompt += '최근 %d회차 분석:\n' % layer2['recent_count']
        prompt += '  - 평균 합계: %.1f\n' % layer2['avg_sum']
        prompt += '  - 평균 고범위(32+) 포함: %.1f개\n' % layer2['avg_high_count']
        prompt += '  - 평균 홀수 개수: %.1f\n' % layer2['avg_odd_count']
        prompt += '  - 평균 연속쌍: %.1f\n' % layer2['avg_consecutive_pairs']
        prompt += '  - 고범위 2개 이상 비율: %.0f%%\n' % (layer2['high_range_ratio'] * 100)
        
        return prompt
    
    def build_layer3_prompt(self) -> str:
        '''3층: 오늘의 후보군 프롬프트'''
        candidates = self.load_today_candidates(20)
        
        if not candidates:
            return '''
[3층 - 오늘의 후보군]
후보 데이터가 없습니다.
'''
        
        prompt = '[3층 - 오늘의 로컬 엔진 후보군 (상위 20개)]\n'
        prompt += 'anti-pattern 점수순 정렬:\n\n'
        
        for i, cand in enumerate(candidates[:20], 1):
            nums = ', '.join('%02d' % n for n in cand['numbers'])
            prompt += '%2d. [%s] | anti_score: %.2f | crowd_proxy: %.2f\n' % (
                i, nums, cand['anti_score'], cand['crowd_proxy']
            )
        
        return prompt
    
    def build_enhanced_prompt(self, custom_instructions: str = None) -> str:
        '''增强된 3층 프롬프트 구성'''
        
        prompt = '''당신은 번호 분석 전문가입니다. 

아래 3층 구조 데이터를 바탕으로 다음 회차 가능성이 가장 높은 번호 5세트를 추천해주세요.

'''
        
        prompt += self.build_layer1_prompt()
        prompt += '\n\n'
        prompt += self.build_layer2_prompt()
        prompt += '\n\n'
        prompt += self.build_layer3_prompt()
        prompt += '\n\n'
        
        prompt += '''[분석 요청 사항]

1. 패턴 학습 적용: 1층 데이터에서 3개 이상 적중한 패턴의 공통점을 파악하여 적용
2. 트렌드 반영: 2층의 최근 당첨 트렌드(합계, 고범위 빈도 등)를 고려
3. 후보군 평가: 3층 후보군을 기반으로 하되, 반드시 3층의 번호만 사용
4. 다양성 보장: 5세트가 서로 다른 분석 관점을 반영 (순위 간 번호 겹치지 않게)
5. 선택 근거 명시: 각 세트가 어떤 학습 패턴/트렌드를 반영하는지 설명
6. 크레딧 절약: 핵심 분석만 수행, 299 크레딧 제한 준수

출력 형식:
## 추천 번호 5세트

### 1순위: [번호 6개]
- 선택 근거: (어떤 패턴/트렌드 반영)

### 2순위: [번호 6개]
...

마크다운 형식으로 작성해주세요.
'''
        
        if custom_instructions:
            prompt += '\n\n[추가 요청]\n' + custom_instructions
        
        return prompt
    
    def parse_manus_response(self, response: str) -> dict:
        '''Manus 응답 파싱'''
        result = {
            'raw_response': response,
            'recommended_sets': [],
            'success': False
        }
        
        number_pattern = r'\b([1-4][0-9])\b'
        
        sections = re.split(r'#{1,3}\b', response)
        
        recommended_sets = []
        for section in sections:
            numbers = re.findall(number_pattern, section)
            if len(numbers) >= 6:
                unique_numbers = sorted(set(int(n) for n in numbers[:6]))
                if len(unique_numbers) == 6:
                    recommended_sets.append(unique_numbers)
        
        set_blocks = re.split(r'(?:###\n|#{2,3}[^\n]+\n)', response)
        for block in set_blocks:
            numbers = re.findall(number_pattern, block)
            if 5 <= len(numbers) <= 7:
                unique_numbers = sorted(set(int(n) for n in numbers[:6]))
                if len(unique_numbers) == 6:
                    recommended_sets.append(unique_numbers)
        
        seen = set()
        unique_sets = []
        for numbers in recommended_sets:
            key = tuple(numbers)
            if key not in seen:
                seen.add(key)
                unique_sets.append(numbers)
        
        result['recommended_sets'] = unique_sets[:5]
        result['success'] = len(unique_sets) > 0
        
        return result
    
    def call_manus_api(self, prompt: str, max_wait_seconds: int = 300) -> str:
        '''Manus API 호출'''
        if not MANUS_API_KEY:
            logger.error('MANUS_API_KEY가 설정되지 않았습니다.')
            return '에러: API 키가 없습니다. .env 파일에 MANUS_API_KEY를 설정해주세요.'
        
        headers = {
            'x-manus-api-key': MANUS_API_KEY,
            'Content-Type': 'application/json'
        }
        
        try:
            create_res = requests.post(
                API_BASE_URL + '/task.create',
                headers=headers,
                json={
                    'message': {'content': [{'type': 'text', 'text': prompt}]},
                    'title': '번호 분석 ' + datetime.now(KST).strftime('%Y-%m-%d')
                },
                timeout=30
            )
            create_data = create_res.json()
            
            if not create_data.get('ok'):
                error_msg = create_data.get('error', {}).get('message', '알 수 없는 오류')
                logger.error('태스크 생성 실패: %s' % error_msg)
                return '에러: 태스크 생성 실패 - ' + error_msg
            
            task_id = create_data['task_id']
            logger.info('Manus 태스크 생성됨: %s' % task_id)
            
        except requests.exceptions.Timeout:
            logger.error('API 요청 타임아웃')
            return '에러: API 요청이 타임아웃되었습니다.'
        except Exception as e:
            logger.error('API 호출 오류: %s' % e)
            return '에러: API 호출 중 예외 발생 - ' + str(e)
        
        start_time = time.time()
        while time.time() - start_time < max_wait_seconds:
            try:
                list_res = requests.get(
                    API_BASE_URL + '/task.listMessages',
                    headers=headers,
                    params={'task_id': task_id, 'order': 'desc', 'limit': 1},
                    timeout=20
                )
                list_data = list_res.json()
                
                if not list_data.get('ok'):
                    time.sleep(10)
                    continue
                
                messages = list_data.get('messages', [])
                for msg in messages:
                    if msg.get('type') == 'status_update':
                        status_info = msg.get('status_update', {})
                        agent_status = status_info.get('agent_status', '')
                        
                        if agent_status == 'stopped':
                            full_res = requests.get(
                                API_BASE_URL + '/task.listMessages',
                                headers=headers,
                                params={'task_id': task_id, 'order': 'asc'},
                                timeout=20
                            )
                            full_messages = full_res.json().get('messages', [])
                            
                            for m in reversed(full_messages):
                                if m.get('type') == 'assistant_message':
                                    return m['assistant_message'].get('content', '')
                
                logger.info('분석 중... (%.0f초 경과)' % (time.time() - start_time))
                time.sleep(15)
                
            except Exception as e:
                logger.warning('폴링 중 오류: %s' % e)
                time.sleep(10)
        
        return '에러: 분석 시간이 초과되었습니다.'
    
    def run_analysis(self, custom_instructions: str = None, use_manus: bool = None, save_results: bool = True) -> dict:
        '''전체 분석 실행'''
        
        if use_manus is None:
            use_manus = MANUS_API_KEY is not None
        
        # 대상 회차 정보 가져오기
        from log_utils import get_round_context
        ctx = get_round_context(self.project_dir / 'lotto.xlsx')
        target_round = ctx.get('target_round') or 0
        
        result = {
            'timestamp': self.utc_now_iso(),
            'success': False,
            'recommended_sets': [],
            'raw_response': '',
            'learning_data': None,
            'target_round': target_round
        }
        
        logger.info('=' * 60)
        logger.info('Manus AI 분석 시작 (3층 피드백 루프)')
        
        learning_data = self.feedback_store.get_learning_data_for_manus()
        result['learning_data'] = learning_data
        
        l1_count = len(learning_data['layer1_prediction_feedback'])
        l2_data = learning_data['layer2_winning_pattern_stats']
        l3_count = len(learning_data['layer3_today_candidates'])
        logger.info('1층 (예측 피드백): %d개' % l1_count)
        logger.info('2층 (당첨 패턴): %s' % l2_data)
        logger.info('3층 (오늘 후보): %d개' % l3_count)
        
        prompt = self.build_enhanced_prompt(custom_instructions)
        
        if use_manus:
            logger.info('Manus API 호출 중...')
            raw_response = self.call_manus_api(prompt)
            result['raw_response'] = raw_response
            
            parsed = self.parse_manus_response(raw_response)
            result['recommended_sets'] = parsed['recommended_sets']
            result['success'] = parsed['success']
            
            if result['success']:
                logger.info('추천 세트 %d개 추출 완료' % len(result['recommended_sets']))
            else:
                logger.warning('추천 세트 추출 실패 - 원본 응답 저장')
        
        if save_results:
            self._save_analysis_results(result)
        
        logger.info('=' * 60)
        return result
    
    def _save_analysis_results(self, result: dict):
        '''분석 결과 저장'''
        
        report_path = self.reports_dir / 'weekly_ai_recommendation.txt'
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(result['raw_response'] or '분석 결과 없음')
        
        sets_path = self.reports_dir / 'recommended_sets.json'
        with open(sets_path, 'w', encoding='utf-8') as f:
            json.dump({
                'timestamp': result['timestamp'],
                'sets': result['recommended_sets'],
                'success': result['success']
            }, f, ensure_ascii=False, indent=2)
        
        # 기본 AI 분석과 동일한 형식으로 저장 (ai_ui_utils.py 호환)
        intel_report_path = self.reports_dir / 'intelligent_analysis_report.md'
        intel_report = []
        target_round = result.get('target_round', 0)
        intel_report.append(f"<!-- metadata: round={target_round}, date={datetime.now(KST).strftime('%Y-%m-%d')} -->")
        
        # 추천 세트를 로그에 저장 + 리포트 파일에도 저장
        if result['success'] and result['recommended_sets']:
            for i, numbers in enumerate(result['recommended_sets'], 1):
                nums_str = ", ".join(f"{n:02d}" for n in sorted(numbers))
                intel_report.append(f"{i}순위: {nums_str} (점수: {10.0 - i * 0.5:.2f})")
                
                # 수동 로그에 저장 (prediction_log.jsonl)
                log_record = {
                    "timestamp": self.utc_now_iso(),
                    "target_round": target_round,
                    "candidate_rank": i,
                    "numbers": sorted(numbers),
                    "score": 10.0 - i * 0.5,
                    "log_type": "prediction",
                    "is_manus_intelligent": True
                }
                persist_log_record(self.log_dir, "prediction", log_record)
                logger.info(f'Manus 분석 결과 로그 저장: {i}순위 - {nums_str}')
        else:
            intel_report.append("분석 결과 없음")
        
        with open(intel_report_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(intel_report))
        
        learning_path = self.reports_dir / 'learning_data_snapshot.json'
        with open(learning_path, 'w', encoding='utf-8') as f:
            json.dump(result['learning_data'], f, ensure_ascii=False, indent=2)
        
        logger.info('결과 저장 완료: %s' % report_path)
    
    def run_scheduled_analysis(self) -> dict:
        '''스케줄된 분석 실행 (매일 오전 10시)'''
        logger.info('스케줄된 Manus 분석 시작')
        
        result = self.run_analysis(
            custom_instructions='매일 오전 분석 - 점심 전까지 최종 추천 제공',
            use_manus=MANUS_API_KEY is not None
        )
        
        if result['success']:
            self.feedback_store.generate_feedback_report()
        
        return result
    
    def get_latest_recommendations(self) -> list:
        '''가장 최근 추천 세트 조회'''
        sets_path = self.reports_dir / 'recommended_sets.json'
        
        if not sets_path.exists():
            return []
        
        try:
            with open(sets_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data.get('sets', [])
        except Exception:
            return []


def run_manus_intelligent_analysis():
    '''호환성을 위한 래퍼 함수'''
    analyzer = ManusAIAnalyzer()
    return analyzer.run_scheduled_analysis()


if __name__ == '__main__':
    analyzer = ManusAIAnalyzer()
    
    print('=' * 60)
    print('Manus AI 분석기 테스트 (3층 피드백 루프)')
    print('=' * 60)
    
    learning_data = analyzer.feedback_store.get_learning_data_for_manus()
    
    print('\n현재 학습 데이터 상태:')
    print('  1층 (예측 피드백): %d개' % len(learning_data['layer1_prediction_feedback']))
    print('  2층 (당첨 패턴): recent_count = %d' % learning_data['layer2_winning_pattern_stats'].get('recent_count', 0))
    print('  3층 (오늘 후보): %d개' % len(learning_data['layer3_today_candidates']))
    
    print('\n3층 프롬프트 미리보기:')
    print('-' * 40)
    layer3 = analyzer.build_layer3_prompt()
    print(layer3[:500] + '...')
    
    if MANUS_API_KEY:
        print('\n[OK] API 키 설정됨 - 실제 분석 가능')
        response = analyzer.run_analysis(use_manus=True, save_results=True)
        print('\n분석 결과: %d개 세트 추천' % len(response['recommended_sets']))
    else:
        print('\n[WARNING] API 키 없음 - 시뮬레이션 모드')
        print('실제 분석을 위해 .env 파일에 MANUS_API_KEY를 설정하세요.')
    
    print('\n테스트 완료')