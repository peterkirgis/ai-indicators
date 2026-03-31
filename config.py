"""Shared configuration for the NYT AI sentiment pipeline."""

import os
import re
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not installed; rely on shell-exported env vars

# ── Paths ──────────────────────────────────────────────────────────────
DATA_DIR = Path(__file__).parent / "data"
ARCHIVE_CACHE_DIR = DATA_DIR / "archive_cache"
ARTICLES_PATH = DATA_DIR / "articles.json"
COMMENTS_PATH = DATA_DIR / "comments.json"
COMMENTS_CHECKPOINT_PATH = DATA_DIR / "comments_checkpoint.json"
SENTIMENT_PATH = DATA_DIR / "sentiment.json"
SENTIMENT_CHECKPOINT_PATH = DATA_DIR / "sentiment_checkpoint.json"

# ── API Keys ───────────────────────────────────────────────────────────
NYT_API_KEY = os.environ.get("NYT_API_KEY", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

# ── NYT Archive API ───────────────────────────────────────────────────
START_MONTH = "2022-11"
END_MONTH = "2026-03"
ARCHIVE_SLEEP_S = 6.0  # seconds between Archive API requests

# ── Comment scraping ──────────────────────────────────────────────────
COMMENT_DELAY_S = 1.0  # seconds between articles
COMMENT_SORT = "recommended"

# ── Sentiment classification ──────────────────────────────────────────
SENTIMENT_BATCH_SIZE = 50
SENTIMENT_CONCURRENCY = 10   # parallel API requests
SENTIMENT_MODEL = "google/gemini-3-flash-preview"
COMMENT_BODY_MAX_CHARS = 500  # truncate for sentiment prompt

# ── AI headline detection (from notebook) ─────────────────────────────
STRICT_TERMS = [
    r"(?<!\w)AI(?!\w)",
    r"(?<!\w)A\.I\.?(?!\w)",
    r"artificial intelligence",
]
STRICT_PATTERN = re.compile("|".join(f"(?:{t})" for t in STRICT_TERMS), re.IGNORECASE)


def mentions_ai(headline: str) -> bool:
    """Return True if headline mentions AI-like terms."""
    return bool(STRICT_PATTERN.search(headline or ""))
