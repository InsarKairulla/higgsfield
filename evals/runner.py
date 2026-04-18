from __future__ import annotations

import json
import shutil
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

from evals.cases import CaseSpec, load_cases
from evals.reporting import build_report, write_report
from evals.scoring import score_case
from evals.trace import Trace
from evals.viewer import write_run_viewer


PROJECT_ROOT = Path(__file__).resolve().parents[1]

RunAgentFn = Callable[[str], Any]
TraceRecord = dict[str, Any]


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _make_run_dir(output_root: str | Path, prefix: str) -> Path:
    root = Path(output_root)
    if not root.is_absolute():
        root = (PROJECT_ROOT / root).resolve()
    run_dir = root / f"{prefix}_{_now_stamp()}_{uuid.uuid4().hex[:8]}"
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "traces").mkdir(exist_ok=True)
    return run_dir


def _ensure_corpus_available() -> None:
    index_path = PROJECT_ROOT / "corpus" / "index.json"
    if index_path.exists():
        return

    archive_path = PROJECT_ROOT / "corpus.zip"
    if not archive_path.exists():
        raise RuntimeError("corpus/index.json is missing and corpus.zip was not found")

    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            if member.is_dir() or not member.filename.startswith("corpus/"):
                continue
            target_path = PROJECT_ROOT / member.filename
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target_path.open("wb") as destination:
                shutil.copyfileobj(source, destination)


def _load_eval_dotenv() -> None:
    dotenv_path = PROJECT_ROOT / ".env"
    load_dotenv(dotenv_path=dotenv_path if dotenv_path.exists() else None, override=False)


def _load_default_run_agent() -> RunAgentFn:
    _load_eval_dotenv()
    _ensure_corpus_available()
    from agent import run_agent  # Imported lazily so offline scoring stays lightweight.

    return run_agent


def is_transient_error(error: str | None) -> bool:
    if not error:
        return False
    lowered = error.lower()
    keywords = [
        "429",
        "500",
        "502",
        "503",
        "504",
        "rate limit",
        "ratelimit",
        "timeout",
        "timed out",
        "temporarily unavailable",
        "connection",
        "network",
        "overloaded",
        "server error",
        "internal server error",
        "apiconnectionerror",
        "apitimeouterror",
    ]
    return any(keyword in lowered for keyword in keywords)


def _normalize_trace_payload(result: Any, question: str) -> dict[str, Any]:
    if hasattr(result, "to_dict"):
        payload = result.to_dict()
    elif isinstance(result, dict):
        payload = result
    else:
        raise TypeError("run_agent result must be a dict or expose to_dict()")
    if not isinstance(payload, dict):
        raise TypeError("trace payload must be a dictionary")
    payload = dict(payload)
    payload.setdefault("question", question)
    payload.setdefault("messages", [])
    payload.setdefault("citations", [])
    payload.setdefault("total_tokens", {"input": 0, "output": 0})
    payload.setdefault("wall_time_ms", 0)
    payload.setdefault("cost_usd", 0.0)
    payload.setdefault("stopped_reason", "error")
    payload.setdefault("error", None)
    payload.setdefault("run_id", str(uuid.uuid4()))
    return payload


def _build_error_trace(question: str, error: str, wall_time_ms: int) -> dict[str, Any]:
    return {
        "run_id": str(uuid.uuid4()),
        "question": question,
        "model": "",
        "messages": [{"role": "user", "content": question}],
        "final_answer": None,
        "citations": [],
        "stopped_reason": "error",
        "total_tokens": {"input": 0, "output": 0},
        "cost_usd": 0.0,
        "wall_time_ms": wall_time_ms,
        "error": error,
    }


def _with_eval_metadata(
    raw_trace: dict[str, Any],
    *,
    case: CaseSpec,
    repeat_index: int,
    attempt_index: int,
    selected_for_scoring: bool,
    transient_error: bool,
) -> dict[str, Any]:
    payload = dict(raw_trace)
    eval_metadata = dict(payload.get("eval") or {})
    eval_metadata.update(
        {
            "case_id": case.case_id,
            "case_path": str(case.source_path) if case.source_path else None,
            "repeat_index": repeat_index,
            "attempt_index": attempt_index,
            "selected_for_scoring": selected_for_scoring,
            "transient_error": transient_error,
        }
    )
    payload["eval"] = eval_metadata
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _trace_filename(case_id: str, repeat_index: int, attempt_index: int) -> str:
    return f"{case_id}__repeat{repeat_index:03d}__attempt{attempt_index:03d}.json"


def _run_case_repeat(
    *,
    case: CaseSpec,
    repeat_index: int,
    traces_dir: Path,
    max_retries: int,
    retry_delay_s: float,
    run_agent_fn: RunAgentFn,
) -> TraceRecord:
    attempts: list[dict[str, Any]] = []
    selected_trace_path: Path | None = None
    selected_trace_payload: dict[str, Any] | None = None

    for attempt_index in range(1, max_retries + 2):
        started_at = time.time()
        try:
            raw_trace = _normalize_trace_payload(run_agent_fn(case.input), case.input)
        except Exception as exc:
            elapsed_ms = int((time.time() - started_at) * 1000)
            raw_trace = _build_error_trace(
                case.input,
                f"{type(exc).__name__}: {exc}",
                elapsed_ms,
            )

        transient = raw_trace.get("stopped_reason") == "error" and is_transient_error(
            raw_trace.get("error")
        )
        trace_path = traces_dir / _trace_filename(case.case_id, repeat_index, attempt_index)
        payload = _with_eval_metadata(
            raw_trace,
            case=case,
            repeat_index=repeat_index,
            attempt_index=attempt_index,
            selected_for_scoring=False,
            transient_error=transient,
        )
        _write_json(trace_path, payload)
        attempts.append(
            {
                "attempt_index": attempt_index,
                "trace_path": trace_path,
                "selected_for_scoring": False,
                "transient_error": transient,
                "stopped_reason": payload.get("stopped_reason"),
                "error": payload.get("error"),
            }
        )
        selected_trace_path = trace_path
        selected_trace_payload = payload

        if transient and attempt_index <= max_retries:
            time.sleep(max(0.0, retry_delay_s) * attempt_index)
            continue
        break

    assert selected_trace_path is not None and selected_trace_payload is not None

    selected_trace_payload = _with_eval_metadata(
        selected_trace_payload,
        case=case,
        repeat_index=repeat_index,
        attempt_index=int(selected_trace_payload["eval"]["attempt_index"]),
        selected_for_scoring=True,
        transient_error=bool(selected_trace_payload["eval"].get("transient_error")),
    )
    _write_json(selected_trace_path, selected_trace_payload)
    attempts[-1]["selected_for_scoring"] = True

    trace = Trace.from_path(selected_trace_path)
    score = score_case(case, trace)
    return {
        "case": case,
        "repeat_index": repeat_index,
        "trace_path": selected_trace_path,
        "selected_attempt": attempts[-1]["attempt_index"],
        "attempts": attempts,
        "trace": trace,
        "score": score,
    }


def run_live_suite(
    *,
    cases_dir: str | Path = "cases",
    output_root: str | Path = "eval_runs",
    concurrency: int = 4,
    repeats: int = 1,
    max_retries: int = 2,
    retry_delay_s: float = 1.0,
    previous_report: dict[str, Any] | None = None,
    run_agent_fn: RunAgentFn | None = None,
) -> dict[str, Any]:
    cases = load_cases(cases_dir)
    run_dir = _make_run_dir(output_root, "run")
    traces_dir = run_dir / "traces"
    runner = run_agent_fn or _load_default_run_agent()

    futures = []
    results: list[TraceRecord] = []
    with ThreadPoolExecutor(max_workers=max(1, int(concurrency))) as executor:
        for case in cases:
            for repeat_index in range(1, max(1, int(repeats)) + 1):
                futures.append(
                    executor.submit(
                        _run_case_repeat,
                        case=case,
                        repeat_index=repeat_index,
                        traces_dir=traces_dir,
                        max_retries=max(0, int(max_retries)),
                        retry_delay_s=float(retry_delay_s),
                        run_agent_fn=runner,
                    )
                )
        for future in as_completed(futures):
            results.append(future.result())

    report = build_report(
        results,
        run_id=run_dir.name,
        mode="live",
        output_dir=run_dir,
        cases_dir=cases_dir,
        config={
            "concurrency": max(1, int(concurrency)),
            "repeats": max(1, int(repeats)),
            "max_retries": max(0, int(max_retries)),
            "retry_delay_s": float(retry_delay_s),
        },
        previous_report=previous_report,
    )
    report_path = write_report(report, run_dir)
    viewer_path = write_run_viewer(report, run_dir)
    return {
        "run_dir": run_dir,
        "report_path": report_path,
        "viewer_path": viewer_path,
        "report": report,
    }


def discover_saved_traces(directory: str | Path) -> list[dict[str, Any]]:
    base_dir = Path(directory)
    if not base_dir.exists():
        raise FileNotFoundError(base_dir)

    grouped: dict[tuple[str, int], list[Trace]] = {}
    for path in sorted(base_dir.rglob("*.json")):
        trace = Trace.from_path(path)
        metadata = trace.eval_metadata
        case_id = metadata.get("case_id")
        repeat_index = metadata.get("repeat_index")
        if not case_id or repeat_index is None:
            continue
        grouped.setdefault((str(case_id), int(repeat_index)), []).append(trace)

    executions: list[dict[str, Any]] = []
    for (case_id, repeat_index), traces in sorted(grouped.items()):
        ordered = sorted(
            traces,
            key=lambda trace: int(trace.eval_metadata.get("attempt_index", 0)),
        )
        selected = [trace for trace in ordered if trace.eval_metadata.get("selected_for_scoring")]
        chosen = selected[-1] if selected else ordered[-1]
        attempts = []
        for trace in ordered:
            attempts.append(
                {
                    "attempt_index": int(trace.eval_metadata.get("attempt_index", 0)),
                    "trace_path": trace.source_path,
                    "selected_for_scoring": bool(
                        trace.source_path == chosen.source_path
                    ),
                    "transient_error": bool(trace.eval_metadata.get("transient_error")),
                    "stopped_reason": trace.stopped_reason,
                    "error": trace.error,
                }
            )
        executions.append(
            {
                "case_id": case_id,
                "repeat_index": repeat_index,
                "trace": chosen,
                "trace_path": chosen.source_path,
                "selected_attempt": int(chosen.eval_metadata.get("attempt_index", 0)),
                "attempts": attempts,
            }
        )
    return executions


def rescore_saved_traces(
    *,
    input_dir: str | Path,
    cases_dir: str | Path = "cases",
    output_dir: str | Path | None = None,
    previous_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    case_map = {case.case_id: case for case in load_cases(cases_dir)}
    discovered = discover_saved_traces(input_dir)

    scored: list[dict[str, Any]] = []
    for execution in discovered:
        case_id = execution["case_id"]
        if case_id not in case_map:
            continue
        case = case_map[case_id]
        trace = execution["trace"]
        scored.append(
            {
                "case": case,
                "repeat_index": execution["repeat_index"],
                "trace_path": execution["trace_path"],
                "selected_attempt": execution["selected_attempt"],
                "attempts": execution["attempts"],
                "trace": trace,
                "score": score_case(case, trace),
            }
        )

    destination = Path(output_dir or input_dir)
    destination.mkdir(parents=True, exist_ok=True)
    report = build_report(
        scored,
        run_id=destination.name,
        mode="rescore",
        output_dir=destination,
        cases_dir=cases_dir,
        config={"input_dir": str(input_dir)},
        previous_report=previous_report,
    )
    report_path = write_report(report, destination)
    viewer_path = write_run_viewer(report, destination)
    return {
        "run_dir": destination,
        "report_path": report_path,
        "viewer_path": viewer_path,
        "report": report,
    }
