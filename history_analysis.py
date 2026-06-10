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


def enrich_history_dataframe(history_df: pd.DataFrame) -> pd.DataFrame:
    if history_df.empty:
        return history_df.copy()

    df = history_df.copy()
    if "timestamp" not in df.columns:
        return df

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    valid_ts = df["timestamp"].notna()
    if valid_ts.any():
        ts_kst = df.loc[valid_ts, "timestamp"].dt.tz_convert("Asia/Seoul")
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

    rows: list[dict[str, Any]] = []
    for keys, group in valid.groupby(group_keys, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        row = {period_col: keys[0]}
        if group_col:
            row[group_col] = keys[1]

        score_series = pd.to_numeric(group.get("score_metric"), errors="coerce").dropna()
        target_rounds = pd.to_numeric(group.get("target_round"), errors="coerce").dropna()
        avg_gap = pd.to_numeric(group.get("avg_gap_factor"), errors="coerce").dropna()
        avg_prob = pd.to_numeric(group.get("avg_probability_weight"), errors="coerce").dropna()

        row.update(
            {
                "logs": int(len(group)),
                "unique_runs": int(group.get("run_id", pd.Series(dtype=object)).replace("-", pd.NA).dropna().nunique()),
                "unique_target_rounds": int(target_rounds.nunique()),
                "scored_logs": int(score_series.size),
                "score_coverage": round(float(score_series.size / len(group)), 4) if len(group) else 0.0,
                "avg_score": round(float(score_series.mean()), 4) if not score_series.empty else None,
                "median_score": round(float(score_series.median()), 4) if not score_series.empty else None,
                "score_std": round(float(score_series.std(ddof=0)), 4) if not score_series.empty else None,
                "best_score": round(float(score_series.max()), 4) if not score_series.empty else None,
                "p25_score": round(float(score_series.quantile(0.25)), 4) if not score_series.empty else None,
                "p75_score": round(float(score_series.quantile(0.75)), 4) if not score_series.empty else None,
                "avg_gap_factor": round(float(avg_gap.mean()), 4) if not avg_gap.empty else None,
                "avg_probability_weight": round(float(avg_prob.mean()), 4) if not avg_prob.empty else None,
            }
        )
        rows.append(row)

    summary = pd.DataFrame(rows)
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
