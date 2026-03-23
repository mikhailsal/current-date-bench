"""Cost tracker: per-task, per-session tracking with JSON log."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import src.config as _cfg


@dataclass
class TaskCost:
    label: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    elapsed_seconds: float = 0.0
    n_calls: int = 0

    def add(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float,
        elapsed_seconds: float = 0.0,
    ) -> None:
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        self.cost_usd += cost_usd
        self.elapsed_seconds += elapsed_seconds
        self.n_calls += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "n_calls": self.n_calls,
        }


@dataclass
class SessionCost:
    tasks: list[TaskCost] = field(default_factory=list)
    started_at: str = ""

    def __post_init__(self) -> None:
        if not self.started_at:
            self.started_at = datetime.now(timezone.utc).isoformat()

    @property
    def total_prompt_tokens(self) -> int:
        return sum(t.prompt_tokens for t in self.tasks)

    @property
    def total_completion_tokens(self) -> int:
        return sum(t.completion_tokens for t in self.tasks)

    @property
    def total_cost_usd(self) -> float:
        return sum(t.cost_usd for t in self.tasks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "tasks": [t.to_dict() for t in self.tasks],
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_cost_usd": round(self.total_cost_usd, 6),
        }


def load_lifetime_cost() -> float:
    cost_log = _cfg.COST_LOG_PATH
    if not cost_log.exists():
        return 0.0
    try:
        data = json.loads(cost_log.read_text(encoding="utf-8"))
        return float(data.get("lifetime_cost_usd", 0.0))
    except (json.JSONDecodeError, ValueError):
        return 0.0


def save_session_to_cost_log(session: SessionCost) -> float:
    results_dir = _cfg.RESULTS_DIR
    cost_log = _cfg.COST_LOG_PATH
    results_dir.mkdir(parents=True, exist_ok=True)

    existing_sessions: list[dict[str, Any]] = []
    lifetime = 0.0
    if cost_log.exists():
        try:
            data = json.loads(cost_log.read_text(encoding="utf-8"))
            existing_sessions = data.get("sessions", [])
            lifetime = float(data.get("lifetime_cost_usd", 0.0))
        except (json.JSONDecodeError, ValueError):
            pass

    lifetime += session.total_cost_usd
    existing_sessions.append(session.to_dict())

    log_data = {
        "lifetime_cost_usd": round(lifetime, 6),
        "sessions": existing_sessions,
    }
    cost_log.write_text(
        json.dumps(log_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return lifetime
