"""Scorer: aggregates judge classifications into per-model, per-prompt statistics.

For each model config + prompt config combination, collects the classification
distribution (correct_date, wrong_date, refusal) across all repetitions.
Also computes aggregate scores across all prompts for a model config.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.cache import (
    list_prompt_ids_for_config,
    list_repetitions,
    load_cached_response,
)
from src.config import NUM_REPETITIONS, ModelConfig


@dataclass
class PromptResult:
    """Results for a single prompt configuration."""
    prompt_id: str = ""
    correct_date: int = 0
    wrong_date: int = 0
    refusal: int = 0
    total: int = 0

    @property
    def correct_pct(self) -> float:
        return (self.correct_date / self.total * 100) if self.total else 0.0

    @property
    def wrong_pct(self) -> float:
        return (self.wrong_date / self.total * 100) if self.total else 0.0

    @property
    def refusal_pct(self) -> float:
        return (self.refusal / self.total * 100) if self.total else 0.0


@dataclass
class ModelScore:
    model_id: str = ""
    config_slug: str = ""
    display_label: str = ""
    reasoning_effort: str = ""
    temperature: float = 0.7
    provider: str | None = None
    prompt_results: list[PromptResult] = field(default_factory=list)
    total_correct: int = 0
    total_wrong: int = 0
    total_refusal: int = 0
    total_responses: int = 0
    correct_pct: float = 0.0
    wrong_pct: float = 0.0
    refusal_pct: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "config_slug": self.config_slug,
            "display_label": self.display_label,
            "reasoning_effort": self.reasoning_effort,
            "temperature": self.temperature,
            "provider": self.provider,
            "total_responses": self.total_responses,
            "correct_date": self.total_correct,
            "wrong_date": self.total_wrong,
            "refusal": self.total_refusal,
            "correct_pct": round(self.correct_pct, 1),
            "wrong_pct": round(self.wrong_pct, 1),
            "refusal_pct": round(self.refusal_pct, 1),
            "prompts": [
                {
                    "prompt_id": pr.prompt_id,
                    "correct_date": pr.correct_date,
                    "wrong_date": pr.wrong_date,
                    "refusal": pr.refusal,
                    "total": pr.total,
                    "correct_pct": round(pr.correct_pct, 1),
                    "wrong_pct": round(pr.wrong_pct, 1),
                    "refusal_pct": round(pr.refusal_pct, 1),
                }
                for pr in self.prompt_results
            ],
        }


def _collect_prompt_results(
    config_slug: str,
    prompt_id: str,
    num_repetitions: int = NUM_REPETITIONS,
) -> PromptResult:
    result = PromptResult(prompt_id=prompt_id)
    for rep in range(1, num_repetitions + 1):
        cached = load_cached_response(config_slug, prompt_id, rep)
        if not cached:
            continue
        scores = cached.get("judge_scores")
        if not scores or not isinstance(scores, dict):
            continue

        classification = scores.get("classification", "")
        result.total += 1
        if classification == "correct_date":
            result.correct_date += 1
        elif classification == "wrong_date":
            result.wrong_date += 1
        elif classification == "refusal":
            result.refusal += 1

    return result


def score_model(
    model_config: ModelConfig,
    *,
    prompt_ids: list[str] | None = None,
    num_repetitions: int = NUM_REPETITIONS,
) -> ModelScore:
    """Score a model config across all (or specified) prompt configs.

    If prompt_ids is None, scores all prompt subdirectories found in cache.
    """
    config_slug = model_config.config_slug

    if prompt_ids is None:
        prompt_ids = list_prompt_ids_for_config(config_slug)
    if not prompt_ids:
        return ModelScore(
            model_id=model_config.model_id,
            config_slug=config_slug,
            display_label=model_config.label,
            reasoning_effort=model_config.effective_reasoning,
            temperature=model_config.effective_temperature,
            provider=model_config.provider,
        )

    all_prompts: list[PromptResult] = []
    for pid in prompt_ids:
        pr = _collect_prompt_results(config_slug, pid, num_repetitions)
        if pr.total > 0:
            all_prompts.append(pr)

    if not all_prompts:
        return ModelScore(
            model_id=model_config.model_id,
            config_slug=config_slug,
            display_label=model_config.label,
            reasoning_effort=model_config.effective_reasoning,
            temperature=model_config.effective_temperature,
            provider=model_config.provider,
        )

    total_correct = sum(pr.correct_date for pr in all_prompts)
    total_wrong = sum(pr.wrong_date for pr in all_prompts)
    total_refusal = sum(pr.refusal for pr in all_prompts)
    total_responses = sum(pr.total for pr in all_prompts)

    correct_pct = total_correct / total_responses * 100 if total_responses else 0.0
    wrong_pct = total_wrong / total_responses * 100 if total_responses else 0.0
    refusal_pct = total_refusal / total_responses * 100 if total_responses else 0.0

    return ModelScore(
        model_id=model_config.model_id,
        config_slug=config_slug,
        display_label=model_config.label,
        reasoning_effort=model_config.effective_reasoning,
        temperature=model_config.effective_temperature,
        provider=model_config.provider,
        prompt_results=all_prompts,
        total_correct=total_correct,
        total_wrong=total_wrong,
        total_refusal=total_refusal,
        total_responses=total_responses,
        correct_pct=correct_pct,
        wrong_pct=wrong_pct,
        refusal_pct=refusal_pct,
    )
