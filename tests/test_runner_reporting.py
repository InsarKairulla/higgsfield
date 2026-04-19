from __future__ import annotations

import copy
import json
import os
import shutil
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from evals.cases import load_case
from evals.reporting import build_diff, format_report_text, load_report
from evals.runner import (
    _load_default_run_agent,
    discover_saved_traces,
    rescore_saved_traces,
    run_live_suite,
)
from evals.viewer import render_run_viewer


ROOT = Path(__file__).resolve().parents[1]


class _FakeRunResult:
    def __init__(self, payload: dict):
        self._payload = payload

    def to_dict(self) -> dict:
        return copy.deepcopy(self._payload)


def _fixture_trace() -> dict:
    return json.loads((ROOT / "tests" / "fixtures" / "voyager_trace.json").read_text(encoding="utf-8"))


def _make_case_dir(base_dir: str | Path, *case_names: str) -> Path:
    destination = Path(base_dir) / "cases"
    destination.mkdir()
    for case_name in case_names:
        shutil.copy2(ROOT / "cases" / case_name, destination / case_name)
    return destination


class LiveRunnerReportingTests(unittest.TestCase):
    def test_default_runner_loads_dotenv_before_importing_agent(self) -> None:
        fake_run_agent = object()
        fake_agent = types.SimpleNamespace(run_agent=fake_run_agent)

        with mock.patch("evals.runner.load_dotenv") as mocked_load_dotenv:
            with mock.patch("evals.runner._ensure_corpus_available") as mocked_corpus:
                with mock.patch.dict("sys.modules", {"agent": fake_agent}):
                    loaded = _load_default_run_agent()

        self.assertIs(loaded, fake_run_agent)
        mocked_load_dotenv.assert_called_once()
        mocked_corpus.assert_called_once()

    def test_live_runner_retries_transient_errors_and_persists_attempts(self) -> None:
        failing = _fixture_trace()
        failing["stopped_reason"] = "error"
        failing["final_answer"] = None
        failing["citations"] = []
        failing["error"] = "RateLimitError: 429 too many requests"
        failing["messages"] = [{"role": "user", "content": failing["question"]}]

        successful = _fixture_trace()
        calls = {"count": 0}

        def fake_run_agent(question: str) -> _FakeRunResult:
            calls["count"] += 1
            if calls["count"] == 1:
                return _FakeRunResult(failing)
            return _FakeRunResult(successful)

        with tempfile.TemporaryDirectory() as tmpdir:
            cases_dir = _make_case_dir(tmpdir, "voyager_happy_path.yaml")
            result = run_live_suite(
                cases_dir=cases_dir,
                output_root=tmpdir,
                concurrency=1,
                repeats=1,
                max_retries=2,
                retry_delay_s=0.0,
                run_agent_fn=fake_run_agent,
            )

            report = result["report"]
            case_entry = report["cases"][0]

            self.assertEqual(calls["count"], 2)
            self.assertEqual(case_entry["pass_summary"], "1/1 passed")
            self.assertEqual(case_entry["repeats"][0]["attempt_count"], 2)
            self.assertTrue(Path(case_entry["repeats"][0]["trace_path"]).name.endswith("attempt002.json"))
            trace_files = sorted((result["run_dir"] / "traces").glob("*.json"))
            self.assertEqual(len(trace_files), 2)

    def test_live_runner_does_not_retry_assertion_failures(self) -> None:
        failing = _fixture_trace()
        failing["final_answer"] = "Voyager 1 crossed the heliopause in 2013."
        failing["messages"][-2]["tool_calls"][0]["args"]["answer"] = failing["final_answer"]

        calls = {"count": 0}

        def fake_run_agent(question: str) -> _FakeRunResult:
            calls["count"] += 1
            return _FakeRunResult(failing)

        with tempfile.TemporaryDirectory() as tmpdir:
            cases_dir = _make_case_dir(tmpdir, "voyager_happy_path.yaml")
            result = run_live_suite(
                cases_dir=cases_dir,
                output_root=tmpdir,
                concurrency=1,
                repeats=1,
                max_retries=3,
                retry_delay_s=0.0,
                run_agent_fn=fake_run_agent,
            )

            case_entry = result["report"]["cases"][0]
            self.assertEqual(calls["count"], 1)
            self.assertEqual(case_entry["repeats"][0]["attempt_count"], 1)

    def test_rescore_saved_traces_works_without_live_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            traces_dir = Path(tmpdir) / "saved_traces"
            traces_dir.mkdir()
            payload = _fixture_trace()
            payload["eval"] = {
                "case_id": "voyager_happy_path",
                "repeat_index": 1,
                "attempt_index": 1,
                "selected_for_scoring": True,
                "transient_error": False,
            }
            trace_path = traces_dir / "voyager.json"
            trace_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

            result = rescore_saved_traces(
                input_dir=traces_dir,
                cases_dir=ROOT / "cases",
                output_dir=Path(tmpdir) / "rescored",
            )

            self.assertEqual(result["report"]["summary"]["passed_repeats"], 1)
            self.assertTrue((Path(tmpdir) / "rescored" / "report.html").exists())
            discovered = discover_saved_traces(traces_dir)
            self.assertEqual(len(discovered), 1)

    def test_rescore_saved_traces_keeps_external_trace_paths_valid_for_viewer(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            original_cwd = Path.cwd()
            tmp_path = Path(tmpdir)
            try:
                os.chdir(tmp_path)
                traces_dir = Path("fixtures") / "traces"
                traces_dir.mkdir(parents=True)
                payload = _fixture_trace()
                payload["eval"] = {
                    "case_id": "voyager_happy_path",
                    "repeat_index": 1,
                    "attempt_index": 1,
                    "selected_for_scoring": True,
                    "transient_error": False,
                }
                (traces_dir / "voyager.json").write_text(
                    json.dumps(payload, indent=2),
                    encoding="utf-8",
                )

                result = rescore_saved_traces(
                    input_dir=traces_dir,
                    cases_dir=ROOT / "cases",
                    output_dir=Path("eval_runs") / "judge_rescored_haiku45",
                )

                repeat = result["report"]["cases"][0]["repeats"][0]
                self.assertTrue(Path(repeat["trace_path"]).is_absolute())
                self.assertTrue(Path(repeat["trace_path"]).exists())
                self.assertTrue((Path("eval_runs") / "judge_rescored_haiku45" / "report.html").exists())
            finally:
                os.chdir(original_cwd)

    def test_diff_flags_regressions(self) -> None:
        previous = {
            "run_id": "prev",
            "cases": [
                {
                    "case_id": "voyager_happy_path",
                    "status": "pass",
                    "pass_count": 1,
                    "total_repeats": 1,
                    "pass_summary": "1/1 passed",
                    "failure_reason": "",
                }
            ],
        }
        current = {
            "run_id": "current",
            "cases": [
                {
                    "case_id": "voyager_happy_path",
                    "status": "fail",
                    "pass_count": 0,
                    "total_repeats": 1,
                    "pass_summary": "0/1 passed",
                    "failure_reason": "final answer was wrong",
                }
            ],
        }

        diff = build_diff(current, previous)

        self.assertEqual(len(diff["regressions"]), 1)
        self.assertEqual(diff["regressions"][0]["case_id"], "voyager_happy_path")

    def test_viewer_renders_failed_checks_and_tool_calls(self) -> None:
        trace = _fixture_trace()
        trace["final_answer"] = "Wrong answer"
        trace["messages"][-2]["tool_calls"][0]["args"]["answer"] = "Wrong answer"

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            trace_path = output_dir / "trace.json"
            trace["eval"] = {
                "case_id": "voyager_happy_path",
                "repeat_index": 1,
                "attempt_index": 1,
                "selected_for_scoring": True,
                "transient_error": False,
            }
            trace_path.write_text(json.dumps(trace, indent=2), encoding="utf-8")

            case = load_case(ROOT / "cases" / "voyager_happy_path.yaml")
            score = {
                "case_id": case.case_id,
                "passed": False,
                "failure_reason": "final_answer did not contain '2012'",
                "metrics": [
                    {
                        "name": "hard_assertions",
                        "passed": False,
                        "summary": "final_answer did not contain '2012'",
                        "details": {
                            "assertions": [
                                {
                                    "type": "contains",
                                    "passed": False,
                                    "message": "final_answer did not contain '2012'",
                                }
                            ]
                        },
                    }
                ],
            }
            report = {
                "run_id": "demo",
                "mode": "rescore",
                "summary": {"passed_repeats": 0, "repeat_count": 1, "pass_rate_pct": 0.0},
                "cases": [
                    {
                        "case_id": case.case_id,
                        "status": "fail",
                        "pass_summary": "0/1 passed",
                        "repeats": [
                            {
                                "repeat_index": 1,
                                "trace_path": "trace.json",
                                "score": score,
                            }
                        ],
                    }
                ],
            }

            html = render_run_viewer(report, output_dir)

            self.assertIn("Failed Checks", html)
            self.assertIn("tool call: web_search", html)
            self.assertIn("final_answer did not contain", html)

    def test_report_can_be_reloaded_from_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cases_dir = _make_case_dir(
                tmpdir,
                "voyager_happy_path.yaml",
                "voyager_required_tool_sequence.yaml",
            )
            result = run_live_suite(
                cases_dir=cases_dir,
                output_root=tmpdir,
                concurrency=1,
                repeats=1,
                max_retries=0,
                retry_delay_s=0.0,
                run_agent_fn=lambda question: _FakeRunResult(_fixture_trace()),
            )
            reloaded = load_report(result["report_path"])
            text = format_report_text(reloaded)

            self.assertIn("Cases:", text)
            self.assertEqual(reloaded["summary"]["passed_repeats"], 2)

    def test_report_text_surfaces_runtime_errors_clearly(self) -> None:
        report = {
            "run_id": "demo",
            "mode": "live",
            "summary": {
                "passed_repeats": 0,
                "repeat_count": 1,
                "pass_rate_pct": 0.0,
                "total_cost_usd": 0.0,
                "p50_latency_ms": 10,
                "p95_latency_ms": 10,
                "mean_tool_calls_per_case": 0.0,
                "runtime_error_repeats": 1,
            },
            "cases": [
                {
                    "case_id": "voyager_happy_path",
                    "status": "fail",
                    "pass_summary": "0/1 passed",
                    "failure_reason": "run stopped via 'error' instead of 'finish'",
                    "runtime_error": "runtime error: RuntimeError: ANTHROPIC_API_KEY is not set. See .env.example.",
                }
            ],
            "diff": {},
        }

        text = format_report_text(report)

        self.assertIn("Runtime errors: 1 repeat(s)", text)
        self.assertIn("runtime error: RuntimeError: ANTHROPIC_API_KEY is not set", text)


if __name__ == "__main__":
    unittest.main()
