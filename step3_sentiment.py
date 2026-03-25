"""
Step 3: Classify comment sentiment using OpenRouter + Gemini 3 Flash.

Reads data/comments.json, sends batches of comments to the LLM for
positive/negative/neutral classification, and writes data/sentiment.json.
"""

import argparse
import json
import time
import sys

import requests
from tqdm.auto import tqdm

from config import (
    COMMENTS_PATH,
    COMMENT_BODY_MAX_CHARS,
    DATA_DIR,
    OPENROUTER_API_KEY,
    SENTIMENT_BATCH_SIZE,
    SENTIMENT_CHECKPOINT_PATH,
    SENTIMENT_MODEL,
    SENTIMENT_PATH,
)

SYSTEM_PROMPT = """\
You are a sentiment classifier. For each comment from a New York Times article \
about AI, classify the commenter's attitude toward AI / artificial intelligence \
and how they frame AI.

Respond with a JSON object:
{"results": [{"id": <commentID>, "sentiment": "positive"|"negative"|"neutral"|"irrelevant", "framing": "tool"|"entity"|"neither", "confidence": "high"|"medium"|"low"}]}

Sentiment guide:
- "positive": Enthusiasm, optimism, support, or excitement about AI, its capabilities, or potential benefits.
- "negative": Fear, concern, criticism, opposition, or pessimism about AI, its risks, or societal impact.
- "neutral": Discusses AI factually without a clear positive or negative stance, or asks genuine questions about AI.
- "irrelevant": The comment is not about AI at all — it may be about the article's writing quality, off-topic political discussion, personal anecdotes unrelated to AI, etc.

Framing guide:
- "tool": The commenter treats AI as a tool or technology that humans use — e.g. "AI can help us," "we should regulate this technology," "it's just software."
- "entity": The commenter treats AI as an autonomous agent or being — e.g. "AI wants," "AI will take over," "AI thinks," "AI is coming for our jobs," as if it has its own will or agency.
- "neither": The framing doesn't clearly fit either category, or the comment is irrelevant to AI.

Classify the commenter's attitude toward AI itself, not their opinion of the article.\
"""


def load_checkpoint() -> set:
    if SENTIMENT_CHECKPOINT_PATH.exists():
        data = json.loads(SENTIMENT_CHECKPOINT_PATH.read_text())
        return set(data.get("completed_comment_ids", []))
    return set()


def save_checkpoint(completed: set):
    SENTIMENT_CHECKPOINT_PATH.write_text(json.dumps({
        "completed_comment_ids": list(completed),
        "count": len(completed),
    }))


def classify_batch(comments: list[dict], headline: str) -> list[dict]:
    """Send a batch of comments to Gemini 3 Flash via OpenRouter."""
    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY not set. Export it as an environment variable."
        )

    # Build user prompt
    lines = [f'Comments from NYT article: "{headline}"\n']
    for c in comments:
        body = (c["commentBody"] or "")[:COMMENT_BODY_MAX_CHARS]
        lines.append(f'Comment ID {c["commentID"]}: "{body}"')

    user_prompt = "\n".join(lines) + "\n\nRespond with JSON only."

    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": SENTIMENT_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        },
        timeout=60,
    )
    response.raise_for_status()

    content = response.json()["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    return parsed.get("results", [])


def chunk(lst, n):
    """Split list into chunks of size n."""
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def print_sample_results(articles: list, sentiment_map: dict, limit: int):
    """Print a readable summary of classified comments for manual review."""
    printed = 0
    for article in articles:
        article_printed = False
        for comment in article["comments"]:
            cid = comment["commentID"]
            if cid in sentiment_map:
                if not article_printed:
                    print(f"\n{'='*80}")
                    print(f"ARTICLE: {article['headline']}")
                    print(f"{'='*80}")
                    article_printed = True
                s = sentiment_map[cid]
                body = comment["commentBody"][:200]
                print(f"\n  [{s['sentiment'].upper():8s}] [framing: {s['framing']}] (confidence: {s['confidence']})")
                print(f"  {body}{'...' if len(comment['commentBody']) > 200 else ''}")
                printed += 1
                if printed >= limit:
                    return


def main():
    parser = argparse.ArgumentParser(description="Classify comment sentiment via OpenRouter")
    parser.add_argument("--limit", type=int, default=0,
                        help="Only classify this many comments (0 = all). Good for testing.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be sent without calling the API")
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    articles = json.loads(COMMENTS_PATH.read_text())
    completed = load_checkpoint()

    # Build flat list of (comment, headline) pairs needing classification
    work = []
    for article in articles:
        for comment in article["comments"]:
            if comment["commentID"] not in completed:
                work.append((comment, article["headline"]))

    total_comments = sum(len(a["comments"]) for a in articles)
    print(f"Total comments: {total_comments}")
    print(f"Already classified: {len(completed)}")
    print(f"Remaining: {len(work)}")

    if args.limit > 0:
        work = work[:args.limit]
        print(f"Limiting to: {len(work)} (--limit {args.limit})")

    print()

    if not work:
        print("All comments already classified!")
        if not SENTIMENT_PATH.exists():
            SENTIMENT_PATH.write_text(json.dumps(articles, indent=2, ensure_ascii=False))
        return

    if args.dry_run:
        batches = list(chunk(work, SENTIMENT_BATCH_SIZE))
        print(f"Would send {len(batches)} batches ({len(work)} comments) to {SENTIMENT_MODEL}")
        print(f"\nSample batch (first {min(SENTIMENT_BATCH_SIZE, len(work))} comments):")
        for c, headline in work[:SENTIMENT_BATCH_SIZE]:
            body = (c["commentBody"] or "")[:120]
            print(f"  [{c['commentID']}] ({headline[:50]}...) {body}...")
        return

    # Build a lookup: commentID -> sentiment result
    sentiment_map = {}

    batches = list(chunk(work, SENTIMENT_BATCH_SIZE))
    backoff_delays = [5, 10, 30, 60]

    for batch in tqdm(batches, desc="Classifying sentiment"):
        comments_in_batch = [c for c, _ in batch]
        headline = batch[0][1]  # use first comment's article headline

        for attempt in range(len(backoff_delays) + 1):
            try:
                results = classify_batch(comments_in_batch, headline)
                break
            except KeyboardInterrupt:
                print("\n\nInterrupted! Progress has been saved.")
                save_checkpoint(completed)
                sys.exit(0)
            except Exception as e:
                if attempt < len(backoff_delays):
                    delay = backoff_delays[attempt]
                    print(f"\n  Error: {e}")
                    print(f"  Retrying in {delay}s...")
                    time.sleep(delay)
                else:
                    print(f"\n  Failed after all retries — skipping batch")
                    results = []

        # Map results back by comment ID
        for r in results:
            cid = r.get("id")
            if cid is not None:
                sentiment_map[cid] = {
                    "sentiment": r.get("sentiment", "neutral"),
                    "framing": r.get("framing", "neither"),
                    "confidence": r.get("confidence", "low"),
                }
                completed.add(cid)

        save_checkpoint(completed)
        time.sleep(0.5)  # gentle rate limit

    # Print readable sample for review
    print_sample_results(articles, sentiment_map, limit=min(len(work), 50))

    # Merge sentiment into article structure
    for article in articles:
        for comment in article["comments"]:
            cid = comment["commentID"]
            if cid in sentiment_map:
                comment["sentiment"] = sentiment_map[cid]["sentiment"]
                comment["framing"] = sentiment_map[cid]["framing"]
                comment["confidence"] = sentiment_map[cid]["confidence"]

    SENTIMENT_PATH.write_text(json.dumps(articles, indent=2, ensure_ascii=False))

    classified = sum(
        1 for a in articles for c in a["comments"] if "sentiment" in c
    )
    print(f"\nDone! {classified}/{total_comments} comments classified.")
    print(f"Saved to {SENTIMENT_PATH}")


if __name__ == "__main__":
    main()
