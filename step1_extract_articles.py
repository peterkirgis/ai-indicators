"""
Step 1: Extract AI-related article URLs from the NYT Archive API.

Fetches monthly archive data (Nov 2022 – Dec 2025), filters for headlines
mentioning AI, and writes article metadata to data/articles.json.
"""

import json
import time

import pandas as pd
import requests
from tqdm.auto import tqdm

from config import (
    ARCHIVE_CACHE_DIR,
    ARCHIVE_SLEEP_S,
    ARTICLES_PATH,
    DATA_DIR,
    END_MONTH,
    NYT_API_KEY,
    START_MONTH,
    mentions_ai,
)


def month_range(start: str, end: str):
    """Yield (year, month) tuples for each month in the range."""
    for p in pd.period_range(pd.Period(start, freq="M"), pd.Period(end, freq="M"), freq="M"):
        yield p.year, p.month


def fetch_month(year: int, month: int) -> dict:
    """Fetch one month of archive data, using local cache when available."""
    cache_path = ARCHIVE_CACHE_DIR / f"{year:04d}-{month:02d}.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text())

    url = f"https://api.nytimes.com/svc/archive/v1/{year}/{month}.json"
    r = requests.get(url, params={"api-key": NYT_API_KEY}, timeout=60)

    if r.status_code == 429:
        print(f"  Rate limited, sleeping 30s...")
        time.sleep(30)
        r = requests.get(url, params={"api-key": NYT_API_KEY}, timeout=60)

    r.raise_for_status()
    data = r.json()
    cache_path.write_text(json.dumps(data))
    time.sleep(ARCHIVE_SLEEP_S)
    return data


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    articles = []
    months = list(month_range(START_MONTH, END_MONTH))

    for y, m in tqdm(months, desc="Fetching archives"):
        data = fetch_month(y, m)
        docs = data.get("response", {}).get("docs", [])

        for d in docs:
            headline = (d.get("headline") or {}).get("main") or ""
            pub_date = d.get("pub_date", "")
            web_url = d.get("web_url", "")

            if not headline or not pub_date:
                continue
            if not mentions_ai(headline):
                continue

            articles.append({
                "article_id": d.get("_id", ""),
                "web_url": web_url,
                "headline": headline,
                "pub_date": pub_date,
                "month": pub_date[:7],
            })

    # Deduplicate by web_url (same article can appear in overlapping queries)
    seen = set()
    unique = []
    for a in articles:
        if a["web_url"] not in seen:
            seen.add(a["web_url"])
            unique.append(a)
    articles = unique

    # Sort by publication date
    articles.sort(key=lambda a: a["pub_date"])

    ARTICLES_PATH.write_text(json.dumps(articles, indent=2, ensure_ascii=False))
    print(f"\nExtracted {len(articles)} AI-related articles → {ARTICLES_PATH}")


if __name__ == "__main__":
    main()
