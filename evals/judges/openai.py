from __future__ import annotations

import json
import os
from urllib import error, request

from evals.judges.base import JudgeClient, JudgeConfig, JudgeInput, JudgeOutput
from evals.judges.prompting import (
    JUDGE_SYSTEM_PROMPT,
    build_judge_user_prompt,
    build_openai_response_format,
)
from evals.judges.schema import parse_judge_response


class OpenAIJudge(JudgeClient):
    def __init__(self, config: JudgeConfig):
        self._config = config
        self._api_key = os.getenv("OPENAI_API_KEY", "").strip()

    def evaluate(self, judge_input: JudgeInput) -> JudgeOutput:
        if not self._api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")

        raw_text = self._create_completion(judge_input)
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

    def _create_completion(self, judge_input: JudgeInput) -> str:
        body = {
            "model": self._config.model,
            "temperature": self._config.temperature,
            "max_tokens": self._config.max_tokens,
            "response_format": build_openai_response_format(judge_input.metric_name),
            "messages": [
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": build_judge_user_prompt(judge_input)},
            ],
        }
        payload = json.dumps(body).encode("utf-8")
        req = request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(self._format_error(detail, exc)) from exc
        except error.URLError as exc:
            raise RuntimeError(f"OpenAI judge request failed: {exc.reason}") from exc

        return self._extract_message_text(data)

    def _extract_message_text(self, response_payload: dict) -> str:
        choices = response_payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("OpenAI judge response did not contain any choices")

        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise RuntimeError("OpenAI judge response did not contain a message payload")

        refusal = message.get("refusal")
        if isinstance(refusal, str) and refusal.strip():
            raise RuntimeError(f"OpenAI judge refused the request: {refusal.strip()}")

        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            text_parts = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    text_parts.append(text.strip())
            if text_parts:
                return "\n".join(text_parts)

        raise RuntimeError("OpenAI judge response did not contain text content")

    def _format_error(self, detail: str, exc: error.HTTPError) -> str:
        try:
            payload = json.loads(detail)
        except json.JSONDecodeError:
            payload = None

        if isinstance(payload, dict):
            err = payload.get("error")
            if isinstance(err, dict):
                message = err.get("message")
                if isinstance(message, str) and message.strip():
                    return f"OpenAI judge request failed ({exc.code}): {message.strip()}"

        return f"OpenAI judge request failed ({exc.code}): {detail.strip() or exc.reason}"
