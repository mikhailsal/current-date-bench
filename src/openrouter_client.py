"""OpenRouter client: OpenAI SDK wrapper with retry logic, cost tracking, timing.

Supports reasoning effort, provider pinning, and empty-content retries.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
import requests
from openai import OpenAI

from src.config import (
    API_CALL_TIMEOUT,
    OPENROUTER_BASE_URL,
    OPENROUTER_MODELS_URL,
    ModelPricing,
    get_reasoning_effort,
)

log = logging.getLogger(__name__)


@dataclass
class UsageInfo:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    elapsed_seconds: float = 0.0


@dataclass
class CompletionResult:
    content: str = ""
    usage: UsageInfo = field(default_factory=UsageInfo)
    model: str = ""
    finish_reason: str = ""
    reasoning_content: str | None = None


def _usage_from_response(
    *, model: str, response: Any, elapsed: float, get_model_pricing: Any,
) -> UsageInfo:
    usage = UsageInfo(elapsed_seconds=elapsed)
    if not response.usage:
        return usage
    ru = response.usage
    usage.prompt_tokens = int(ru.prompt_tokens or 0)
    usage.completion_tokens = int(ru.completion_tokens or 0)

    raw_cost = getattr(ru, "cost", None)
    used_api_cost = False
    if isinstance(raw_cost, (int, float)) and not isinstance(raw_cost, bool):
        usage.cost_usd = float(raw_cost)
        used_api_cost = True
    elif isinstance(raw_cost, str) and raw_cost.strip():
        try:
            usage.cost_usd = float(raw_cost)
            used_api_cost = True
        except ValueError:
            pass

    if not used_api_cost:
        pricing = get_model_pricing(model)
        usage.cost_usd = (
            usage.prompt_tokens * pricing.prompt_price
            + usage.completion_tokens * pricing.completion_price
        )
    return usage


class OpenRouterClient:
    MAX_RETRIES = 5
    RETRY_BACKOFF_BASE = 3.0
    RETRYABLE_STATUS_CODES = {402, 429, 500, 502, 503}
    EMPTY_CONTENT_RETRIES = 2

    def __init__(self, api_key: str, timeout: float = API_CALL_TIMEOUT) -> None:
        self.api_key = api_key
        self._client = OpenAI(
            base_url=OPENROUTER_BASE_URL,
            api_key=api_key,
            timeout=httpx.Timeout(timeout, connect=10.0),
        )
        self._pricing_cache: dict[str, ModelPricing] = {}
        self._reasoning_models: set[str] = set()

    def fetch_pricing(self) -> dict[str, ModelPricing]:
        if self._pricing_cache:
            return self._pricing_cache
        resp = requests.get(
            OPENROUTER_MODELS_URL,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        for model in data:
            model_id = model.get("id", "")
            pricing = model.get("pricing", {})
            self._pricing_cache[model_id] = ModelPricing(
                prompt_price=float(pricing.get("prompt", "0")),
                completion_price=float(pricing.get("completion", "0")),
            )
            supported_params = model.get("supported_parameters", [])
            if "reasoning" in supported_params:
                self._reasoning_models.add(model_id)
        return self._pricing_cache

    def supports_reasoning(self, model_id: str) -> bool:
        if not self._pricing_cache:
            self.fetch_pricing()
        return model_id in self._reasoning_models

    def get_model_pricing(self, model_id: str) -> ModelPricing:
        if not self._pricing_cache:
            self.fetch_pricing()
        return self._pricing_cache.get(model_id, ModelPricing())

    def validate_model(self, model_id: str) -> bool:
        if not self._pricing_cache:
            self.fetch_pricing()
        return model_id in self._pricing_cache

    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 1024,
        temperature: float = 0.7,
        *,
        reasoning_effort: str | None = None,
        provider: str | None = None,
    ) -> CompletionResult:
        """Send a chat completion request with retry logic.

        Args:
            provider: OpenRouter provider slug to pin requests to (e.g.
                ``"moonshotai/int4"``). Disables fallbacks so every call
                is served by exactly this provider.
        """
        use_reasoning = self._resolve_reasoning_effort(model, reasoning_effort)
        accumulated = UsageInfo()

        for attempt in range(1, self.EMPTY_CONTENT_RETRIES + 2):
            result = self._chat_single(
                model=model, messages=messages,
                max_tokens=max_tokens, temperature=temperature,
                reasoning_effort=use_reasoning,
                provider=provider,
            )
            accumulated.prompt_tokens += result.usage.prompt_tokens
            accumulated.completion_tokens += result.usage.completion_tokens
            accumulated.cost_usd += result.usage.cost_usd
            accumulated.elapsed_seconds += result.usage.elapsed_seconds

            if result.content:
                result.usage = accumulated
                return result

            if attempt <= self.EMPTY_CONTENT_RETRIES:
                log.warning(
                    "%s: empty response, retry %d/%d",
                    model, attempt, self.EMPTY_CONTENT_RETRIES,
                )
                time.sleep(2.0 * attempt)
                continue

            result.usage = accumulated
            return result

        return result  # type: ignore[possibly-undefined]

    def _resolve_reasoning_effort(self, model: str, override: str | None) -> str | None:
        if override == "off":
            return None
        if override is not None and override != "auto":
            return override
        if not self.supports_reasoning(model):
            return None
        return get_reasoning_effort(model)

    def _chat_single(
        self, model: str, messages: list[dict[str, Any]],
        max_tokens: int, temperature: float,
        reasoning_effort: str | None = None,
        provider: str | None = None,
    ) -> CompletionResult:
        last_error: Exception | None = None
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                extra_body: dict[str, Any] | None = None
                if reasoning_effort:
                    extra_body = {"reasoning": {"effort": reasoning_effort}}

                if provider:
                    extra_body = extra_body or {}
                    extra_body["provider"] = {
                        "order": [provider],
                        "allow_fallbacks": False,
                    }

                kwargs: dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                }
                if extra_body:
                    kwargs["extra_body"] = extra_body

                t0 = time.monotonic()
                response = self._client.chat.completions.create(**kwargs)
                elapsed = time.monotonic() - t0

                finish_reason = ""
                content = ""
                reasoning_content = None
                if response.choices:
                    finish_reason = response.choices[0].finish_reason or ""
                    if response.choices[0].message.content:
                        content = response.choices[0].message.content.strip()
                    msg = response.choices[0].message
                    raw_reasoning = getattr(msg, "reasoning", None)
                    if raw_reasoning and isinstance(raw_reasoning, str):
                        reasoning_content = raw_reasoning.strip()
                    if not reasoning_content:
                        raw_rc = getattr(msg, "reasoning_content", None)
                        if raw_rc and isinstance(raw_rc, str):
                            reasoning_content = raw_rc.strip()

                usage = _usage_from_response(
                    model=model, response=response, elapsed=elapsed,
                    get_model_pricing=self.get_model_pricing,
                )
                return CompletionResult(
                    content=content, usage=usage,
                    model=model, finish_reason=finish_reason,
                    reasoning_content=reasoning_content,
                )
            except Exception as e:
                last_error = e
                status_code = getattr(e, "status_code", None)
                if status_code and status_code in self.RETRYABLE_STATUS_CODES:
                    if attempt < self.MAX_RETRIES:
                        wait = self.RETRY_BACKOFF_BASE ** (attempt + 1)
                        time.sleep(wait)
                        continue
                raise
        raise last_error or RuntimeError("Chat completion failed after retries")
