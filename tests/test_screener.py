import os
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

import pandas as pd
import requests
from src import screener as s


def response(data=None, status=200):
    r = Mock(status_code=status)
    r.json.return_value = {"data": []} if data is None else data
    return r


def financial(code="12340", sales="120", op="24", eps="10", bps="50", year=2026):
    return {"Code": code, "DiscDate": f"{year}-06-01",
            "DocType": "FYFinancialStatements_Consolidated_JP", "CurPerType": "FY",
            "CurPerSt": f"{year-1}-04-01", "CurPerEn": f"{year}-03-31",
            "CurFYSt": f"{year-1}-04-01", "CurFYEn": f"{year}-03-31", "DiscTime": "15:00:00",
            "DiscNo": "1", "Sales": sales, "OP": op, "EPS": eps, "BPS": bps}


class APITests(unittest.TestCase):
    def setUp(self):
        s._last_request_at = None
        self.env = patch.dict(os.environ, {"JQUANTS_API_KEY": "test-key"})
        self.sleep = patch.object(s.time, "sleep")
        self.env.start()
        self.sleeper = self.sleep.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.sleep.stop)

    def test_v2_pagination_keeps_params_and_input(self):
        params = {"date": "20260101"}
        with patch.object(s.requests, "get", side_effect=[
            response({"data": [{"Code": "12340"}], "pagination_key": "next"}),
            response({"data": [{"Code": "56780"}]})]) as get:
            df = s.jquants_get("/fins/summary", params)
        self.assertEqual(df.Code.tolist(), ["12340", "56780"])
        self.assertEqual(params, {"date": "20260101"})
        self.assertEqual(get.call_args.kwargs["params"], {"date": "20260101", "pagination_key": "next"})
        self.assertEqual(get.call_args.kwargs["headers"], {"x-api-key": "test-key"})
        self.assertEqual(get.call_args.args[0], s.BASE_URL + "/fins/summary")
        self.assertEqual(get.call_args.kwargs["timeout"], 30)
        self.assertTrue(self.sleeper.called)

    def test_empty_is_valid(self):
        with patch.object(s.requests, "get", return_value=response()):
            self.assertTrue(s.jquants_get("/fins/summary").empty)

    def test_bad_envelopes_are_failures(self):
        for data in [{}, {"error": "denied"}, {"data": None}, {"data": ["bad"]}, []]:
            with self.subTest(data=data), patch.object(s.requests, "get", return_value=response(data)):
                with self.assertRaisesRegex(RuntimeError, "Invalid J-Quants"):
                    s.jquants_get("/fins/summary")

    def test_bad_json(self):
        r = response()
        r.json.side_effect = ValueError("bad json")
        with patch.object(s.requests, "get", return_value=r):
            with self.assertRaisesRegex(RuntimeError, "JSON"):
                s.jquants_get("/fins/summary")

    def test_permanent_http_errors_fail_without_retry(self):
        for status in [400, 401, 403, 404]:
            with self.subTest(status=status), patch.object(s.requests, "get", return_value=response(status=status)) as get:
                with self.assertRaisesRegex(RuntimeError, str(status)):
                    s.jquants_get("/fins/summary")
                self.assertEqual(get.call_count, 1)

    def test_transient_retry_and_backoff(self):
        for failure in [response(status=429), response(status=503), requests.Timeout(), requests.ConnectionError()]:
            with self.subTest(failure=failure), patch.object(s.requests, "get", side_effect=[failure, response()]) as get:
                self.assertTrue(s.jquants_get("/fins/summary").empty)
                self.assertEqual(get.call_count, 2)
        self.assertIn(unittest.mock.call(120), self.sleeper.call_args_list)

    def test_retry_exhaustion(self):
        for failure in [response(status=429), response(status=500), requests.Timeout()]:
            with self.subTest(failure=failure), patch.object(s.requests, "get", side_effect=[failure] * 3) as get:
                with self.assertRaises(RuntimeError):
                    s.jquants_get("/fins/summary")
                self.assertEqual(get.call_count, 3)

    def test_limiter_covers_separate_calls(self):
        with patch.object(s.time, "monotonic", return_value=100), patch.object(s.requests, "get", return_value=response()):
            s.jquants_get("/fins/summary")
            s.jquants_get("/equities/master")
        self.sleeper.assert_called_once_with(13)

    def test_repeated_pagination_fails(self):
        with patch.object(s.requests, "get", return_value=response({"data": [], "pagination_key": "same"})) as get:
            with self.assertRaisesRegex(RuntimeError, "pagination"):
                s.jquants_get("/fins/summary")
            self.assertEqual(get.call_count, 2)

    def test_missing_credentials_fail_before_http(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(s.requests, "get") as get:
            with self.assertRaisesRegex(RuntimeError, "JQUANTS_API_KEY"):
                s.jquants_get("/fins/summary")
            get.assert_not_called()

    def test_partial_window_failure_is_not_swallowed(self):
        with patch.object(s, "jquants_get", side_effect=[pd.DataFrame([financial()]), RuntimeError("HTTP 403")]):
            with self.assertRaisesRegex(RuntimeError, "403"):
                s.fetch_fin_summary_window(datetime(2026, 10, 3), days=2)

    def test_empty_window_and_weekends(self):
        with patch.object(s, "jquants_get", return_value=pd.DataFrame()) as get:
            self.assertTrue(s.fetch_fin_summary_window(datetime(2026, 10, 5), days=2).empty)
            get.assert_not_called()


class ScreeningTests(unittest.TestCase):
    def run_screen(self, now=None, prev=None, prices=None, info=None, valuation=None):
        now = pd.DataFrame([financial()]) if now is None else now
        prev = pd.DataFrame([financial(sales="100", op="20", year=2025)]) if prev is None else prev
        prices = pd.DataFrame([{"Code": "12340", "C": "100"}]) if prices is None else prices
        info = pd.DataFrame([{"Code": "12340", "CoName": "会社", "CoNameEn": "Company"}]) if info is None else info
        valuation = pd.DataFrame([{ "Code": "12340", "PER": 10, "PBR": 2, "ROE": 0.2}]) if valuation is None else valuation
        with patch.object(s, "fetch_fin_summary_window", side_effect=[now, prev]), patch.object(s, "jquants_get", side_effect=[prices, info, valuation]) as get:
            result = s.screen()
        return result, get

    def test_success_uses_official_master_and_price_date(self):
        result, get = self.run_screen()
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0].CompanyName, "会社")
        self.assertEqual(result.iloc[0].Sales_growth, 20)
        self.assertEqual(result.iloc[0].OP_growth, 20)
        self.assertEqual(result.iloc[0].PER, 10)
        self.assertEqual(get.call_args_list[1].args[0], "/equities/master")
        self.assertEqual(get.call_args_list[0].args[1], get.call_args_list[1].args[1])

    def test_empty_previous_is_explicit_failure_not_keyerror(self):
        with self.assertRaisesRegex(RuntimeError, "前年同期"):
            self.run_screen(prev=pd.DataFrame())

    def test_empty_current_is_failure(self):
        with self.assertRaisesRegex(RuntimeError, "財務サマリー"):
            self.run_screen(now=pd.DataFrame())

    def test_zero_or_missing_comparison_is_excluded(self):
        for value in ["0", "", None]:
            with self.subTest(value=value):
                result, _ = self.run_screen(prev=pd.DataFrame([financial(sales=value, op=value, year=2025)]))
                self.assertTrue(result.empty)

    def test_unmatched_code_is_excluded(self):
        result, _ = self.run_screen(prev=pd.DataFrame([financial(code="56780", year=2025)]))
        self.assertTrue(result.empty)

    def test_missing_numeric_fields_are_excluded(self):
        result, _ = self.run_screen(valuation=pd.DataFrame([{"Code": "12340", "PER": None, "PBR": None, "ROE": None}]))
        self.assertTrue(result.empty)

    def test_empty_master_is_failure(self):
        with self.assertRaisesRegex(RuntimeError, "会社情報"):
            self.run_screen(info=pd.DataFrame())

    def test_schema_mismatch_is_explicit(self):
        for kwargs in [{"prices": pd.DataFrame([{"Code": "12340", "Close": "100"}])},
                       {"info": pd.DataFrame([{"Code": "12340", "CompanyName": "legacy"}])},
                       {"now": pd.DataFrame([{"Code": "12340"}])}]:
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(RuntimeError, "missing columns"):
                self.run_screen(**kwargs)

    def test_price_fallback_only_on_valid_empty_day(self):
        with patch.object(s, "fetch_fin_summary_window", side_effect=[pd.DataFrame([financial()]), pd.DataFrame([financial(sales="100", op="20", year=2025)])]), patch.object(s, "jquants_get", side_effect=[pd.DataFrame(), pd.DataFrame([{"Code": "12340", "C": "100"}]), pd.DataFrame([{"Code": "12340", "CoName": "会社"}]), pd.DataFrame([{"Code": "12340", "PER": 10, "PBR": 2, "ROE": 0.2}])]) as get:
            self.assertEqual(len(s.screen()), 1)
            self.assertEqual(get.call_count, 4)

    def test_no_prices_is_failure(self):
        with patch.object(s, "fetch_fin_summary_window", side_effect=[pd.DataFrame([financial()]), pd.DataFrame([financial()])]), patch.object(s, "jquants_get", return_value=pd.DataFrame()):
            with self.assertRaisesRegex(RuntimeError, "株価"):
                s.screen()

    def test_whole_latest_disclosure_no_column_mixing(self):
        old = financial()
        new = financial(eps="")
        new.update(DiscTime="16:00:00", DiscNo="2")
        df = s.latest_financials(pd.DataFrame([new, old]))
        self.assertEqual(df.iloc[0].EPS, "")
        self.assertEqual(df.iloc[0].DiscNo, "2")


class ComparisonRegressionTests(unittest.TestCase):
    def test_dividend_and_forecast_revision_do_not_replace_statement(self):
        for doc_type in ["DividendForecastRevision", "EarnForecastRevision"]:
            with self.subTest(doc_type=doc_type):
                actual = financial()
                revision = financial(sales="", op="", eps="", bps="")
                revision.update(DocType=doc_type, DiscTime="16:00:00", DiscNo="2")
                result, _ = ScreeningTests().run_screen(now=pd.DataFrame([actual, revision]))
                self.assertEqual(len(result), 1)
                self.assertEqual(result.iloc[0].Sales_growth, 20)

    def test_period_and_accounting_mismatches_are_excluded(self):
        for changed in [{"CurPerType": "3Q"}, {"CurPerEn": "2024-12-31"},
                        {"CurPerSt": "2024-07-01"}, {"CurFYEn": "2025-06-30"},
                        {"CurFYSt": "2024-07-01"},
                        {"DocType": "FYFinancialStatements_NonConsolidated_JP"},
                        {"DocType": "FYFinancialStatements_Consolidated_IFRS"},
                        {"CurFYEn": ""}, {"CurPerEn": "invalid"}]:
            previous = financial(sales="100", op="20", year=2025)
            previous.update(changed)
            with self.subTest(changed=changed):
                result, _ = ScreeningTests().run_screen(prev=pd.DataFrame([previous]))
                self.assertTrue(result.empty)

    def test_previous_matching_statement_survives_other_period(self):
        matched = financial(sales="100", op="20", year=2025)
        other = financial(sales="1", op="1", year=2025)
        other.update(CurPerType="3Q", CurPerEn="2024-12-31", DiscNo="2", DiscTime="16:00:00")
        result, _ = ScreeningTests().run_screen(prev=pd.DataFrame([matched, other]))
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0].Sales_growth, 20)

    def test_correcting_statement_is_used_without_backfilling_blanks(self):
        old = financial()
        corrected = financial(sales="", op="")
        corrected.update(DiscNo="2", DiscTime="16:00:00")
        result, _ = ScreeningTests().run_screen(now=pd.DataFrame([old, corrected]))
        self.assertTrue(result.empty)

    def test_previous_correcting_statement_is_used(self):
        old = financial(sales="100", op="20", year=2025)
        corrected = financial(sales="110", op="22", year=2025)
        corrected.update(DiscNo="2", DiscTime="16:00:00")
        df = s.compare_financials(pd.DataFrame([financial()]), pd.DataFrame([corrected, old]))
        self.assertEqual(df.iloc[0].Sales_prev, 110)

    def test_leap_year_period_matching(self):
        current = financial()
        current.update(CurPerSt="2023-03-01", CurPerEn="2024-02-29", CurFYSt="2023-03-01", CurFYEn="2024-02-29")
        previous = financial(sales="100", op="20", year=2025)
        previous.update(CurPerSt="2022-03-01", CurPerEn="2023-02-28", CurFYSt="2022-03-01", CurFYEn="2023-02-28")
        df = s.compare_financials(pd.DataFrame([current]), pd.DataFrame([previous]))
        self.assertEqual(df.iloc[0].Sales_growth, 20)

    def test_revision_only_windows_produce_no_candidates(self):
        revision = financial()
        revision["DocType"] = "DividendForecastRevision"
        for side in ["now", "prev"]:
            with self.subTest(side=side):
                result, _ = ScreeningTests().run_screen(**{side: pd.DataFrame([revision])})
                self.assertTrue(result.empty)

    def test_missing_period_schema_is_not_silently_accepted(self):
        df = pd.DataFrame([financial()]).drop(columns=["CurPerType"])
        with self.assertRaisesRegex(RuntimeError, "missing columns"):
            s.compare_financials(df, pd.DataFrame([financial(year=2025)]))

    def test_official_valuation_ignores_quarter_eps_and_summary_roe(self):
        actual = financial(eps="0.01", bps="1")
        actual["ROE"] = "0.001"
        result, get = ScreeningTests().run_screen(now=pd.DataFrame([actual]))
        self.assertEqual(len(result), 1)
        row = result.iloc[0]
        self.assertEqual((row.PER, row.PBR, row.ROE), (10, 2, 20))
        self.assertEqual(get.call_args.args[0], "/equities/valuation")
        self.assertEqual(get.call_args.args[1], get.call_args_list[0].args[1])

    def test_unavailable_or_nonfinite_valuations_are_excluded(self):
        for value in [None, "", "bad", float("inf"), -float("inf")]:
            with self.subTest(value=value):
                valuation = pd.DataFrame([{"Code": "12340", "PER": value, "PBR": value, "ROE": value}])
                result, _ = ScreeningTests().run_screen(valuation=valuation)
                self.assertTrue(result.empty)

    def test_empty_valuation_or_wrong_schema_fails(self):
        for frame, message in [(pd.DataFrame(), "バリュエーション"),
                               (pd.DataFrame([{"Code": "12340"}]), "missing columns")]:
            with self.subTest(message=message), self.assertRaisesRegex(RuntimeError, message):
                ScreeningTests().run_screen(valuation=frame)

    def test_valuation_api_failure_propagates(self):
        with patch.object(s, "fetch_fin_summary_window", side_effect=[pd.DataFrame([financial()]), pd.DataFrame([financial(sales="100", op="20", year=2025)])]), patch.object(s, "jquants_get", side_effect=[pd.DataFrame([{"Code": "12340", "C": "100"}]), pd.DataFrame([{"Code": "12340", "CoName": "会社"}]), RuntimeError("HTTP 403")]):
            with self.assertRaisesRegex(RuntimeError, "403"):
                s.screen()


class NotificationTests(unittest.TestCase):
    def test_empty_result_notification_timeout(self):
        with patch.dict(os.environ, {"NTFY_TOPIC": "test"}), patch.object(s.requests, "post", return_value=response()) as post:
            s.notify(pd.DataFrame())
            self.assertEqual(post.call_args.kwargs["timeout"], 30)
            self.assertIn("該当銘柄なし", post.call_args.kwargs["data"].decode())

    def test_failed_notification_fails_job(self):
        with patch.dict(os.environ, {"NTFY_TOPIC": "test"}), patch.object(s.requests, "post", return_value=response(status=503)):
            with self.assertRaisesRegex(RuntimeError, "ntfy HTTP 503"):
                s.notify(pd.DataFrame())

    def test_screen_failure_never_sends_no_candidates(self):
        with patch.dict(os.environ, {"NTFY_TOPIC": "test", "JQUANTS_API_KEY": "test"}), patch.object(s, "screen", side_effect=RuntimeError("incomplete")), patch.object(s, "notify") as notify:
            with self.assertRaises(RuntimeError):
                s.main()
            notify.assert_not_called()


if __name__ == "__main__":
    unittest.main()
