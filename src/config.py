"""Configuration for the Current Date Benchmark.

Supports per-model settings (temperature, reasoning, provider pinning) and
per-prompt configurations (system_prompt + user_prompt pairs) via YAML.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "cache"
RESULTS_DIR = PROJECT_ROOT / "results"
COST_LOG_PATH = RESULTS_DIR / "cost_log.json"
ENV_PATH = PROJECT_ROOT / ".env"
CONFIGS_PATH = PROJECT_ROOT / "configs" / "models.yaml"

# ---------------------------------------------------------------------------
# Token / generation limits
# ---------------------------------------------------------------------------
RESPONSE_MAX_TOKENS = 512
RESPONSE_TEMPERATURE = 0.7
JUDGE_MAX_TOKENS = 128
JUDGE_TEMPERATURE = 0.0

MAX_TOKENS_BY_REASONING: dict[str, int] = {
    "none": 512,
    "low": 4096,
    "medium": 8192,
    "high": 16384,
}

# ---------------------------------------------------------------------------
# OpenRouter
# ---------------------------------------------------------------------------
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
API_CALL_TIMEOUT = 60

# ---------------------------------------------------------------------------
# Judge model
# ---------------------------------------------------------------------------
JUDGE_MODEL = "google/gemini-3-flash-preview"

# ---------------------------------------------------------------------------
# Reasoning model support
# ---------------------------------------------------------------------------
REASONING_EFFORT_DEFAULT = "low"

REASONING_EFFORT_BY_PREFIX: dict[str, str] = {
    "google/gemini-3-pro":   "low",
    "google/gemini-3.1-pro": "low",
    "google/":      "none",
    "qwen/":        "none",
    "openai/":      "low",
    "anthropic/":   "none",
    "stepfun/":     "low",
    "nvidia/":      "none",
    "arcee-ai/":    "low",
    "z-ai/":        "none",
    "x-ai/":        "low",
    "bytedance-seed/": "low",
    "minimax/":     "low",
    "xiaomi/":      "low",
    "deepseek/":    "low",
    "kwaipilot/":   "none",
    "mistralai/":   "none",
    "openrouter/":  "low",
    "nex-agi/":     "none",
    "tngtech/":     "low",
    "amazon/":      "none",
    "inception/":   "low",
}


def get_reasoning_effort(model_id: str) -> str:
    """Return the default reasoning effort for a model based on its ID prefix."""
    best_match = ""
    best_effort = REASONING_EFFORT_DEFAULT
    for prefix, effort in REASONING_EFFORT_BY_PREFIX.items():
        if model_id.startswith(prefix) and len(prefix) > len(best_match):
            best_match = prefix
            best_effort = effort
    return best_effort


# ---------------------------------------------------------------------------
# Default repetitions (flat, no runs)
# ---------------------------------------------------------------------------
NUM_REPETITIONS = 10

# ---------------------------------------------------------------------------
# Default test models (used when no YAML config and no --models flag)
# ---------------------------------------------------------------------------
DEFAULT_TEST_MODELS: list[str] = [
    "openai/gpt-5.1-codex-mini",
    "anthropic/claude-sonnet-4.6",
    "anthropic/claude-opus-4.5",
    "anthropic/claude-opus-4.6",
    "google/gemini-2.5-flash-lite",
    "google/gemini-2.5-flash",
    "google/gemini-3-flash-preview",
    "google/gemini-3-pro-preview",
    "google/gemini-3.1-pro-preview",
    "meta-llama/llama-4-scout",
    "qwen/qwen3-8b",
    "qwen/qwen3-coder",
    "qwen/qwen3-coder-next",
    "qwen/qwen3.5-flash-02-23",
    "mistralai/mistral-small-3.2-24b-instruct",
    "mistralai/mistral-small-2603",
    "z-ai/glm-5",
    "z-ai/glm-5-turbo",
    "moonshotai/kimi-k2.5",
    "deepseek/deepseek-v3.2",
    "deepseek/deepseek-v3.2-exp",
    "nex-agi/deepseek-v3.1-nex-n1",
    "tngtech/deepseek-r1t2-chimera",
    "x-ai/grok-4.20-beta",
    "minimax/minimax-m2.7",
]


# ---------------------------------------------------------------------------
# Prompt configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PromptConfig:
    """A (system_prompt, user_prompt) pair for benchmarking.

    Attributes:
        prompt_id: Unique identifier used in cache paths and results.
        system_prompt: System message content (empty string = no system prompt).
        user_prompt: The user message sent to the model.
        active: Whether this prompt config is included in default runs.
    """
    prompt_id: str
    system_prompt: str = ""
    user_prompt: str = "current date"
    active: bool = True


DEFAULT_PROMPT_CONFIGS: list[PromptConfig] = [
    PromptConfig(prompt_id="current_date", system_prompt="", user_prompt="current date"),
]

PROMPT_CONFIGS: dict[str, PromptConfig] = {}


def get_prompt_config(prompt_id: str) -> PromptConfig | None:
    """Look up a prompt config by its ID."""
    return PROMPT_CONFIGS.get(prompt_id)


def get_active_prompt_configs() -> list[PromptConfig]:
    """Return all active prompt configs, or defaults if none registered."""
    active = [pc for pc in PROMPT_CONFIGS.values() if pc.active]
    return active if active else list(DEFAULT_PROMPT_CONFIGS)


# ---------------------------------------------------------------------------
# Model pricing
# ---------------------------------------------------------------------------

@dataclass
class ModelPricing:
    prompt_price: float = 0.0
    completion_price: float = 0.0


# ---------------------------------------------------------------------------
# Per-model configuration
# ---------------------------------------------------------------------------

def generate_display_label(model_id: str, reasoning: str, temperature: float) -> str:
    """Auto-generate a display label: ``{name}@{reasoning}-t{temp}``."""
    name = model_id.split("/", 1)[-1] if "/" in model_id else model_id
    return f"{name}@{reasoning}-t{temperature}"


@dataclass(frozen=True)
class ModelConfig:
    """Configuration for a specific benchmark entry.

    Multiple configs can share the same base ``model_id`` but differ in
    temperature, reasoning, or provider.

    Attributes:
        model_id: The API model identifier (e.g. ``openai/gpt-5-nano``).
        display_label: Human-readable label shown in the leaderboard.
        temperature: Response temperature. ``None`` means use global default.
        reasoning_effort: Reasoning effort. ``None`` means use prefix-based default.
        temperature_supported: False if provider ignores the temperature parameter.
        active: Whether included in default benchmark runs.
        provider: OpenRouter provider slug to pin requests to a specific provider.
    """
    model_id: str
    display_label: str = ""
    temperature: float | None = None
    reasoning_effort: str | None = None
    temperature_supported: bool = True
    active: bool = True
    provider: str | None = None
    max_tokens: int | None = None

    @property
    def label(self) -> str:
        return self.display_label or self.model_id

    @property
    def effective_temperature(self) -> float:
        return self.temperature if self.temperature is not None else RESPONSE_TEMPERATURE

    @property
    def effective_reasoning(self) -> str:
        return self.reasoning_effort if self.reasoning_effort is not None else get_reasoning_effort(self.model_id)

    @property
    def effective_max_tokens(self) -> int:
        if self.max_tokens is not None:
            return self.max_tokens
        return MAX_TOKENS_BY_REASONING.get(self.effective_reasoning, RESPONSE_MAX_TOKENS)

    @property
    def config_slug(self) -> str:
        """Cache directory component: ``{slug}@{reasoning}-t{temp}``
        or ``{slug}+{provider_tag}@{reasoning}-t{temp}`` when provider is pinned."""
        slug = model_id_to_slug(self.model_id)
        if self.provider:
            provider_tag = self.provider.replace("/", "-")
            return f"{slug}+{provider_tag}@{self.effective_reasoning}-t{self.effective_temperature}"
        return f"{slug}@{self.effective_reasoning}-t{self.effective_temperature}"


MODEL_CONFIGS: dict[str, ModelConfig] = {}


def register_config(cfg: ModelConfig) -> None:
    """Register a model configuration. Raises ValueError on duplicate labels."""
    label = cfg.label
    if label in MODEL_CONFIGS:
        raise ValueError(f"Duplicate model config label: {label!r}")
    MODEL_CONFIGS[label] = cfg


def get_model_config(label_or_model_id: str) -> ModelConfig:
    """Resolve a display label or raw model_id to a ModelConfig.

    Lookup order:
      1. Exact match in MODEL_CONFIGS by label.
      2. Search for entries where model_id matches (unique match only).
      3. Create a default ModelConfig on the fly.
    """
    if label_or_model_id in MODEL_CONFIGS:
        return MODEL_CONFIGS[label_or_model_id]

    matches = [c for c in MODEL_CONFIGS.values() if c.model_id == label_or_model_id]
    if len(matches) == 1:
        return matches[0]

    return ModelConfig(model_id=label_or_model_id)


def list_registered_labels_for_model(model_id: str) -> list[str]:
    """Return all registered config labels that share a given model_id."""
    return [c.label for c in MODEL_CONFIGS.values() if c.model_id == model_id]


def get_config_by_slug(config_slug: str) -> ModelConfig | None:
    """Look up a ModelConfig by its ``config_slug``."""
    for cfg in MODEL_CONFIGS.values():
        if cfg.config_slug == config_slug:
            return cfg
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def model_id_to_slug(model_id: str) -> str:
    """Convert 'openai/gpt-5-nano' -> 'openai--gpt-5-nano'."""
    return model_id.replace("/", "--")


def slug_to_model_id(slug: str) -> str:
    """Convert 'openai--gpt-5-nano' -> 'openai/gpt-5-nano'."""
    return slug.replace("--", "/", 1)


def ensure_dirs() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def load_api_key() -> str:
    load_dotenv(ENV_PATH)
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key or key == "your-key-here":
        print(
            "ERROR: OPENROUTER_API_KEY is not set.\n"
            f"  Create a .env file at {ENV_PATH} with:\n"
            "  OPENROUTER_API_KEY=sk-or-...\n"
            "  Or export it as an environment variable.",
            file=sys.stderr,
        )
        sys.exit(1)
    return key


# ---------------------------------------------------------------------------
# YAML configuration loader
# ---------------------------------------------------------------------------

def load_model_configs(path: Path | None = None) -> list[ModelConfig]:
    """Load model configurations from a YAML file and register them.

    Also loads prompt configurations from the same file.
    Returns the list of newly created ModelConfig objects.
    """
    import yaml

    config_path = path or CONFIGS_PATH
    if not config_path.exists():
        return []

    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not data:
        return []

    # Load prompt configs
    if "prompts" in data:
        for entry in data["prompts"]:
            pc = PromptConfig(
                prompt_id=entry["prompt_id"],
                system_prompt=entry.get("system_prompt", ""),
                user_prompt=entry.get("user_prompt", "current date"),
                active=entry.get("active", True),
            )
            PROMPT_CONFIGS[pc.prompt_id] = pc

    if "models" not in data:
        return []

    configs: list[ModelConfig] = []
    for entry in data["models"]:
        model_id = entry["model_id"]
        temperature = float(entry["temperature"])
        reasoning = entry["reasoning_effort"]
        temp_supported = entry.get("temperature_supported", True)
        active = entry.get("active", True)
        provider = entry.get("provider") or None

        max_tokens = entry.get("max_tokens")
        if max_tokens is not None:
            max_tokens = int(max_tokens)

        label = entry.get("display_label") or generate_display_label(
            model_id, reasoning, temperature,
        )

        cfg = ModelConfig(
            model_id=model_id,
            display_label=label,
            temperature=temperature,
            reasoning_effort=reasoning,
            temperature_supported=temp_supported,
            active=active,
            provider=provider,
            max_tokens=max_tokens,
        )
        if cfg.label not in MODEL_CONFIGS:
            register_config(cfg)
        configs.append(cfg)

    return configs


# ---------------------------------------------------------------------------
# Auto-load configs from YAML on import
# ---------------------------------------------------------------------------

_yaml_configs_loaded = False


def _auto_load_configs() -> None:
    global _yaml_configs_loaded
    if _yaml_configs_loaded:
        return
    _yaml_configs_loaded = True
    if CONFIGS_PATH.exists():
        load_model_configs(CONFIGS_PATH)


_auto_load_configs()
