"""Runner: sends the configured prompt to a model and caches responses.

Supports configurable system_prompt + user_prompt pairs, reasoning effort,
temperature, provider pinning, and flat repetition structure.
"""

from __future__ import annotations

from typing import Any

from rich.console import Console

from src.cache import load_cached_response, save_response
from src.config import (
    NUM_REPETITIONS,
    ModelConfig,
    PromptConfig,
)
from src.cost_tracker import TaskCost
from src.openrouter_client import OpenRouterClient

console = Console()


def run_prompt_experiment(
    client: OpenRouterClient,
    model_config: ModelConfig,
    prompt_config: PromptConfig,
    cost: TaskCost,
    *,
    num_repetitions: int = NUM_REPETITIONS,
) -> int:
    """Ask the model the configured prompt N times.

    Returns the number of API calls made (excluding cache hits).
    """
    config_slug = model_config.config_slug
    prompt_id = prompt_config.prompt_id
    model_id = model_config.model_id
    calls_made = 0
    tag = f"[bold]{model_config.label}[/bold]"

    temperature = model_config.effective_temperature
    reasoning = model_config.effective_reasoning

    settings_info = {
        "temperature": temperature,
        "reasoning_effort": reasoning,
        "provider": model_config.provider,
    }

    for rep in range(1, num_repetitions + 1):
        cached = load_cached_response(config_slug, prompt_id, rep)
        if cached and cached.get("response"):
            console.print(f"  {tag} [dim]cached: {prompt_id}/rep_{rep}[/dim]")
            continue

        messages: list[dict[str, Any]] = []
        if prompt_config.system_prompt:
            messages.append({"role": "system", "content": prompt_config.system_prompt})
        messages.append({"role": "user", "content": prompt_config.user_prompt})

        result = client.chat(
            model=model_id,
            messages=messages,
            max_tokens=model_config.effective_max_tokens,
            temperature=temperature,
            reasoning_effort=reasoning,
            provider=model_config.provider,
        )

        cost.add(
            prompt_tokens=result.usage.prompt_tokens,
            completion_tokens=result.usage.completion_tokens,
            cost_usd=result.usage.cost_usd,
            elapsed_seconds=result.usage.elapsed_seconds,
        )

        cost_info = {
            "prompt_tokens": result.usage.prompt_tokens,
            "completion_tokens": result.usage.completion_tokens,
            "cost_usd": round(result.usage.cost_usd, 6),
            "elapsed_seconds": round(result.usage.elapsed_seconds, 2),
        }

        save_response(
            config_slug, prompt_id, rep, result.content, messages, model_id,
            reasoning_content=result.reasoning_content,
            gen_cost=cost_info,
            settings=settings_info,
        )
        calls_made += 1
        console.print(f"  {tag} [green]done[/green]: {prompt_id}/rep_{rep}")

    return calls_made
