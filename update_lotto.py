from __future__ import annotations

import math
import re
import time
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

from analysis import analyze_logs
from log_utils import ensure_runtime_dirs

BASE_URL = "https://lottohell.com/statistics/round-ball-order/"
HEADERS = {"User-Agent": "Mozilla/5.0"}
REQUIRED_COLUMNS = ["회차", "추첨일", "번호1", "번호2", "번호3", "번호4", "번호5", "번호6", "수집페이지", "출처"]


def fetch_page(page_no: int, retries: int = 3, delay: float = 1.0) -> str:
    url = f"{BASE_URL}?page={page_no}"
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            return resp.text
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(delay * attempt)
    raise RuntimeError(f"페이지 요청 실패: {url} ({last_error})")


def parse_draw_date(raw_text: str) -> str:
    match = re.search(r"(\d{4})년\s*(\d{2})월\s*(\d{2})일", raw_text)
    if not match:
        return raw_text.strip()
    year, month, day = match.groups()
    return f"{year}-{month}-{day}"


def parse_cards(html: str, page_no: int) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    cards = soup.select("div.card.text-center.border-primary.mt-3")
    rows = []
    source_url = f"{BASE_URL}?page={page_no}"

    for card in cards:
        header = card.select_one(".card-header")
        if not header:
            continue

        round_match = re.search(r"(\d+)회", header.get_text(" ", strip=True))
        if not round_match:
            continue
        draw_no = int(round_match.group(1))

        number_nodes = card.select(".numberCircle strong")
        numbers = []
        for node in number_nodes[:6]:
            num_match = re.search(r"\d+", node.get_text(" ", strip=True))
            if num_match:
                numbers.append(int(num_match.group()))
        if len(numbers) != 6:
            continue

        date_node = card.select_one(".text-muted")
        draw_date = parse_draw_date(date_node.get_text(" ", strip=True) if date_node else "")

        rows.append(
            {
                "회차": draw_no,
                "추첨일": draw_date,
                "번호1": numbers[0],
                "번호2": numbers[1],
                "번호3": numbers[2],
                "번호4": numbers[3],
                "번호5": numbers[4],
                "번호6": numbers[5],
                "수집페이지": page_no,
                "출처": source_url,
            }
        )

    return rows


def extract_latest_round(page1_html: str) -> int:
    rows = parse_cards(page1_html, 1)
    if not rows:
        raise RuntimeError("최신 회차를 찾을 수 없습니다.")
    return max(row["회차"] for row in rows)


def load_existing_dataframe(file_path: Path) -> pd.DataFrame:
    if not file_path.exists():
        return pd.DataFrame(columns=REQUIRED_COLUMNS)

    df = pd.read_excel(file_path)
    if all(col in df.columns for col in REQUIRED_COLUMNS):
        return df[REQUIRED_COLUMNS].copy()

    print("기존 lotto.xlsx가 구형 형식이라 전체 재수집을 진행합니다.")
    return pd.DataFrame(columns=REQUIRED_COLUMNS)


def collect_all_pages(latest_round: int) -> pd.DataFrame:
    total_pages = math.ceil(latest_round / 20)
    all_rows = []
    for page_no in range(1, total_pages + 1):
        html = fetch_page(page_no)
        page_rows = parse_cards(html, page_no)
        all_rows.extend(page_rows)
        print(f"[전체 수집] {page_no}/{total_pages} 페이지 완료, 누적 {len(all_rows)}건")

    df = pd.DataFrame(all_rows)
    if df.empty:
        raise RuntimeError("전체 수집 결과가 비어 있습니다.")
    return df


def collect_incremental_pages(latest_round: int, current_max_round: int) -> pd.DataFrame:
    all_rows = []
    total_pages = math.ceil(latest_round / 20)

    for page_no in range(1, total_pages + 1):
        html = fetch_page(page_no)
        page_rows = parse_cards(html, page_no)
        if not page_rows:
            break

        new_rows = [row for row in page_rows if row["회차"] > current_max_round]
        all_rows.extend(new_rows)
        min_round_on_page = min(row["회차"] for row in page_rows)
        print(f"[증분 수집] page={page_no}, 신규 {len(new_rows)}건, 페이지 최소 회차 {min_round_on_page}")

        if min_round_on_page <= current_max_round:
            break

    return pd.DataFrame(all_rows, columns=REQUIRED_COLUMNS)


def finalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    final_df = df.copy()
    final_df = final_df.drop_duplicates(subset=["회차"], keep="first")
    final_df["회차"] = pd.to_numeric(final_df["회차"], errors="coerce")
    final_df = final_df.dropna(subset=["회차"])
    final_df["회차"] = final_df["회차"].astype(int)
    final_df = final_df.sort_values(by="회차", ascending=False).reset_index(drop=True)
    return final_df[REQUIRED_COLUMNS]


def save_excel(df: pd.DataFrame, file_path: Path) -> None:
    with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Lotto")
        ws = writer.book["Lotto"]
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        widths = {"A": 10, "B": 14, "C": 8, "D": 8, "E": 8, "F": 8, "G": 8, "H": 8, "I": 12, "J": 55}
        for col, width in widths.items():
            ws.column_dimensions[col].width = width


def update_excel(file_path: Path | None = None) -> tuple[pd.DataFrame, str]:
    file_path = file_path or (Path(__file__).resolve().parent / "lotto.xlsx")
    existing_df = load_existing_dataframe(file_path)

    page1_html = fetch_page(1)
    latest_round = extract_latest_round(page1_html)

    if existing_df.empty:
        collected_df = collect_all_pages(latest_round)
        final_df = finalize_dataframe(collected_df)
        mode = "full"
    else:
        current_max_round = int(existing_df["회차"].max())
        if latest_round <= current_max_round:
            print(f"최신 데이터 유지 중: 현재 {current_max_round}회차")
            final_df = finalize_dataframe(existing_df)
            mode = "noop"
        else:
            incremental_df = collect_incremental_pages(latest_round, current_max_round)
            final_df = finalize_dataframe(pd.concat([incremental_df, existing_df], ignore_index=True))
            mode = "incremental"

    save_excel(final_df, file_path)
    print(f"저장 완료: {file_path}")
    print(f"모드: {mode}, 총 {len(final_df)}건, 최신 회차 {final_df.iloc[0]['회차']}회")
    return final_df, mode


def run_pipeline() -> None:
    project_dir = Path(__file__).resolve().parent
    ensure_runtime_dirs(project_dir)
    final_df, mode = update_excel(project_dir / "lotto.xlsx")
    summary = analyze_logs(project_dir, project_dir / "lotto.xlsx")
    print("로그 분석 완료")
    print(
        f"분석 요약 | 모드={mode}, 최신 회차={int(final_df.iloc[0]['회차'])}, "
        f"매칭 로그={summary['resolved_match_rows']}, 추천 임계값={summary.get('recommended_threshold')}"
    )


if __name__ == "__main__":
    run_pipeline()
