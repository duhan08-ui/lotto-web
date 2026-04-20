from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from anti_pattern_lotto import AntiPatternLottoV2, LottoConfig, generate_single_anti_pattern_ticket
from analysis import analyze_logs
from app import LottoPredictor
from history_analysis import build_period_summary, enrich_history_dataframe
from log_utils import LOG_FILE_MAP, load_combined_log_history, persist_log_record
from update_lotto import update_excel


PROJECT_DIR = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_DIR / "app.py"
EXCEL_PATH = PROJECT_DIR / "lotto.xlsx"
MANUAL_LOG_PATH = PROJECT_DIR / "logs" / LOG_FILE_MAP["manual"]


def _build_authenticated_app() -> AppTest:
    at = AppTest.from_file(str(APP_PATH))
    at.session_state["auth"] = True
    at.session_state["counts"] = {"prediction": 0, "probability": 0, "manual": 0}
    at.session_state["unlock_mode"] = False
    at.session_state["unlock_granted"] = False
    at.session_state["predict_results"] = None
    at.session_state["probability_results"] = None
    at.session_state["manual_result"] = None
    at.session_state["analysis_summary"] = None
    at.session_state["view"] = ""
    at.session_state["show_data_gate"] = False
    at.session_state["data_access_granted"] = False
    at.session_state["history_selected_date"] = None
    at.session_state["simulation_count"] = 5000
    at.session_state["simulation_notice"] = None
    return at


class LottoPredictorSmokeTest(unittest.TestCase):
    def test_predictor_core_flows(self):
        predictor = LottoPredictor(EXCEL_PATH)
        self.assertGreater(predictor.total_draws, 0)
        self.assertEqual(len(predictor.predict()), 5)
        self.assertEqual(len(predictor.predict_probability_only()), 5)

        result = predictor.score_manual_combination([1, 2, 3, 4, 5, 6])
        self.assertIn("best_score", result)
        self.assertIn("average_score", result)
        self.assertEqual(len(result["sorted"]), 6)

    def test_anti_pattern_single_ticket_helper(self):
        ticket = generate_single_anti_pattern_ticket(seed=123456)
        self.assertEqual(len(ticket), 6)
        self.assertEqual(len(set(ticket)), 6)
        self.assertEqual(tuple(sorted(ticket)), ticket)
        self.assertTrue(all(1 <= n <= 45 for n in ticket))
        self.assertIn(sum(n >= 32 for n in ticket), {3, 4, 5})

    def test_anti_pattern_multi_seed_constraints_and_diversity(self):
        tickets = [generate_single_anti_pattern_ticket(seed=1000 + idx) for idx in range(8)]
        self.assertGreaterEqual(len(set(tickets)), 4)

        engine = AntiPatternLottoV2(LottoConfig(seed=2026))
        for ticket in tickets:
            self.assertTrue(engine.is_valid(ticket))
            self.assertGreaterEqual(sum(ticket), 138)
            self.assertLessEqual(sum(n <= 12 for n in ticket), 1)
            self.assertLessEqual(sum(n in engine.popular_numbers for n in ticket), 1)
            self.assertLessEqual(engine.repeated_last_digit_penalty(ticket), 1)
            self.assertGreaterEqual(engine.decade_bucket_count(ticket), 4)


class StreamlitAppSmokeTest(unittest.TestCase):
    def test_login_screen_renders(self):
        at = AppTest.from_file(str(APP_PATH))
        at.run(timeout=60)

        self.assertEqual(len(at.text_input), 1)
        self.assertEqual(at.text_input[0].label, "입장 비밀번호")
        self.assertTrue(any(button.label == "입장하기" for button in at.button))

    def test_authenticated_dashboard_renders_cleaner_home(self):
        at = _build_authenticated_app()
        at.run(timeout=120)

        markdown_blob = "\n".join((node.value or "") for node in at.markdown)
        self.assertNotIn("command center", markdown_blob.lower())
        self.assertNotIn("추천 시작 전에 현재 분석 상태를 먼저 확인하세요", markdown_blob)
        self.assertIn("Data Algorithm Intelligence", markdown_blob)
        self.assertNotIn("분석 회차", markdown_blob)
        self.assertIn("수동 번호 점수 확인", markdown_blob)
        self.assertNotIn("1번 기준 영역과 2번 영역을 카드 단위로 분리했습니다.", markdown_blob)
        self.assertEqual(len(at.number_input), 6)
        self.assertNotIn("사용 제한 현황", markdown_blob)
        self.assertNotIn("추천 실행 → 수동 검증 → 로그 히스토리 확인까지 한 흐름으로 이어지도록 홈 화면 동선을 다시 정리했습니다.", markdown_blob)
        self.assertNotIn("추천 결과 검증용으로 바로 이어서 쓰기 좋게 메인 화면 안에 통합했습니다.", markdown_blob)
        self.assertNotIn("온보딩 가이드", markdown_blob)
        self.assertIn("현재 운영 모드", markdown_blob)
        self.assertIn("패턴 추천 남은 횟수", markdown_blob)
        self.assertIn("확률 추천 남은 횟수", markdown_blob)
        self.assertIn("처음 사용하는 분을 위한 순서", markdown_blob)
        self.assertIn("결과 읽는 방법", markdown_blob)
        self.assertIn("사용 제한 · 작업 상태", markdown_blob)
        self.assertTrue(any(button.label == "패턴 추천 바로 받기" for button in at.button))
        self.assertTrue(any(button.label == "확률 추천 바로 받기" for button in at.button))

    def test_analysis_view_shows_operating_metrics(self):
        at = _build_authenticated_app()
        at.session_state["counts"] = {"prediction": 1, "probability": 2, "manual": 0}
        at.session_state["view"] = "analysis"
        at.run(timeout=120)

        markdown_blob = "\n".join((node.value or "") for node in at.markdown)
        self.assertIn("로그 분석 · 히스토리", markdown_blob)
        self.assertIn("분석 회차", markdown_blob)
        self.assertIn("평균 인접 중복", markdown_blob)
        self.assertIn("시뮬레이션 규모", markdown_blob)
        self.assertIn("패턴 추천 사용 가능", markdown_blob)
        self.assertIn("확률 추천 사용 가능", markdown_blob)
        self.assertIn("현재 운영 모드", markdown_blob)
        self.assertIn("시뮬레이션 규모 설정", markdown_blob)
        self.assertTrue(any(widget.label == "시뮬레이션 규모" for widget in at.number_input))
        self.assertTrue(any(widget.label == "변경 비밀번호" for widget in at.text_input))

    def test_data_gate_keeps_existing_password_label_for_enable(self):
        at = _build_authenticated_app()
        at.session_state["view"] = "data_gate"
        at.session_state["show_data_gate"] = True
        at.run(timeout=120)

        markdown_blob = "\n".join((node.value or "") for node in at.markdown)
        self.assertIn("원본 데이터 접근 확인", markdown_blob)
        self.assertIn("비밀번호를 입력하면 원본 데이터 내용을 확인할 수 있습니다.", markdown_blob)
        self.assertTrue(any(widget.label == "원본 데이터 비밀번호" for widget in at.text_input))

    def test_show_data_view_supports_password_gated_disable(self):
        at = _build_authenticated_app()
        at.session_state["view"] = "show_data"
        at.session_state["show_data_gate"] = True
        at.session_state["data_access_granted"] = True
        at.run(timeout=120)

        markdown_blob = "\n".join((node.value or "") for node in at.markdown)
        self.assertIn("lotto.xlsx 원본 데이터", markdown_blob)
        self.assertIn("원본 데이터 보기 해제", markdown_blob)
        self.assertIn("비밀번호를 입력하면 원본 데이터 보기 권한이 해제됩니다.", markdown_blob)
        self.assertTrue(any(widget.label == "원본 데이터 비밀번호" for widget in at.text_input))
        self.assertTrue(any(button.label == "최신 데이터 다시 확인" for button in at.button))

    def test_solo_button_fills_numbers_without_logging_and_manual_score_keeps_existing_log_flow(self):
        original_exists = MANUAL_LOG_PATH.exists()
        original_bytes = MANUAL_LOG_PATH.read_bytes() if original_exists else b""
        if not original_exists:
            MANUAL_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            MANUAL_LOG_PATH.touch()

        try:
            at = _build_authenticated_app()
            at.run(timeout=120)
            solo_button = next(button for button in at.button if button.label == "나혼자 당첨")
            score_button_label = "점수 계산하기"
            size_before = MANUAL_LOG_PATH.stat().st_size

            solo_button.click().run(timeout=120)
            values_after_solo = [widget.value for widget in at.number_input]
            self.assertTrue(any(button.label == score_button_label for button in at.button))
            self.assertTrue(all(value is not None for value in values_after_solo))
            self.assertEqual(len(set(values_after_solo)), 6)
            self.assertEqual(MANUAL_LOG_PATH.stat().st_size, size_before)

            solo_button = next(button for button in at.button if button.label == "나혼자 당첨")
            solo_button.click().run(timeout=120)
            values_after_second_solo = [widget.value for widget in at.number_input]
            self.assertNotEqual(values_after_solo, values_after_second_solo)
            self.assertEqual(len(set(values_after_second_solo)), 6)
            self.assertEqual(MANUAL_LOG_PATH.stat().st_size, size_before)

            score_button = next(button for button in at.button if button.label == score_button_label)
            score_button.click().run(timeout=120)
            self.assertEqual(at.session_state["view"], "manual")
            self.assertGreater(MANUAL_LOG_PATH.stat().st_size, size_before)
            self.assertTrue(any("수동 점수 결과를 logs/manual_score_log.jsonl 파일에 저장했습니다." in msg.value for msg in at.success))
        finally:
            if original_exists:
                MANUAL_LOG_PATH.write_bytes(original_bytes)
            elif MANUAL_LOG_PATH.exists():
                MANUAL_LOG_PATH.unlink()


class LogAnalysisRegressionTest(unittest.TestCase):
    def test_same_second_analysis_runs_keep_all_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            shutil.copy2(EXCEL_PATH, base_dir / "lotto.xlsx")

            with patch("analysis.utc_now_iso", return_value="2026-04-20T00:00:00+00:00"):
                first = analyze_logs(base_dir, base_dir / "lotto.xlsx")
                second = analyze_logs(base_dir, base_dir / "lotto.xlsx")

            history_df = load_combined_log_history(base_dir)
            analysis_df = history_df[history_df["log_type"] == "analysis"].copy()

            self.assertEqual(len(analysis_df), 2)
            self.assertNotEqual(first["run_id"], second["run_id"])
            self.assertEqual(analysis_df["run_id"].nunique(), 2)

    def test_period_summary_contains_statistical_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            shutil.copy2(EXCEL_PATH, base_dir / "lotto.xlsx")
            log_dir = base_dir / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)

            persist_log_record(
                log_dir,
                "manual",
                {
                    "timestamp": "2026-04-20T00:00:00+00:00",
                    "run_id": "manual-run-1",
                    "score": -5.0,
                    "best_score": -5.0,
                    "avg_gap_factor": 1.1,
                    "avg_probability_weight": 0.9,
                    "target_round": 1221,
                },
            )
            persist_log_record(
                log_dir,
                "manual",
                {
                    "timestamp": "2026-04-20T12:00:00+00:00",
                    "run_id": "manual-run-2",
                    "score": -7.0,
                    "best_score": -7.0,
                    "avg_gap_factor": 1.3,
                    "avg_probability_weight": 1.1,
                    "target_round": 1221,
                },
            )

            history_df = enrich_history_dataframe(load_combined_log_history(base_dir))
            daily_summary = build_period_summary(history_df, "date_kst")

            self.assertFalse(daily_summary.empty)
            self.assertIn("unique_runs", daily_summary.columns)
            self.assertIn("median_score", daily_summary.columns)
            self.assertIn("score_std", daily_summary.columns)
            self.assertIn("score_coverage", daily_summary.columns)
            self.assertTrue((daily_summary["unique_runs"] >= 1).all())


class UpdatePipelineRegressionTest(unittest.TestCase):
    def test_update_excel_supports_custom_excel_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_excel = Path(tmpdir) / "lotto.xlsx"
            shutil.copy2(EXCEL_PATH, temp_excel)
            latest_round = int(pd.read_excel(temp_excel)["회차"].max())
            fake_page = f"""
            <div class="card text-center border-primary mt-3">
                <div class="card-header">제 {latest_round}회</div>
                <span class="numberCircle"><strong>1</strong></span>
                <span class="numberCircle"><strong>2</strong></span>
                <span class="numberCircle"><strong>3</strong></span>
                <span class="numberCircle"><strong>4</strong></span>
                <span class="numberCircle"><strong>5</strong></span>
                <span class="numberCircle"><strong>6</strong></span>
                <div class="text-muted">2026년 04월 18일 추첨</div>
            </div>
            """

            with patch("update_lotto.fetch_page", return_value=fake_page):
                updated_df, mode = update_excel(temp_excel)

            reloaded_df = pd.read_excel(temp_excel)
            self.assertEqual(mode, "noop")
            self.assertEqual(int(updated_df.iloc[0]["회차"]), latest_round)
            self.assertEqual(int(reloaded_df["회차"].max()), latest_round)
            self.assertIn("출처", reloaded_df.columns)
            self.assertIn("수집페이지", reloaded_df.columns)

    def test_weekly_workflow_keeps_sunday_kst_schedule_and_update_step(self):
        workflow_path = PROJECT_DIR / ".github" / "workflows" / "weekly-lotto-analysis.yml"
        workflow_text = workflow_path.read_text(encoding="utf-8")

        self.assertIn("cron: '5 16 * * 6'", workflow_text)
        self.assertIn("run: python update_lotto.py", workflow_text)
        self.assertIn("git add lotto.xlsx logs reports", workflow_text)


if __name__ == "__main__":
    unittest.main()
