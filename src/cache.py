"""Cache: save/load API responses and judge scores as JSON files.

New cache structure (flat repetitions, per-prompt):
  cache/{config_slug}/{prompt_id}/rep_{N}.json

Where config_slug is e.g. ``openai--gpt-5-nano@low-t1.0``
and prompt_id is e.g. ``current_date`` or ``what_is_date_today``.

Each JSON file contains:
  - metadata: model, prompt_id, repetition, timestamp, settings
  - response: the model's raw text response
  - reasoning_content: reasoning/thinking tokens (if any)
  - request_messages: the messages sent to the API
  - gen_cost: cost/token info for the generation call
  - judge_scores: dict with classification from the judge (added later)
  - judge_cost: cost/token info for the judge call
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import CACHE_DIR


def _cache_path(config_slug: str, prompt_id: str, repetition: int) -> Path:
    return CACHE_DIR / config_slug / prompt_id / f"rep_{repetition}.json"


def load_cached_response(
    config_slug: str, prompt_id: str, repetition: int,
) -> dict[str, Any] | None:
    path = _cache_path(config_slug, prompt_id, repetition)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_response(
    config_slug: str,
    prompt_id: str,
    repetition: int,
    response_text: str,
    messages: list[dict[str, Any]],
    model_id: str,
    *,
    reasoning_content: str | None = None,
    gen_cost: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
) -> Path:
    path = _cache_path(config_slug, prompt_id, repetition)
    path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "metadata": {
            "model": model_id,
            "prompt_id": prompt_id,
            "repetition": repetition,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "settings": settings or {},
        },
        "response": response_text,
        "reasoning_content": reasoning_content,
        "request_messages": messages,
        "gen_cost": gen_cost,
        "judge_scores": None,
        "judge_cost": None,
    }

    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def save_judge_scores(
    config_slug: str,
    prompt_id: str,
    repetition: int,
    scores: dict[str, Any],
    judge_raw_response: str = "",
    judge_cost: dict[str, Any] | None = None,
) -> None:
    path = _cache_path(config_slug, prompt_id, repetition)
    if not path.exists():
        return

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return

    data["judge_scores"] = scores
    if judge_raw_response:
        data["judge_raw_response"] = judge_raw_response
    if judge_cost is not None:
        data["judge_cost"] = judge_cost

    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def list_repetitions(config_slug: str, prompt_id: str) -> list[int]:
    """List all repetition numbers for a config+prompt combination."""
    prompt_dir = CACHE_DIR / config_slug / prompt_id
    if not prompt_dir.exists():
        return []
    reps: list[int] = []
    for f in sorted(prompt_dir.glob("rep_*.json")):
        m = re.match(r"^rep_(\d+)\.json$", f.name)
        if m:
            reps.append(int(m.group(1)))
    return sorted(reps)


def list_prompt_ids_for_config(config_slug: str) -> list[str]:
    """List all prompt_id subdirectories for a given config."""
    config_dir = CACHE_DIR / config_slug
    if not config_dir.exists():
        return []
    return sorted(
        d.name for d in config_dir.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    )


def list_all_cached_configs() -> list[str]:
    """List all config_slug directories in the cache."""
    if not CACHE_DIR.exists():
        return []
    return sorted(d.name for d in CACHE_DIR.iterdir() if d.is_dir())
