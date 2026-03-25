"""
Fetch all comments from a New York Times article.

NYT loads comments via an internal API endpoint at:
  https://www.nytimes.com/svc/community/V3/requestHandler

This doesn't require an API key — it's the same endpoint
the NYT frontend uses to render comments.

Usage:
    python fetch_nyt_comments.py [--url URL] [--output OUTPUT] [--sort newest|oldest|recommended]
"""

import requests
import json
import time
import argparse
import csv
import re
from datetime import datetime

DEFAULT_URL = "https://www.nytimes.com/interactive/2026/03/09/business/ai-writing-quiz.html"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://www.nytimes.com/",
}

COMMENTS_ENDPOINT = "https://www.nytimes.com/svc/community/V3/requestHandler"
BATCH_SIZE = 25  # NYT returns 25 comments per request


def fetch_comments_batch(article_url: str, offset: int = 0, sort: str = "newest") -> dict:
    """Fetch a single batch of comments."""
    params = {
        "cmd": "GetCommentsAll",
        "url": article_url,
        "offset": offset,
        "sort": sort,
    }
    resp = requests.get(COMMENTS_ENDPOINT, params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_all_comments(article_url: str, sort: str = "newest") -> list[dict]:
    """
    Paginate through all comments on an article.
    Returns a list of comment dicts.
    """
    all_comments = []
    offset = 0

    # First request to get total count
    print(f"Fetching comments for:\n  {article_url}\n")
    data = fetch_comments_batch(article_url, offset=0, sort=sort)

    results = data.get("results", {})
    total_comments = results.get("totalCommentsFound", 0)
    total_parent = results.get("totalParentCommentsFound", 0)
    print(f"Total comments (including replies): {total_comments}")
    print(f"Total top-level comments: {total_parent}\n")

    if total_comments == 0:
        print("No comments found. The article may not have comments enabled,")
        print("or the comments section may not be open yet.")
        return []

    # Collect first batch
    comments = results.get("comments", [])
    all_comments.extend(comments)
    print(f"  Fetched {len(all_comments)}/{total_parent} top-level comments...")

    # Paginate through remaining
    while len(all_comments) < total_parent:
        offset += BATCH_SIZE
        time.sleep(0.5)  # Be polite

        try:
            data = fetch_comments_batch(article_url, offset=offset, sort=sort)
            comments = data.get("results", {}).get("comments", [])
            if not comments:
                break
            all_comments.extend(comments)
            print(f"  Fetched {len(all_comments)}/{total_parent} top-level comments...")
        except Exception as e:
            print(f"  Error at offset {offset}: {e}")
            break

    # Flatten replies into the list (they're nested under each parent)
    flat = []
    for comment in all_comments:
        flat.append(comment)
        replies = comment.get("replies", [])
        if replies:
            flat.extend(replies)

    print(f"\nTotal comments collected: {len(flat)} "
          f"({len(all_comments)} top-level + {len(flat) - len(all_comments)} replies)")
    return flat


def clean_html(text: str) -> str:
    """Strip HTML tags from comment body."""
    return re.sub(r"<[^>]+>", "", text or "")


def save_json(comments: list[dict], path: str):
    """Save raw comment data as JSON."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(comments, f, indent=2, ensure_ascii=False)
    print(f"Saved JSON to {path}")


def save_csv(comments: list[dict], path: str):
    """Save comments as a flat CSV."""
    fields = [
        "commentID",
        "parentID",
        "userDisplayName",
        "userLocation",
        "commentBody",
        "createDate",
        "recommendations",
        "replyCount",
        "editorsSelection",
        "depth",
    ]

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for c in comments:
            row = {k: c.get(k, "") for k in fields}
            row["commentBody"] = clean_html(row["commentBody"])
            # Convert timestamp to readable date
            ts = c.get("createDate")
            if ts:
                try:
                    row["createDate"] = datetime.fromtimestamp(int(ts)).isoformat()
                except (ValueError, TypeError):
                    pass
            writer.writerow(row)

    csv_path = path.replace(".json", ".csv") if path.endswith(".json") else path
    print(f"Saved CSV to {csv_path}")


def main():
    parser = argparse.ArgumentParser(description="Download NYT article comments")
    parser.add_argument("--url", default=DEFAULT_URL, help="NYT article URL")
    parser.add_argument("--output", default="nyt_comments", help="Output filename (without extension)")
    parser.add_argument("--sort", default="newest", choices=["newest", "oldest", "recommended"])
    parser.add_argument("--format", default="both", choices=["json", "csv", "both"])
    args = parser.parse_args()

    comments = fetch_all_comments(args.url, sort=args.sort)

    if not comments:
        return

    if args.format in ("json", "both"):
        save_json(comments, f"{args.output}.json")
    if args.format in ("csv", "both"):
        save_csv(comments, f"{args.output}.csv")


if __name__ == "__main__":
    main()