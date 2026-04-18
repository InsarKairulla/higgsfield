from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from evals.trace import Trace


@dataclass
class AssertionOutcome:
    assertion_type: str
    passed: bool
    message: str
    expected: Any = None
    actual: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.assertion_type,
            "passed": self.passed,
            "message": self.message,
            "expected": self.expected,
            "actual": self.actual,
        }


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def _first_match(values: list[bool]) -> bool:
    return any(values)


def _tool_sequence_matches(actual_names: list[str], expected_names: list[str]) -> bool:
    cursor = 0
    for name in actual_names:
        if cursor < len(expected_names) and name == expected_names[cursor]:
            cursor += 1
    return cursor == len(expected_names)


def evaluate_assertion(trace: Trace, assertion: dict[str, Any]) -> AssertionOutcome:
    assertion_type = str(assertion.get("type") or "").strip()
    if not assertion_type:
        return AssertionOutcome(
            assertion_type="invalid",
            passed=False,
            message="assertion is missing a type",
        )

    if assertion_type == "equals":
        path = str(assertion.get("path") or "")
        expected = assertion.get("value")
        try:
            actual = trace.get(path)
        except KeyError:
            return AssertionOutcome(assertion_type, False, f"path not found: {path}", expected=expected)
        passed = actual == expected
        return AssertionOutcome(
            assertion_type,
            passed,
            f"{path} == {expected!r}" if passed else f"{path} was {actual!r}, expected {expected!r}",
            expected=expected,
            actual=actual,
        )

    if assertion_type == "contains":
        path = str(assertion.get("path") or "")
        expected = str(assertion.get("value") or "")
        try:
            actual = trace.get(path)
        except KeyError:
            return AssertionOutcome(assertion_type, False, f"path not found: {path}", expected=expected)
        actual_text = _as_text(actual)
        passed = expected in actual_text
        return AssertionOutcome(
            assertion_type,
            passed,
            f"{path} contains {expected!r}" if passed else f"{path} did not contain {expected!r}",
            expected=expected,
            actual=actual_text,
        )

    if assertion_type == "not_contains":
        path = str(assertion.get("path") or "")
        forbidden = str(assertion.get("value") or "")
        try:
            actual = trace.get(path)
        except KeyError:
            return AssertionOutcome(assertion_type, False, f"path not found: {path}", expected=forbidden)
        actual_text = _as_text(actual)
        passed = forbidden not in actual_text
        return AssertionOutcome(
            assertion_type,
            passed,
            f"{path} did not contain {forbidden!r}"
            if passed
            else f"{path} unexpectedly contained {forbidden!r}",
            expected=forbidden,
            actual=actual_text,
        )

    if assertion_type == "regex":
        path = str(assertion.get("path") or "")
        pattern = str(assertion.get("pattern") or "")
        try:
            actual = trace.get(path)
        except KeyError:
            return AssertionOutcome(assertion_type, False, f"path not found: {path}", expected=pattern)
        actual_text = _as_text(actual)
        passed = bool(re.search(pattern, actual_text, flags=re.IGNORECASE))
        return AssertionOutcome(
            assertion_type,
            passed,
            f"{path} matched /{pattern}/" if passed else f"{path} did not match /{pattern}/",
            expected=pattern,
            actual=actual_text,
        )

    if assertion_type == "not_regex":
        path = str(assertion.get("path") or "")
        pattern = str(assertion.get("pattern") or "")
        try:
            actual = trace.get(path)
        except KeyError:
            return AssertionOutcome(assertion_type, False, f"path not found: {path}", expected=pattern)
        actual_text = _as_text(actual)
        passed = not re.search(pattern, actual_text, flags=re.IGNORECASE)
        return AssertionOutcome(
            assertion_type,
            passed,
            f"{path} did not match /{pattern}/"
            if passed
            else f"{path} unexpectedly matched /{pattern}/",
            expected=pattern,
            actual=actual_text,
        )

    if assertion_type == "list_contains":
        path = str(assertion.get("path") or "")
        expected = assertion.get("value")
        try:
            actual = trace.get(path)
        except KeyError:
            return AssertionOutcome(assertion_type, False, f"path not found: {path}", expected=expected)
        if not isinstance(actual, list):
            return AssertionOutcome(assertion_type, False, f"{path} is not a list", expected=expected, actual=actual)
        passed = expected in actual
        return AssertionOutcome(
            assertion_type,
            passed,
            f"{path} contains {expected!r}" if passed else f"{path} did not include {expected!r}",
            expected=expected,
            actual=actual,
        )

    if assertion_type == "tool_called":
        name = str(assertion.get("name") or "")
        min_count = int(assertion.get("min_count", 1))
        max_count = assertion.get("max_count")
        count = len(trace.tool_calls(name))
        passed = count >= min_count and (max_count is None or count <= int(max_count))
        return AssertionOutcome(
            assertion_type,
            passed,
            f"{name} called {count} time(s)",
            expected={"min_count": min_count, "max_count": max_count},
            actual=count,
        )

    if assertion_type == "tool_arg_equals":
        name = str(assertion.get("name") or "")
        arg = str(assertion.get("arg") or "")
        expected = assertion.get("value")
        matches = [call.args.get(arg) == expected for call in trace.tool_calls(name)]
        passed = _first_match(matches)
        return AssertionOutcome(
            assertion_type,
            passed,
            f"{name}.{arg} matched {expected!r}" if passed else f"no {name} call used {arg}={expected!r}",
            expected=expected,
            actual=[call.args.get(arg) for call in trace.tool_calls(name)],
        )

    if assertion_type == "tool_sequence":
        expected_names = [str(item) for item in assertion.get("names") or []]
        actual_names = trace.tool_call_names()
        passed = _tool_sequence_matches(actual_names, expected_names)
        return AssertionOutcome(
            assertion_type,
            passed,
            "tool sequence matched" if passed else "tool sequence did not match",
            expected=expected_names,
            actual=actual_names,
        )

    if assertion_type == "citations_are_fetched":
        fetched_urls = trace.fetched_urls()
        citations = trace.citations
        missing = [url for url in citations if url not in fetched_urls]
        passed = not missing
        return AssertionOutcome(
            assertion_type,
            passed,
            "every citation was fetched" if passed else "some citations were never fetched",
            expected="all citations appear in fetch_url arguments",
            actual={"citations": citations, "missing": missing},
        )

    if assertion_type == "no_forbidden_citations":
        forbidden = {str(value) for value in assertion.get("values") or []}
        cited = [url for url in trace.citations if url in forbidden]
        passed = not cited
        return AssertionOutcome(
            assertion_type,
            passed,
            "no forbidden citations were present"
            if passed
            else "trace cited forbidden URLs",
            expected=sorted(forbidden),
            actual=cited,
        )

    if assertion_type == "answer_words_lte":
        limit = int(assertion.get("value", 0))
        actual = trace.answer_word_count()
        passed = actual <= limit
        return AssertionOutcome(
            assertion_type,
            passed,
            f"answer length {actual} <= {limit}" if passed else f"answer length {actual} exceeded {limit}",
            expected=limit,
            actual=actual,
        )

    if assertion_type == "extract_quotes_are_verbatim":
        violations: list[str] = []
        checked = 0
        for call in trace.tool_calls("extract_quotes"):
            source_text = str(call.args.get("text") or "")
            if not isinstance(call.result, list):
                violations.append("extract_quotes result was not a JSON list")
                continue
            for quote in call.result:
                checked += 1
                quote_text = str(quote)
                if quote_text not in source_text:
                    violations.append(quote_text)
        passed = not violations
        return AssertionOutcome(
            assertion_type,
            passed,
            "all extracted quotes were verbatim"
            if passed
            else "some extracted quotes were not verbatim substrings",
            expected="every extract_quotes output is a substring of its input text",
            actual={"checked_quotes": checked, "violations": violations},
        )

    return AssertionOutcome(
        assertion_type=assertion_type,
        passed=False,
        message=f"unsupported assertion type: {assertion_type}",
    )


def evaluate_assertions(trace: Trace, assertions: list[dict[str, Any]]) -> list[AssertionOutcome]:
    outcomes: list[AssertionOutcome] = []
    for assertion in assertions:
        if not isinstance(assertion, dict):
            outcomes.append(
                AssertionOutcome(
                    assertion_type="invalid",
                    passed=False,
                    message="assertion must be a mapping",
                    actual=assertion,
                )
            )
            continue
        outcomes.append(evaluate_assertion(trace, assertion))
    return outcomes

