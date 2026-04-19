from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _relative_path(path: str | Path, base_dir: Path) -> str:
    candidate = Path(path)
    try:
        return str(candidate.resolve().relative_to(base_dir.resolve()))
    except ValueError:
        return str(candidate.resolve())


def _percentile(values: list[int], percentile: int) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    rank = max(1, math.ceil((percentile / 100) * len(ordered)))
    return int(ordered[rank - 1])


def _case_status(pass_count: int, total_repeats: int) -> str:
    if pass_count == total_repeats:
        return "pass"
    if pass_count == 0:
        return "fail"
    return "flaky"


def _rate(pass_count: int, total_repeats: int) -> float:
    if total_repeats <= 0:
        return 0.0
    return pass_count / total_repeats


def _runtime_error_message(stopped_reason: str, error: Any) -> str:
    if stopped_reason != "error" or not error:
        return ""
    return f"runtime error: {error}"


def build_report(
    executions: list[dict[str, Any]],
    *,
    run_id: str,
    mode: str,
    output_dir: str | Path,
    cases_dir: str | Path,
    config: dict[str, Any],
    previous_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    output_path = Path(output_dir)
    repeat_rows: list[dict[str, Any]] = []

    for execution in sorted(
        executions,
        key=lambda item: (item["case"].case_id, item["repeat_index"]),
    ):
        case = execution["case"]
        trace = execution["trace"]
        score = execution["score"]
        attempts = []
        for attempt in execution.get("attempts", []):
            attempts.append(
                {
                    "attempt_index": int(attempt["attempt_index"]),
                    "selected_for_scoring": bool(attempt.get("selected_for_scoring")),
                    "transient_error": bool(attempt.get("transient_error")),
                    "stopped_reason": str(attempt.get("stopped_reason") or ""),
                    "error": attempt.get("error"),
                    "trace_path": _relative_path(attempt["trace_path"], output_path),
                }
            )

        repeat_rows.append(
            {
                "case_id": case.case_id,
                "description": case.description,
                "tags": list(case.tags),
                "repeat_index": int(execution["repeat_index"]),
                "passed": bool(score.passed),
                "failure_reason": _runtime_error_message(trace.stopped_reason, trace.error)
                or score.failure_reason(),
                "trace_path": _relative_path(execution["trace_path"], output_path),
                "attempt_count": len(attempts),
                "selected_attempt": int(execution["selected_attempt"]),
                "attempts": attempts,
                "wall_time_ms": trace.wall_time_ms,
                "cost_usd": trace.cost_usd,
                "tool_calls": trace.tool_call_count(),
                "stopped_reason": trace.stopped_reason,
                "error": trace.error,
                "runtime_error": _runtime_error_message(trace.stopped_reason, trace.error),
                "run_id": trace.run_id,
                "question": trace.question,
                "score": score.to_dict(),
            }
        )

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in repeat_rows:
        grouped[row["case_id"]].append(row)

    case_rows: list[dict[str, Any]] = []
    for case_id in sorted(grouped):
        repeats = sorted(grouped[case_id], key=lambda item: item["repeat_index"])
        pass_count = sum(1 for repeat in repeats if repeat["passed"])
        total_repeats = len(repeats)
        runtime_error = next(
            (repeat["runtime_error"] for repeat in repeats if repeat.get("runtime_error")),
            "",
        )
        failure_reason = next(
            (repeat["failure_reason"] for repeat in repeats if not repeat["passed"]),
            "",
        )
        case_rows.append(
            {
                "case_id": case_id,
                "description": repeats[0]["description"],
                "tags": repeats[0]["tags"],
                "status": _case_status(pass_count, total_repeats),
                "pass_count": pass_count,
                "total_repeats": total_repeats,
                "pass_summary": f"{pass_count}/{total_repeats} passed",
                "failure_reason": failure_reason,
                "runtime_error": runtime_error,
                "repeats": repeats,
            }
        )

    latencies = [row["wall_time_ms"] for row in repeat_rows]
    costs = [float(row["cost_usd"]) for row in repeat_rows]
    tool_counts = [row["tool_calls"] for row in repeat_rows]
    passed_repeats = sum(1 for row in repeat_rows if row["passed"])
    total_repeats = len(repeat_rows)
    runtime_error_repeats = sum(1 for row in repeat_rows if row.get("runtime_error"))

    report = {
        "run_id": run_id,
        "mode": mode,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "output_dir": str(output_path),
        "cases_dir": str(cases_dir),
        "config": config,
        "summary": {
            "case_count": len(case_rows),
            "repeat_count": total_repeats,
            "passed_repeats": passed_repeats,
            "runtime_error_repeats": runtime_error_repeats,
            "pass_rate": round(_rate(passed_repeats, total_repeats), 4),
            "pass_rate_pct": round(_rate(passed_repeats, total_repeats) * 100, 1),
            "total_cost_usd": round(sum(costs), 6),
            "p50_latency_ms": _percentile(latencies, 50),
            "p95_latency_ms": _percentile(latencies, 95),
            "mean_tool_calls_per_case": round(
                sum(tool_counts) / total_repeats, 2
            )
            if total_repeats
            else 0.0,
        },
        "cases": case_rows,
        "diff": {},
    }
    report["diff"] = build_diff(report, previous_report) if previous_report else {
        "against": None,
        "summary": {"regressions": 0, "improvements": 0},
        "regressions": [],
        "improvements": [],
        "new_cases": [],
        "removed_cases": [],
    }
    return report


def build_diff(
    current_report: dict[str, Any], previous_report: dict[str, Any]
) -> dict[str, Any]:
    current_cases = {
        case["case_id"]: case for case in current_report.get("cases", [])
    }
    previous_cases = {
        case["case_id"]: case for case in previous_report.get("cases", [])
    }
    status_rank = {"fail": 0, "flaky": 1, "pass": 2}
    regressions: list[dict[str, Any]] = []
    improvements: list[dict[str, Any]] = []
    new_cases: list[dict[str, Any]] = []
    removed_cases: list[dict[str, Any]] = []

    for case_id in sorted(current_cases):
        current_case = current_cases[case_id]
        if case_id not in previous_cases:
            new_cases.append(
                {
                    "case_id": case_id,
                    "after": current_case["pass_summary"],
                    "status": current_case["status"],
                }
            )
            continue

        previous_case = previous_cases[case_id]
        current_rank = status_rank[current_case["status"]]
        previous_rank = status_rank[previous_case["status"]]
        current_rate = _rate(current_case["pass_count"], current_case["total_repeats"])
        previous_rate = _rate(previous_case["pass_count"], previous_case["total_repeats"])
        change = {
            "case_id": case_id,
            "before": previous_case["pass_summary"],
            "after": current_case["pass_summary"],
            "before_status": previous_case["status"],
            "after_status": current_case["status"],
            "previous_failure_reason": previous_case.get("failure_reason", ""),
            "current_failure_reason": current_case.get("failure_reason", ""),
        }

        if current_rank < previous_rank or (
            current_rank == previous_rank and current_rate < previous_rate
        ):
            regressions.append(change)
        elif current_rank > previous_rank or (
            current_rank == previous_rank and current_rate > previous_rate
        ):
            improvements.append(change)

    for case_id in sorted(previous_cases):
        if case_id not in current_cases:
            removed_cases.append(
                {
                    "case_id": case_id,
                    "before": previous_cases[case_id]["pass_summary"],
                    "status": previous_cases[case_id]["status"],
                }
            )

    return {
        "against": previous_report.get("run_id"),
        "summary": {
            "regressions": len(regressions),
            "improvements": len(improvements),
        },
        "regressions": regressions,
        "improvements": improvements,
        "new_cases": new_cases,
        "removed_cases": removed_cases,
    }


def write_report(report: dict[str, Any], output_dir: str | Path) -> Path:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    report_path = output_path / "report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report_path


def load_report(path_or_dir: str | Path) -> dict[str, Any]:
    candidate = Path(path_or_dir)
    report_path = candidate / "report.json" if candidate.is_dir() else candidate
    return json.loads(report_path.read_text(encoding="utf-8"))


def format_report_text(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        f"Run: {report['run_id']} ({report['mode']})",
        (
            f"Pass rate: {summary['passed_repeats']}/{summary['repeat_count']} "
            f"({summary['pass_rate_pct']}%) | cost ${summary['total_cost_usd']:.4f} "
            f"| p50 {summary['p50_latency_ms']}ms | p95 {summary['p95_latency_ms']}ms "
            f"| mean tool calls {summary['mean_tool_calls_per_case']}"
        ),
    ]
    if summary.get("runtime_error_repeats"):
        lines.append(f"Runtime errors: {summary['runtime_error_repeats']} repeat(s)")
    lines.extend(["", "Cases:"])

    for case in report.get("cases", []):
        prefix = case["status"].upper().ljust(5)
        line = f"{prefix} {case['case_id']} ({case['pass_summary']})"
        if case["status"] != "pass":
            if case.get("runtime_error"):
                line += f" - {case['runtime_error']}"
            elif case.get("failure_reason"):
                line += f" - {case['failure_reason']}"
        lines.append(line)

    diff = report.get("diff") or {}
    if diff.get("against"):
        lines.append("")
        lines.append(f"Diff vs {diff['against']}:")
        regressions = diff.get("regressions") or []
        if regressions:
            lines.append("Regressions:")
            for item in regressions:
                line = f"- {item['case_id']}: {item['before']} -> {item['after']}"
                if item.get("current_failure_reason"):
                    line += f" - {item['current_failure_reason']}"
                lines.append(line)
        else:
            lines.append("Regressions: none")

        improvements = diff.get("improvements") or []
        if improvements:
            lines.append("Improvements:")
            for item in improvements:
                lines.append(f"- {item['case_id']}: {item['before']} -> {item['after']}")

    return "\n".join(lines)
