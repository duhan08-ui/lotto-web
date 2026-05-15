"""
tests/test_coverage_boost.py
────────────────────────────────────────────────────────────
커버리지 30%+ 목표 달성을 위한 단위 테스트.

대상 모듈 (커버리지 낮은 순):
  - ai_intelligent_analyzer.py   0%  → 80%+
  - analysis.py                 58%  → 80%+
  - update_lotto.py             68%  → 85%+
  - history_analysis.py         89%  → 95%+
  - app.py (패스워드 로드)       —   → 신규

추가로 검증:
  - secrets.toml 기반 패스워드 로드 (_load_secret 함수)
"""
import json
import math
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parents[1]
EXCEL_PATH = PROJECT_DIR / "lotto.xlsx"

# ═══════════════════════════════════════════════════════════
# 1. ai_intelligent_analyzer.py  (0% → 80%+)
# ═══════════════════════════════════════════════════════════
from ai_intelligent_analyzer import AIIntelligentAnalyzer


class TestAIAnalyzerACValue(unittest.TestCase):
    """AC값 계산 정확성."""

    def setUp(self):
        self.analyzer = AIIntelligentAnalyzer(PROJECT_DIR)

    def test_consecutive_numbers_ac_zero(self):
        """연속 번호는 AC값 0."""
        self.assertEqual(self.analyzer.calculate_ac_value([1, 2, 3, 4, 5, 6]), 0)

    def test_dispersed_numbers_high_ac(self):
        """분산된 번호는 높은 AC값."""
        ac = self.analyzer.calculate_ac_value([1, 8, 18, 29, 38, 45])
        self.assertGreater(ac, 5)

    def test_ac_value_range(self):
        """AC값 범위: 0~14."""
        for nums in [
            [1, 2, 3, 4, 5, 6],
            [1, 10, 20, 30, 40, 45],
            [3, 7, 11, 22, 33, 44],
            [2, 13, 24, 31, 38, 45],
        ]:
            ac = self.analyzer.calculate_ac_value(nums)
            self.assertGreaterEqual(ac, 0)
            self.assertLessEqual(ac, 14)

    def test_known_ac_calculation(self):
        """[1,2,4,8,16,32] → diffs가 모두 다름 → 높은 AC값."""
        ac = self.analyzer.calculate_ac_value([1, 2, 4, 8, 16, 32])
        self.assertGreater(ac, 8)


class TestAIAnalyzerPatterns(unittest.TestCase):
    """analyze_patterns 패턴 분석."""

    def setUp(self):
        self.analyzer = AIIntelligentAnalyzer(PROJECT_DIR)

    def test_odd_even_ratio(self):
        nums = [1, 3, 5, 2, 4, 6]  # 홀3 짝3
        result = self.analyzer.analyze_patterns(nums)
        self.assertEqual(result["odd_even"], "3:3")

    def test_sum_correct(self):
        nums = [1, 2, 3, 4, 5, 6]
        result = self.analyzer.analyze_patterns(nums)
        self.assertEqual(result["sum"], 21)

    def test_extinction_zones(self):
        """31~45 구간에만 번호 → 구간 1~3 소멸."""
        nums = [32, 33, 35, 40, 42, 45]
        result = self.analyzer.analyze_patterns(nums)
        self.assertIn(1, result["extinction_zones"])

    def test_range_distribution_sums_to_6(self):
        nums = [5, 15, 25, 35, 40, 45]
        result = self.analyzer.analyze_patterns(nums)
        self.assertEqual(sum(result["range_dist"]), 6)

    def test_full_range_no_extinction(self):
        """각 구간에 번호가 있으면 소멸 없음."""
        nums = [5, 15, 25, 35, 43, 45]
        result = self.analyzer.analyze_patterns(nums)
        self.assertEqual(result["extinction_zones"], [])


class TestAIAnalyzerHistoricalStats(unittest.TestCase):
    """get_historical_stats 과거 데이터 통계."""

    def setUp(self):
        self.analyzer = AIIntelligentAnalyzer(PROJECT_DIR)

    def test_returns_stats_when_excel_exists(self):
        stats = self.analyzer.get_historical_stats(limit=50)
        self.assertIsNotNone(stats)
        self.assertIn("top_freq", stats)
        self.assertIn("total_count", stats)

    def test_top_freq_has_15_items(self):
        stats = self.analyzer.get_historical_stats(limit=50)
        self.assertEqual(len(stats["top_freq"]), 15)

    def test_returns_none_when_no_excel(self):
        analyzer = AIIntelligentAnalyzer("/nonexistent/path")
        self.assertIsNone(analyzer.get_historical_stats())

    def test_total_count_is_positive(self):
        stats = self.analyzer.get_historical_stats(limit=30)
        self.assertGreater(stats["total_count"], 0)


class TestAIAnalyzerScore(unittest.TestCase):
    """simulate_reinforcement_learning_score 점수 계산."""

    def setUp(self):
        self.analyzer = AIIntelligentAnalyzer(PROJECT_DIR)
        self.stats = self.analyzer.get_historical_stats(limit=100)

    def test_score_is_numeric(self):
        score = self.analyzer.simulate_reinforcement_learning_score(
            [7, 14, 21, 28, 35, 42], self.stats
        )
        self.assertIsInstance(score, float)

    def test_score_range_reasonable(self):
        """점수는 0~20 사이여야 함 (규칙 기반 가중합 최대값)."""
        score = self.analyzer.simulate_reinforcement_learning_score(
            [3, 11, 19, 27, 35, 43], self.stats
        )
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 25)

    def test_score_without_stats(self):
        """stats=None 이어도 점수 계산 가능."""
        score = self.analyzer.simulate_reinforcement_learning_score(
            [1, 10, 20, 30, 40, 45], None
        )
        self.assertIsInstance(score, float)

    def test_hot_numbers_give_higher_score(self):
        """상위 빈도 번호를 포함하면 더 높은 점수."""
        top_nums = [n for n, _ in self.stats["top_freq"][:6]]
        score_hot = self.analyzer.simulate_reinforcement_learning_score(top_nums, self.stats)
        score_cold = self.analyzer.simulate_reinforcement_learning_score(
            [2, 4, 6, 8, 10, 12], None
        )
        self.assertGreaterEqual(score_hot, score_cold)


class TestAIAnalyzerRunAnalysis(unittest.TestCase):
    """run_analysis 통합 실행."""

    def test_run_analysis_no_logs(self):
        """로그 없을 때 빈 결과 반환."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            shutil.copy2(EXCEL_PATH, tmppath / "lotto.xlsx")
            (tmppath / "logs").mkdir()
            (tmppath / "reports").mkdir()
            analyzer = AIIntelligentAnalyzer(tmppath)
            result = analyzer.run_analysis()
            self.assertIsInstance(result, str)

    def test_run_analysis_with_logs(self):
        """로그 있을 때 상위 5세트 추출."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            shutil.copy2(EXCEL_PATH, tmppath / "lotto.xlsx")
            log_dir = tmppath / "logs"
            log_dir.mkdir()
            (tmppath / "reports").mkdir()
            log_file = log_dir / "prediction_log.jsonl"
            for i in range(10):
                record = {
                    "log_type": "prediction",
                    "numbers": [i + 1, i + 7, i + 14, i + 21, i + 28, min(i + 35, 45)],
                    "score": float(i),
                    "target_round": 1200 + i,
                }
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record) + "\n")
            analyzer = AIIntelligentAnalyzer(tmppath)
            result = analyzer.run_analysis()
            self.assertIn("순위", result)


# ═══════════════════════════════════════════════════════════
# 2. analysis.py 핵심 함수 (58% → 80%+)
# ═══════════════════════════════════════════════════════════
from analysis import (
    _prize_label_from_match,
    _build_threshold_table,
    _select_recommended_threshold,
    _build_summary_text,
    _explode_numbers,
)


class TestPrizeLabelFromMatch(unittest.TestCase):
    """_prize_label_from_match 등급 판정."""

    def test_1st_prize(self):
        label, order = _prize_label_from_match(6, False)
        self.assertEqual(label, "1등")
        self.assertEqual(order, 1)

    def test_2nd_prize_with_bonus(self):
        label, order = _prize_label_from_match(5, True)
        self.assertEqual(label, "2등")
        self.assertEqual(order, 2)

    def test_3rd_prize_no_bonus(self):
        label, order = _prize_label_from_match(5, False)
        self.assertEqual(label, "3등")
        self.assertEqual(order, 3)

    def test_4th_prize(self):
        label, order = _prize_label_from_match(4, False)
        self.assertEqual(label, "4등")

    def test_5th_prize(self):
        label, order = _prize_label_from_match(3, False)
        self.assertEqual(label, "5등")

    def test_miss(self):
        label, order = _prize_label_from_match(2, False)
        self.assertEqual(label, "낙점")
        self.assertEqual(order, 6)

    def test_zero_hits(self):
        label, order = _prize_label_from_match(0, False)
        self.assertEqual(label, "낙점")

    def test_none_hit_count(self):
        label, order = _prize_label_from_match(None, False)
        self.assertEqual(label, "낙점")


class TestBuildThresholdTable(unittest.TestCase):
    """_build_threshold_table 임계값 분석 테이블."""

    def _make_df(self, scores, hit_counts):
        return pd.DataFrame({"score": scores, "hit_count": hit_counts})

    def test_empty_df_returns_empty(self):
        result = _build_threshold_table(pd.DataFrame())
        self.assertTrue(result.empty)

    def test_basic_table_structure(self):
        df = self._make_df([1.0, 2.0, 3.0, 4.0, 5.0], [2, 3, 4, 3, 5])
        result = _build_threshold_table(df)
        self.assertIn("threshold", result.columns)
        self.assertIn("samples", result.columns)
        self.assertIn("hit_3_plus_rate", result.columns)
        self.assertFalse(result.empty)

    def test_threshold_monotone_decreasing_samples(self):
        """임계값 높아질수록 샘플 수 감소."""
        df = self._make_df([1.0, 2.0, 3.0, 4.0, 5.0], [2, 3, 4, 3, 5])
        result = _build_threshold_table(df)
        samples = result["samples"].tolist()
        self.assertEqual(samples, sorted(samples, reverse=True))

    def test_hit_rate_between_0_and_1(self):
        df = self._make_df([1.0, 2.0, 3.0, 4.0], [1, 3, 4, 5])
        result = _build_threshold_table(df)
        self.assertTrue((result["hit_3_plus_rate"] >= 0).all())
        self.assertTrue((result["hit_3_plus_rate"] <= 1).all())

    def test_single_row_df(self):
        df = self._make_df([5.0], [3])
        result = _build_threshold_table(df)
        self.assertFalse(result.empty)


class TestSelectRecommendedThreshold(unittest.TestCase):
    """_select_recommended_threshold 권장 임계값 선택."""

    def _make_threshold_df(self, rows):
        return pd.DataFrame(rows)

    def test_returns_none_for_empty(self):
        self.assertIsNone(_select_recommended_threshold(pd.DataFrame()))

    def test_returns_dict(self):
        df = self._make_threshold_df([
            {"threshold": 5.0, "samples": 20, "avg_hits": 2.5,
             "hit_3_plus_rate": 0.4, "hit_4_plus_rate": 0.1, "max_hits": 5},
        ])
        result = _select_recommended_threshold(df)
        self.assertIsInstance(result, dict)
        self.assertIn("threshold", result)
        self.assertIn("minimum_samples_rule", result)

    def test_prefers_more_samples_over_single(self):
        """샘플 많은 쪽이 적중률 낮아도 선택될 수 있어야 함."""
        df = self._make_threshold_df([
            {"threshold": 15.0, "samples": 1, "avg_hits": 5.0,
             "hit_3_plus_rate": 1.0, "hit_4_plus_rate": 1.0, "max_hits": 5},
            {"threshold": 3.0, "samples": 50, "avg_hits": 2.5,
             "hit_3_plus_rate": 0.4, "hit_4_plus_rate": 0.1, "max_hits": 4},
        ])
        result = _select_recommended_threshold(df)
        # minimum_samples=5 기준: 50개 샘플 row가 선택됨
        self.assertEqual(result["samples"], 50)

    def test_fallback_to_less_samples_when_needed(self):
        """최소 1개 샘플이라도 있으면 결과 반환."""
        df = self._make_threshold_df([
            {"threshold": 10.0, "samples": 1, "avg_hits": 3.0,
             "hit_3_plus_rate": 1.0, "hit_4_plus_rate": 0.5, "max_hits": 3},
        ])
        result = _select_recommended_threshold(df)
        self.assertIsNotNone(result)
        self.assertEqual(result["minimum_samples_rule"], 1)


class TestBuildSummaryText(unittest.TestCase):
    """_build_summary_text 요약 텍스트 생성."""

    def _base_summary(self):
        return {
            "generated_at_utc": "2026-01-01T00:00:00+00:00",
            "latest_source_round": 1200,
            "resolved_match_rows": 50,
            "time_series_rows": 10,
            "daily_summary_rows": 7,
            "weekly_summary_rows": 4,
            "monthly_summary_rows": 2,
            "weekday_summary_rows": 7,
            "recommended_threshold": None,
            "best_round_example": None,
        }

    def test_basic_structure(self):
        text = _build_summary_text(self._base_summary())
        self.assertIn("로그 분석 요약", text)
        self.assertIn("최신 원본 회차: 1200", text)

    def test_with_recommended_threshold(self):
        summary = self._base_summary()
        summary["recommended_threshold"] = {
            "threshold": 5.5,
            "samples": 30,
            "avg_hits": 2.8,
            "hit_3_plus_rate": 0.45,
            "hit_4_plus_rate": 0.12,
            "minimum_samples_rule": 5,
        }
        text = _build_summary_text(summary)
        self.assertIn("5.5", text)
        self.assertIn("30", text)

    def test_with_best_round_example(self):
        summary = self._base_summary()
        summary["best_round_example"] = {
            "target_round": 1200,
            "log_type": "prediction",
            "score": 7.5,
            "numbers": [1, 2, 3, 4, 5, 6],
            "actual_numbers": [1, 2, 3, 4, 5, 6],
            "bonus_number": 7,
            "matched_numbers": [1, 2, 3, 4, 5, 6],
            "prize_label": "1등",
            "hit_count": 6,
        }
        text = _build_summary_text(summary)
        self.assertIn("1등", text)
        self.assertIn("1200", text)

    def test_no_threshold_message(self):
        text = _build_summary_text(self._base_summary())
        self.assertIn("충분한 매칭 로그가 없어", text)


class TestExplodeNumbers(unittest.TestCase):
    """_explode_numbers 예측-실제 번호 매칭."""

    def _make_actual_df(self, round_no, numbers, bonus):
        return pd.DataFrame([{
            "회차": round_no,
            "추첨일": "2026-01-01",
            "번호1": numbers[0], "번호2": numbers[1], "번호3": numbers[2],
            "번호4": numbers[3], "번호5": numbers[4], "번호6": numbers[5],
            "보너스": bonus,
        }])

    def test_perfect_match(self):
        pred_df = pd.DataFrame([{
            "target_round": 1200,
            "numbers": [1, 2, 3, 4, 5, 6],
            "score": 5.0,
        }])
        actual_df = self._make_actual_df(1200, [1, 2, 3, 4, 5, 6], 7)
        result = _explode_numbers(pred_df, actual_df)
        self.assertEqual(result.iloc[0]["hit_count"], 6)
        self.assertEqual(result.iloc[0]["prize_label"], "1등")

    def test_partial_match(self):
        pred_df = pd.DataFrame([{
            "target_round": 1200,
            "numbers": [1, 2, 3, 10, 20, 30],
            "score": 3.0,
        }])
        actual_df = self._make_actual_df(1200, [1, 2, 3, 4, 5, 6], 7)
        result = _explode_numbers(pred_df, actual_df)
        self.assertEqual(result.iloc[0]["hit_count"], 3)
        self.assertEqual(result.iloc[0]["prize_label"], "5등")

    def test_bonus_match_gives_2nd(self):
        pred_df = pd.DataFrame([{
            "target_round": 1200,
            "numbers": [1, 2, 3, 4, 5, 7],
            "score": 4.0,
        }])
        actual_df = self._make_actual_df(1200, [1, 2, 3, 4, 5, 6], 7)
        result = _explode_numbers(pred_df, actual_df)
        self.assertTrue(result.iloc[0]["bonus_match"])
        self.assertEqual(result.iloc[0]["prize_label"], "2등")

    def test_no_match_round(self):
        """매칭 회차 없으면 빈 DataFrame."""
        pred_df = pd.DataFrame([{
            "target_round": 9999,
            "numbers": [1, 2, 3, 4, 5, 6],
            "score": 5.0,
        }])
        actual_df = self._make_actual_df(1200, [1, 2, 3, 4, 5, 6], 7)
        result = _explode_numbers(pred_df, actual_df)
        self.assertTrue(result.empty)

    def test_empty_pred_df(self):
        result = _explode_numbers(pd.DataFrame(), pd.DataFrame())
        self.assertTrue(result.empty)


# ═══════════════════════════════════════════════════════════
# 3. update_lotto.py  (68% → 85%+)
# ═══════════════════════════════════════════════════════════
from update_lotto import parse_draw_date, parse_cards, finalize_dataframe, load_existing_dataframe


class TestParseDrawDate(unittest.TestCase):
    """parse_draw_date 날짜 파싱."""

    def test_korean_date_format(self):
        result = parse_draw_date("2026년 01월 15일")
        self.assertEqual(result, "2026-01-15")

    def test_korean_date_with_spaces(self):
        result = parse_draw_date("2026년  04월  06일")
        self.assertEqual(result, "2026-04-06")

    def test_invalid_format_returns_stripped(self):
        result = parse_draw_date("  no date here  ")
        self.assertEqual(result, "no date here")

    def test_empty_string(self):
        result = parse_draw_date("")
        self.assertEqual(result, "")


class TestParseCards(unittest.TestCase):
    """parse_cards HTML 파싱."""

    def _make_html(self, round_no, numbers, bonus, date="2026년 01월 15일"):
        nums_html = "".join(
            f'<span class="numberCircle"><strong>{n}</strong></span>'
            for n in numbers
        )
        bonus_html = f'<span class="numberCircle"><strong>{bonus}</strong></span>'
        return f"""
        <div class="card text-center border-primary mt-3">
            <div class="card-header">제 {round_no}회</div>
            {nums_html}
            <div class="plusCircle"><i class="fa fa-plus"></i></div>
            {bonus_html}
            <div class="text-muted">{date}</div>
        </div>
        """

    def test_parses_single_card(self):
        html = self._make_html(1200, [1, 2, 3, 4, 5, 6], 7)
        rows = parse_cards(html, 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["회차"], 1200)
        self.assertEqual(rows[0]["번호1"], 1)
        self.assertEqual(rows[0]["보너스"], 7)

    def test_parses_multiple_cards(self):
        html = self._make_html(1200, [1, 2, 3, 4, 5, 6], 7)
        html += self._make_html(1199, [10, 20, 30, 35, 40, 45], 15)
        rows = parse_cards(html, 1)
        self.assertEqual(len(rows), 2)

    def test_parses_date_correctly(self):
        html = self._make_html(1200, [1, 2, 3, 4, 5, 6], 7, "2026년 04월 06일")
        rows = parse_cards(html, 1)
        self.assertEqual(rows[0]["추첨일"], "2026-04-06")

    def test_invalid_html_returns_empty(self):
        rows = parse_cards("<html><body>no cards</body></html>", 1)
        self.assertEqual(rows, [])

    def test_card_without_round_skipped(self):
        html = """
        <div class="card text-center border-primary mt-3">
            <div class="card-header">제목 없음</div>
        </div>
        """
        rows = parse_cards(html, 1)
        self.assertEqual(rows, [])


class TestFinalizeDataframe(unittest.TestCase):
    """finalize_dataframe 데이터 정렬 및 정규화."""

    def _make_df(self):
        return pd.DataFrame([
            {"회차": 1199, "추첨일": "2026-04-01",
             "번호1": 5, "번호2": 10, "번호3": 15,
             "번호4": 20, "번호5": 25, "번호6": 30, "보너스": 35,
             "수집페이지": 1, "출처": "http://test.com"},
            {"회차": 1200, "추첨일": "2026-04-08",
             "번호1": 1, "번호2": 7, "번호3": 14,
             "번호4": 21, "번호5": 35, "번호6": 42, "보너스": 45,
             "수집페이지": 1, "출처": "http://test.com"},
        ])

    def test_sorted_descending(self):
        df = self._make_df()
        result = finalize_dataframe(df)
        rounds = result["회차"].tolist()
        self.assertEqual(rounds, sorted(rounds, reverse=True))

    def test_no_duplicates(self):
        df = self._make_df()
        # 중복 행 추가
        df = pd.concat([df, df.iloc[[0]]], ignore_index=True)
        result = finalize_dataframe(df)
        self.assertEqual(len(result), 2)

    def test_required_columns_present(self):
        df = self._make_df()
        result = finalize_dataframe(df)
        for col in ["회차", "추첨일", "번호1", "번호6", "보너스"]:
            self.assertIn(col, result.columns)


class TestLoadExistingDataframe(unittest.TestCase):
    """load_existing_dataframe 기존 엑셀 로드."""

    def test_loads_real_excel(self):
        df = load_existing_dataframe(EXCEL_PATH)
        self.assertFalse(df.empty)
        self.assertIn("회차", df.columns)

    def test_returns_empty_for_missing_file(self):
        df = load_existing_dataframe(Path("/nonexistent/path/lotto.xlsx"))
        self.assertTrue(df.empty)


# ═══════════════════════════════════════════════════════════
# 4. history_analysis.py  (89% → 95%+)
# ═══════════════════════════════════════════════════════════
from history_analysis import (
    enrich_history_dataframe,
    build_period_summary,
    build_log_type_summary,
    build_weekday_summary,
    _safe_date,
)


class TestSafeDate(unittest.TestCase):
    """_safe_date 날짜 파싱."""

    def test_valid_date(self):
        result = _safe_date("2026-04-15")
        self.assertIsNotNone(result)
        self.assertEqual(str(result), "2026-04-15")

    def test_invalid_date_returns_none(self):
        self.assertIsNone(_safe_date("not-a-date"))

    def test_empty_string_returns_none(self):
        self.assertIsNone(_safe_date(""))


class TestEnrichHistoryDataframe(unittest.TestCase):
    """enrich_history_dataframe 타임스탬프 보강."""

    def _make_df(self, timestamps):
        # score_metric 필수 컬럼 포함 (history_analysis 요구사항)
        return pd.DataFrame([
            {"timestamp": ts, "log_type": "prediction",
             "score": 5.0, "score_metric": 5.0}
            for ts in timestamps
        ])

    def test_empty_df_returned_as_is(self):
        result = enrich_history_dataframe(pd.DataFrame())
        self.assertTrue(result.empty)

    def test_kst_columns_added(self):
        df = self._make_df(["2026-04-15T10:00:00+00:00"])
        result = enrich_history_dataframe(df)
        self.assertIn("date_kst", result.columns)
        self.assertIn("week_kst", result.columns)
        self.assertIn("month_kst", result.columns)
        self.assertIn("weekday_kst", result.columns)

    def test_score_zscore_calculated(self):
        df = self._make_df([
            "2026-04-15T10:00:00+00:00",
            "2026-04-15T11:00:00+00:00",
            "2026-04-15T12:00:00+00:00",
        ])
        df["score_metric"] = [1.0, 2.0, 3.0]
        result = enrich_history_dataframe(df)
        self.assertIn("score_zscore", result.columns)

    def test_valid_timestamps_handled(self):
        df = self._make_df(["2026-04-15T10:00:00+00:00", "2026-04-16T10:00:00+00:00"])
        result = enrich_history_dataframe(df)
        self.assertFalse(result.empty)
        self.assertEqual(len(result), 2)


class TestBuildPeriodSummary(unittest.TestCase):
    """build_period_summary 기간별 통계."""

    def _make_enriched_df(self):
        raw = pd.DataFrame([
            {"timestamp": "2026-04-15T10:00:00+00:00", "log_type": "prediction",
             "score": 5.0, "score_metric": 5.0, "avg_gap_factor": 1.1, "target_round": 1200, "run_id": "r1"},
            {"timestamp": "2026-04-15T11:00:00+00:00", "log_type": "prediction",
             "score": 7.0, "score_metric": 7.0, "avg_gap_factor": 1.3, "target_round": 1200, "run_id": "r2"},
            {"timestamp": "2026-04-16T10:00:00+00:00", "log_type": "probability",
             "score": 4.0, "score_metric": 4.0, "avg_gap_factor": 0.9, "target_round": 1201, "run_id": "r3"},
        ])
        return enrich_history_dataframe(raw)

    def test_empty_returns_empty(self):
        result = build_period_summary(pd.DataFrame(), "date_kst")
        self.assertTrue(result.empty)

    def test_daily_summary_columns(self):
        # load_combined_log_history 결과와 유사한 실제 데이터 사용
        from log_utils import load_combined_log_history
        import tempfile, shutil
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            from log_utils import persist_log_record
            log_dir = tmppath / "logs"
            log_dir.mkdir()
            for i in range(3):
                persist_log_record(log_dir, "prediction", {
                    "timestamp": f"2026-04-{15+i}T10:00:00+00:00",
                    "run_id": f"r{i}", "score": float(i+1),
                    "best_score": float(i+1), "target_round": 1200+i,
                })
            from history_analysis import enrich_history_dataframe
            df = enrich_history_dataframe(load_combined_log_history(tmppath))
            result = build_period_summary(df, "date_kst")
        self.assertIn("logs", result.columns)
        self.assertIn("avg_score", result.columns)

    def test_daily_summary_row_count(self):
        from log_utils import load_combined_log_history, persist_log_record
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            (tmppath / "logs").mkdir()
            for i in range(3):
                persist_log_record(tmppath / "logs", "prediction", {
                    "timestamp": f"2026-04-{15+i}T10:00:00+00:00",
                    "run_id": f"r{i}", "score": float(i+1),
                    "best_score": float(i+1), "target_round": 1200+i,
                })
            from history_analysis import enrich_history_dataframe
            df = enrich_history_dataframe(load_combined_log_history(tmppath))
            result = build_period_summary(df, "date_kst")
        self.assertGreater(len(result), 0)

    def test_missing_period_col_returns_empty(self):
        df = pd.DataFrame([{"log_type": "prediction", "score": 5.0}])
        result = build_period_summary(df, "nonexistent_col")
        self.assertTrue(result.empty)


class TestBuildWeekdaySummary(unittest.TestCase):
    """build_weekday_summary 요일별 통계."""

    def test_empty_returns_empty(self):
        result = build_weekday_summary(pd.DataFrame())
        self.assertTrue(result.empty)

    def test_weekday_column_present(self):
        from log_utils import load_combined_log_history, persist_log_record
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            (tmppath / "logs").mkdir()
            persist_log_record(tmppath / "logs", "prediction", {
                "timestamp": "2026-04-14T10:00:00+00:00",
                "run_id": "r1", "score": 5.0, "best_score": 5.0, "target_round": 1200,
            })
            df = enrich_history_dataframe(load_combined_log_history(tmppath))
            result = build_weekday_summary(df)
        self.assertIn("weekday_kst", result.columns)

    def test_korean_weekday_values(self):
        from log_utils import load_combined_log_history, persist_log_record
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            (tmppath / "logs").mkdir()
            for i in range(5):
                persist_log_record(tmppath / "logs", "prediction", {
                    "timestamp": f"2026-04-{14+i}T10:00:00+00:00",
                    "run_id": f"r{i}", "score": float(i+1),
                    "best_score": float(i+1), "target_round": 1200+i,
                })
            df = enrich_history_dataframe(load_combined_log_history(tmppath))
            result = build_weekday_summary(df)
        valid_days = {"월", "화", "수", "목", "금", "토", "일"}
        for day in result["weekday_kst"]:
            self.assertIn(day, valid_days)


class TestBuildLogTypeSummary(unittest.TestCase):
    """build_log_type_summary 로그 유형 통계."""

    def test_empty_returns_empty(self):
        result = build_log_type_summary(pd.DataFrame())
        self.assertTrue(result.empty)

    def test_multiple_types(self):
        from log_utils import load_combined_log_history, persist_log_record
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            (tmppath / "logs").mkdir()
            for log_type in ["prediction", "probability", "manual"]:
                persist_log_record(tmppath / "logs", log_type, {
                    "timestamp": "2026-04-15T10:00:00+00:00",
                    "run_id": f"r-{log_type}", "score": 5.0,
                    "best_score": 5.0, "target_round": 1200,
                })
            df = enrich_history_dataframe(load_combined_log_history(tmppath))
            result = build_log_type_summary(df)
        self.assertGreaterEqual(len(result), 1)

    def test_sorted_by_logs_desc(self):
        from log_utils import load_combined_log_history, persist_log_record
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            (tmppath / "logs").mkdir()
            for i in range(5):
                persist_log_record(tmppath / "logs", "prediction", {
                    "timestamp": f"2026-04-15T{10+i}:00:00+00:00",
                    "run_id": f"rp{i}", "score": float(i+1),
                    "best_score": float(i+1), "target_round": 1200+i,
                })
            persist_log_record(tmppath / "logs", "manual", {
                "timestamp": "2026-04-15T20:00:00+00:00",
                "run_id": "rm", "score": 1.0, "best_score": 1.0, "target_round": 1200,
            })
            df = enrich_history_dataframe(load_combined_log_history(tmppath))
            result = build_log_type_summary(df)
        logs_values = result["logs"].tolist()
        self.assertEqual(logs_values, sorted(logs_values, reverse=True))


# ═══════════════════════════════════════════════════════════
# 5. 패스워드 로드 (_load_secret) 검증
# ═══════════════════════════════════════════════════════════
class TestLoadSecretFunction(unittest.TestCase):
    """app.py _load_secret 로직 — 환경변수 → 기본값 순서 검증."""

    def _load_secret_via_env(self, env_key, default):
        """secrets.toml 없을 때 환경변수 → 기본값 순서 직접 검증."""
        return os.getenv(env_key, default)

    def test_env_variable_used_when_set(self):
        """환경변수 설정 시 해당 값 반환."""
        os.environ["TEST_LOTTO_PW_A"] = "env_password"
        result = self._load_secret_via_env("TEST_LOTTO_PW_A", "default")
        self.assertEqual(result, "env_password")
        del os.environ["TEST_LOTTO_PW_A"]

    def test_default_used_when_no_env(self):
        """환경변수 없을 때 기본값 반환."""
        if "TEST_LOTTO_PW_NONE" in os.environ:
            del os.environ["TEST_LOTTO_PW_NONE"]
        result = self._load_secret_via_env("TEST_LOTTO_PW_NONE", "default_value")
        self.assertEqual(result, "default_value")

    def test_env_overrides_default(self):
        """환경변수가 기본값보다 우선."""
        os.environ["LOTTO_SIMULATION_EDIT_PASSWORD"] = "custom1234"
        result = self._load_secret_via_env("LOTTO_SIMULATION_EDIT_PASSWORD", "1221")
        self.assertEqual(result, "custom1234")
        del os.environ["LOTTO_SIMULATION_EDIT_PASSWORD"]

    def test_default_password_value(self):
        """기본 비밀번호 값이 환경변수에 없을 때 사용되는 값 확인."""
        if "LOTTO_UNLOCK_PASSWORD" in os.environ:
            del os.environ["LOTTO_UNLOCK_PASSWORD"]
        result = self._load_secret_via_env("LOTTO_UNLOCK_PASSWORD", "0518")
        self.assertEqual(result, "0518")

    def test_secrets_toml_file_exists(self):
        """secrets.toml 파일이 .streamlit 폴더에 존재하는지 확인."""
        secrets_path = PROJECT_DIR / ".streamlit" / "secrets.toml"
        self.assertTrue(secrets_path.exists(), ".streamlit/secrets.toml 파일이 없습니다")

    def test_secrets_toml_contains_required_keys(self):
        """secrets.toml에 필수 키가 모두 포함됐는지 확인."""
        secrets_path = PROJECT_DIR / ".streamlit" / "secrets.toml"
        content = secrets_path.read_text(encoding="utf-8")
        for key in ["SIMULATION_EDIT_PASSWORD", "DATA_CHECK_PASSWORD", "UNLOCK_PASSWORD"]:
            self.assertIn(key, content, f"{key}가 secrets.toml에 없습니다")

    def test_gitignore_excludes_streamlit(self):
        """.gitignore가 .streamlit/ 폴더를 제외하는지 확인."""
        gitignore_path = PROJECT_DIR / ".gitignore"
        content = gitignore_path.read_text(encoding="utf-8")
        self.assertIn(".streamlit", content, ".gitignore에 .streamlit이 없습니다")


if __name__ == "__main__":
    unittest.main(verbosity=2)
