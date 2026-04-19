from __future__ import annotations

from typing import Any

from evals.cases import CaseSpec
from evals.judges.base import (
    ExtractedQuoteEvidence,
    FetchedPageEvidence,
    JudgeInput,
)
from evals.trace import Trace


def _normalize_metric_context(case: CaseSpec, metric_context: dict[str, Any]) -> dict[str, Any]:
    internal_keys = {"enabled", "pass_threshold", "rubric_path"}
    filtered_context = {
        str(key): value
        for key, value in metric_context.items()
        if str(key) not in internal_keys
    }
    return {
        "case_description": case.description,
        "case_tags": list(case.tags),
        "case_notes": case.notes,
        "metric_config": filtered_context,
    }


def _collect_fetched_pages(trace: Trace) -> list[FetchedPageEvidence]:
    pages: list[FetchedPageEvidence] = []
    for call in trace.tool_calls("fetch_url"):
        content = call.result if isinstance(call.result, str) else ""
        pages.append(
            FetchedPageEvidence(
                url=str(call.args.get("url") or ""),
                content=content,
            )
        )
    return pages


def _collect_extracted_quotes(
    trace: Trace, fetched_pages: list[FetchedPageEvidence]
) -> list[ExtractedQuoteEvidence]:
    content_to_urls: dict[str, str] = {
        page.content: page.url for page in fetched_pages if page.content and page.url
    }
    quotes: list[ExtractedQuoteEvidence] = []
    for call in trace.tool_calls("extract_quotes"):
        topic = str(call.args.get("topic") or "")
        source_text = str(call.args.get("text") or "")
        source_url = content_to_urls.get(source_text)
        if not isinstance(call.result, list):
            continue
        for quote in call.result:
            quotes.append(
                ExtractedQuoteEvidence(
                    quote=str(quote),
                    topic=topic,
                    source_url=source_url,
                )
            )
    return quotes


def build_judge_input(
    metric_name: str,
    case: CaseSpec,
    trace: Trace,
    rubric_text: str,
    metric_context: dict[str, Any],
) -> JudgeInput:
    fetched_pages = _collect_fetched_pages(trace)
    extracted_quotes = _collect_extracted_quotes(trace, fetched_pages)
    return JudgeInput(
        metric_name=metric_name,
        case_id=case.case_id,
        question=trace.question,
        final_answer=trace.final_answer,
        citations=trace.citations,
        stopped_reason=trace.stopped_reason,
        fetched_pages=fetched_pages,
        extracted_quotes=extracted_quotes,
        rubric_text=rubric_text,
        metric_context=_normalize_metric_context(case, metric_context),
    )

