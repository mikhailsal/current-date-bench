"""Cache: save/load API responses and judge scores as JSON files.

Cache structure:
  cache/{model_slug}/run_{N}/rep_{R}.json

Each JSON file contains:
  - response: the model's raw text response
  - judge_scores: dict with classification from the judge (added later)
  - metadata: model, repetition, timestamp
  - gen_cost: cost/token info for the generation call
  - judge_cost: cost/token info for the judge call
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import CACHE_DIR, model_id_to_slug


def _cache_path(model_slug: str, run: int, repetition: int) -> Path:
    return CACHE_DIR / model_slug / f"run_{run}" / f"rep_{repetition}.json"


def load_cached_response(model_slug: str, run: int, repetition: int) -> dict[str, Any] | None:
    path = _cache_path(model_slug, run, repetition)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_response(
    model_slug: str,
    run: int,
    repetition: int,
    response_text: str,
    messages: list[dict[str, Any]],
    model_id: str,
    gen_cost: dict[str, Any] | None = None,
) -> Path:
    path = _cache_path(model_slug, run, repetition)
    path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "metadata": {
            "model": model_id,
            "run": run,
            "repetition": repetition,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "response": response_text,
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
    model_slug: str,
    run: int,
    repetition: int,
    scores: dict[str, Any],
    judge_raw_response: str = "",
    judge_cost: dict[str, Any] | None = None,
) -> None:
    path = _cache_path(model_slug, run, repetition)
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


def list_available_runs(model_slug: str) -> list[int]:
    model_dir = CACHE_DIR / model_slug
    if not model_dir.exists():
        return []
    runs: list[int] = []
    for d in sorted(model_dir.iterdir()):
        if d.is_dir():
            m = re.match(r"^run_(\d+)$", d.name)
            if m:
                runs.append(int(m.group(1)))
    return sorted(runs)


def list_all_cached_models() -> list[str]:
    if not CACHE_DIR.exists():
        return []
    return sorted(d.name for d in CACHE_DIR.iterdir() if d.is_dir())


def list_repetitions_in_run(model_slug: str, run: int) -> list[int]:
    run_dir = CACHE_DIR / model_slug / f"run_{run}"
    if not run_dir.exists():
        return []
    reps: list[int] = []
    for f in sorted(run_dir.glob("rep_*.json")):
        m = re.match(r"^rep_(\d+)\.json$", f.name)
        if m:
            reps.append(int(m.group(1)))
    return sorted(reps)
