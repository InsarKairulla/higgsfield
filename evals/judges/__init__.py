from __future__ import annotations

import os

from evals.judges.anthropic import AnthropicJudge
from evals.judges.base import JudgeClient, JudgeConfig
from evals.judges.openai import OpenAIJudge


_SUPPORTED_PROVIDERS = {"anthropic", "openai"}


def resolve_judge_config(
    *,
    provider: str | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
    no_judge: bool = False,
) -> JudgeConfig:
    if no_judge:
        return JudgeConfig(enabled=False, disabled_reason="judge disabled by configuration")

    resolved_provider = (provider or os.getenv("DRL_JUDGE_PROVIDER", "")).strip()
    resolved_model = (model or os.getenv("DRL_JUDGE_MODEL", "")).strip()
    resolved_max_tokens = max_tokens or int(os.getenv("DRL_JUDGE_MAX_TOKENS", "900"))

    if not resolved_provider or not resolved_model:
        return JudgeConfig(
            enabled=False,
            provider=resolved_provider,
            model=resolved_model,
            max_tokens=resolved_max_tokens,
            disabled_reason="judge disabled: no judge provider/model configured",
        )

    if resolved_provider not in _SUPPORTED_PROVIDERS:
        return JudgeConfig(
            enabled=False,
            provider=resolved_provider,
            model=resolved_model,
            max_tokens=resolved_max_tokens,
            disabled_reason=f"judge disabled: unsupported provider {resolved_provider!r}",
        )

    return JudgeConfig(
        enabled=True,
        provider=resolved_provider,
        model=resolved_model,
        max_tokens=resolved_max_tokens,
    )


def build_judge_client(config: JudgeConfig) -> JudgeClient | None:
    if not config.enabled:
        return None
    if config.provider == "anthropic":
        return AnthropicJudge(config)
    if config.provider == "openai":
        return OpenAIJudge(config)
    return None
