import json
import os
from datetime import date
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from anti_pattern_lotto import (
    AntiPatternLottoV2,
    LottoConfig,
    generate_prime_composite_stats_ticket,
    generate_single_anti_pattern_ticket,
    prime_composite_triple_pattern,
)
from analysis import analyze_logs
import app as app_module
from app import LottoPredictor
from history_analysis import build_period_summary, enrich_history_dataframe
from log_utils import (
    LOG_FILE_MAP,
    ensure_runtime_dirs,
    load_app_state,
    load_combined_log_history,
    persist_log_record,
    reset_runtime_persistence_caches,
    save_app_state,
)
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

    def test_prime_composite_stats_ticket_helper_uses_historical_pattern_buckets(self):
        ticket = generate_prime_composite_stats_ticket(EXCEL_PATH, seed=20260421)
        self.assertEqual(len(ticket), 6)
        self.assertEqual(len(set(ticket)), 6)
        self.assertEqual(tuple(sorted(ticket)), ticket)
        self.assertTrue(all(1 <= n <= 45 for n in ticket))

        df = pd.read_excel(EXCEL_PATH)
        observed_patterns = {
            prime_composite_triple_pattern(tuple(sorted(int(row[column]) for column in df.columns if str(column).startswith("번호"))))
            for _, row in df.iterrows()
        }
        self.assertIn(prime_composite_triple_pattern(ticket), observed_patterns)

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


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else []

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class RemotePersistenceRegressionTest(unittest.TestCase):
    def setUp(self):
        reset_runtime_persistence_caches()

    def tearDown(self):
        reset_runtime_persistence_caches()

    def test_remote_bootstrap_restores_state_and_logs_after_local_reset(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            remote_state = {
                "counts": {"prediction": 2, "probability": 1, "manual": 4},
                "unlock_granted": True,
                "data_access_granted": True,
                "updated_at": "2026-04-20T00:00:00+00:00",
                "simulation_count": 7000,
            }
            remote_payload = {
                "record_uid": "manual-remote-1",
                "timestamp": "2026-04-20T00:00:00+00:00",
                "run_id": "manual-run-remote",
                "log_type": "manual",
                "source_round": 1220,
                "target_round": 1221,
                "numbers": [3, 11, 19, 27, 35, 43],
                "input_numbers": [3, 11, 19, 27, 35, 43],
                "best_order": [3, 11, 19, 27, 35, 43],
                "best_score": -4.2,
                "average_score": -5.1,
                "input_order_score": -4.2,
                "probability_score": -2.4,
                "avg_gap_factor": 1.12,
                "avg_probability_weight": 0.94,
            }

            def fake_request(method, url, headers=None, params=None, json=None, timeout=None):
                if method == "GET" and url.endswith("/lotto_app_state"):
                    return _FakeResponse(200, [{"payload_json": remote_state, "updated_at": remote_state["updated_at"]}])
                if method == "GET" and url.endswith("/lotto_log_records"):
                    return _FakeResponse(200, [{"payload_json": remote_payload}])
                raise AssertionError(f"unexpected request: {method} {url}")

            env = {
                "LOTTO_PERSISTENCE_BACKEND": "supabase",
                "LOTTO_SUPABASE_URL": "https://example.supabase.co",
                "LOTTO_SUPABASE_KEY": "test-key",
                "LOTTO_SUPABASE_STATE_TABLE": "lotto_app_state",
                "LOTTO_SUPABASE_LOG_TABLE": "lotto_log_records",
                "LOTTO_SUPABASE_STATE_KEY": "main",
            }
            with patch.dict(os.environ, env, clear=False), patch("log_utils.requests.request", side_effect=fake_request):
                ensure_runtime_dirs(base_dir)
                loaded_state = load_app_state(base_dir)
                history_df = load_combined_log_history(base_dir)

            self.assertEqual(loaded_state["simulation_count"], 7000)
            self.assertTrue(loaded_state["unlock_granted"])
            self.assertEqual(int(history_df.iloc[0]["target_round"]), 1221)
            self.assertEqual(history_df.iloc[0]["numbers"], [3, 11, 19, 27, 35, 43])
            self.assertTrue((base_dir / "logs" / "app_state.json").exists())
            self.assertTrue((base_dir / "logs" / LOG_FILE_MAP["manual"]).exists())

    def test_remote_persistence_mirrors_state_and_logs_on_write(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            posted_rows = []

            def fake_request(method, url, headers=None, params=None, json=None, timeout=None):
                if method == "GET" and url.endswith("/lotto_app_state"):
                    return _FakeResponse(200, [])
                if method == "GET" and url.endswith("/lotto_log_records"):
                    return _FakeResponse(200, [])
                if method == "POST":
                    posted_rows.append((url, json))
                    return _FakeResponse(201, [])
                raise AssertionError(f"unexpected request: {method} {url}")

            env = {
                "LOTTO_PERSISTENCE_BACKEND": "supabase",
                "LOTTO_SUPABASE_URL": "https://example.supabase.co",
                "LOTTO_SUPABASE_KEY": "test-key",
                "LOTTO_SUPABASE_STATE_TABLE": "lotto_app_state",
                "LOTTO_SUPABASE_LOG_TABLE": "lotto_log_records",
                "LOTTO_SUPABASE_STATE_KEY": "main",
            }
            with patch.dict(os.environ, env, clear=False), patch("log_utils.requests.request", side_effect=fake_request):
                save_app_state(
                    base_dir,
                    counts={"prediction": 1, "probability": 2, "manual": 3},
                    unlock_granted=True,
                    data_access_granted=True,
                    simulation_count=9000,
                )
                persist_log_record(
                    base_dir / "logs",
                    "manual",
                    {
                        "timestamp": "2026-04-20T01:00:00+00:00",
                        "run_id": "manual-local-1",
                        "numbers": [1, 9, 17, 25, 33, 41],
                        "best_order": [1, 9, 17, 25, 33, 41],
                        "best_score": -3.2,
                        "average_score": -4.0,
                        "input_order_score": -3.2,
                        "probability_score": -2.0,
                    },
                )

            self.assertEqual(len(posted_rows), 2)
            self.assertTrue(any(url.endswith("/lotto_app_state") for url, _ in posted_rows))
            self.assertTrue(any(url.endswith("/lotto_log_records") for url, _ in posted_rows))
            state_post = next(payload for url, payload in posted_rows if url.endswith("/lotto_app_state"))
            log_post = next(payload for url, payload in posted_rows if url.endswith("/lotto_log_records"))
            self.assertEqual(state_post[0]["payload_json"]["simulation_count"], 9000)
            self.assertEqual(log_post[0]["payload_json"]["log_type"], "manual")


class DefaultStateRegressionTest(unittest.TestCase):
    def setUp(self):
        reset_runtime_persistence_caches()

    def tearDown(self):
        reset_runtime_persistence_caches()

    def test_missing_state_defaults_to_unlimited_start_and_zero_counts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            state = load_app_state(base_dir)

        self.assertTrue(state["unlock_granted"])
        self.assertEqual(state["counts"], {"prediction": 0, "probability": 0, "manual": 0})


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


class ReportArtifactRegressionTest(unittest.TestCase):
    def test_report_file_path_falls_back_to_default_name_when_map_key_missing(self):
        report_dir = PROJECT_DIR / "reports"

        with patch.dict(app_module.REPORT_FILE_MAP, {}, clear=True):
            resolved = app_module._report_file_path(report_dir, "daily_summary", "daily_log_summary.csv")
            df = app_module._read_report_csv(report_dir, "daily_summary", "daily_log_summary.csv")

        self.assertEqual(resolved, report_dir / "daily_log_summary.csv")
        self.assertFalse(df.empty)


class LogDetailTableRegressionTest(unittest.TestCase):
    def test_log_detail_table_shows_all_rows_when_preview_limit_disabled(self):
        rows = [
            {
                "log_type": "prediction",
                "timestamp_kst": f"2026-04-20 10:{idx % 60:02d}:00",
                "target_round": 1200 + idx,
                "numbers_text": f"{idx:02d}, {idx + 1:02d}, {idx + 2:02d}, {idx + 3:02d}, {idx + 4:02d}, {idx + 5:02d}",
                "score_metric": float(idx),
                "run_id": f"run-{idx}",
            }
            for idx in range(150)
        ]
        logs_df = pd.DataFrame(rows)
        captured = {}

        def _capture_dataframe(data, **kwargs):
            captured["row_count"] = len(data)

        with (
            patch.object(app_module.st, "markdown"),
            patch.object(app_module.st, "caption") as caption_mock,
            patch.object(app_module.st, "dataframe", side_effect=_capture_dataframe),
            patch.object(app_module.st, "download_button"),
        ):
            app_module._render_log_detail_table(logs_df, "패턴 분석 로그", "prediction_log", preview_limit=None)

        self.assertEqual(captured.get("row_count"), 150)
        caption_text = " ".join(str(call.args[0]) for call in caption_mock.call_args_list if call.args)
        self.assertIn("150건", caption_text)
        self.assertIn("화면에 모두 표시", caption_text)


class HistoryMatchBackfillRegressionTest(unittest.TestCase):
    def test_history_logs_are_enriched_with_actual_numbers_matches_and_prize_labels(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_excel = Path(tmpdir) / "lotto.xlsx"
            df = pd.read_excel(EXCEL_PATH)
            next_round = int(pd.to_numeric(df["회차"], errors="coerce").dropna().max()) + 1
            appended_row = {
                "회차": next_round,
                "추첨일": "2026.04.25",
                "번호1": 1,
                "번호2": 2,
                "번호3": 3,
                "번호4": 4,
                "번호5": 5,
                "번호6": 6,
                "보너스": 7,
            }
            extended_df = pd.concat([pd.DataFrame([appended_row]), df], ignore_index=True)
            extended_df.to_excel(temp_excel, index=False)

            history_df = pd.DataFrame(
                [
                    {
                        "log_type": "prediction",
                        "target_round": next_round,
                        "numbers": [1, 2, 3, 4, 5, 6],
                        "numbers_text": "01, 02, 03, 04, 05, 06",
                        "timestamp_kst": "2026-04-26 12:00:00",
                    },
                    {
                        "log_type": "probability",
                        "target_round": next_round,
                        "numbers": [1, 2, 3, 4, 5, 7],
                        "numbers_text": "01, 02, 03, 04, 05, 07",
                        "timestamp_kst": "2026-04-26 12:01:00",
                    },
                    {
                        "log_type": "manual",
                        "target_round": next_round,
                        "numbers": [1, 2, 3, 7, 8, 9],
                        "numbers_text": "01, 02, 03, 07, 08, 09",
                        "input_numbers": [1, 2, 3, 7, 8, 9],
                        "input_numbers_text": "01, 02, 03, 07, 08, 09",
                        "timestamp_kst": "2026-04-26 12:02:00",
                    },
                ]
            )

            enriched = app_module._enrich_logs_with_actual_results(
                history_df,
                temp_excel,
                app_module._file_cache_token(temp_excel),
            )
            display_df = app_module._history_display_df(enriched)

            self.assertEqual(enriched.iloc[0]["matched_numbers_text"], "01, 02, 03, 04, 05, 06")
            self.assertEqual(enriched.iloc[0]["prize_label"], "1등")
            self.assertEqual(enriched.iloc[1]["matched_numbers_text"], "01, 02, 03, 04, 05")
            self.assertEqual(enriched.iloc[1]["prize_label"], "2등")
            self.assertEqual(enriched.iloc[2]["matched_numbers_text"], "01, 02, 03")
            self.assertEqual(enriched.iloc[2]["prize_label"], "5등")
            self.assertIn("실제당첨번호", display_df.columns)
            self.assertIn("일치번호", display_df.columns)
            self.assertIn("당첨결과", display_df.columns)
            self.assertEqual(display_df.iloc[0]["실제당첨번호"], "01, 02, 03, 04, 05, 06")
            self.assertEqual(display_df.iloc[1]["당첨결과"], "2등")
            self.assertEqual(display_df.iloc[2]["일치번호"], "01, 02, 03")


class SingleLogTabRegressionTest(unittest.TestCase):
    def test_single_log_tab_uses_date_filter_and_removes_recent_saved_metric(self):
        logs_df = pd.DataFrame(
            [
                {
                    "log_type": "prediction",
                    "timestamp_kst": "2026-04-20 10:00:00",
                    "date_kst": "2026-04-20",
                    "target_round": 1220,
                    "numbers_text": "1, 2, 3, 4, 5, 6",
                    "score_metric": 5.0,
                    "run_id": "run-1",
                },
                {
                    "log_type": "prediction",
                    "timestamp_kst": "2026-04-21 10:00:00",
                    "date_kst": "2026-04-21",
                    "target_round": 1221,
                    "numbers_text": "7, 8, 9, 10, 11, 12",
                    "score_metric": 7.0,
                    "run_id": "run-2",
                },
            ]
        )
        filtered_df = logs_df.iloc[[1]].copy()
        captured = {}

        def _capture_stats_grid(_, items):
            captured["labels"] = [item[0] for item in items]
            captured["values"] = [item[1] for item in items]

        with (
            patch.object(app_module.st, "markdown"),
            patch.object(app_module.st, "caption"),
            patch.object(app_module.st, "info"),
            patch.object(app_module, "_render_log_date_filter", return_value=(filtered_df, "2026-04-21 ~ 2026-04-21")),
            patch.object(app_module, "_render_stats_grid", side_effect=_capture_stats_grid),
            patch.object(app_module, "_render_log_detail_table") as detail_mock,
        ):
            app_module._render_single_log_tab(logs_df, "패턴 분석 로그", "빈 로그")

        self.assertIn("조회 기간", captured.get("labels", []))
        self.assertNotIn("최근 저장", captured.get("labels", []))
        self.assertIn("2026-04-21 ~ 2026-04-21", captured.get("values", []))
        rendered_df = detail_mock.call_args.args[0]
        self.assertEqual(len(rendered_df), 1)
        self.assertEqual(rendered_df.iloc[0]["run_id"], "run-2")


class LogDateFilterResetRegressionTest(unittest.TestCase):
    def test_reset_button_restores_full_period_without_session_state_error(self):
        logs_df = pd.DataFrame(
            [
                {"timestamp_kst": "2026-04-20 10:00:00", "date_kst": "2026-04-20", "score_metric": 1.0},
                {"timestamp_kst": "2026-04-21 10:00:00", "date_kst": "2026-04-21", "score_metric": 2.0},
                {"timestamp_kst": "2026-04-22 10:00:00", "date_kst": "2026-04-22", "score_metric": 3.0},
            ]
        )

        def _render_filter_app():
            import pandas as pd
            import app as app_module

            local_logs_df = pd.DataFrame(
                [
                    {"timestamp_kst": "2026-04-20 10:00:00", "date_kst": "2026-04-20", "score_metric": 1.0},
                    {"timestamp_kst": "2026-04-21 10:00:00", "date_kst": "2026-04-21", "score_metric": 2.0},
                    {"timestamp_kst": "2026-04-22 10:00:00", "date_kst": "2026-04-22", "score_metric": 3.0},
                ]
            )
            filtered_df, period_label = app_module._render_log_date_filter(local_logs_df, "prediction_log")
            st = app_module.st
            st.write(period_label)
            st.write(len(filtered_df))

        at = AppTest.from_function(_render_filter_app)
        at.run(timeout=60)
        at.date_input[0].set_value(date(2026, 4, 21))
        at.date_input[1].set_value(date(2026, 4, 21))
        at.run(timeout=60)

        self.assertEqual(at.session_state["prediction_log_filter_start"], date(2026, 4, 21))
        self.assertEqual(at.session_state["prediction_log_filter_end"], date(2026, 4, 21))

        at.button[0].click()
        at.run(timeout=60)

        self.assertEqual(at.session_state["prediction_log_filter_start"], date(2026, 4, 20))
        self.assertEqual(at.session_state["prediction_log_filter_end"], date(2026, 4, 22))
        self.assertEqual(at.session_state["prediction_log_filter_start_picker"], date(2026, 4, 20))
        self.assertEqual(at.session_state["prediction_log_filter_end_picker"], date(2026, 4, 22))
        self.assertFalse(at.exception)


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


class LogMatchBackfillRegressionTest(unittest.TestCase):
    def test_enrich_logs_with_actual_results_fills_match_numbers_and_prize_labels(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_excel = Path(tmpdir) / "lotto.xlsx"
            df = pd.read_excel(EXCEL_PATH)
            next_round = int(df["회차"].max()) + 1
            new_row = df.iloc[0].copy()
            new_row["회차"] = next_round
            for idx, number in enumerate([1, 2, 3, 4, 5, 6], start=1):
                new_row[f"번호{idx}"] = number
            if "보너스" in df.columns:
                new_row["보너스"] = 7
            if "추첨일" in df.columns:
                new_row["추첨일"] = "2026-04-26"
            augmented_df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
            augmented_df.to_excel(temp_excel, index=False)

            history_df = pd.DataFrame(
                [
                    {
                        "log_type": "prediction",
                        "timestamp_kst": "2026-04-26 10:00:00",
                        "date_kst": "2026-04-26",
                        "target_round": next_round,
                        "numbers": [1, 2, 3, 4, 5, 6],
                        "numbers_text": "01, 02, 03, 04, 05, 06",
                        "run_id": "pred-run",
                    },
                    {
                        "log_type": "probability",
                        "timestamp_kst": "2026-04-26 10:01:00",
                        "date_kst": "2026-04-26",
                        "target_round": next_round,
                        "numbers": [1, 2, 3, 4, 5, 7],
                        "numbers_text": "01, 02, 03, 04, 05, 07",
                        "run_id": "prob-run",
                    },
                    {
                        "log_type": "manual",
                        "timestamp_kst": "2026-04-26 10:02:00",
                        "date_kst": "2026-04-26",
                        "target_round": next_round,
                        "numbers": [11, 12, 13, 14, 15, 16],
                        "numbers_text": "11, 12, 13, 14, 15, 16",
                        "input_numbers": [11, 12, 13, 14, 15, 16],
                        "input_numbers_text": "11, 12, 13, 14, 15, 16",
                        "run_id": "manual-run",
                    },
                ]
            )

            cache_token = app_module._file_cache_token(temp_excel)
            enriched = app_module._enrich_logs_with_actual_results(history_df, temp_excel, cache_token)

            self.assertEqual(enriched.loc[0, "matched_numbers_text"], "01, 02, 03, 04, 05, 06")
            self.assertEqual(enriched.loc[0, "prize_label"], "1등")
            self.assertEqual(enriched.loc[1, "matched_numbers_text"], "01, 02, 03, 04, 05")
            self.assertEqual(enriched.loc[1, "prize_label"], "2등")
            self.assertEqual(enriched.loc[2, "matched_numbers_text"], "-")
            self.assertEqual(enriched.loc[2, "prize_label"], "낙점")

            display_df = app_module._history_display_df(enriched)
            self.assertIn("실제당첨번호", display_df.columns)
            self.assertIn("보너스번호", display_df.columns)
            self.assertIn("일치번호", display_df.columns)
            self.assertIn("당첨결과", display_df.columns)
            self.assertEqual(display_df.iloc[0]["당첨결과"], "1등")
            self.assertEqual(display_df.iloc[1]["당첨결과"], "2등")
            self.assertEqual(display_df.iloc[2]["당첨결과"], "낙점")

    def test_history_display_df_sorts_prize_results_from_first_to_miss_within_same_round(self):
        history_df = pd.DataFrame(
            [
                {
                    "log_type": "manual",
                    "timestamp_kst": "2026-04-26 10:02:00",
                    "date_kst": "2026-04-26",
                    "target_round": 1221,
                    "candidate_rank": 3,
                    "numbers_text": "11, 12, 13, 14, 15, 16",
                    "prize_label": "낙점",
                    "prize_order": 6,
                    "hit_count": 0,
                    "run_id": "manual-run",
                },
                {
                    "log_type": "prediction",
                    "timestamp_kst": "2026-04-26 10:00:00",
                    "date_kst": "2026-04-26",
                    "target_round": 1221,
                    "candidate_rank": 2,
                    "numbers_text": "01, 02, 03, 04, 05, 07",
                    "prize_label": "2등",
                    "prize_order": 2,
                    "hit_count": 5,
                    "run_id": "pred-run-2",
                },
                {
                    "log_type": "probability",
                    "timestamp_kst": "2026-04-26 10:01:00",
                    "date_kst": "2026-04-26",
                    "target_round": 1221,
                    "candidate_rank": 1,
                    "numbers_text": "01, 02, 03, 04, 05, 06",
                    "prize_label": "1등",
                    "prize_order": 1,
                    "hit_count": 6,
                    "run_id": "prob-run-1",
                },
            ]
        )

        display_df = app_module._history_display_df(history_df)

        self.assertEqual(display_df.iloc[0]["당첨결과"], "1등")
        self.assertEqual(display_df.iloc[1]["당첨결과"], "2등")
        self.assertEqual(display_df.iloc[2]["당첨결과"], "낙점")


class UpdatePipelineRegressionTest(unittest.TestCase):
    def test_update_excel_supports_custom_excel_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_excel = Path(tmpdir) / "lotto.xlsx"
            shutil.copy2(EXCEL_PATH, temp_excel)
            existing_df = pd.read_excel(temp_excel)
            latest_round = int(existing_df["회차"].max())
            expected_bonus = int(existing_df.loc[existing_df["회차"] == latest_round, "보너스"].iloc[0])
            fake_page = f"""
            <div class="card text-center border-primary mt-3">
                <div class="card-header">제 {latest_round}회</div>
                <span class="numberCircle"><strong>1</strong></span>
                <span class="numberCircle"><strong>2</strong></span>
                <span class="numberCircle"><strong>3</strong></span>
                <span class="numberCircle"><strong>4</strong></span>
                <span class="numberCircle"><strong>5</strong></span>
                <span class="numberCircle"><strong>6</strong></span>
                <div class="plusCircle"><i class="fa fa-plus"></i></div>
                <span class="numberCircle"><strong>7</strong></span>
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
            self.assertIn("보너스", reloaded_df.columns)
            self.assertEqual(int(reloaded_df.loc[reloaded_df["회차"] == latest_round, "보너스"].iloc[0]), expected_bonus)

    def test_weekly_workflow_is_manual_only_and_keeps_update_step(self):
        workflow_path = PROJECT_DIR / ".github" / "workflows" / "weekly-lotto-analysis.yml"
        workflow_text = workflow_path.read_text(encoding="utf-8")

        self.assertIn("workflow_dispatch:", workflow_text)
        self.assertNotIn("schedule:", workflow_text)
        self.assertNotIn("cron: '10 15 * * 6'", workflow_text)
        self.assertIn("run: python update_lotto.py", workflow_text)
        self.assertIn("git add lotto.xlsx logs reports", workflow_text)


if __name__ == "__main__":
    unittest.main()
