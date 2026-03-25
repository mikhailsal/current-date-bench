"""Leaderboard: display, Markdown export, and JSON export for the Current Date Benchmark."""

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
    table.add_column("Model", style="bold", max_width=50, no_wrap=True, overflow="ellipsis")
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

        row: list[str | Text] = [
            str(rank),
            ms.display_label,
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


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------

def generate_markdown_report(
    model_scores: list[ModelScore],
    *,
    lifetime_cost: float = 0.0,
) -> str:
    """Generate a Markdown leaderboard report for GitHub / README embedding."""
    if not model_scores:
        return "No results available yet. Run the benchmark first.\n"

    sorted_scores = sorted(
        model_scores,
        key=lambda s: (s.refusal_pct, -s.wrong_pct),
        reverse=True,
    )
    has_multi_prompt = any(len(ms.prompt_results) > 1 for ms in sorted_scores)

    lines: list[str] = []
    lines.append("# Current Date Bench — Honesty Leaderboard\n")
    lines.append(
        f"> Auto-generated from benchmark results. "
        f"Last updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
    )
    lines.append("")

    prompt_ids = set()
    for ms in sorted_scores:
        for pr in ms.prompt_results:
            prompt_ids.add(pr.prompt_id)
    if prompt_ids:
        lines.append(f"**Prompts tested:** {', '.join(f'`{p}`' for p in sorted(prompt_ids))}")
    n_models = len([ms for ms in sorted_scores if ms.total_responses > 0])
    lines.append(f"**Models:** {n_models} | **Cost:** ${lifetime_cost:.4f} USD\n")
    lines.append("")

    # Main table
    header = "| # | Model | Honest% | Halluc% | HasDate% | N |"
    sep = "|--:|-------|--------:|--------:|---------:|--:|"
    if has_multi_prompt:
        header += " Prompts |"
        sep += "--------:|"

    lines.append(header)
    lines.append(sep)

    for rank, ms in enumerate(sorted_scores, 1):
        if ms.total_responses == 0:
            continue

        model_name = ms.display_label
        if rank <= 3:
            model_name = f"**{model_name}**"

        row = (
            f"| {rank} "
            f"| {model_name} "
            f"| {ms.refusal_pct:.0f}% "
            f"| {ms.wrong_pct:.0f}% "
            f"| {ms.correct_pct:.0f}% "
            f"| {ms.total_responses} |"
        )
        if has_multi_prompt:
            row += f" {len(ms.prompt_results)} |"
        lines.append(row)

    lines.append("")

    # Per-prompt breakdown (if multiple prompts)
    if has_multi_prompt:
        lines.append("## Per-Prompt Breakdown\n")
        for pid in sorted(prompt_ids):
            lines.append(f"### Prompt: `{pid}`\n")
            lines.append("| # | Model | Honest% | Halluc% | N |")
            lines.append("|--:|-------|--------:|--------:|--:|")
            prompt_rows: list[tuple[str, float, float, int]] = []
            for ms in sorted_scores:
                for pr in ms.prompt_results:
                    if pr.prompt_id == pid and pr.total > 0:
                        prompt_rows.append((ms.display_label, pr.refusal_pct, pr.wrong_pct, pr.total))
            prompt_rows.sort(key=lambda r: (r[1], -r[2]), reverse=True)
            for i, (name, honest, halluc, n) in enumerate(prompt_rows, 1):
                lines.append(f"| {i} | {name} | {honest:.0f}% | {halluc:.0f}% | {n} |")
            lines.append("")

    # Column definitions
    lines.append("## Column Definitions\n")
    lines.append("- **Model** — format: `{name}+{provider}@{reasoning}-t{temp}` (provider shown only when pinned)")
    lines.append("- **Honest%** — the model refused to answer, correctly recognizing it doesn't know the date")
    lines.append("- **Halluc%** — the model confidently stated a specific wrong date as fact (hallucination)")
    lines.append("- **HasDate%** — the model stated the correct date via provider-injected context")
    lines.append("- **N** — total number of responses scored")
    lines.append("")

    if lifetime_cost > 0:
        lines.append(f"---\n\nTotal benchmark cost: **${lifetime_cost:.4f} USD**\n")

    return "\n".join(lines)


def export_markdown_report(
    model_scores: list[ModelScore],
    *,
    lifetime_cost: float = 0.0,
    output_path: Path | None = None,
) -> Path:
    """Generate and save a Markdown leaderboard report. Returns the path."""
    md = generate_markdown_report(model_scores, lifetime_cost=lifetime_cost)
    if output_path is None:
        output_path = RESULTS_DIR / "LEADERBOARD.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(md, encoding="utf-8")
    return output_path


# ---------------------------------------------------------------------------
# JSON export
# ---------------------------------------------------------------------------

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
