"""Runner: sends the 'current date' query to a model with an empty system prompt."""

from __future__ import annotations

from typing import Any

from rich.console import Console

from src.cache import load_cached_response, save_response
from src.config import RESPONSE_MAX_TOKENS, RESPONSE_TEMPERATURE, NUM_REPETITIONS, model_id_to_slug
from src.cost_tracker import TaskCost
from src.openrouter_client import OpenRouterClient

console = Console()


def run_current_date_experiment(
    client: OpenRouterClient,
    model_id: str,
    cost: TaskCost,
    *,
    run: int = 1,
    num_repetitions: int = NUM_REPETITIONS,
    reasoning_effort: str | None = None,
    temperature: float | None = None,
) -> int:
    """Ask the model 'current date' N times with an empty system prompt.

    Returns the number of API calls made (excluding cache hits).
    """
    model_slug = model_id_to_slug(model_id)
    calls_made = 0
    tag = f"[bold]{model_id}[/bold]"
    run_label = f" (run {run})" if run > 1 else ""

    for rep in range(1, num_repetitions + 1):
        cached = load_cached_response(model_slug, run, rep)
        if cached and cached.get("response"):
            console.print(f"  {tag} [dim]cached: rep {rep}{run_label}[/dim]")
            continue

        messages: list[dict[str, Any]] = [
            {"role": "user", "content": "current date"},
        ]

        result = client.chat(
            model=model_id,
            messages=messages,
            max_tokens=RESPONSE_MAX_TOKENS,
            temperature=temperature if temperature is not None else RESPONSE_TEMPERATURE,
            reasoning_effort=reasoning_effort,
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
            model_slug, run, rep, result.content, messages, model_id,
            gen_cost=cost_info,
        )
        calls_made += 1
        console.print(f"  {tag} [green]done[/green]: rep {rep}{run_label}")

    return calls_made
