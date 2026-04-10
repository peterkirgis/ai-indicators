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
import math
import os
import random
from collections import defaultdict
from pathlib import Path

from geo import normalize_location, STATE_FIPS, STATE_FULL_NAMES, BACHELORS_PCT, GDP_PER_CAPITA

WEIGHT_ALPHA = 2.0  # position bias correction: 1.0 = no correction, higher = more aggressive
MIN_COMMENTS_FOR_BAND = 5  # articles need this many classified comments to contribute to error bands


def _percentile(values, p):
    """Compute p-th percentile without numpy."""
    if not values:
        return 0
    s = sorted(values)
    k = (len(s) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return round(s[f] + (k - f) * (s[c] - s[f]), 1)

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
    # Per-article percentages for error bands
    article_pcts = defaultdict(list)  # month -> list of per-article dicts
    # Per-article sentiment-by-framing for the cross-tab chart
    sbf_article_pcts = defaultdict(lambda: defaultdict(list))  # framing -> sentiment -> list of %

    for article in articles:
        month = article["month"]
        headline = article["headline"]
        classified = [c for c in article["comments"] if c.get("sentiment")]

        # Track per-article stats for variance bands
        if len(classified) >= MIN_COMMENTS_FOR_BAND:
            n = len(classified)
            framed = [c for c in classified if c.get("framing") in ("tool", "entity")]
            nf = len(framed) if framed else 0
            ap_entry = {
                "neg": sum(1 for c in classified if c["sentiment"] == "negative") / n * 100,
                "pos": sum(1 for c in classified if c["sentiment"] == "positive") / n * 100,
                "neu": sum(1 for c in classified if c["sentiment"] == "neutral") / n * 100,
            }
            if nf >= 3:
                ap_entry["tool"] = sum(1 for c in framed if c["framing"] == "tool") / nf * 100
                ap_entry["entity"] = sum(1 for c in framed if c["framing"] == "entity") / nf * 100
            article_pcts[month].append(ap_entry)

        # Per-article sentiment-by-framing for cross-tab error bars
        for framing_type in ("tool", "entity"):
            framed_of_type = [c for c in classified if c.get("framing") == framing_type]
            if len(framed_of_type) >= 3:
                nft = len(framed_of_type)
                sbf_article_pcts[framing_type]["negative"].append(
                    sum(1 for c in framed_of_type if c["sentiment"] == "negative") / nft * 100)
                sbf_article_pcts[framing_type]["positive"].append(
                    sum(1 for c in framed_of_type if c["sentiment"] == "positive") / nft * 100)
                sbf_article_pcts[framing_type]["neutral"].append(
                    sum(1 for c in framed_of_type if c["sentiment"] == "neutral") / nft * 100)

        for comment in classified:
            s = comment["sentiment"]
            f = comment.get("framing", "")
            conf = comment.get("confidence", "")
            body = (comment.get("commentBody") or "").strip()

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
        ap = article_pcts.get(month, [])
        monthly.append({
            "month": month,
            "pct_neg": round(sd.get("negative", 0) / total * 100, 1),
            "pct_pos": round(sd.get("positive", 0) / total * 100, 1),
            "pct_neu": round(sd.get("neutral", 0) / total * 100, 1),
            "total": total,
            "pct_tool": round(fd.get("tool", 0) / ft * 100, 1) if ft else 0,
            "pct_entity": round(fd.get("entity", 0) / ft * 100, 1) if ft else 0,
            "neg_p25": _percentile([a["neg"] for a in ap], 25) if ap else None,
            "neg_p75": _percentile([a["neg"] for a in ap], 75) if ap else None,
            "pos_p25": _percentile([a["pos"] for a in ap], 25) if ap else None,
            "pos_p75": _percentile([a["pos"] for a in ap], 75) if ap else None,
            "tool_p25": _percentile([a["tool"] for a in ap if "tool" in a], 25) if any("tool" in a for a in ap) else None,
            "tool_p75": _percentile([a["tool"] for a in ap if "tool" in a], 75) if any("tool" in a for a in ap) else None,
            "entity_p25": _percentile([a["entity"] for a in ap if "entity" in a], 25) if any("entity" in a for a in ap) else None,
            "entity_p75": _percentile([a["entity"] for a in ap if "entity" in a], 75) if any("entity" in a for a in ap) else None,
            "n_articles": len(ap),
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

    # Compute IQR for sentiment-by-framing cross-tab
    sbf_bands = {}
    for framing, sents in sbf_article_pcts.items():
        sbf_bands[framing] = {}
        for sent, vals in sents.items():
            sbf_bands[framing][sent] = {
                "p25": _percentile(vals, 25),
                "p75": _percentile(vals, 75),
            }

    # Geographic breakdown by US state
    geo_data = defaultdict(lambda: {"n": 0, "neg": 0, "pos": 0, "tool": 0, "entity": 0, "framed": 0})
    geo_total = 0
    geo_mapped = 0
    geo_non_us = 0
    for article in articles:
        for comment in article["comments"]:
            if not comment.get("sentiment"):
                continue
            loc = (comment.get("userLocation") or "").strip()
            if not loc:
                continue
            geo_total += 1
            state = normalize_location(loc)
            if state is None:
                continue
            if state == "non-us":
                geo_non_us += 1
                continue
            geo_mapped += 1
            g = geo_data[state]
            g["n"] += 1
            if comment["sentiment"] == "negative":
                g["neg"] += 1
            elif comment["sentiment"] == "positive":
                g["pos"] += 1
            f = comment.get("framing", "")
            if f == "tool":
                g["tool"] += 1
                g["framed"] += 1
            elif f == "entity":
                g["entity"] += 1
                g["framed"] += 1

    MIN_STATE_N = 50
    geo_states = []
    for state, g in sorted(geo_data.items(), key=lambda x: -x[1]["n"]):
        if g["n"] < MIN_STATE_N:
            continue
        geo_states.append({
            "state": state,
            "name": STATE_FULL_NAMES.get(state, state),
            "fips": STATE_FIPS.get(state, ""),
            "n": g["n"],
            "pct_neg": round(g["neg"] / g["n"] * 100, 1),
            "pct_pos": round(g["pos"] / g["n"] * 100, 1),
            "pct_entity": round(g["entity"] / g["framed"] * 100, 1) if g["framed"] >= 10 else None,
            "bachelors_pct": BACHELORS_PCT.get(state),
            "gdp_pc": GDP_PER_CAPITA.get(state),
        })

    return {
        "monthly": monthly,
        "overall": {k: round(v / total_all * 100, 1) for k, v in all_s.items()},
        "framing_overall": {k: round(v / ft_all * 100, 1) for k, v in all_f.items()} if ft_all else {},
        "sbf": sbf_pct,
        "sbf_bands": sbf_bands,
        "total": total_all,
        "examples": sampled,
        "geo": {
            "states": geo_states,
            "mapped": geo_mapped,
            "non_us": geo_non_us,
            "total": geo_total,
            "coverage_pct": round(geo_mapped / geo_total * 100, 1) if geo_total else 0,
        },
    }


def build_insights_data_weighted(articles, alpha=WEIGHT_ALPHA):
    """Like build_insights_data, but weights by community endorsement (likes)
    with position-bias correction. Only includes top-level comments (depth=1)."""
    monthly_s = defaultdict(lambda: defaultdict(float))
    monthly_f = defaultdict(lambda: defaultdict(float))
    sbf = defaultdict(lambda: defaultdict(float))
    examples = defaultdict(list)
    article_pcts = defaultdict(list)
    sbf_article_pcts = defaultdict(lambda: defaultdict(list))
    total_unweighted = 0

    for article in articles:
        month = article["month"]
        headline = article["headline"]

        # Filter to top-level, classified comments and sort by time
        top_level = [
            c for c in article["comments"]
            if c.get("depth", 1) == 1 and c.get("sentiment")
        ]
        top_level.sort(key=lambda c: int(c.get("createDate") or 0))
        n = len(top_level)
        if n == 0:
            continue

        # Per-article weighted percentages for error bands
        art_weights = defaultdict(float)
        art_framing_w = defaultdict(float)
        art_sbf_w = defaultdict(lambda: defaultdict(float))  # framing -> sentiment -> weight
        art_sbf_total = defaultdict(float)  # framing -> total weight
        art_total_w = 0.0
        art_framing_total_w = 0.0

        for i, comment in enumerate(top_level):
            recs = comment.get("recommendations", 0)
            frac_rank = i / (n - 1) if n > 1 else 0.0
            rank_factor = 1 + alpha * frac_rank
            weight = math.log1p(recs) / rank_factor
            if weight == 0:
                continue

            total_unweighted += 1
            s = comment["sentiment"]
            f = comment.get("framing", "")
            body = (comment.get("commentBody") or "").strip()

            monthly_s[month][s] += weight
            art_weights[s] += weight
            art_total_w += weight

            if f in ("tool", "entity"):
                monthly_f[month][f] += weight
                sbf[f][s] += weight
                art_framing_w[f] += weight
                art_framing_total_w += weight
                art_sbf_w[f][s] += weight
                art_sbf_total[f] += weight

            # Collect examples sorted by weight
            if comment.get("confidence") == "high" and 80 <= len(body) <= 380:
                entry = {
                    "body": body,
                    "author": comment.get("userDisplayName", "Anonymous"),
                    "location": comment.get("userLocation", ""),
                    "recs": recs,
                    "headline": headline,
                    "weight": round(weight, 2),
                }
                if s == "negative" and f != "entity":
                    examples["negative"].append(entry)
                if s == "positive":
                    examples["positive"].append(entry)
                if f == "entity" and s == "negative":
                    examples["entity_negative"].append(entry)
                if f == "tool":
                    examples["tool"].append(entry)

        if art_total_w > 0 and n >= MIN_COMMENTS_FOR_BAND:
            ap_entry = {
                "neg": art_weights.get("negative", 0) / art_total_w * 100,
                "pos": art_weights.get("positive", 0) / art_total_w * 100,
                "neu": art_weights.get("neutral", 0) / art_total_w * 100,
            }
            if art_framing_total_w > 0:
                ap_entry["tool"] = art_framing_w.get("tool", 0) / art_framing_total_w * 100
                ap_entry["entity"] = art_framing_w.get("entity", 0) / art_framing_total_w * 100
            article_pcts[month].append(ap_entry)

            # Per-article sentiment-by-framing for cross-tab error bars
            for ft_type in ("tool", "entity"):
                if art_sbf_total[ft_type] > 0:
                    for sent in ("negative", "positive", "neutral"):
                        pct = art_sbf_w[ft_type].get(sent, 0) / art_sbf_total[ft_type] * 100
                        sbf_article_pcts[ft_type][sent].append(pct)

    months = sorted(monthly_s.keys())
    monthly = []
    for month in months:
        sd = monthly_s[month]
        total = sum(sd.values())
        if total < 1:
            continue
        fd = monthly_f[month]
        ft = sum(fd.values())
        ap = article_pcts.get(month, [])
        monthly.append({
            "month": month,
            "pct_neg": round(sd.get("negative", 0) / total * 100, 1),
            "pct_pos": round(sd.get("positive", 0) / total * 100, 1),
            "pct_neu": round(sd.get("neutral", 0) / total * 100, 1),
            "total": round(total, 1),
            "pct_tool": round(fd.get("tool", 0) / ft * 100, 1) if ft else 0,
            "pct_entity": round(fd.get("entity", 0) / ft * 100, 1) if ft else 0,
            "neg_p25": _percentile([a["neg"] for a in ap], 25) if ap else None,
            "neg_p75": _percentile([a["neg"] for a in ap], 75) if ap else None,
            "pos_p25": _percentile([a["pos"] for a in ap], 25) if ap else None,
            "pos_p75": _percentile([a["pos"] for a in ap], 75) if ap else None,
            "tool_p25": _percentile([a["tool"] for a in ap if "tool" in a], 25) if any("tool" in a for a in ap) else None,
            "tool_p75": _percentile([a["tool"] for a in ap if "tool" in a], 75) if any("tool" in a for a in ap) else None,
            "entity_p25": _percentile([a["entity"] for a in ap if "entity" in a], 25) if any("entity" in a for a in ap) else None,
            "entity_p75": _percentile([a["entity"] for a in ap if "entity" in a], 75) if any("entity" in a for a in ap) else None,
            "n_articles": len(ap),
        })

    all_s = defaultdict(float)
    all_f = defaultdict(float)
    for d in monthly_s.values():
        for k, v in d.items():
            all_s[k] += v
    for d in monthly_f.values():
        for k, v in d.items():
            all_f[k] += v

    total_all = sum(all_s.values())
    ft_all = sum(all_f.values())

    random.seed(43)  # different seed so weighted examples differ from raw
    sampled = {}
    for key, items in examples.items():
        pool = sorted(items, key=lambda x: x["weight"], reverse=True)[:60]
        sampled[key] = random.sample(pool, min(4, len(pool)))

    sbf_pct = {}
    for framing, d in sbf.items():
        ft = sum(d.values())
        sbf_pct[framing] = {s: round(v / ft * 100, 1) for s, v in d.items()}

    sbf_bands = {}
    for framing, sents in sbf_article_pcts.items():
        sbf_bands[framing] = {}
        for sent, vals in sents.items():
            sbf_bands[framing][sent] = {
                "p25": _percentile(vals, 25),
                "p75": _percentile(vals, 75),
            }

    # Geographic breakdown (weighted)
    geo_data = defaultdict(lambda: {"w": 0.0, "neg": 0.0, "pos": 0.0, "tool": 0.0, "entity": 0.0, "framed": 0.0, "n": 0})
    geo_total = 0
    geo_mapped = 0
    geo_non_us = 0
    for article in articles:
        top_level = [c for c in article["comments"] if c.get("depth", 1) == 1 and c.get("sentiment")]
        top_level.sort(key=lambda c: int(c.get("createDate") or 0))
        n = len(top_level)
        if not n:
            continue
        for i, comment in enumerate(top_level):
            loc = (comment.get("userLocation") or "").strip()
            if not loc:
                continue
            recs = comment.get("recommendations", 0)
            frac_rank = i / (n - 1) if n > 1 else 0.0
            w = math.log1p(recs) / (1 + alpha * frac_rank)
            if w == 0:
                continue
            geo_total += 1
            state = normalize_location(loc)
            if state is None:
                continue
            if state == "non-us":
                geo_non_us += 1
                continue
            geo_mapped += 1
            g = geo_data[state]
            g["w"] += w
            g["n"] += 1
            if comment["sentiment"] == "negative":
                g["neg"] += w
            elif comment["sentiment"] == "positive":
                g["pos"] += w
            f = comment.get("framing", "")
            if f == "tool":
                g["tool"] += w
                g["framed"] += w
            elif f == "entity":
                g["entity"] += w
                g["framed"] += w

    MIN_STATE_N = 50
    geo_states = []
    for state, g in sorted(geo_data.items(), key=lambda x: -x[1]["n"]):
        if g["n"] < MIN_STATE_N:
            continue
        geo_states.append({
            "state": state,
            "name": STATE_FULL_NAMES.get(state, state),
            "fips": STATE_FIPS.get(state, ""),
            "n": g["n"],
            "pct_neg": round(g["neg"] / g["w"] * 100, 1) if g["w"] else 0,
            "pct_pos": round(g["pos"] / g["w"] * 100, 1) if g["w"] else 0,
            "pct_entity": round(g["entity"] / g["framed"] * 100, 1) if g["framed"] >= 10 else None,
            "bachelors_pct": BACHELORS_PCT.get(state),
            "gdp_pc": GDP_PER_CAPITA.get(state),
        })

    return {
        "monthly": monthly,
        "overall": {k: round(v / total_all * 100, 1) for k, v in all_s.items()} if total_all else {},
        "framing_overall": {k: round(v / ft_all * 100, 1) for k, v in all_f.items()} if ft_all else {},
        "sbf": sbf_pct,
        "sbf_bands": sbf_bands,
        "total": total_unweighted,
        "examples": sampled,
        "geo": {
            "states": geo_states,
            "mapped": geo_mapped,
            "non_us": geo_non_us,
            "total": geo_total,
            "coverage_pct": round(geo_mapped / geo_total * 100, 1) if geo_total else 0,
        },
    }


INDEX_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NYT AI Comments</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3.0.1/dist/chartjs-plugin-annotation.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-chart-geo@4.1.1"></script>
<script src="https://cdn.jsdelivr.net/npm/topojson-client@3"></script>
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
  #tab-insights.active, #tab-methods.active { display: block; overflow-y: auto; }

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
  .view-toggle { display: flex; align-items: center; gap: 8px; margin-bottom: 32px; }
  .toggle-btn { padding: 8px 16px; border: 1px solid #ddd; border-radius: 20px; background: #fff; cursor: pointer; font-size: 13px; font-weight: 500; color: #555; }
  .toggle-btn:hover { border-color: #999; }
  .toggle-btn.active { background: #333; color: #fff; border-color: #333; }
  .toggle-hint { font-size: 12px; color: #999; margin-left: 8px; }
  .annotation-toggle { display: flex; align-items: center; gap: 6px; margin-bottom: 16px; font-size: 13px; color: #666; cursor: pointer; user-select: none; }
  .annotation-toggle input { cursor: pointer; }
</style>
</head>
<body>

<nav class="tabs-nav">
  <button class="tab-btn active" id="btn-insights" onclick="showTab('insights')">Insights</button>
  <button class="tab-btn" id="btn-browser" onclick="showTab('browser')">Comment Browser</button>
  <button class="tab-btn" id="btn-methods" onclick="showTab('methods')">Methodology</button>
</nav>

<!-- ── TAB 1: BROWSER ── -->
<div id="tab-browser" class="tab-content">
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
<div id="tab-insights" class="tab-content active">
  <div class="insights-page">
    <h1>How NYT Readers Feel About AI</h1>
    <p class="insights-subtitle" id="insightsSubtitle"></p>

    <div class="view-toggle">
      <button class="toggle-btn active" onclick="switchView('raw', this)">Raw count</button>
      <button class="toggle-btn" onclick="switchView('weighted', this)">Community-endorsed</button>
      <span class="toggle-hint" id="toggleHint">Each comment counts equally</span>
    </div>

    <div class="key-stats" id="keyStats"></div>

    <label class="annotation-toggle"><input type="checkbox" id="annotationsToggle" onchange="toggleAnnotations(this.checked)"> Show key AI events on charts</label>

    <!-- Story 1: Mostly negative, consistently -->
    <div class="story-section">
      <h2>Most NYT readers are skeptical of AI &mdash; and have been since day one</h2>
      <p class="story-desc">
        Since ChatGPT launched in November 2022, negative sentiment has consistently dominated reader comments.
        Despite major capability advances &mdash; GPT-4, Sora, DeepSeek &mdash; the ratio has remained remarkably
        stable: roughly half of commenters express fear, concern, or criticism of AI.
      </p>
      <div class="chart-wrap"><canvas id="chartSentiment" height="110"></canvas></div>
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
      <div class="chart-wrap"><canvas id="chartFraming" height="110"></canvas></div>
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

    <!-- Story 5: Geography -->
    <div class="story-section">
      <h2>Does where you live shape how you feel about AI?</h2>
      <p class="story-desc" id="geoDesc"></p>
      <div class="filter-row" style="margin-bottom:16px">
        <button class="filter-btn active" id="geoBtn-sentiment" onclick="switchGeoView('sentiment', this)" style="border-left: 4px solid #2ecc71">Sentiment (% positive)</button>
        <button class="filter-btn" id="geoBtn-framing" onclick="switchGeoView('framing', this)" style="border-left: 4px solid #9b59b6">Mental model (% entity)</button>
      </div>
      <div class="chart-wrap" style="position:relative; height:520px; margin-bottom:0;"><canvas id="chartGeo"></canvas></div>
      <div id="geoLegend" style="display:flex; align-items:center; justify-content:center; gap:8px; font-size:12px; color:#888; margin:8px 0 16px;"></div>
      <div style="display:flex; gap:16px; flex-wrap:wrap;">
        <div style="flex:1; min-width:380px;">
          <div class="chart-wrap"><canvas id="chartGeoPolitics" height="280"></canvas></div>
          <p class="story-desc" id="corrPolitics" style="margin-top:8px; text-align:center; font-size:13px;"></p>
        </div>
        <div style="flex:1; min-width:380px;">
          <div class="chart-wrap"><canvas id="chartGeoGdp" height="280"></canvas></div>
          <p class="story-desc" id="corrGdp" style="margin-top:8px; text-align:center; font-size:13px;"></p>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- ── TAB 3: METHODOLOGY ── -->
<div id="tab-methods" class="tab-content">
  <div class="insights-page" style="max-width:760px">
    <h1>Methodology</h1>

    <div class="story-section">
      <h2>Data collection</h2>
      <p class="story-desc">
        <strong>Articles:</strong> Extracted from the NYT Archive API (Nov 2022 &ndash; Mar 2026).
        Headlines filtered for mentions of &ldquo;AI,&rdquo; &ldquo;A.I.,&rdquo; or &ldquo;artificial intelligence&rdquo;
        using regex pattern matching. <strong>1,434 articles</strong> matched.<br><br>
        <strong>Comments:</strong> All reader comments scraped via the NYT Community API, including replies.
        Comments sorted by &ldquo;recommended&rdquo; (default NYT ordering).
        <strong>138,450 comments</strong> collected.
      </p>
    </div>

    <div class="story-section">
      <h2>Sentiment &amp; framing classification</h2>
      <p class="story-desc">
        Each comment was classified by <strong>Google Gemini 3 Flash</strong> (via OpenRouter, temperature&nbsp;0.0)
        on two dimensions:<br><br>
        <strong>Sentiment</strong> &mdash; the commenter&rsquo;s attitude toward AI itself (not the article):<br>
        &bull; <em>Positive:</em> enthusiasm, optimism, support<br>
        &bull; <em>Negative:</em> fear, concern, criticism, opposition<br>
        &bull; <em>Neutral:</em> factual discussion, genuine questions<br>
        &bull; <em>Irrelevant:</em> not about AI<br><br>
        <strong>Framing</strong> &mdash; how the commenter conceptualizes AI:<br>
        &bull; <em>Tool:</em> AI as technology humans use and control<br>
        &bull; <em>Entity:</em> AI as an autonomous agent with its own will or agency<br>
        &bull; <em>Neither:</em> doesn&rsquo;t clearly fit either category<br><br>
        Comments were truncated to 500 characters and processed in batches of 50.
        Each classification includes a confidence level (high/medium/low).
      </p>
    </div>

    <div class="story-section">
      <h2>Community-endorsed (weighted) analysis</h2>
      <p class="story-desc">
        The weighted view adjusts for two biases in raw comment counts:<br><br>
        <strong>1. Not all comments are equal.</strong> Likes (recommendations) indicate community endorsement.
        We use <code>log(1 + likes)</code> to weight each comment, compressing the influence of viral outliers
        while still reflecting community preference.<br><br>
        <strong>2. Early comments get more likes.</strong> The first comments on an article accumulate
        disproportionately more likes simply due to visibility. We correct for this by dividing each
        comment&rsquo;s weight by <code>1 + 2.0 &times; position_rank</code>, where position_rank
        ranges from 0.0 (first comment) to 1.0 (last). This applies at most a 3&times; correction.<br><br>
        Replies (depth&nbsp;&gt;&nbsp;1) and comments with zero likes are excluded from the weighted view.
      </p>
    </div>

    <div class="story-section">
      <h2>Error bands</h2>
      <p class="story-desc">
        The shaded bands on the sentiment chart show the <strong>25th&ndash;75th percentile range</strong>
        of per-article sentiment percentages within each month. Only articles with &ge;&nbsp;5 classified
        comments are included. Wider bands indicate more variation between articles in that month;
        narrow bands mean articles that month had similar sentiment distributions.
      </p>
    </div>

    <div class="story-section">
      <h2>Geographic analysis &amp; reference data</h2>
      <p class="story-desc">
        Commenter locations are self-reported free text, normalized to US states using pattern matching
        (state names, abbreviations, &ldquo;City, ST&rdquo; patterns, and a dictionary of ~100 major US cities).
        Coverage: ~65% of comments mapped to a US state. States with fewer than 50 classified comments are excluded.<br><br>
        <strong>Education:</strong> Percentage of adults 25+ with a bachelor&rsquo;s degree or higher, from the
        US Census Bureau American Community Survey 2023 1-year estimates (Table S1501).
        DC is excluded from the scatter plot as an outlier (62.5%).<br>
        <strong>GDP per capita:</strong> Bureau of Economic Analysis (BEA), 2023 state-level GDP per capita in current dollars.
        DC is excluded from the GDP scatter plot as an outlier ($236K).
      </p>
    </div>

    <div class="story-section">
      <h2>Limitations</h2>
      <p class="story-desc">
        &bull; Single news source (NYT) with a specific readership demographic<br>
        &bull; LLM-based classification may introduce systematic biases vs. human annotators<br>
        &bull; Comment populations skew toward engaged, opinionated readers<br>
        &bull; Like counts reflect NYT readership preferences, not the general public<br>
        &bull; Early months (Nov&ndash;Dec 2022) have fewer articles, increasing variance
      </p>
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
  if (name === 'insights' && !insightsInitialized) { tryInitInsights(); }
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
const insightsDataWeighted = __INSIGHTS_DATA_WEIGHTED__;
let insightCharts = [];
let currentView = 'raw';
let showAnnotations = false;
let currentGeoView = 'sentiment';
let geoChart = null;
let usTopoReady = false;
let usTopoStates = null;
const articleCount = __ARTICLE_COUNT_NUM__;

function tryInitInsights() {
  if (!insightsInitialized && usTopoReady) {
    initInsights(insightsData);
    insightsInitialized = true;
  }
}

// Pre-fetch US topology, then init insights (since it's the default tab)
fetch('https://cdn.jsdelivr.net/npm/us-atlas@3/states-10m.json')
  .then(r => r.json())
  .then(topo => {
    usTopoStates = topojson.feature(topo, topo.objects.states).features;
    usTopoReady = true;
    tryInitInsights();
  });

function renderGeoMap(geoStates, mode) {
  if (!usTopoReady || !usTopoStates) return;

  // Build lookup by FIPS
  const byFips = {};
  geoStates.forEach(s => { if (s.fips) byFips[s.fips] = s; });

  const isFraming = mode === 'framing';
  const label = isFraming ? '% entity framing' : '% positive sentiment';

  // Sentiment: red (low pos) -> green (high pos)
  // Framing: blue (low entity/more tool) -> purple (high entity)
  const colorLo = isFraming ? [52, 152, 219]  : [231, 76, 60];
  const colorHi = isFraming ? [155, 89, 182]  : [46, 204, 113];

  // Get value range for color scaling
  const vals = geoStates.map(s => isFraming ? (s.pct_entity || 0) : s.pct_pos).filter(v => v != null);
  const vMin = Math.min(...vals);
  const vMax = Math.max(...vals);

  const chartData = usTopoStates.map(feature => {
    const fips = String(feature.id).padStart(2, '0');
    const s = byFips[fips];
    return {
      feature: feature,
      value: s ? (isFraming ? (s.pct_entity || 0) : s.pct_pos) : null,
      stateData: s || null,
    };
  });

  // Destroy previous geo chart
  if (geoChart) { geoChart.destroy(); geoChart = null; }

  const canvas = document.getElementById('chartGeo');
  if (!canvas) return;

  geoChart = new Chart(canvas, {
    type: 'choropleth',
    data: {
      labels: chartData.map(d => d.feature.properties ? d.feature.properties.name : ''),
      datasets: [{
        label: label,
        data: chartData,
        backgroundColor: (ctx) => {
          const v = ctx.raw && ctx.raw.value;
          if (v == null) return '#e8e8e8';
          const t = (v - vMin) / (vMax - vMin || 1);
          const r = Math.round(colorLo[0] + t * (colorHi[0] - colorLo[0]));
          const g = Math.round(colorLo[1] + t * (colorHi[1] - colorLo[1]));
          const b = Math.round(colorLo[2] + t * (colorHi[2] - colorLo[2]));
          return 'rgb(' + r + ',' + g + ',' + b + ')';
        },
        borderColor: '#fff',
        borderWidth: 0.5,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      showOutline: true,
      showGraticule: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: function(ctx) {
              const d = ctx.raw;
              if (!d || !d.stateData) return 'No data';
              const s = d.stateData;
              if (isFraming) {
                return [
                  s.name + ' (' + s.state + ')',
                  'Entity framing: ' + (s.pct_entity != null ? s.pct_entity + '%' : 'n/a'),
                  'n = ' + s.n.toLocaleString() + ' comments'
                ];
              }
              return [
                s.name + ' (' + s.state + ')',
                'Positive: ' + s.pct_pos + '%',
                'Negative: ' + s.pct_neg + '%',
                'n = ' + s.n.toLocaleString() + ' comments'
              ];
            }
          }
        }
      },
      scales: {
        projection: {
          axis: 'x',
          projection: 'albersUsa',
        },
        color: {
          axis: 'x',
          display: false,
          legend: { display: false },
        }
      }
    }
  });

  // Update color legend below map
  const legendEl = document.getElementById('geoLegend');
  if (legendEl) {
    const loRgb = 'rgb(' + colorLo.join(',') + ')';
    const hiRgb = 'rgb(' + colorHi.join(',') + ')';
    const loLabel = isFraming ? 'Less entity' : 'Less positive';
    const hiLabel = isFraming ? 'More entity' : 'More positive';
    legendEl.innerHTML =
      '<span>' + loLabel + '</span>' +
      '<div style="width:180px;height:12px;border-radius:6px;background:linear-gradient(to right,' + loRgb + ',' + hiRgb + ')"></div>' +
      '<span>' + hiLabel + '</span>' +
      '<span style="margin-left:12px;color:#ccc">|</span>' +
      '<span style="margin-left:12px"><span style="display:inline-block;width:12px;height:12px;border-radius:2px;background:#e8e8e8;vertical-align:middle"></span> No data</span>';
  }
}

let geoScatterCharts = [];

function linearRegression(points) {
  const n = points.length;
  if (n < 3) return { slope: 0, intercept: 0, r: 0 };
  let sx = 0, sy = 0, sxx = 0, sxy = 0, syy = 0;
  points.forEach(p => { sx += p.x; sy += p.y; sxx += p.x*p.x; sxy += p.x*p.y; syy += p.y*p.y; });
  const denom = n * sxx - sx * sx;
  const slope = (n * sxy - sx * sy) / denom;
  const intercept = (sy - slope * sx) / n;
  const mx = sx / n, my = sy / n;
  let num = 0, dx2 = 0, dy2 = 0;
  points.forEach(p => { const dx = p.x - mx, dy = p.y - my; num += dx*dy; dx2 += dx*dx; dy2 += dy*dy; });
  const r = num / (Math.sqrt(dx2 * dy2) || 1);
  return { slope, intercept, r };
}

function renderGeoScatters(geoStates, mode) {
  geoScatterCharts.forEach(c => c.destroy());
  geoScatterCharts = [];

  const isFraming = mode === 'framing';
  const yKey = isFraming ? 'pct_entity' : 'pct_pos';
  const yLabel = isFraming ? '% entity framing' : '% positive toward AI';
  const yColor = isFraming ? '#9b59b6' : '#2ecc71';
  const trendColor = isFraming ? 'rgba(155,89,182,0.4)' : 'rgba(46,204,113,0.4)';

  // Filter states with valid data
  const withEdu = geoStates.filter(s => s.bachelors_pct != null && s[yKey] != null);
  const withGdp = geoStates.filter(s => s.gdp_pc != null && s[yKey] != null);

  // Scatter 1: Education
  const eduCanvas = document.getElementById('chartGeoPolitics');
  if (eduCanvas && withEdu.length) {
    const eduPoints = withEdu.filter(s => s.state !== 'DC').map(s => ({ x: s.bachelors_pct, y: s[yKey] }));
    const eduReg = linearRegression(eduPoints);
    const eduXmin = Math.min(...eduPoints.map(p => p.x));
    const eduXmax = Math.max(...eduPoints.map(p => p.x));

    geoScatterCharts.push(new Chart(eduCanvas, {
      type: 'scatter',
      data: {
        datasets: [
          {
            label: 'States',
            data: withEdu.filter(s => s.state !== 'DC').map(s => ({ x: s.bachelors_pct, y: s[yKey], state: s.state, n: s.n })),
            backgroundColor: yColor,
            pointRadius: (ctx) => {
              const n = ctx.raw && ctx.raw.n || 50;
              return Math.max(3, Math.min(12, Math.sqrt(n / 30)));
            },
            pointHoverRadius: 8,
          },
          {
            label: 'Trend',
            data: [
              { x: eduXmin, y: eduReg.intercept + eduReg.slope * eduXmin },
              { x: eduXmax, y: eduReg.intercept + eduReg.slope * eduXmax },
            ],
            type: 'line',
            borderColor: trendColor,
            borderWidth: 2,
            borderDash: [6, 3],
            pointRadius: 0,
            fill: false,
          }
        ]
      },
      options: {
        responsive: true,
        plugins: {
          legend: { display: false },
          tooltip: {
            filter: ctx => ctx.datasetIndex === 0,
            callbacks: {
              label: ctx => ctx.raw.state + ': ' + yLabel.split('%')[0] + ctx.raw.y + '%, BA+ ' + ctx.raw.x + '% (n=' + ctx.raw.n.toLocaleString() + ')'
            }
          }
        },
        scales: {
          x: { title: { display: true, text: "% adults with bachelor's degree or higher (ACS 2023)" } },
          y: { title: { display: true, text: yLabel } }
        }
      }
    }));

    const corrEl = document.getElementById('corrPolitics');
    if (corrEl) corrEl.innerHTML = '<strong>r = ' + eduReg.r.toFixed(3) + '</strong> &middot; r&sup2; = ' + (eduReg.r * eduReg.r).toFixed(3);
  }

  // Scatter 2: GDP
  const gdpCanvas = document.getElementById('chartGeoGdp');
  const gdpFiltered = withGdp.filter(s => s.state !== 'DC');
  if (gdpCanvas && gdpFiltered.length) {
    const gdpPoints = gdpFiltered.map(s => ({ x: Math.round(s.gdp_pc / 1000), y: s[yKey] }));
    const gdpReg = linearRegression(gdpPoints);
    const gdpXmin = Math.min(...gdpPoints.map(p => p.x));
    const gdpXmax = Math.max(...gdpPoints.map(p => p.x));

    geoScatterCharts.push(new Chart(gdpCanvas, {
      type: 'scatter',
      data: {
        datasets: [
          {
            label: 'States',
            data: gdpFiltered.map(s => ({ x: Math.round(s.gdp_pc / 1000), y: s[yKey], state: s.state, n: s.n })),
            backgroundColor: yColor,
            pointRadius: (ctx) => {
              const n = ctx.raw && ctx.raw.n || 50;
              return Math.max(3, Math.min(12, Math.sqrt(n / 30)));
            },
            pointHoverRadius: 8,
          },
          {
            label: 'Trend',
            data: [
              { x: gdpXmin, y: gdpReg.intercept + gdpReg.slope * gdpXmin },
              { x: gdpXmax, y: gdpReg.intercept + gdpReg.slope * gdpXmax },
            ],
            type: 'line',
            borderColor: trendColor,
            borderWidth: 2,
            borderDash: [6, 3],
            pointRadius: 0,
            fill: false,
          }
        ]
      },
      options: {
        responsive: true,
        plugins: {
          legend: { display: false },
          tooltip: {
            filter: ctx => ctx.datasetIndex === 0,
            callbacks: {
              label: ctx => ctx.raw.state + ': ' + yLabel.split('%')[0] + ctx.raw.y + '%, GDP $' + ctx.raw.x + 'K (n=' + ctx.raw.n.toLocaleString() + ')'
            }
          }
        },
        scales: {
          x: { title: { display: true, text: 'GDP per capita ($K, 2023)' } },
          y: { title: { display: true, text: yLabel } }
        }
      }
    }));

    const corrEl = document.getElementById('corrGdp');
    if (corrEl) corrEl.innerHTML = '<strong>r = ' + gdpReg.r.toFixed(3) + '</strong> &middot; r&sup2; = ' + (gdpReg.r * gdpReg.r).toFixed(3);
  }
}

function switchGeoView(mode, btn) {
  currentGeoView = mode;
  btn.parentElement.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  const d = currentView === 'weighted' ? insightsDataWeighted : insightsData;
  const geoStates = (d.geo || {}).states || [];
  if (geoStates.length) {
    renderGeoMap(geoStates, mode);
    renderGeoScatters(geoStates, mode);
  }
}

const AI_EVENTS = [
  { month: '2022-11', label: 'ChatGPT launches', pos: 'start' },
  { month: '2023-05', label: 'Senate hearings / Hinton / AI pause letter', pos: 'end' },
  { month: '2023-12', label: 'Altman fired+rehired / Gemini', pos: 'start' },
  { month: '2024-05', label: 'GPT-4o / Google I/O', pos: 'end' },
  { month: '2025-01', label: 'DeepSeek R1', pos: 'start' },
  { month: '2025-07', label: 'GPT-5 / Chatbot spirals', pos: 'end' },
  { month: '2025-11', label: 'AI agents / regulation peak', pos: 'start' },
];

function buildAnnotations(months) {
  const annots = {};
  AI_EVENTS.forEach((ev, i) => {
    const idx = months.indexOf(ev.month);
    if (idx === -1) return;
    annots['event' + i] = {
      type: 'line',
      xMin: idx, xMax: idx,
      borderColor: 'rgba(0,0,0,0.2)',
      borderWidth: 1,
      borderDash: [4, 3],
      display: showAnnotations,
      label: {
        display: showAnnotations,
        content: ev.label,
        position: ev.pos,
        backgroundColor: 'rgba(255,255,255,0.92)',
        color: '#555',
        font: { size: 10, weight: '500' },
        borderColor: '#ccc',
        borderWidth: 1,
        borderRadius: 3,
        padding: { x: 6, y: 3 },
      }
    };
  });
  return annots;
}

function toggleAnnotations(on) {
  showAnnotations = on;
  // Update existing time-series charts (first two in the array)
  insightCharts.slice(0, 2).forEach(chart => {
    const annots = chart.options.plugins.annotation.annotations;
    Object.values(annots).forEach(a => {
      a.display = on;
      if (a.label) a.label.display = on;
    });
    chart.update();
  });
}

function initInsights(d) {
  if (!d) d = insightsData;

  // Destroy previous charts
  insightCharts.forEach(c => c.destroy());
  insightCharts = [];

  // Update subtitle
  const sub = document.getElementById('insightsSubtitle');
  if (currentView === 'weighted') {
    sub.innerHTML = 'Analysis of <strong>' + d.total.toLocaleString() + '</strong> top-level comments with likes, weighted by community endorsement &middot; November 2022 &ndash; March 2026';
  } else {
    sub.innerHTML = 'Analysis of <strong>' + d.total.toLocaleString() + '</strong> classified comments across <strong>' + articleCount.toLocaleString() + '</strong> articles &middot; November 2022 &ndash; March 2026';
  }

  // Update hint
  document.getElementById('toggleHint').textContent =
    currentView === 'weighted' ? 'Weighted by likes with position-bias correction, replies excluded' : 'Each comment counts equally';

  // Update key stats
  const o = d.overall;
  const f = d.framing_overall || {};
  document.getElementById('keyStats').innerHTML = `
    <div class="key-stat"><div class="ks-value" style="color:#e74c3c">${o.negative || 0}%</div><div class="ks-label">of comments are negative toward AI</div></div>
    <div class="key-stat"><div class="ks-value" style="color:#2ecc71">${o.positive || 0}%</div><div class="ks-label">are positive toward AI</div></div>
    <div class="key-stat"><div class="ks-value" style="color:#3498db">${f.tool || 0}%</div><div class="ks-label">frame AI as a tool</div></div>
    <div class="key-stat"><div class="ks-value" style="color:#9b59b6">${f.entity || 0}%</div><div class="ks-label">frame AI as an autonomous entity</div></div>`;

  const months = d.monthly.map(m => m.month);
  const chartDefaults = {
    responsive: true,
    plugins: { legend: { position: 'top' }, tooltip: { mode: 'index', intersect: false } },
  };
  const yLabel = currentView === 'weighted' ? '% of weighted endorsement' : '% of classified comments';

  // Chart 1: Sentiment over time (with IQR bands)
  const sentAnnotations = buildAnnotations(months);
  insightCharts.push(new Chart(document.getElementById('chartSentiment'), {
    type: 'line',
    data: {
      labels: months,
      datasets: [
        // Negative band (p75 upper bound)
        { label: '_neg_hi', data: d.monthly.map(m => m.neg_p75), borderColor: 'transparent', backgroundColor: 'rgba(231,76,60,0.13)', fill: '+1', pointRadius: 0, tension: 0.35 },
        // Negative band (p25 lower bound)
        { label: '_neg_lo', data: d.monthly.map(m => m.neg_p25), borderColor: 'transparent', fill: false, pointRadius: 0, tension: 0.35 },
        // Main negative line
        { label: 'Negative', data: d.monthly.map(m => m.pct_neg), borderColor: '#e74c3c', backgroundColor: 'transparent', fill: false, tension: 0.35, pointRadius: 2, borderWidth: 2 },
        // Neutral
        { label: 'Neutral', data: d.monthly.map(m => m.pct_neu), borderColor: '#95a5a6', backgroundColor: 'transparent', fill: false, tension: 0.35, pointRadius: 2, borderWidth: 2 },
        // Positive band (p75 upper bound)
        { label: '_pos_hi', data: d.monthly.map(m => m.pos_p75), borderColor: 'transparent', backgroundColor: 'rgba(46,204,113,0.13)', fill: '+1', pointRadius: 0, tension: 0.35 },
        // Positive band (p25 lower bound)
        { label: '_pos_lo', data: d.monthly.map(m => m.pos_p25), borderColor: 'transparent', fill: false, pointRadius: 0, tension: 0.35 },
        // Main positive line
        { label: 'Positive', data: d.monthly.map(m => m.pct_pos), borderColor: '#2ecc71', backgroundColor: 'transparent', fill: false, tension: 0.35, pointRadius: 2, borderWidth: 2 },
      ]
    },
    options: { ...chartDefaults,
      plugins: {
        ...chartDefaults.plugins,
        annotation: { annotations: sentAnnotations },
        legend: { position: 'top', labels: { filter: item => !item.text.startsWith('_') } },
      },
      scales: {
        y: { min: 0, max: 100, ticks: { callback: v => v + '%' }, title: { display: true, text: yLabel } },
        x: { ticks: { maxTicksLimit: 14 } }
    }}
  }));

  // Chart 2: Framing over time (with IQR bands)
  const framAnnotations = buildAnnotations(months);
  insightCharts.push(new Chart(document.getElementById('chartFraming'), {
    type: 'line',
    data: {
      labels: months,
      datasets: [
        // Tool band
        { label: '_tool_hi', data: d.monthly.map(m => m.tool_p75), borderColor: 'transparent', backgroundColor: 'rgba(52,152,219,0.13)', fill: '+1', pointRadius: 0, tension: 0.35 },
        { label: '_tool_lo', data: d.monthly.map(m => m.tool_p25), borderColor: 'transparent', fill: false, pointRadius: 0, tension: 0.35 },
        // Main tool line
        { label: 'Tool',   data: d.monthly.map(m => m.pct_tool),   borderColor: '#3498db', backgroundColor: 'transparent', fill: false, tension: 0.35, pointRadius: 2, borderWidth: 2 },
        // Entity band
        { label: '_ent_hi', data: d.monthly.map(m => m.entity_p75), borderColor: 'transparent', backgroundColor: 'rgba(155,89,182,0.13)', fill: '+1', pointRadius: 0, tension: 0.35 },
        { label: '_ent_lo', data: d.monthly.map(m => m.entity_p25), borderColor: 'transparent', fill: false, pointRadius: 0, tension: 0.35 },
        // Main entity line
        { label: 'Entity', data: d.monthly.map(m => m.pct_entity), borderColor: '#9b59b6', backgroundColor: 'transparent', fill: false, tension: 0.35, pointRadius: 2, borderWidth: 2 },
      ]
    },
    options: { ...chartDefaults,
      plugins: {
        ...chartDefaults.plugins,
        annotation: { annotations: framAnnotations },
        legend: { position: 'top', labels: { filter: item => !item.text.startsWith('_') } },
      },
      scales: {
        y: { min: 0, max: 100, ticks: { callback: v => v + '%' }, title: { display: true, text: '% of tool+entity framed comments' } },
        x: { ticks: { maxTicksLimit: 14 } }
    }}
  }));

  // Chart 3: Sentiment distribution conditioned on framing (with IQR whiskers)
  const tool   = d.sbf.tool   || {};
  const entity = d.sbf.entity || {};
  const tb = (d.sbf_bands || {}).tool || {};
  const eb = (d.sbf_bands || {}).entity || {};

  // Helper to get [p25, p75] for a framing+sentiment combo
  const getBand = (bands, sent) => bands[sent] ? [bands[sent].p25, bands[sent].p75] : [null, null];

  // Custom plugin to draw IQR whiskers on bars
  const errorBarPlugin = {
    id: 'errorBars',
    afterDraw(chart) {
      const ctx = chart.ctx;
      chart.data.datasets.forEach((dataset, di) => {
        if (!dataset.errorBars) return;
        const meta = chart.getDatasetMeta(di);
        dataset.errorBars.forEach((eb, i) => {
          if (!eb || eb[0] == null) return;
          const bar = meta.data[i];
          if (!bar) return;
          const x = bar.x;
          const yLo = chart.scales.y.getPixelForValue(eb[0]);
          const yHi = chart.scales.y.getPixelForValue(eb[1]);
          const w = 6;
          ctx.save();
          ctx.strokeStyle = 'rgba(0,0,0,0.5)';
          ctx.lineWidth = 1.5;
          // Vertical line
          ctx.beginPath(); ctx.moveTo(x, yLo); ctx.lineTo(x, yHi); ctx.stroke();
          // Top cap
          ctx.beginPath(); ctx.moveTo(x - w, yHi); ctx.lineTo(x + w, yHi); ctx.stroke();
          // Bottom cap
          ctx.beginPath(); ctx.moveTo(x - w, yLo); ctx.lineTo(x + w, yLo); ctx.stroke();
          ctx.restore();
        });
      });
    }
  };

  insightCharts.push(new Chart(document.getElementById('chartSbf'), {
    type: 'bar',
    data: {
      labels: ['Tool framing', 'Entity framing'],
      datasets: [
        { label: 'Negative',   data: [tool.negative || 0, entity.negative || 0],   backgroundColor: '#e74c3c', borderRadius: 4,
          errorBars: [getBand(tb, 'negative'), getBand(eb, 'negative')] },
        { label: 'Neutral',    data: [tool.neutral || 0, entity.neutral || 0],     backgroundColor: '#95a5a6', borderRadius: 4,
          errorBars: [getBand(tb, 'neutral'), getBand(eb, 'neutral')] },
        { label: 'Positive',   data: [tool.positive || 0, entity.positive || 0],   backgroundColor: '#2ecc71', borderRadius: 4,
          errorBars: [getBand(tb, 'positive'), getBand(eb, 'positive')] },
        { label: 'Irrelevant', data: [tool.irrelevant || 0, entity.irrelevant || 0], backgroundColor: '#f39c12', borderRadius: 4 },
      ]
    },
    options: { ...chartDefaults, scales: {
      y: { min: 0, max: 100, ticks: { callback: v => v + '%' }, title: { display: true, text: '% of comments within framing group' } }
    }},
    plugins: [errorBarPlugin]
  }));

  renderQuotes('quotes-negative', d.examples.negative       || [], 'negative');
  renderQuotes('quotes-tool',     d.examples.tool            || [], 'tool');
  renderQuotes('quotes-entity',   d.examples.entity_negative || [], 'entity');
  renderQuotes('quotes-positive', d.examples.positive        || [], 'positive');

  // Chart 5: Geography (choropleth)
  const geo = d.geo || {};
  const geoStates = geo.states || [];
  const geoDesc = document.getElementById('geoDesc');
  if (geoStates.length && geoDesc) {
    geoDesc.innerHTML = 'Sentiment toward AI by US state, based on commenter-reported locations. ' +
      '<strong>' + (geo.coverage_pct || 0) + '%</strong> of comments mapped to a US state (' +
      (geo.mapped || 0).toLocaleString() + ' comments). States with fewer than 50 comments excluded. ' +
      'Hover over a state for details.';
  }
  if (geoStates.length && usTopoReady) {
    renderGeoMap(geoStates, currentGeoView);
    renderGeoScatters(geoStates, currentGeoView);
  }

  // Preserve annotation checkbox state
  document.getElementById('annotationsToggle').checked = showAnnotations;
}

function switchView(mode, btn) {
  currentView = mode;
  document.querySelectorAll('.toggle-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  const d = mode === 'weighted' ? insightsDataWeighted : insightsData;
  initInsights(d);
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
    insights_weighted = build_insights_data_weighted(articles)

    # Write data.json
    data_path = DOCS_DIR / "data.json"
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

    # Inject both datasets into HTML
    insights_json = json.dumps(insights, ensure_ascii=True).replace("</", "<\\/")
    insights_w_json = json.dumps(insights_weighted, ensure_ascii=True).replace("</", "<\\/")

    html = INDEX_HTML
    html = html.replace("__INSIGHTS_DATA_WEIGHTED__", insights_w_json)
    html = html.replace("__INSIGHTS_DATA__", insights_json)
    html = html.replace("__ARTICLE_COUNT_NUM__", str(len(articles)))

    html_path = DOCS_DIR / "index.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    data_mb = data_path.stat().st_size / (1024 * 1024)
    print(f"Built docs/index.html + docs/data.json ({data_mb:.1f} MB)")
    print(f"  {len(articles)} articles, {num_classified} classified comments")


if __name__ == "__main__":
    main()
