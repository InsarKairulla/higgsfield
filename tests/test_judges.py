from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from evals.cases import load_case
from evals.judges import build_judge_client, resolve_judge_config
from evals.judges.base import JudgeConfig, JudgeOutput, RubricItemAssessment
from evals.judges.input_builder import build_judge_input
from evals.judges.openai import OpenAIJudge
from evals.judges.rubrics import load_rubric_text
from evals.judges.schema import JudgeSchemaError, parse_judge_response
from evals.scoring import ScoringContext, score_case
from evals.trace import Trace


ROOT = Path(__file__).resolve().parents[1]


class _FakeHTTPResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


class _MockJudgeClient:
    def evaluate(self, judge_input):
        return JudgeOutput(
            metric_name=judge_input.metric_name,
            verdict="pass",
            passed=True,
            score=0.92,
            rationale=f"{judge_input.metric_name} passed in mocked judge",
            rubric_items=[
                RubricItemAssessment(
                    item="Mock rubric item",
                    assessment="pass",
                    evidence="Mocked evidence",
                )
            ],
            failure_modes_detected=[],
            provider="mock",
            model="mock-judge",
            raw_response="{}",
        )


class JudgeSubsystemTests(unittest.TestCase):
    def test_schema_validation_accepts_valid_json(self) -> None:
        raw = """
        {
          "metric_name": "factual_correctness",
          "verdict": "pass",
          "passed": true,
          "score": 0.9,
          "rationale": "The answer is supported by the evidence.",
          "rubric_items": [
            {
              "item": "Uses supported facts",
              "assessment": "pass",
              "evidence": "The fetched page states the same fact."
            }
          ],
          "failure_modes_detected": []
        }
        """

        parsed = parse_judge_response(raw, "factual_correctness")

        self.assertEqual(parsed.metric_name, "factual_correctness")
        self.assertTrue(parsed.passed)
        self.assertEqual(len(parsed.rubric_items), 1)

    def test_schema_validation_rejects_invalid_json_shape(self) -> None:
        raw = """
        {
          "metric_name": "factual_correctness",
          "verdict": "pass",
          "passed": true,
          "score": 1.2,
          "rationale": "bad score",
          "rubric_items": [],
          "failure_modes_detected": []
        }
        """

        with self.assertRaises(JudgeSchemaError):
            parse_judge_response(raw, "factual_correctness")

    def test_rubric_loader_merges_metric_and_case_specific_files(self) -> None:
        case = load_case(ROOT / "cases" / "voyager_ambiguity_disclosure.yaml")

        rubric_text, rubric_paths = load_rubric_text("ambiguity_handling", case, {})

        self.assertIn("Ambiguity Handling Rubric", rubric_text)
        self.assertIn("Case-Specific Guidance: voyager_ambiguity_disclosure", rubric_text)
        self.assertEqual(len(rubric_paths), 2)

    def test_judge_input_builder_collects_pages_and_quotes(self) -> None:
        case = load_case(ROOT / "cases" / "voyager_happy_path.yaml")
        trace = Trace.from_path(ROOT / "tests" / "fixtures" / "voyager_trace.json")
        rubric_text, _ = load_rubric_text("factual_correctness", case, {})

        judge_input = build_judge_input(
            "factual_correctness",
            case,
            trace,
            rubric_text,
            {"focus": "Test focus"},
        )

        self.assertEqual(judge_input.case_id, "voyager_happy_path")
        self.assertEqual(judge_input.question, trace.question)
        self.assertEqual(len(judge_input.fetched_pages), 1)
        self.assertEqual(judge_input.fetched_pages[0].url, "https://corpus.local/nasa-heliopause-announcement")
        self.assertGreaterEqual(len(judge_input.extracted_quotes), 2)
        self.assertTrue(any(quote.source_url for quote in judge_input.extracted_quotes))
        self.assertIn("Test focus", str(judge_input.metric_context))

    def test_provider_selection_supports_openai(self) -> None:
        config = resolve_judge_config(provider="openai", model="gpt-4.1-mini")

        judge_client = build_judge_client(config)

        self.assertTrue(config.enabled)
        self.assertEqual(config.provider, "openai")
        self.assertIsInstance(judge_client, OpenAIJudge)

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-openai-key"}, clear=False)
    @patch("evals.judges.openai.request.urlopen")
    def test_openai_provider_parses_structured_response(self, mock_urlopen) -> None:
        case = load_case(ROOT / "cases" / "voyager_happy_path.yaml")
        trace = Trace.from_path(ROOT / "tests" / "fixtures" / "voyager_trace.json")
        rubric_text, _ = load_rubric_text("factual_correctness", case, {})
        judge_input = build_judge_input(
            "factual_correctness",
            case,
            trace,
            rubric_text,
            {"focus": "Judge provider selection test"},
        )
        mock_urlopen.return_value = _FakeHTTPResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "metric_name": "factual_correctness",
                                    "verdict": "pass",
                                    "passed": True,
                                    "score": 0.88,
                                    "rationale": "The answer matches the retrieved evidence.",
                                    "rubric_items": [
                                        {
                                            "item": "States the correct year",
                                            "assessment": "pass",
                                            "evidence": "The answer and quote both cite 2012.",
                                        }
                                    ],
                                    "failure_modes_detected": [],
                                }
                            )
                        }
                    }
                ]
            }
        )

        judge = OpenAIJudge(JudgeConfig(enabled=True, provider="openai", model="gpt-4.1-mini"))
        result = judge.evaluate(judge_input)

        request_obj = mock_urlopen.call_args.args[0]
        request_payload = json.loads(request_obj.data.decode("utf-8"))
        self.assertEqual(request_payload["model"], "gpt-4.1-mini")
        self.assertEqual(
            request_payload["response_format"]["json_schema"]["schema"]["properties"]["metric_name"]["enum"],
            ["factual_correctness"],
        )
        self.assertEqual(result.provider, "openai")
        self.assertEqual(result.model, "gpt-4.1-mini")
        self.assertTrue(result.passed)
        self.assertEqual(result.metric_name, "factual_correctness")

    def test_mocked_judge_metrics_are_used_when_configured(self) -> None:
        case = load_case(ROOT / "cases" / "voyager_happy_path.yaml")
        trace = Trace.from_path(ROOT / "tests" / "fixtures" / "voyager_trace.json")
        context = ScoringContext(
            judge_config=JudgeConfig(enabled=True, provider="mock", model="mock-model"),
            judge_client=_MockJudgeClient(),
        )

        score = score_case(case, trace, context=context)

        factual_metric = next(metric for metric in score.metrics if metric.name == "factual_correctness")
        citation_metric = next(metric for metric in score.metrics if metric.name == "citation_grounding_quality")
        self.assertTrue(factual_metric.passed)
        self.assertFalse(factual_metric.skipped)
        self.assertEqual(factual_metric.details["judge"]["provider"], "mock")
        self.assertTrue(citation_metric.passed)

    def test_judge_metrics_skip_cleanly_when_disabled(self) -> None:
        case = load_case(ROOT / "cases" / "voyager_happy_path.yaml")
        trace = Trace.from_path(ROOT / "tests" / "fixtures" / "voyager_trace.json")

        score = score_case(case, trace)

        factual_metric = next(metric for metric in score.metrics if metric.name == "factual_correctness")
        self.assertTrue(factual_metric.passed)
        self.assertTrue(factual_metric.skipped)
        self.assertIn("judge disabled", factual_metric.summary)


if __name__ == "__main__":
    unittest.main()
