# -*- coding: utf-8 -*-
import json
from pathlib import Path
from datetime import datetime

def get_winner_dashboard_data(project_dir):
    project_dir = Path(project_dir)
    reports_dir = project_dir / 'reports'
    
    dashboard = {
        'latest_result': None,
        'history': [],
        'stats': {
            'total_weeks': 0,
            'rank6_count': 0,
            'rank5_count': 0,
            'rank4_count': 0,
            'best_match': 0,
            'best_round': 0
        },
        'recent_trend': []
    }
    
    # 최신 결과
    json_path = reports_dir / 'auto_weekly_result.json'
    if json_path.exists():
        with open(json_path, 'r', encoding='utf-8') as f:
            dashboard['latest_result'] = json.load(f)
    
    # 히스토리
    winner_log = project_dir / 'logs' / 'weekly_winner_log.jsonl'
    if winner_log.exists():
        with open(winner_log, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    dashboard['history'].append(json.loads(line))
                except:
                    pass
    
    # 통계 계산
    if dashboard['history']:
        dashboard['stats']['total_weeks'] = len(dashboard['history'])
        
        for h in dashboard['history']:
            dashboard['stats']['rank6_count'] += h.get('rank6_count', 0) or h.get('rank6', 0)
            dashboard['stats']['rank5_count'] += h.get('rank5_count', 0) or h.get('rank5', 0)
            dashboard['stats']['rank4_count'] += h.get('rank4_count', 0) or h.get('rank4', 0)
            
            best = h.get('best_match_count', 0) or h.get('best_match', 0)
            if best > dashboard['stats']['best_match']:
                dashboard['stats']['best_match'] = best
                dashboard['stats']['best_round'] = h.get('lotto_round', 0)
        
        # 최근 추세 (최근 5주)
        dashboard['recent_trend'] = dashboard['history'][-5:] if len(dashboard['history']) > 5 else dashboard['history']
    
    return dashboard

def render_winner_dashboard(project_dir):
    dashboard = get_winner_dashboard_data(project_dir)
    
    return dashboard

# 대시보드 HTML 생성 (Streamlit 외에서 사용 가능)
def generate_dashboard_html(project_dir):
    dashboard = get_winner_dashboard_data(project_dir)
    
    latest = dashboard.get('latest_result')
    stats = dashboard.get('stats', {})
    history = dashboard.get('history', [])
    
    html = '''
    <div style='background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); padding: 20px; border-radius: 15px; color: white;'>
        <h2 style='text-align: center; margin-bottom: 20px;'>🏆 당첨 현황 대시보드</h2>
    '''
    
    if latest:
        win_nums = latest.get('winning_numbers', [])
        html += f'''
        <div style='background: rgba(255,255,255,0.1); padding: 15px; border-radius: 10px; margin-bottom: 20px;'>
            <h3 style='margin: 0 0 10px 0;'>📢 Latest: {latest.get('lotto_round', 0)}회차</h3>
            <div style='font-size: 24px; text-align: center; margin: 10px 0;'>
                {' '.join([f'<span style=\"background:#e94560;padding:8px 12px;border-radius:5px;margin:2px;display:inline-block;\">{n:02d}</span>' for n in win_nums])}
            </div>
            <p style='text-align: center; color: #aaa; margin: 5px 0;'>검사일시: {latest.get('check_date', '')[:10]}</p>
        </div>
        '''
    
    # 통계
    html += '''
        <div style='display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 20px;'>
    '''
    
    stat_items = [
        ('총 분석', stats.get('total_weeks', 0), '📊', '#4ecdc4'),
        ('4등 달성', stats.get('rank5_count', 0), '🎯', '#45b7d1'),
        ('5등 달성', stats.get('rank4_count', 0), '✨', '#96ceb4'),
        ('최고 일치', stats.get('best_match', 0), '🏆', '#ffeaa7')
    ]
    
    for label, value, icon, color in stat_items:
        html += f'''
            <div style='background: {color}; padding: 15px; border-radius: 10px; text-align: center;'>
                <div style='font-size: 24px;'>{icon}</div>
                <div style='font-size: 28px; font-weight: bold;'>{value}</div>
                <div style='font-size: 12px;'>{label}</div>
            </div>
        '''
    
    html += '</div>'
    
    # 최근 히스토리
    if history:
        html += '''
        <h3 style='margin-bottom: 10px;'>📈 최근 당첨 추이</h3>
        <div style='overflow-x: auto;'>
            <table style='width: 100%; border-collapse: collapse; font-size: 14px;'>
                <tr style='background: rgba(255,255,255,0.1);'>
                    <th style='padding: 10px;'>회차</th>
                    <th style='padding: 10px;'>최고일치</th>
                    <th style='padding: 10px;'>4등</th>
                    <th style='padding: 10px;'>5등</th>
                    <th style='padding: 10px;'>날짜</th>
                </tr>
        '''
        
        for h in history[-8:]:
            date = h.get('timestamp', '')[:10] if h.get('timestamp') else ''
            html += f'''
                <tr style='border-bottom: 1px solid rgba(255,255,255,0.1);'>
                    <td style='padding: 8px;'>{h.get('lotto_round', 0)}회</td>
                    <td style='padding: 8px;'>{h.get('best_match_count', 0) or h.get('best_match', 0)}개</td>
                    <td style='padding: 8px;'>{h.get('rank5_count', 0) or h.get('rank5', 0)}건</td>
                    <td style='padding: 8px;'>{h.get('rank4_count', 0) or h.get('rank4', 0)}건</td>
                    <td style='padding: 8px;'>{date}</td>
                </tr>
            '''
        
        html += '</table></div>'
    
    html += '</div>'
    
    return html

if __name__ == '__main__':
    from pathlib import Path
    project_dir = Path(__file__).resolve().parent
    dashboard = get_winner_dashboard_data(project_dir)
    print(json.dumps(dashboard, ensure_ascii=False, indent=2))