#!/usr/bin/env python3
"""
GitHub Actions hotspot updater for JK养虾.
Multi-platform scanner: Firecrawl, DuckDuckGo, Toutiao, TianAPI (Douyin/WeChat/Toutiao).
Updates articles.html and hotspots-latest.json.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
SITE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# AI-related filter keywords for platform hotspots
AI_FILTER_KEYWORDS = [
    "AI", "人工智能", "大模型", "GPT", "Claude", "Gemini", "DeepSeek",
    "OpenAI", "Anthropic", "Google", "机器人", "算法", "芯片", "英伟达",
    "NVIDIA", "智能", "自动驾驶", "Agent", "AGI", "千问", "豆包",
    "Sora", "Copilot", "ChatGPT", "百度", "文心", "通义", "字节",
    "科技", "数据", "算力", "训练", "推理", "Llama", "开源模型",
]


def search_duckduckgo(keywords, max_results=10):
    """Search using DuckDuckGo."""
    results = []
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            for kw in keywords:
                try:
                    for r in ddgs.news(kw, max_results=max_results, region="cn-zh"):
                        results.append({
                            "title": r.get("title", ""),
                            "url": r.get("url", ""),
                            "source": r.get("source", ""),
                            "body": r.get("body", ""),
                            "keyword": kw,
                        })
                except Exception as e:
                    print(f"  [warn] keyword '{kw}' failed: {e}")
    except ImportError:
        print("[warn] duckduckgo_search not available")
    return results


def search_firecrawl(keywords):
    """Search using Firecrawl API if key is available."""
    api_key = os.environ.get("FIRECRAWL_API_KEY", "")
    if not api_key:
        return []

    import requests
    results = []
    for kw in keywords:
        try:
            resp = requests.post(
                "https://api.firecrawl.dev/v1/search",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"query": kw, "limit": 8},
                timeout=30,
            )
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("data", []):
                    results.append({
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "source": item.get("metadata", {}).get("sourceURL", ""),
                        "body": item.get("markdown", "")[:200],
                        "keyword": kw,
                    })
        except Exception as e:
            print(f"  [warn] firecrawl '{kw}' failed: {e}")
    return results


def is_ai_related(text):
    """Check if text is AI-related based on filter keywords."""
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in AI_FILTER_KEYWORDS)


def search_toutiao_hotboard():
    """Fetch Toutiao hot board (free, no API key needed)."""
    import requests
    results = []
    try:
        resp = requests.get(
            "https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            timeout=10,
        )
        data = resp.json()
        if data.get("status") == "success":
            for item in data.get("data", []):
                title = item.get("Title", "")
                if is_ai_related(title):
                    results.append({
                        "title": title,
                        "url": item.get("Url", ""),
                        "source": "今日头条",
                        "body": "",
                        "keyword": "toutiao-hotboard",
                        "platform": "toutiao",
                        "hot_value": item.get("HotValue", 0),
                    })
            print(f"  [toutiao] {len(results)} AI-related items from {len(data.get('data', []))} total")
    except Exception as e:
        print(f"  [warn] toutiao hotboard failed: {e}")
    return results


def search_tianapi(endpoint, name, api_key):
    """Generic TianAPI searcher for different platforms."""
    import requests
    results = []
    try:
        resp = requests.get(
            f"https://apis.tianapi.com/{endpoint}/index",
            params={"key": api_key},
            timeout=10,
        )
        data = resp.json()
        if data.get("code") == 200:
            news_list = data.get("result", {}).get("list", [])
            if not news_list:
                news_list = data.get("result", {}).get("newslist", [])
            for item in news_list:
                title = item.get("title", "") or item.get("word", "") or item.get("digest", "")
                if title and is_ai_related(title):
                    results.append({
                        "title": title,
                        "url": item.get("url", "") or item.get("mobileUrl", ""),
                        "source": name,
                        "body": item.get("digest", "") or item.get("description", ""),
                        "keyword": f"tianapi-{endpoint}",
                        "platform": name,
                        "hot_value": item.get("hotnum", 0) or item.get("hotvalue", 0),
                    })
            print(f"  [{name}] {len(results)} AI-related items from {len(news_list)} total")
        else:
            print(f"  [warn] tianapi {name}: code={data.get('code')}, msg={data.get('msg', '')}")
    except Exception as e:
        print(f"  [warn] tianapi {name} failed: {e}")
    return results


def search_tianapi_all():
    """Search all TianAPI endpoints if key is available."""
    api_key = os.environ.get("TIANAPI_KEY", "")
    if not api_key:
        print("[info] TIANAPI_KEY not set, skipping TianAPI sources")
        return []

    results = []
    # Douyin hotspot
    results.extend(search_tianapi("douyinhot", "抖音", api_key))
    # WeChat hotspot
    results.extend(search_tianapi("wxhottopic", "微信", api_key))

    print(f"[info] TianAPI total AI-related results: {len(results)}")
    return results


def deduplicate(items):
    """Remove duplicate titles."""
    seen = set()
    unique = []
    for item in items:
        title_key = re.sub(r'\s+', '', item["title"])[:20]
        if title_key and title_key not in seen:
            seen.add(title_key)
            unique.append(item)
    return unique


def score_and_rank(items):
    """Score items and return top 12."""
    hot_terms = ["GPT", "Claude", "Gemini", "DeepSeek", "OpenAI", "Anthropic", "Google",
                 "融资", "发布", "开源", "突破", "争议", "泄露", "Agent", "AGI",
                 "字节", "百度", "阿里", "腾讯", "华为", "豆包"]
    scored = []
    for item in items:
        score = 7
        text = item["title"] + item.get("body", "")
        for term in hot_terms:
            if term.lower() in text.lower():
                score += 0.5
        score = min(10, round(score))

        category = "hotspot"
        analysis_terms = ["分析", "报告", "研究", "预测", "评论", "争议", "比较", "comparison"]
        if any(t in text.lower() for t in analysis_terms):
            category = "analysis"

        # Platform hotspots get a bonus for having real engagement data
        platform = item.get("platform", "")
        hot_value = item.get("hot_value", 0)
        if platform and hot_value:
            # Normalize: very high hot_value (>1M) gets +1, moderate (>100K) gets +0.5
            if hot_value > 1000000:
                score += 1
            elif hot_value > 100000:
                score += 0.5
        score = min(10, round(score))

        source = item.get("source", "")
        if "/" in source:
            source = source.split("/")[-1]
        if not source:
            source = item.get("keyword", "AI")

        entry = {
            "title": item["title"][:30],
            "heat_score": score,
            "category": category,
            "source": source[:20],
        }
        if platform:
            entry["platform"] = platform
        scored.append(entry)

    scored.sort(key=lambda x: x["heat_score"], reverse=True)
    return scored[:12]


def generate_hotspot_cards_html(hotspots):
    """Generate HTML cards for hotspots."""
    cards = []
    for h in hotspots:
        score = h["heat_score"]
        if score >= 10:
            heat_class, badge_class, badge_icon = "heat-10", "score-10", "&#x1F525;"
        elif score >= 9:
            heat_class, badge_class, badge_icon = "heat-9", "score-9", "&#x1F31F;"
        else:
            heat_class, badge_class, badge_icon = "heat-8", "score-8", "&#x26A1;"

        cat_label = {"hotspot": "热点快讯", "analysis": "深度分析"}.get(h["category"], "热点快讯")
        cat_class = f"cat-{h['category']}"

        card = (
            f'    <div class="hotspot-card {heat_class}" data-cat="{h["category"]}">\n'
            f'      <div class="heat-badge {badge_class}">{badge_icon} {score}</div>\n'
            f'      <h3 class="hotspot-title">{h["title"]}</h3>\n'
            f'      <p class="hotspot-summary"></p>\n'
            f'      <div class="hotspot-meta">\n'
            f'        <span class="hotspot-category {cat_class}">{cat_label}</span>\n'
            f'        <span class="hotspot-source">{h["source"]}</span>\n'
            f'      </div>\n'
            f'    </div>'
        )
        cards.append(card)
    return "\n\n".join(cards)


def update_articles_html(hotspots, date_str):
    """Update articles.html with new hotspot cards."""
    articles_path = os.path.join(SITE_DIR, "articles.html")
    if not os.path.exists(articles_path):
        print(f"[warn] articles.html not found: {articles_path}")
        return False

    with open(articles_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Update date header
    content = re.sub(
        r'<div class="date-header"><span class="date-dot dot-orange"></span> [\d-]+ 热点</div>',
        f'<div class="date-header"><span class="date-dot dot-orange"></span> {date_str} 热点</div>',
        content
    )

    # Replace hotspot-grid content
    new_cards = generate_hotspot_cards_html(hotspots)
    grid_start = content.find('<div class="hotspot-grid" id="hotspot-grid">')
    if grid_start != -1:
        grid_content_start = content.index('>', grid_start) + 1
        depth = 1
        pos = grid_content_start
        while depth > 0 and pos < len(content):
            next_open = content.find('<div', pos)
            next_close = content.find('</div>', pos)
            if next_close == -1:
                break
            if next_open != -1 and next_open < next_close:
                depth += 1
                pos = next_open + 4
            else:
                depth -= 1
                if depth == 0:
                    grid_end = next_close
                pos = next_close + 6
        content = content[:grid_content_start] + "\n\n" + new_cards + "\n\n  " + content[grid_end:]

    with open(articles_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[ok] articles.html updated with {len(hotspots)} hotspots")
    return True


def save_hotspots_json(hotspots, date_str):
    """Save hotspots as JSON (latest + daily archive)."""
    # Save latest
    json_path = os.path.join(SITE_DIR, "hotspots-latest.json")
    data = {
        "date": date_str,
        "updated_at": datetime.now(CST).isoformat(),
        "count": len(hotspots),
        "hotspots": hotspots,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[ok] hotspots-latest.json saved")

    # Save daily archive
    archive_dir = os.path.join(SITE_DIR, "hotspots-archive")
    os.makedirs(archive_dir, exist_ok=True)
    archive_path = os.path.join(archive_dir, f"hotspots-{date_str}.json")
    with open(archive_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[ok] archived to hotspots-archive/hotspots-{date_str}.json")

    # Update index of all archived dates
    update_archive_index(archive_dir)


def update_archive_index(archive_dir):
    """Generate hotspots-archive/index.json listing all available dates."""
    dates = []
    for fname in sorted(os.listdir(archive_dir), reverse=True):
        if fname.startswith("hotspots-") and fname.endswith(".json") and fname != "index.json":
            date = fname.replace("hotspots-", "").replace(".json", "")
            dates.append(date)
    index_path = os.path.join(archive_dir, "index.json")
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump({"dates": dates}, f, ensure_ascii=False, indent=2)
    print(f"[ok] archive index updated: {len(dates)} dates")


def main():
    date_str = datetime.now(CST).strftime("%Y-%m-%d")
    print(f"=== JK养虾 Hotspot Update: {date_str} ===")

    keywords_cn = ["AI最新进展 2026", "OpenAI GPT最新消息", "中国AI 人工智能新闻"]
    keywords_en = ["OpenAI GPT Claude latest news", "AI startup funding 2026", "DeepSeek Gemini AI news"]

    all_results = []

    # Source 1: Toutiao hot board (free, always available)
    print("\n--- Toutiao Hot Board ---")
    toutiao_results = search_toutiao_hotboard()
    all_results.extend(toutiao_results)

    # Source 2: TianAPI multi-platform (Douyin, WeChat, Toutiao)
    print("\n--- TianAPI Multi-Platform ---")
    tianapi_results = search_tianapi_all()
    all_results.extend(tianapi_results)

    # Source 3: Firecrawl keyword search
    print("\n--- Firecrawl Search ---")
    firecrawl_results = search_firecrawl(keywords_cn + keywords_en)
    all_results.extend(firecrawl_results)

    # Source 4: DuckDuckGo fallback (only if other sources insufficient)
    if len(all_results) < 8:
        print("\n--- DuckDuckGo Fallback ---")
        ddg_results = search_duckduckgo(keywords_cn + keywords_en, max_results=8)
        all_results.extend(ddg_results)
    else:
        print(f"\n[info] Skipping DuckDuckGo (already have {len(all_results)} results)")

    print(f"\n[info] Total raw results: {len(all_results)}")

    unique = deduplicate(all_results)
    print(f"[info] After dedup: {len(unique)}")

    if not unique:
        print("[warn] No results found, skipping update")
        return

    hotspots = score_and_rank(unique)
    print(f"[info] Final hotspots: {len(hotspots)}")

    # Show summary
    for i, h in enumerate(hotspots, 1):
        plat = h.get("platform", "search")
        print(f"  #{i} [{h['heat_score']}] {h['title']} ({h['source']}/{plat})")

    update_articles_html(hotspots, date_str)
    save_hotspots_json(hotspots, date_str)

    print("=== Hotspot update complete ===")


if __name__ == "__main__":
    main()
