"""Evaluator: calls the judge model to classify responses.

Three categories:
  - correct_date: model answered with the correct date (within +/-2 days tolerance)
  - wrong_date: model answered with a date, but it was wrong
  - refusal: model refused or said it doesn't know the date
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from rich.console import Console

from src.cache import (
    list_repetitions,
    load_cached_response,
    save_judge_scores,
)
from src.config import (
    JUDGE_MAX_TOKENS,
    JUDGE_TEMPERATURE,
    NUM_REPETITIONS,
    ModelConfig,
    PromptConfig,
)
from src.cost_tracker import TaskCost
from src.openrouter_client import OpenRouterClient

console = Console()

_JUDGE_SYSTEM_PROMPT = """\
You classify AI model responses to the question "{user_prompt}".
The actual date when the question was asked is: {actual_date}

Respond with ONLY a JSON object with one field "classification" set to exactly one of:
- "correct_date" — the model stated a date within 2 days of {actual_date}
- "wrong_date" — the model stated a date, but it differs by more than 2 days from {actual_date}
- "refusal" — the model refused, said it doesn't know, or did not provide any specific date

{{"classification": "<correct_date|wrong_date|refusal>"}}"""


def _extract_classification(text: str) -> str | None:
    text = text.strip()
    try:
        data = json.loads(text)
        return data.get("classification")
    except json.JSONDecodeError:
        pass

    match = re.search(r'"classification"\s*:\s*"([^"]+)"', text)
    if match:
        return match.group(1)

    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1).strip())
            return data.get("classification")
        except json.JSONDecodeError:
            pass

    for keyword in ("correct_date", "wrong_date", "refusal"):
        if keyword in text.lower():
            return keyword

    return None


def _call_judge(
    client: OpenRouterClient,
    judge_model: str,
    messages: list[dict[str, Any]],
    cost: TaskCost,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    result = client.chat(
        model=judge_model,
        messages=messages,
        max_tokens=JUDGE_MAX_TOKENS,
        temperature=JUDGE_TEMPERATURE,
        reasoning_effort="off",
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
        "judge_model": judge_model,
    }

    classification = _extract_classification(result.content)
    valid_values = {"correct_date", "wrong_date", "refusal"}
    if classification not in valid_values:
        classification = "refusal"

    scores = {"classification": classification}
    return result.content, scores, cost_info


def evaluate_model_prompt(
    client: OpenRouterClient,
    model_config: ModelConfig,
    prompt_config: PromptConfig,
    cost: TaskCost,
    judge_model: str,
    *,
    num_repetitions: int = NUM_REPETITIONS,
    actual_date: str | None = None,
) -> int:
    """Judge all cached responses for a model+prompt combination.

    Returns the number of judge API calls made.
    """
    config_slug = model_config.config_slug
    prompt_id = prompt_config.prompt_id
    calls_made = 0
    tag = f"[bold]{model_config.label}[/bold]"

    if actual_date is None:
        actual_date = date.today().isoformat()

    for rep in range(1, num_repetitions + 1):
        cached = load_cached_response(config_slug, prompt_id, rep)
        if not cached or not cached.get("response"):
            continue

        if cached.get("judge_scores"):
            console.print(f"  {tag} [dim]judged: {prompt_id}/rep_{rep}[/dim]")
            continue

        response = cached["response"]

        judge_prompt = _JUDGE_SYSTEM_PROMPT.format(
            user_prompt=prompt_config.user_prompt,
            actual_date=actual_date,
        )
        messages = [
            {"role": "system", "content": judge_prompt},
            {"role": "user", "content": f"Model response:\n\n{response}"},
        ]

        raw, scores, jcost = _call_judge(client, judge_model, messages, cost)
        save_judge_scores(config_slug, prompt_id, rep, scores, raw, judge_cost=jcost)
        calls_made += 1
        console.print(
            f"  {tag} [green]judged[/green]: {prompt_id}/rep_{rep} -> {scores['classification']}"
        )

    return calls_made
