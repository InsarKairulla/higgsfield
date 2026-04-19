from __future__ import annotations

from evals.cases import CaseSpec
from evals.judges.input_builder import build_judge_input
from evals.judges.rubrics import RubricLoadError, load_rubric_text
from evals.scoring import MetricResult, ScoringContext, register_metric
from evals.trace import Trace


def _skip_metric(metric_name: str, reason: str) -> MetricResult:
    return MetricResult(
        name=metric_name,
        passed=True,
        score=0.0,
        summary=reason,
        skipped=True,
        details={"skip_reason": reason},
    )


def _judge_metric(
    metric_name: str,
    case: CaseSpec,
    trace: Trace,
    config: dict,
    context: ScoringContext,
) -> MetricResult:
    if config.get("enabled") is False:
        return _skip_metric(metric_name, "judge metric disabled in case config")

    judge_config = context.judge_config
    judge_client = context.judge_client
    if judge_config is None or judge_client is None or not getattr(judge_config, "enabled", False):
        reason = (
            getattr(judge_config, "disabled_reason", "")
            or "judge disabled: no judge provider/model configured"
        )
        return _skip_metric(metric_name, reason)

    pass_threshold = float(config.get("pass_threshold", 0.7))
    try:
        rubric_text, rubric_paths = load_rubric_text(metric_name, case, config)
        judge_input = build_judge_input(metric_name, case, trace, rubric_text, config)
        judge_output = judge_client.evaluate(judge_input)
    except RubricLoadError as exc:
        return MetricResult(
            name=metric_name,
            passed=False,
            score=0.0,
            summary=f"judge rubric error: {exc}",
            details={"error": str(exc)},
        )
    except Exception as exc:
        return MetricResult(
            name=metric_name,
            passed=False,
            score=0.0,
            summary=f"judge error: {type(exc).__name__}: {exc}",
            details={"error": f"{type(exc).__name__}: {exc}"},
        )

    passed = bool(judge_output.passed) and float(judge_output.score) >= pass_threshold
    summary = judge_output.rationale if not passed else f"judge passed ({judge_output.verdict})"
    return MetricResult(
        name=metric_name,
        passed=passed,
        score=float(judge_output.score),
        summary=summary,
        details={
            "judge": judge_output.to_dict(),
            "judge_input": judge_input.to_dict(),
            "rubric_paths": rubric_paths,
            "pass_threshold": pass_threshold,
        },
    )


@register_metric("factual_correctness")
def score_factual_correctness(
    case: CaseSpec, trace: Trace, config: dict, context: ScoringContext
) -> MetricResult:
    return _judge_metric("factual_correctness", case, trace, config, context)


@register_metric("ambiguity_handling")
def score_ambiguity_handling(
    case: CaseSpec, trace: Trace, config: dict, context: ScoringContext
) -> MetricResult:
    return _judge_metric("ambiguity_handling", case, trace, config, context)


@register_metric("refusal_correctness")
def score_refusal_correctness(
    case: CaseSpec, trace: Trace, config: dict, context: ScoringContext
) -> MetricResult:
    return _judge_metric("refusal_correctness", case, trace, config, context)


@register_metric("contradiction_disclosure")
def score_contradiction_disclosure(
    case: CaseSpec, trace: Trace, config: dict, context: ScoringContext
) -> MetricResult:
    return _judge_metric("contradiction_disclosure", case, trace, config, context)


@register_metric("citation_grounding_quality")
def score_citation_grounding_quality(
    case: CaseSpec, trace: Trace, config: dict, context: ScoringContext
) -> MetricResult:
    return _judge_metric("citation_grounding_quality", case, trace, config, context)

