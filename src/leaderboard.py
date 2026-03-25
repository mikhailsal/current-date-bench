"""Leaderboard: display and export results for the Current Date Benchmark."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table
from rich.text import Text

from src.config import RESULTS_DIR
from src.cost_tracker import SessionCost
from src.scorer import ModelScore

console = Console()


def display_leaderboard(
    model_scores: list[ModelScore],
    *,
    session: SessionCost | None = None,
    lifetime_cost: float = 0.0,
) -> None:
    if not model_scores:
        console.print("[dim]No scores to display.[/dim]")
        return

    sorted_scores = sorted(
        model_scores,
        key=lambda s: (s.refusal_pct, -s.wrong_pct),
        reverse=True,
    )
    has_multi_prompt = any(len(ms.prompt_results) > 1 for ms in sorted_scores)

    table = Table(
        title="Current Date Bench -- Honesty Leaderboard",
        title_style="bold",
        show_lines=False,
        box=None,
        expand=False,
        padding=(0, 1),
    )
    table.add_column("#", justify="right", style="dim", width=2)
    table.add_column("Model", style="bold", max_width=40, no_wrap=True, overflow="ellipsis")
    table.add_column("Reason", justify="center", width=6)
    table.add_column("Temp", justify="right", width=4)
    table.add_column("Honest%", justify="right", width=8)
    table.add_column("Halluc%", justify="right", width=8)
    table.add_column("HasDate%", justify="right", width=8)
    table.add_column("N", justify="right", width=3)
    if has_multi_prompt:
        table.add_column("Prompts", justify="right", width=7)

    for rank, ms in enumerate(sorted_scores, 1):
        if ms.refusal_pct >= 80:
            honesty_style = "bold green"
        elif ms.refusal_pct >= 20:
            honesty_style = "green"
        elif ms.refusal_pct > 0:
            honesty_style = "yellow"
        else:
            honesty_style = "dim"

        if ms.wrong_pct >= 80:
            halluc_style = "bold red"
        elif ms.wrong_pct > 0:
            halluc_style = "red"
        else:
            halluc_style = "dim"

        has_date_style = "cyan" if ms.correct_pct > 0 else "dim"

        reasoning_display = ms.reasoning_effort or "auto"
        temp_display = f"{ms.temperature:.1f}"

        row: list[str | Text] = [
            str(rank),
            ms.display_label,
            Text(reasoning_display, style="yellow" if reasoning_display != "none" else "dim"),
            Text(temp_display, style="dim"),
            Text(f"{ms.refusal_pct:.0f}%", style=honesty_style),
            Text(f"{ms.wrong_pct:.0f}%", style=halluc_style),
            Text(f"{ms.correct_pct:.0f}%", style=has_date_style),
            str(ms.total_responses),
        ]

        if has_multi_prompt:
            row.append(str(len(ms.prompt_results)))

        table.add_row(*row)

    console.print()
    console.print(table)

    if session:
        console.print(
            f"\n  [dim]Session cost: ${session.total_cost_usd:.4f} "
            f"({session.total_prompt_tokens:,} in / {session.total_completion_tokens:,} out)[/dim]"
        )
    if lifetime_cost > 0:
        console.print(f"  [dim]Lifetime cost: ${lifetime_cost:.4f}[/dim]")


def display_detailed(model_scores: list[ModelScore]) -> None:
    for ms in sorted(model_scores, key=lambda s: (s.refusal_pct, -s.wrong_pct), reverse=True):
        console.print(f"\n[bold]{ms.display_label}[/bold]")
        console.print(
            f"  Config: reasoning={ms.reasoning_effort}, temp={ms.temperature}"
            + (f", provider={ms.provider}" if ms.provider else "")
        )
        console.print(
            f"  Honest (refused): {ms.total_refusal}/{ms.total_responses} ({ms.refusal_pct:.1f}%)"
        )
        console.print(
            f"  Hallucinated:     {ms.total_wrong}/{ms.total_responses} ({ms.wrong_pct:.1f}%)"
        )
        console.print(
            f"  Has date (injected): {ms.total_correct}/{ms.total_responses} ({ms.correct_pct:.1f}%)"
        )

        if len(ms.prompt_results) > 1:
            console.print("  [dim]Per-prompt breakdown:[/dim]")
            for pr in ms.prompt_results:
                console.print(
                    f"    {pr.prompt_id}: "
                    f"{pr.correct_date}v {pr.wrong_date}x {pr.refusal}? "
                    f"(of {pr.total}) — "
                    f"honest={pr.refusal_pct:.0f}% halluc={pr.wrong_pct:.0f}%"
                )


def export_results_json(
    model_scores: list[ModelScore],
    *,
    session: SessionCost | None = None,
    lifetime_cost: float = 0.0,
) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = RESULTS_DIR / f"results_{timestamp}.json"

    data: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "benchmark": "current_date",
        "models": [ms.to_dict() for ms in sorted(
            model_scores, key=lambda s: (s.refusal_pct, -s.wrong_pct), reverse=True
        )],
    }
    if session:
        data["session_cost"] = session.to_dict()
    if lifetime_cost > 0:
        data["lifetime_cost_usd"] = round(lifetime_cost, 6)

    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path
