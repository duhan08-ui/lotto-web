import os
import json
import streamlit as st
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

KST = ZoneInfo('Asia/Seoul')


def get_ball_color(n):
    if n <= 10: return '#B8860B'
    elif n <= 20: return '#1565C0'
    elif n <= 30: return '#C62828'
    elif n <= 40: return '#546E7A'
    else: return '#2E7D32'

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
    # Supabase에서 최신 로그 동기화 (최소 간격 안에서는 재동기화를 건너뜀)
    # =========================================================================
    try:
        from log_utils import bootstrap_remote_runtime_if_needed, invalidate_remote_bootstrap_if_stale
        invalidate_remote_bootstrap_if_stale(project_dir)
        bootstrap_remote_runtime_if_needed(project_dir)
    except Exception:
        pass

    # CSS 스타일 (STUDIO 1b · 다크+골드)
    st.markdown('''
        <style>
        .sreco-eyebrow { font:500 10.5px/1 'Pretendard',sans-serif; color:#2D4A6B; letter-spacing:2px; text-transform:uppercase; margin-bottom:11px; }
        .sreco-title { font:600 21px/1.2 'Pretendard',sans-serif; color:#201E1A !important; letter-spacing:-.2px; margin:0 0 4px; }
        .sreco-cap { font:400 12.5px/1.4 'Pretendard',sans-serif; color:#9A9489 !important; margin:0 0 18px; }
        .sreco-card { position:relative; border:1px solid rgba(28,25,20,.10); border-radius:16px;
            background:#FFFEFB; padding:24px 26px 10px; margin-bottom:8px; box-shadow:0 1px 2px rgba(28,25,20,.04),0 12px 34px -18px rgba(28,25,20,.16); }
        .sreco-card::before { content:''; position:absolute; left:0; right:0; top:0; height:3px;
            background:#2D4A6B; border-radius:16px 16px 0 0; }
        .srrow { display:flex; align-items:center; gap:20px; padding:18px 0; border-bottom:1px solid rgba(28,25,20,.06); }
        .srrow:last-child { border-bottom:0; }
        .srrow.top { background:linear-gradient(90deg,rgba(45,74,107,.06),transparent 72%); border-radius:12px; padding:18px 12px; }
        .srk { font:400 22px/1 'Pretendard',sans-serif; color:#9A9489; width:32px; flex:none; text-align:center; }
        .srk.gold { color:#2D4A6B; }
        .sballs { display:flex; gap:9px; flex-wrap:wrap; }
        .sball { display:inline-flex; align-items:center; justify-content:center; width:40px; height:40px;
            border-radius:50%; font:500 14px/1 'Pretendard',sans-serif; color:#201E1A;
            background:#F4F1EA; border:1px solid rgba(28,25,20,.14); flex:none; }
        .srrow.top .sball { border-color:rgba(45,74,107,.30); background:rgba(45,74,107,.06); }
        .smeta { margin-left:auto; text-align:right; flex:none; }
        .smeta .sc { font:500 15px/1 'Pretendard',sans-serif; color:#201E1A; }
        .smeta .sc.gold { color:#2D4A6B; }
        .smeta .mx { font:400 9.5px/1.3 'Pretendard',sans-serif; color:#9A9489; letter-spacing:1px; text-transform:uppercase; margin-top:6px; }
        </style>
    ''', unsafe_allow_html=True)

    today = datetime.now(KST).strftime('%Y-%m-%d')

    prediction_path = project_dir / 'logs' / 'prediction_log.jsonl'
    probability_path = project_dir / 'logs' / 'probability_log.jsonl'
    manual_path = project_dir / 'logs' / 'manual_score_log.jsonl'

    def _read_jsonl(path):
        rows = []
        if not path.exists():
            return rows
        try:
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    nums = d.get('numbers')
                    if nums and len(nums) == 6:
                        rows.append(d)
        except Exception:
            pass
        return rows

    def _norm(d):
        return {
            'numbers': sorted(int(n) for n in d.get('numbers', [])),
            'score': d.get('score', d.get('best_score', d.get('composite_score'))),
            'target_round': d.get('target_round') or (d.get('source_round', 0) + 1 if d.get('source_round') else None),
        }

    # =====================================================================
    # 단일 TOP5 선정 (우선순위)
    #   1) is_intelligent CompositeScore TOP5 (엔진이 뽑은 순위권 세트)
    #   2) round_XXXX_top5.json 의 pattern_top5 (오늘자)
    #   3) prediction_log 최신 회차 score 내림차순
    #   4) prediction_log 가장 최근 기록
    # =====================================================================
    best5 = []

    # 1) is_intelligent 우선 — 세 로그 어디에 있든 번호 기준 중복 제거 후 사용
    all_rows = _read_jsonl(prediction_path) + _read_jsonl(probability_path) + _read_jsonl(manual_path)
    if all_rows:
        latest_tr = max((r.get('target_round') or r.get('source_round', 0) for r in all_rows), default=0)
        intel = [r for r in all_rows
                 if r.get('is_intelligent')
                 and (r.get('target_round') or r.get('source_round', 0)) == latest_tr]
        if intel:
            intel.sort(key=lambda x: x.get('candidate_rank', 99))
            seen, uniq = set(), []
            for r in intel:
                key = tuple(sorted(r.get('numbers', [])))
                if key not in seen:
                    seen.add(key)
                    uniq.append(_norm(r))
            if uniq:
                best5 = uniq[:5]

    # 2) top5.json (오늘자) pattern_top5
    if not best5:
        tj_round, tj_pattern, _tj_prob, _tj_manual = _load_latest_top5_json(project_dir)
        if tj_pattern:
            best5 = [{'numbers': sorted(it.get('numbers', [])),
                      'score': it.get('score'),
                      'target_round': tj_round} for it in tj_pattern[:5]]

    # 3) prediction_log 최신 회차 score 내림차순
    if not best5:
        pred = _read_jsonl(prediction_path)
        if pred:
            latest_tr = max((r.get('target_round') or r.get('source_round', 0) for r in pred), default=0)
            cand = [r for r in pred if (r.get('target_round') or r.get('source_round', 0)) == latest_tr]
            seen, uniq = set(), []
            for r in sorted(cand, key=lambda x: x.get('score', 0), reverse=True):
                key = tuple(sorted(r.get('numbers', [])))
                if key not in seen:
                    seen.add(key)
                    uniq.append(_norm(r))
            if uniq:
                best5 = uniq[:5]

    # 4) prediction_log 가장 최근 기록
    if not best5:
        pred = _read_jsonl(prediction_path)
        if pred:
            seen, uniq = set(), []
            for r in reversed(pred):
                key = tuple(sorted(r.get('numbers', [])))
                if key not in seen:
                    seen.add(key)
                    uniq.append(_norm(r))
                if len(uniq) >= 5:
                    break
            if uniq:
                best5 = uniq

    # ── 표시 회차 결정 ───────────────────────────────────────────────────
    display_round = None
    for it in best5:
        if it.get('target_round'):
            display_round = it['target_round']
            break
    if not display_round:
        try:
            from log_utils import get_round_context
            ctx = get_round_context(project_dir / 'lotto.xlsx')
            display_round = ctx.get('target_round')
        except Exception:
            pass

    # ── 렌더 ─────────────────────────────────────────────────────────────
    st.markdown('---')
    if not best5:
        st.markdown('### AI 지능형 추천 번호')
        st.info('아직 생성된 데이터가 없습니다. 매일 오전 9시에 자동으로 생성됩니다.')
        return False

    rd = f'{display_round} 회차' if display_round else '다음 회차'
    rows_html = ''
    for i, item in enumerate(best5[:5], 1):
        nums = sorted(item.get('numbers', []))
        score = item.get('score')
        top = ' top' if i == 1 else ''
        gold = ' gold' if i == 1 else ''
        balls = ''.join(f'<span class="sball" style="color:{get_ball_color(n)};">{n:02d}</span>' for n in nums)
        sc = ''
        if isinstance(score, (int, float)) and score:
            sc = (f'<div class="smeta"><div class="sc{gold}">{score:.4f}</div>'
                  f'<div class="mx">CompositeScore</div></div>')
        rows_html += (f'<div class="srrow{top}"><span class="srk{gold}">{i:02d}</span>'
                      f'<div class="sballs">{balls}</div>{sc}</div>')
    st.markdown(
        f'<div class="sreco-card">'
        f'<div class="sreco-eyebrow">AI RECOMMENDATION · {rd}</div>'
        f'<div class="sreco-title">추천 번호 TOP 5</div>'
        f'<div class="sreco-cap">CompositeScore 상위 5세트 · {today} 업데이트</div>'
        f'{rows_html}</div>',
        unsafe_allow_html=True)
    return True


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
    from log_utils import load_top5_log

    KST = _ZI('Asia/Seoul')

    st.markdown("---")
    st.markdown("### 회차별 TOP5 예측 결과")
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
            f'<div class="ball" style="background-color:#F4F1EA; border:1px solid rgba(28,25,20,0.14); width:36px; height:36px; border-radius:50%; display:inline-flex; align-items:center; justify-content:center; font-weight:800; color:{get_ball_color(n)}; margin:2px;">{n:02d}</div>'
            for n in sorted(actual_nums)
        )
        bonus_html = (
            f'<div class="ball" style="background-color:#F2EFE8; width:32px; height:32px; border-radius:50%; display:inline-flex; align-items:center; justify-content:center; font-weight:700; color:#5A6169; margin:2px; border:2px dashed rgba(28,25,20,0.3);">{bonus:02d}</div>'
            if bonus else ''
        )
        st.markdown(
            f'<div style="background:rgba(255,215,0,0.12); border:1px solid #ffd700; border-radius:10px; padding:12px 16px; margin-bottom:12px;">'
            f'<span style="color:#ffd700; font-weight:900;">{selected_round}회차 실제 당첨번호</span>&nbsp;&nbsp;'
            f'{balls_html}'
            + (f'&nbsp;<span style="color:#aaa; font-size:0.85em;">보너스</span> {bonus_html}' if bonus_html else '')
            + '</div>',
            unsafe_allow_html=True
        )
    else:
        st.info(f"⏳ {selected_round}회차는 아직 추첨 전입니다. 추첨 후 결과가 자동으로 표시됩니다.")

    # ── TOP5 예측 결과 카드 ────────────────────────────────────────────
    def prize_label(hit: int, bonus_match: bool) -> str:
        if hit >= 6: return "1등"
        if hit == 5 and bonus_match: return "2등"
        if hit == 5: return "3등"
        if hit == 4: return "4등"
        if hit == 3: return "5등"
        return "낙점"

    prize_color = {"1등": "#ffd700", "2등": "#c0c0c0", "3등": "#cd7f32",
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
                    f'<div class="ball" style="background-color:#F4F1EA; border:1px solid rgba(28,25,20,0.14); width:30px; height:30px; border-radius:50%; display:inline-flex; align-items:center; justify-content:center; font-weight:800; color:{get_ball_color(n)}; margin:2px; outline: 2px solid #2D4A6B;">{n:02d}</div>'
                    if n in matched else
                    f'<div style="width:30px; height:30px; border-radius:50%; display:inline-flex; align-items:center; justify-content:center; font-weight:700; color:#aaa; margin:2px; background:rgba(255,255,255,0.08);">{n:02d}</div>'
                    for n in sorted(nums)
                )
            else:
                result_html = '<span style="color:#aaa;">추첨 대기</span>'
                matched_html = ''.join(
                    f'<div class="ball" style="background-color:#F4F1EA; border:1px solid rgba(28,25,20,0.14); width:30px; height:30px; border-radius:50%; display:inline-flex; align-items:center; justify-content:center; font-weight:800; color:{get_ball_color(n)}; margin:2px;">{n:02d}</div>'
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

