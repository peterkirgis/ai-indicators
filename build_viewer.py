"""
Build an HTML viewer for browsing comments by article and reviewing sentiment results.

Outputs to docs/ for GitHub Pages:
  docs/index.html  — two-tab app: comment browser + insights
  docs/data.json   — article + comment + sentiment data (loaded async)

Usage:
    python build_viewer.py
    cd docs && python -m http.server 8000
"""

import json
import os
import random
from collections import defaultdict
from pathlib import Path

COMMENTS_PATH = "data/comments.json"
SENTIMENT_PATH = "data/sentiment.json"
DOCS_DIR = Path("docs")


def load_data():
    """Load comments and merge in any available sentiment data."""
    articles = json.loads(open(COMMENTS_PATH).read())

    sentiment_map = {}
    if os.path.exists(SENTIMENT_PATH):
        sentiment_articles = json.loads(open(SENTIMENT_PATH).read())
        for a in sentiment_articles:
            for c in a["comments"]:
                if "sentiment" in c:
                    sentiment_map[c["commentID"]] = {
                        "sentiment": c["sentiment"],
                        "framing": c.get("framing", ""),
                        "confidence": c.get("confidence", ""),
                    }

    for a in articles:
        for c in a["comments"]:
            if c["commentID"] in sentiment_map:
                c["sentiment"] = sentiment_map[c["commentID"]]["sentiment"]
                c["framing"] = sentiment_map[c["commentID"]]["framing"]
                c["confidence"] = sentiment_map[c["commentID"]]["confidence"]

    return articles, len(sentiment_map)


def build_data_json(articles):
    """Build the slim data payload for the browser tab."""
    return [{
        "article_id": a["article_id"],
        "web_url": a["web_url"],
        "headline": a["headline"],
        "pub_date": a["pub_date"],
        "month": a["month"],
        "comment_count": a["comment_count"],
        "comments": [{
            "commentID": c["commentID"],
            "commentBody": c["commentBody"],
            "userDisplayName": c.get("userDisplayName", ""),
            "userLocation": c.get("userLocation", ""),
            "createDate": c.get("createDate", ""),
            "recommendations": c.get("recommendations", 0),
            "depth": c.get("depth", 1),
            "sentiment": c.get("sentiment", ""),
            "framing": c.get("framing", ""),
            "confidence": c.get("confidence", ""),
        } for c in a["comments"]]
    } for a in articles]


def build_insights_data(articles):
    """Pre-compute aggregated stats for the insights tab."""
    monthly_s = defaultdict(lambda: defaultdict(int))
    monthly_f = defaultdict(lambda: defaultdict(int))
    sbf = defaultdict(lambda: defaultdict(int))  # sentiment by framing
    examples = defaultdict(list)

    for article in articles:
        month = article["month"]
        headline = article["headline"]
        for comment in article["comments"]:
            s = comment.get("sentiment", "")
            f = comment.get("framing", "")
            conf = comment.get("confidence", "")
            body = (comment.get("commentBody") or "").strip()

            if not s:
                continue

            monthly_s[month][s] += 1

            if f in ("tool", "entity"):
                monthly_f[month][f] += 1
                sbf[f][s] += 1

            # Collect high-confidence examples of reasonable length
            if conf == "high" and 80 <= len(body) <= 380:
                entry = {
                    "body": body,
                    "author": comment.get("userDisplayName", "Anonymous"),
                    "location": comment.get("userLocation", ""),
                    "recs": comment.get("recommendations", 0),
                    "headline": headline,
                }
                if s == "negative" and f != "entity":
                    examples["negative"].append(entry)
                if s == "positive":
                    examples["positive"].append(entry)
                if f == "entity" and s == "negative":
                    examples["entity_negative"].append(entry)
                if f == "tool":
                    examples["tool"].append(entry)

    months = sorted(monthly_s.keys())
    monthly = []
    for month in months:
        sd = monthly_s[month]
        total = sum(sd.values())
        if total < 10:
            continue
        fd = monthly_f[month]
        ft = sum(fd.values())
        monthly.append({
            "month": month,
            "pct_neg": round(sd.get("negative", 0) / total * 100, 1),
            "pct_pos": round(sd.get("positive", 0) / total * 100, 1),
            "pct_neu": round(sd.get("neutral", 0) / total * 100, 1),
            "total": total,
            "pct_tool": round(fd.get("tool", 0) / ft * 100, 1) if ft else 0,
            "pct_entity": round(fd.get("entity", 0) / ft * 100, 1) if ft else 0,
        })

    all_s = defaultdict(int)
    all_f = defaultdict(int)
    for d in monthly_s.values():
        for k, v in d.items():
            all_s[k] += v
    for d in monthly_f.values():
        for k, v in d.items():
            all_f[k] += v

    total_all = sum(all_s.values())
    ft_all = sum(all_f.values())

    random.seed(42)
    sampled = {}
    for key, items in examples.items():
        pool = sorted(items, key=lambda x: x["recs"], reverse=True)[:60]
        sampled[key] = random.sample(pool, min(4, len(pool)))

    sbf_pct = {}
    for framing, d in sbf.items():
        ft = sum(d.values())
        sbf_pct[framing] = {s: round(v / ft * 100, 1) for s, v in d.items()}

    return {
        "monthly": monthly,
        "overall": {k: round(v / total_all * 100, 1) for k, v in all_s.items()},
        "framing_overall": {k: round(v / ft_all * 100, 1) for k, v in all_f.items()} if ft_all else {},
        "sbf": sbf_pct,
        "total": total_all,
        "examples": sampled,
    }


INDEX_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NYT AI Comments</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f5f5; color: #222; height: 100vh; display: flex; flex-direction: column; }

  /* Tabs */
  .tabs-nav { display: flex; background: #fff; border-bottom: 2px solid #e8e8e8; padding: 0 20px; flex-shrink: 0; }
  .tab-btn { padding: 12px 20px; border: none; background: none; cursor: pointer; font-size: 14px; font-weight: 500; color: #888; border-bottom: 2px solid transparent; margin-bottom: -2px; }
  .tab-btn:hover { color: #333; }
  .tab-btn.active { color: #2196F3; border-bottom-color: #2196F3; }
  .tab-content { display: none; flex: 1; overflow: hidden; }
  .tab-content.active { display: flex; }
  #tab-insights.active { display: block; overflow-y: auto; }

  /* ── BROWSER TAB ── */
  .loading { display: flex; align-items: center; justify-content: center; width: 100%; font-size: 18px; color: #999; }
  .layout { display: flex; width: 100%; }
  .sidebar { width: 380px; min-width: 380px; background: #fff; border-right: 1px solid #ddd; display: flex; flex-direction: column; height: calc(100vh - 45px); }
  .sidebar-header { padding: 16px; border-bottom: 1px solid #eee; background: #fafafa; }
  .sidebar-header h1 { font-size: 16px; margin-bottom: 8px; }
  .sidebar-header .stats { font-size: 13px; color: #666; line-height: 1.6; }
  .search-box { width: 100%; padding: 8px 12px; border: 1px solid #ddd; border-radius: 6px; font-size: 14px; margin-top: 8px; }
  .filter-row { display: flex; gap: 6px; margin-top: 8px; flex-wrap: wrap; }
  .filter-btn { padding: 4px 10px; border: 1px solid #ddd; border-radius: 12px; font-size: 12px; cursor: pointer; background: #fff; }
  .filter-btn.active { background: #333; color: #fff; border-color: #333; }
  .article-list { flex: 1; overflow-y: auto; }
  .article-item { padding: 12px 16px; border-bottom: 1px solid #f0f0f0; cursor: pointer; transition: background 0.1s; }
  .article-item:hover { background: #f0f7ff; }
  .article-item.selected { background: #e3f0ff; border-left: 3px solid #2196F3; }
  .article-item .month { font-size: 11px; color: #999; text-transform: uppercase; }
  .article-item .headline { font-size: 13px; font-weight: 500; margin: 4px 0; line-height: 1.4; }
  .article-item .meta { font-size: 11px; color: #888; }
  .comment-count { background: #eee; padding: 1px 6px; border-radius: 8px; font-size: 11px; }
  .main { flex: 1; display: flex; flex-direction: column; overflow: hidden; height: calc(100vh - 45px); }
  .main-header { padding: 16px 24px; border-bottom: 1px solid #eee; background: #fff; }
  .main-header h2 { font-size: 18px; line-height: 1.4; }
  .main-header .article-meta { font-size: 13px; color: #666; margin-top: 4px; }
  .main-header a { color: #2196F3; text-decoration: none; }
  .comments-container { flex: 1; overflow-y: auto; padding: 16px 24px; }
  .comment { background: #fff; border-radius: 8px; padding: 16px; margin-bottom: 12px; border: 1px solid #e8e8e8; }
  .comment.depth-2 { margin-left: 32px; border-left: 3px solid #ddd; }
  .comment-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
  .comment-author { font-weight: 600; font-size: 13px; }
  .comment-location { color: #888; font-size: 12px; }
  .comment-body { font-size: 14px; line-height: 1.6; color: #333; }
  .comment-footer { display: flex; gap: 16px; margin-top: 10px; font-size: 12px; color: #999; }
  .sentiment-badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; text-transform: uppercase; }
  .sentiment-positive { background: #e8f5e9; color: #2e7d32; }
  .sentiment-negative { background: #fce4ec; color: #c62828; }
  .sentiment-neutral { background: #f5f5f5; color: #757575; }
  .sentiment-irrelevant { background: #fff3e0; color: #e65100; }
  .framing-badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; text-transform: uppercase; margin-left: 4px; }
  .framing-tool { background: #e3f2fd; color: #1565c0; }
  .framing-entity { background: #f3e5f5; color: #7b1fa2; }
  .sentiment-panel { width: 300px; min-width: 300px; background: #fff; border-left: 1px solid #ddd; padding: 16px; overflow-y: auto; height: calc(100vh - 45px); }
  .sentiment-panel h3 { font-size: 14px; margin-bottom: 12px; }
  .stat-card { background: #fafafa; border-radius: 8px; padding: 12px; margin-bottom: 10px; border: 1px solid #eee; }
  .stat-card .label { font-size: 12px; color: #888; text-transform: uppercase; }
  .stat-card .value { font-size: 24px; font-weight: 700; margin: 4px 0; }
  .stat-card .sub { font-size: 12px; color: #aaa; }
  .bar { height: 8px; border-radius: 4px; background: #eee; margin: 8px 0; overflow: hidden; display: flex; }
  .bar-pos { background: #4caf50; }
  .bar-neu { background: #bdbdbd; }
  .bar-neg { background: #e53935; }
  .bar-irr { background: #ff9800; }
  .placeholder { color: #bbb; font-size: 13px; text-align: center; padding: 40px 0; }
  .no-article { display: flex; align-items: center; justify-content: center; flex: 1; color: #bbb; font-size: 16px; }

  /* ── INSIGHTS TAB ── */
  .insights-page { max-width: 920px; margin: 0 auto; padding: 40px 24px 80px; }
  .insights-page h1 { font-size: 28px; font-weight: 700; margin-bottom: 8px; }
  .insights-subtitle { font-size: 15px; color: #666; margin-bottom: 40px; line-height: 1.5; }
  .key-stats { display: flex; gap: 16px; margin-bottom: 48px; flex-wrap: wrap; }
  .key-stat { background: #fff; border-radius: 10px; padding: 20px 24px; border: 1px solid #e8e8e8; flex: 1; min-width: 160px; }
  .ks-value { font-size: 38px; font-weight: 700; line-height: 1; }
  .ks-label { font-size: 13px; color: #888; margin-top: 6px; line-height: 1.4; }
  .story-section { background: #fff; border-radius: 12px; padding: 32px; margin-bottom: 32px; border: 1px solid #e8e8e8; }
  .story-section h2 { font-size: 20px; font-weight: 700; margin-bottom: 10px; line-height: 1.35; }
  .story-desc { font-size: 14px; color: #555; margin-bottom: 28px; line-height: 1.7; }
  .chart-wrap { position: relative; margin-bottom: 32px; }
  .quotes-label { font-size: 11px; font-weight: 600; text-transform: uppercase; color: #999; letter-spacing: 0.05em; margin-bottom: 12px; }
  .quotes-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }
  .quote-card { border-radius: 8px; padding: 16px 18px; border-left: 4px solid; }
  .quote-card.negative { background: #fff5f5; border-color: #e74c3c; }
  .quote-card.positive { background: #f0fff4; border-color: #2ecc71; }
  .quote-card.entity  { background: #fdf4ff; border-color: #9b59b6; }
  .quote-card.tool    { background: #f0f7ff; border-color: #3498db; }
  .quote-body { font-size: 13px; line-height: 1.65; color: #333; margin-bottom: 10px; font-style: italic; }
  .quote-meta { font-size: 11px; color: #999; }
  .quote-meta strong { color: #666; font-style: normal; }
  .quote-article { font-size: 11px; color: #bbb; margin-top: 3px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
</style>
</head>
<body>

<nav class="tabs-nav">
  <button class="tab-btn active" id="btn-browser" onclick="showTab('browser')">Comment Browser</button>
  <button class="tab-btn" id="btn-insights" onclick="showTab('insights')">Insights</button>
</nav>

<!-- ── TAB 1: BROWSER ── -->
<div id="tab-browser" class="tab-content active">
  <div class="loading" id="loading">Loading data&hellip;</div>
  <div class="layout" id="app" style="display:none">
    <div class="sidebar">
      <div class="sidebar-header">
        <h1>NYT AI Comments</h1>
        <div class="stats" id="headerStats"></div>
        <input type="text" class="search-box" placeholder="Search headlines..." oninput="filterArticles()">
        <div class="filter-row">
          <button class="filter-btn active" onclick="setFilter('all', this)">All</button>
          <button class="filter-btn" onclick="setFilter('has-comments', this)">Has comments</button>
          <button class="filter-btn" onclick="setFilter('classified', this)">Classified</button>
        </div>
      </div>
      <div class="article-list" id="articleList"></div>
    </div>
    <div class="main">
      <div class="main-header" id="mainHeader">
        <div class="no-article">Select an article from the sidebar</div>
      </div>
      <div class="comments-container" id="commentsContainer"></div>
    </div>
    <div class="sentiment-panel">
      <h3>Sentiment Analysis</h3>
      <div id="globalStats"></div>
      <hr style="border:none;border-top:1px solid #eee;margin:16px 0;">
      <h3>Article Sentiment</h3>
      <div id="articleStats"><div class="placeholder">Select an article to see its sentiment breakdown</div></div>
    </div>
  </div>
</div>

<!-- ── TAB 2: INSIGHTS ── -->
<div id="tab-insights" class="tab-content">
  <div class="insights-page">
    <h1>How NYT Readers Feel About AI</h1>
    <p class="insights-subtitle">
      Analysis of <strong>__TOTAL__</strong> classified comments across <strong>__ARTICLE_COUNT__</strong> articles
      &middot; November 2022 &ndash; March 2026
    </p>

    <div class="key-stats">
      <div class="key-stat">
        <div class="ks-value" style="color:#e74c3c">__PCT_NEG__%</div>
        <div class="ks-label">of comments are negative toward AI</div>
      </div>
      <div class="key-stat">
        <div class="ks-value" style="color:#2ecc71">__PCT_POS__%</div>
        <div class="ks-label">are positive toward AI</div>
      </div>
      <div class="key-stat">
        <div class="ks-value" style="color:#3498db">__PCT_TOOL__%</div>
        <div class="ks-label">frame AI as a tool</div>
      </div>
      <div class="key-stat">
        <div class="ks-value" style="color:#9b59b6">__PCT_ENTITY__%</div>
        <div class="ks-label">frame AI as an autonomous entity</div>
      </div>
    </div>

    <!-- Story 1: Mostly negative, consistently -->
    <div class="story-section">
      <h2>Most NYT readers are skeptical of AI &mdash; and have been since day one</h2>
      <p class="story-desc">
        Since ChatGPT launched in November 2022, negative sentiment has consistently dominated reader comments.
        Despite major capability advances &mdash; GPT-4, Sora, DeepSeek &mdash; the ratio has remained remarkably
        stable: roughly half of commenters express fear, concern, or criticism of AI.
      </p>
      <div class="chart-wrap"><canvas id="chartSentiment" height="75"></canvas></div>
      <p class="quotes-label">Representative negative comments</p>
      <div class="quotes-grid" id="quotes-negative"></div>
    </div>

    <!-- Story 2: Mostly tool framing, consistently -->
    <div class="story-section">
      <h2>Most people see AI as a tool humans control &mdash; not an autonomous agent</h2>
      <p class="story-desc">
        When commenters describe AI, the majority treat it as a technology to be used, shaped, and regulated
        rather than as an entity with its own agency or will. This framing has also held steady over time,
        suggesting a stable conceptual model of AI in the public mind.
      </p>
      <div class="chart-wrap"><canvas id="chartFraming" height="75"></canvas></div>
      <p class="quotes-label">Comments framing AI as a tool</p>
      <div class="quotes-grid" id="quotes-tool"></div>
    </div>

    <!-- Story 3: Entity framing = more fear -->
    <div class="story-section">
      <h2>But those who see AI as an agent are far more fearful</h2>
      <p class="story-desc">
        Commenters who frame AI as an autonomous entity &mdash; writing as if AI &ldquo;wants,&rdquo;
        &ldquo;thinks,&rdquo; or &ldquo;is coming for us&rdquo; &mdash; are dramatically more negative than
        those who treat AI as a tool. Entity framers show roughly twice the rate of negative sentiment,
        suggesting that anthropomorphization and fear go hand in hand.
      </p>
      <div class="chart-wrap"><canvas id="chartSbf" height="75"></canvas></div>
      <p class="quotes-label">Comments framing AI as an autonomous entity</p>
      <div class="quotes-grid" id="quotes-entity"></div>
    </div>

    <!-- Story 4: Positive voices -->
    <div class="story-section">
      <h2>The optimists: what does enthusiasm about AI look like?</h2>
      <p class="story-desc">
        The minority of commenters who are positive about AI tend to emphasize its potential as a productivity
        tool, draw parallels to past technological transitions, or express excitement about scientific
        and creative possibilities.
      </p>
      <div class="quotes-grid" id="quotes-positive"></div>
    </div>
  </div>
</div>

<script>
// ── TAB SWITCHING ────────────────────────────────────────────────────────────
let insightsInitialized = false;
function showTab(name) {
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  document.getElementById('btn-' + name).classList.add('active');
  if (name === 'insights' && !insightsInitialized) { initInsights(); insightsInitialized = true; }
}

// ── BROWSER TAB ──────────────────────────────────────────────────────────────
let articles = [], currentFilter = 'all', selectedIdx = -1;

fetch('data.json')
  .then(r => r.json())
  .then(data => {
    articles = data;
    document.getElementById('loading').style.display = 'none';
    document.getElementById('app').style.display = 'flex';
    const total = articles.reduce((s, a) => s + a.comment_count, 0);
    const classified = articles.flatMap(a => a.comments).filter(c => c.sentiment).length;
    document.getElementById('headerStats').innerHTML =
      `${articles.length} articles &middot; ${total.toLocaleString()} comments &middot; ${classified.toLocaleString()} classified`;
    renderGlobalStats();
    filterArticles();
  })
  .catch(err => { document.getElementById('loading').textContent = 'Error loading data: ' + err.message; });

function setFilter(f, btn) {
  currentFilter = f;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  filterArticles();
}

function filterArticles() {
  const q = document.querySelector('.search-box').value.toLowerCase();
  const list = document.getElementById('articleList');
  list.innerHTML = '';
  articles.forEach((a, i) => {
    if (q && !a.headline.toLowerCase().includes(q)) return;
    if (currentFilter === 'has-comments' && a.comment_count === 0) return;
    if (currentFilter === 'classified' && !a.comments.some(c => c.sentiment)) return;
    const div = document.createElement('div');
    div.className = 'article-item' + (i === selectedIdx ? ' selected' : '');
    const hasClassified = a.comments.some(c => c.sentiment);
    div.innerHTML = `
      <div class="month">${a.month}</div>
      <div class="headline">${escHtml(a.headline)}</div>
      <div class="meta">
        <span class="comment-count">${a.comment_count} comments</span>
        ${hasClassified ? '<span class="sentiment-badge sentiment-positive" style="margin-left:4px">classified</span>' : ''}
      </div>`;
    div.onclick = () => selectArticle(i);
    list.appendChild(div);
  });
}

function selectArticle(idx) {
  selectedIdx = idx;
  const a = articles[idx];
  document.getElementById('mainHeader').innerHTML = `
    <h2>${escHtml(a.headline)}</h2>
    <div class="article-meta">${a.month} &middot; ${a.comment_count} comments &middot; <a href="${a.web_url}" target="_blank">Read on NYT</a></div>`;
  const container = document.getElementById('commentsContainer');
  container.innerHTML = ''; container.scrollTop = 0;
  a.comments.forEach(c => {
    const div = document.createElement('div');
    div.className = 'comment' + (c.depth > 1 ? ' depth-2' : '');
    const sentBadge = c.sentiment ? `<span class="sentiment-badge sentiment-${c.sentiment}">${c.sentiment}</span>` : '';
    const frameBadge = c.framing && c.framing !== 'neither' ? `<span class="framing-badge framing-${c.framing}">${c.framing}</span>` : '';
    const date = c.createDate ? new Date(parseInt(c.createDate) * 1000).toLocaleDateString() : '';
    div.innerHTML = `
      <div class="comment-header">
        <div><span class="comment-author">${escHtml(c.userDisplayName)}</span><span class="comment-location">${c.userLocation ? ' &middot; ' + escHtml(c.userLocation) : ''}</span></div>
        <div>${sentBadge}${frameBadge}</div>
      </div>
      <div class="comment-body">${escHtml(c.commentBody)}</div>
      <div class="comment-footer"><span>&#9829; ${c.recommendations}</span><span>${date}</span></div>`;
    container.appendChild(div);
  });
  const statsDiv = document.getElementById('articleStats');
  const classified = a.comments.filter(c => c.sentiment);
  if (!classified.length) { statsDiv.innerHTML = '<div class="placeholder">No comments classified yet</div>'; }
  else {
    const pos = classified.filter(c => c.sentiment === 'positive').length;
    const neg = classified.filter(c => c.sentiment === 'negative').length;
    const neu = classified.filter(c => c.sentiment === 'neutral').length;
    const irr = classified.filter(c => c.sentiment === 'irrelevant').length;
    const t = classified.length;
    statsDiv.innerHTML = `
      <div class="stat-card"><div class="label">Classified</div><div class="value">${t} / ${a.comment_count}</div></div>
      <div class="bar"><div class="bar-pos" style="width:${pos/t*100}%"></div><div class="bar-neu" style="width:${neu/t*100}%"></div><div class="bar-neg" style="width:${neg/t*100}%"></div><div class="bar-irr" style="width:${irr/t*100}%"></div></div>
      <div class="stat-card"><div class="label">Positive</div><div class="value" style="color:#2e7d32">${pos} <span class="sub">(${(pos/t*100).toFixed(1)}%)</span></div></div>
      <div class="stat-card"><div class="label">Neutral</div><div class="value" style="color:#757575">${neu} <span class="sub">(${(neu/t*100).toFixed(1)}%)</span></div></div>
      <div class="stat-card"><div class="label">Negative</div><div class="value" style="color:#c62828">${neg} <span class="sub">(${(neg/t*100).toFixed(1)}%)</span></div></div>
      <div class="stat-card"><div class="label">Irrelevant</div><div class="value" style="color:#e65100">${irr} <span class="sub">(${(irr/t*100).toFixed(1)}%)</span></div></div>`;
  }
  filterArticles();
}

function renderGlobalStats() {
  const all = articles.flatMap(a => a.comments).filter(c => c.sentiment);
  const div = document.getElementById('globalStats');
  if (!all.length) { div.innerHTML = '<div class="placeholder">No comments classified yet.<br>Run step3_sentiment.py to start.</div>'; return; }
  const pos = all.filter(c => c.sentiment === 'positive').length;
  const neg = all.filter(c => c.sentiment === 'negative').length;
  const neu = all.filter(c => c.sentiment === 'neutral').length;
  const irr = all.filter(c => c.sentiment === 'irrelevant').length;
  const t = all.length;
  const totalAll = articles.reduce((s, a) => s + a.comment_count, 0);
  div.innerHTML = `
    <div class="stat-card"><div class="label">Overall Progress</div><div class="value">${t.toLocaleString()} <span class="sub">/ ${totalAll.toLocaleString()}</span></div><div class="sub">${(t/totalAll*100).toFixed(1)}% complete</div></div>
    <div class="bar"><div class="bar-pos" style="width:${pos/t*100}%"></div><div class="bar-neu" style="width:${neu/t*100}%"></div><div class="bar-neg" style="width:${neg/t*100}%"></div><div class="bar-irr" style="width:${irr/t*100}%"></div></div>
    <div class="stat-card"><div class="label">Positive</div><div class="value" style="color:#2e7d32">${pos} <span class="sub">(${(pos/t*100).toFixed(1)}%)</span></div></div>
    <div class="stat-card"><div class="label">Neutral</div><div class="value" style="color:#757575">${neu} <span class="sub">(${(neu/t*100).toFixed(1)}%)</span></div></div>
    <div class="stat-card"><div class="label">Negative</div><div class="value" style="color:#c62828">${neg} <span class="sub">(${(neg/t*100).toFixed(1)}%)</span></div></div>
    <div class="stat-card"><div class="label">Irrelevant</div><div class="value" style="color:#e65100">${irr} <span class="sub">(${(irr/t*100).toFixed(1)}%)</span></div></div>`;
}

function escHtml(s) {
  const d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML;
}

// ── INSIGHTS TAB ─────────────────────────────────────────────────────────────
const insightsData = __INSIGHTS_DATA__;

function initInsights() {
  const d = insightsData;
  const months = d.monthly.map(m => m.month);
  const chartDefaults = {
    responsive: true,
    plugins: { legend: { position: 'top' }, tooltip: { mode: 'index', intersect: false } },
  };

  // Chart 1: Sentiment over time
  new Chart(document.getElementById('chartSentiment'), {
    type: 'line',
    data: {
      labels: months,
      datasets: [
        { label: 'Negative', data: d.monthly.map(m => m.pct_neg), borderColor: '#e74c3c', backgroundColor: 'rgba(231,76,60,0.07)', fill: true, tension: 0.35, pointRadius: 2 },
        { label: 'Neutral',  data: d.monthly.map(m => m.pct_neu), borderColor: '#95a5a6', backgroundColor: 'rgba(149,165,166,0.07)', fill: true, tension: 0.35, pointRadius: 2 },
        { label: 'Positive', data: d.monthly.map(m => m.pct_pos), borderColor: '#2ecc71', backgroundColor: 'rgba(46,204,113,0.07)', fill: true, tension: 0.35, pointRadius: 2 },
      ]
    },
    options: { ...chartDefaults, scales: {
      y: { min: 0, max: 100, ticks: { callback: v => v + '%' }, title: { display: true, text: '% of classified comments' } },
      x: { ticks: { maxTicksLimit: 14 } }
    }}
  });

  // Chart 2: Framing over time
  new Chart(document.getElementById('chartFraming'), {
    type: 'line',
    data: {
      labels: months,
      datasets: [
        { label: 'Tool',   data: d.monthly.map(m => m.pct_tool),   borderColor: '#3498db', backgroundColor: 'rgba(52,152,219,0.09)', fill: true, tension: 0.35, pointRadius: 2 },
        { label: 'Entity', data: d.monthly.map(m => m.pct_entity), borderColor: '#9b59b6', backgroundColor: 'rgba(155,89,182,0.09)', fill: true, tension: 0.35, pointRadius: 2 },
      ]
    },
    options: { ...chartDefaults, scales: {
      y: { min: 0, max: 100, ticks: { callback: v => v + '%' }, title: { display: true, text: '% of tool+entity framed comments' } },
      x: { ticks: { maxTicksLimit: 14 } }
    }}
  });

  // Chart 3: Sentiment by framing (grouped bar)
  const sentKeys = ['negative', 'neutral', 'positive', 'irrelevant'];
  const tool   = d.sbf.tool   || {};
  const entity = d.sbf.entity || {};
  new Chart(document.getElementById('chartSbf'), {
    type: 'bar',
    data: {
      labels: ['Negative', 'Neutral', 'Positive', 'Irrelevant'],
      datasets: [
        { label: 'Tool framing',   data: sentKeys.map(s => tool[s]   || 0), backgroundColor: '#3498db', borderRadius: 4 },
        { label: 'Entity framing', data: sentKeys.map(s => entity[s] || 0), backgroundColor: '#9b59b6', borderRadius: 4 },
      ]
    },
    options: { ...chartDefaults, scales: {
      y: { min: 0, max: 100, ticks: { callback: v => v + '%' }, title: { display: true, text: '% within framing group' } }
    }}
  });

  renderQuotes('quotes-negative', d.examples.negative       || [], 'negative');
  renderQuotes('quotes-tool',     d.examples.tool            || [], 'tool');
  renderQuotes('quotes-entity',   d.examples.entity_negative || [], 'entity');
  renderQuotes('quotes-positive', d.examples.positive        || [], 'positive');
}

function renderQuotes(containerId, quotes, type) {
  const el = document.getElementById(containerId);
  if (!el || !quotes.length) return;
  el.innerHTML = quotes.map(q => `
    <div class="quote-card ${type}">
      <p class="quote-body">&ldquo;${escHtml(q.body)}&rdquo;</p>
      <p class="quote-meta"><strong>${escHtml(q.author)}</strong>${q.location ? ' &middot; ' + escHtml(q.location) : ''}${q.recs > 0 ? ' &middot; &#9829; ' + q.recs : ''}</p>
      <p class="quote-article">${escHtml(q.headline)}</p>
    </div>`).join('');
}
</script>
</body>
</html>"""


def main():
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    articles, num_classified = load_data()
    data = build_data_json(articles)
    insights = build_insights_data(articles)

    # Write data.json
    data_path = DOCS_DIR / "data.json"
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

    # Inject insights data + stat placeholders into HTML
    insights_json = json.dumps(insights, ensure_ascii=True).replace("</", "<\\/")
    overall = insights["overall"]
    framing = insights["framing_overall"]

    html = INDEX_HTML
    html = html.replace("__INSIGHTS_DATA__", insights_json)
    html = html.replace("__TOTAL__", f"{insights['total']:,}")
    html = html.replace("__ARTICLE_COUNT__", f"{len(articles):,}")
    html = html.replace("__PCT_NEG__", str(overall.get("negative", 0)))
    html = html.replace("__PCT_POS__", str(overall.get("positive", 0)))
    html = html.replace("__PCT_TOOL__", str(framing.get("tool", 0)))
    html = html.replace("__PCT_ENTITY__", str(framing.get("entity", 0)))

    html_path = DOCS_DIR / "index.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    data_mb = data_path.stat().st_size / (1024 * 1024)
    print(f"Built docs/index.html + docs/data.json ({data_mb:.1f} MB)")
    print(f"  {len(articles)} articles, {num_classified} classified comments")


if __name__ == "__main__":
    main()
