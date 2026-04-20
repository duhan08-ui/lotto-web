from __future__ import annotations

import calendar
import math
import os
import random
from collections import Counter
from datetime import date, datetime
from itertools import permutations
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from analysis import analyze_logs
from anti_pattern_lotto import generate_single_anti_pattern_ticket
from history_analysis import (
    build_log_type_summary as build_history_log_type_summary,
    build_period_summary as build_history_period_summary,
    enrich_history_dataframe,
)
from log_utils import (
    LOG_FILE_MAP,
    REPORT_FILE_MAP,
    build_log_status_table,
    ensure_runtime_dirs,
    load_app_state,
    load_combined_log_history,
    log_manual_score,
    log_prediction_results,
    save_app_state,
)
from update_lotto import update_excel

# --- 설정 및 상수 ---
TITLE = "Data Algorithm Intelligence"
SUBTITLE = "데이터 알고리즘 인텔리전스: 통계적 패턴과 수치 흐름을 시뮬레이션하는 지능형 분석 플랫폼"
LOCK_LIMIT = 3
DEFAULT_SIMULATION_COUNT = int(os.getenv("LOTTO_SIMULATION_COUNT", "5000"))
SIMULATION_COUNT = DEFAULT_SIMULATION_COUNT
SIMULATION_EDIT_PASSWORD = "1221"
SIMULATION_PANEL_VARIANT = "A"
DATA_CHECK_PASSWORD = os.getenv("LOTTO_DATA_CHECK_PASSWORD", "1221")
UNLOCK_PASSWORD = os.getenv("LOTTO_UNLOCK_PASSWORD", "0518")
KST = ZoneInfo("Asia/Seoul")
LIMIT_TARGETS = ("prediction", "probability")
ARTIFACT_LABEL_MAP = {
    "prediction_actual_match_csv": "예측-실제 적중 매칭",
    "threshold_analysis_csv": "임계값 분석",
    "score_timeseries_csv": "점수 시계열",
    "score_timeseries_png": "점수 추이 차트",
    "gap_factor_timeseries_png": "gap 계수 추이 차트",
    "daily_summary_csv": "일별 통계 요약",
    "weekly_summary_csv": "주별 통계 요약",
    "monthly_summary_csv": "월별 통계 요약",
    "weekday_summary_csv": "요일별 통계 요약",
    "log_type_summary_csv": "로그 유형 통계 요약",
    "summary_txt": "분석 요약 텍스트",
    "summary_json": "분석 요약 JSON",
}


def _today_password() -> str:
    return datetime.now(KST).strftime("%m%d")


def _file_cache_token(path: Path | str) -> tuple[str, int, int]:
    file_path = Path(path)
    if not file_path.exists():
        return (str(file_path), 0, 0)
    stat = file_path.stat()
    return (str(file_path.resolve()), stat.st_mtime_ns, stat.st_size)


@st.cache_resource(show_spinner=False)
def _get_cached_predictor(excel_path_str: str, cache_token: tuple[str, int, int]) -> "LottoPredictor":
    return LottoPredictor(excel_path_str)


@st.cache_data(show_spinner=False)
def _read_excel_cached(excel_path_str: str, cache_token: tuple[str, int, int]) -> pd.DataFrame:
    return pd.read_excel(excel_path_str)



def _sanitize_simulation_count(value: int | str | None) -> int:
    try:
        count = int(value or DEFAULT_SIMULATION_COUNT)
    except (TypeError, ValueError):
        count = DEFAULT_SIMULATION_COUNT
    return max(1000, min(count, 50000))


def _current_simulation_count() -> int:
    return _sanitize_simulation_count(st.session_state.get("simulation_count", DEFAULT_SIMULATION_COUNT))


def _current_source_round(
    excel_path: Path,
    cache_token: tuple[str, int, int],
    predictor: "LottoPredictor" | None = None,
) -> int:
    fallback = int(getattr(predictor, "total_draws", 0) or 0)
    try:
        df = _read_excel_cached(str(excel_path), cache_token)
    except Exception:
        return fallback

    if df.empty:
        return fallback
    if "회차" not in df.columns:
        return fallback or int(len(df))

    rounds = pd.to_numeric(df["회차"], errors="coerce").dropna()
    if rounds.empty:
        return fallback or int(len(df))
    return int(rounds.max())


def _analysis_dependency_signature(project_dir: Path, excel_path: Path, cache_token: tuple[str, int, int]) -> tuple:
    log_dir = project_dir / "logs"
    signatures = [cache_token]
    for file_name in LOG_FILE_MAP.values():
        signatures.append(_file_cache_token(log_dir / file_name))
    return tuple(signatures)


def _get_fresh_analysis_summary(
    project_dir: Path,
    excel_path: Path,
    cache_token: tuple[str, int, int],
    predictor: "LottoPredictor" | None = None,
    *,
    force_refresh: bool = False,
) -> dict:
    summary = st.session_state.get("analysis_summary")
    stored_signature = st.session_state.get("analysis_signature")
    latest_source_round = _current_source_round(excel_path, cache_token, predictor)
    current_signature = _analysis_dependency_signature(project_dir, excel_path, cache_token)

    summary_round = None
    if isinstance(summary, dict):
        try:
            summary_round = int(summary.get("latest_source_round"))
        except (TypeError, ValueError):
            summary_round = None

    needs_refresh = force_refresh or not isinstance(summary, dict) or stored_signature != current_signature or summary_round != latest_source_round
    if needs_refresh:
        summary = analyze_logs(project_dir, excel_path)
        st.session_state.analysis_summary = summary
        st.session_state.analysis_signature = _analysis_dependency_signature(project_dir, excel_path, cache_token)
    return st.session_state.get("analysis_summary") or {}


def _generate_anti_pattern_manual_numbers(previous_numbers: list[int] | None = None) -> list[int]:
    previous_tuple = tuple(sorted(int(n) for n in previous_numbers)) if previous_numbers else None
    rng = random.SystemRandom()
    latest_candidate: list[int] = []
    for _ in range(12):
        seed = rng.randint(1, 10**9)
        latest_candidate = list(generate_single_anti_pattern_ticket(seed=seed))
        if previous_tuple is None or tuple(latest_candidate) != previous_tuple:
            return latest_candidate
    return latest_candidate


def _refresh_source_data(excel_path: Path) -> dict:
    try:
        final_df, mode = update_excel(excel_path)
        latest_round = int(final_df.iloc[0]["회차"]) if not final_df.empty else 0
        st.cache_data.clear()
        st.cache_resource.clear()
        st.session_state.analysis_summary = None
        st.session_state.analysis_signature = None
        if mode == "incremental":
            message = f"원본 데이터를 최신 회차까지 갱신했습니다. 현재 {latest_round}회차 기준입니다."
            level = "success"
        elif mode == "full":
            message = f"원본 데이터를 전체 재수집해 최신 회차까지 갱신했습니다. 현재 {latest_round}회차 기준입니다."
            level = "success"
        else:
            message = f"이미 최신 데이터입니다. 현재 {latest_round}회차 기준입니다."
            level = "info"
    except Exception as exc:
        message = f"원본 데이터 최신화 중 오류가 발생했습니다: {exc}"
        level = "error"

    notice = {"level": level, "message": message}
    st.session_state.source_data_refresh_notice = notice
    return notice


def disable_copy():
    st.markdown(
        """
        <style>
        :root {
            --text-main: #f8fbff;
            --text-sub: #b6c5dd;
            --line-soft: rgba(148, 163, 184, 0.16);
            --line-glow: rgba(250, 204, 21, 0.18);
            --shadow-soft: 0 24px 70px rgba(2, 8, 23, 0.42);
            --panel-top: rgba(255,255,255,0.06);
            --panel-bottom: rgba(255,255,255,0.015);
        }
        html, body, [data-testid="stAppViewContainer"] {
            -webkit-user-select: none;
            -moz-user-select: none;
            -ms-user-select: none;
            user-select: none;
            background:
                radial-gradient(circle at 0% 0%, rgba(56,189,248,0.18), transparent 22%),
                radial-gradient(circle at 100% 0%, rgba(167,139,250,0.16), transparent 24%),
                radial-gradient(circle at 50% 100%, rgba(52,211,153,0.10), transparent 26%),
                linear-gradient(180deg, #030712 0%, #081120 52%, #0b1327 100%);
            color: var(--text-main);
        }
        canvas { pointer-events: none; }
        .block-container {
            padding-top: 1.6rem;
            padding-bottom: 3rem;
            max-width: 1240px;
        }
        h1, h2, h3, h4, p, li, span, label, div {
            color: var(--text-main);
        }
        [data-testid="stHeader"] {
            background: rgba(0,0,0,0);
        }
        [data-testid="stToolbar"] {
            right: 0.75rem;
            display: none !important;
            visibility: hidden !important;
        }
        [data-testid="stToolbarActions"],
        [data-testid="stToolbarActionButton"],
        #MainMenu,
        #GithubIcon,
        [class*="viewerBadge"],
        [data-testid="stStatusWidget"] {
            display: none !important;
            visibility: hidden !important;
        }
        [data-testid="stMetricValue"] { color: #ffffff; }
        [data-testid="stMetricLabel"] { color: var(--text-sub); }
        div[data-baseweb="tab-list"] {
            gap: 10px;
            margin-bottom: 0.6rem;
        }
        button[role="tab"] {
            border-radius: 999px !important;
            padding: 10px 16px !important;
            background: rgba(255,255,255,0.04) !important;
            border: 1px solid rgba(255,255,255,0.08) !important;
            color: #d7e6fb !important;
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.05);
        }
        button[role="tab"][aria-selected="true"] {
            background: linear-gradient(135deg, rgba(56,189,248,0.22), rgba(167,139,250,0.24)) !important;
            border-color: rgba(125,211,252,0.32) !important;
            color: #ffffff !important;
        }
        .stButton > button,
        .stDownloadButton > button,
        .stFormSubmitButton > button {
            border-radius: 16px;
            border: 1px solid rgba(148,163,184,0.18);
            background: linear-gradient(180deg, rgba(19,34,58,0.98), rgba(10,20,36,0.98));
            color: #f8fbff;
            font-weight: 800;
            min-height: 48px;
            box-shadow: 0 14px 30px rgba(2,8,23,0.24);
            transition: all 0.18s ease;
        }
        .stButton > button:hover,
        .stDownloadButton > button:hover,
        .stFormSubmitButton > button:hover {
            border-color: rgba(125,211,252,0.34);
            background: linear-gradient(180deg, rgba(25,45,74,0.98), rgba(11,22,39,0.98));
            transform: translateY(-1px);
        }
        .stButton > button[kind="primary"] {
            border: 1px solid rgba(103,232,249,0.34) !important;
            background: linear-gradient(135deg, rgba(14,165,233,0.96), rgba(59,130,246,0.96) 55%, rgba(124,58,237,0.96)) !important;
            color: #ffffff !important;
            box-shadow: 0 16px 38px rgba(14,165,233,0.24) !important;
        }
        .stButton > button[kind="primary"]:hover {
            border-color: rgba(191,219,254,0.9) !important;
            filter: brightness(1.05);
        }
        .hero-card, .soft-panel, .feature-card, .section-shell, .result-card, .calendar-panel, .unlock-shell, .status-strip, .stage-card-bridge {
            border: 1px solid var(--line-soft);
            border-radius: 24px;
            background:
                linear-gradient(180deg, var(--panel-top), var(--panel-bottom)),
                linear-gradient(180deg, rgba(10,19,35,0.94), rgba(6,12,24,0.96));
            box-shadow: var(--shadow-soft), inset 0 1px 0 rgba(255,255,255,0.05);
            backdrop-filter: blur(18px);
        }
        .hero-card {
            position: relative;
            overflow: hidden;
            padding: 34px 34px 28px 34px;
            margin-bottom: 20px;
            border-color: rgba(148,163,184,0.14);
            background:
                radial-gradient(circle at 8% 0%, rgba(250,204,21,0.10), transparent 24%),
                radial-gradient(circle at 100% 0%, rgba(56,189,248,0.16), transparent 28%),
                linear-gradient(180deg, rgba(255,255,255,0.06), rgba(255,255,255,0.015)),
                linear-gradient(180deg, rgba(9,18,35,0.97), rgba(6,12,24,0.98));
        }
        .hero-card::before {
            content: "";
            position: absolute;
            inset: 0;
            background: linear-gradient(135deg, rgba(56,189,248,0.08), transparent 36%, rgba(168,85,247,0.12));
            pointer-events: none;
        }
        .hero-card::after {
            content: "";
            position: absolute;
            inset: 1px;
            border-radius: 23px;
            border: 1px solid rgba(255,255,255,0.05);
            pointer-events: none;
        }
        .hero-eyebrow {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 7px 12px;
            border-radius: 999px;
            background: rgba(8,145,178,0.12);
            border: 1px solid rgba(125,211,252,0.22);
            color: #c9f2ff;
            font-size: 0.78rem;
            font-weight: 800;
            margin-bottom: 12px;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }
        .hero-title {
            margin: 0;
            font-size: 2.5rem;
            font-weight: 900;
            letter-spacing: -0.05em;
            line-height: 1.06;
            color: #ffffff;
        }
        .hero-subtitle {
            max-width: 900px;
            margin: 14px 0 0 0;
            color: #d2e0f5;
            font-size: 1rem;
            line-height: 1.72;
        }
        .hero-usage-row {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-top: 18px;
        }
        .hero-usage-pill {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 10px 14px;
            border-radius: 999px;
            background: rgba(15,23,42,0.58);
            border: 1px solid rgba(125,211,252,0.20);
            color: #dbeafe !important;
            font-size: 0.84rem;
            font-weight: 700;
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.05);
        }
        .hero-usage-pill b {
            color: #ffffff !important;
        }
        .status-strip {
            display: flex;
            gap: 18px;
            align-items: center;
            padding: 18px 20px;
            margin: 0 0 18px 0;
            border-color: rgba(103,232,249,0.14);
        }
        .status-strip .badge {
            flex: 0 0 auto;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-width: 92px;
            padding: 8px 12px;
            border-radius: 999px;
            font-size: 0.75rem;
            font-weight: 900;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }
        .status-strip .body { flex: 1 1 auto; }
        .status-strip .title {
            color: #ffffff !important;
            font-size: 1.02rem;
            font-weight: 900;
            margin-bottom: 6px;
        }
        .status-strip .desc,
        .status-strip .meta {
            color: #cbd9ef !important;
            font-size: 0.92rem;
            line-height: 1.58;
        }
        .status-strip .meta {
            font-size: 0.83rem;
            color: #8edff8 !important;
            margin-top: 4px;
        }
        .status-strip.unlocked {
            background: linear-gradient(135deg, rgba(16,185,129,0.16), rgba(10,19,35,0.94) 52%, rgba(56,189,248,0.12));
            border-color: rgba(52,211,153,0.24);
        }
        .status-strip.unlocked .badge {
            background: rgba(16,185,129,0.14);
            border: 1px solid rgba(110,231,183,0.24);
            color: #d1fae5 !important;
        }
        .status-strip.limited {
            background: linear-gradient(135deg, rgba(59,130,246,0.16), rgba(10,19,35,0.94) 48%, rgba(124,58,237,0.12));
            border-color: rgba(96,165,250,0.24);
        }
        .status-strip.limited .badge {
            background: rgba(59,130,246,0.14);
            border: 1px solid rgba(147,197,253,0.24);
            color: #dbeafe !important;
        }
        .soft-panel {
            padding: 22px 22px 18px 22px;
            margin-bottom: 14px;
            border-color: rgba(148,163,184,0.14);
            background:
                linear-gradient(180deg, rgba(255,255,255,0.045), rgba(255,255,255,0.012)),
                linear-gradient(180deg, rgba(11,20,38,0.95), rgba(7,14,27,0.97));
        }
        .soft-panel h4 {
            margin: 0 0 8px 0;
            color: #ffffff !important;
            font-size: 1.02rem;
        }
        .soft-panel p {
            margin: 0;
            color: var(--text-sub) !important;
            line-height: 1.65;
            font-size: 0.93rem;
        }
        .guide-list {
            margin: 12px 0 0 0;
            padding-left: 18px;
        }
        .guide-list li {
            margin-bottom: 8px;
            color: #dbe7ff !important;
            line-height: 1.55;
        }
        .guide-studio-shell {
            padding: 26px;
            margin-bottom: 18px;
            border-radius: 28px;
            border: 1px solid rgba(125,211,252,0.14);
            background:
                radial-gradient(circle at 0% 0%, rgba(56,189,248,0.10), transparent 22%),
                radial-gradient(circle at 100% 0%, rgba(168,85,247,0.10), transparent 26%),
                linear-gradient(180deg, rgba(255,255,255,0.045), rgba(255,255,255,0.012)),
                linear-gradient(180deg, rgba(8,18,33,0.97), rgba(5,11,22,0.98));
        }
        .guide-studio-header {
            display: flex;
            flex-wrap: wrap;
            align-items: flex-start;
            justify-content: space-between;
            gap: 14px;
            margin-bottom: 18px;
        }
        .guide-studio-header .eyebrow {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 7px 12px;
            border-radius: 999px;
            background: rgba(14,165,233,0.12);
            border: 1px solid rgba(125,211,252,0.20);
            color: #c9f2ff !important;
            font-size: 0.76rem;
            font-weight: 900;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin-bottom: 10px;
        }
        .guide-studio-header h3 {
            margin: 0;
            color: #ffffff !important;
            font-size: 1.32rem;
            line-height: 1.25;
        }
        .guide-studio-header p {
            margin: 10px 0 0 0;
            max-width: 760px;
            color: #c9d8ef !important;
            line-height: 1.7;
            font-size: 0.95rem;
        }
        .guide-chip-row {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            justify-content: flex-end;
        }
        .guide-chip {
            display: inline-flex;
            align-items: center;
            padding: 9px 12px;
            border-radius: 999px;
            background: rgba(15,23,42,0.62);
            border: 1px solid rgba(148,163,184,0.14);
            color: #d9eaff !important;
            font-size: 0.82rem;
            font-weight: 700;
        }
        .guide-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 14px;
        }
        .guide-card-premium {
            position: relative;
            overflow: hidden;
            min-height: 220px;
            padding: 22px 22px 18px 22px;
            border-radius: 22px;
            border: 1px solid rgba(148,163,184,0.14);
            background:
                linear-gradient(180deg, rgba(255,255,255,0.04), rgba(255,255,255,0.012)),
                linear-gradient(180deg, rgba(11,20,38,0.95), rgba(7,14,27,0.97));
            box-shadow: 0 20px 46px rgba(2,8,23,0.22), inset 0 1px 0 rgba(255,255,255,0.05);
        }
        .guide-card-premium::after {
            content: "";
            position: absolute;
            inset: auto -34px -34px auto;
            width: 110px;
            height: 110px;
            border-radius: 999px;
            opacity: 0.14;
            background: currentColor;
            filter: blur(14px);
        }
        .guide-card-premium .card-label {
            display: inline-flex;
            margin-bottom: 10px;
            color: #8edff8 !important;
            font-size: 0.74rem;
            font-weight: 900;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }
        .guide-card-premium h4 {
            margin: 0 0 8px 0;
            color: #ffffff !important;
            font-size: 1.06rem;
        }
        .guide-card-premium p {
            margin: 0 0 12px 0;
            color: #d1def2 !important;
            line-height: 1.65;
            font-size: 0.91rem;
        }
        .guide-step-list {
            margin: 0;
            padding-left: 18px;
        }
        .guide-step-list li {
            margin-bottom: 8px;
            color: #e6efff !important;
            line-height: 1.55;
        }
        .guide-note {
            margin-top: 12px;
            padding: 10px 12px;
            border-radius: 14px;
            background: rgba(15,23,42,0.55);
            border: 1px solid rgba(125,211,252,0.14);
            color: #d8e7fb !important;
            font-size: 0.84rem;
            line-height: 1.55;
        }
        .guide-card-cyan { color: #bfe9ff; }
        .guide-card-violet { color: #ddd6fe; }
        .guide-card-emerald { color: #bbf7d0; }
        @media (max-width: 1100px) {
            .guide-grid { grid-template-columns: 1fr; }
            .guide-chip-row { justify-content: flex-start; }
        }
        .feature-card {
            position: relative;
            overflow: hidden;
            padding: 22px 22px 18px 22px;
            margin-bottom: 12px;
            min-height: 156px;
            border-color: rgba(148,163,184,0.14);
            box-shadow: 0 22px 48px rgba(2,8,23,0.28), inset 0 1px 0 rgba(255,255,255,0.05);
        }
        .feature-card::after {
            content: "";
            position: absolute;
            inset: auto -40px -40px auto;
            width: 120px;
            height: 120px;
            border-radius: 999px;
            opacity: 0.16;
            background: currentColor;
            filter: blur(12px);
        }
        .feature-card .eyebrow {
            display: inline-flex;
            font-size: 0.73rem;
            font-weight: 900;
            letter-spacing: 0.08em;
            opacity: 0.96;
            margin-bottom: 8px;
            text-transform: uppercase;
        }
        .feature-card .title {
            color: #ffffff !important;
            font-size: 1.08rem;
            font-weight: 900;
            margin-bottom: 6px;
        }
        .feature-card .desc {
            color: rgba(255,255,255,0.92) !important;
            font-size: 0.9rem;
            line-height: 1.6;
        }
        .feature-green {
            color: #bbf7d0;
            background:
                radial-gradient(circle at 0% 0%, rgba(250,204,21,0.10), transparent 24%),
                linear-gradient(135deg, rgba(16,185,129,0.20), rgba(8,18,32,0.98));
            border-color: rgba(52,211,153,0.24);
        }
        .feature-purple {
            color: #ddd6fe;
            background:
                radial-gradient(circle at 100% 0%, rgba(56,189,248,0.10), transparent 28%),
                linear-gradient(135deg, rgba(124,58,237,0.24), rgba(8,18,32,0.98));
            border-color: rgba(167,139,250,0.24);
        }
        .metric-panel {
            padding: 20px 20px 18px 20px;
            border-radius: 20px;
            border: 1px solid rgba(148,163,184,0.14);
            background:
                linear-gradient(180deg, rgba(255,255,255,0.04), rgba(255,255,255,0.01)),
                linear-gradient(180deg, rgba(12,24,43,0.96), rgba(7,15,28,0.95));
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.05), 0 18px 42px rgba(2,8,23,0.22);
            min-height: 128px;
            margin-bottom: 10px;
        }
        .metric-panel .label {
            color: #8edff8 !important;
            font-size: 0.76rem;
            font-weight: 900;
            letter-spacing: 0.08em;
            margin-bottom: 10px;
            text-transform: uppercase;
        }
        .metric-panel .value {
            color: #ffffff !important;
            font-size: 1.78rem;
            font-weight: 900;
            line-height: 1.1;
            margin-bottom: 8px;
            letter-spacing: -0.04em;
        }
        .metric-panel .desc {
            color: #bfd0ea !important;
            font-size: 0.86rem;
            line-height: 1.5;
        }
        .section-shell {
            padding: 24px;
            margin-bottom: 16px;
            border-color: rgba(148,163,184,0.14);
            background:
                radial-gradient(circle at 100% 0%, rgba(250,204,21,0.08), transparent 22%),
                linear-gradient(180deg, rgba(255,255,255,0.045), rgba(255,255,255,0.01)),
                linear-gradient(180deg, rgba(10,20,37,0.96), rgba(7,14,27,0.98));
        }
        .section-shell h3 {
            margin: 0 0 10px 0;
            color: #ffffff !important;
            font-size: 1.14rem;
        }
        .section-shell p {
            margin: 0;
            color: #cbd7ee !important;
            line-height: 1.72;
        }
        .result-card {
            padding: 22px;
            margin-bottom: 12px;
            border-color: rgba(125,211,252,0.18);
            background:
                radial-gradient(circle at 100% 0%, rgba(250,204,21,0.08), transparent 24%),
                linear-gradient(180deg, rgba(255,255,255,0.035), rgba(255,255,255,0.008)),
                linear-gradient(180deg, rgba(10,21,39,0.98), rgba(8,16,29,0.96));
        }
        .result-card h4 {
            margin: 0 0 10px 0;
            color: #ffffff !important;
            font-size: 1.05rem;
        }
        .result-card p {
            margin: 0 0 7px 0;
            color: #d6e2f5 !important;
            line-height: 1.6;
        }
        .number-badges {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin: 12px 0 14px 0;
        }
        .number-ball {
            width: 44px;
            height: 44px;
            border-radius: 999px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            font-weight: 900;
            color: #07111f !important;
            background: linear-gradient(180deg, #fef3c7, #fbbf24);
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.65), 0 10px 22px rgba(251,191,36,0.18);
        }
        .divider-space { height: 12px; }
        .unlock-shell {
            padding: 18px 20px;
            margin-bottom: 14px;
            border-color: rgba(167,139,250,0.22);
            background: linear-gradient(135deg, rgba(124,58,237,0.16), rgba(8,16,30,0.95));
        }
        .unlock-shell .title {
            color: #ffffff !important;
            font-size: 1rem;
            font-weight: 900;
            margin-bottom: 6px;
        }
        .unlock-shell .desc {
            color: #d7e5fb !important;
            font-size: 0.92rem;
            line-height: 1.6;
        }
        .calendar-panel {
            padding: 18px 20px;
            margin-bottom: 14px;
            border-color: rgba(96,165,250,0.18);
        }
        .calendar-panel .title {
            color: #ffffff !important;
            font-size: 1rem;
            font-weight: 900;
            margin-bottom: 5px;
        }
        .calendar-panel .desc {
            color: #bfd0ea !important;
            font-size: 0.9rem;
        }
        .calendar-head {
            text-align: center;
            padding: 8px 0 10px 0;
            font-size: 0.8rem;
            font-weight: 800;
            color: #8edff8 !important;
        }
        .calendar-cell {
            min-height: 72px;
            border-radius: 16px;
            border: 1px dashed rgba(148,163,184,0.12);
            background: rgba(255,255,255,0.02);
        }
        .calendar-cell.empty {
            background: transparent;
            border-color: transparent;
        }
        .stage-card-bridge {
            padding: 18px 20px;
            margin: 10px 0 18px 0;
            border-color: rgba(103,232,249,0.2);
            background: linear-gradient(135deg, rgba(14,165,233,0.14), rgba(8,16,30,0.96) 55%, rgba(91,33,182,0.16));
        }
        .stage-card-bridge .header-title {
            color: #c9f2ff !important;
            font-size: 0.78rem;
            font-weight: 900;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin-bottom: 6px;
        }
        .stage-card-bridge .title {
            color: #ffffff !important;
            font-size: 1.08rem;
            font-weight: 900;
            margin-bottom: 6px;
        }
        .stage-card-bridge .desc {
            color: #d5e3f9 !important;
            font-size: 0.92rem;
            line-height: 1.6;
        }
        .stage-card-bridge .meta {
            color: #8edff8 !important;
            font-size: 0.83rem;
            margin-top: 8px;
        }
        [data-testid="stDataFrame"] {
            border-radius: 18px;
            overflow: hidden;
            border: 1px solid rgba(148,163,184,0.12);
            box-shadow: 0 16px 32px rgba(2,8,23,0.16);
        }
        @media (max-width: 900px) {
            .block-container {
                padding-top: 1rem;
                padding-bottom: 1.8rem;
                padding-left: 0.9rem;
                padding-right: 0.9rem;
            }
            .hero-card, .soft-panel, .feature-card, .section-shell, .result-card, .calendar-panel, .unlock-shell, .status-strip, .stage-card-bridge {
                border-radius: 18px;
            }
            .hero-card { padding: 22px 18px 18px 18px; }
            .hero-title { font-size: 1.9rem; }
            .hero-subtitle, .soft-panel p, .feature-card .desc, .section-shell p, .result-card p, .status-strip .desc, .status-strip .meta { font-size: 0.9rem; }
            .status-strip {
                flex-direction: column;
                align-items: flex-start;
            }
            .metric-panel {
                min-height: auto;
                padding: 16px;
            }
            .metric-panel .value { font-size: 1.48rem; }
            .number-ball {
                width: 40px;
                height: 40px;
                font-size: 0.92rem;
            }
        }
        
.sim-shell {
    border: 1px solid rgba(125,211,252,0.16);
    border-radius: 24px;
    background:
        linear-gradient(180deg, rgba(255,255,255,0.045), rgba(255,255,255,0.01)),
        linear-gradient(180deg, rgba(7,16,30,0.98), rgba(4,10,21,0.98));
    box-shadow: 0 24px 70px rgba(2, 8, 23, 0.34), inset 0 1px 0 rgba(255,255,255,0.05);
    padding: 22px 24px;
    margin: 8px 0 18px 0;
}
.sim-shell h4, .sim-card h4, .sim-banner h4 { margin: 0 0 8px 0; color: #ffffff; }
.sim-shell p, .sim-card p, .sim-banner p { color: #cbd5e1; line-height: 1.65; }
.sim-card {
    border: 1px solid rgba(148,163,184,0.16);
    border-radius: 22px;
    padding: 20px 22px;
    min-height: 196px;
    background:
        linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0.01)),
        linear-gradient(180deg, rgba(11,21,38,0.98), rgba(6,12,24,0.98));
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.05);
}
.sim-card + .sim-card { margin-top: 12px; }
.sim-badge-row { display: flex; flex-wrap: wrap; gap: 10px; margin: 12px 0 0 0; }
.sim-badge {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 9px 13px;
    border-radius: 999px;
    background: rgba(15,23,42,0.72);
    border: 1px solid rgba(125,211,252,0.16);
    color: #e2e8f0;
    font-size: 0.82rem;
    font-weight: 700;
}
.sim-value {
    display: block;
    margin-top: 12px;
    color: #ffffff;
    font-size: 2rem;
    font-weight: 900;
    letter-spacing: -0.04em;
}
.sim-meta-list {
    margin: 16px 0 0 0;
    padding-left: 18px;
    color: #cbd5e1;
    line-height: 1.8;
}
.sim-banner {
    border: 1px solid rgba(34,211,238,0.16);
    border-radius: 24px;
    padding: 18px 22px;
    margin: 6px 0 16px 0;
    background:
        radial-gradient(circle at 0% 0%, rgba(34,211,238,0.16), transparent 24%),
        radial-gradient(circle at 100% 0%, rgba(168,85,247,0.14), transparent 28%),
        linear-gradient(180deg, rgba(9,18,35,0.98), rgba(6,12,24,0.98));
}
.sim-banner .eyebrow, .sim-card .eyebrow {
    display: inline-flex;
    padding: 6px 10px;
    border-radius: 999px;
    font-size: 0.74rem;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #cffafe;
    background: rgba(8,145,178,0.12);
    border: 1px solid rgba(125,211,252,0.18);
    margin-bottom: 10px;
}
.sim-mini-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 12px;
    margin-top: 16px;
}
.sim-mini-item {
    border-radius: 18px;
    padding: 16px 16px;
    background: rgba(15,23,42,0.66);
    border: 1px solid rgba(148,163,184,0.14);
}
.sim-mini-label { color: #94a3b8; font-size: 0.82rem; font-weight: 700; }
.sim-mini-value { color: #ffffff; font-size: 1.24rem; font-weight: 900; margin-top: 6px; }
.sim-console {
    border-radius: 26px;
    padding: 22px 24px;
    border: 1px solid rgba(251,191,36,0.18);
    background:
        radial-gradient(circle at 0% 0%, rgba(245,158,11,0.16), transparent 24%),
        radial-gradient(circle at 100% 0%, rgba(239,68,68,0.10), transparent 24%),
        linear-gradient(180deg, rgba(14,18,30,0.99), rgba(8,10,18,0.99));
    box-shadow: 0 24px 70px rgba(2, 8, 23, 0.34), inset 0 1px 0 rgba(255,255,255,0.05);
    margin: 10px 0 18px 0;
}
.sim-console-top {
    display: flex; flex-wrap: wrap; justify-content: space-between; gap: 14px; align-items: flex-start;
    margin-bottom: 16px;
}
.sim-console-kpis { display: flex; flex-wrap: wrap; gap: 10px; }
.sim-console-kpi {
    min-width: 150px;
    padding: 12px 14px;
    border-radius: 18px;
    background: rgba(15,23,42,0.7);
    border: 1px solid rgba(148,163,184,0.16);
}
.sim-console-kpi b { display:block; color:#f8fafc; font-size:1.12rem; margin-top:6px; }
.sim-console-kpi span { color:#94a3b8; font-size:0.8rem; font-weight:700; }
.sim-form-caption {
    color: #94a3b8;
    font-size: 0.86rem;
    margin: 8px 0 0 0;
    line-height: 1.7;
}
@media (max-width: 980px) {
    .sim-mini-grid { grid-template-columns: 1fr; }
    .sim-console-top { flex-direction: column; }
}

</style>
        """,
        unsafe_allow_html=True,
    )
    components.html(
        """
        <script>
        (function () {
            const LABELS = new Set(["Manage app", "Hosted with Streamlit"]);
            const SELECTORS = [
                '[class*="viewerBadge"]',
                '[data-testid="stStatusWidget"]',
                'button[aria-label="Manage app"]',
                'a[aria-label="Manage app"]',
                'button[title="Manage app"]',
                'a[title="Manage app"]'
            ];

            function hideTarget(rootDoc) {
                SELECTORS.forEach((selector) => {
                    rootDoc.querySelectorAll(selector).forEach((node) => {
                        node.style.display = "none";
                        node.style.visibility = "hidden";
                    });
                });

                rootDoc.querySelectorAll("button, a, div, span").forEach((node) => {
                    const text = (node.textContent || "").trim();
                    if (!LABELS.has(text)) {
                        return;
                    }

                    let current = node;
                    for (let depth = 0; depth < 6 && current; depth += 1) {
                        const style = rootDoc.defaultView.getComputedStyle(current);
                        if (style.position === "fixed" || style.position === "sticky") {
                            current.style.display = "none";
                            current.style.visibility = "hidden";
                            return;
                        }
                        current = current.parentElement;
                    }

                    node.style.display = "none";
                    node.style.visibility = "hidden";
                });
            }

            const rootDoc = window.parent.document;
            hideTarget(rootDoc);
            new MutationObserver(() => hideTarget(rootDoc)).observe(rootDoc.body, {
                childList: true,
                subtree: true,
            });
            window.addEventListener("load", () => hideTarget(rootDoc));
            setInterval(() => hideTarget(rootDoc), 1500);
        })();
        </script>
        """,
        height=0,
        width=0,
    )


class LottoPredictor:
    def __init__(self, excel_path):
        self.excel_path = excel_path
        self.rows = self._load_rows(excel_path)
        self.total_draws = len(self.rows)
        self.universe = list(range(1, 46))
        self.base_hit_probability = 6.0 / 45.0
        self.max_gap_bucket = 25

        self.total_counter = Counter(n for row in self.rows for n in row)
        self.position_counters = [Counter() for _ in range(6)]
        for row in self.rows:
            for idx, num in enumerate(row):
                if idx < 6:
                    self.position_counters[idx][num] += 1

        self.last_seen_gap = self._build_last_seen_gap()
        self.gap_probability = self._build_gap_probability(prior_strength=32.0)
        self.pair_counter = self._build_pair_counter(window=320)
        self.avg_total_freq = (len(self.rows) * 6) / 45.0
        self.avg_pair_freq = max((len(self.rows) * 15) / ((45 * 44) / 2), 1e-6)
        self.gap_factor_lookup = self._build_gap_factor_lookup()
        self.pair_strength_matrix = self._build_pair_strength_matrix()
        self.probability_weight_lookup = self._build_probability_weight_lookup()
        self.base_position_weights = self._build_base_position_weights()
        self.adjacent_overlap_stats = self._build_adjacent_overlap_stats()

    def _load_rows(self, excel_path):
        df = pd.read_excel(excel_path)
        expected_number_cols = [f"번호{i}" for i in range(1, 7)]
        if all(col in df.columns for col in expected_number_cols):
            number_cols = expected_number_cols
        else:
            number_cols = [col for col in df.columns if str(col).startswith("번호")]
            if len(number_cols) >= 6:
                number_cols = sorted(
                    number_cols,
                    key=lambda col: int("".join(ch for ch in str(col) if ch.isdigit()) or 999),
                )[:6]
            else:
                number_cols = list(df.columns[:6])
        rows = []
        for _, row in df[number_cols].iterrows():
            vals = [int(cell) for cell in row.tolist() if isinstance(cell, (int, float)) and 1 <= int(cell) <= 45]
            if len(vals) == 6:
                rows.append(vals)
        return rows

    def _build_last_seen_gap(self):
        last_seen = {n: self.total_draws for n in self.universe}
        for idx, row in enumerate(self.rows):
            for n in row:
                if last_seen[n] == self.total_draws:
                    last_seen[n] = idx
        return last_seen

    def _build_gap_probability(self, prior_strength=32.0):
        stats = {gap: {"success": 0, "total": 0} for gap in range(self.max_gap_bucket + 1)}
        chrono_rows = list(reversed(self.rows))
        last_seen_idx = {n: None for n in self.universe}
        for idx, row in enumerate(chrono_rows):
            present = set(row)
            for n in self.universe:
                if last_seen_idx[n] is not None:
                    gap = min(idx - last_seen_idx[n] - 1, self.max_gap_bucket)
                    if gap >= 0:
                        stats[gap]["total"] += 1
                        if n in present:
                            stats[gap]["success"] += 1
            for n in present:
                last_seen_idx[n] = idx
        return {
            g: (s["success"] + self.base_hit_probability * prior_strength) / (s["total"] + prior_strength)
            for g, s in stats.items()
        }

    def _build_pair_counter(self, window=320):
        pair_counter = Counter()
        for row in self.rows[:window]:
            nums = sorted(list(row))
            for i in range(len(nums)):
                for j in range(i + 1, len(nums)):
                    pair_counter[(nums[i], nums[j])] += 1
        return pair_counter

    def _build_adjacent_overlap_stats(self):
        overlaps = [len(set(self.rows[i]) & set(self.rows[i + 1])) for i in range(len(self.rows) - 1)]
        return {"distribution": Counter(overlaps), "average": sum(overlaps) / len(overlaps) if overlaps else 0}

    def _build_gap_factor_lookup(self):
        lookup = [1.0] * 46
        for number in self.universe:
            gap = self.last_seen_gap[number]
            prob = self.gap_probability.get(min(gap, self.max_gap_bucket), self.base_hit_probability)
            lookup[number] = min(max(prob / self.base_hit_probability, 0.78), 1.35)
        return lookup

    def _build_pair_strength_matrix(self):
        matrix = [[1.0] * 46 for _ in range(46)]
        normalizer = self.avg_pair_freq + 1.0
        for idx, left in enumerate(self.universe):
            for right in self.universe[idx + 1 :]:
                value = (self.pair_counter.get((left, right), 0) + 1.0) / normalizer
                matrix[left][right] = value
                matrix[right][left] = value
        return matrix

    def _build_probability_weight_lookup(self):
        lookup = [0.0] * 46
        for number in self.universe:
            overall_prob = (self.total_counter[number] + 2.0) / (self.total_draws + 2.0 * 45)
            gap_factor = self.gap_factor_lookup[number]
            lookup[number] = max((overall_prob / self.base_hit_probability) ** 1.15 * (gap_factor ** 1.55), 1e-9)
        return lookup

    def _build_base_position_weights(self):
        weights = [[0.0] * 46 for _ in range(6)]
        for position in range(6):
            for number in self.universe:
                total_f = (self.total_counter[number] + 1.0) / (self.avg_total_freq + 1.0)
                gap_f = self.gap_factor_lookup[number]
                weights[position][number] = max(float((total_f ** 0.92) * (gap_f ** 1.35)), 1e-9)
        return weights

    def _current_gap_factor(self, number):
        return self.gap_factor_lookup[number]

    def _probability_only_weight(self, number):
        return self.probability_weight_lookup[number]

    def _number_weight(self, number, position, picked, add_noise=True):
        pair_s = 1.0
        if picked:
            pair_s = sum(self.pair_strength_matrix[number][p] for p in picked) / len(picked)
        noise = random.uniform(0.986, 1.014) if add_noise else 1.0
        return max(float(self.base_position_weights[position][number] * (pair_s ** 1.08) * noise), 1e-9)

    def get_number_info(self, n):
        gf = self._current_gap_factor(n)
        gap = self.last_seen_gap[n]
        status = "최신 회차 출현" if gap == 0 else f"최근 {gap}회 미출현"
        label = "(유리)" if gf > 1.05 else "(약함)" if gf < 0.95 else "(보통)"
        return f"- {n:02d} | 전체출현 {self.total_counter[n]}회 | gap {gap:>2} | {status} | gap계수 {gf:.4f} {label} | 확률가중치 {self._probability_only_weight(n):.4f}"

    def average_gap_factor(self, numbers):
        return round(sum(self._current_gap_factor(n) for n in numbers) / len(numbers), 6)

    def average_probability_weight(self, numbers):
        return round(sum(self._probability_only_weight(n) for n in numbers) / len(numbers), 6)

    def predict(self, sets=5, simulation_count: int | None = None):
        simulation_count = _sanitize_simulation_count(simulation_count) if simulation_count is not None else DEFAULT_SIMULATION_COUNT
        best_by_key = {}
        for _ in range(simulation_count):
            available = self.universe.copy()
            picked = []
            pair_sums = [0.0] * 46
            score = 0.0

            for position in range(6):
                deterministic_weights = []
                sampled_weights = []
                picked_count = len(picked)
                for number in available:
                    pair_factor = 1.0 if picked_count == 0 else max(pair_sums[number] / picked_count, 1e-9)
                    deterministic_weight = max(self.base_position_weights[position][number] * (pair_factor ** 1.08), 1e-9)
                    deterministic_weights.append(deterministic_weight)
                    sampled_weights.append(deterministic_weight * random.uniform(0.986, 1.014))

                selected_index = random.choices(range(len(available)), weights=sampled_weights, k=1)[0]
                selected_number = available.pop(selected_index)
                picked.append(selected_number)
                score += math.log(max(deterministic_weights[selected_index], 1e-12))

                for candidate in available:
                    pair_sums[candidate] += self.pair_strength_matrix[candidate][selected_number]

            key = tuple(sorted(picked))
            current = best_by_key.get(key)
            if current is None or score > current["score_raw"]:
                best_by_key[key] = {"ordered": picked, "sorted": list(key), "score_raw": score}

        final = sorted(best_by_key.values(), key=lambda item: item["score_raw"], reverse=True)[:sets]
        return [{"ordered": item["ordered"], "sorted": item["sorted"], "score": round(item["score_raw"], 4)} for item in final]

    def predict_probability_only(self, sets=5, simulation_count: int | None = None):
        simulation_count = _sanitize_simulation_count(simulation_count) if simulation_count is not None else DEFAULT_SIMULATION_COUNT
        best_by_key = {}
        for _ in range(simulation_count):
            available = self.universe.copy()
            picked = []
            score = 0.0
            for _ in range(6):
                weights = [self.probability_weight_lookup[number] for number in available]
                if sum(weights) <= 0:
                    weights = [1.0] * len(available)
                selected_index = random.choices(range(len(available)), weights=weights, k=1)[0]
                selected_number = available.pop(selected_index)
                picked.append(selected_number)
                score += math.log(max(self.probability_weight_lookup[selected_number], 1e-12))

            key = tuple(sorted(picked))
            current = best_by_key.get(key)
            if current is None or score > current["score_raw"]:
                best_by_key[key] = {"sorted": list(key), "score_raw": score}

        final = sorted(best_by_key.values(), key=lambda item: item["score_raw"], reverse=True)[:sets]
        return [{"sorted": item["sorted"], "ordered": None, "score": round(item["score_raw"], 4)} for item in final]

    def score_manual_combination(self, numbers):
        input_numbers = [int(n) for n in numbers]
        sorted_numbers = sorted(input_numbers)
        permutation_scores = []
        for perm in permutations(sorted_numbers):
            ordered = list(perm)
            score = sum(math.log(self._number_weight(n, idx, ordered[:idx], False)) for idx, n in enumerate(ordered))
            permutation_scores.append((score, ordered))

        best_score, best_order = max(permutation_scores, key=lambda item: item[0])
        average_score = sum(score for score, _ in permutation_scores) / len(permutation_scores)
        input_order_score = sum(
            math.log(self._number_weight(n, idx, input_numbers[:idx], False))
            for idx, n in enumerate(input_numbers)
        )
        probability_score = sum(math.log(self._probability_only_weight(n)) for n in sorted_numbers)
        return {
            "input_order": input_numbers,
            "sorted": sorted_numbers,
            "best_order": best_order,
            "best_score": round(best_score, 4),
            "average_score": round(average_score, 4),
            "input_order_score": round(input_order_score, 4),
            "probability_score": round(probability_score, 4),
        }


def _init_session_state(project_dir: Path):
    persisted = load_app_state(project_dir)
    defaults = {
        "auth": False,
        "counts": dict(persisted.get("counts", {"prediction": 0, "probability": 0, "manual": 0})),
        "unlock_mode": False,
        "unlock_granted": bool(persisted.get("unlock_granted", False)),
        "predict_results": None,
        "probability_results": None,
        "manual_result": None,
        "analysis_summary": None,
        "view": "",
        "show_data_gate": False,
        "data_access_granted": bool(persisted.get("data_access_granted", False)),
        "history_selected_date": None,
        "simulation_count": _sanitize_simulation_count(persisted.get("simulation_count", DEFAULT_SIMULATION_COUNT)),
        "simulation_notice": None,
        "analysis_signature": None,
        "source_data_refresh_notice": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _persist_runtime_state(project_dir: Path):
    save_app_state(
        project_dir,
        counts=st.session_state.get("counts", {}),
        unlock_granted=st.session_state.get("unlock_granted", False),
        data_access_granted=st.session_state.get("data_access_granted", False),
        simulation_count=_sanitize_simulation_count(st.session_state.get("simulation_count", DEFAULT_SIMULATION_COUNT)),
    )


def _read_report_csv(report_dir: Path, file_key: str) -> pd.DataFrame:
    file_name = REPORT_FILE_MAP[file_key]
    file_path = report_dir / file_name
    if not file_path.exists() or file_path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(file_path)
    except Exception:
        return pd.DataFrame()


def _render_download_button(path: Path, label: str, mime: str, key: str):
    if not path.exists():
        return
    with path.open("rb") as fp:
        st.download_button(
            label=label,
            data=fp.read(),
            file_name=path.name,
            mime=mime,
            key=key,
            use_container_width=True,
        )


def _artifact_label(key: str) -> str:
    return ARTIFACT_LABEL_MAP.get(str(key), str(key))


def _history_display_df(history_df: pd.DataFrame) -> pd.DataFrame:
    if history_df.empty:
        return history_df
    display = history_df.copy()
    if "log_type" in display.columns:
        display["log_type"] = display["log_type"].map(_log_type_label)
    keep_cols = [
        "log_type",
        "timestamp_kst",
        "date_kst",
        "week_kst",
        "month_kst",
        "target_round",
        "candidate_rank",
        "numbers_text",
        "input_numbers_text",
        "best_order_text",
        "matched_numbers_text",
        "score_metric",
        "input_order_score",
        "avg_gap_factor",
        "avg_probability_weight",
        "run_id",
    ]
    display = display[[c for c in keep_cols if c in display.columns]].copy()
    rename_map = {
        "log_type": "로그유형",
        "timestamp_kst": "저장시각(KST)",
        "date_kst": "일자",
        "week_kst": "주간",
        "month_kst": "월간",
        "target_round": "대상회차",
        "candidate_rank": "후보순위",
        "numbers_text": "번호조합",
        "input_numbers_text": "입력순서",
        "best_order_text": "최적순서",
        "matched_numbers_text": "일치번호",
        "score_metric": "대표점수",
        "input_order_score": "입력순서점수",
        "avg_gap_factor": "평균 gap 계수",
        "avg_probability_weight": "평균 확률 가중치",
        "run_id": "run_id",
    }
    return display.rename(columns=rename_map)


def _usage_status_snapshot() -> tuple[str, str, str, str]:
    unlock_granted = bool(st.session_state.get("unlock_granted"))
    if unlock_granted:
        return "무제한 모드", "무제한", "무제한", "사용 제한 해제가 유지 중입니다."

    counts = st.session_state.get("counts", {})
    prediction_remaining = str(_remaining_uses(counts.get("prediction", 0)))
    probability_remaining = str(_remaining_uses(counts.get("probability", 0)))
    return (
        "제한 모드",
        f"{prediction_remaining}/{LOCK_LIMIT}",
        f"{probability_remaining}/{LOCK_LIMIT}",
        "패턴 추천과 확률 추천은 각각 최대 3회까지 사용할 수 있습니다.",
    )


def _render_hero(predictor: LottoPredictor):
    st.markdown(
        f"""
        <div class="hero-card">
            <div class="hero-eyebrow">DAINTELLIGENCE</div>
            <h1 class="hero-title">{TITLE}</h1>
            <p class="hero-subtitle">{SUBTITLE}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_feature_card(theme: str, eyebrow: str, title: str, desc: str):
    st.markdown(
        f"""
        <div class="feature-card {theme}">
            <div class="eyebrow">{eyebrow}</div>
            <div class="title">{title}</div>
            <div class="desc">{desc}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_home_guide_studio() -> None:
    mode_label, prediction_remaining, probability_remaining, limit_desc = _usage_status_snapshot()
    st.markdown(
        f"""
        <div class="guide-studio-shell">
            <div class="guide-grid">
                <div class="guide-card-premium guide-card-cyan">
                    <div class="card-label">Quick Start</div>
                    <h4>처음 사용하는 분을 위한 순서</h4>
                    <p>처음 접속했다면 아래 4단계만 따라가면 전체 기능 흐름을 가장 빠르게 이해할 수 있습니다.</p>
                    <ol class="guide-step-list">
                        <li><b>패턴 추천 바로 받기</b> 또는 <b>확률 추천 바로 받기</b>를 눌러 먼저 결과 화면으로 이동합니다.</li>
                        <li>상단 후보 카드에서 <b>점수 · 추천 순서 · gap 계수</b>를 비교해 우선 검토할 조합을 좁힙니다.</li>
                        <li>관심 있는 번호는 <b>수동 번호 점수 확인</b>에 다시 넣어 동일 기준으로 한 번 더 검증합니다.</li>
                        <li>마지막으로 <b>로그 분석 · 히스토리</b>에서 누적 흐름, 적중 매칭, 임계값 변화를 확인합니다.</li>
                    </ol>
                </div>
                <div class="guide-card-premium guide-card-violet">
                    <div class="card-label">Reading Guide</div>
                    <h4>결과 읽는 방법</h4>
                    <p>추천 결과는 숫자만 보는 것보다 각 지표를 함께 읽을 때 판단이 더 쉬워집니다.</p>
                    <ul class="guide-step-list">
                        <li><b>점수</b> : 후보끼리 우선순위를 비교할 때 가장 먼저 보는 대표 지표입니다.</li>
                        <li><b>추천 순서</b> : 모델이 조합을 어떤 흐름으로 평가했는지 보여줍니다.</li>
                        <li><b>평균 gap 계수</b> : 최근 미출현 흐름이 얼마나 반영됐는지 확인할 수 있습니다.</li>
                        <li><b>평균 확률 가중치</b> : 전체 빈도와 gap 확률을 합친 기본 강도를 뜻합니다.</li>
                    </ul>
                </div>
                <div class="guide-card-premium guide-card-emerald">
                    <div class="card-label">Workspace</div>
                    <h4>사용 제한 · 작업 상태</h4>
                    <p>현재 홈 화면에서 확인할 수 있는 사용 제한 결과 값을 바로 볼 수 있습니다.</p>
                    <ul class="guide-step-list">
                        <li><b>현재 운영 모드</b> : {mode_label}</li>
                        <li><b>패턴 추천 남은 횟수</b> : {prediction_remaining}</li>
                        <li><b>확률 추천 남은 횟수</b> : {probability_remaining}</li>
                        <li><b>상태 안내</b> : {limit_desc}</li>
                    </ul>
                    <div class="guide-note">데이터 인벤토리 logs를 <b>축적·분석</b>하도록 설계 했습니다.</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_metric_panel(container, label: str, value: str, desc: str):
    container.markdown(
        f"""
        <div class="metric-panel">
            <div class="label">{label}</div>
            <div class="value">{value}</div>
            <div class="desc">{desc}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_stats_grid(container, items: list[tuple[str, str, str]]):
    if not items:
        return
    row_size = 3 if len(items) > 2 else len(items)
    for start in range(0, len(items), row_size):
        chunk = items[start : start + row_size]
        cols = container.columns(len(chunk))
        for col, (label, value, desc) in zip(cols, chunk):
            _render_metric_panel(col, label, value, desc)


def _build_analysis_context_items(
    predictor: "LottoPredictor",
    latest_source_round: int | None = None,
) -> list[tuple[str, str, str]]:
    analyzed_round = int(latest_source_round) if latest_source_round is not None else int(predictor.total_draws)
    return [
        ("분석 회차", f"{analyzed_round:,}", "현재 불러온 최신 원본 회차 기준입니다."),
        ("평균 인접 중복", f"{predictor.adjacent_overlap_stats['average']:.3f}", "연속 회차 사이 번호 겹침 정도입니다."),
        ("시뮬레이션 규모", f"{_current_simulation_count():,}", "추천 계산에 사용하는 반복 횟수입니다."),
    ]


def _build_home_overview_items(predictor: "LottoPredictor", latest_source_round: int | None = None) -> list[tuple[str, str, str]]:
    prediction_remaining = "∞" if st.session_state.get("unlock_granted") else str(_remaining_uses(st.session_state.get("counts", {}).get("prediction", 0)))
    probability_remaining = "∞" if st.session_state.get("unlock_granted") else str(_remaining_uses(st.session_state.get("counts", {}).get("probability", 0)))
    mode_label = "무제한" if st.session_state.get("unlock_granted") else "제한 모드"
    return _build_analysis_context_items(predictor, latest_source_round) + [
        ("패턴 추천 사용 가능", prediction_remaining, "현재 세션에서 바로 실행 가능한 패턴 추천 상태입니다."),
        ("확률 추천 사용 가능", probability_remaining, "출현 확률 추천에서 즉시 사용할 수 있는 상태입니다."),
        ("현재 운영 모드", mode_label, "잠금 상태와 추천 사용 정책을 한눈에 보여줍니다."),
    ]


def _render_home_dashboard(predictor: "LottoPredictor") -> None:
    return


def _get_stage_separator_copy(view: str) -> tuple[str, str, str] | None:
    return None


def _render_stage_separator(container, view: str) -> None:
    copy = _get_stage_separator_copy(view)
    if not copy:
        return
    eyebrow, title, desc = copy
    container.markdown(
        f"""
        <div class="stage-card-bridge">
            <div class="header-title">{eyebrow}</div>
            <div class="title">{title}</div>
            <div class="desc">{desc}</div>
            <div class="meta">핵심 수치 확인 → 추천 카드 또는 로그 데이터 해석 순서로 이어지도록 화면 흐름을 다시 정리했습니다.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _format_ball_badges(numbers: list[int]) -> str:
    return "".join(f'<span class="number-ball">{int(n):02d}</span>' for n in numbers)


def _render_number_detail_cards(container, predictor: LottoPredictor, numbers: list[int]) -> None:
    if not numbers:
        return
    for start in range(0, len(numbers), 3):
        chunk = numbers[start : start + 3]
        cols = container.columns(len(chunk))
        for col, n in zip(cols, chunk):
            gap = predictor.last_seen_gap[n]
            gap_factor = predictor._current_gap_factor(n)
            prob_weight = predictor._probability_only_weight(n)
            status = "최신 회차 출현" if gap == 0 else f"최근 {gap}회 미출현"
            panel = col.container()
            panel.markdown(f"**번호 {n:02d}**")
            panel.caption(f"전체 출현 {predictor.total_counter[n]}회")
            panel.caption(f"현재 상태 {status}")
            panel.caption(f"gap 계수 {gap_factor:.4f}")
            panel.caption(f"확률 가중치 {prob_weight:.4f}")


def _render_result_block(container, title: str, intro: str, results: list[dict], predictor: LottoPredictor, probability_only: bool = False):
    if title:
        container.markdown(f"### {title}")
    if intro:
        container.caption(intro)
    for i, item in enumerate(results, 1):
        numbers = item["sorted"]
        ordered = item.get("ordered")
        label = "확률 후보" if probability_only else "후보"
        ordered_text = _format_number_sequence(ordered) if ordered else "-"
        container.markdown(
            f"""
            <div class="result-card">
                <h4>{label} {i:02d} · 점수 {item['score']}</h4>
                <div class="number-badges">{_format_ball_badges(numbers)}</div>
                <p><b>추천 순서</b> : {ordered_text}</p>
                <p><b>평균 gap 계수</b> : {predictor.average_gap_factor(numbers):.6f}</p>
                <p><b>평균 확률 가중치</b> : {predictor.average_probability_weight(numbers):.6f}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        _render_number_detail_cards(container, predictor, numbers)
        container.markdown("<div class='divider-space'></div>", unsafe_allow_html=True)


KOREAN_WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]
LOG_TYPE_LABELS = {
    "prediction": "패턴 분석",
    "probability": "확률 분석",
    "manual": "수동 점수",
    "analysis": "분석 요약",
}
PERIOD_LABELS = {
    "date_kst": "일자",
    "week_kst": "주간",
    "month_kst": "월간",
}


def _log_type_label(value: str) -> str:
    return LOG_TYPE_LABELS.get(str(value), str(value))


def _format_number_sequence(numbers) -> str:
    if not numbers:
        return "-"
    try:
        return ", ".join(f"{int(n):02d}" for n in numbers)
    except Exception:
        return str(numbers)


def _format_period_summary_df(summary_df: pd.DataFrame, period_col: str) -> pd.DataFrame:
    if summary_df.empty:
        return summary_df
    display = summary_df.copy()
    if "log_type" in display.columns:
        display["log_type"] = display["log_type"].map(_log_type_label)
    rename_map = {
        period_col: PERIOD_LABELS.get(period_col, period_col),
        "log_type": "로그유형",
        "logs": "저장건수",
        "unique_runs": "실행수",
        "unique_target_rounds": "대상회차수",
        "scored_logs": "점수보유건수",
        "score_coverage": "점수보유율",
        "avg_score": "평균 대표점수",
        "median_score": "중앙값 점수",
        "score_std": "점수 표준편차",
        "best_score": "최고 대표점수",
        "p25_score": "점수 25%",
        "p75_score": "점수 75%",
        "avg_gap_factor": "평균 gap 계수",
        "avg_probability_weight": "평균 확률 가중치",
    }
    return display.rename(columns=rename_map)


def _format_log_type_summary_df(summary_df: pd.DataFrame) -> pd.DataFrame:
    if summary_df.empty:
        return summary_df
    display = summary_df.copy()
    if "log_type" in display.columns:
        display["log_type"] = display["log_type"].map(_log_type_label)
    rename_map = {
        "log_type": "로그유형",
        "logs": "저장건수",
        "unique_runs": "실행수",
        "unique_target_rounds": "대상회차수",
        "scored_logs": "점수보유건수",
        "score_coverage": "점수보유율",
        "avg_score": "평균 대표점수",
        "median_score": "중앙값 점수",
        "score_std": "점수 표준편차",
        "best_score": "최고 대표점수",
        "p25_score": "점수 25%",
        "p75_score": "점수 75%",
        "avg_gap_factor": "평균 gap 계수",
        "avg_probability_weight": "평균 확률 가중치",
    }
    return display.rename(columns=rename_map)


def _render_analysis_summary_detail(summary: dict) -> None:
    summary = dict(summary or {})
    threshold = summary.get("recommended_threshold") or {}
    _render_stats_grid(
        st,
        [
            ("매칭 로그", f"{int(summary.get('resolved_match_rows', 0) or 0):,}", "실제 당첨 번호와 비교 가능한 로그 수입니다."),
            ("시계열 행", f"{int(summary.get('time_series_rows', 0) or 0):,}", "날짜별 추이 분석에 반영된 집계 행 수입니다."),
            ("추천 임계값", str(threshold.get("threshold", "-")), "3개 이상 적중 비율을 계산할 때 추천된 기준 점수입니다."),
            ("실행 ID", str(summary.get("run_id") or "-"), "이번 분석 실행을 구분하는 식별값입니다."),
        ],
    )

    if threshold:
        st.markdown(
            f"""
            <div class="soft-panel">
                <h4>추천 임계값 상세</h4>
                <p>기준 점수 <b>{threshold.get('threshold', '-')}</b><br>
                샘플 수 <b>{threshold.get('samples', '-')}</b><br>
                3개 이상 적중 비율 <b>{threshold.get('hit_3_plus_rate', 0):.2%}</b></p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.info("현재는 추천 임계값을 계산할 만큼 실제 매칭 로그가 충분하지 않습니다.")

    artifacts = summary.get("artifacts") or {}
    if isinstance(artifacts, dict) and artifacts:
        artifact_df = pd.DataFrame(
            [
                {"산출물": _artifact_label(key), "파일명": value}
                for key, value in artifacts.items()
            ]
        )
        st.markdown("##### 산출물 파일")
        st.dataframe(artifact_df, use_container_width=True, hide_index=True)


def _render_period_kpis(logs_df: pd.DataFrame, prefix: str):
    score_series = pd.to_numeric(logs_df.get("score_metric"), errors="coerce") if not logs_df.empty else pd.Series(dtype=float)
    scored = score_series.dropna()
    avg_score = scored.mean() if not scored.empty else float("nan")
    best_score = scored.max() if not scored.empty else float("nan")
    score_std = scored.std(ddof=0) if not scored.empty else float("nan")
    type_count = int(logs_df["log_type"].nunique()) if (not logs_df.empty and "log_type" in logs_df.columns) else 0
    unique_runs = int(logs_df["run_id"].replace("-", pd.NA).dropna().nunique()) if (not logs_df.empty and "run_id" in logs_df.columns) else 0
    score_coverage = (len(scored) / len(logs_df)) if len(logs_df) else 0.0

    _render_stats_grid(
        st,
        [
            (f"{prefix} 로그", f"{len(logs_df):,}", "선택한 범위에 저장된 로그 수입니다."),
            (f"{prefix} 실행수", f"{unique_runs:,}", "동일 run_id를 묶은 실제 분석 실행 횟수입니다."),
            (f"{prefix} 로그 유형", f"{type_count:,}", "해당 기간에 기록된 로그 유형 수입니다."),
            (f"{prefix} 점수보유율", f"{score_coverage:.1%}", "대표 점수를 가진 로그 비율입니다."),
            (f"{prefix} 평균 점수", f"{avg_score:.4f}" if pd.notna(avg_score) else "-", "대표 점수의 평균값입니다."),
            (f"{prefix} 점수 표준편차", f"{score_std:.4f}" if pd.notna(score_std) else "-", "점수 분산이 큰지 빠르게 확인하는 지표입니다."),
            (f"{prefix} 최고 점수", f"{best_score:.4f}" if pd.notna(best_score) else "-", "대표 점수 기준 최고값입니다."),
        ],
    )


def _render_log_detail_table(logs_df: pd.DataFrame, title: str, key_prefix: str, preview_limit: int = 200) -> None:
    st.markdown(f"##### {title}")
    if logs_df.empty:
        st.info("표시할 로그가 없습니다.")
        return

    display_df = _history_display_df(logs_df)
    total_rows = int(len(display_df))
    preview_df = display_df.head(preview_limit).copy()
    st.caption(f"미리보기는 최근 {min(total_rows, preview_limit):,}건을 보여주며, 다운로드 버튼으로 전체 로그를 받을 수 있습니다. 전체 보관 로그 수: {total_rows:,}건")
    st.dataframe(preview_df, use_container_width=True, hide_index=True)

    csv_data = display_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    st.download_button(
        f"{title} 전체 CSV 다운로드",
        data=csv_data,
        file_name=f"{key_prefix}_full_history.csv",
        mime="text/csv",
        key=f"download_{key_prefix}_full_history",
        use_container_width=True,
    )


def _remaining_uses(count: int) -> int:
    return max(LOCK_LIMIT - int(count or 0), 0)


def _render_home_status_strip() -> None:
    prediction_remaining = _remaining_uses(st.session_state.counts.get("prediction", 0))
    probability_remaining = _remaining_uses(st.session_state.counts.get("probability", 0))

    if st.session_state.unlock_granted:
        tone = "unlocked"
        badge = "무제한 유지"
        title = "사용 제한 해제가 유지 중입니다"
        desc = "패턴 추천과 확률 추천을 계속 이용할 수 있습니다. 원하는 방식으로 바로 결과 화면으로 이동해 비교해 보세요."
        meta = "두 추천 버튼 모두 즉시 실행 가능합니다. 로그 분석 · 히스토리와 함께 흐름을 이어서 확인하면 좋습니다."
    else:
        tone = "limited"
        badge = "제한 모드"
        title = "현재는 제한 모드입니다"
        desc = "패턴 추천과 확률 추천은 각각 최대 3회까지 사용할 수 있습니다. 분석 스튜디오 아래에서 남은 사용 가능 횟수를 바로 확인할 수 있습니다."
        meta = f"패턴 남은 횟수 {prediction_remaining}/{LOCK_LIMIT} · 확률 남은 횟수 {probability_remaining}/{LOCK_LIMIT}"

    st.markdown(
        f"""
        <div class="status-strip {tone}">
            <div class="badge">{badge}</div>
            <div class="body">
                <div class="title">{title}</div>
                <div class="desc">{desc}</div>
                <div class="meta">{meta}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _shift_month(base_date: date, month_offset: int) -> date:
    total_month = (base_date.year * 12 + (base_date.month - 1)) + month_offset
    year = total_month // 12
    month = total_month % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(base_date.day, last_day))


def _coerce_date_value(value, fallback: date) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except Exception:
            return fallback
    return fallback


def _sync_history_selected_date_from_picker():
    picker_value = st.session_state.get("history_selected_date_picker")
    if picker_value is None:
        return
    st.session_state.history_selected_date = _coerce_date_value(picker_value, st.session_state.get("history_selected_date"))


def _prepare_history_analytics(history_df: pd.DataFrame) -> pd.DataFrame:
    return enrich_history_dataframe(history_df)


def _build_period_summary(history_df: pd.DataFrame, period_col: str) -> pd.DataFrame:
    return build_history_period_summary(history_df, period_col)


def _build_log_type_summary(history_df: pd.DataFrame) -> pd.DataFrame:
    return build_history_log_type_summary(history_df)


def _render_clickable_calendar(history_df: pd.DataFrame, selected_date: date) -> None:
    selected_month = selected_date.strftime("%Y-%m")
    month_df = history_df[history_df["month_kst"] == selected_month].copy()

    st.markdown(
        f"""
        <div class="calendar-panel">
            <div class="title">{selected_month} 로그 캘린더</div>
            <div class="desc">원하는 날짜를 직접 눌러서 즉시 로그를 확인할 수 있습니다.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if month_df.empty:
        st.info("선택한 달에는 저장된 로그가 없습니다.")
        return

    year, month = [int(part) for part in selected_month.split("-")]
    day_counts = month_df.groupby("date_kst").size().to_dict()
    type_labels = (
        month_df.groupby("date_kst")["log_type"]
        .agg(lambda values: ", ".join(sorted({_log_type_label(v) for v in values})))
        .to_dict()
    )

    header_cols = st.columns(7)
    for idx, name in enumerate(["일", "월", "화", "수", "목", "금", "토"]):
        header_cols[idx].markdown(f"<div class='calendar-head'>{name}</div>", unsafe_allow_html=True)

    cal = calendar.Calendar(firstweekday=6)
    for week in cal.monthdayscalendar(year, month):
        cols = st.columns(7)
        for idx, day_value in enumerate(week):
            with cols[idx]:
                if day_value == 0:
                    st.markdown("<div class='calendar-cell empty'></div>", unsafe_allow_html=True)
                    continue
                day_obj = date(year, month, day_value)
                day_key = day_obj.strftime("%Y-%m-%d")
                count = int(day_counts.get(day_key, 0))
                types = type_labels.get(day_key, "로그 없음")
                button_type = "primary" if day_obj == selected_date else "secondary"
                if st.button(f"{day_value}", key=f"history_calendar_{day_key}", use_container_width=True, type=button_type):
                    st.session_state.history_selected_date = day_obj
                    st.rerun()
                st.caption(f"{count}건")
                st.caption(types)


def _render_calendar_history_section(history_df: pd.DataFrame):
    analytics_df = _prepare_history_analytics(history_df)
    if analytics_df.empty:
        st.info("표시할 로그 히스토리가 없습니다.")
        return

    available_dates = [d for d in analytics_df["date_obj"].dropna().drop_duplicates().tolist() if d is not None]
    if not available_dates:
        st.info("날짜 정보가 있는 로그가 아직 없습니다.")
        return

    available_dates = sorted(available_dates)
    latest_date = available_dates[-1]
    min_date = available_dates[0]
    max_date = available_dates[-1]

    current_selected = _coerce_date_value(st.session_state.get("history_selected_date"), latest_date)
    if current_selected < min_date:
        current_selected = min_date
    if current_selected > max_date:
        current_selected = max_date
    st.session_state.history_selected_date = current_selected
    if st.session_state.get("history_selected_date_picker") != current_selected:
        st.session_state.history_selected_date_picker = current_selected

    st.markdown("#### 달력 기반 로그 탐색")
    st.caption("월 선택은 기준 일자에 통합했고, 캘린더 날짜를 직접 눌러서 일별·주별·월별 로그를 바로 내려다볼 수 있게 정리했습니다.")

    picker_col, prev_col, today_col, next_col = st.columns([2.2, 1.0, 0.9, 1.0])
    with picker_col:
        selected_date = st.date_input(
            "기준 일자 선택",
            min_value=min_date,
            max_value=max_date,
            key="history_selected_date_picker",
            on_change=_sync_history_selected_date_from_picker,
        )
        st.session_state.history_selected_date = _coerce_date_value(selected_date, current_selected)
    with prev_col:
        st.markdown("<div style='height: 30px;'></div>", unsafe_allow_html=True)
        if st.button("◀ 이전 달", use_container_width=True, key="history_prev_month"):
            st.session_state.history_selected_date = _shift_month(st.session_state.history_selected_date, -1)
            st.rerun()
    with today_col:
        st.markdown("<div style='height: 30px;'></div>", unsafe_allow_html=True)
        if st.button("최신", use_container_width=True, key="history_latest_date"):
            st.session_state.history_selected_date = latest_date
            st.rerun()
    with next_col:
        st.markdown("<div style='height: 30px;'></div>", unsafe_allow_html=True)
        if st.button("다음 달 ▶", use_container_width=True, key="history_next_month"):
            st.session_state.history_selected_date = _shift_month(st.session_state.history_selected_date, 1)
            st.rerun()

    selected_date = st.session_state.history_selected_date
    _render_clickable_calendar(analytics_df, selected_date)

    selected_date_str = selected_date.strftime("%Y-%m-%d")
    selected_week = f"{selected_date.isocalendar().year}-W{selected_date.isocalendar().week:02d}"
    selected_month_str = selected_date.strftime("%Y-%m")

    day_df = analytics_df[analytics_df["date_kst"] == selected_date_str].copy()
    week_df = analytics_df[analytics_df["week_kst"] == selected_week].copy()
    month_df = analytics_df[analytics_df["month_kst"] == selected_month_str].copy()

    st.markdown(f"##### 선택 기준: {selected_date_str} · {selected_week} · {selected_month_str}")
    _render_period_kpis(day_df, "선택 일자")

    type_counts = day_df["log_type"].value_counts().rename_axis("log_type").reset_index(name="logs") if not day_df.empty else pd.DataFrame()
    if not type_counts.empty:
        type_counts["log_type"] = type_counts["log_type"].map(_log_type_label)
        st.dataframe(
            type_counts.rename(columns={"log_type": "로그유형", "logs": "저장건수"}),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("선택한 날짜에는 저장된 로그가 없습니다.")

    daily_summary = _build_period_summary(analytics_df, "date_kst")
    weekly_summary = _build_period_summary(analytics_df, "week_kst")
    monthly_summary = _build_period_summary(analytics_df, "month_kst")

    tab_day, tab_week, tab_month = st.tabs(["일별 상세", "주별 분석", "월별 분석"])

    with tab_day:
        day_logs = analytics_df[analytics_df["date_kst"] == selected_date_str].copy()
        _render_period_kpis(day_logs, "일별")
        left, right = st.columns([0.9, 1.1])
        with left:
            st.markdown(f"##### {selected_date_str} 유형별 요약")
            day_type = _build_log_type_summary(day_logs)
            if day_type.empty:
                st.info("선택한 날짜의 로그가 없습니다.")
            else:
                st.dataframe(_format_log_type_summary_df(day_type), use_container_width=True, hide_index=True)
        with right:
            st.markdown(f"##### {selected_date_str} 상세 로그")
            if day_logs.empty:
                st.info("선택한 날짜의 로그가 없습니다.")
            else:
                _render_log_detail_table(day_logs, f"{selected_date_str} 상세 로그", f"day_{selected_date_str}")
        if not daily_summary.empty:
            with st.expander("전체 일별 집계 보기"):
                st.dataframe(_format_period_summary_df(daily_summary.head(120), "date_kst"), use_container_width=True, hide_index=True)

    with tab_week:
        week_logs = analytics_df[analytics_df["week_kst"] == selected_week].copy()
        _render_period_kpis(week_logs, "주별")
        left, right = st.columns([1.0, 1.0])
        with left:
            st.markdown(f"##### {selected_week} 날짜별 요약")
            week_daily = _build_period_summary(week_logs, "date_kst")
            if week_daily.empty:
                st.info("선택한 주차의 로그가 없습니다.")
            else:
                st.dataframe(_format_period_summary_df(week_daily, "date_kst"), use_container_width=True, hide_index=True)
        with right:
            st.markdown(f"##### {selected_week} 로그유형 요약")
            week_type = _build_log_type_summary(week_logs)
            if week_type.empty:
                st.info("선택한 주차의 로그가 없습니다.")
            else:
                st.dataframe(_format_log_type_summary_df(week_type), use_container_width=True, hide_index=True)
        if not week_logs.empty:
            _render_log_detail_table(week_logs, "주간 상세 로그", f"week_{selected_week}")
        if not weekly_summary.empty:
            with st.expander("전체 주별 집계 보기"):
                st.dataframe(_format_period_summary_df(weekly_summary.head(80), "week_kst"), use_container_width=True, hide_index=True)

    with tab_month:
        month_logs = analytics_df[analytics_df["month_kst"] == selected_month_str].copy()
        _render_period_kpis(month_logs, "월별")
        left, right = st.columns([1.0, 1.0])
        with left:
            st.markdown(f"##### {selected_month_str} 날짜별 요약")
            month_daily = _build_period_summary(month_logs, "date_kst")
            if month_daily.empty:
                st.info("선택한 월의 로그가 없습니다.")
            else:
                st.dataframe(_format_period_summary_df(month_daily, "date_kst"), use_container_width=True, hide_index=True)
        with right:
            st.markdown(f"##### {selected_month_str} 로그유형 요약")
            month_type = _build_log_type_summary(month_logs)
            if month_type.empty:
                st.info("선택한 월의 로그가 없습니다.")
            else:
                st.dataframe(_format_log_type_summary_df(month_type), use_container_width=True, hide_index=True)
        if not month_logs.empty:
            _render_log_detail_table(month_logs, "월간 상세 로그", f"month_{selected_month_str}")
        if not monthly_summary.empty:
            with st.expander("전체 월별 집계 보기"):
                st.dataframe(_format_period_summary_df(monthly_summary.head(36), "month_kst"), use_container_width=True, hide_index=True)


def _render_single_log_tab(filtered: pd.DataFrame, title: str, empty_message: str):
    st.markdown(f"#### {title}")
    if filtered.empty:
        st.info(empty_message)
        return

    score_series = pd.to_numeric(filtered.get("score_metric"), errors="coerce")
    _render_stats_grid(
        st,
        [
            ("저장 건수", f"{len(filtered):,}", "현재 탭에 포함된 로그 수입니다."),
            ("평균 대표 점수", f"{score_series.dropna().mean():.3f}" if score_series.dropna().any() else "-", "대표 점수 기준 평균값입니다."),
            ("최근 저장", filtered["timestamp_kst"].iloc[0] if "timestamp_kst" in filtered.columns else "-", "가장 최근 저장 시각입니다."),
        ],
    )

    _render_log_detail_table(filtered, title, title.replace(" ", "_").lower(), preview_limit=120)

    preview_cols = [
        c
        for c in [
            "log_type",
            "timestamp_kst",
            "date_kst",
            "week_kst",
            "month_kst",
            "target_round",
            "numbers_text",
            "input_numbers_text",
            "best_order_text",
            "score_metric",
            "input_order_score",
            "avg_gap_factor",
            "avg_probability_weight",
            "run_id",
        ]
        if c in filtered.columns
    ]
    with st.expander("간단 원본 미리보기"):
        preview_df = filtered[preview_cols].head(40).copy()
        if "log_type" in preview_df.columns:
            preview_df["log_type"] = preview_df["log_type"].map(_log_type_label)
        st.dataframe(preview_df, use_container_width=True, hide_index=True)





def _apply_simulation_count(project_dir: Path, new_count: int) -> None:
    sanitized = _sanitize_simulation_count(new_count)
    st.session_state.simulation_count = sanitized
    st.session_state.simulation_notice = f"시뮬레이션 규모가 {sanitized:,}회로 변경되었습니다. 다음 추천부터 바로 반영됩니다."
    _persist_runtime_state(project_dir)


def _render_simulation_form(project_dir: Path, form_key: str, caption_text: str) -> None:
    with st.form(form_key, clear_on_submit=False):
        current_count = _current_simulation_count()
        simulation_count = st.number_input(
            "시뮬레이션 규모",
            min_value=1000,
            max_value=50000,
            step=500,
            value=current_count,
            help="추천 계산 반복 횟수입니다. 값이 커질수록 탐색 폭은 넓어지지만 응답 시간도 함께 늘어납니다.",
        )
        password = st.text_input("변경 비밀번호", type="password", key=f"{form_key}_password")
        submitted = st.form_submit_button("시뮬레이션 규모 적용", use_container_width=True)
        if submitted:
            if not password:
                st.warning("변경 비밀번호를 먼저 입력해 주세요.")
            elif password != SIMULATION_EDIT_PASSWORD:
                st.error("비밀번호가 올바르지 않습니다.")
            else:
                _apply_simulation_count(project_dir, int(simulation_count))
                st.rerun()
    st.caption(caption_text)


def _render_simulation_control(project_dir: Path, variant: str = SIMULATION_PANEL_VARIANT) -> None:
    current_count = _current_simulation_count()
    if st.session_state.get("simulation_notice"):
        st.success(st.session_state.simulation_notice)
        st.session_state.simulation_notice = None

    st.markdown("#### 시뮬레이션 규모 설정")
    
    if variant == "A":
        left, right = st.columns([1.08, 0.92])
        with left:
            st.markdown(
                f"""
                <div class="sim-card">
                    <div class="eyebrow">Simulation Status</div>
                    <h4>현재 운영 규모를 먼저 확인한 뒤 변경</h4>
                    <p>시뮬레이션 횟수가 높을수록 통계적 유의성은 상승하지만, 브라우저의 응답 속도가 느려질 수 있습니다. 일반적인 분석에는 5,000~10,000회 설정을 권장합니다.</p>
                    <span class="sim-value">{current_count:,}회</span>
                    <div class="sim-badge-row">
                        <span class="sim-badge">권장 시작값 · 5,000회</span>                        
                    </div>
                    <ul class="sim-meta-list">
                        <li>규모를 높이는 것은 "데이터의 해상도"를 높이는 것과 같습니다.</li>
                        <li>해상도가 너무 높으면 오히려 노이즈(데이터 왜곡)가 발생할 수 있습니다.</li>
                        <li>무조건 높이는 것보다, 최근 데이터(Short-term)와 과거 데이터(Long-term)의 가중치를 조절하는 것이 더 정밀한 결과를 도출할 수 있다</li>
                    </ul>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with right:
            st.markdown(
                """
                <div class="unlock-shell">
                    <div class="title">🔐 시뮬레이션 규모 변경 안내</div>
                    <div class="desc">비밀번호를 넣어야만 시뮬레이션 규모를 변경할수 있습니다.</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            _render_simulation_form(project_dir, "simulation_form_a", "변경 후에는 다음 추천 실행부터 새 규모가 반영됩니다.")
        return

    if variant == "B":
        st.markdown(
            f"""
            <div class="sim-banner">
                <div class="eyebrow">History Control Deck</div>
                <h4>분석 화면에서 바로 읽는 시뮬레이션 규모 배너</h4>
                <p>현재 적용 중인 규모를 배너에서 먼저 확인하고, 하단 카드에서 변경 이유와 보안 절차를 나눠 읽을 수 있게 정리했습니다.</p>
                <div class="sim-mini-grid">
                    <div class="sim-mini-item">
                        <div class="sim-mini-label">현재 적용 규모</div>
                        <div class="sim-mini-value">{current_count:,}회</div>
                    </div>
                    <div class="sim-mini-item">
                        <div class="sim-mini-label">권장 기준</div>
                        <div class="sim-mini-value">5,000회</div>
                    </div>
                    <div class="sim-mini-item">
                        <div class="sim-mini-label">변경 보안</div>
                        <div class="sim-mini-value">PW 1221</div>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown(
                f"""
                <div class="sim-card">
                    <div class="eyebrow">Current State</div>
                    <h4>현재 값</h4>
                    <p>현재 추천 계산에 쓰이는 반복 횟수입니다.</p>
                    <span class="sim-value">{current_count:,}회</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with col2:
            st.markdown(
                """
                <div class="sim-card">
                    <div class="eyebrow">Guide</div>
                    <h4>변경 가이드</h4>
                    <p>빠른 응답이 중요하면 3,000~5,000회, 탐색 폭을 넓히려면 7,500~10,000회 수준이 무난합니다.</p>
                    <div class="sim-form-caption">로그 파일은 유지되고 설정값만 변경됩니다.</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with col3:
            st.markdown(
                """
                <div class="unlock-shell">
                    <div class="title">🔐 보안 변경</div>
                    <div class="desc">원본 데이터 확인과 비슷한 톤으로, 비밀번호 인증 뒤에만 값 변경이 되도록 구성했습니다.</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            _render_simulation_form(project_dir, "simulation_form_b", "저장 즉시 런타임 설정에 반영되며 로그 이력은 유지됩니다.")
        return

    st.markdown(
        f"""
        <div class="sim-console">
            <div class="sim-console-top">
                <div>
                    <div class="eyebrow">Simulation Console</div>
                    <h4>로그 분석 화면 안에 붙는 일체형 관리 콘솔</h4>
                    <p>현재 규모 확인과 보안 변경 흐름을 하나의 콘솔 안에 압축해, 운영자가 빠르게 읽고 즉시 바꿀 수 있도록 설계했습니다.</p>
                </div>
                <div class="sim-console-kpis">
                    <div class="sim-console-kpi"><span>현재 규모</span><b>{current_count:,}회</b></div>
                    <div class="sim-console-kpi"><span>보안 비밀번호</span><b>1221</b></div>
                    <div class="sim-console-kpi"><span>저장 방식</span><b>설정값만 반영</b></div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    _render_simulation_form(project_dir, "simulation_form_c", "패턴 추천·확률 추천 모두 동일한 시뮬레이션 규모를 공유합니다.")

def _render_analysis_view(summary: dict, project_dir: Path, report_dir: Path, predictor: "LottoPredictor", latest_source_round: int | None = None):
    history_df = load_combined_log_history(project_dir)
    status_df = build_log_status_table(project_dir)
    matched_df = _read_report_csv(report_dir, "match")
    threshold_df = _read_report_csv(report_dir, "threshold")
    timeseries_df = _read_report_csv(report_dir, "timeseries")

    st.markdown("### 로그 분석 · 히스토리")
    st.caption("저장 로그를 일자·주간·월간 기준으로 바로 탐색할 수 있게 정리했습니다. 달력으로 날짜를 고르고 상세 기록까지 내려가며 확인할 수 있습니다.")

    total_logs = int(len(history_df)) if not history_df.empty else 0
    last_saved = "-"
    if not history_df.empty and history_df["timestamp_kst"].replace("-", pd.NA).dropna().any():
        last_saved = history_df["timestamp_kst"].replace("-", pd.NA).dropna().iloc[0]

    _render_stats_grid(
        st,
        _build_home_overview_items(predictor, latest_source_round)
        + [
            ("전체 로그", f"{total_logs:,}", "통합 히스토리에 저장된 전체 로그 수입니다."),
            ("최근 저장", last_saved, "가장 최근에 저장된 로그 시각입니다."),
            ("매칭 로그", f"{summary.get('resolved_match_rows', 0):,}", "실제 당첨 번호와 비교 가능한 로그 수입니다."),
            ("시계열 행", f"{summary.get('time_series_rows', 0):,}", "추이 분석에 사용된 집계 행 수입니다."),
        ],
    )

    threshold = summary.get("recommended_threshold")
    if threshold:
        st.success(
            f"추천 임계값 안내 · 점수 {threshold['threshold']} 이상 · 샘플 {threshold['samples']}건 · 3개 이상 적중 비율 {threshold['hit_3_plus_rate']:.2%}"
        )
    else:
        st.info("아직 실제 당첨번호와 연결된 로그가 충분하지 않아 추천 임계값은 계산되지 않았습니다.")

    _render_simulation_control(project_dir, SIMULATION_PANEL_VARIANT)

    _render_calendar_history_section(history_df)

    tab_pred, tab_prob, tab_manual, tab_analysis = st.tabs(
        ["패턴 분석 로그", "확률 분석 로그", "수동 점수 로그", "분석 요약 로그"]
    )

    with tab_pred:
        pred_df = history_df[history_df["log_type"] == "prediction"].copy() if not history_df.empty else pd.DataFrame()
        _render_single_log_tab(pred_df, "패턴 분석 로그", "아직 저장된 패턴 분석 로그가 없습니다.")

    with tab_prob:
        prob_df = history_df[history_df["log_type"] == "probability"].copy() if not history_df.empty else pd.DataFrame()
        _render_single_log_tab(prob_df, "확률 분석 로그", "아직 저장된 확률 분석 로그가 없습니다.")

    with tab_analysis:
        left, right = st.columns([1.0, 1.05])
        with left:
            st.markdown(
                f"""
                <div class="soft-panel">
                    <h4>분석 기준 요약</h4>
                    <p>최신 원본 회차 <b>{summary.get('latest_source_round')}</b><br>
                    다음 예측 대상 회차 <b>{summary.get('next_target_round')}</b><br>
                    생성 시각(UTC) <b>{summary.get('generated_at_utc')}</b></p>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if not status_df.empty:
                status_view = status_df.copy()
                status_view["log_type"] = status_view["log_type"].map(_log_type_label)
                status_view = status_view.rename(
                    columns={
                        "log_type": "로그유형",
                        "file_name": "파일명",
                        "records": "저장건수",
                        "size_kb": "크기(KB)",
                        "last_saved_at": "마지막 저장시각(UTC)",
                    }
                )
                st.dataframe(
                    status_view[["로그유형", "파일명", "저장건수", "크기(KB)", "마지막 저장시각(UTC)"]],
                    use_container_width=True,
                    hide_index=True,
                )
        with right:
            st.markdown("#### 분석 요약")
            _render_analysis_summary_detail(summary)

        sub1, sub2 = st.columns(2)
        with sub1:
            st.markdown("#### 적중 매칭")
            if matched_df.empty:
                st.info("실제 당첨 번호와 연결된 예측 로그가 아직 없습니다.")
            else:
                st.dataframe(matched_df.head(120), use_container_width=True, hide_index=True)
        with sub2:
            st.markdown("#### 임계값 분석")
            if threshold_df.empty:
                st.info("임계값 분석용 매칭 로그가 아직 부족합니다.")
            else:
                st.dataframe(threshold_df, use_container_width=True, hide_index=True)

        if not timeseries_df.empty:
            st.markdown("#### 날짜별 평균 점수 / gap 계수 추이")
            chart_left, chart_right = st.columns(2)
            with chart_left:
                score_pivot = timeseries_df.pivot(index="date", columns="log_type", values="avg_score")
                score_pivot = score_pivot.rename(columns=_log_type_label)
                st.line_chart(score_pivot, use_container_width=True)
            with chart_right:
                gap_pivot = timeseries_df.pivot(index="date", columns="log_type", values="avg_gap_factor")
                gap_pivot = gap_pivot.rename(columns=_log_type_label)
                st.line_chart(gap_pivot, use_container_width=True)

        with st.expander("파일 다운로드"):
            dl1, dl2, dl3 = st.columns(3)
            with dl1:
                _render_download_button(project_dir / "logs" / LOG_FILE_MAP["prediction"], "패턴 분석 로그 다운로드", "application/json", "dl_pred")
                _render_download_button(project_dir / "logs" / LOG_FILE_MAP["probability"], "확률분석로그 다운로드", "application/json", "dl_prob")
            with dl2:
                _render_download_button(project_dir / "logs" / LOG_FILE_MAP["manual"], "수동번호점수로그 다운로드", "application/json", "dl_manual")
                _render_download_button(project_dir / "logs" / LOG_FILE_MAP["analysis"], "분석요약로그 다운로드", "application/json", "dl_analysis")
                _render_download_button(project_dir / "logs" / "lotto_history.db", "lotto_history.db 다운로드", "application/octet-stream", "dl_history_db")
            with dl3:
                _render_download_button(report_dir / REPORT_FILE_MAP["match"], "prediction_actual_match.csv", "text/csv", "dl_match")
                _render_download_button(report_dir / REPORT_FILE_MAP["threshold"], "threshold_analysis.csv", "text/csv", "dl_threshold")
                _render_download_button(report_dir / REPORT_FILE_MAP["timeseries"], "score_timeseries.csv", "text/csv", "dl_timeseries")
                _render_download_button(report_dir / REPORT_FILE_MAP["daily_summary"], "daily_log_summary.csv", "text/csv", "dl_daily_summary")
                _render_download_button(report_dir / REPORT_FILE_MAP["weekly_summary"], "weekly_log_summary.csv", "text/csv", "dl_weekly_summary")
                _render_download_button(report_dir / REPORT_FILE_MAP["monthly_summary"], "monthly_log_summary.csv", "text/csv", "dl_monthly_summary")
                _render_download_button(report_dir / REPORT_FILE_MAP["weekday_summary"], "weekday_log_summary.csv", "text/csv", "dl_weekday_summary")
                _render_download_button(report_dir / REPORT_FILE_MAP["log_type_summary"], "log_type_summary.csv", "text/csv", "dl_log_type_summary")

    with tab_manual:
        manual_df = history_df[history_df["log_type"] == "manual"].copy() if not history_df.empty else pd.DataFrame()
        _render_single_log_tab(manual_df, "수동 입력 점수 확인 로그", "아직 저장된 수동 번호 점수 로그가 없습니다.")


def _render_data_gate(project_dir: Path):
    data_access_granted = bool(st.session_state.get("data_access_granted", False))
    gate_title = "원본 데이터 보기 해제" if data_access_granted else "원본 데이터 접근 확인"
    gate_desc = (
        "비밀번호를 입력하면 원본 데이터 보기 권한이 해제됩니다."
        if data_access_granted
        else "비밀번호를 입력하면 원본 데이터 내용을 확인할 수 있습니다."
    )
    submit_label = "원본 데이터 보기 해제" if data_access_granted else "원본 데이터 열기"

    st.markdown(
        f"""
        <div class="soft-panel">
            <h4>{gate_title}</h4>
            <p>{gate_desc}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.form("data_check_password_form", clear_on_submit=True):
        pw = st.text_input("원본 데이터 비밀번호", type="password", key="data_check_password_input")
        submitted = st.form_submit_button(submit_label, use_container_width=True)

        if submitted:
            if pw == DATA_CHECK_PASSWORD:
                st.session_state.data_access_granted = not data_access_granted
                st.session_state.show_data_gate = False
                st.session_state.view = "show_data" if st.session_state.data_access_granted else ""
                _persist_runtime_state(project_dir)
                st.rerun()
            elif pw:
                st.error("비밀번호가 올바르지 않습니다.")
            else:
                st.warning("원본 데이터 비밀번호를 먼저 입력해 주세요.")


def main():
    st.set_page_config(page_title=TITLE, layout="wide")
    disable_copy()

    project_dir = Path(__file__).resolve().parent
    _init_session_state(project_dir)
    excel_path = project_dir / "lotto.xlsx"
    _, report_dir = ensure_runtime_dirs(project_dir)

    if not st.session_state.auth:
        st.markdown(
            f"""
            <div class="hero-card">
                <div class="hero-eyebrow">보안 입장</div>
                <h1 class="hero-title">{TITLE}</h1>
                <p class="hero-subtitle">입장 비밀번호를 입력하면 분석 대시보드로 이동합니다.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        today_pw = _today_password()
        pw_in = st.text_input("입장 비밀번호", type="password")
        if st.button("입장하기", use_container_width=True) or (pw_in == today_pw):
            if pw_in == today_pw:
                st.session_state.auth = True
                st.rerun()
            elif pw_in:
                st.error("입장 비밀번호가 올바르지 않습니다.")
        return

    if not os.path.exists(excel_path):
        st.error("lotto.xlsx 파일이 필요합니다.")
        return
    excel_cache_token = _file_cache_token(excel_path)
    predictor = _get_cached_predictor(str(excel_path), excel_cache_token)
    current_source_round = _current_source_round(excel_path, excel_cache_token, predictor)

    _render_hero(predictor)

    _render_home_guide_studio()

    refresh_notice = st.session_state.pop("source_data_refresh_notice", None)
    if isinstance(refresh_notice, dict) and refresh_notice.get("message"):
        level = str(refresh_notice.get("level") or "info").lower()
        if level == "success":
            st.success(refresh_notice["message"])
        elif level == "error":
            st.error(refresh_notice["message"])
        else:
            st.info(refresh_notice["message"])

    p_lock = (not st.session_state.unlock_granted) and st.session_state.counts["prediction"] >= LOCK_LIMIT
    pr_lock = (not st.session_state.unlock_granted) and st.session_state.counts["probability"] >= LOCK_LIMIT

    action_col1, action_col2 = st.columns(2)
    with action_col1:
        st.markdown("<div id='pattern-action-anchor'></div>", unsafe_allow_html=True)
        _render_feature_card(
            "feature-green",
            "추천 시작",
            "패턴 추천 받기",
            "포지션·gap·pair 가중치를 함께 반영합니다. 처음이라면 이 버튼부터 눌러 보세요.",
        )
        if st.button(
            "패턴 추천 바로 받기" + (" (잠김)" if p_lock else ""),
            key="home_predict_btn",
            disabled=p_lock,
            use_container_width=True,
            type="primary",
        ):
            with st.spinner("분석 중입니다. 패턴 가중치 기반 추천을 계산하고 있습니다..."):
                runtime_simulation_count = _current_simulation_count()
                results = predictor.predict(simulation_count=runtime_simulation_count)
                if not st.session_state.unlock_granted:
                    st.session_state.counts["prediction"] += 1
                st.session_state.predict_results = results
                log_prediction_results(
                    base_dir=project_dir,
                    excel_path=excel_path,
                    predictor=predictor,
                    results=results,
                    log_type="prediction",
                    simulation_count=runtime_simulation_count,
                )
                _persist_runtime_state(project_dir)
            st.session_state.view = "predict"
            st.session_state.show_data_gate = False
        if st.session_state.unlock_granted:
            st.caption("즉시 실행 가능합니다.")
        else:
            st.caption("잠김 상태가 되면 우측 하단의 사용 제한 해제 메뉴를 이용하세요.")

    with action_col2:
        st.markdown("<div id='probability-action-anchor'></div>", unsafe_allow_html=True)
        _render_feature_card(
            "feature-purple",
            "비교 추천",
            "확률 추천 받기",
            "전체 빈도와 미출현 구간 확률을 우선 반영합니다. 패턴 추천과 비교할 때 유용합니다.",
        )
        if st.button(
            "확률 추천 바로 받기" + (" (잠김)" if pr_lock else ""),
            key="home_probability_btn",
            disabled=pr_lock,
            use_container_width=True,
            type="primary",
        ):
            with st.spinner("분석 중입니다. 확률 기반 추천을 계산하고 있습니다..."):
                runtime_simulation_count = _current_simulation_count()
                results = predictor.predict_probability_only(simulation_count=runtime_simulation_count)
                if not st.session_state.unlock_granted:
                    st.session_state.counts["probability"] += 1
                st.session_state.probability_results = results
                log_prediction_results(
                    base_dir=project_dir,
                    excel_path=excel_path,
                    predictor=predictor,
                    results=results,
                    log_type="probability",
                    simulation_count=runtime_simulation_count,
                )
                _persist_runtime_state(project_dir)
            st.session_state.view = "prob_only"
            st.session_state.show_data_gate = False
        if st.session_state.unlock_granted:
            st.caption("즉시 실행 가능합니다.")
        else:
            st.caption("잠김 상태가 되면 우측 하단의 사용 제한 해제 메뉴를 이용하세요.")

    st.markdown(
        """
        <div class="section-shell">
            <h3>수동 번호 점수 확인</h3>
            <p>직접 고른 번호 6개를 입력하면 입력 순서 점수, 최적 순서 점수, 확률 점수를 같은 기준으로 다시 비교할 수 있습니다.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    pending_manual_numbers = st.session_state.pop("pending_manual_numbers", None)
    if pending_manual_numbers:
        for idx, number in enumerate(pending_manual_numbers):
            st.session_state[f"mn{idx}"] = int(number)
    with st.form("manual_score_form", clear_on_submit=False):
        top_inputs = st.columns(3)
        bottom_inputs = st.columns(3)
        input_cols = [*top_inputs, *bottom_inputs]
        m_nums = [
            input_cols[i].number_input(f"번호 {i+1}", 1, 45, value=None, key=f"mn{i}")
            for i in range(6)
        ]
        button_col1, button_col2 = st.columns(2)
        with button_col1:
            solo_submitted = st.form_submit_button(
                "나혼자 당첨",
                use_container_width=True,
            )
        with button_col2:
            submitted = st.form_submit_button(
                "점수 계산하기",
                use_container_width=True,
            )

        if solo_submitted:
            current_manual_numbers = [st.session_state.get(f"mn{i}") for i in range(6)]
            previous_numbers = [int(n) for n in current_manual_numbers] if all(n is not None for n in current_manual_numbers) else None
            generated_numbers = _generate_anti_pattern_manual_numbers(previous_numbers=previous_numbers)
            st.session_state.pending_manual_numbers = generated_numbers
            st.session_state.manual_result = None
            st.session_state.view = ""
            st.session_state.show_data_gate = False
            st.rerun()

        if submitted:
            if not all(n is not None for n in m_nums):
                st.warning("6개의 번호를 모두 입력해 주세요.")
            elif len(set(m_nums)) != 6:
                st.warning("중복 없는 6개의 번호를 입력하세요.")
            else:
                result = predictor.score_manual_combination(m_nums)
                st.session_state.manual_result = result
                log_manual_score(
                    base_dir=project_dir,
                    excel_path=excel_path,
                    predictor=predictor,
                    numbers=m_nums,
                    result=result,
                )
                _persist_runtime_state(project_dir)
                st.session_state.view = "manual"
                st.session_state.show_data_gate = False

    row2_col1, row2_col2, row2_col3 = st.columns(3)
    with row2_col1:
        st.markdown(
            """
            <div class="soft-panel">
                <h4>로그 분석 · 히스토리</h4>
                <p>저장된 추천 이력과 적중 매칭, 임계값 변화를 한 번에 확인합니다.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("로그 분석 · 히스토리", key="home_analysis_btn", use_container_width=True):
            with st.spinner("분석 중입니다. 분석 · 히스토리를 생성하고 있습니다..."):
                st.session_state.analysis_summary = _get_fresh_analysis_summary(
                    project_dir,
                    excel_path,
                    excel_cache_token,
                    predictor,
                    force_refresh=True,
                )
            st.session_state.view = "analysis"
            st.session_state.show_data_gate = False
    with row2_col2:
        st.markdown(
            """
            <div class="soft-panel">
                <h4>원본 데이터</h4>
                <p>비밀번호를 입력하면 lotto.xlsx 원본 데이터를 확인하고 내려받을 수 있습니다.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("원본 데이터 보기", key="home_data_btn", use_container_width=True):
            with st.spinner("최신 회차를 확인하고 원본 데이터를 준비하고 있습니다..."):
                _refresh_source_data(excel_path)
            if st.session_state.data_access_granted:
                st.session_state.view = "show_data"
                st.session_state.show_data_gate = False
            else:
                st.session_state.show_data_gate = True
                st.session_state.view = "data_gate"
            st.rerun()
    with row2_col3:
        limit_status_title = "사용 제한" if st.session_state.unlock_granted else "사용 제한 해제"
        limit_status_desc = (
            "현재는 무제한 상태입니다. 다시 제한 모드로 전환하려면 비밀번호를 입력해 주세요."
            if st.session_state.unlock_granted
            else "패턴 추천/확률 추천의 3회 제한을 해제하려면 비밀번호를 입력해 주세요."
        )
        st.markdown(
            f"""
            <div class="soft-panel">
                <h4>{limit_status_title}</h4>
                <p>{limit_status_desc}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button(limit_status_title, key="home_unlock_btn", use_container_width=True):
            st.session_state.unlock_mode = not st.session_state.unlock_mode


    if st.session_state.unlock_mode:
        limit_toggle_title = "🔒 사용 제한 적용" if st.session_state.unlock_granted else "🔓 사용 제한 해제"
        limit_toggle_desc = (
            "현재 무제한 상태입니다. 비밀번호가 맞으면 제한 모드로 다시 전환됩니다."
            if st.session_state.unlock_granted
            else "현재 제한 모드입니다. 비밀번호가 맞으면 무제한 상태로 전환됩니다."
        )
        limit_submit_label = "사용 제한 적용" if st.session_state.unlock_granted else "사용 제한 해제"
        password_label = "비밀번호 입력"
        st.markdown(
            f"""
            <div class="unlock-shell">
                <div class="title">{limit_toggle_title}</div>
                <div class="desc">{limit_toggle_desc}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        with st.form("unlock_form", clear_on_submit=True):
            ent_code = st.text_input(password_label, type="password", key="unlock_input_field")
            unlock_submitted = st.form_submit_button(limit_submit_label, use_container_width=True)

            if unlock_submitted:
                if ent_code == UNLOCK_PASSWORD:
                    st.session_state.counts["prediction"] = 0
                    st.session_state.counts["probability"] = 0
                    st.session_state.unlock_granted = not st.session_state.unlock_granted
                    st.session_state.unlock_mode = False
                    _persist_runtime_state(project_dir)
                    if st.session_state.unlock_granted:
                        st.success("사용 제한이 해제되었습니다. 패턴 추천과 확률 추천을 무제한으로 사용할 수 있습니다.")
                    else:
                        st.success("사용 제한이 다시 적용되었습니다. 패턴 추천과 확률 추천은 각각 3회씩 사용할 수 있습니다.")
                    st.rerun()
                elif ent_code:
                    st.error("비밀번호가 올바르지 않습니다.")

    res = st.container()
    v = st.session_state.get("view", "")

    if v == "data_gate" and not st.session_state.data_access_granted:
        with res:
            _render_data_gate(project_dir)

    elif v == "show_data":
        with res:
            res.markdown("### lotto.xlsx 원본 데이터")
            if st.session_state.data_access_granted:
                control_col1, control_col2, control_col3 = st.columns([2, 2, 1])
                with control_col2:
                    if st.button("최신 데이터 다시 확인", key="refresh_show_data_btn", use_container_width=True):
                        with st.spinner("최신 회차를 다시 확인하고 있습니다..."):
                            _refresh_source_data(excel_path)
                        st.rerun()
                with control_col3:
                    if st.button("원본 데이터 보기 해제", key="data_access_toggle_btn", use_container_width=True):
                        st.session_state.show_data_gate = not st.session_state.show_data_gate
                if st.session_state.show_data_gate:
                    _render_data_gate(project_dir)
            if not st.session_state.data_access_granted:
                res.warning("원본 데이터 확인 권한이 없습니다.")
            else:
                if not excel_path.exists():
                    res.error(f"파일을 찾을 수 없습니다: {excel_path.name}")
                else:
                    try:
                        df_display = _read_excel_cached(str(excel_path), excel_cache_token).copy()
                        # 컬럼 필터링 안전하게 처리
                        cols_to_drop = ["수집페이지", "출처"]
                        existing_drops = [c for c in cols_to_drop if c in df_display.columns]
                        if existing_drops:
                            df_display = df_display.drop(columns=existing_drops)
                        
                        latest_round_display = "-"
                        if "회차" in df_display.columns and not df_display.empty:
                            latest_round_display = f"{int(pd.to_numeric(df_display['회차'], errors='coerce').dropna().max())}회"

                        _render_stats_grid(
                            res,
                            [
                                ("현재 데이터 행 수", f"{len(df_display):,}", "lotto.xlsx에 들어 있는 전체 행 수입니다."),
                                ("최신 회차", latest_round_display, "원본 데이터 보기 진입 시점 기준으로 다시 확인한 최신 회차입니다."),
                                ("보안 상태", "인증 완료", "원본 데이터 보기 권한이 확인된 상태입니다."),
                            ],
                        )

                        res.dataframe(df_display, use_container_width=True, hide_index=True)
                        _render_download_button(excel_path, "lotto.xlsx 다운로드", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "dl_excel_btn")
                    except Exception as e:
                        res.error(f"데이터를 읽는 중 오류가 발생했습니다: {e}")

    elif v == "summary":
        pass

    elif v == "predict":
        with res:
            results = st.session_state.get("predict_results") or []
            _render_result_block(
                res,
                title="",
                intro="포지션, gap, pair 시너지를 함께 반영한 상위 후보입니다.",
                results=results,
                predictor=predictor,
                probability_only=False,
            )
            res.success("패턴 추천 결과를 logs/prediction_log.jsonl 파일에 저장했습니다.")

    elif v == "prob_only":
        with res:
            results = st.session_state.get("probability_results") or []
            _render_result_block(
                res,
                title="",
                intro="전체 빈도와 구간 확률에 집중한 상위 후보입니다.",
                results=results,
                predictor=predictor,
                probability_only=True,
            )
            res.success("확률 추천 결과를 logs/probability_log.jsonl 파일에 저장했습니다.")

    elif v == "manual":
        with res:
            ret = st.session_state.get("manual_result")
            if ret:
                res.markdown(
                    f"""
                    <div class="result-card">
                        <h4>입력 번호 { _format_number_sequence(ret['sorted']) }</h4>
                        <div class="number-badges">{_format_ball_badges(ret['sorted'])}</div>
                        <p><b>입력 순서</b> : {_format_number_sequence(ret.get('input_order', ret['sorted']))}</p>
                        <p><b>입력 순서 점수</b> : {ret.get('input_order_score', ret['best_score'])}</p>
                        <p><b>최적 순서</b> : {_format_number_sequence(ret.get('best_order', ret['sorted']))}</p>
                        <p><b>최고 순서 점수</b> : {ret['best_score']}</p>
                        <p><b>평균 점수</b> : {ret['average_score']}</p>
                        <p><b>확률 점수</b> : {ret['probability_score']}</p>
                        <p><b>평균 gap 계수</b> : {predictor.average_gap_factor(ret['sorted']):.6f}</p>
                        <p><b>평균 확률 가중치</b> : {predictor.average_probability_weight(ret['sorted']):.6f}</p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                _render_number_detail_cards(res, predictor, ret["sorted"])
                res.success("수동 점수 결과를 logs/manual_score_log.jsonl 파일에 저장했습니다.")

    elif v == "analysis":
        with res:
            summary = _get_fresh_analysis_summary(project_dir, excel_path, excel_cache_token, predictor)
            _render_analysis_view(summary, project_dir, report_dir, predictor, current_source_round)


if __name__ == "__main__":
    main()
