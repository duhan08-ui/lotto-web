# -*- coding: utf-8 -*-
# ============================================
# app.py에 성능 대시보드 통합 가이드
# ============================================
#
# 이 파일을 app.py에 추가하여 성능 대시보드를 사용할 수 있습니다.
# 아래 코드를 app.py의 적절한 위치에 붙여넣기 하세요.
#
# ============================================

def add_performance_dashboard_to_app():
    '''
    app.py에 통합할 코드:
    
    # 1. imports 추가 (이미 있다면 생략)
    import json
    from pathlib import Path
    
    # 2. performance_dashboard.py import 추가
    try:
        from integrated_dashboard import render_performance_section
        DASHBOARD_AVAILABLE = True
    except:
        DASHBOARD_AVAILABLE = False
    
    # 3. app.py의 사이드바 또는 메인 영역에 아래 코드 추가
    '''
    
    code = """
# ============================================
# 성능 대시보드 섹션 (app.py에 추가)
# ============================================

def show_performance_dashboard():
    import streamlit as st
    import json
    from pathlib import Path
    
    # 프로젝트 디렉토리 설정
    PROJECT_DIR = Path(__file__).resolve().parent
    REPORTS_DIR = PROJECT_DIR / 'reports'
    
    # ==========================================
    # 데이터 로드
    # ==========================================
    perf_data = {'metrics': {'total': {}, 'recent': {}}, 'results': [], 'trend': []}
    json_path = REPORTS_DIR / 'performance_analysis.json'
    if json_path.exists():
        with open(json_path, 'r', encoding='utf-8') as f:
            loaded = json.load(f)
            perf_data['metrics'] = loaded.get('metrics', perf_data['metrics'])
            perf_data['results'] = loaded.get('detailed_results', [])
    
    # 성능 로그
    perf_log = PROJECT_DIR / 'logs' / 'performance_log.jsonl'
    if perf_log.exists():
        with open(perf_log, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    try:
                        perf_data['trend'].append(json.loads(line))
                    except:
                        pass
    
    metrics = perf_data.get('metrics', {})
    total = metrics.get('total', {})
    recent = metrics.get('recent', {})
    
    # ==========================================
    # CSS 스타일
    # ==========================================
    st.markdown('''
    <style>
        .db-card {background: linear-gradient(135deg, #1a1a2e, #16213e); border-radius: 16px; padding: 20px; margin: 8px 0; box-shadow: 0 4px 15px rgba(0,0,0,0.3);}
        .db-card-4th {border-left: 5px solid #f1c40f;}
        .db-card-5th {border-left: 5px solid #2ecc71;}
        .db-card-top5 {border-left: 5px solid #3498db;}
        .db-header {color: #888; font-size: 12px; margin-bottom: 8px;}
        .db-title {color: white; font-size: 15px; font-weight: bold; margin-bottom: 10px;}
        .db-value {font-size: 38px; font-weight: bold; color: #4ecdc4;}
        .db-bar {background: rgba(255,255,255,0.12); border-radius: 12px; height: 26px; margin: 10px 0; overflow: hidden;}
        .db-bar-fill {height: 100%; border-radius: 12px; display: flex; align-items: center; justify-content: center; font-weight: bold; color: white; font-size: 12px;}
        .bar-gold {background: linear-gradient(90deg, #e67e22, #f1c40f);}
        .bar-green {background: linear-gradient(90deg, #27ae60, #2ecc71);}
        .bar-blue {background: linear-gradient(90deg, #2980b9, #3498db);}
        .db-sub {color: #666; font-size: 10px; margin-top: 6px;}
        .section-title {color: white; font-size: 17px; font-weight: bold; margin: 20px 0 12px 0; padding-bottom: 8px; border-bottom: 2px solid rgba(255,255,255,0.1);}
        .ball {display: inline-flex; align-items: center; justify-content: center; width: 36px; height: 36px; border-radius: 50%; font-weight: bold; font-size: 14px; margin: 2px; box-shadow: 0 2px 6px rgba(0,0,0,0.3);}
        .ball-odd {background: linear-gradient(135deg, #e74c3c, #ff6b6b);}
        .ball-even {background: linear-gradient(135deg, #3498db, #5dade2);}
    </style>
    ''', unsafe_allow_html=True)
    
    # ==========================================
    # 헤더
    # ==========================================
    st.markdown('<p class=\"section-title\">🏆 AI 추천 번호 적중률 현황</p>', unsafe_allow_html=True)
    
    # ==========================================
    # 3카드 (4등/5등/Top5 달성률)
    # ==========================================
    col1, col2, col3 = st.columns(3)
    
    rate_4th = total.get('hit_rate_4th', 0)
    rounds_4th = total.get('rounds_with_4th', 0)
    total_rounds = total.get('rounds', 0)
    total_4th = total.get('total_4th_hits', 0)
    
    with col1:
        st.markdown(f'''
        <div class=\"db-card db-card-4th\">
            <div class=\"db-header\">📊 누적 성능</div>
            <div class=\"db-title\">🎯 4등 달성률</div>
            <div class=\"db-value\" style=\"color: #f1c40f;\">{rate_4th}%</div>
            <div class=\"db-bar\"><div class=\"db-bar-fill bar-gold\" style=\"width: {min(rate_4th, 100)}%;\">{rate_4th}%</div></div>
            <div class=\"db-sub\">{rounds_4th}/{total_rounds}회차 | 총 {total_4th}건</div>
        </div>
        ''', unsafe_allow_html=True)
    
    rate_5th = total.get('hit_rate_5th', 0)
    rounds_5th = total.get('rounds_with_5th', 0)
    total_5th = total.get('total_5th_hits', 0)
    
    with col2:
        st.markdown(f'''
        <div class=\"db-card db-card-5th\">
            <div class=\"db-header\">📊 누적 성능</div>
            <div class=\"db-title\">✨ 5등 달성률</div>
            <div class=\"db-value\" style=\"color: #2ecc71;\">{rate_5th}%</div>
            <div class=\"db-bar\"><div class=\"db-bar-fill bar-green\" style=\"width: {min(rate_5th, 100)}%;\">{rate_5th}%</div></div>
            <div class=\"db-sub\">{rounds_5th}/{total_rounds}회차 | 총 {total_5th}건</div>
        </div>
        ''', unsafe_allow_html=True)
    
    rate_top5 = total.get('hit_rate_top5', 0)
    rounds_top5 = total.get('rounds_with_top5_hit', 0)
    
    with col3:
        st.markdown(f'''
        <div class=\"db-card db-card-top5\">
            <div class=\"db-header\">📊 누적 성능</div>
            <div class=\"db-title\">⭐ Top5 추천 적중률</div>
            <div class=\"db-value\" style=\"color: #3498db;\">{rate_top5}%</div>
            <div class=\"db-bar\"><div class=\"db-bar-fill bar-blue\" style=\"width: {min(rate_top5, 100)}%;\">{rate_top5}%</div></div>
            <div class=\"db-sub\">{rounds_top5}/{total_rounds}회차에서 4등 이상</div>
        </div>
        ''', unsafe_allow_html=True)
    
    st.markdown('---')
    
    # ==========================================
    # 최근 20주 성능
    # ==========================================
    st.markdown('<p class=\"section-title\">📉 최근 20주 성능</p>', unsafe_allow_html=True)
    
    col1, col2, col3, col4 = st.columns(4)
    
    recent_rate_4th = recent.get('hit_rate_4th', 0)
    recent_4th = recent.get('4th_hits', 0)
    recent_weeks = recent.get('weeks', 20)
    
    with col1:
        st.markdown(f'''
        <div class=\"db-card\" style=\"text-align: center;\">
            <div class=\"db-title\" style=\"color: #f1c40f;\">🎯 4등</div>
            <div style=\"font-size: 28px; font-weight: bold; color: #f1c40f;\">{recent_rate_4th}%</div>
            <div class=\"db-sub\">{recent_4th}건</div>
        </div>
        ''', unsafe_allow_html=True)
    
    recent_rate_5th = recent.get('hit_rate_5th', 0)
    recent_5th = recent.get('5th_hits', 0)
    
    with col2:
        st.markdown(f'''
        <div class=\"db-card\" style=\"text-align: center;\">
            <div class=\"db-title\" style=\"color: #2ecc71;\">✨ 5등</div>
            <div style=\"font-size: 28px; font-weight: bold; color: #2ecc71;\">{recent_rate_5th}%</div>
            <div class=\"db-sub\">{recent_5th}건</div>
        </div>
        ''', unsafe_allow_html=True)
    
    recent_top5 = recent.get('top5_hits', 0)
    recent_rate_top5 = recent.get('hit_rate_top5', 0)
    
    with col3:
        st.markdown(f'''
        <div class=\"db-card\" style=\"text-align: center;\">
            <div class=\"db-title\" style=\"color: #3498db;\">⭐ Top5</div>
            <div style=\"font-size: 28px; font-weight: bold; color: #3498db;\">{recent_rate_top5}%</div>
            <div class=\"db-sub\">{recent_top5}회</div>
        </div>
        ''', unsafe_allow_html=True)
    
    with col4:
        diff_4th = recent_rate_4th - rate_4th
        icon = '📈' if diff_4th > 0 else ('📉' if diff_4th < 0 else '➡️')
        color = '#2ecc71' if diff_4th >= 0 else '#e74c3c'
        
        st.markdown(f'''
        <div class=\"db-card\" style=\"text-align: center;\">
            <div class=\"db-title\" style=\"color: #9b59b6;\">{icon} 추세</div>
            <div style=\"font-size: 22px; font-weight: bold; color: {color};\">{'+' if diff_4th > 0 else ''}{diff_4th:.1f}%</div>
            <div class=\"db-sub\">vs 누적</div>
        </div>
        ''', unsafe_allow_html=True)
    
    st.markdown('---')
    
    # ==========================================
    # 상세 내역 테이블
    # ==========================================
    st.markdown('<p class=\"section-title\">📋 최근 20주 상세 내역</p>', unsafe_allow_html=True)
    
    results = perf_data.get('results', [])
    if results:
        import pandas as pd
        
        table_data = []
        for r in results[:20]:
            actual = r.get('actual_numbers', [])
            nums_str = '  '.join([f'{n:02d}' for n in actual])
            
            table_data.append({
                '회차': r.get('round', 0),
                '당첨번호': nums_str,
                '최고': f'{r.get("best_match", 0)}개',
                '4등': '🎯' if r.get('match_5', 0) > 0 else '-',
                '5등': '✨' if r.get('match_4', 0) > 0 else '-',
                'Top5': '✅' if r.get('top5_hits', 0) > 0 else '-'
            })
        
        st.dataframe(pd.DataFrame(table_data), use_container_width=True, hide_index=True)
    else:
        st.info('아직 분석 데이터가 없습니다. performance_analyzer.py를 실행해주세요.')
    
    # ==========================================
    # 추이 그래프
    # ==========================================
    trend = perf_data.get('trend', [])
    if len(trend) >= 2:
        st.markdown('<p class=\"section-title\">📈 성능 추이</p>', unsafe_allow_html=True)
        
        import pandas as pd
        trend_data = [{'날짜': t.get('timestamp', '')[:10], '4등': t.get('hit_rate_4th', 0), '5등': t.get('hit_rate_5th', 0)} for t in trend[-8:]]
        st.bar_chart(pd.DataFrame(trend_data).set_index('날짜'))

# ==========================================
# 사용 방법:
# app.py의 적절한 위치에서 아래처럼 호출하세요:
#
# if st.session_state.get('show_performance_dashboard'):
#     show_performance_dashboard()
#
# ============================================
"""
    
    return code

if __name__ == '__main__':
    code = add_performance_dashboard_to_app()
    print('=' * 60)
    print('app.py 통합 코드 생성 완료')
    print('=' * 60)
    print('')
    print('사용법:')
    print('1. performance_analyzer.py 실행')
    print('2. app.py에 show_performance_dashboard() 함수 추가')
    print('3. 사이드바나 탭에서 호출')
    print('')
    print('자세한 코드는 다음 파일을 참고하세요:')
    print('- dashboard_cards.py (standalone)')
    print('- integrated_dashboard.py (import용)')