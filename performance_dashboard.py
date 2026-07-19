# -*- coding: utf-8 -*-
import json
from pathlib import Path
from datetime import datetime

def load_performance_data(project_dir):
    project_dir = Path(project_dir)
    reports_dir = project_dir / 'reports'
    performance_log = project_dir / 'logs' / 'performance_log.jsonl'
    
    data = {
        'current': None,
        'trend': [],
        'history': []
    }
    
    # 현재 성능 데이터
    json_path = reports_dir / 'performance_analysis.json'
    if json_path.exists():
        with open(json_path, 'r', encoding='utf-8') as f:
            data['current'] = json.load(f)
    
    # 추이 데이터
    if performance_log.exists():
        with open(performance_log, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    data['trend'].append(json.loads(line))
                except:
                    pass
    
    return data

def get_performance_summary(project_dir):
    data = load_performance_data(project_dir)
    current = data.get('current', {})
    
    if not current:
        return {
            'status': 'no_data',
            'message': '아직 분석 데이터가 없습니다. 먼저 분석을 실행해주세요.'
        }
    
    metrics = current.get('metrics', {})
    total = metrics.get('total', {})
    recent = metrics.get('recent', {})
    
    return {
        'status': 'success',
        'total_rounds': total.get('rounds', 0),
        'hit_rate_4th': total.get('hit_rate_4th', 0),
        'hit_rate_5th': total.get('hit_rate_5th', 0),
        'hit_rate_top5': total.get('hit_rate_top5', 0),
        'recent_weeks': recent.get('weeks', 0),
        'recent_hit_rate_4th': recent.get('hit_rate_4th', 0),
        'recent_hit_rate_5th': recent.get('hit_rate_5th', 0),
        'total_4th_hits': total.get('total_4th_hits', 0),
        'total_5th_hits': total.get('total_5th_hits', 0),
        'recent_4th_hits': recent.get('4th_hits', 0),
        'recent_5th_hits': recent.get('5th_hits', 0),
        'trend': data.get('trend', [])
    }

def generate_dashboard_html(project_dir):
    summary = get_performance_summary(project_dir)
    
    if summary['status'] == 'no_data':
        return '''
        <div style='background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); padding: 30px; border-radius: 15px; color: white; text-align: center;'>
            <h2>📊 아직 분석 데이터가 없습니다</h2>
            <p>먼저 performance_analyzer.py를 실행해주세요.</p>
        </div>
        '''
    
    # 진행률 바 HTML 생성
    def progress_bar(value, max_val=100, color='#4ecdc4'):
        percent = min(value, max_val)
        return f'''
        <div style='background: rgba(255,255,255,0.2); border-radius: 10px; height: 20px; width: 100%;'>
            <div style='background: {color}; border-radius: 10px; height: 20px; width: {percent}%; text-align: center; line-height: 20px; font-size: 12px;'>{percent}%</div>
        </div>
        '''
    
    html = '''
    <div style='background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); padding: 20px; border-radius: 15px; color: white;'>
        <h2 style='text-align: center; margin-bottom: 20px;'>📊 AI 추천 번호 적중률 분석</h2>
        <p style='text-align: center; color: #aaa;'>최근 업데이트: ''' + datetime.now().strftime('%Y-%m-%d') + '''</p>
        
        <!-- 누적 성능 -->
        <div style='background: rgba(255,255,255,0.05); padding: 15px; border-radius: 10px; margin-bottom: 15px;'>
            <h3 style='margin: 0 0 15px 0; color: #4ecdc4;'>📈 누적 성능 (''' + str(summary['total_rounds']) + '''회차)</h3>
            
            <div style='margin-bottom: 12px;'>
                <div style='display: flex; justify-content: space-between; margin-bottom: 5px;'>
                    <span>🎯 4등 달성률 (5개 일치)</span>
                    <span style='font-weight: bold; color: #ffeaa7;'>''' + str(summary['hit_rate_4th']) + '''%</span>
                </div>
                ''' + progress_bar(summary['hit_rate_4th'], 100, '#ffeaa7') + '''
                <small style='color: #aaa;'>4등 ''' + str(summary['total_4th_hits']) + '''건 달성</small>
            </div>
            
            <div style='margin-bottom: 12px;'>
                <div style='display: flex; justify-content: space-between; margin-bottom: 5px;'>
                    <span>✨ 5등 달성률 (4개 일치)</span>
                    <span style='font-weight: bold; color: #a8e6cf;'>''' + str(summary['hit_rate_5th']) + '''%</span>
                </div>
                ''' + progress_bar(summary['hit_rate_5th'], 100, '#a8e6cf') + '''
                <small style='color: #aaa;'>5등 ''' + str(summary['total_5th_hits']) + '''건 달성</small>
            </div>
            
            <div>
                <div style='display: flex; justify-content: space-between; margin-bottom: 5px;'>
                    <span>⭐ Top5 추천 적중률</span>
                    <span style='font-weight: bold; color: #74b9ff;'>''' + str(summary['hit_rate_top5']) + '''%</span>
                </div>
                ''' + progress_bar(summary['hit_rate_top5'], 100, '#74b9ff') + '''
            </div>
        </div>
        
        <!-- 최근 성능 -->
        <div style='background: rgba(255,255,255,0.05); padding: 15px; border-radius: 10px; margin-bottom: 15px;'>
            <h3 style='margin: 0 0 15px 0; color: #a29bfe;'>📉 최근 ''' + str(summary['recent_weeks']) + '''주 성능</h3>
            
            <div style='display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; text-align: center;'>
                <div style='background: rgba(255,234,167,0.2); padding: 15px; border-radius: 10px;'>
                    <div style='font-size: 28px; font-weight: bold; color: #ffeaa7;'>''' + str(summary['recent_hit_rate_4th']) + '''%</div>
                    <div style='font-size: 12px; color: #aaa;'>4등 달성률</div>
                    <div style='font-size: 11px; color: #666; margin-top: 5px;>(''' + str(summary['recent_4th_hits']) + '''건)</div>
                </div>
                
                <div style='background: rgba(168,230,207,0.2); padding: 15px; border-radius: 10px;'>
                    <div style='font-size: 28px; font-weight: bold; color: #a8e6cf;'>''' + str(summary['recent_hit_rate_5th']) + '''%</div>
                    <div style='font-size: 12px; color: #aaa;'>5등 달성률</div>
                    <div style='font-size: 11px; color: #666; margin-top: 5px;>(''' + str(summary['recent_5th_hits']) + '''건)</div>
                </div>
                
                <div style='background: rgba(116,185,255,0.2); padding: 15px; border-radius: 10px;'>
                    <div style='font-size: 28px; font-weight: bold; color: #74b9ff;'>''' + str(summary.get('recent_top5_rate', 0)) + '''%</div>
                    <div style='font-size: 12px; color: #aaa;'>Top5 적중률</div>
                </div>
            </div>
        </div>
    '''
    
    # 추이 차트 (텍스트 기반)
    trend = summary.get('trend', [])
    if len(trend) >= 2:
        html += '''
        <div style='background: rgba(255,255,255,0.05); padding: 15px; border-radius: 10px;'>
            <h3 style='margin: 0 0 15px 0; color: #fd79a8;'>📈 성능 추이</h3>
            <div style='font-size: 12px; color: #aaa;'>
        '''
        
        for i, t in enumerate(trend[-6:]):
            date = t.get('timestamp', '')[:10] if t.get('timestamp') else ''
            r4 = t.get('hit_rate_4th', 0)
            r5 = t.get('hit_rate_5th', 0)
            
            # 미니 막대그래프
            bar4 = '█' * int(r4 / 10) + '░' * (10 - int(r4 / 10))
            bar5 = '█' * int(r5 / 10) + '░' * (10 - int(r5 / 10))
            
            html += f'''
            <div style='margin-bottom: 8px;'>
                <span style='color: #666;'>{date}</span>
                4등: <span style='color: #ffeaa7;'>{bar4}</span> {r4}%
                | 5등: <span style='color: #a8e6cf;'>{bar5}</span> {r5}%
            </div>
            '''
        
        html += '</div></div>'
    
    html += '</div>'
    
    return html

def get_table_data(project_dir, limit=20):
    data = load_performance_data(project_dir)
    current = data.get('current', {})
    results = current.get('detailed_results', [])
    
    return results[:limit]

if __name__ == '__main__':
    from pathlib import Path
    project_dir = Path(__file__).resolve().parent
    
    summary = get_performance_summary(project_dir)
    print('적중률 분석 결과:')
    print('4등 달성률:', summary.get('hit_rate_4th', 0), '%')
    print('5등 달성률:', summary.get('hit_rate_5th', 0), '%')
    print('Top5 적중률:', summary.get('hit_rate_top5', 0), '%')