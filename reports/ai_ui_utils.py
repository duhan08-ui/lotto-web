import os
import json
import streamlit as st
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

KST = ZoneInfo('Asia/Seoul')

def get_ball_color(n):
    if n <= 10: return '#f2b705'
    elif n <= 20: return '#007bff'
    elif n <= 30: return '#dc3545'
    elif n <= 40: return '#6c757d'
    else: return '#28a745'

def _load_latest_top5_json(project_dir: Path):
    """
    reports/round_XXXX_top5.json 파일 중 가장 최신 회차를 로드합니다.
    [FIX] created_date_kst가 오늘 날짜가 아니면 만료로 간주 → None 반환
    → 앱은 오늘 로그 기반 TOP5로 폴백하여 항상 최신 데이터 표시
    """
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo as _ZI
    today_kst = _dt.now(_ZI('Asia/Seoul')).strftime('%Y-%m-%d')

    reports_dir = project_dir / 'reports'
    import glob, re
    pattern = str(reports_dir / 'round_*_top5.json')
    files = glob.glob(pattern)
    if not files:
        return None, None, None, None

    def extract_round(fp):
        m = re.search(r'round_(\d+)_top5\.json', fp)
        return int(m.group(1)) if m else 0

    latest_file = max(files, key=extract_round)
    try:
        with open(latest_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # 만료 감지: created_date_kst 가 없거나 오늘이 아니면 폴백
        created_date = data.get('created_date_kst', '')
        if not created_date or created_date != today_kst:
            return None, None, None, None  # 오래된 top5.json → 로그 기반으로 폴백
        target_round = data.get('target_round')
        pattern_top5 = data.get('pattern_top5', [])
        probability_top5 = data.get('probability_top5', [])
        manual_top5 = data.get('manual_top5', [])
        return target_round, pattern_top5, probability_top5, manual_top5
    except Exception:
        return None, None, None, None


def render_ai_recommendation_section(project_dir: Path):
    # =========================================================================
    # Supabase에서 최신 로그 동기화 (매 호출 시 캐시 무효화 → 항상 최신 반영)
    # =========================================================================
    try:
        from log_utils import bootstrap_remote_runtime_if_needed, _RUNTIME_REMOTE_BOOTSTRAP_DONE
        log_dir = project_dir / 'logs'
        _RUNTIME_REMOTE_BOOTSTRAP_DONE.discard(str(log_dir.resolve()))
        bootstrap_remote_runtime_if_needed(project_dir)
    except Exception:
        pass

    # =========================================================================
    # 첫 번째 시도: 지능형 분석 보고서 (intelligent_analysis_report.md)
    # =========================================================================

    
    # CSS 스타일 정의 (공통)
    st.markdown('''
        <style>
        .ai-section-title {
            font-size: 1.3rem;
            font-weight: 900;
            margin-bottom: 4px;
            color: #ffffff !important;
        }
        .ai-section-caption {
            font-size: 0.85rem;
            color: #8edff8 !important;
            margin-bottom: 16px;
        }
        .ai-card {
            background: linear-gradient(135deg, rgba(255,255,255,0.05), rgba(255,255,255,0.02));
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 16px;
            padding: 16px;
            margin-bottom: 14px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.2);
        }
        .ai-card.pattern {
            border-color: rgba(56, 189, 248, 0.3);
            background: linear-gradient(135deg, rgba(56,189,248,0.08), rgba(255,255,255,0.02));
        }
        .ai-card.probability {
            border-color: rgba(167,139,250,0.3);
            background: linear-gradient(135deg, rgba(167,139,250,0.08), rgba(255,255,255,0.02));
        }
        .ai-card.manual {
            border-color: rgba(52,211,153,0.3);
            background: linear-gradient(135deg, rgba(52,211,153,0.08), rgba(255,255,255,0.02));
        }
        .ball-container {
            display: flex;
            gap: 8px;
            margin: 10px 0;
            align-items: center;
            flex-wrap: wrap;
        }
        .ball {
            width: 36px;
            height: 36px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: 900;
            font-size: 14px;
            box-shadow: 1px 2px 6px rgba(0,0,0,0.4);
            border: 1px solid rgba(255,255,255,0.2);
        }
        .rank-badge {
            display: inline-block;
            padding: 3px 12px;
            border-radius: 999px;
            font-size: 11px;
            font-weight: 900;
            letter-spacing: 0.05em;
        }
        .rank-badge.pattern {
            background: rgba(56, 189, 248, 0.25);
            color: #38bdf8;
            border: 1px solid rgba(56, 189, 248, 0.4);
        }
        .rank-badge.probability {
            background: rgba(167, 139, 250, 0.25);
            color: #c4b5fd;
            border: 1px solid rgba(167, 139, 250, 0.4);
        }
        .rank-badge.manual {
            background: rgba(52, 211, 153, 0.25);
            color: #6ee7b7;
            border: 1px solid rgba(52, 211, 153, 0.4);
        }
        .score-text {
            color: #b6c5dd;
            font-size: 12px;
            margin-top: 6px;
        }
        .info-badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 10px;
            font-weight: 700;
            margin-left: 8px;
            vertical-align: middle;
        }
        .info-badge.pattern { background: rgba(56, 189, 248, 0.3); color: #38bdf8; }
        .info-badge.probability { background: rgba(167, 139, 250, 0.3); color: #c4b5fd; }
        .info-badge.manual { background: rgba(52, 211, 153, 0.3); color: #6ee7b7; }
        </style>
    ''', unsafe_allow_html=True)

    # 오늘 날짜 (KST)
    today = datetime.now(KST).strftime('%Y-%m-%d')
    

    
    # =========================================================================
    # 방법 2: prediction_log.jsonl과 probability_log.jsonl에서 오늘 데이터 1~5순위 추출
    # =========================================================================
    prediction_path = project_dir / 'logs' / 'prediction_log.jsonl'
    probability_path = project_dir / 'logs' / 'probability_log.jsonl'
    manual_path = project_dir / 'logs' / 'manual_score_log.jsonl'
    
    # 로그에서 데이터 추출
    prediction_sets = []
    probability_sets = []
    manual_sets = []

    def _read_latest_round_sets(path, score_key='score'):
        """로그 파일에서 최신 target_round 기준 상위 5세트 반환 (날짜 무관)"""
        if not path.exists():
            return []
        try:
            with open(path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            all_data = []
            for line in lines:
                try:
                    data = json.loads(line.strip())
                    if data.get('numbers') and len(data.get('numbers', [])) == 6:
                        all_data.append(data)
                except:
                    continue
            if not all_data:
                return []
            # 최신 target_round 기준 필터 (날짜 무관)
            latest_tr = max(
                (d.get('target_round') or d.get('source_round', 0) for d in all_data),
                default=0
            )
            if latest_tr:
                latest_data = [d for d in all_data
                               if (d.get('target_round') or d.get('source_round', 0)) == latest_tr]
            else:
                latest_data = all_data
            # 중복 제거 후 점수순 정렬
            seen = set()
            unique_data = []
            for d in latest_data:
                key = tuple(sorted(d.get('numbers', [])))
                if key not in seen:
                    seen.add(key)
                    unique_data.append(d)
            unique_data.sort(key=lambda x: x.get(score_key, x.get('score', 0)), reverse=True)
            return unique_data[:5]
        except Exception:
            return []

    # prediction_log.jsonl에서 최신 target_round 기준 1~5순위 추출 (날짜 무관)
    try:
        prediction_sets = _read_latest_round_sets(prediction_path, score_key='score')
    except Exception as e:
        st.error(f'prediction 로그 읽기 오류: {e}')

    # probability_log.jsonl에서 최신 target_round 기준 1~5순위 추출 (날짜 무관)
    try:
        probability_sets = _read_latest_round_sets(probability_path, score_key='score')
    except Exception as e:
        st.error(f'probability 로그 읽기 오류: {e}')

    # manual_score_log.jsonl에서 최신 target_round 기준 1~5순위 추출 (날짜 무관)
    try:
        manual_sets = _read_latest_round_sets(manual_path, score_key='best_score')
    except Exception as e:
        st.error(f'manual 로그 읽기 오류: {e}')
    
    # =========================================================================
    # 표시 결정: top5.json > 리포트 > 로그 순 (우선순위)
    # =========================================================================

    # 가장 높은 우선순위: round_XXXX_top5.json (다음 회차 예측)
    top5_target_round, top5_pattern, top5_probability, top5_manual = _load_latest_top5_json(project_dir)
    has_top5_json = bool(top5_pattern or top5_probability)

    has_prediction = len(prediction_sets) > 0
    has_probability = len(probability_sets) > 0
    has_manual = len(manual_sets) > 0

    if has_top5_json or has_prediction or has_probability or has_manual:
        st.markdown('---')

        # 표시할 대상 회차 결정
        # 우선순위: top5.json > lotto.xlsx > 로그 source_round+1
        display_round = top5_target_round if has_top5_json else None
        if not display_round:
            try:
                from log_utils import get_round_context
                ctx = get_round_context(project_dir / 'lotto.xlsx')
                display_round = ctx.get('target_round')
            except Exception:
                pass
        if not display_round:
            all_logs = prediction_sets + probability_sets + manual_sets
            if all_logs:
                max_tr = max(
                    (d.get('target_round') or d.get('source_round', 0) for d in all_logs),
                    default=0
                )
                if max_tr:
                    display_round = max_tr

        round_label = f'<span style="color:#ffd700; font-weight:900;">🎯 {display_round}회차</span> ' if display_round else ''
        st.markdown(f'<div class="ai-section-title">🚀 AI 지능형 추천 번호 &nbsp; {round_label}</div>', unsafe_allow_html=True)
        st.markdown('<div class="ai-section-caption">📅 업데이트: {} | ✨ 패턴 + 확률 분석 | 🎯 다음 회차 당첨 예측</div>'.format(today), unsafe_allow_html=True)

        # has_top5_json일 때 top5_manual도 체크
        has_top5_manual = bool(top5_manual) if has_top5_json else False

        # ── 우선순위 1: round_XXXX_top5.json 기반 ─────────────────────────
        if has_top5_json:
            if top5_pattern:
                st.markdown('**🔵 패턴 추천 (Prediction)**')
                for item in top5_pattern[:5]:
                    rank_label = f'{item.get("rank", "?")}순위'
                    nums = item.get('numbers', [])
                    score = item.get('score', 0)
                    balls_html = ''.join(
                        f'<div class="ball" style="background-color:{get_ball_color(n)};">{n:02d}</div>'
                        for n in sorted(nums)
                    )
                    card_html = (
                        f'<div class="ai-card pattern">'
                        f'<span class="rank-badge pattern">🔵 {rank_label}</span>'
                        f'<span class="info-badge pattern">🎯 {top5_target_round}회차</span>'
                        f'<div class="ball-container">{balls_html}</div>'
                        + (f'<div class="score-text">점수: {score:.4f}</div>' if score else '')
                        + '</div>'
                    )
                    st.markdown(card_html, unsafe_allow_html=True)

            if top5_probability:
                st.markdown('**🟣 확률 추천 (Probability)**')
                for item in top5_probability[:5]:
                    rank_label = f'{item.get("rank", "?")}순위'
                    nums = item.get('numbers', [])
                    score = item.get('score', 0)
                    balls_html = ''.join(
                        f'<div class="ball" style="background-color:{get_ball_color(n)};">{n:02d}</div>'
                        for n in sorted(nums)
                    )
                    card_html = (
                        f'<div class="ai-card probability">'
                        f'<span class="rank-badge probability">🟣 {rank_label}</span>'
                        f'<span class="info-badge probability">🎯 {top5_target_round}회차</span>'
                        f'<div class="ball-container">{balls_html}</div>'
                        + (f'<div class="score-text">점수: {score:.4f}</div>' if score else '')
                        + '</div>'
                    )
                    st.markdown(card_html, unsafe_allow_html=True)

            # top5.json의 manual_top5 우선, 없으면 로그 기반
            manual_source = top5_manual if has_top5_manual else (manual_sets if has_manual else [])
            if manual_source:
                st.markdown('**🟢 수동/AI 추천 (Manual)**')
                for i, data in enumerate(manual_source[:5], 1):
                    nums = data.get('numbers', [])
                    score = data.get('score', data.get('best_score', 0))
                    balls_html = ''.join(
                        f'<div class="ball" style="background-color:{get_ball_color(n)};">{n:02d}</div>'
                        for n in sorted(nums)
                    )
                    card_html = (
                        f'<div class="ai-card manual">'
                        f'<span class="rank-badge manual">🟢 {i}순위</span>'
                        f'<span class="info-badge manual">🎯 {display_round}회차</span>'
                        f'<div class="ball-container">{balls_html}</div>'
                        + (f'<div class="score-text">점수: {score:.2f}</div>' if score else '')
                        + '</div>'
                    )
                    st.markdown(card_html, unsafe_allow_html=True)
        else:
            # ── 우선순위 2: 로그 기반 ─────────────────────────────────────
            if has_prediction:
                st.markdown('**🔵 패턴 추천 (Prediction)**')
                for i, data in enumerate(prediction_sets[:5], 1):
                    tr = display_round or data.get('target_round') or (data.get('source_round', 0) + 1) or '?'
                    nums = data.get('numbers', [])
                    score = data.get('score', 0)
                    balls_html = ''.join(
                        f'<div class="ball" style="background-color:{get_ball_color(n)};">{n:02d}</div>'
                        for n in sorted(nums)
                    )
                    card_html = (
                        f'<div class="ai-card pattern">'
                        f'<span class="rank-badge pattern">🔵 {i}순위</span>'
                        f'<span class="info-badge pattern">🎯 {tr}회차</span>'
                        f'<div class="ball-container">{balls_html}</div>'
                        + (f'<div class="score-text">점수: {score:.2f}</div>' if score else '')
                        + '</div>'
                    )
                    st.markdown(card_html, unsafe_allow_html=True)

            if has_probability:
                st.markdown('**🟣 확률 추천 (Probability)**')
                for i, data in enumerate(probability_sets[:5], 1):
                    tr = display_round or data.get('target_round') or (data.get('source_round', 0) + 1) or '?'
                    nums = data.get('numbers', [])
                    score = data.get('score', 0)
                    balls_html = ''.join(
                        f'<div class="ball" style="background-color:{get_ball_color(n)};">{n:02d}</div>'
                        for n in sorted(nums)
                    )
                    card_html = (
                        f'<div class="ai-card probability">'
                        f'<span class="rank-badge probability">🟣 {i}순위</span>'
                        f'<span class="info-badge probability">🎯 {tr}회차</span>'
                        f'<div class="ball-container">{balls_html}</div>'
                        + (f'<div class="score-text">점수: {score:.2f}</div>' if score else '')
                        + '</div>'
                    )
                    st.markdown(card_html, unsafe_allow_html=True)

            if has_manual:
                st.markdown('**🟢 수동/AI 추천 (Manual)**')
                for i, data in enumerate(manual_sets[:5], 1):
                    tr = display_round or data.get('target_round') or (data.get('source_round', 0) + 1) or '?'
                    nums = data.get('numbers', [])
                    score = data.get('score', 0)
                    balls_html = ''.join(
                        f'<div class="ball" style="background-color:{get_ball_color(n)};">{n:02d}</div>'
                        for n in sorted(nums)
                    )
                    card_html = (
                        f'<div class="ai-card manual">'
                        f'<span class="rank-badge manual">🟢 {i}순위</span>'
                        f'<span class="info-badge manual">🎯 {tr}회차</span>'
                        f'<div class="ball-container">{balls_html}</div>'
                        + (f'<div class="score-text">점수: {score:.2f}</div>' if score else '')
                        + '</div>'
                    )
                    st.markdown(card_html, unsafe_allow_html=True)

        return True
    else:
        # =========================================================================
        # 날짜 없이 가장 최근 데이터 표시
        # =========================================================================
        recent_prediction = []
        recent_probability = []
        recent_manual = []
        
        # 가장 최근 prediction 데이터
        if prediction_path.exists():
            try:
                with open(prediction_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                
                seen = set()
                for line in reversed(lines):
                    try:
                        data = json.loads(line.strip())
                        key = tuple(sorted(data.get('numbers', [])))
                        if key not in seen:
                            seen.add(key)
                            recent_prediction.append(data)
                            if len(recent_prediction) >= 5:
                                break
                    except:
                        continue
            except:
                pass
        
        # 가장 최근 probability 데이터
        if probability_path.exists():
            try:
                with open(probability_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                
                seen = set()
                for line in reversed(lines):
                    try:
                        data = json.loads(line.strip())
                        key = tuple(sorted(data.get('numbers', [])))
                        if key not in seen:
                            seen.add(key)
                            recent_probability.append(data)
                            if len(recent_probability) >= 5:
                                break
                    except:
                        continue
            except:
                pass
        
        # 가장 최근 manual 데이터
        if manual_path.exists():
            try:
                with open(manual_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                
                seen = set()
                for line in reversed(lines):
                    try:
                        data = json.loads(line.strip())
                        key = tuple(sorted(data.get('numbers', [])))
                        if key not in seen:
                            seen.add(key)
                            recent_manual.append(data)
                            if len(recent_manual) >= 5:
                                break
                    except:
                        continue
            except:
                pass
        
        has_recent = len(recent_prediction) > 0 or len(recent_probability) > 0 or len(recent_manual) > 0
        
        if has_recent:
            st.markdown('---')
            # fallback: lotto.xlsx 기준 회차 우선, 없으면 로그 max 기준
            all_recent = recent_prediction + recent_probability + recent_manual
            fb_target_round = None
            try:
                from log_utils import get_round_context
                ctx = get_round_context(project_dir / 'lotto.xlsx')
                fb_target_round = ctx.get('target_round')
            except Exception:
                pass
            if not fb_target_round:
                max_sr_recent = max((d.get('target_round') or d.get('source_round', 0) for d in all_recent), default=0)
                fb_target_round = max_sr_recent if max_sr_recent else '?'
            fb_round_label = f'<span style="color:#ffd700; font-weight:900;">🎯 {fb_target_round}회차</span>' if fb_target_round != '?' else ''
            st.markdown(f'<div class="ai-section-title">🚀 AI 지능형 추천 번호 &nbsp; {fb_round_label}</div>', unsafe_allow_html=True)
            st.markdown('<div class="ai-section-caption">📅 최근 생성 데이터 | 🎯 다음 회차 당첨 예측</div>', unsafe_allow_html=True)

            if recent_prediction:
                st.markdown('**🔵 패턴 추천**')
                for i, data in enumerate(recent_prediction[:5], 1):
                    nums = data.get('numbers', [])
                    score = data.get('score', 0)
                    balls_html = ''.join(
                        f'<div class="ball" style="background-color:{get_ball_color(n)};">{n:02d}</div>'
                        for n in sorted(nums)
                    )
                    card_html = (
                        f'<div class="ai-card pattern">'
                        f'<span class="rank-badge pattern">🔵 {i}순위</span>'
                        f'<span class="info-badge pattern">🎯 {fb_target_round}회차</span>'
                        f'<div class="ball-container">{balls_html}</div>'
                        + (f'<div class="score-text">점수: {score:.2f}</div>' if score else '')
                        + '</div>'
                    )
                    st.markdown(card_html, unsafe_allow_html=True)

            if recent_probability:
                st.markdown('**🟣 확률 추천**')
                for i, data in enumerate(recent_probability[:5], 1):
                    nums = data.get('numbers', [])
                    score = data.get('score', 0)
                    balls_html = ''.join(
                        f'<div class="ball" style="background-color:{get_ball_color(n)};">{n:02d}</div>'
                        for n in sorted(nums)
                    )
                    card_html = (
                        f'<div class="ai-card probability">'
                        f'<span class="rank-badge probability">🟣 {i}순위</span>'
                        f'<span class="info-badge probability">🎯 {fb_target_round}회차</span>'
                        f'<div class="ball-container">{balls_html}</div>'
                        + (f'<div class="score-text">점수: {score:.2f}</div>' if score else '')
                        + '</div>'
                    )
                    st.markdown(card_html, unsafe_allow_html=True)

            if recent_manual:
                st.markdown('**🟢 수동/AI 추천**')
                for i, data in enumerate(recent_manual[:5], 1):
                    nums = data.get('numbers', [])
                    score = data.get('score', 0)
                    balls_html = ''.join(
                        f'<div class="ball" style="background-color:{get_ball_color(n)};">{n:02d}</div>'
                        for n in sorted(nums)
                    )
                    card_html = (
                        f'<div class="ai-card manual">'
                        f'<span class="rank-badge manual">🟢 {i}순위</span>'
                        f'<span class="info-badge manual">🎯 {fb_target_round}회차</span>'
                        f'<div class="ball-container">{balls_html}</div>'
                        + (f'<div class="score-text">점수: {score:.2f}</div>' if score else '')
                        + '</div>'
                    )
                    st.markdown(card_html, unsafe_allow_html=True)

            return True
        else:
            st.markdown('---')
            st.markdown('### 🚀 AI 지능형 추천 번호')
            st.info('🤖 아직 생성된 데이터가 없습니다. 매일 오전 9시에 자동으로 생성됩니다.')
            return False

