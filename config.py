"""Shared configuration for K4 / Track 3A: Eval + Guardrail Stack."""

import os
from dotenv import load_dotenv

load_dotenv()

# --- API / provider ---
# MWAPI exposes an Anthropic-compatible /v1/messages endpoint.  Keep the
# legacy names as fallbacks so an existing local .env can be migrated without
# copying a secret into source control.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
LLM_API_FORMAT = os.getenv("LLM_API_FORMAT", "anthropic").strip().lower()
LLM_API_KEY = (
    os.getenv("LLM_API_KEY")
    or os.getenv("MWAPI_API_KEY")
    or os.getenv("ANTHROPIC_API_KEY")
    or OPENAI_API_KEY
).strip()
LLM_BASE_URL = (
    os.getenv("LLM_BASE_URL")
    or os.getenv("ANTHROPIC_BASE_URL")
    or os.getenv("OPENAI_BASE_URL")
    or "https://api.mwapi.dev"
).rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "").strip()
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "180"))

# The MWAPI high-speed tier is billed as a 5x rate on this account.  Prices
# below are BASE prices before that multiplier and must match the selected
# model in the MWAPI dashboard. Defaults match Claude Haiku 4.5; edit them if
# the account switches to a different model/rate.
LLM_PRICE_MULTIPLIER = float(os.getenv("LLM_PRICE_MULTIPLIER", "5"))
LLM_BASE_INPUT_USD_PER_MTOK = float(
    os.getenv("LLM_BASE_INPUT_USD_PER_MTOK", "1")
)
LLM_BASE_OUTPUT_USD_PER_MTOK = float(
    os.getenv("LLM_BASE_OUTPUT_USD_PER_MTOK", "5")
)
LLM_MAX_RUN_USD = float(os.getenv("LLM_MAX_RUN_USD", "3"))
LLM_MAX_DAILY_USD = float(os.getenv("LLM_MAX_DAILY_USD", "5"))
LLM_MAX_REQUESTS = int(os.getenv("LLM_MAX_REQUESTS", "600"))
LLM_MAX_OUTPUT_TOKENS = int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "512"))
ENABLE_LLM_ENRICHMENT = os.getenv("ENABLE_LLM_ENRICHMENT", "0") == "1"

HF_TOKEN = os.getenv("HF_TOKEN", "")  # Optional: for HuggingFace models

# --- Qdrant (same as Day 18) ---
QDRANT_HOST = "localhost"
QDRANT_PORT = 6333
COLLECTION_NAME = "lab24_production"
NAIVE_COLLECTION = "lab24_naive"

# --- Embedding (same as Day 18) ---
EMBEDDING_MODEL = "BAAI/bge-m3"
EMBEDDING_DIM = 1024

# --- Chunking (same as Day 18) ---
HIERARCHICAL_PARENT_SIZE = 2048
HIERARCHICAL_CHILD_SIZE = 256
SEMANTIC_THRESHOLD = 0.85

# --- Search (same as Day 18) ---
BM25_TOP_K = 20
DENSE_TOP_K = 20
HYBRID_TOP_K = 20
RERANK_TOP_K = 3

# --- Paths ---
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT_DIR, "data")
FIXTURES_DIR = os.path.join(ROOT_DIR, "fixtures")
ARTIFACTS_DIR = os.path.join(ROOT_DIR, "artifacts")
TEST_SET_PATH = os.path.join(FIXTURES_DIR, "test_set_50q.json")
ANSWERS_PATH = os.path.join(ARTIFACTS_DIR, "answers_50q.json")
HUMAN_LABELS_PATH = os.path.join(FIXTURES_DIR, "human_labels_10q.json")
ADVERSARIAL_SET_PATH = os.path.join(FIXTURES_DIR, "adversarial_set_20.json")
CLEAN_SET_PATH = os.path.join(FIXTURES_DIR, "clean_set_8.json")
OUTPUT_SET_PATH = os.path.join(FIXTURES_DIR, "output_set_4.json")
GUARDRAILS_CONFIG_DIR = os.path.join(ROOT_DIR, "guardrails")
PAIR_QUESTION_IDS = (1, 5, 12, 21, 41)

# --- Model roles ---
# A role can override LLM_MODEL, otherwise every paid call uses the exact
# MWAPI Claude model selected in .env.
_UNCONFIGURED_MODEL = "claude-model-from-mwapi"
_DEFAULT_ROLE_MODEL = LLM_MODEL or _UNCONFIGURED_MODEL
GENERATION_MODEL = (os.getenv("GENERATION_MODEL") or _DEFAULT_ROLE_MODEL).strip()
ENRICHMENT_MODEL = (os.getenv("ENRICHMENT_MODEL") or GENERATION_MODEL).strip()
EVALUATOR_MODEL = (os.getenv("EVALUATOR_MODEL") or _DEFAULT_ROLE_MODEL).strip()
EVALUATOR_EMBEDDING_MODEL = os.getenv("EVALUATOR_EMBEDDING_MODEL", EMBEDDING_MODEL)
JUDGE_MODEL = (os.getenv("JUDGE_MODEL") or _DEFAULT_ROLE_MODEL).strip()
GUARD_MODEL = (os.getenv("GUARD_MODEL") or _DEFAULT_ROLE_MODEL).strip()

# --- Guardrail latency budget ---
LATENCY_BUDGET_P95_MS = 500  # Full guard target; Task 12 currently measures input guards only.
PRESIDIO_LANGUAGE = "en"    # Presidio base language; custom VN recognizers added via PatternRecognizer
