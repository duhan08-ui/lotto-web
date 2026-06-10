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
        """로그 파일에서 최신 target_round 기준 상위 5세트 반환.
        is_intelligent=True 로그가 있으면 우선 표시 (CompositeScore 기반 AI 추천).
        없으면 일반 로그를 score 내림차순으로 표시.
        """
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

            # is_intelligent=True 로그 우선 추출 (AI 지능형 추천 결과)
            # _cleanup_old_intelligent_logs 덕분에 항상 최신 5개만 존재
            intel_data = [d for d in latest_data if d.get('is_intelligent')]
            if intel_data:
                intel_data.sort(key=lambda x: x.get('candidate_rank', 99))
                seen = set()
                unique_intel = []
                for d in intel_data:
                    key = tuple(sorted(d.get('numbers', [])))
                    if key not in seen:
                        seen.add(key)
                        unique_intel.append(d)
                if len(unique_intel) >= 5:
                    return unique_intel[:5]

            # is_intelligent 로그 부족 시 일반 로그 score 내림차순
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

    # FIX1: is_intelligent=True 로그(AI 지능형 추천 결과)가 있으면 top5.json보다 우선
    # gha_daily: 2-b에서 top5.json(오늘날짜) 생성 후 3에서 ai_intelligent 실행
    # top5.json이 오늘 날짜여도 is_intelligent 결과가 있으면 그걸 표시
    has_intelligent = (
        any(d.get('is_intelligent') for d in prediction_sets) or
        any(d.get('is_intelligent') for d in probability_sets)
    )
    if has_intelligent:
        # is_intelligent 결과로 prediction/probability를 덮음 → top5.json 무시
        has_top5_json = False
        top5_target_round = None
        top5_pattern = []
        top5_probability = []
        top5_manual = []
    else:
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

        # AI 지능형 분석 결과(is_intelligent) 유무를 화면에 명시
        # → "일반 추천 로그 폴백" 상태인지 사용자가 즉시 알 수 있음
        if has_intelligent:
            st.markdown(
                '<div class="ai-section-caption">🧠 AI 지능형 분석(CompositeScore) 결과 표시 중</div>',
                unsafe_allow_html=True)
        elif not has_top5_json:
            st.warning(
                '⚠️ 이 회차의 AI 지능형 분석(is_intelligent) 결과가 아직 없어 '
                '일반 추천 로그를 표시하고 있습니다. '
                'GitHub Actions → "로또 자동 스케줄러" 실행 로그에서 '
                '"AI 지능형 추천 분석" 단계가 성공했는지 확인하세요.')

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

def render_top5_history_section(project_dir: Path, excel_path: Path) -> None:
    """
    회차별 TOP5 결과 뷰어.
    - top5_log.jsonl 에서 회차별 예측 번호 로드
    - lotto.xlsx 에서 실제 당첨번호 로드
    - 신규 회차 확정 시 1등~낙점까지 결과 자동 표시
    """
    import pandas as pd
    from zoneinfo import ZoneInfo as _ZI
    from datetime import datetime as _dt

    KST = _ZI('Asia/Seoul')

    st.markdown("---")
    st.markdown("### 🏆 회차별 TOP5 예측 결과")
    st.caption("매일 오전 9시 저장된 TOP5 예측번호를 회차 추첨 후 1등~낙점까지 자동 비교합니다.")

    # ── top5_log.jsonl 로드 ──────────────────────────────────────────
    records = load_top5_log(project_dir)
    if not records:
        st.info("아직 TOP5 로그가 없습니다. 오전 9시 GHA 실행 후 데이터가 쌓입니다.")
        return

    # ── 실제 당첨번호 맵 로드 (회차 → {numbers, bonus}) ────────────────
    actual_map: dict[int, dict] = {}
    try:
        df_excel = pd.read_excel(excel_path)
        for _, row in df_excel.iterrows():
            try:
                rnd = int(row['회차'])
                nums = [int(row[f'번호{i}']) for i in range(1, 7)]
                bonus = int(row['보너스']) if '보너스' in row and pd.notna(row['보너스']) else None
                actual_map[rnd] = {'numbers': nums, 'bonus': bonus}
            except Exception:
                continue
    except Exception as e:
        st.warning(f"당첨번호 로드 실패: {e}")

    # ── 회차 목록 추출 (target_round 기준) ─────────────────────────────
    rounds = sorted(set(r.get('target_round', 0) for r in records if r.get('target_round')), reverse=True)
    if not rounds:
        st.info("회차 정보가 없습니다.")
        return

    # ── 회차 선택 ──────────────────────────────────────────────────────
    round_options = []
    for rnd in rounds:
        has_result = rnd in actual_map
        label = f"{rnd}회차 {'✅ 결과확정' if has_result else '⏳ 추첨대기'}"
        round_options.append((label, rnd))

    selected_label = st.selectbox(
        "조회할 회차 선택",
        options=[o[0] for o in round_options],
        key="top5_history_round_select"
    )
    selected_round = next(o[1] for o in round_options if o[0] == selected_label)

    # ── 선택 회차의 TOP5 로그 필터 ───────────────────────────────────
    round_records = [r for r in records if r.get('target_round') == selected_round]

    if not round_records:
        st.info(f"{selected_round}회차 TOP5 로그가 없습니다.")
        return

    # 날짜별로 그룹화 (같은 회차를 여러 날 예측할 수 있음)
    dates = sorted(set(r.get('created_date_kst', '')[:10] for r in round_records if r.get('created_date_kst')), reverse=True)
    selected_date = st.selectbox(
        "예측 날짜 선택",
        options=dates,
        key="top5_history_date_select"
    )

    day_records = [r for r in round_records if r.get('created_date_kst', '')[:10] == selected_date]

    # ── 실제 당첨번호 표시 ────────────────────────────────────────────
    actual_info = actual_map.get(selected_round)
    if actual_info:
        actual_nums = actual_info['numbers']
        bonus = actual_info.get('bonus')
        balls_html = ''.join(
            f'<div class="ball" style="background-color:{get_ball_color(n)}; width:36px; height:36px; border-radius:50%; display:inline-flex; align-items:center; justify-content:center; font-weight:900; color:#fff; margin:2px;">{n:02d}</div>'
            for n in sorted(actual_nums)
        )
        bonus_html = (
            f'<div class="ball" style="background-color:#888; width:32px; height:32px; border-radius:50%; display:inline-flex; align-items:center; justify-content:center; font-weight:700; color:#fff; margin:2px; border:2px dashed #ffd700;">{bonus:02d}</div>'
            if bonus else ''
        )
        st.markdown(
            f'<div style="background:rgba(255,215,0,0.12); border:1px solid #ffd700; border-radius:10px; padding:12px 16px; margin-bottom:12px;">'
            f'<span style="color:#ffd700; font-weight:900;">🎯 {selected_round}회차 실제 당첨번호</span>&nbsp;&nbsp;'
            f'{balls_html}'
            + (f'&nbsp;<span style="color:#aaa; font-size:0.85em;">보너스</span> {bonus_html}' if bonus_html else '')
            + '</div>',
            unsafe_allow_html=True
        )
    else:
        st.info(f"⏳ {selected_round}회차는 아직 추첨 전입니다. 추첨 후 결과가 자동으로 표시됩니다.")

    # ── TOP5 예측 결과 카드 ────────────────────────────────────────────
    def prize_label(hit: int, bonus_match: bool) -> str:
        if hit >= 6: return "🥇 1등"
        if hit == 5 and bonus_match: return "🥈 2등"
        if hit == 5: return "🥉 3등"
        if hit == 4: return "4등"
        if hit == 3: return "5등"
        return "낙점"

    prize_color = {"🥇 1등": "#ffd700", "🥈 2등": "#c0c0c0", "🥉 3등": "#cd7f32",
                   "4등": "#38bdf8", "5등": "#86efac", "낙점": "#6b7280"}

    for log_type_label, type_key, badge_class in [
        ("🔵 패턴 추천 (Prediction)", "prediction", "pattern"),
        ("🟣 확률 추천 (Probability)", "probability", "probability"),
    ]:
        type_records = sorted(
            [r for r in day_records if r.get('top5_type') == type_key],
            key=lambda x: x.get('candidate_rank', 99)
        )
        if not type_records:
            continue

        st.markdown(f"**{log_type_label}**")
        for rec in type_records[:5]:
            nums = rec.get('numbers', [])
            rank = rec.get('candidate_rank', '?')
            score = rec.get('score', 0)

            if actual_info:
                actual_nums = actual_info['numbers']
                bonus = actual_info.get('bonus')
                matched = sorted(set(nums) & set(actual_nums))
                bonus_match = bool(bonus and bonus in nums)
                hit = len(matched)
                label = prize_label(hit, bonus_match)
                result_color = prize_color.get(label, "#6b7280")
                result_html = (
                    f'<span style="color:{result_color}; font-weight:900; font-size:1.05em;">{label}</span>'
                    f'&nbsp;<span style="color:#aaa; font-size:0.85em;">({hit}개 일치'
                    + (f', 보너스 일치' if bonus_match and hit < 6 else '')
                    + ')</span>'
                )
                matched_html = ''.join(
                    f'<div class="ball" style="background-color:{get_ball_color(n)}; width:30px; height:30px; border-radius:50%; display:inline-flex; align-items:center; justify-content:center; font-weight:900; color:#fff; margin:2px; outline: 3px solid #ffd700;">{n:02d}</div>'
                    if n in matched else
                    f'<div style="width:30px; height:30px; border-radius:50%; display:inline-flex; align-items:center; justify-content:center; font-weight:700; color:#aaa; margin:2px; background:rgba(255,255,255,0.08);">{n:02d}</div>'
                    for n in sorted(nums)
                )
            else:
                result_html = '<span style="color:#aaa;">추첨 대기</span>'
                matched_html = ''.join(
                    f'<div class="ball" style="background-color:{get_ball_color(n)}; width:30px; height:30px; border-radius:50%; display:inline-flex; align-items:center; justify-content:center; font-weight:900; color:#fff; margin:2px;">{n:02d}</div>'
                    for n in sorted(nums)
                )

            st.markdown(
                f'<div style="background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.12); border-radius:8px; padding:10px 14px; margin-bottom:6px; display:flex; align-items:center; gap:12px; flex-wrap:wrap;">'
                f'<span style="color:#94a3b8; min-width:48px; font-weight:700;">{rank}순위</span>'
                f'<div style="display:inline-flex; flex-wrap:wrap;">{matched_html}</div>'
                f'<span style="color:#64748b; font-size:0.82em;">점수 {score:.4f}</span>'
                f'&nbsp;&nbsp;{result_html}'
                f'</div>',
                unsafe_allow_html=True
            )

