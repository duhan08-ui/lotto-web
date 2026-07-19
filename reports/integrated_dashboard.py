# -*- coding: utf-8 -*-
import streamlit as st
import json
from pathlib import Path
from datetime import datetime

# 성능 분석 대시보드 통합
def render_performance_section(project_dir):
    project_dir = Path(project_dir)
    reports_dir = project_dir / 'reports'
    
    # 데이터 로드
    perf_data = {'metrics': {'total': {}, 'recent': {}}, 'results': [], 'trend': []}
    json_path = reports_dir / 'performance_analysis.json'
    if json_path.exists():
        with open(json_path, 'r', encoding='utf-8') as f:
            loaded = json.load(f)
            perf_data['metrics'] = loaded.get('metrics', perf_data['metrics'])
            perf_data['results'] = loaded.get('detailed_results', [])
    
    perf_log = project_dir / 'logs' / 'performance_log.jsonl'
    if perf_log.exists():
        with open(perf_log, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    try:
                        perf_data['trend'].append(json.loads(line))
                    except:
                        pass
    
    winner_data = {'latest': None, 'history': []}
    winner_json = reports_dir / 'auto_weekly_result.json'
    if winner_json.exists():
        with open(winner_json, 'r', encoding='utf-8') as f:
            winner_data['latest'] = json.load(f)
    
    winner_log = project_dir / 'logs' / 'weekly_winner_log.jsonl'
    if winner_log.exists():
        with open(winner_log, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    try:
                        winner_data['history'].append(json.loads(line))
                    except:
                        pass
    
    metrics = perf_data.get('metrics', {})
    total = metrics.get('total', {})
    recent = metrics.get('recent', {})
    
    # ========================================
    # CSS 스타일
    # ========================================
    st.markdown('''
    <style>
        .perf-card {
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            border-radius: 16px;
            padding: 24px;
            margin: 8px 0;
            box-shadow: 0 4px 20px rgba(0,0,0,0.4);
            transition: transform 0.2s;
        }
        .perf-card:hover {
            transform: translateY(-2px);
        }
        .perf-card-4th { border-left: 5px solid #f1c40f; }
        .perf-card-5th { border-left: 5px solid #2ecc71; }
        .perf-card-top5 { border-left: 5px solid #3498db; }
        .perf-card-trend { border-left: 5px solid #9b59b6; }
        
        .perf-header { color: #888; font-size: 12px; margin-bottom: 8px; }
        .perf-title { color: white; font-size: 16px; font-weight: bold; margin-bottom: 12px; }
        .perf-value { font-size: 42px; font-weight: bold; color: #4ecdc4; }
        .perf-value-gold { color: #f1c40f; }
        .perf-value-green { color: #2ecc71; }
        .perf-value-blue { color: #3498db; }
        
        .perf-bar {
            background: rgba(255,255,255,0.15);
            border-radius: 12px;
            height: 28px;
            margin: 12px 0;
            overflow: hidden;
        }
        .perf-bar-fill {
            height: 100%;
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: bold;
            color: white;
            font-size: 13px;
        }
        .bar-gold { background: linear-gradient(90deg, #e67e22, #f1c40f); }
        .bar-green { background: linear-gradient(90deg, #27ae60, #2ecc71); }
        .bar-blue { background: linear-gradient(90deg, #2980b9, #3498db); }
        .bar-purple { background: linear-gradient(90deg, #8e44ad, #9b59b6); }
        
        .perf-sub { color: #666; font-size: 11px; margin-top: 8px; }
        .perf-stat { text-align: center; padding: 15px; }
        .perf-stat-value { font-size: 32px; font-weight: bold; }
        .perf-stat-label { color: #888; font-size: 11px; margin-top: 5px; }
        
        .lotto-ball {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 40px;
            height: 40px;
            border-radius: 50%;
            font-weight: bold;
            font-size: 15px;
            margin: 3px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.3);
        }
        .ball-odd { background: linear-gradient(135deg, #e74c3c, #ff6b6b); }
        .ball-even { background: linear-gradient(135deg, #3498db, #5dade2); }
        
        .section-title {
            color: white;
            font-size: 18px;
            font-weight: bold;
            margin: 25px 0 15px 0;
            padding-bottom: 10px;
            border-bottom: 2px solid rgba(255,255,255,0.1);
        }
        
        .trend-up { color: #2ecc71; }
        .trend-down { color: #e74c3c; }
        .trend-same { color: #f39c12; }
    </style>
    ''', unsafe_allow_html=True)
    
    # ========================================
    # 헤더
    # ========================================
    st.markdown('<p class=\"section-title\">🏆 AI 추천 번호 적중률 현황</p>', unsafe_allow_html=True)
    
    # ========================================
    # 메인 3카드 (누적 달성률)
    # ========================================
    col1, col2, col3 = st.columns(3)
    
    rate_4th = total.get('hit_rate_4th', 0)
    rounds_4th = total.get('rounds_with_4th', 0)
    total_rounds = total.get('rounds', 0)
    total_4th = total.get('total_4th_hits', 0)
    
    with col1:
        st.markdown(f'''
        <div class=\"perf-card perf-card-4th\">
            <div class=\"perf-header\">📊 누적 성능</div>
            <div class=\"perf-title\">🎯 4등 달성률 <span style=\"color:#f1c40f\">(5개 일치)</span></div>
            <div class=\"perf-value perf-value-gold\">{rate_4th}%</div>
            <div class=\"perf-bar\">
                <div class=\"perf-bar-fill bar-gold\" style=\"width: {min(rate_4th, 100)}%;\">{rate_4th}%</div>
            </div>
            <div class=\"perf-sub\">{rounds_4th}/{total_rounds}회차에서 달성 | 총 {total_4th}건</div>
        </div>
        ''', unsafe_allow_html=True)
    
    rate_5th = total.get('hit_rate_5th', 0)
    rounds_5th = total.get('rounds_with_5th', 0)
    total_5th = total.get('total_5th_hits', 0)
    
    with col2:
        st.markdown(f'''
        <div class=\"perf-card perf-card-5th\">
            <div class=\"perf-header\">📊 누적 성능</div>
            <div class=\"perf-title\">✨ 5등 달성률 <span style=\"color:#2ecc71\">(4개 일치)</span></div>
            <div class=\"perf-value perf-value-green\">{rate_5th}%</div>
            <div class=\"perf-bar\">
                <div class=\"perf-bar-fill bar-green\" style=\"width: {min(rate_5th, 100)}%;\">{rate_5th}%</div>
            </div>
            <div class=\"perf-sub\">{rounds_5th}/{total_rounds}회차에서 달성 | 총 {total_5th}건</div>
        </div>
        ''', unsafe_allow_html=True)
    
    rate_top5 = total.get('hit_rate_top5', 0)
    rounds_top5 = total.get('rounds_with_top5_hit', 0)
    
    with col3:
        st.markdown(f'''
        <div class=\"perf-card perf-card-top5\">
            <div class=\"perf-header\">📊 누적 성능</div>
            <div class=\"perf-title\">⭐ Top5 추천 적중률</div>
            <div class=\"perf-value perf-value-blue\">{rate_top5}%</div>
            <div class=\"perf-bar\">
                <div class=\"perf-bar-fill bar-blue\" style=\"width: {min(rate_top5, 100)}%;\">{rate_top5}%</div>
            </div>
            <div class=\"perf-sub\">{rounds_top5}/{total_rounds}회차에서 4등 이상 달성</div>
        </div>
        ''', unsafe_allow_html=True)
    
    st.markdown('---')
    
    # ========================================
    # 최근 20주 성능
    # ========================================
    st.markdown('<p class=\"section-title\">📉 최근 20주 성능</p>', unsafe_allow_html=True)
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        recent_rate_4th = recent.get('hit_rate_4th', 0)
        recent_4th = recent.get('4th_hits', 0)
        recent_weeks = recent.get('weeks', 20)
        
        st.markdown(f'''
        <div class=\"perf-card\" style=\"text-align: center;\">
            <div class=\"perf-title\" style=\"color: #f1c40f;\">🎯 4등 달성률</div>
            <div class=\"perf-stat-value perf-value-gold\">{recent_rate_4th}%</div>
            <div class=\"perf-stat-label\">최근 {recent_4th}건 ({recent_weeks}주)</div>
        </div>
        ''', unsafe_allow_html=True)
    
    with col2:
        recent_rate_5th = recent.get('hit_rate_5th', 0)
        recent_5th = recent.get('5th_hits', 0)
        
        st.markdown(f'''
        <div class=\"perf-card\" style=\"text-align: center;\">
            <div class=\"perf-title\" style=\"color: #2ecc71;\">✨ 5등 달성률</div>
            <div class=\"perf-stat-value perf-value-green\">{recent_rate_5th}%</div>
            <div class=\"perf-stat-label\">최근 {recent_5th}건 ({recent_weeks}주)</div>
        </div>
        ''', unsafe_allow_html=True)
    
    with col3:
        recent_top5 = recent.get('top5_hits', 0)
        recent_rate_top5 = recent.get('hit_rate_top5', 0)
        
        st.markdown(f'''
        <div class=\"perf-card\" style=\"text-align: center;\">
            <div class=\"perf-title\" style=\"color: #3498db;\">⭐ Top5 적중률</div>
            <div class=\"perf-stat-value perf-value-blue\">{recent_rate_top5}%</div>
            <div class=\"perf-stat-label\">최근 {recent_top5}회 ({recent_weeks}주)</div>
        </div>
        ''', unsafe_allow_html=True)
    
    with col4:
        diff_4th = recent_rate_4th - rate_4th
        if diff_4th > 0:
            trend_class = 'trend-up'
            trend_icon = '📈'
        elif diff_4th < 0:
            trend_class = 'trend-down'
            trend_icon = '📉'
        else:
            trend_class = 'trend-same'
            trend_icon = '➡️'
        
        st.markdown(f'''
        <div class=\"perf-card\" style=\"text-align: center;\">
            <div class=\"perf-title\" style=\"color: #9b59b6;\">{trend_icon} 추세</div>
            <div class=\"perf-stat-value {trend_class}\" style=\"font-size: 24px;\">{'+' if diff_4th > 0 else ''}{diff_4th:.1f}%</div>
            <div class=\"perf-stat-label\">4등 vs 누적 대비</div>
        </div>
        ''', unsafe_allow_html=True)
    
    st.markdown('---')
    
    # ========================================
    # 이번 회차 당첨 결과
    # ========================================
    winner = winner_data.get('latest')
    if winner:
        win_nums = winner.get('winning_numbers', [])
        lotto_round = winner.get('lotto_round', 0)
        best = winner.get('best_match', {})
        best_count = best.get('count', 0)
        
        st.markdown('<p class=\"section-title\">🎰 이번 회차 당첨 결과</p>', unsafe_allow_html=True)
        
        balls_html = ''
        for n in win_nums:
            ball_class = 'ball-odd' if n % 2 == 1 else 'ball-even'
            balls_html += f'<span class=\"lotto-ball {ball_class}\">{n:02d}</span>'
        
        col1, col2 = st.columns([2, 1])
        with col1:
            st.markdown(f'''
            <div class=\"perf-card\">
                <div class=\"perf-header\">현재 {lotto_round}회차</div>
                <div class=\"perf-title\">당첨 번호</div>
                <div style=\"margin-top: 15px; text-align: center;\">{balls_html}</div>
            </div>
            ''', unsafe_allow_html=True)
        
        with col2:
            match_color = '#f1c40f' if best_count >= 5 else ('#2ecc71' if best_count >= 4 else '#888')
            st.markdown(f'''
            <div class=\"perf-card\" style=\"text-align: center;\">
                <div class=\"perf-title\">최고 매칭</div>
                <div class=\"perf-value\" style=\"color: {match_color}; font-size: 56px;\">{best_count}개</div>
                <div class=\"perf-sub\">일치</div>
            </div>
            ''', unsafe_allow_html=True)
    
    # ========================================
    # 상세 히스토리 테이블
    # ========================================
    st.markdown('<p class=\"section-title\">📋 최근 20주 상세 내역</p>', unsafe_allow_html=True)
    
    results = perf_data.get('results', [])
    if results:
        import pandas as pd
        
        table_data = []
        for r in results[:20]:
            actual = r.get('actual_numbers', [])
            nums_str = '  '.join([f'{n:02d}' for n in actual])
            
            icon_4th = '🎯' if r.get('match_5', 0) > 0 else '-'
            icon_5th = '✨' if r.get('match_4', 0) > 0 else '-'
            icon_top5 = '✅' if r.get('top5_hits', 0) > 0 else '-'
            
            table_data.append({
                '회차': r.get('round', 0),
                '당첨번호': nums_str,
                '최고일치': f'{r.get("best_match", 0)}개',
                '4등': icon_4th,
                '5등': icon_5th,
                'Top5': icon_top5
            })
        
        df = pd.DataFrame(table_data)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info('아직 분석 데이터가 없습니다. 먼저 performance_analyzer.py를 실행해주세요.')
    
    # ========================================
    # 성능 추이 그래프
    # ========================================
    trend = perf_data.get('trend', [])
    if len(trend) >= 2:
        st.markdown('<p class=\"section-title\">📈 성능 추이</p>', unsafe_allow_html=True)
        
        trend_data = [{'날짜': t.get('timestamp', '')[:10], '4등': t.get('hit_rate_4th', 0), '5등': t.get('hit_rate_5th', 0)} for t in trend[-8:]]
        
        df_chart = pd.DataFrame(trend_data)
        st.bar_chart(df_chart.set_index('날짜'))

def render_section(project_dir):
    render_performance_section(project_dir)

if __name__ == '__main__':
    import sys
    from pathlib import Path
    
    if len(sys.argv) > 1 and sys.argv[1] == '--test':
        st.set_page_config(page_title='AI 추천 적중률 대시보드', page_icon='🏆', layout='wide')
        project_dir = Path(__file__).resolve().parent
        render_performance_section(project_dir)