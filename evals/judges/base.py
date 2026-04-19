from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class JudgeConfig:
    enabled: bool
    provider: str = ""
    model: str = ""
    max_tokens: int = 900
    temperature: float = 0.0
    disabled_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "provider": self.provider,
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "disabled_reason": self.disabled_reason,
        }


@dataclass(frozen=True)
class FetchedPageEvidence:
    url: str
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"url": self.url, "content": self.content}


@dataclass(frozen=True)
class ExtractedQuoteEvidence:
    quote: str
    topic: str
    source_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "quote": self.quote,
            "topic": self.topic,
            "source_url": self.source_url,
        }


@dataclass(frozen=True)
class JudgeInput:
    metric_name: str
    case_id: str
    question: str
    final_answer: str
    citations: list[str]
    stopped_reason: str
    fetched_pages: list[FetchedPageEvidence]
    extracted_quotes: list[ExtractedQuoteEvidence]
    rubric_text: str
    metric_context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_name": self.metric_name,
            "case_id": self.case_id,
            "question": self.question,
            "final_answer": self.final_answer,
            "citations": self.citations,
            "stopped_reason": self.stopped_reason,
            "fetched_pages": [page.to_dict() for page in self.fetched_pages],
            "extracted_quotes": [quote.to_dict() for quote in self.extracted_quotes],
            "rubric_text": self.rubric_text,
            "metric_context": self.metric_context,
        }


@dataclass(frozen=True)
class RubricItemAssessment:
    item: str
    assessment: str
    evidence: str

    def to_dict(self) -> dict[str, str]:
        return {
            "item": self.item,
            "assessment": self.assessment,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class JudgeOutput:
    metric_name: str
    verdict: str
    passed: bool
    score: float
    rationale: str
    rubric_items: list[RubricItemAssessment]
    failure_modes_detected: list[str]
    provider: str = ""
    model: str = ""
    raw_response: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_name": self.metric_name,
            "verdict": self.verdict,
            "passed": self.passed,
            "score": self.score,
            "rationale": self.rationale,
            "rubric_items": [item.to_dict() for item in self.rubric_items],
            "failure_modes_detected": self.failure_modes_detected,
            "provider": self.provider,
            "model": self.model,
            "raw_response": self.raw_response,
        }


class JudgeClient(Protocol):
    def evaluate(self, judge_input: JudgeInput) -> JudgeOutput:
        """Return a validated structured verdict for the supplied metric input."""

