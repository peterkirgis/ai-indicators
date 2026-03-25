# ai-indicators

Tracking public sentiment toward AI through New York Times article comments (Nov 2022 – present).

## Method

1. Pull all NYT articles with AI-related headlines via the Archive API (~1,400 articles)
2. Scrape reader comments for each article via the NYT community API (~120k comments)
3. Classify each comment's sentiment (positive/negative/neutral/irrelevant) and framing (tool/entity/neither) using Gemini 3 Flash via OpenRouter
4. Aggregate by month to track sentiment trends over time

## Pipeline

```
python step1_extract_articles.py   # extract article URLs → data/articles.json
python step2_scrape_comments.py    # scrape comments     → data/comments.json
python step3_sentiment.py          # classify sentiment   → data/sentiment.json
python build_viewer.py             # build viewer         → docs/
```

## Key files

| File | Purpose |
|------|---------|
| `config.py` | Shared config, API keys (via `.env`), AI headline regex |
| `nyt_comments.py` | NYT comment scraping module |
| `step3_sentiment.py` | LLM sentiment/framing classifier with checkpointing |
| `build_viewer.py` | Builds interactive HTML viewer to `docs/` |
| `analysis.ipynb` | Sentiment trend visualizations |

## Viewer

Browse articles and comments with sentiment labels at the GitHub Pages site, or locally:

```
cd docs && python -m http.server 8000
```

## Setup

Requires a `.env` file with:

```
NYT_API_KEY=...
OPENROUTER_API_KEY=...
```
