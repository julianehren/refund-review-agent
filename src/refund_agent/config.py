"""Central configuration: file paths, model choice and prices.

Everything that you might want to change lives here, so the rest of the code
does not contain "magic values".
"""

import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # reads ANTHROPIC_API_KEY (and optional CLAUDE_MODEL) from .env

# --- Paths -----------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = Path(os.getenv("REFUND_DB_PATH", DATA_DIR / "shop.db"))
POLICY_PATH = DATA_DIR / "store_policy.md"
CHROMA_DIR = PROJECT_ROOT / ".chroma"
LABELS_PATH = PROJECT_ROOT / "evals" / "labels.json"

# --- Simulation date ---------------------------------------------------------
# The synthetic data is built around a fixed "today", so results are
# reproducible no matter when you run the project.
AS_OF_DATE = date(2026, 10, 15)

# --- LLM settings ------------------------------------------------------------
DEFAULT_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-5-5")
MAX_AGENT_STEPS = 10  # safety limit: the agent may call tools at most this often

# USD per 1 million tokens (input, output) – standard rates, prompts < 100k tokens.
# Source: https://platform.claude.com/docs/en/about-claude/pricing (Oct 2026)
MODEL_PRICES_USD = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}

# --- RAG settings ------------------------------------------------------------
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
POLICY_COLLECTION = "store-policy"
RAG_TOP_K = 3
