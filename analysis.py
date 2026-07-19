from __future__ import annotations

import json
import math
import uuid
from pathlib import Path
from typing import Any

# [메모리] matplotlib 은 최상위에서 import 하면 앱 시작 시 항상 메모리에 로드된다
# (폰트매니저 포함 수십~수백 MB). 차트(PNG) 생성은 배포 안정화를 위해 비활성화됐으므로,
# matplotlib 은 실제로 그릴 때만 함수 내부에서 지연 import 한다. → 평소 메모리 절감.

# 한글 폰트 설정은 '차트를 처음 그릴 때' 한 번만 수행.
_FONT_READY = False


def _ensure_korean_font() -> None:
    global _FONT_READY
    if _FONT_READY:
        return
    _FONT_READY = True
    try:
        import matplotlib
        import matplotlib.font_manager as fm
        avail = {f.name for f in fm.fontManager.ttflist}
        for cand in ("NanumGothic", "NanumBarunGothic", "NanumSquare",
                     "Malgun Gothic", "AppleGothic", "Noto Sans CJK KR"):
            if cand in avail:
                matplotlib.rcParams["font.family"] = cand
                break
        matplotlib.rcParams["axes.unicode_minus"] = False
    except Exception:
        pass
import pandas as pd

from history_analysis import (
    build_log_type_summary,
    build_period_summary,
    build_weekday_summary,
    enrich_history_dataframe,
)
from log_utils import (
    build_log_status_table,
    ensure_runtime_dirs,
    get_round_context,
    load_combined_log_history,
    persist_log_record,
    utc_now_iso,
)


def _prize_label_from_match(hit_count: int, bonus_match: bool) -> tuple[str, int]:
    hit_count = int(hit_count or 0)
    if hit_count >= 6:
        return "1등", 1
    if hit_count == 5 and bonus_match:
        return "2등", 2
    if hit_count == 5:
        return "3등", 3
    if hit_count == 4:
        return "4등", 4
    if hit_count == 3:
        return "5등", 5
    return "낙점", 6


def _explode_numbers(df: pd.DataFrame, actual_df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    actual_map = {
        int(row["회차"]): {
            "actual_numbers": [int(row[f"번호{i}"]) for i in range(1, 7)],
            "bonus_number": int(row.get("보너스")) if pd.notna(row.get("보너스")) else None,
            "draw_date": row.get("추첨일"),
        }
        for _, row in actual_df.iterrows()
    }

    records: list[dict[str, Any]] = []
    for row in df.to_dict(orient="records"):
        target_round = row.get("target_round")
        if target_round is None or int(target_round) not in actual_map:
            continue
        actual_info = actual_map[int(target_round)]
        actual_numbers = actual_info["actual_numbers"]
        bonus_number = actual_info.get("bonus_number")
        predicted_numbers = [int(n) for n in row.get("numbers", [])]
        matched_numbers = sorted(set(predicted_numbers) & set(actual_numbers))
        bonus_match = bool(bonus_number is not None and bonus_number in predicted_numbers)
        prize_label, prize_order = _prize_label_from_match(len(matched_numbers), bonus_match)
        row["actual_numbers"] = actual_numbers
        row["bonus_number"] = bonus_number
        row["bonus_match"] = bonus_match
        row["matched_numbers"] = matched_numbers
        row["matched_numbers_text"] = ", ".join(f"{int(n):02d}" for n in matched_numbers) if matched_numbers else "-"
        row["hit_count"] = len(matched_numbers)
        row["prize_label"] = prize_label
        row["prize_order"] = prize_order
        row["actual_draw_date"] = actual_info["draw_date"]
        records.append(row)
    return pd.DataFrame(records)


def _prepare_prediction_df(base_dir: Path, actual_df: pd.DataFrame, history_df: pd.DataFrame | None = None) -> pd.DataFrame:
    if history_df is None:
        history_df = load_combined_log_history(base_dir)
    if history_df.empty:
        return history_df

    merged = history_df[history_df["log_type"].isin(["prediction", "probability"])].copy()
    if merged.empty:
        return merged

    merged["target_round"] = pd.to_numeric(merged["target_round"], errors="coerce")
    merged["score"] = pd.to_numeric(merged["score"], errors="coerce")
    merged["avg_gap_factor"] = pd.to_numeric(merged["avg_gap_factor"], errors="coerce")
    merged = merged.dropna(subset=["target_round", "score"]).copy()
    merged["target_round"] = merged["target_round"].astype(int)
    matched_df = _explode_numbers(merged, actual_df)
    if not matched_df.empty:
        matched_df["timestamp_sort"] = pd.to_datetime(matched_df.get("timestamp"), utc=True, errors="coerce")
        matched_df = matched_df.sort_values(
            ["target_round", "prize_order", "hit_count", "score", "candidate_rank", "timestamp_sort"],
            ascending=[False, True, False, False, True, False],
            na_position="last",
        ).drop(columns=["timestamp_sort"], errors="ignore").reset_index(drop=True)
    return matched_df


def _build_threshold_table(matched_df: pd.DataFrame) -> pd.DataFrame:
    if matched_df.empty or matched_df["score"].dropna().empty:
        return pd.DataFrame(columns=["threshold", "samples", "avg_hits", "hit_3_plus_rate", "hit_4_plus_rate", "max_hits"])

    min_score = float(matched_df["score"].min())
    max_score = float(matched_df["score"].max())
    start = math.floor(min_score * 2) / 2
    end = math.ceil(max_score * 2) / 2
    thresholds: list[float] = []
    current = start
    while current <= end + 1e-9:
        thresholds.append(round(current, 2))
        current += 0.5

    rows = []
    for threshold in thresholds:
        subset = matched_df[matched_df["score"] >= threshold]
        if subset.empty:
            continue
        rows.append(
            {
                "threshold": threshold,
                "samples": int(len(subset)),
                "avg_hits": round(float(subset["hit_count"].mean()), 4),
                "hit_3_plus_rate": round(float((subset["hit_count"] >= 3).mean()), 4),
                "hit_4_plus_rate": round(float((subset["hit_count"] >= 4).mean()), 4),
                "max_hits": int(subset["hit_count"].max()),
            }
        )
    return pd.DataFrame(rows)


def _select_recommended_threshold(threshold_df: pd.DataFrame) -> dict[str, Any] | None:
    if threshold_df.empty:
        return None

    for minimum_samples in (5, 3, 1):
        subset = threshold_df[threshold_df["samples"] >= minimum_samples].copy()
        if subset.empty:
            continue
        subset = subset.sort_values(
            ["hit_3_plus_rate", "avg_hits", "samples", "threshold"],
            ascending=[False, False, False, False],
        )
        best = subset.iloc[0].to_dict()
        best["minimum_samples_rule"] = minimum_samples
        return best
    return None


def _prepare_time_series(base_dir: Path, history_df: pd.DataFrame | None = None) -> pd.DataFrame:
    if history_df is None:
        history_df = load_combined_log_history(base_dir)
    if history_df.empty:
        return history_df

    df = history_df[history_df["log_type"].isin(["prediction", "probability", "manual"])].copy()
    if df.empty:
        return df

    df["score_metric"] = df["score"].where(df["score"].notna(), df["best_score"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp", "score_metric"]).copy()
    df["date"] = df["timestamp"].dt.strftime("%Y-%m-%d")
    df["score_metric"] = pd.to_numeric(df["score_metric"], errors="coerce")
    df["avg_gap_factor"] = pd.to_numeric(df["avg_gap_factor"], errors="coerce")
    summary = (
        df.groupby(["date", "log_type"], as_index=False)
        .agg(avg_score=("score_metric", "mean"), avg_gap_factor=("avg_gap_factor", "mean"), samples=("score_metric", "size"))
        .sort_values(["date", "log_type"])
    )
    summary["avg_score"] = summary["avg_score"].round(4)
    summary["avg_gap_factor"] = summary["avg_gap_factor"].round(6)
    return summary


def _save_line_chart(df: pd.DataFrame, value_col: str, title: str, y_label: str, output_path: Path) -> None:
    if df.empty:
        return
    pivot = df.pivot(index="date", columns="log_type", values=value_col).sort_index()
    if pivot.empty:
        return
    _ensure_korean_font()
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.figure import Figure
    # pyplot 전역 상태를 쓰지 않는 객체지향 API → 멀티스레드 안전, figure 누수 없음
    fig = Figure(figsize=(12, 5))
    ax = fig.subplots()
    for col in pivot.columns:
        ax.plot(pivot.index, pivot[col], marker="o", linewidth=2, label=col)
    ax.set_title(title)
    ax.set_xlabel("date")
    ax.set_ylabel(y_label)
    ax.tick_params(axis="x", rotation=45)
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=110)
    # Figure 는 pyplot 전역 매니저에 등록되지 않으므로 함수 종료 시 자동 해제됨


def _build_summary_text(summary: dict[str, Any]) -> str:
    lines = [
        "로그 분석 요약",
        "=" * 32,
        f"생성 시각(UTC): {summary['generated_at_utc']}",
        f"최신 원본 회차: {summary['latest_source_round']}",
        f"매칭 로그 수: {summary['resolved_match_rows']}",
        f"시계열 집계 행 수: {summary['time_series_rows']}",
        f"일별 요약 행 수: {summary.get('daily_summary_rows', 0)}",
        f"주별 요약 행 수: {summary.get('weekly_summary_rows', 0)}",
        f"월별 요약 행 수: {summary.get('monthly_summary_rows', 0)}",
        f"요일별 요약 행 수: {summary.get('weekday_summary_rows', 0)}",
        "",
    ]

    rec = summary.get("recommended_threshold")
    if rec:
        lines.extend(
            [
                "권장 임계값",
                "-" * 24,
                f"권장 점수 기준: {rec['threshold']} 이상",
                f"샘플 수: {rec['samples']}",
                f"평균 적중 수: {rec['avg_hits']}",
                f"3개 이상 적중 비율: {rec['hit_3_plus_rate']}",
                f"4개 이상 적중 비율: {rec['hit_4_plus_rate']}",
                f"선택 기준 최소 샘플 수: {rec['minimum_samples_rule']}",
                "",
            ]
        )
    else:
        lines.extend(["권장 임계값", "-" * 24, "충분한 매칭 로그가 없어 임계값 추천을 생성하지 못했습니다.", ""])

    best_round = summary.get("best_round_example")
    if best_round:
        lines.extend(
            [
                "대표 적중 사례",
                "-" * 24,
                f"대상 회차: {best_round['target_round']}",
                f"로그 유형: {best_round['log_type']}",
                f"점수: {best_round['score']}",
                f"예측 번호: {best_round['numbers']}",
                f"실제 당첨 번호: {best_round['actual_numbers']}",
                f"보너스 번호: {best_round.get('bonus_number', '-')}",
                f"일치 번호: {best_round['matched_numbers']}",
                f"당첨 등급: {best_round.get('prize_label', '-')}",
                f"적중 개수: {best_round['hit_count']}",
            ]
        )
    else:
        lines.extend(["대표 적중 사례", "-" * 24, "아직 실제 당첨번호와 연결된 로그가 없습니다."])

    return "\n".join(lines) + "\n"


def analyze_logs(base_dir: Path | str, excel_path: Path | str) -> dict[str, Any]:
    base_dir = Path(base_dir)
    excel_path = Path(excel_path)
    log_dir, report_dir = ensure_runtime_dirs(base_dir)

    if not excel_path.exists():
        raise FileNotFoundError(f"lotto.xlsx 파일을 찾을 수 없습니다: {excel_path}")

    actual_df = pd.read_excel(excel_path)
    # [성능] 로그 DB를 한 번만 읽어 파생 테이블 전체에서 재사용한다.
    # (이전: enrich/예측/시계열에서 각각 load_combined_log_history 를 호출해
    #  같은 DB를 3회 재조회 + Supabase 동기화를 3회 반복했음)
    combined_df = load_combined_log_history(base_dir)
    history_df = enrich_history_dataframe(combined_df)
    matched_df = _prepare_prediction_df(base_dir, actual_df, history_df=combined_df)
    threshold_df = _build_threshold_table(matched_df)
    time_series_df = _prepare_time_series(base_dir, history_df=combined_df)
    daily_summary_df = build_period_summary(history_df, "date_kst")
    weekly_summary_df = build_period_summary(history_df, "week_kst")
    monthly_summary_df = build_period_summary(history_df, "month_kst")
    weekday_summary_df = build_weekday_summary(history_df)
    log_type_summary_df = build_log_type_summary(history_df)

    matched_csv = report_dir / "prediction_actual_match.csv"
    threshold_csv = report_dir / "threshold_analysis.csv"
    score_ts_csv = report_dir / "score_timeseries.csv"
    daily_summary_csv = report_dir / "daily_log_summary.csv"
    weekly_summary_csv = report_dir / "weekly_log_summary.csv"
    monthly_summary_csv = report_dir / "monthly_log_summary.csv"
    weekday_summary_csv = report_dir / "weekday_log_summary.csv"
    log_type_summary_csv = report_dir / "log_type_summary.csv"
    summary_json = report_dir / "analysis_summary.json"
    summary_txt = report_dir / "analysis_summary.txt"
    score_chart = report_dir / "score_timeseries.png"
    gap_chart = report_dir / "gap_factor_timeseries.png"

    if matched_df.empty:
        pd.DataFrame(
            columns=[
                "timestamp",
                "log_type",
                "target_round",
                "candidate_rank",
                "numbers",
                "actual_numbers",
                "matched_numbers",
                "matched_numbers_text",
                "bonus_number",
                "bonus_match",
                "hit_count",
                "prize_label",
                "prize_order",
                "score",
                "avg_gap_factor",
            ]
        ).to_csv(matched_csv, index=False, encoding="utf-8-sig")
    else:
        matched_df.to_csv(matched_csv, index=False, encoding="utf-8-sig")

    threshold_df.to_csv(threshold_csv, index=False, encoding="utf-8-sig")
    time_series_df.to_csv(score_ts_csv, index=False, encoding="utf-8-sig")
    daily_summary_df.to_csv(daily_summary_csv, index=False, encoding="utf-8-sig")
    weekly_summary_df.to_csv(weekly_summary_csv, index=False, encoding="utf-8-sig")
    monthly_summary_df.to_csv(monthly_summary_csv, index=False, encoding="utf-8-sig")
    weekday_summary_df.to_csv(weekday_summary_csv, index=False, encoding="utf-8-sig")
    log_type_summary_df.to_csv(log_type_summary_csv, index=False, encoding="utf-8-sig")

    # [배포 안정화] matplotlib PNG 생성을 비활성화한다.
    # 이 두 PNG는 앱 화면에 표시되지 않으며(다운로드 목록에도 없음),
    # Streamlit Cloud의 제약 컨테이너에서 matplotlib(Agg+한글 freetype 폰트)
    # savefig 가 네이티브 크래시(Bus error/SIGBUS)를 유발하는 주원인이었다.
    # 화면 추이는 score_timeseries.csv 기반 표로 대체된다.
    # _save_line_chart(time_series_df, "avg_score", "일자별 평균 대표 점수 추이", "평균 점수", score_chart)
    # _save_line_chart(time_series_df, "avg_gap_factor", "일자별 평균 gap 계수 추이", "평균 gap 계수", gap_chart)

    best_example = None
    if not matched_df.empty:
        best_row = matched_df.sort_values(["prize_order", "score"], ascending=[True, False], na_position="last").iloc[0].to_dict()
        best_example = {
            "target_round": int(best_row["target_round"]),
            "log_type": str(best_row["log_type"]),
            "score": float(best_row["score"]),
            "numbers": best_row["numbers"],
            "actual_numbers": best_row["actual_numbers"],
            "bonus_number": best_row.get("bonus_number"),
            "matched_numbers": best_row["matched_numbers"],
            "prize_label": best_row.get("prize_label", "-"),
            "hit_count": int(best_row["hit_count"]),
        }

    recommended_threshold = _select_recommended_threshold(threshold_df)
    round_context = get_round_context(excel_path)
    summary = {
        "generated_at_utc": utc_now_iso(),
        "latest_source_round": round_context["source_round"],
        "next_target_round": round_context["target_round"],
        "resolved_match_rows": int(len(matched_df)),
        "time_series_rows": int(len(time_series_df)),
        "daily_summary_rows": int(len(daily_summary_df)),
        "weekly_summary_rows": int(len(weekly_summary_df)),
        "monthly_summary_rows": int(len(monthly_summary_df)),
        "weekday_summary_rows": int(len(weekday_summary_df)),
        "log_type_summary_rows": int(len(log_type_summary_df)),
        "recommended_threshold": recommended_threshold,
        "best_round_example": best_example,
        "log_file_status": [],
        "artifacts": {
            "prediction_actual_match_csv": str(matched_csv.name),
            "threshold_analysis_csv": str(threshold_csv.name),
            "score_timeseries_csv": str(score_ts_csv.name),
            "daily_summary_csv": str(daily_summary_csv.name),
            "weekly_summary_csv": str(weekly_summary_csv.name),
            "monthly_summary_csv": str(monthly_summary_csv.name),
            "weekday_summary_csv": str(weekday_summary_csv.name),
            "log_type_summary_csv": str(log_type_summary_csv.name),
            "score_timeseries_png": str(score_chart.name),
            "gap_factor_timeseries_png": str(gap_chart.name),
            "summary_txt": str(summary_txt.name),
        },
    }

    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_txt.write_text(_build_summary_text(summary), encoding="utf-8")
    summary["run_id"] = f"analysis-{summary['generated_at_utc'].replace(':', '').replace('-', '')}-{uuid.uuid4().hex[:8]}"
    # 캘린더에 분석 요약 횟수가 축적되지 않도록 로그 저장을 비활성화합니다.
    # persist_log_record(log_dir, "analysis", summary)
    summary["log_file_status"] = build_log_status_table(base_dir).to_dict(orient="records")
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    project_dir = Path(__file__).resolve().parent
    result = analyze_logs(project_dir, project_dir / "lotto.xlsx")
    print(json.dumps(result, ensure_ascii=False, indent=2))
