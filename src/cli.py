"""CLI for the Current Date Benchmark.

Tests whether LLMs know the current date across different prompt
configurations, model settings (temperature, reasoning, provider).
Supports parallel execution for faster benchmarking.
"""

from __future__ import annotations

import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date

import click
from rich.console import Console

from src.config import (
    JUDGE_MODEL,
    MODEL_CONFIGS,
    NUM_REPETITIONS,
    ModelConfig,
    PromptConfig,
    ensure_dirs,
    get_active_prompt_configs,
    get_config_by_slug,
    get_model_config,
    list_registered_labels_for_model,
    load_api_key,
)
from src.cost_tracker import SessionCost, TaskCost, load_lifetime_cost, save_session_to_cost_log
from src.openrouter_client import OpenRouterClient

console = Console()


def _expand_model_configs(
    model_ids: list[str] | None,
    *,
    active_only: bool = True,
) -> list[ModelConfig]:
    """Resolve CLI model specifiers into a list of ModelConfig objects.

    If model_ids is None, returns all active configs from the YAML registry.
    """
    if model_ids is None:
        configs = [
            cfg for cfg in MODEL_CONFIGS.values()
            if (cfg.active if active_only else True)
        ]
        return configs if configs else []

    entries: list[ModelConfig] = []
    seen: set[str] = set()

    for mid in model_ids:
        if mid in MODEL_CONFIGS:
            cfg = MODEL_CONFIGS[mid]
            if cfg.label not in seen:
                entries.append(cfg)
                seen.add(cfg.label)
            continue

        registered = list_registered_labels_for_model(mid)
        if registered:
            for label in registered:
                if label not in seen:
                    entries.append(MODEL_CONFIGS[label])
                    seen.add(label)
        else:
            if mid not in seen:
                cfg = get_model_config(mid)
                entries.append(cfg)
                seen.add(mid)

    return entries


def _parse_model_ids(models_str: str | None) -> list[str] | None:
    if not models_str:
        return None
    return [m.strip() for m in models_str.split(",") if m.strip()]


def _parse_prompt_ids(prompts_str: str | None) -> list[PromptConfig] | None:
    if not prompts_str:
        return None
    from src.config import get_prompt_config
    configs: list[PromptConfig] = []
    for pid in prompts_str.split(","):
        pid = pid.strip()
        if not pid:
            continue
        pc = get_prompt_config(pid)
        if pc is None:
            console.print(f"[red]Unknown prompt_id: {pid}[/red]")
            sys.exit(1)
        configs.append(pc)
    return configs


def _validate_models(
    client: OpenRouterClient,
    configs: list[ModelConfig],
    extra_models: list[str] | None = None,
) -> bool:
    console.print("[dim]Fetching model catalog from OpenRouter...[/dim]")
    client.fetch_pricing()
    all_valid = True
    seen: set[str] = set()

    all_model_ids = [cfg.model_id for cfg in configs]
    if extra_models:
        all_model_ids.extend(extra_models)

    for model_id in all_model_ids:
        if model_id in seen:
            continue
        seen.add(model_id)

        if not client.validate_model(model_id):
            console.print(f"  [red]Model not found: {model_id}[/red]")
            all_valid = False
        else:
            pricing = client.get_model_pricing(model_id)
            in_price = pricing.prompt_price * 1_000_000
            out_price = pricing.completion_price * 1_000_000
            reasoning_tag = ""
            if client.supports_reasoning(model_id):
                reasoning_tag = " [yellow]reasoning:supported[/yellow]"
            console.print(
                f"  [green]OK[/green] {model_id} "
                f"(${in_price:.2f}/${out_price:.2f} per M tokens){reasoning_tag}"
            )
    return all_valid


# ---------------------------------------------------------------------------
# Single-model pipeline (used by both sequential and parallel modes)
# ---------------------------------------------------------------------------

@dataclass
class ModelResult:
    label: str = ""
    gen_cost: TaskCost = field(default_factory=TaskCost)
    judge_cost: TaskCost = field(default_factory=TaskCost)
    gen_calls: int = 0
    judge_calls: int = 0
    error: str | None = None


def _run_single_model(
    client: OpenRouterClient,
    cfg: ModelConfig,
    prompt_configs: list[PromptConfig],
    judge: str,
    reps: int,
    actual_date: str,
) -> ModelResult:
    """Run the full pipeline (generate + judge) for one model across all prompts.

    Designed for thread-pool execution. Catches exceptions so one failure
    doesn't crash the whole batch.
    """
    from src.evaluator import evaluate_model_prompt
    from src.runner import run_prompt_experiment

    result = ModelResult(label=cfg.label)
    result.gen_cost = TaskCost(label=f"gen:{cfg.label}")
    result.judge_cost = TaskCost(label=f"judge:{cfg.label}")

    try:
        for pc in prompt_configs:
            console.print(
                f"\n[bold]{cfg.label}[/bold] -- "
                f"[blue]generating ({pc.prompt_id})...[/blue]"
            )
            gen_calls = run_prompt_experiment(
                client, cfg, pc, result.gen_cost,
                num_repetitions=reps,
            )
            result.gen_calls += gen_calls
            console.print(
                f"  [bold]{cfg.label}[/bold] -- generation [{pc.prompt_id}] complete: "
                f"{gen_calls} calls, ${result.gen_cost.cost_usd:.4f}"
            )

            console.print(
                f"  [bold]{cfg.label}[/bold] -- "
                f"[cyan]judging ({pc.prompt_id})...[/cyan]"
            )
            judge_calls = evaluate_model_prompt(
                client, cfg, pc, result.judge_cost, judge,
                num_repetitions=reps,
                actual_date=actual_date,
            )
            result.judge_calls += judge_calls
            console.print(
                f"  [bold]{cfg.label}[/bold] -- judging [{pc.prompt_id}] complete: "
                f"{judge_calls} calls, ${result.judge_cost.cost_usd:.4f}"
            )
    except Exception as e:
        result.error = str(e)
        console.print(f"  [red]{cfg.label} -- ERROR: {e}[/red]")

    return result


@click.group()
def cli() -> None:
    """Current Date Benchmark: do LLMs know today's date?"""
    pass


@cli.command()
@click.option("--models", "-m", default=None, help="Comma-separated model IDs or config labels.")
@click.option("--prompts", "-p", default=None, help="Comma-separated prompt_ids from config. Defaults to all active.")
@click.option("--judge", "-j", default=JUDGE_MODEL, show_default=True, help="Judge model.")
@click.option("--reps", "-n", default=NUM_REPETITIONS, type=int, show_default=True, help="Repetitions per model+prompt.")
@click.option("--date-override", default=None, help="Override actual date (YYYY-MM-DD) for judging.")
@click.option(
    "--reasoning-effort", "-r", default=None, type=str,
    help="Override reasoning effort for all models: 'off', 'none', 'low', 'medium', 'high'.",
)
@click.option(
    "--temperature", "-t", default=None, type=float,
    help="Override temperature for all models (0.0-2.0).",
)
@click.option(
    "--parallel", "-P", default=1, type=int, show_default=True,
    help="Number of models to run in parallel. Use -P 8 to run 8 models concurrently.",
)
def run(
    models: str | None,
    prompts: str | None,
    judge: str,
    reps: int,
    date_override: str | None,
    reasoning_effort: str | None,
    temperature: float | None,
    parallel: int,
) -> None:
    """Run the current date benchmark."""
    from src.scorer import score_model
    from src.leaderboard import display_leaderboard, display_detailed, export_results_json

    model_ids = _parse_model_ids(models)
    model_configs = _expand_model_configs(model_ids)

    if not model_configs:
        console.print("[red]No model configs found. Check configs/models.yaml or pass --models.[/red]")
        sys.exit(1)

    if reasoning_effort is not None or temperature is not None:
        overridden: list[ModelConfig] = []
        for cfg in model_configs:
            overridden.append(ModelConfig(
                model_id=cfg.model_id,
                display_label=cfg.display_label,
                temperature=temperature if temperature is not None else cfg.temperature,
                reasoning_effort=reasoning_effort if reasoning_effort is not None else cfg.reasoning_effort,
                temperature_supported=cfg.temperature_supported,
                active=cfg.active,
                provider=cfg.provider,
            ))
        model_configs = overridden

    prompt_configs = _parse_prompt_ids(prompts)
    if prompt_configs is None:
        prompt_configs = get_active_prompt_configs()

    api_key = load_api_key()
    client = OpenRouterClient(api_key)

    if not _validate_models(client, model_configs, [judge]):
        console.print("[red]Some models were not found. Aborting.[/red]")
        sys.exit(1)

    ensure_dirs()

    actual_date = date_override or date.today().isoformat()
    n_workers = max(1, min(parallel, len(model_configs)))

    console.print(f"\n[bold]Current Date Benchmark v2[/bold]")
    console.print(f"  Model configs: {len(model_configs)}")
    for cfg in model_configs:
        console.print(
            f"    {cfg.label} "
            f"(reasoning={cfg.effective_reasoning}, t={cfg.effective_temperature}"
            + (f", provider={cfg.provider}" if cfg.provider else "")
            + ")"
        )
    console.print(f"  Prompt configs: {', '.join(pc.prompt_id for pc in prompt_configs)}")
    console.print(f"  Repetitions: {reps}")
    console.print(f"  Judge: {judge}")
    console.print(f"  Actual date: {actual_date}")
    if n_workers > 1:
        console.print(f"  [yellow]Parallel workers: {n_workers}[/yellow]")
    console.print()

    session = SessionCost()
    model_results: list[ModelResult] = []

    if n_workers == 1:
        for cfg in model_configs:
            mr = _run_single_model(client, cfg, prompt_configs, judge, reps, actual_date)
            model_results.append(mr)
    else:
        console.print(f"[bold blue]Running {len(model_configs)} models with {n_workers} parallel workers[/bold blue]\n")
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = {
                pool.submit(
                    _run_single_model, client, cfg, prompt_configs, judge, reps, actual_date,
                ): cfg.label
                for cfg in model_configs
            }
            for future in as_completed(futures):
                label = futures[future]
                try:
                    mr = future.result()
                except Exception as e:
                    mr = ModelResult(label=label, error=str(e))
                    console.print(f"  [red]{label} -- FATAL: {e}[/red]")
                model_results.append(mr)

    for mr in model_results:
        session.tasks.append(mr.gen_cost)
        session.tasks.append(mr.judge_cost)

    failed = [mr.label for mr in model_results if mr.error]

    console.print(f"\n[bold green]Scoring[/bold green]")
    prompt_id_list = [pc.prompt_id for pc in prompt_configs]

    # Re-resolve configs (parallel may reorder results)
    model_scores = []
    for cfg in model_configs:
        ms = score_model(cfg, prompt_ids=prompt_id_list, num_repetitions=reps)
        model_scores.append(ms)

    if failed:
        console.print(f"\n[yellow]Models that failed: {', '.join(failed)}[/yellow]")
        for mr in model_results:
            if mr.error:
                console.print(f"  [dim]{mr.label}: {mr.error}[/dim]")

    lifetime = save_session_to_cost_log(session)

    console.print(f"\n{'=' * 60}")
    display_leaderboard(model_scores, session=session, lifetime_cost=lifetime)
    display_detailed(model_scores)

    path = export_results_json(model_scores, session=session, lifetime_cost=lifetime)
    console.print(f"\n[dim]Results saved to: {path}[/dim]\n")


@cli.command()
@click.option("--models", "-m", default=None, help="Comma-separated model IDs. Defaults to all cached.")
@click.option("--reps", "-n", default=NUM_REPETITIONS, type=int, show_default=True, help="Repetitions per prompt.")
@click.option("--detailed", "-d", is_flag=True, default=False, help="Show detailed breakdown.")
def leaderboard(models: str | None, reps: int, detailed: bool) -> None:
    """Display leaderboard from cached results."""
    from src.cache import list_all_cached_configs
    from src.scorer import score_model
    from src.leaderboard import display_leaderboard, display_detailed

    if models:
        model_ids = _parse_model_ids(models)
        model_configs = _expand_model_configs(model_ids, active_only=False)
    else:
        cached_slugs = list_all_cached_configs()
        if not cached_slugs:
            console.print("[dim]No cached results found. Run the benchmark first.[/dim]")
            return
        model_configs = []
        for slug in cached_slugs:
            cfg = get_config_by_slug(slug)
            if cfg:
                model_configs.append(cfg)
            else:
                model_configs.append(ModelConfig(model_id=slug, display_label=slug))

    lifetime = load_lifetime_cost()

    model_scores = []
    for cfg in model_configs:
        ms = score_model(cfg, num_repetitions=reps)
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
