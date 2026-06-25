# -*- coding: utf-8 -*-
import json
import streamlit as st
from pathlib import Path
from datetime import datetime

def get_performance_data(project_dir):
    project_dir = Path(project_dir)
    reports_dir = project_dir / 'reports'
    
    data = {
        'metrics': None,
        'results': [],
        'trend': []
    }
    
    # performance_analysis.json 로드
    json_path = reports_dir / 'performance_analysis.json'
    if json_path.exists():
        with open(json_path, 'r', encoding='utf-8') as f:
            loaded = json.load(f)
            if 'metrics' not in loaded:
                data = {'metrics': loaded, 'results': [], 'trend': []}
            else:
                data = loaded
                # 'detailed_results' → 'results' 키 통일
                if 'results' not in data or not data['results']:
                    data['results'] = data.get('detailed_results', [])
    
    # trend 데이터 - performance_log.jsonl 추가 병합
    # (performance_analysis.json에 trend 키가 있어도 jsonl 데이터를 함께 합산)
    perf_log = project_dir / 'logs' / 'performance_log.jsonl'
    if perf_log.exists():
        if 'trend' not in data:
            data['trend'] = []
        existing_ts = {t.get('timestamp', '') for t in data['trend']}
        with open(perf_log, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    try:
                        entry = json.loads(line)
                        ts = entry.get('timestamp', '__NO_TS__')
                        if ts not in existing_ts:
                            data['trend'].append(entry)
                            existing_ts.add(ts)
                    except:
                        pass
    
    return data

def get_winner_data(project_dir):
    project_dir = Path(project_dir)
    reports_dir = project_dir / 'reports'
    
    data = {
        'latest': None,
        'history': []
    }
    
    # auto_weekly_result.json 로드
    json_path = reports_dir / 'auto_weekly_result.json'
    if json_path.exists():
        with open(json_path, 'r', encoding='utf-8') as f:
            data['latest'] = json.load(f)
    
    # weekly_winner_log.jsonl 로드
    winner_log = project_dir / 'logs' / 'weekly_winner_log.jsonl'
    if winner_log.exists():
        with open(winner_log, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    try:
                        data['history'].append(json.loads(line))
                    except:
                        pass
    
    return data


def get_ai_recommendation_hit_data(project_dir):
    """
    AI 지능형 추천 번호(prediction_log, probability_log, manual_score_log)에서
    실제 당첨 번호와 대조하여 당첨된 기록을 추출합니다.
    기존 수식/계산 코드 일절 건드리지 않고, 로그 데이터만 읽어 매칭합니다.
    """
    project_dir = Path(project_dir)
    logs_dir = project_dir / 'logs'
    
    # 실제 당첨 번호 데이터 로드
    # [BUG FIX] lotto.xlsx에서 직접 읽어 항상 최신 데이터 사용
    # (weekly_winner_log.jsonl, auto_weekly_result.json은 없을 수 있음)
    actual_results = {}  # {round_num: {'numbers': [...], 'bonus': N}}

    # 1순위: lotto.xlsx 직접 읽기 (가장 신뢰도 높음)
    excel_path = project_dir / 'lotto.xlsx'
    if excel_path.exists():
        try:
            import pandas as pd
            df = pd.read_excel(excel_path)
            num_cols = [c for c in df.columns if str(c).startswith('번호')]
            num_cols = sorted(num_cols, key=lambda x: int(''.join(ch for ch in str(x) if ch.isdigit()) or 999))[:6]
            for _, row in df.iterrows():
                try:
                    rnd = int(row['회차'])
                    nums = sorted([int(row[c]) for c in num_cols])
                    bonus = int(row['보너스']) if '보너스' in df.columns else None
                    actual_results[rnd] = {'numbers': nums, 'bonus': bonus}
                except:
                    pass
        except Exception as e:
            pass

    # 2순위: weekly_winner_log.jsonl 보완
    winner_log = logs_dir / 'weekly_winner_log.jsonl'
    if winner_log.exists():
        with open(winner_log, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    d = json.loads(line)
                    rnd = d.get('lotto_round', 0)
                    if rnd and d.get('winning_numbers') and int(rnd) not in actual_results:
                        actual_results[int(rnd)] = {
                            'numbers': d['winning_numbers'],
                            'bonus': d.get('bonus_number', None)
                        }
                except:
                    pass

    if not actual_results:
        return []
    
    # AI 추천 로그 파일들
    log_files = {
        '패턴추천': logs_dir / 'prediction_log.jsonl',
        '확률추천': logs_dir / 'probability_log.jsonl',
        '수동추천': logs_dir / 'manual_score_log.jsonl',
    }
    
    hits = []
    pred_by_round = {}   # {target_round: 해당 회차 총 예측 조합 수} - 자동+수동 전부 포함

    for log_type_label, log_path in log_files.items():
        if not log_path.exists():
            continue

        with open(log_path, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                    target_round = entry.get('target_round', entry.get('source_round', 0))
                    if not target_round:
                        continue
                    target_round = int(target_round)

                    pred_nums = entry.get('numbers', [])
                    if not pred_nums or len(pred_nums) != 6:
                        continue

                    # 회차별 예측 조합 수 누적 (당첨번호 유무와 무관하게 카운트)
                    # 미래 회차(아직 추첨 안 된 회차) 예측도 포함
                    pred_by_round[target_round] = pred_by_round.get(target_round, 0) + 1

                    # 당첨 비교는 실제 당첨번호가 있는 회차만
                    actual = actual_results.get(target_round)
                    if not actual:
                        continue

                    actual_nums = actual['numbers']
                    bonus = actual.get('bonus')
                    matched = sorted(set(pred_nums) & set(actual_nums))
                    hit_count = len(matched)

                    if hit_count < 3:
                        continue

                    # 등수 판정
                    bonus_match = bonus is not None and int(bonus) in pred_nums
                    if hit_count == 6:
                        prize = '1등'
                        prize_order = 1
                    elif hit_count == 5 and bonus_match:
                        prize = '2등'
                        prize_order = 2
                    elif hit_count == 5:
                        prize = '3등'
                        prize_order = 3
                    elif hit_count == 4:
                        prize = '4등'
                        prize_order = 4
                    elif hit_count == 3:
                        prize = '5등'
                        prize_order = 5
                    else:
                        continue

                    hits.append({
                        'log_type': log_type_label,
                        'target_round': target_round,
                        'pred_numbers': sorted(pred_nums),
                        'actual_numbers': actual_nums,
                        'bonus_number': bonus,
                        'matched_numbers': matched,
                        'hit_count': hit_count,
                        'bonus_match': bonus_match,
                        'prize': prize,
                        'prize_order': prize_order,
                        'candidate_rank': entry.get('candidate_rank', entry.get('rank', '-')),
                        'score': entry.get('score', entry.get('score_metric', '-')),
                        'timestamp': entry.get('timestamp', ''),
                        'run_id': entry.get('run_id', ''),
                    })
                except:
                    pass

    # 등수 높은 순, 회차 최신 순으로 정렬
    hits.sort(key=lambda x: (x['prize_order'], -x['target_round']))
    # (hits, pred_by_round) 튜플로 반환
    # pred_by_round = {회차번호: 해당 회차 총 예측 조합 수(자동+수동 합산)}
    return hits, pred_by_round


def render_performance_dashboard(project_dir):
    perf_data = get_performance_data(project_dir)
    winner_data = get_winner_data(project_dir)
    
    metrics = perf_data.get('metrics', {})
    total = metrics.get('total', {})
    recent = metrics.get('recent', {})
    
    # ========================================
    # 스타일 CSS
    # ========================================
    st.markdown('''
    <style>
        /* 카드 기본 스타일 */
        .card {
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            border-radius: 16px;
            padding: 20px;
            margin: 10px 0;
            box-shadow: 0 4px 15px rgba(0,0,0,0.3);
        }
        
        .card-header {
            font-size: 14px;
            color: #aaa;
            margin-bottom: 8px;
        }
        
        .card-title {
            font-size: 18px;
            font-weight: bold;
            color: white;
            margin-bottom: 10px;
        }
        
        .card-value {
            font-size: 36px;
            font-weight: bold;
            color: #4ecdc4;
        }
        
        .card-value-small {
            font-size: 24px;
            font-weight: bold;
        }
        
        .card-sub {
            font-size: 12px;
            color: #888;
            margin-top: 5px;
        }
        
        /* 1등 카드 */
        .card-1st {
            border-left: 4px solid #ff6b6b;
        }
        .card-1st .card-value { color: #ff6b6b; }

        /* 2등 카드 */
        .card-2nd {
            border-left: 4px solid #ffa94d;
        }
        .card-2nd .card-value { color: #ffa94d; }

        /* 3등 카드 */
        .card-3rd {
            border-left: 4px solid #ffd43b;
        }
        .card-3rd .card-value { color: #ffd43b; }
        
        /* 4등 카드 */
        .card-4th {
            border-left: 4px solid #ffeaa7;
        }
        .card-4th .card-value { color: #ffeaa7; }
        
        /* 5등 카드 */
        .card-5th {
            border-left: 4px solid #a8e6cf;
        }
        .card-5th .card-value { color: #a8e6cf; }
        
        /* Top5 카드 */
        .card-top5 {
            border-left: 4px solid #74b9ff;
        }
        .card-top5 .card-value { color: #74b9ff; }
        
        /* 진행률 바 */
        .progress-container {
            background: rgba(255,255,255,0.1);
            border-radius: 10px;
            height: 25px;
            width: 100%;
            margin: 10px 0;
            overflow: hidden;
        }
        
        .progress-bar {
            height: 100%;
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 12px;
            font-weight: bold;
            color: white;
            transition: width 0.5s ease;
        }
        
        .progress-red { background: linear-gradient(90deg, #c0392b, #ff6b6b); }
        .progress-orange { background: linear-gradient(90deg, #d35400, #ffa94d); }
        .progress-yellow { background: linear-gradient(90deg, #b7950b, #ffd43b); }
        .progress-gold { background: linear-gradient(90deg, #f39c12, #ffeaa7); }
        .progress-green { background: linear-gradient(90deg, #27ae60, #a8e6cf); }
        .progress-blue { background: linear-gradient(90deg, #2980b9, #74b9ff); }
        .progress-purple { background: linear-gradient(90deg, #8e44ad, #a29bfe); }
        
        /* 추이 그래프 */
        .trend-bar {
            display: inline-block;
            width: 8px;
            margin: 0 2px;
            border-radius: 2px;
        }
        
        /* 숫자 볼 */
        .lotto-ball {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 36px;
            height: 36px;
            border-radius: 50%;
            font-weight: bold;
            font-size: 14px;
            margin: 2px;
        }
        
        .ball-odd { background: linear-gradient(135deg, #e94560, #ff6b6b); }
        .ball-even { background: linear-gradient(135deg, #4ecdc4, #45b7d1); }
        .ball-matched { background: linear-gradient(135deg, #f39c12, #ffeaa7); color: #1a1a2e !important; }
        
        /* 표 스타일 */
        .data-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }
        
        .data-table th {
            background: rgba(255,255,255,0.1);
            padding: 10px 8px;
            text-align: center;
            color: #aaa;
            font-weight: normal;
        }
        
        .data-table td {
            padding: 8px;
            text-align: center;
            border-bottom: 1px solid rgba(255,255,255,0.05);
            color: white;
        }
        
        .data-table tr:hover {
            background: rgba(255,255,255,0.05);
        }
        
        .hit-icon {
            font-size: 16px;
        }
        
        .hit-1st { color: #ff6b6b; font-weight: bold; }
        .hit-2nd { color: #ffa94d; font-weight: bold; }
        .hit-3rd { color: #ffd43b; font-weight: bold; }
        .hit-4th { color: #ffeaa7; }
        .hit-5th { color: #a8e6cf; }
        .hit-top5 { color: #74b9ff; }
        
        /* 섹션 헤더 */
        .section-header {
            font-size: 20px;
            font-weight: bold;
            color: white;
            margin: 20px 0 15px 0;
            padding-bottom: 10px;
            border-bottom: 2px solid rgba(255,255,255,0.1);
        }
        
        /* AI 당첨 카드 */
        .ai-hit-card {
            background: linear-gradient(135deg, rgba(255,107,107,0.15), rgba(26,26,46,0.95));
            border: 1px solid rgba(255,107,107,0.4);
            border-radius: 16px;
            padding: 18px 20px;
            margin: 10px 0;
        }
        .ai-hit-card.prize-2 {
            background: linear-gradient(135deg, rgba(255,169,77,0.15), rgba(26,26,46,0.95));
            border-color: rgba(255,169,77,0.4);
        }
        .ai-hit-card.prize-3 {
            background: linear-gradient(135deg, rgba(255,212,59,0.12), rgba(26,26,46,0.95));
            border-color: rgba(255,212,59,0.4);
        }
        .ai-hit-card.prize-4 {
            background: linear-gradient(135deg, rgba(255,234,167,0.1), rgba(26,26,46,0.95));
            border-color: rgba(255,234,167,0.3);
        }
        .ai-hit-card.prize-5 {
            background: linear-gradient(135deg, rgba(168,230,207,0.1), rgba(26,26,46,0.95));
            border-color: rgba(168,230,207,0.3);
        }
        .ai-hit-prize-badge {
            display: inline-block;
            padding: 4px 14px;
            border-radius: 999px;
            font-size: 13px;
            font-weight: 900;
            margin-bottom: 8px;
        }
        .ai-hit-balls {
            display: flex;
            flex-wrap: wrap;
            gap: 5px;
            margin: 8px 0;
            align-items: center;
        }
        .ai-hit-ball {
            width: 32px;
            height: 32px;
            border-radius: 50%;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            font-weight: 900;
            font-size: 12px;
            color: white;
        }
        .ai-hit-meta {
            font-size: 12px;
            color: #8edff8;
            margin-top: 6px;
        }
        
        /* 스탯 그리드 */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 15px;
            margin: 15px 0;
        }
        
        .stat-box {
            background: rgba(255,255,255,0.05);
            border-radius: 12px;
            padding: 15px;
            text-align: center;
        }
        
        .stat-value {
            font-size: 28px;
            font-weight: bold;
            color: #4ecdc4;
        }
        
        .stat-label {
            font-size: 12px;
            color: #888;
            margin-top: 5px;
        }
    </style>
    ''', unsafe_allow_html=True)
    
    # ========================================
    # 대시보드 헤더
    # ========================================
    st.markdown('<p class=\"section-header\">🏆 AI 추천 번호 적중률 현황</p>', unsafe_allow_html=True)
    
    # ========================================
    # 1. 메인 카드 — 1등/2등/3등/4등/5등/Top5
    # ========================================
    # [수정] 모든 수치를 ai_hits(target_round 기반 정확 매칭) 기준으로 집계
    # performance_analysis.json 은 target_round 무시 크로스집계 버그가 있었으므로
    # 수치 표시에 사용하지 않음. 성능 추이 그래프도 ai_hits 기반으로 회차별 집계.

    # ai_hits 미리 생성 (섹션5와 공유)
    # pred_by_round = {회차번호: 해당 회차 총 예측 조합 수(자동생성+수동추천 합산)}
    ai_hits, pred_by_round = get_ai_recommendation_hit_data(project_dir)

    # ── 회차 수 계산 ─────────────────────────────────────────────
    results = perf_data.get('results', [])
    total_rounds = len(results) if results else 0
    pred_total = len(pred_by_round) if pred_by_round else 1  # 예측 실행된 회차 수

    # ── ai_hits 기반 누적 건수 집계 ─────────────────────────────
    total_1st  = sum(1 for h in ai_hits if h['prize_order'] == 1)
    total_2nd  = sum(1 for h in ai_hits if h['prize_order'] == 2)
    total_3rd  = sum(1 for h in ai_hits if h['prize_order'] == 3)
    total_4th  = sum(1 for h in ai_hits if h['prize_order'] == 4)
    total_5th  = sum(1 for h in ai_hits if h['prize_order'] == 5)
    total_top5 = sum(1 for h in ai_hits if h['prize_order'] <= 4)

    # ── 적중률: 회차별 (당첨 조합 수 / 해당 회차 예측 조합 수) 평균 ──
    # 매일 쌓이는 예측 수에 왜곡되지 않고, 회차마다 공정하게 비교
    # 자동생성(패턴+확률) + 수동추천 전부 포함한 회차별 예측 수로 나눔
    from collections import defaultdict as _dd2
    hits_by_round = {
        1: _dd2(int), 2: _dd2(int), 3: _dd2(int),
        4: _dd2(int), 5: _dd2(int)
    }
    for h in ai_hits:
        hits_by_round[h['prize_order']][h['target_round']] += 1

    def _avg_rate(prize_order):
        rates = []
        for rnd, n_pred in pred_by_round.items():
            n_hit = hits_by_round[prize_order].get(rnd, 0)
            if n_pred > 0:
                rates.append(n_hit / n_pred * 100)
        return round(sum(rates) / len(rates), 2) if rates else 0.0

    rate_1st  = _avg_rate(1)
    rate_2nd  = _avg_rate(2)
    rate_3rd  = _avg_rate(3)
    rate_4th  = _avg_rate(4)
    rate_5th  = _avg_rate(5)
    # top5(4등 이상): 회차별 (4등+3등+2등+1등 조합 수) / 해당 회차 예측 수 평균
    def _avg_rate_top5():
        rates = []
        top5_by_round = _dd2(int)
        for h in ai_hits:
            if h['prize_order'] <= 4:
                top5_by_round[h['target_round']] += 1
        for rnd, n_pred in pred_by_round.items():
            n_hit = top5_by_round.get(rnd, 0)
            if n_pred > 0:
                rates.append(n_hit / n_pred * 100)
        return round(sum(rates) / len(rates), 2) if rates else 0.0
    rate_top5 = _avg_rate_top5()

    # 전체 예측 조합 수 합계 (카드 표시용)
    total_pred_count = sum(pred_by_round.values())
    
    st.markdown(f'**🥇 1·2·3등 달성 현황** <span style="font-size:12px; color:#888;">전체 {total_pred_count}조합 / {pred_total}회차 예측 기준</span>', unsafe_allow_html=True)
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown(f'''
        <div class=\"card card-1st\">
            <div class=\"card-header\">📊 누적 성능</div>
            <div class=\"card-title\">🥇 1등 달성률</div>
            <div class=\"card-value\">{rate_1st}%</div>
            <div class=\"progress-container\">
                <div class=\"progress-bar progress-red\" style=\"width: {min(rate_1st, 100)}%;\">{rate_1st}%</div>
            </div>
            <div class=\"card-sub\">예측 {total_pred_count}조합 중 {total_1st}조합 적중</div>
        </div>
        ''', unsafe_allow_html=True)
    
    with col2:
        st.markdown(f'''
        <div class=\"card card-2nd\">
            <div class=\"card-header\">📊 누적 성능</div>
            <div class=\"card-title\">🥈 2등 달성률</div>
            <div class=\"card-value\">{rate_2nd}%</div>
            <div class=\"progress-container\">
                <div class=\"progress-bar progress-orange\" style=\"width: {min(rate_2nd, 100)}%;\">{rate_2nd}%</div>
            </div>
            <div class=\"card-sub\">예측 {total_pred_count}조합 중 {total_2nd}조합 적중</div>
        </div>
        ''', unsafe_allow_html=True)
    
    with col3:
        st.markdown(f'''
        <div class=\"card card-3rd\">
            <div class=\"card-header\">📊 누적 성능</div>
            <div class=\"card-title\">🥉 3등 달성률</div>
            <div class=\"card-value\">{rate_3rd}%</div>
            <div class=\"progress-container\">
                <div class=\"progress-bar progress-yellow\" style=\"width: {min(rate_3rd, 100)}%;\">{rate_3rd}%</div>
            </div>
            <div class=\"card-sub\">예측 {total_pred_count}조합 중 {total_3rd}조합 적중</div>
        </div>
        ''', unsafe_allow_html=True)
    
    st.markdown(f'**🎯 4·5등 달성 현황** <span style="font-size:12px; color:#888;">전체 {total_pred_count}조합 / {pred_total}회차 예측 기준</span>', unsafe_allow_html=True)
    col1, col2, col3 = st.columns(3)
    
    with col1:
        
        st.markdown(f'''
        <div class=\"card card-4th\">
            <div class=\"card-header\">📊 누적 성능</div>
            <div class=\"card-title\">🎯 4등 달성률</div>
            <div class=\"card-value\">{rate_4th}%</div>
            <div class=\"progress-container\">
                <div class=\"progress-bar progress-gold\" style=\"width: {min(rate_4th, 100)}%;\">{rate_4th}%</div>
            </div>
            <div class=\"card-sub\">예측 {total_pred_count}조합 중 {total_4th}조합 적중</div>
        </div>
        ''', unsafe_allow_html=True)
    
    with col2:
        
        st.markdown(f'''
        <div class=\"card card-5th\">
            <div class=\"card-header\">📊 누적 성능</div>
            <div class=\"card-title\">✨ 5등 달성률</div>
            <div class=\"card-value\" style=\"color: #a8e6cf;\">{rate_5th}%</div>
            <div class=\"progress-container\">
                <div class=\"progress-bar progress-green\" style=\"width: {min(rate_5th, 100)}%;\">{rate_5th}%</div>
            </div>
            <div class=\"card-sub\">예측 {total_pred_count}조합 중 {total_5th}조합 적중</div>
        </div>
        ''', unsafe_allow_html=True)
    
    with col3:
        
        st.markdown(f'''
        <div class=\"card card-top5\">
            <div class=\"card-header\">📊 누적 성능</div>
            <div class=\"card-title\">⭐ Top5 추천 적중률</div>
            <div class=\"card-value\" style=\"color: #74b9ff;\">{rate_top5}%</div>
            <div class=\"progress-container\">
                <div class=\"progress-bar progress-blue\" style=\"width: {min(rate_top5, 100)}%;\">{rate_top5}%</div>
            </div>
            <div class=\"card-sub\">예측 {total_pred_count}조합 중 {total_top5}조합 4등 이상 적중</div>
        </div>
        ''', unsafe_allow_html=True)
    
    st.markdown('---')
    
    # ========================================
    # 3. 최근 당첨 결과
    # ========================================
    winner = winner_data.get('latest')
    if winner:
        win_nums = winner.get('winning_numbers', [])
        lotto_round = winner.get('lotto_round', 0)
        
        st.markdown('<p class=\"section-header\">🎰 이번 회차 당첨 결과</p>', unsafe_allow_html=True)
        
        balls_html = ''
        for n in win_nums:
            ball_class = 'ball-odd' if n % 2 == 1 else 'ball-even'
            balls_html += f'<span class=\"lotto-ball {ball_class}\">{n:02d}</span>'
        
        best = winner.get('best_match', {})
        best_count = best.get('count', 0)
        
        st.markdown(f'''
        <div class=\"card\">
            <div style=\"display: flex; justify-content: space-between; align-items: center;\">
                <div>
                    <div class=\"card-header\">현재 {lotto_round}회차</div>
                    <div class=\"card-title\">당첨 번호</div>
                    <div style=\"margin-top: 15px;\">{balls_html}</div>
                </div>
                <div style=\"text-align: center;\">
                    <div class=\"card-header\">최고 매칭</div>
                    <div class=\"card-value\" style=\"font-size: 48px;\">{best_count}개</div>
                    <div class=\"card-sub\">일치</div>
                </div>
            </div>
        </div>
        ''', unsafe_allow_html=True)
    
    st.markdown('---')
    
    # ========================================
    # 5. 🆕 AI 지능형 추천 번호 당첨 현황
    #    (prediction_log / probability_log / manual_score_log 기반)
    # ========================================
    st.markdown(f'<p class=\"section-header\">🤖 AI 지능형 추천 번호 당첨 현황 <span style=\"font-size:14px; color:#888;\">전체 {total_pred_count}조합 / {pred_total}회차 예측 기준</span></p>', unsafe_allow_html=True)
    st.caption('AI 지능형 추천 번호(패턴·확률·수동 추천)에서 실제 당첨이 발생한 경우를 별도로 표시합니다.')
    
    # ai_hits 는 섹션1에서 이미 생성됨 (get_ai_recommendation_hit_data)

    # ── AI 지능형 추천 번호 당첨 현황 요약 카드
    # 1,2,3등 달성 현황의 "총 N건" 수치와 동일하게 고정
    prize_counts = {
        '1등': total_1st,
        '2등': total_2nd,
        '3등': total_3rd,
        '4등': total_4th,
        '5등': total_5th,
    }

    if True:  # 항상 실행

        prize_colors = {
            '1등': ('#ff6b6b', '🥇'),
            '2등': ('#ffa94d', '🥈'),
            '3등': ('#ffd43b', '🥉'),
            '4등': ('#ffeaa7', '🎯'),
            '5등': ('#a8e6cf', '✨'),
        }
        
        # 요약 카드
        summary_cols = st.columns(5)
        for i, (prize_name, (color, icon)) in enumerate(prize_colors.items()):
            cnt = prize_counts.get(prize_name, 0)
            with summary_cols[i]:
                st.markdown(f'''
                <div class=\"card\" style=\"text-align: center; border-left: 4px solid {color};\">
                    <div style=\"font-size: 22px;\">{icon}</div>
                    <div style=\"font-size: 13px; color: {color}; font-weight: bold;\">{prize_name}</div>
                    <div style=\"font-size: 28px; font-weight: 900; color: {color};\">{cnt}건</div>
                </div>
                ''', unsafe_allow_html=True)
        
        st.markdown('')
        
        # 상세 카드 목록 (페이지네이션)
        prize_class_map = {1: '', 2: 'prize-2', 3: 'prize-3', 4: 'prize-4', 5: 'prize-5'}
        
        def ball_color(n):
            if n <= 10: return '#f2b705'
            elif n <= 20: return '#007bff'
            elif n <= 30: return '#dc3545'
            elif n <= 40: return '#6c757d'
            else: return '#28a745'
        
        # ── 페이지네이션 설정 ──────────────────────────────────────
        ITEMS_PER_PAGE = 3
        total_items = len(ai_hits)
        total_pages = max(1, (total_items + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
        
        page_key = 'ai_hit_cards_page'
        if page_key not in st.session_state:
            st.session_state[page_key] = 1
        # 범위 보정 (데이터 변경 시 안전 처리)
        st.session_state[page_key] = max(1, min(st.session_state[page_key], total_pages))
        current_page = st.session_state[page_key]
        
        # 현재 페이지에 해당하는 항목만 슬라이싱
        start_idx = (current_page - 1) * ITEMS_PER_PAGE
        end_idx   = start_idx + ITEMS_PER_PAGE
        page_hits = ai_hits[start_idx:end_idx]
        
        # ── 현재 페이지 강조 CSS ──────────────────────────────────
        st.markdown(f'''
        <style>
            /* 현재 페이지 버튼 강조 */
            div[data-testid="stButton"] button[kind="secondary"]:disabled {{
                background: linear-gradient(135deg, #4ecdc4, #45b7d1) !important;
                color: #0e1117 !important;
                font-weight: 900 !important;
                font-size: 15px !important;
                border: none !important;
                box-shadow: 0 0 12px rgba(78,205,196,0.6) !important;
                opacity: 1 !important;
                cursor: default !important;
            }}
        </style>
        ''', unsafe_allow_html=True)
        
        # ── 상단 페이지네이션 컨트롤 ─────────────────────────────
        def render_pagination(suffix):
            col_prev2, col_prev, col_nums, col_next, col_next2 = st.columns([1, 1, 6, 1, 1])
            with col_prev2:
                if st.button('⏮', key=f'ai_page_first_{suffix}', disabled=(current_page == 1), use_container_width=True):
                    st.session_state[page_key] = 1
                    st.rerun()
            with col_prev:
                if st.button('◀', key=f'ai_page_prev_{suffix}', disabled=(current_page == 1), use_container_width=True):
                    st.session_state[page_key] -= 1
                    st.rerun()
            with col_nums:
                # 숫자 버튼: 최대 7개 표시, 현재 페이지 중심으로 슬라이딩
                max_btns = 7
                half = max_btns // 2
                btn_start = max(1, min(current_page - half, total_pages - max_btns + 1))
                btn_end   = min(total_pages, btn_start + max_btns - 1)
                num_btn_cols = st.columns(btn_end - btn_start + 1)
                for idx, pnum in enumerate(range(btn_start, btn_end + 1)):
                    with num_btn_cols[idx]:
                        is_current = (pnum == current_page)
                        if st.button(
                            str(pnum),
                            key=f'ai_page_num_{pnum}_{suffix}',
                            use_container_width=True,
                            disabled=is_current,
                        ):
                            st.session_state[page_key] = pnum
                            st.rerun()
            with col_next:
                if st.button('▶', key=f'ai_page_next_{suffix}', disabled=(current_page == total_pages), use_container_width=True):
                    st.session_state[page_key] += 1
                    st.rerun()
            with col_next2:
                if st.button('⏭', key=f'ai_page_last_{suffix}', disabled=(current_page == total_pages), use_container_width=True):
                    st.session_state[page_key] = total_pages
                    st.rerun()
            st.markdown(
                f'<div style="text-align:center; color: #aaa; font-size: 12px; margin-top: 2px;">'
                f'{current_page} / {total_pages} 페이지 &nbsp;·&nbsp; 전체 {total_items}건'
                f'</div>',
                unsafe_allow_html=True
            )
        
        if total_pages > 1:
            render_pagination('top')
        
        st.markdown('<div style="height: 6px;"></div>', unsafe_allow_html=True)
        
        # ── 카드 렌더링 ───────────────────────────────────────────
        for hit in page_hits:
            prize_name = hit['prize']
            prize_order = hit['prize_order']
            color, icon = prize_colors.get(prize_name, ('#888', '⭐'))
            card_class = prize_class_map.get(prize_order, '')
            
            # 예측 번호 볼 (일치 번호 강조)
            pred_balls = ''
            for n in hit['pred_numbers']:
                if n in hit['matched_numbers']:
                    pred_balls += f'<div class=\"ai-hit-ball\" style=\"background:{ball_color(n)}; box-shadow: 0 0 8px {color}; border: 2px solid {color};\">{n:02d}</div>'
                else:
                    pred_balls += f'<div class=\"ai-hit-ball\" style=\"background:rgba(255,255,255,0.12); color: #ccc;\">{n:02d}</div>'
            
            # 실제 당첨 번호 볼
            actual_balls = ''
            for n in hit['actual_numbers']:
                if n in hit['matched_numbers']:
                    actual_balls += f'<div class=\"ai-hit-ball\" style=\"background:{ball_color(n)}; border: 2px solid {color};\">{n:02d}</div>'
                else:
                    actual_balls += f'<div class=\"ai-hit-ball\" style=\"background:rgba(255,255,255,0.08); color: #999;\">{n:02d}</div>'
            
            bonus_text = ''
            if hit.get('bonus_number') and hit['bonus_match']:
                bonus_text = f' + 보너스 <b>{hit["bonus_number"]:02d}</b> 일치'
            
            ts = hit.get('timestamp', '')[:10] if hit.get('timestamp') else '-'
            run_id = hit.get('run_id', '-')
            crank = hit.get('candidate_rank', '-')
            score = hit.get('score', '-')
            
            st.markdown(f'''
            <div class=\"ai-hit-card {card_class}\">
                <div style=\"display: flex; align-items: center; gap: 10px; margin-bottom: 6px;\">
                    <span class=\"ai-hit-prize-badge\" style=\"background: rgba(255,255,255,0.08); color: {color}; border: 1px solid {color};\">{icon} {prize_name}</span>
                    <span style=\"color: #8edff8; font-size: 13px;\">{hit["target_round"]}회차</span>
                    <span style=\"color: #666; font-size: 12px;\">| {hit["log_type"]}</span>
                </div>
                <div style=\"font-size: 12px; color: #aaa; margin-bottom: 6px;\">예측 번호 (강조 = 일치)</div>
                <div class=\"ai-hit-balls\">{pred_balls}</div>
                <div style=\"font-size: 12px; color: #aaa; margin-bottom: 4px;\">실제 당첨 번호</div>
                <div class=\"ai-hit-balls\">{actual_balls}</div>
                <div class=\"ai-hit-meta\">
                    일치 {hit["hit_count"]}개{bonus_text} &nbsp;|&nbsp;
                    추천 날짜: {ts} &nbsp;|&nbsp;
                    후보 순위: {crank} &nbsp;|&nbsp;
                    점수: {score}
                </div>
            </div>
            ''', unsafe_allow_html=True)
        
        # ── 하단 페이지네이션 컨트롤 ─────────────────────────────
        st.markdown('<div style="height: 10px;"></div>', unsafe_allow_html=True)
        
        if total_pages > 1:
            render_pagination('bottom')
        
        # 전체 표로도 보여주기
        with st.expander('📋 AI 추천 당첨 전체 목록 (표)', expanded=False):
            import pandas as pd
            table_rows = []
            for hit in ai_hits:
                table_rows.append({
                    '회차': hit['target_round'],
                    '추천유형': hit['log_type'],
                    '당첨등수': hit['prize'],
                    '일치개수': hit['hit_count'],
                    '예측번호': ' '.join(f"{n:02d}" for n in hit['pred_numbers']),
                    '일치번호': ' '.join(f"{n:02d}" for n in hit['matched_numbers']),
                    '당첨번호': ' '.join(f"{n:02d}" for n in hit['actual_numbers']),
                    '후보순위': hit['candidate_rank'],
                    '추천날짜': hit.get('timestamp', '')[:10],
                })
            if table_rows:
                df_ai = pd.DataFrame(table_rows)
                st.dataframe(df_ai, use_container_width=True, hide_index=True)
    
    st.markdown('---')
    
    # ========================================
    # 6. 성능 추이 그래프
    # ========================================
    # [수정] ai_hits(target_round 기반 정확 매칭) 에서 회차별 집계
    # performance_analysis.json results 는 크로스집계 버그가 있으므로 사용 안 함

    import pandas as pd
    from collections import defaultdict as _dd

    # ai_hits → 회차별로 집계
    round_hit_map = _dd(lambda: {'match_4': 0, 'match_5': 0, 'match_3': 0, 'total': 0})
    for h in ai_hits:
        rnd = h['target_round']
        round_hit_map[rnd]['total'] += 1
        if h['prize_order'] == 4:
            round_hit_map[rnd]['match_4'] += 1
        elif h['prize_order'] == 5:
            round_hit_map[rnd]['match_3'] += 1
        elif h['prize_order'] == 3:
            round_hit_map[rnd]['match_5'] += 1

    # 예측이 실행된 전체 회차 목록: pred_by_round(자동+수동 전부) 기준
    results_raw = perf_data.get('results', [])
    all_pred_rounds = set(pred_by_round.keys())
    # performance_analysis.json 예측 있는 회차도 보완 (이전 데이터 호환)
    for r in results_raw:
        if r.get('total_predictions', 0) > 0:
            all_pred_rounds.add(r['round'])

    trend_data = []
    for rnd in sorted(all_pred_rounds):
        # 회차별 예측 수: pred_by_round 우선 (자동+수동 전부 포함), 없으면 performance_analysis.json
        n_pred = pred_by_round.get(rnd)
        if not n_pred:
            perf_r = next((r for r in results_raw if r['round'] == rnd), None)
            n_pred = perf_r['total_predictions'] if perf_r else 1
        n_pred = n_pred or 1
        m4 = round_hit_map[rnd]['match_4']
        m3 = round_hit_map[rnd]['match_3']
        trend_data.append({
            'round': rnd,
            'match_4': m4,
            'match_3': m3,
            'total_predictions': n_pred,
            'hit_rate_4th': round(m4 / n_pred * 100, 2),
            'hit_rate_5th': round(m3 / n_pred * 100, 2),
        })

    if len(trend_data) >= 2:
        st.markdown('<p class=\"section-header\">📈 성능 추이</p>', unsafe_allow_html=True)

        # ── 성능 추이 그래프 (접기/펼치기) ───────────────────────
        with st.expander('📊 성능 추이 그래프', expanded=False):
            try:
                import plotly.graph_objects as go
                labels = [f"{t['round']}회" for t in trend_data]
                r4_vals = [t['hit_rate_4th'] for t in trend_data]
                r5_vals = [t['hit_rate_5th'] for t in trend_data]
                fig = go.Figure()
                fig.add_trace(go.Bar(name='4등(%)', x=labels, y=r4_vals, marker_color='#4ecdc4'))
                fig.add_trace(go.Bar(name='5등(%)', x=labels, y=r5_vals, marker_color='#ffd43b'))
                fig.update_layout(
                    barmode='group',
                    height=350,
                    margin=dict(l=20, r=20, t=20, b=60),
                    legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
                    xaxis=dict(tickangle=-45, tickfont=dict(size=10)),
                    yaxis=dict(title='적중률 (%)'),
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font=dict(color='#ccc'),
                )
                st.plotly_chart(fig, use_container_width=True)
            except ImportError:
                # plotly 없으면 최근 20회차만 bar_chart로 표시
                recent_20 = trend_data[-20:]
                chart_data = [{'회차': f"{t['round']}회", '4등(%)': t['hit_rate_4th'], '5등(%)': t['hit_rate_5th']}
                              for t in recent_20]
                df_chart = pd.DataFrame(chart_data)
                st.bar_chart(df_chart.set_index('회차'))

        # ── 회차별 상세 (접기/펼치기) ────────────────────────────
        with st.expander('📋 회차별 상세', expanded=False):
            # 테이블 형태로 표시 (화면 넘침 없음)
            table_rows = []
            for t in reversed(trend_data):
                table_rows.append({
                    '회차': f"{t['round']}회차",
                    '4등 건수': t['match_4'],
                    '4등 적중률': f"{t['hit_rate_4th']}%",
                    '5등 건수': t['match_3'],
                    '5등 적중률': f"{t['hit_rate_5th']}%",
                })
            df_detail = pd.DataFrame(table_rows)
            st.dataframe(df_detail, use_container_width=True, hide_index=True)
    else:
        st.markdown('''
        <div class=\"card\" style=\"text-align: center; padding: 40px;\">
            <div style=\"font-size: 48px; margin-bottom: 15px;\">📊</div>
            <div style=\"color: #888;\">아직 충분한 추이 데이터가 없습니다.</div>
            <div style=\"color: #666; font-size: 12px; margin-top: 10px;\">최소 2회 이상 분석 실행 필요</div>
        </div>
        ''', unsafe_allow_html=True)

def add_to_streamlit_app(project_dir):
    try:
        render_performance_dashboard(project_dir)
    except Exception as e:
        st.error(f'대시보드 렌더링 오류: {str(e)}')

if __name__ == '__main__':
    from pathlib import Path
    import sys
    
    project_dir = Path(__file__).resolve().parent
    
    if len(sys.argv) > 1 and sys.argv[1] == '--streamlit':
        import streamlit as st
        st.set_page_config(page_title='AI 추천 적중률 대시보드', layout='wide')
        render_performance_dashboard(project_dir)
    else:
        print('Streamlit 앱에서 호출해주세요.')
