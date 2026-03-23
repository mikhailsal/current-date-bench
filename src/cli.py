"""CLI for the Current Date Benchmark.

Tests whether LLMs know the current date when asked with no system prompt.
"""

from __future__ import annotations

import sys
from datetime import date

import click
from rich.console import Console

from src.config import (
    DEFAULT_TEST_MODELS,
    JUDGE_MODEL,
    NUM_REPETITIONS,
    ensure_dirs,
    get_reasoning_effort,
    load_api_key,
    model_id_to_slug,
)
from src.cost_tracker import SessionCost, TaskCost, load_lifetime_cost, save_session_to_cost_log
from src.openrouter_client import OpenRouterClient

console = Console()


def _parse_models(models_str: str | None) -> list[str]:
    if not models_str:
        return list(DEFAULT_TEST_MODELS)
    return [m.strip() for m in models_str.split(",") if m.strip()]


def _validate_models(client: OpenRouterClient, models: list[str]) -> bool:
    console.print("[dim]Fetching model catalog from OpenRouter...[/dim]")
    client.fetch_pricing()
    all_valid = True
    for model_id in models:
        if not client.validate_model(model_id):
            console.print(f"  [red]Model not found: {model_id}[/red]")
            all_valid = False
        else:
            pricing = client.get_model_pricing(model_id)
            in_price = pricing.prompt_price * 1_000_000
            out_price = pricing.completion_price * 1_000_000
            console.print(
                f"  [green]OK[/green] {model_id} "
                f"(${in_price:.2f}/${out_price:.2f} per M tokens)"
            )
    return all_valid


@click.group()
def cli() -> None:
    """Current Date Benchmark: do LLMs know today's date?"""
    pass


@cli.command()
@click.option("--models", "-m", default=None, help="Comma-separated model IDs.")
@click.option("--judge", "-j", default=JUDGE_MODEL, show_default=True, help="Judge model.")
@click.option("--runs", "-r", default=1, type=int, show_default=True, help="Number of runs.")
@click.option("--reps", "-n", default=NUM_REPETITIONS, type=int, show_default=True, help="Repetitions per run.")
@click.option("--date-override", default=None, help="Override actual date (YYYY-MM-DD) for judging.")
def run(
    models: str | None,
    judge: str,
    runs: int,
    reps: int,
    date_override: str | None,
) -> None:
    """Run the current date benchmark."""
    from src.evaluator import evaluate_model
    from src.runner import run_current_date_experiment
    from src.scorer import score_model
    from src.leaderboard import display_leaderboard, display_detailed, export_results_json

    model_list = _parse_models(models)
    api_key = load_api_key()
    client = OpenRouterClient(api_key)

    all_to_validate = list(set(model_list + [judge]))
    if not _validate_models(client, all_to_validate):
        console.print("[red]Some models were not found. Aborting.[/red]")
        sys.exit(1)

    ensure_dirs()

    actual_date = date_override or date.today().isoformat()

    console.print(f"\n[bold]Current Date Benchmark[/bold]")
    console.print(f"  Models: {', '.join(model_list)}")
    console.print(f"  Runs: {runs}")
    console.print(f"  Repetitions per run: {reps}")
    console.print(f"  Judge: {judge}")
    console.print(f"  Actual date: {actual_date}")
    console.print()

    session = SessionCost()

    for model_id in model_list:
        gen_cost = TaskCost(label=f"gen:{model_id}")
        judge_cost = TaskCost(label=f"judge:{model_id}")

        reasoning = get_reasoning_effort(model_id)

        for run_num in range(1, runs + 1):
            console.print(
                f"\n[bold]{model_id}[/bold] — "
                f"[blue]generating (run {run_num}/{runs})...[/blue]"
            )
            gen_calls = run_current_date_experiment(
                client, model_id, gen_cost,
                run=run_num, num_repetitions=reps,
                reasoning_effort=reasoning,
            )
            console.print(
                f"  [bold]{model_id}[/bold] — generation complete: "
                f"{gen_calls} calls, ${gen_cost.cost_usd:.4f}"
            )

            console.print(
                f"  [bold]{model_id}[/bold] — "
                f"[cyan]judging (run {run_num}/{runs})...[/cyan]"
            )
            judge_calls = evaluate_model(
                client, model_id, judge_cost, judge,
                run=run_num, num_repetitions=reps,
                actual_date=actual_date,
            )
            console.print(
                f"  [bold]{model_id}[/bold] — judging complete: "
                f"{judge_calls} calls, ${judge_cost.cost_usd:.4f}"
            )

        session.tasks.append(gen_cost)
        session.tasks.append(judge_cost)

    console.print(f"\n[bold green]Scoring[/bold green]")
    model_scores = []
    for model_id in model_list:
        ms = score_model(model_id, num_repetitions=reps)
        model_scores.append(ms)

    lifetime = save_session_to_cost_log(session)

    console.print(f"\n{'=' * 60}")
    display_leaderboard(model_scores, session=session, lifetime_cost=lifetime)
    display_detailed(model_scores)

    path = export_results_json(model_scores, session=session, lifetime_cost=lifetime)
    console.print(f"\n[dim]Results saved to: {path}[/dim]\n")


@cli.command()
@click.option("--models", "-m", default=None, help="Comma-separated model IDs. Defaults to all cached.")
@click.option("--reps", "-n", default=NUM_REPETITIONS, type=int, show_default=True, help="Repetitions per run.")
@click.option("--detailed", "-d", is_flag=True, default=False, help="Show detailed breakdown.")
def leaderboard(models: str | None, reps: int, detailed: bool) -> None:
    """Display leaderboard from cached results."""
    from src.cache import list_all_cached_models
    from src.config import slug_to_model_id
    from src.scorer import score_model
    from src.leaderboard import display_leaderboard, display_detailed

    if models:
        model_list = _parse_models(models)
    else:
        cached_slugs = list_all_cached_models()
        if not cached_slugs:
            console.print("[dim]No cached results found. Run the benchmark first.[/dim]")
            return
        model_list = [slug_to_model_id(s) for s in cached_slugs]

    lifetime = load_lifetime_cost()

    model_scores = []
    for model_id in model_list:
        ms = score_model(model_id, num_repetitions=reps)
        if ms.total_responses > 0:
            model_scores.append(ms)

    if not model_scores:
        console.print("[dim]No results found.[/dim]")
        return

    display_leaderboard(model_scores, lifetime_cost=lifetime)
    if detailed:
        display_detailed(model_scores)


if __name__ == "__main__":
    cli()
