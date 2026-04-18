from __future__ import annotations

import copy
import unittest
from pathlib import Path

from evals.cases import load_case, load_cases
from evals.scoring import score_case
from evals.trace import Trace


ROOT = Path(__file__).resolve().parents[1]


class OfflineScoringTests(unittest.TestCase):
    def test_loads_all_starter_cases(self) -> None:
        cases = load_cases(ROOT / "cases")
        self.assertEqual(len(cases), 10)

    def test_fixture_trace_passes_voyager_case(self) -> None:
        case = load_case(ROOT / "cases" / "voyager_happy_path.yaml")
        trace = Trace.from_path(ROOT / "tests" / "fixtures" / "voyager_trace.json")

        score = score_case(case, trace)

        self.assertTrue(score.passed)
        self.assertTrue(all(metric.passed for metric in score.metrics))

    def test_quote_grounding_catches_paraphrase(self) -> None:
        case = load_case(ROOT / "cases" / "voyager_happy_path.yaml")
        trace = Trace.from_path(ROOT / "tests" / "fixtures" / "voyager_trace.json")
        broken_raw = copy.deepcopy(trace.raw)
        broken_raw["messages"][7]["content"][0] = (
            "NASA said Voyager 1 crossed in late August 2012 after particle flux data changed."
        )

        score = score_case(case, Trace(raw=broken_raw))
        quote_metric = next(metric for metric in score.metrics if metric.name == "quote_grounding")

        self.assertFalse(score.passed)
        self.assertFalse(quote_metric.passed)


if __name__ == "__main__":
    unittest.main()

