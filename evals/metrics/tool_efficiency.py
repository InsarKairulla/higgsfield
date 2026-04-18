from __future__ import annotations

from collections import Counter

from evals.cases import CaseSpec
from evals.scoring import MetricResult, register_metric
from evals.trace import Trace


def _build_summary(checks: list[dict]) -> tuple[bool, str]:
    for check in checks:
        if not check["passed"]:
            return False, check["message"]
    return True, "tool usage stayed within configured bounds"


@register_metric("tool_efficiency")
def score_tool_efficiency(case: CaseSpec, trace: Trace, config: dict) -> MetricResult:
    tool_names = trace.tool_call_names()
    counts = Counter(tool_names)
    checks: list[dict] = []

    required_tools = [str(name) for name in config.get("required_tools") or []]
    if required_tools:
        missing = [name for name in required_tools if counts[name] == 0]
        checks.append(
            {
                "name": "required_tools",
                "passed": not missing,
                "message": "all required tools were used"
                if not missing
                else f"missing required tools: {', '.join(missing)}",
                "actual": dict(counts),
            }
        )

    ordered_tools = [str(name) for name in config.get("ordered_tools") or []]
    if ordered_tools:
        cursor = 0
        for name in tool_names:
            if cursor < len(ordered_tools) and name == ordered_tools[cursor]:
                cursor += 1
        passed = cursor == len(ordered_tools)
        checks.append(
            {
                "name": "ordered_tools",
                "passed": passed,
                "message": "required tool order observed"
                if passed
                else f"tool order was {tool_names}, expected subsequence {ordered_tools}",
                "actual": tool_names,
            }
        )

    max_tool_calls = config.get("max_tool_calls")
    if max_tool_calls is not None:
        max_tool_calls = int(max_tool_calls)
        total_calls = len(tool_names)
        checks.append(
            {
                "name": "max_tool_calls",
                "passed": total_calls <= max_tool_calls,
                "message": f"total tool calls {total_calls} <= {max_tool_calls}"
                if total_calls <= max_tool_calls
                else f"total tool calls {total_calls} exceeded {max_tool_calls}",
                "actual": total_calls,
            }
        )

    max_calls_per_tool = config.get("max_calls_per_tool") or {}
    for tool_name, max_calls in max_calls_per_tool.items():
        max_calls_int = int(max_calls)
        actual = counts[str(tool_name)]
        checks.append(
            {
                "name": f"max_calls_per_tool:{tool_name}",
                "passed": actual <= max_calls_int,
                "message": f"{tool_name} calls {actual} <= {max_calls_int}"
                if actual <= max_calls_int
                else f"{tool_name} calls {actual} exceeded {max_calls_int}",
                "actual": actual,
            }
        )

    passed, summary = _build_summary(checks or [{"passed": True, "message": "no tool checks configured"}])
    return MetricResult(
        name="tool_efficiency",
        passed=passed,
        score=1.0 if passed else 0.0,
        summary=summary,
        details={"case_id": case.case_id, "checks": checks, "tool_counts": dict(counts)},
    )

