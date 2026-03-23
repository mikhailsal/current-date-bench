"""Configuration for the Current Date Benchmark."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "cache"
RESULTS_DIR = PROJECT_ROOT / "results"
COST_LOG_PATH = RESULTS_DIR / "cost_log.json"
ENV_PATH = PROJECT_ROOT / ".env"

RESPONSE_MAX_TOKENS = 256
RESPONSE_TEMPERATURE = 0.7
JUDGE_MAX_TOKENS = 128
JUDGE_TEMPERATURE = 0.0

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
API_CALL_TIMEOUT = 60

JUDGE_MODEL = "google/gemini-3-flash-preview"

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

DEFAULT_TEST_MODELS: list[str] = [
    "openai/gpt-5-nano",
    "openai/gpt-5.4-nano",
    "openai/gpt-5.4-mini",
    "openai/gpt-5.2",
    "openai/gpt-5.1-codex-mini",
    "openai/gpt-5.3-codex",
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

NUM_REPETITIONS = 5


def get_reasoning_effort(model_id: str) -> str:
    best_match = ""
    best_effort = REASONING_EFFORT_DEFAULT
    for prefix, effort in REASONING_EFFORT_BY_PREFIX.items():
        if model_id.startswith(prefix) and len(prefix) > len(best_match):
            best_match = prefix
            best_effort = effort
    return best_effort


class ModelPricing:
    def __init__(self, prompt_price: float = 0.0, completion_price: float = 0.0):
        self.prompt_price = prompt_price
        self.completion_price = completion_price


def model_id_to_slug(model_id: str) -> str:
    return model_id.replace("/", "--")


def slug_to_model_id(slug: str) -> str:
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
