from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

KOREAN_WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]


def _safe_date(value: str):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        return None


# enrich 결과에만 존재하는 표식 컬럼들. 이미 enrich된 df가 다시 들어오면
# (build_period_summary/build_weekday_summary/build_log_type_summary 및
#  analyze_logs 에서 enrich된 df를 그대로 넘기는 경우) 무거운 재파싱을 생략한다.
_ENRICHED_MARKER_COLS = ("is_scored_log", "score_zscore", "date_obj")


def enrich_history_dataframe(history_df: pd.DataFrame) -> pd.DataFrame:
    if history_df.empty:
        return history_df.copy()

    # [성능] 멱등 처리: 이미 enrich된 데이터프레임이면 타임스탬프 재파싱·
    # isocalendar·zscore 계산을 반복하지 않는다. (대용량에서 enrich 1회 ~1.5초가
    # 집계마다 중복 호출되어 로그분석 진입이 수 초~십수 초 느려지던 주범)
    if all(col in history_df.columns for col in _ENRICHED_MARKER_COLS):
        return history_df.copy()

    df = history_df.copy()
    if "timestamp" not in df.columns:
        return df

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    valid_ts = df["timestamp"].notna()
    # [성능] timestamp_kst/date_kst/week_kst/month_kst 는 load_combined_log_history 의
    # _postprocess_history_df 가 이미 동일 로직으로 계산해 둔다. 이미 있으면 재계산을
    # 생략하고, enrich 에서만 필요한 weekday_kst 만 추가로 만든다(동일 결과, 대용량 가속).
    _kst_ready = all(c in df.columns for c in ["timestamp_kst", "date_kst", "week_kst", "month_kst"])
    if valid_ts.any():
        ts_kst = df.loc[valid_ts, "timestamp"].dt.tz_convert("Asia/Seoul")
        if not _kst_ready:
            df.loc[valid_ts, "timestamp_kst"] = ts_kst.dt.strftime("%Y-%m-%d %H:%M:%S")
            df.loc[valid_ts, "date_kst"] = ts_kst.dt.strftime("%Y-%m-%d")
            iso = ts_kst.dt.isocalendar()
            df.loc[valid_ts, "week_kst"] = iso["year"].astype(str) + "-W" + iso["week"].astype(str).str.zfill(2)
            df.loc[valid_ts, "month_kst"] = ts_kst.dt.strftime("%Y-%m")
        df.loc[valid_ts, "weekday_kst"] = ts_kst.dt.weekday.map(lambda idx: KOREAN_WEEKDAYS[idx])

    for period_col in ["timestamp_kst", "date_kst", "week_kst", "month_kst", "weekday_kst"]:
        if period_col not in df.columns:
            df[period_col] = "-"
        df[period_col] = df[period_col].fillna("-")

    for numeric_col in [
        "score_metric",
        "score",
        "best_score",
        "average_score",
        "probability_score",
        "input_order_score",
        "avg_gap_factor",
        "avg_probability_weight",
        "target_round",
        "source_round",
        "candidate_rank",
    ]:
        if numeric_col in df.columns:
            df[numeric_col] = pd.to_numeric(df[numeric_col], errors="coerce")

    if "run_id" not in df.columns:
        df["run_id"] = "-"
    if "record_uid" not in df.columns:
        df["record_uid"] = "-"

    score_metric = pd.to_numeric(df.get("score_metric"), errors="coerce")
    if score_metric is None or len(score_metric) != len(df):
        score_metric = pd.Series(index=df.index, dtype=float)
    df["score_metric"] = score_metric
    df["is_scored_log"] = df["score_metric"].notna()
    df["date_obj"] = df["date_kst"].map(_safe_date)
    df["score_zscore"] = pd.Series(index=df.index, dtype=float)

    scored_mask = df["is_scored_log"]
    if scored_mask.any():
        score_std = df.loc[scored_mask, "score_metric"].std(ddof=0)
        if pd.notna(score_std) and float(score_std) > 0:
            score_mean = df.loc[scored_mask, "score_metric"].mean()
            df.loc[scored_mask, "score_zscore"] = (
                (df.loc[scored_mask, "score_metric"] - score_mean) / score_std
            ).round(4)

    return df


def _empty_period_summary(period_col: str, include_group: bool = True) -> pd.DataFrame:
    base_cols = [period_col]
    if include_group:
        base_cols.append("log_type")
    base_cols.extend(
        [
            "logs",
            "unique_runs",
            "unique_target_rounds",
            "scored_logs",
            "score_coverage",
            "avg_score",
            "median_score",
            "score_std",
            "best_score",
            "p25_score",
            "p75_score",
            "avg_gap_factor",
            "avg_probability_weight",
        ]
    )
    return pd.DataFrame(columns=base_cols)


def build_period_summary(history_df: pd.DataFrame, period_col: str, *, group_col: str | None = "log_type") -> pd.DataFrame:
    if history_df.empty or period_col not in history_df.columns:
        return _empty_period_summary(period_col, include_group=bool(group_col))

    df = enrich_history_dataframe(history_df)
    valid = df[df[period_col].notna() & (df[period_col] != "-")].copy()
    if valid.empty:
        return _empty_period_summary(period_col, include_group=bool(group_col))

    group_keys = [period_col]
    if group_col:
        group_keys.append(group_col)

    # [성능] 그룹별 파이썬 루프(그룹당 pd.to_numeric + 통계 10여 개 반복)를
    # groupby.agg 로 벡터화한다. 값·반올림·정렬 결과는 기존 루프 버전과 동일하며,
    # 대용량(수천 그룹)에서 집계 시간을 크게 단축한다.
    work = pd.DataFrame({key: valid[key] for key in group_keys})
    work["_score"] = pd.to_numeric(valid.get("score_metric"), errors="coerce")
    work["_tr"] = pd.to_numeric(valid.get("target_round"), errors="coerce")
    work["_gap"] = pd.to_numeric(valid.get("avg_gap_factor"), errors="coerce")
    work["_prob"] = pd.to_numeric(valid.get("avg_probability_weight"), errors="coerce")
    run_series = valid.get("run_id", pd.Series("-", index=valid.index)).replace("-", pd.NA)
    work["_run"] = run_series

    grouped = work.groupby(group_keys, dropna=False)
    logs = grouped.size()
    scored = grouped["_score"].count()
    summary = pd.DataFrame(
        {
            "logs": logs.astype(int),
            "unique_runs": grouped["_run"].nunique().astype(int),
            "unique_target_rounds": grouped["_tr"].nunique().astype(int),
            "scored_logs": scored.astype(int),
            "score_coverage": (scored / logs).round(4),
            "avg_score": grouped["_score"].mean().round(4),
            "median_score": grouped["_score"].median().round(4),
            "score_std": grouped["_score"].std(ddof=0).round(4),
            "best_score": grouped["_score"].max().round(4),
            "p25_score": grouped["_score"].quantile(0.25).round(4),
            "p75_score": grouped["_score"].quantile(0.75).round(4),
            "avg_gap_factor": grouped["_gap"].mean().round(4),
            "avg_probability_weight": grouped["_prob"].mean().round(4),
        }
    ).reset_index()
    ordered_cols = [period_col] + ([group_col] if group_col else []) + [
        "logs", "unique_runs", "unique_target_rounds", "scored_logs", "score_coverage",
        "avg_score", "median_score", "score_std", "best_score", "p25_score", "p75_score",
        "avg_gap_factor", "avg_probability_weight",
    ]
    summary = summary[ordered_cols]
    if summary.empty:
        return _empty_period_summary(period_col, include_group=bool(group_col))

    sort_cols = [period_col]
    ascending = [False]
    if group_col and group_col in summary.columns:
        sort_cols.append(group_col)
        ascending.append(True)
    summary = summary.sort_values(sort_cols, ascending=ascending).reset_index(drop=True)
    return summary


def build_log_type_summary(history_df: pd.DataFrame) -> pd.DataFrame:
    if history_df.empty:
        return _empty_period_summary("log_type", include_group=False)
    summary = build_period_summary(history_df, "log_type", group_col=None)
    if summary.empty:
        return summary
    return summary.sort_values(["logs", "avg_score"], ascending=[False, False], na_position="last").reset_index(drop=True)


def build_weekday_summary(history_df: pd.DataFrame) -> pd.DataFrame:
    if history_df.empty:
        return _empty_period_summary("weekday_kst", include_group=True)
    df = enrich_history_dataframe(history_df)
    summary = build_period_summary(df, "weekday_kst")
    if summary.empty:
        return summary
    weekday_order = {name: idx for idx, name in enumerate(KOREAN_WEEKDAYS)}
    summary["weekday_order"] = summary["weekday_kst"].map(weekday_order).fillna(99)
    summary = summary.sort_values(["weekday_order", "log_type"], ascending=[True, True]).drop(columns=["weekday_order"])
    return summary.reset_index(drop=True)
