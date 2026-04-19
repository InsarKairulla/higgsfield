from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from evals.cases import find_case, load_case, load_cases
from evals.reporting import format_report_text, load_report
from evals.runner import rescore_saved_traces, run_live_suite
from evals.scoring import CaseScore, score_case
from evals.trace import Trace


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Offline eval utilities")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_cases = subparsers.add_parser("list-cases", help="List YAML cases")
    list_cases.add_argument("--cases-dir", default="cases")

    run_suite = subparsers.add_parser("run-suite", help="Run all cases against the live agent")
    run_suite.add_argument("--cases-dir", default="cases")
    run_suite.add_argument("--output-root", default="eval_runs")
    run_suite.add_argument("--concurrency", type=int, default=4)
    run_suite.add_argument("--repeats", type=int, default=1)
    run_suite.add_argument("--max-retries", type=int, default=2)
    run_suite.add_argument("--retry-delay", type=float, default=1.0)
    run_suite.add_argument("--previous-run", help="Previous run directory or report.json for diffing")
    run_suite.add_argument("--judge-provider", help="Judge provider, for example: anthropic or openai")
    run_suite.add_argument("--judge-model", help="Judge model name")
    run_suite.add_argument("--judge-max-tokens", type=int, default=None)
    run_suite.add_argument("--no-judge", action="store_true", help="Disable judge metrics")
    run_suite.add_argument("--json", action="store_true", help="Print JSON output")

    rescore_dir = subparsers.add_parser(
        "rescore-dir", help="Rescore saved traces without calling the agent"
    )
    rescore_dir.add_argument("--input-dir", required=True)
    rescore_dir.add_argument("--cases-dir", default="cases")
    rescore_dir.add_argument("--output-dir")
    rescore_dir.add_argument("--previous-run", help="Previous run directory or report.json for diffing")
    rescore_dir.add_argument("--judge-provider", help="Judge provider, for example: anthropic or openai")
    rescore_dir.add_argument("--judge-model", help="Judge model name")
    rescore_dir.add_argument("--judge-max-tokens", type=int, default=None)
    rescore_dir.add_argument("--no-judge", action="store_true", help="Disable judge metrics")
    rescore_dir.add_argument("--json", action="store_true", help="Print JSON output")

    score_trace = subparsers.add_parser(
        "score-trace", help="Rescore a cached trace JSON against one case"
    )
    case_group = score_trace.add_mutually_exclusive_group(required=True)
    case_group.add_argument("--case", help="Path to a case YAML file")
    case_group.add_argument("--case-id", help="Case id to resolve under --cases-dir")
    score_trace.add_argument("--cases-dir", default="cases")
    score_trace.add_argument("--trace", required=True, help="Path to cached trace JSON")
    score_trace.add_argument("--judge-provider", help="Judge provider, for example: anthropic or openai")
    score_trace.add_argument("--judge-model", help="Judge model name")
    score_trace.add_argument("--judge-max-tokens", type=int, default=None)
    score_trace.add_argument("--no-judge", action="store_true", help="Disable judge metrics")
    score_trace.add_argument("--json", action="store_true", help="Print JSON output")

    return parser


def _print_case_score(score: CaseScore) -> None:
    print(f"case: {score.case_id}")
    print(f"passed: {score.passed}")
    for metric in score.metrics:
        if metric.skipped:
            status = "SKIP"
        else:
            status = "PASS" if metric.passed else "FAIL"
        print(f"{status} {metric.name}: {metric.summary}")


def _load_previous_report(path: str | None) -> dict | None:
    return None if not path else load_report(path)


def _load_cli_dotenv() -> None:
    project_root = Path(__file__).resolve().parents[1]
    dotenv_path = project_root / ".env"
    load_dotenv(dotenv_path=dotenv_path if dotenv_path.exists() else None, override=False)


def main(argv: list[str] | None = None) -> int:
    _load_cli_dotenv()
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "list-cases":
        for case in load_cases(args.cases_dir):
            print(f"{case.case_id}\t{case.source_path}")
        return 0

    if args.command == "run-suite":
        result = run_live_suite(
            cases_dir=args.cases_dir,
            output_root=args.output_root,
            concurrency=args.concurrency,
            repeats=args.repeats,
            max_retries=args.max_retries,
            retry_delay_s=args.retry_delay,
            previous_report=_load_previous_report(args.previous_run),
            judge_provider=args.judge_provider,
            judge_model=args.judge_model,
            judge_max_tokens=args.judge_max_tokens,
            no_judge=args.no_judge,
        )
        report = result["report"]
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(format_report_text(report))
            print()
            print(f"report -> {result['report_path']}")
            print(f"viewer -> {result['viewer_path']}")
        return 0 if report["summary"]["passed_repeats"] == report["summary"]["repeat_count"] else 1

    if args.command == "rescore-dir":
        result = rescore_saved_traces(
            input_dir=args.input_dir,
            cases_dir=args.cases_dir,
            output_dir=args.output_dir,
            previous_report=_load_previous_report(args.previous_run),
            judge_provider=args.judge_provider,
            judge_model=args.judge_model,
            judge_max_tokens=args.judge_max_tokens,
            no_judge=args.no_judge,
        )
        report = result["report"]
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(format_report_text(report))
            print()
            print(f"report -> {result['report_path']}")
            print(f"viewer -> {result['viewer_path']}")
        return 0 if report["summary"]["passed_repeats"] == report["summary"]["repeat_count"] else 1

    if args.command == "score-trace":
        from evals.judges import build_judge_client, resolve_judge_config
        from evals.scoring import ScoringContext

        case = load_case(args.case) if args.case else find_case(args.case_id, args.cases_dir)
        trace = Trace.from_path(args.trace)
        judge_config = resolve_judge_config(
            provider=args.judge_provider,
            model=args.judge_model,
            max_tokens=args.judge_max_tokens,
            no_judge=args.no_judge,
        )
        score = score_case(
            case,
            trace,
            context=ScoringContext(
                judge_config=judge_config,
                judge_client=build_judge_client(judge_config),
            ),
        )
        if args.json:
            print(json.dumps(score.to_dict(), indent=2))
        else:
            _print_case_score(score)
        return 0 if score.passed else 1

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
