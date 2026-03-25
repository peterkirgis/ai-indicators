"""
Step 2: Scrape comments for all AI-related articles.

Reads data/articles.json, fetches comments for each article using the
NYT community API, and writes data/comments.json with checkpointing.
"""

import json
import time
import sys

from tqdm.auto import tqdm

from config import (
    ARTICLES_PATH,
    COMMENTS_CHECKPOINT_PATH,
    COMMENTS_PATH,
    COMMENT_DELAY_S,
    COMMENT_SORT,
    DATA_DIR,
)
from nyt_comments import clean_html, fetch_all_comments


def load_checkpoint() -> set:
    """Load set of already-processed article URLs."""
    if COMMENTS_CHECKPOINT_PATH.exists():
        data = json.loads(COMMENTS_CHECKPOINT_PATH.read_text())
        return set(data.get("completed_urls", []))
    return set()


def save_checkpoint(completed: set):
    COMMENTS_CHECKPOINT_PATH.write_text(json.dumps({
        "completed_urls": list(completed),
        "count": len(completed),
    }))


def load_partial_results() -> list:
    """Load existing comments.json if resuming."""
    if COMMENTS_PATH.exists():
        return json.loads(COMMENTS_PATH.read_text())
    return []


def save_results(results: list):
    COMMENTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False))


def slim_comment(c: dict) -> dict:
    """Keep only the fields we need from a raw comment."""
    return {
        "commentID": c.get("commentID"),
        "commentBody": clean_html(c.get("commentBody", "")),
        "userDisplayName": c.get("userDisplayName", ""),
        "userLocation": c.get("userLocation", ""),
        "createDate": c.get("createDate", ""),
        "recommendations": c.get("recommendations", 0),
        "parentID": c.get("parentID"),
        "depth": c.get("depth", 1),
    }


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    articles = json.loads(ARTICLES_PATH.read_text())
    completed = load_checkpoint()
    results = load_partial_results()

    # Build index of already-stored articles for fast lookup
    stored_urls = {r["web_url"] for r in results}

    remaining = [a for a in articles if a["web_url"] not in completed]
    print(f"Total articles: {len(articles)}")
    print(f"Already completed: {len(completed)}")
    print(f"Remaining: {len(remaining)}\n")

    if not remaining:
        print("All articles already processed!")
        return

    backoff_delays = [5, 10, 30, 60]

    for article in tqdm(remaining, desc="Scraping comments"):
        url = article["web_url"]

        # Fetch comments with retry/backoff
        comments = []
        for attempt in range(len(backoff_delays) + 1):
            try:
                comments = fetch_all_comments(url, sort=COMMENT_SORT)
                break
            except KeyboardInterrupt:
                print("\n\nInterrupted! Progress has been saved.")
                save_results(results)
                save_checkpoint(completed)
                sys.exit(0)
            except Exception as e:
                if attempt < len(backoff_delays):
                    delay = backoff_delays[attempt]
                    print(f"  Error fetching {url}: {e}")
                    print(f"  Retrying in {delay}s (attempt {attempt + 2}/{len(backoff_delays) + 1})...")
                    time.sleep(delay)
                else:
                    print(f"  Failed after all retries: {url} — skipping")
                    comments = []

        slim = [slim_comment(c) for c in comments]

        record = {
            "article_id": article["article_id"],
            "web_url": url,
            "headline": article["headline"],
            "pub_date": article["pub_date"],
            "month": article["month"],
            "comment_count": len(slim),
            "comments": slim,
        }

        if url not in stored_urls:
            results.append(record)
            stored_urls.add(url)

        completed.add(url)

        # Save after every article
        save_results(results)
        save_checkpoint(completed)

        time.sleep(COMMENT_DELAY_S)

    total_comments = sum(r["comment_count"] for r in results)
    with_comments = sum(1 for r in results if r["comment_count"] > 0)
    print(f"\nDone! {len(results)} articles processed.")
    print(f"  {with_comments} articles had comments")
    print(f"  {total_comments} total comments collected")
    print(f"  Saved to {COMMENTS_PATH}")


if __name__ == "__main__":
    main()
