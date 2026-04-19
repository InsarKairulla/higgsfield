from __future__ import annotations

from evals.judges.base import JudgeClient, JudgeConfig, JudgeInput, JudgeOutput
from evals.judges.prompting import JUDGE_SYSTEM_PROMPT, build_judge_user_prompt
from evals.judges.schema import parse_judge_response


class AnthropicJudge(JudgeClient):
    def __init__(self, config: JudgeConfig):
        from anthropic import Anthropic

        self._config = config
        self._client = Anthropic()

    def evaluate(self, judge_input: JudgeInput) -> JudgeOutput:
        response = self._client.messages.create(
            model=self._config.model,
            max_tokens=self._config.max_tokens,
            temperature=self._config.temperature,
            system=JUDGE_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": build_judge_user_prompt(judge_input),
                }
            ],
        )
        raw_text = "".join(
            block.text
            for block in response.content
            if getattr(block, "type", "") == "text"
        )
        parsed = parse_judge_response(raw_text, judge_input.metric_name)
        return JudgeOutput(
            metric_name=parsed.metric_name,
            verdict=parsed.verdict,
            passed=parsed.passed,
            score=parsed.score,
            rationale=parsed.rationale,
            rubric_items=parsed.rubric_items,
            failure_modes_detected=parsed.failure_modes_detected,
            provider=self._config.provider,
            model=self._config.model,
            raw_response=raw_text,
        )
