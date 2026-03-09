#!/usr/bin/env python3
"""
JK养虾 Auto-Publish Pipeline v4.
Produces 4 articles daily:
  - 3 AI hotspot deep-dive articles (JSON→rich dark-theme HTML→screenshot)
  - 1 龙虾养成日记 (diary, posted to website)
All 4 pushed to WeChat draft box. Each gets a unique cover image.
"""
import json
import math
import os
import re
import sys
import tempfile
from datetime import datetime, timezone, timedelta

import requests

CST = timezone(timedelta(hours=8))
SITE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_START_DATE = datetime(2026, 3, 3, tzinfo=CST)

# --- Config from environment ---
VOLCENGINE_API_KEY = os.environ.get("VOLCENGINE_API_KEY", "")
VOLCENGINE_BASE_URL = "https://ark.cn-beijing.volces.com/api/coding/v3"
VOLCENGINE_MODEL = "ark-code-latest"

WX_APPID = os.environ.get("WX_APPID", "")
WX_APPSECRET = os.environ.get("WX_APPSECRET", "")
WX_COVER_MEDIA_ID = os.environ.get("WX_COVER_MEDIA_ID", "")

WX_IMAGE_WIDTH = 375  # Mobile viewport for screenshot mode

# Cover image color themes for variety
COVER_THEMES = [
    {"bg": "linear-gradient(135deg, #0f2027, #203a43, #2c5364)", "accent": "#00d2ff", "text": "#fff"},
    {"bg": "linear-gradient(135deg, #1a1a2e, #16213e, #0f3460)", "accent": "#e94560", "text": "#fff"},
    {"bg": "linear-gradient(135deg, #0d1b2a, #1b2838, #2d4059)", "accent": "#f5a623", "text": "#fff"},
]


# ============================================================
# Helpers
# ============================================================
def get_day_number():
    now = datetime.now(CST)
    return (now.date() - PROJECT_START_DATE.date()).days + 1

def get_date_str():
    return datetime.now(CST).strftime("%Y-%m-%d")

def get_date_cn():
    now = datetime.now(CST)
    return f"{now.year}年{now.month}月{now.day}日"

def load_hotspots():
    json_path = os.path.join(SITE_DIR, "hotspots-latest.json")
    if not os.path.exists(json_path):
        return []
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f).get("hotspots", [])

def call_llm(system_prompt, user_prompt, max_tokens=4000, temperature=0.7):
    if not VOLCENGINE_API_KEY:
        print("[ERROR] VOLCENGINE_API_KEY not set")
        return None
    resp = requests.post(
        f"{VOLCENGINE_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {VOLCENGINE_API_KEY}", "Content-Type": "application/json"},
        json={
            "model": VOLCENGINE_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        },
        timeout=120,
    )
    data = resp.json()
    if "choices" in data:
        return data["choices"][0]["message"]["content"]
    print(f"[ERROR] LLM failed: {json.dumps(data, ensure_ascii=False)[:300]}")
    return None

def clean_json(text):
    text = re.sub(r'^```(?:json)?\s*\n?', '', text.strip())
    return re.sub(r'\n?```\s*$', '', text)

def clean_html(text):
    text = re.sub(r'^```html?\s*\n?', '', text.strip())
    return re.sub(r'\n?```\s*$', '', text)


# Tags that indicate complex visuals needing screenshot mode
COMPLEX_VIZ_TAGS = [
    "data-table", "ranking-chart", "stat-cards", "stat-card",
    "timeline", "highlight-box", "rank-item", "rank-bar",
]

def has_complex_visuals(html_content):
    """Check if HTML content contains complex data viz that needs screenshot rendering."""
    content_lower = html_content.lower()
    for tag in COMPLEX_VIZ_TAGS:
        if f'class="{tag}"' in content_lower or f"class='{tag}'" in content_lower:
            return True
    # Also check for <table> elements
    if "<table" in content_lower:
        return True
    return False


def build_wechat_text_html(title, date_cn, content, tag="AI深度解读"):
    """Build inline-styled HTML for WeChat text-mode articles (no screenshot needed)."""
    # WeChat strips <style> blocks, so all styles must be inline
    # Convert semantic HTML to inline-styled HTML for WeChat
    html = content

    # h2 headings
    html = re.sub(
        r'<h2>(.*?)</h2>',
        r'<h2 style="font-size:20px;font-weight:700;color:#1a1a1a;margin:32px 0 16px;padding-bottom:8px;border-bottom:2px solid #0077aa;">\1</h2>',
        html
    )

    # paragraphs
    html = re.sub(
        r'<p>(.*?)</p>',
        r'<p style="margin-bottom:16px;font-size:16px;color:#333;line-height:1.9;">\1</p>',
        html, flags=re.DOTALL
    )

    # strong
    html = re.sub(
        r'<strong>(.*?)</strong>',
        r'<strong style="color:#1a1a1a;font-weight:700;">\1</strong>',
        html
    )

    # blockquote
    html = re.sub(
        r'<blockquote>(.*?)</blockquote>',
        r'<blockquote style="border-left:4px solid #0077aa;background:#e8f4f8;padding:16px 20px;margin:20px 0;border-radius:0 8px 8px 0;font-size:15px;color:#555;">\1</blockquote>',
        html, flags=re.DOTALL
    )

    # ul/li
    html = re.sub(r'<ul>', '<ul style="margin:12px 0 20px 24px;">', html)
    html = re.sub(
        r'<li>(.*?)</li>',
        r'<li style="margin-bottom:8px;font-size:16px;color:#333;line-height:1.8;">\1</li>',
        html, flags=re.DOTALL
    )

    # hr
    html = html.replace('<hr>', '<hr style="border:none;border-top:1px solid #e8e8e5;margin:32px 0;">')
    html = html.replace('<hr/>', '<hr style="border:none;border-top:1px solid #e8e8e5;margin:32px 0;">')
    html = html.replace('<hr />', '<hr style="border:none;border-top:1px solid #e8e8e5;margin:32px 0;">')

    # cta-box
    html = re.sub(
        r'<div class="cta-box">(.*?)</div>',
        r'<div style="background:#fff;border:2px solid #0077aa;border-radius:12px;padding:24px 20px;margin:28px 0;text-align:center;">\1</div>',
        html, flags=re.DOTALL
    )

    # Wrap with header
    header = (
        f'<div style="margin-bottom:28px;padding-bottom:16px;border-bottom:1px solid #e8e8e5;">'
        f'<span style="display:inline-block;font-size:12px;color:#0077aa;background:#e8f4f8;padding:3px 12px;border-radius:4px;margin-bottom:12px;">{tag}</span>'
        f'<h1 style="font-size:24px;font-weight:700;color:#1a1a1a;line-height:1.4;margin-bottom:10px;">{title}</h1>'
        f'<p style="font-size:13px;color:#888;">JK养虾 · {date_cn} · Openclaw Agent</p>'
        f'</div>'
    )

    footer = (
        '<div style="margin-top:36px;padding-top:16px;border-top:1px solid #e8e8e5;text-align:center;">'
        '<p style="font-size:13px;color:#888;">关注公众号「JK养虾」，每天一篇AI深度解读</p>'
        '</div>'
    )

    return header + html + footer


# ============================================================
# Step 1: Select topics — pick top 3 hotspots for separate articles
# ============================================================
def select_topics(hotspots):
    """Pick the 3 most important hotspots as individual article topics."""
    system_prompt = """你是「JK养虾」公众号的选题编辑。从今日AI热点中选出3个最值得深度解读的话题。

选择标准：
- 优先选择有具体事件/数据/人物的热点（不选空泛趋势类）
- 3个话题之间要有差异性（不要选太相似的）
- 每个话题要能撑起一篇1500-2000字的深度文章

输出JSON数组（不要代码块标记）：
[
  {
    "topic": "话题简述（20字以内）",
    "title": "文章标题（15字以内，口语化有悬念）",
    "angle": "独特切入角度（不是简单复述新闻，而是提供独特视角/分析）",
    "data_visual": "适合的可视化类型：comparison_table/timeline/ranking/stat_cards/highlight_box",
    "hotspot_index": 0
  },
  ...
]"""

    hotspot_lines = []
    for i, h in enumerate(hotspots[:10], 0):
        plat = h.get("platform", "搜索")
        hotspot_lines.append(f"{i}. [{h['heat_score']}分] {h['title']} (来源:{h['source']}/{plat})")

    user_prompt = f"今日AI热点：\n" + "\n".join(hotspot_lines) + "\n\n请选出3个最佳深度话题。"

    result = call_llm(system_prompt, user_prompt, max_tokens=1000, temperature=0.7)
    if not result:
        return None
    try:
        return json.loads(clean_json(result))
    except json.JSONDecodeError as e:
        print(f"[warn] Topic selection parse failed: {e}")
        print(f"[warn] Raw: {result[:200]}")
        return None


# ============================================================
# Step 2: Generate single-topic deep-dive article (V4 JSON mode)
# ============================================================
HOTSPOT_ARTICLE_SYSTEM_V4 = """你是「JK养虾」公众号的主笔。公众号定位：用通俗易懂的方式，帮普通人看懂AI圈大事。

## 核心原则
- 本文只聚焦一个AI热点话题，写深写透
- 结构：核心要点 → 关键数据 → 事件背景/对比分析 → 对普通人的影响 → 实用建议
- 读者读完要有「学到东西了」的感觉
- 必须包含具体数字、事实、对比数据（不许空洞描述）

## 写作风格
- 口语化，像跟朋友面对面聊
- 用**加粗**标注核心信息
- 禁止：「首先其次最后」「总而言之」「值得注意的是」
- 禁止：排比句、四字成语堆砌
- 技术概念翻译成人话

## 输出格式
输出纯JSON（不要代码块标记），结构如下：
{
  "title": "文章标题（15字以内）",
  "subtitle": "一句话副标题，概括文章核心观点（30字以内）",
  "sections": [
    // 必须包含以下section类型的组合（5-8个section）：

    // 核心要点（必须有，放在最前面）
    {"type": "key_takeaways", "items": ["要点1（含**加粗**关键词）", "要点2", "要点3"]},

    // 关键数字（必须有）
    {"type": "stat_cards", "cards": [{"number": "数字", "label": "说明"}, ...]},

    // 正文段落（可以有多个text section）
    {"type": "text", "tag": "章节编号标签", "title": "章节标题", "content": "正文内容，段落之间用\\n\\n分隔，支持**加粗**"},

    // 对比表格（推荐，适合产品对比/参数对比）
    {"type": "comparison_table", "title": "表格标题",
     "headers": ["列名1", "列名2", "列名3"],
     "rows": [
       {"cells": ["文本", {"text": "带标签", "badge": "green"}, "普通文本"], "highlight": false},
       {"cells": ["高亮行", "内容", "内容"], "highlight": true}
     ],
     "note": "表格注释说明"},

    // 时间线（适合事件回顾）
    {"type": "timeline", "tag": "标签", "title": "时间线标题",
     "events": [{"date": "日期", "title": "事件标题", "desc": "事件描述", "color": "blue/amber/green/red"}]},

    // 重点提示框
    {"type": "callout", "text": "提示内容，支持**加粗**", "variant": "amber/blue"},

    // 排名条形图（适合评分/排名对比）
    {"type": "ranking", "title": "排名标题",
     "items": [{"label": "名称", "value": 85, "display": "85分"}]},

    // 柱状图（适合数据趋势对比）
    {"type": "bar_chart", "title": "图表标题",
     "categories": ["类别1", "类别2"],
     "series": [{"name": "系列名", "data": [10, 20]}]},

    // 行动建议卡片（推荐，放在末尾前）
    {"type": "action_cards", "tag": "标签", "title": "行动建议标题",
     "cards": [{"title": "建议标题", "desc": "建议描述"}]},

    // 利弊分析（可选）
    {"type": "pros_cons", "title": "标题",
     "pros": ["利好1", "利好2"], "cons": ["风险1", "风险2"]},

    // 总结（可选）
    {"type": "conclusion", "title": "总结标题", "text": "总结内容"},

    // CTA（必须有，放最后）
    {"type": "cta", "text": "**关注JK养虾**，每天一篇AI深度解读，不错过任何大事"}
  ]
}

## 要求
- sections数组5-8个元素
- 必须有：key_takeaways、stat_cards、至少1个text、cta
- 推荐有：comparison_table或ranking、action_cards
- 数据可视化至少2个（stat_cards + table/ranking/bar_chart/timeline任选1）
- 所有文本内容用**加粗**标注关键信息
- badge值只能是：green/amber/red/blue
- timeline的color值只能是：blue/amber/green/red"""


def fallback_from_html(html_content, title="AI热点解读"):
    """If LLM returns HTML instead of JSON, wrap it into a minimal article dict."""
    return {
        "title": title,
        "subtitle": "AI热点深度解读",
        "sections": [
            {"type": "text", "content": html_content},
            {"type": "cta", "text": "**关注JK养虾**，每天一篇AI深度解读"},
        ]
    }


def generate_hotspot_article(topic, hotspots, day_num, date_cn):
    """Generate a single deep-dive article for one topic. Returns dict (JSON) or None."""
    idx = topic.get("hotspot_index", 0)
    hotspot = hotspots[idx] if idx < len(hotspots) else hotspots[0]

    user_prompt = f"""请围绕以下话题，写一篇深度解读文章（JSON格式输出）。

话题：{topic['topic']}
标题：{topic['title']}
独特角度：{topic['angle']}
推荐数据可视化：{topic['data_visual']}
热点原文：{hotspot['title']}（来源：{hotspot.get('source', '')}）
日期：{date_cn}

要求：
- 只聚焦这一个话题，写深写透
- sections数组5-8个元素，必须包含key_takeaways、stat_cards、至少1个text、cta
- 至少2个数据可视化section
- 结尾有action_cards给读者实用建议
- 输出纯JSON，不要代码块标记"""

    result = call_llm(HOTSPOT_ARTICLE_SYSTEM_V4, user_prompt, max_tokens=4000, temperature=0.72)
    if not result:
        return None

    # Try parsing as JSON
    try:
        article_data = json.loads(clean_json(result))
        if isinstance(article_data, dict) and "sections" in article_data:
            print(f"    [ok] JSON parsed: {len(article_data['sections'])} sections")
            return article_data
    except json.JSONDecodeError:
        pass

    # Fallback: treat as HTML
    print(f"    [warn] JSON parse failed, using fallback")
    html = clean_html(result)
    return fallback_from_html(html, topic.get("title", "AI热点解读"))


# ============================================================
# Step 3: Generate diary article
# ============================================================
def generate_diary(day_num, date_cn, hotspots):
    """Generate the daily diary entry."""
    day_str = f"{day_num:03d}"
    hotspot_summary = "、".join([h['title'][:15] for h in hotspots[:5]])

    system_prompt = f"""你是「JK养虾」公众号的龙虾COO Agent，写龙虾养成日记Day {day_str}。

## 身份
- 你是AI Agent（龙虾COO），老板是人类创业者
- 你用Openclaw多Agent团队做自动化内容生产
- 项目第{day_num}天（起始日2026年3月3日）

## 日记内容
日记记录今天的工作进展，包括：
- 今天追踪了哪些AI热点（简要提及，不展开）
- 自动化系统做了什么（热点抓取、文章生成、推送等）
- 遇到的技术问题和解决方案
- 对项目进度的反思
- 龙虾养殖的类比和感悟

## 风格
- 日记体，第一人称，像写给自己看的工作笔记
- 轻松幽默，偶尔自嘲
- 500-800字即可，短小精悍
- 用<strong>加粗</strong>标注2-3处重点

## 输出
纯HTML片段，用p/strong/blockquote/hr。禁止markdown。"""

    user_prompt = f"""今天是{date_cn}，Day {day_num}。
今天追踪到的热点包括：{hotspot_summary}
请写今天的龙虾养成日记。"""

    result = call_llm(system_prompt, user_prompt, max_tokens=2000, temperature=0.78)
    if not result:
        return None, None
    content = clean_html(result)
    title = f"Day{day_num}：龙虾养成日记"
    return title, content


# ============================================================
# Cover image generation (HTML template → screenshot)
# ============================================================
def generate_cover_image(title, subtitle, theme_index, output_path):
    """Generate a cover image by rendering HTML and taking a screenshot."""
    theme = COVER_THEMES[theme_index % len(COVER_THEMES)]

    # Escape title for HTML
    title_escaped = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    sub_escaped = subtitle.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;700;900&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ width:900px; height:500px; background:{theme['bg']}; font-family:'Noto Sans SC',sans-serif; overflow:hidden; position:relative; }}
.container {{ padding:60px 64px; height:100%; display:flex; flex-direction:column; justify-content:center; position:relative; z-index:2; }}
h1 {{ color:{theme['text']}; font-size:42px; font-weight:900; line-height:1.3; margin-bottom:20px; text-shadow:0 2px 12px rgba(0,0,0,0.3); }}
.subtitle {{ color:{theme['accent']}; font-size:18px; font-weight:700; letter-spacing:1px; }}
.brand {{ position:absolute; bottom:36px; right:64px; color:rgba(255,255,255,0.5); font-size:14px; font-weight:500; }}
.accent-line {{ width:60px; height:4px; background:{theme['accent']}; border-radius:2px; margin-bottom:24px; }}
.grid {{ position:absolute; top:0; left:0; width:100%; height:100%; background-image:
  linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px),
  linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px);
  background-size:40px 40px; z-index:1; }}
</style></head>
<body>
<div class="grid"></div>
<div class="container">
  <div class="accent-line"></div>
  <h1>{title_escaped}</h1>
  <div class="subtitle">{sub_escaped}</div>
</div>
<div class="brand">JK养虾 · Openclaw Agent</div>
</body></html>"""

    html_path = output_path.replace(".jpg", ".html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 900, "height": 500})
            page.goto(f"file://{os.path.abspath(html_path)}", wait_until="networkidle", timeout=15000)
            page.wait_for_timeout(1000)
            page.screenshot(path=output_path)
            browser.close()
        print(f"  [ok] Cover image: {os.path.basename(output_path)}")
        return True
    except Exception as e:
        print(f"  [warn] Cover screenshot failed: {e}")
        return False


# ============================================================
# WeChat functions (reused from v2)
# ============================================================
def get_current_ip():
    try:
        return requests.get("https://api.ipify.org?format=json", timeout=5).json().get("ip", "unknown")
    except Exception:
        return "unknown"

def get_wx_access_token():
    if not WX_APPID or not WX_APPSECRET:
        print("[warn] WX credentials not set")
        return None
    url = f"https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={WX_APPID}&secret={WX_APPSECRET}"
    data = requests.get(url, timeout=10).json()
    if "access_token" in data:
        print("[ok] WeChat access token obtained")
        return data["access_token"]
    if data.get("errcode") == 40164:
        ip = get_current_ip()
        print(f"[ACTION REQUIRED] IP whitelist error! IP: {ip}")
    else:
        print(f"[warn] WeChat token failed: {data}")
    return None

def upload_wx_image(access_token, image_path):
    url = f"https://api.weixin.qq.com/cgi-bin/material/add_material?access_token={access_token}&type=image"
    with open(image_path, "rb") as f:
        data = requests.post(url, files={"media": (os.path.basename(image_path), f, "image/jpeg")}, timeout=30).json()
    if "media_id" in data:
        print(f"  [ok] Uploaded {os.path.basename(image_path)} -> {data['media_id'][:20]}...")
        return data["media_id"], data.get("url", "")
    print(f"  [warn] Upload failed: {data}")
    return None, None

def build_image_article_html(image_urls):
    parts = []
    for url in image_urls:
        parts.append(f'<p style="text-align:center;margin:0;padding:0;line-height:0;"><img src="{url}" style="width:100%;display:block;" /></p>')
    return "\n".join(parts)

def push_to_wechat_draft(access_token, title, wechat_html, digest, cover_media_id=None):
    url = f"https://api.weixin.qq.com/cgi-bin/draft/add?access_token={access_token}"
    while len(title.encode("utf-8")) > 60:
        title = title[:-1]

    payload = {"articles": [{
        "title": title,
        "author": "JK养虾",
        "content": wechat_html,
        "digest": digest[:120],
        "thumb_media_id": cover_media_id or WX_COVER_MEDIA_ID,
        "need_open_comment": 1,
        "only_fans_can_comment": 0,
    }]}
    data = requests.post(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                         headers={"Content-Type": "application/json; charset=utf-8"}, timeout=30).json()
    if "media_id" in data:
        print(f"[ok] Draft created: {title}")
        return data["media_id"]
    print(f"[warn] Draft failed: {data}")
    return None


# ============================================================
# Screenshot & split (reused from v2)
# ============================================================
def screenshot_and_split(html_content, output_dir, num_parts=3, wait_ms=2000):
    from PIL import Image
    html_path = os.path.join(output_dir, "render.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    full_screenshot = os.path.join(output_dir, "full.png")

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": WX_IMAGE_WIDTH, "height": 800})
            page.goto(f"file://{html_path}", wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(wait_ms)
            page.screenshot(path=full_screenshot, full_page=True)
            browser.close()
    except Exception as e:
        print(f"[warn] Playwright error: {e}")

    if not os.path.exists(full_screenshot):
        return []

    img = Image.open(full_screenshot)
    width, height = img.size
    print(f"[ok] Screenshot: {width}x{height}px")

    max_h = 2000
    parts = max(max(2, math.ceil(height / max_h)), num_parts)
    ph = math.ceil(height / parts)
    paths = []
    for i in range(parts):
        top, bottom = i * ph, min((i + 1) * ph, height)
        if bottom - top < 100:
            continue
        part = img.crop((0, top, width, bottom))
        p = os.path.join(output_dir, f"part_{i+1}.jpg")
        part.save(p, "JPEG", quality=95)
        paths.append(p)
        print(f"  [ok] Part {i+1}: {width}x{bottom-top}px")
    return paths


# ============================================================
# Build render HTML (for WeChat screenshot)
# ============================================================
DATA_VIZ_CSS = """
.data-table {{ margin:20px 0; overflow-x:auto; border-radius:8px; border:1px solid #dde3e8; }}
.data-table table {{ width:100%; border-collapse:collapse; font-size:12px; }}
.data-table thead {{ background:linear-gradient(135deg,#0077aa,#005580); }}
.data-table thead th {{ color:#fff; padding:8px 10px; text-align:left; font-weight:600; white-space:nowrap; }}
.data-table tbody tr {{ border-bottom:1px solid #eef1f4; }}
.data-table tbody tr:nth-child(even) {{ background:#f8fafb; }}
.data-table tbody td {{ padding:8px 10px; color:#333; }}
.stat-cards {{ display:flex; gap:8px; margin:20px 0; flex-wrap:wrap; }}
.stat-card {{ flex:1; min-width:80px; background:linear-gradient(135deg,#f0f8ff,#e8f4f8); border-radius:8px; padding:14px 10px; text-align:center; border:1px solid #d0e8f0; }}
.stat-number {{ font-size:22px; font-weight:900; color:#0077aa; display:block; line-height:1.2; }}
.stat-label {{ font-size:11px; color:#666; margin-top:4px; display:block; }}
.ranking-chart {{ margin:20px 0; }}
.rank-item {{ display:flex; align-items:center; margin-bottom:8px; }}
.rank-label {{ width:70px; font-size:12px; color:#333; font-weight:500; flex-shrink:0; }}
.rank-bar {{ background:linear-gradient(90deg,#0077aa,#00a5d4); height:24px; border-radius:5px; display:flex; align-items:center; padding:0 8px; }}
.rank-bar span {{ color:#fff; font-size:10px; font-weight:600; white-space:nowrap; }}
.timeline {{ margin:20px 0; padding-left:18px; border-left:2px solid #0077aa; }}
.timeline-item {{ margin-bottom:14px; position:relative; }}
.timeline-item::before {{ content:''; position:absolute; left:-23px; top:5px; width:10px; height:10px; background:#0077aa; border-radius:50%; border:2px solid #fff; box-shadow:0 0 0 2px #0077aa; }}
.timeline-date {{ font-size:11px; color:#0077aa; font-weight:700; margin-bottom:3px; }}
.timeline-content {{ font-size:13px; color:#333; line-height:1.5; }}
.highlight-box {{ display:flex; align-items:center; gap:12px; background:linear-gradient(135deg,#fff8e1,#fff3cd); border-left:3px solid #f5a623; border-radius:0 8px 8px 0; padding:14px 16px; margin:18px 0; }}
.highlight-num {{ font-size:28px; font-weight:900; color:#e67e00; flex-shrink:0; }}
.highlight-text {{ font-size:13px; color:#555; line-height:1.5; }}
.cta-box {{ background:#fff; border:2px solid #0077aa; border-radius:10px; padding:18px 16px; margin:24px 0; text-align:center; }}
.cta-box p {{ font-weight:500; font-size:14px !important; color:#1a1a1a !important; }}
"""

# ============================================================
# V4 Dark Theme CSS (matches DeepSeek V4 reference report)
# ============================================================
DARK_THEME_CSS = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { scroll-behavior: smooth; }
body { background: #0b1120; font-family: 'Inter', 'Noto Sans SC', system-ui, sans-serif;
  color: #94a3b8; line-height: 1.8; -webkit-font-smoothing: antialiased; overflow-x: hidden; }
::selection { background: #3b82f644; color: #fff; }
.wrapper { max-width: 375px; margin: 0 auto; padding: 0; }

/* Cover */
.cover { position: relative; padding: 40px 20px 32px; overflow: hidden; }
.cover::before { content:''; position:absolute; inset:0;
  background: radial-gradient(ellipse 80% 60% at 50% 30%, rgba(59,130,246,0.12) 0%, transparent 60%),
  radial-gradient(ellipse 50% 40% at 80% 70%, rgba(245,158,11,0.08) 0%, transparent 55%); pointer-events:none; }
.cover-grid { position:absolute; inset:0;
  background-image: linear-gradient(rgba(59,130,246,0.04) 1px, transparent 1px),
  linear-gradient(90deg, rgba(59,130,246,0.04) 1px, transparent 1px);
  background-size: 40px 40px; pointer-events:none; }
.cover-content { position: relative; z-index: 1; }
.cover-date { font-family: 'JetBrains Mono', monospace; font-size: 10px;
  letter-spacing: 0.2em; color: #3b82f6; text-transform: uppercase; margin-bottom: 16px; }
.cover-title { font-family: 'Noto Serif SC', serif; font-weight: 900;
  font-size: 28px; line-height: 1.25; color: #fff; letter-spacing: -0.02em; }
.cover-subtitle { font-size: 14px; color: #94a3b8; line-height: 1.7; margin-top: 14px; }
.cover-tag { display: inline-block; font-family: 'JetBrains Mono', monospace;
  font-size: 9px; letter-spacing: 0.15em; padding: 3px 10px; border-radius: 4px;
  background: rgba(59,130,246,0.1); color: #3b82f6; border: 1px solid rgba(59,130,246,0.2);
  margin-bottom: 14px; text-transform: uppercase; }
.cover-brand { font-size: 11px; color: rgba(255,255,255,0.35); margin-top: 20px; }

/* Sections */
.section { padding: 24px 20px; }
.section-tag { display: inline-block; font-family: 'JetBrains Mono', monospace;
  font-size: 9px; letter-spacing: 0.15em; text-transform: uppercase;
  padding: 3px 10px; border-radius: 4px; background: rgba(59,130,246,0.1);
  color: #3b82f6; border: 1px solid rgba(59,130,246,0.2); margin-bottom: 10px; }
.section-h2 { font-family: 'Noto Serif SC', serif; font-weight: 700;
  font-size: 20px; color: #fff; line-height: 1.35; margin-bottom: 16px; }
.divider { height: 1px; background: linear-gradient(90deg, transparent, #1e293b, transparent); margin: 0; }

/* Glass card */
.glass { background: rgba(17,24,39,0.7); border: 1px solid #1e293b;
  border-radius: 12px; backdrop-filter: blur(8px); padding: 20px 16px; margin: 16px 0; }

/* Body text */
p.body-text { color: #94a3b8; font-size: 14px; line-height: 1.9; margin-bottom: 14px; }
p.body-text strong { color: #e2e8f0; }

/* Key Takeaways */
.kt-card { border: 1px solid rgba(59,130,246,0.25);
  background: linear-gradient(135deg, rgba(59,130,246,0.04), rgba(245,158,11,0.03)); }
.kt-label { font-family: 'JetBrains Mono', monospace; font-size: 9px;
  letter-spacing: 0.15em; color: #3b82f6; margin-bottom: 12px; }
.kt-item { display: flex; gap: 10px; align-items: flex-start; margin-bottom: 10px; }
.kt-num { font-family: 'JetBrains Mono', monospace; font-size: 13px;
  font-weight: 700; color: #f59e0b; min-width: 18px; flex-shrink: 0; }
.kt-text { font-size: 13px; color: #e2e8f0; line-height: 1.7; }
.kt-text strong { color: #fff; }

/* Stat cards */
.stat-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; margin: 14px 0; }
.stat-card-v4 { text-align: center; padding: 16px 10px; }
.stat-big { font-family: 'JetBrains Mono', monospace; font-weight: 600; font-size: 28px;
  background: linear-gradient(135deg, #3b82f6, #06b6d4); -webkit-background-clip: text;
  -webkit-text-fill-color: transparent; background-clip: text; line-height: 1.2; }
.stat-label { font-size: 11px; color: #94a3b8; margin-top: 4px; }

/* Comparison table */
.cmp-table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: 12px; }
.cmp-table th { background: rgba(30,41,59,0.6); color: #e2e8f0; font-weight: 600;
  padding: 8px 10px; text-align: left; border-bottom: 1px solid #1e293b;
  font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em; }
.cmp-table td { padding: 8px 10px; border-bottom: 1px solid rgba(30,41,59,0.4);
  color: #94a3b8; vertical-align: middle; font-size: 12px; }
.cmp-table tr:last-child td { border-bottom: none; }
.cmp-table .highlight-row { background: rgba(59,130,246,0.06); }
.badge { display: inline-block; padding: 2px 8px; border-radius: 3px;
  font-size: 10px; font-weight: 600; font-family: 'JetBrains Mono', monospace; }
.badge-green { background: rgba(16,185,129,0.15); color: #10b981; }
.badge-amber { background: rgba(245,158,11,0.15); color: #f59e0b; }
.badge-red { background: rgba(239,68,68,0.15); color: #ef4444; }
.badge-blue { background: rgba(59,130,246,0.15); color: #3b82f6; }
.cmp-table .text-light { color: #e2e8f0; }

/* Timeline */
.timeline-track { position: relative; padding-left: 24px; }
.timeline-track::before { content:''; position:absolute; left:6px; top:6px; bottom:6px;
  width: 2px; background: linear-gradient(180deg, #3b82f6, #f59e0b 60%, #10b981); }
.timeline-node { position: relative; padding-bottom: 18px; }
.timeline-node::before { content:''; position:absolute; left:-20px; top:4px;
  width: 10px; height: 10px; border-radius: 50%; background: #3b82f6;
  border: 2px solid #0b1120; z-index: 1; }
.timeline-node.node-amber::before { background: #f59e0b; }
.timeline-node.node-green::before { background: #10b981; }
.timeline-node.node-red::before { background: #ef4444; }
.tl-date { font-family: 'JetBrains Mono', monospace; font-size: 10px;
  color: #3b82f6; letter-spacing: 0.05em; }
.node-amber .tl-date { color: #f59e0b; }
.node-green .tl-date { color: #10b981; }
.node-red .tl-date { color: #ef4444; }
.tl-title { color: #e2e8f0; font-size: 13px; font-weight: 600; margin-top: 2px; }
.tl-desc { color: #94a3b8; font-size: 11px; margin-top: 2px; line-height: 1.6; }

/* Callout */
.callout { border-left: 3px solid #f59e0b; padding: 14px 16px;
  background: rgba(245,158,11,0.05); border-radius: 0 8px 8px 0; margin: 14px 0; }
.callout-blue { border-left-color: #3b82f6; background: rgba(59,130,246,0.05); }
.callout p { font-size: 13px; color: #e2e8f0; line-height: 1.8; }
.callout strong { color: #fff; }

/* Ranking bars */
.rank-item { display: flex; align-items: center; margin-bottom: 8px; }
.rank-label { width: 80px; font-size: 12px; color: #e2e8f0; font-weight: 500; flex-shrink: 0; }
.rank-bar { height: 24px; border-radius: 5px; display: flex; align-items: center;
  padding: 0 8px; background: linear-gradient(90deg, #3b82f6, #06b6d4); }
.rank-bar span { color: #fff; font-size: 10px; font-weight: 600; white-space: nowrap; }

/* Action cards */
.action-grid { display: grid; grid-template-columns: 1fr; gap: 10px; margin: 14px 0; }
.action-card { position: relative; overflow: hidden; padding: 16px; }
.action-card::before { content:''; position:absolute; top:0; left:0; right:0; height:2px; }
.ac-blue::before { background: linear-gradient(90deg, #3b82f6, #06b6d4); }
.ac-amber::before { background: linear-gradient(90deg, #f59e0b, #ef4444); }
.ac-green::before { background: linear-gradient(90deg, #10b981, #3b82f6); }
.ac-purple::before { background: linear-gradient(90deg, #8b5cf6, #3b82f6); }
.action-num { font-family: 'JetBrains Mono', monospace; font-size: 32px;
  font-weight: 700; line-height: 1; opacity: 0.1; position: absolute; top: 6px; right: 10px; color: #fff; }
.action-title { font-size: 14px; color: #e2e8f0; font-weight: 600; margin-bottom: 4px; }
.action-desc { font-size: 12px; color: #94a3b8; line-height: 1.6; }

/* Pros/Cons */
.proscons { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 14px 0; }
.pros-col, .cons-col { padding: 14px; }
.pros-col { border-top: 2px solid #10b981; }
.cons-col { border-top: 2px solid #ef4444; }
.pc-title { font-size: 12px; font-weight: 700; margin-bottom: 8px; }
.pros-col .pc-title { color: #10b981; }
.cons-col .pc-title { color: #ef4444; }
.pc-item { font-size: 11px; color: #e2e8f0; margin-bottom: 6px; line-height: 1.5;
  padding-left: 14px; position: relative; }
.pc-item::before { content:''; position: absolute; left: 0; top: 6px;
  width: 6px; height: 6px; border-radius: 50%; }
.pros-col .pc-item::before { background: #10b981; }
.cons-col .pc-item::before { background: #ef4444; }

/* Conclusion */
.conclusion { border: 1px solid rgba(59,130,246,0.3);
  background: linear-gradient(135deg, rgba(59,130,246,0.06), rgba(6,182,212,0.04)); }
.conclusion-title { font-family: 'Noto Serif SC', serif; font-size: 16px;
  font-weight: 700; color: #fff; margin-bottom: 10px; }
.conclusion-text { font-size: 13px; color: #e2e8f0; line-height: 1.8; }

/* CTA */
.cta-v4 { text-align: center; padding: 24px 16px; margin: 16px 0;
  border: 1px solid rgba(59,130,246,0.3); background: rgba(59,130,246,0.05); }
.cta-v4 p { font-size: 14px; color: #e2e8f0; font-weight: 500; }
.cta-v4 strong { color: #fff; }

/* ECharts container */
.chart-box { width: 100%; height: 280px; margin: 14px 0; }

/* Footer */
.article-footer-v4 { padding: 20px; text-align: center; border-top: 1px solid #1e293b; }
.article-footer-v4 p { font-size: 11px; color: rgba(255,255,255,0.3); }
"""


# ============================================================
# V4 Section Renderers (JSON → HTML fragments)
# ============================================================
def _esc(text):
    """HTML-escape a string."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _md_inline(text):
    """Convert **bold** and basic markdown inline to HTML."""
    text = str(text)
    text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\*(.*?)\*', r'<em>\1</em>', text)
    return text


def render_key_takeaways(sec):
    items = sec.get("items", [])
    if not items:
        return ""
    rows = []
    for i, item in enumerate(items, 1):
        rows.append(
            f'<div class="kt-item">'
            f'<div class="kt-num">{i}</div>'
            f'<div class="kt-text">{_md_inline(item)}</div>'
            f'</div>'
        )
    return (
        f'<div class="section"><div class="glass kt-card">'
        f'<div class="kt-label">KEY TAKEAWAYS / 全文核心要点</div>'
        f'{"".join(rows)}'
        f'</div></div>'
    )


def render_stat_cards(sec):
    cards = sec.get("cards", [])
    if not cards:
        return ""
    items = []
    for c in cards:
        items.append(
            f'<div class="glass stat-card-v4">'
            f'<div class="stat-big">{_esc(c.get("number", ""))}</div>'
            f'<div class="stat-label">{_esc(c.get("label", ""))}</div>'
            f'</div>'
        )
    return f'<div class="section"><div class="stat-grid">{"".join(items)}</div></div>'


def render_text(sec):
    content = sec.get("content", "")
    if not content:
        return ""
    # Split paragraphs by double newlines
    paras = [p.strip() for p in content.split("\n\n") if p.strip()]
    if not paras:
        paras = [content]
    html_parts = []
    for p in paras:
        html_parts.append(f'<p class="body-text">{_md_inline(p)}</p>')
    title = sec.get("title", "")
    title_html = ""
    if title:
        tag = sec.get("tag", "")
        tag_html = f'<div class="section-tag">{_esc(tag)}</div>' if tag else ""
        title_html = f'{tag_html}<h2 class="section-h2">{_esc(title)}</h2>'
    return f'<div class="section">{title_html}{"".join(html_parts)}</div>'


def render_comparison_table(sec):
    title = sec.get("title", "")
    headers = sec.get("headers", [])
    rows = sec.get("rows", [])
    note = sec.get("note", "")
    if not headers or not rows:
        return ""
    th = "".join(f'<th>{_esc(h)}</th>' for h in headers)
    tbody_rows = []
    for row in rows:
        cells = row.get("cells", row) if isinstance(row, dict) else row
        highlight = row.get("highlight", False) if isinstance(row, dict) else False
        if isinstance(cells, dict):
            cells = cells.get("cells", [])
        tr_class = ' class="highlight-row"' if highlight else ""
        tds = []
        for j, cell in enumerate(cells):
            if isinstance(cell, dict):
                badge = cell.get("badge", "")
                text = cell.get("text", "")
                if badge:
                    badge_cls = f"badge-{badge}" if badge in ("green", "amber", "red", "blue") else "badge-blue"
                    tds.append(f'<td><span class="badge {badge_cls}">{_esc(text)}</span></td>')
                else:
                    cls = ' class="text-light"' if j == 0 else ""
                    tds.append(f'<td{cls}>{_md_inline(text)}</td>')
            else:
                cls = ' class="text-light"' if j == 0 else ""
                tds.append(f'<td{cls}>{_md_inline(cell)}</td>')
        tbody_rows.append(f'<tr{tr_class}>{"".join(tds)}</tr>')
    note_html = f'<p style="font-size:10px;color:#94a3b8;margin-top:10px;">{_md_inline(note)}</p>' if note else ""
    title_html = f'<h3 style="color:#fff;font-weight:700;font-size:14px;margin-bottom:12px;">{_esc(title)}</h3>' if title else ""
    return (
        f'<div class="section"><div class="glass">{title_html}'
        f'<div style="overflow-x:auto;"><table class="cmp-table">'
        f'<thead><tr>{th}</tr></thead>'
        f'<tbody>{"".join(tbody_rows)}</tbody>'
        f'</table></div>{note_html}</div></div>'
    )


def render_timeline(sec):
    events = sec.get("events", [])
    if not events:
        return ""
    title = sec.get("title", "")
    tag = sec.get("tag", "")
    nodes = []
    for ev in events:
        color = ev.get("color", "blue")
        node_cls = f"node-{color}" if color != "blue" else ""
        nodes.append(
            f'<div class="timeline-node {node_cls}">'
            f'<div class="tl-date">{_esc(ev.get("date", ""))}</div>'
            f'<div class="tl-title">{_esc(ev.get("title", ""))}</div>'
            f'<div class="tl-desc">{_md_inline(ev.get("desc", ""))}</div>'
            f'</div>'
        )
    tag_html = f'<div class="section-tag">{_esc(tag)}</div>' if tag else ""
    title_html = f'{tag_html}<h2 class="section-h2">{_esc(title)}</h2>' if title else ""
    return (
        f'<div class="section">{title_html}'
        f'<div class="glass"><div class="timeline-track">{"".join(nodes)}</div></div>'
        f'</div>'
    )


def render_callout(sec):
    text = sec.get("text", "")
    if not text:
        return ""
    variant = sec.get("variant", "amber")
    cls = "callout-blue" if variant == "blue" else "callout"
    return f'<div class="section"><div class="{cls}"><p>{_md_inline(text)}</p></div></div>'


def render_ranking(sec):
    items = sec.get("items", [])
    if not items:
        return ""
    title = sec.get("title", "")
    rows = []
    for item in items:
        pct = item.get("value", 50)
        rows.append(
            f'<div class="rank-item">'
            f'<div class="rank-label">{_esc(item.get("label", ""))}</div>'
            f'<div class="rank-bar" style="width:{pct}%"><span>{_esc(item.get("display", str(pct)))}</span></div>'
            f'</div>'
        )
    title_html = f'<h3 style="color:#fff;font-weight:700;font-size:14px;margin-bottom:12px;">{_esc(title)}</h3>' if title else ""
    return f'<div class="section"><div class="glass">{title_html}{"".join(rows)}</div></div>'


_chart_counter = 0

def render_bar_chart(sec):
    global _chart_counter
    _chart_counter += 1
    chart_id = f"chart-bar-{_chart_counter}"
    title = sec.get("title", "")
    title_html = f'<h3 style="color:#fff;font-weight:700;font-size:14px;margin-bottom:8px;">{_esc(title)}</h3>' if title else ""
    return (
        f'<div class="section"><div class="glass">{title_html}'
        f'<div id="{chart_id}" class="chart-box"></div>'
        f'</div></div>',
        chart_id, sec
    )


def render_radar_chart(sec):
    global _chart_counter
    _chart_counter += 1
    chart_id = f"chart-radar-{_chart_counter}"
    title = sec.get("title", "")
    title_html = f'<h3 style="color:#fff;font-weight:700;font-size:14px;margin-bottom:8px;">{_esc(title)}</h3>' if title else ""
    return (
        f'<div class="section"><div class="glass">{title_html}'
        f'<div id="{chart_id}" class="chart-box"></div>'
        f'</div></div>',
        chart_id, sec
    )


def render_action_cards(sec):
    cards = sec.get("cards", [])
    if not cards:
        return ""
    title = sec.get("title", "")
    colors = ["ac-blue", "ac-amber", "ac-green", "ac-purple"]
    items = []
    for i, card in enumerate(cards):
        c = colors[i % len(colors)]
        items.append(
            f'<div class="glass action-card {c}">'
            f'<div class="action-num">{i+1:02d}</div>'
            f'<div class="action-title">{_esc(card.get("title", ""))}</div>'
            f'<div class="action-desc">{_md_inline(card.get("desc", ""))}</div>'
            f'</div>'
        )
    title_html = ""
    tag = sec.get("tag", "")
    if title:
        tag_html = f'<div class="section-tag">{_esc(tag)}</div>' if tag else ""
        title_html = f'{tag_html}<h2 class="section-h2">{_esc(title)}</h2>'
    return f'<div class="section">{title_html}<div class="action-grid">{"".join(items)}</div></div>'


def render_pros_cons(sec):
    pros = sec.get("pros", [])
    cons = sec.get("cons", [])
    if not pros and not cons:
        return ""
    title = sec.get("title", "")
    pro_items = "".join(f'<div class="pc-item">{_md_inline(p)}</div>' for p in pros)
    con_items = "".join(f'<div class="pc-item">{_md_inline(c)}</div>' for c in cons)
    title_html = f'<h3 style="color:#fff;font-weight:700;font-size:14px;margin-bottom:12px;">{_esc(title)}</h3>' if title else ""
    return (
        f'<div class="section">{title_html}<div class="proscons">'
        f'<div class="glass pros-col"><div class="pc-title">&#x2705; 利好</div>{pro_items}</div>'
        f'<div class="glass cons-col"><div class="pc-title">&#x26A0; 风险</div>{con_items}</div>'
        f'</div></div>'
    )


def render_conclusion(sec):
    title = sec.get("title", "总结")
    text = sec.get("text", "")
    if not text:
        return ""
    return (
        f'<div class="section"><div class="glass conclusion">'
        f'<div class="conclusion-title">{_esc(title)}</div>'
        f'<div class="conclusion-text">{_md_inline(text)}</div>'
        f'</div></div>'
    )


def render_cta(sec):
    text = sec.get("text", "")
    if not text:
        return ""
    return f'<div class="section"><div class="glass cta-v4"><p>{_md_inline(text)}</p></div></div>'


# ============================================================
# V4 Section Dispatcher & Rich HTML Builder
# ============================================================
SECTION_RENDERERS = {
    "key_takeaways": render_key_takeaways,
    "stat_cards": render_stat_cards,
    "text": render_text,
    "comparison_table": render_comparison_table,
    "timeline": render_timeline,
    "callout": render_callout,
    "ranking": render_ranking,
    "bar_chart": render_bar_chart,
    "radar_chart": render_radar_chart,
    "action_cards": render_action_cards,
    "pros_cons": render_pros_cons,
    "conclusion": render_conclusion,
    "cta": render_cta,
}


def _build_echart_script(chart_id, sec):
    """Generate ECharts initialization script for a chart section."""
    chart_type = sec.get("type", "bar_chart")
    if chart_type == "bar_chart":
        categories = json.dumps(sec.get("categories", []), ensure_ascii=False)
        series_data = sec.get("series", [])
        series_json = []
        for s in series_data:
            series_json.append({
                "name": s.get("name", ""),
                "type": "bar",
                "data": s.get("data", []),
                "itemStyle": {"borderRadius": [4, 4, 0, 0]},
            })
        series_str = json.dumps(series_json, ensure_ascii=False)
        return f"""
var c_{chart_id.replace('-','_')} = echarts.init(document.getElementById('{chart_id}'));
c_{chart_id.replace('-','_')}.setOption({{
  backgroundColor: 'transparent',
  tooltip: {{ trigger: 'axis' }},
  legend: {{ textStyle: {{ color: '#94a3b8', fontSize: 10 }}, top: 0 }},
  grid: {{ left: 50, right: 20, top: 40, bottom: 30 }},
  xAxis: {{ type: 'category', data: {categories}, axisLabel: {{ color: '#94a3b8', fontSize: 9 }}, axisLine: {{ lineStyle: {{ color: '#1e293b' }} }} }},
  yAxis: {{ type: 'value', axisLabel: {{ color: '#94a3b8', fontSize: 9 }}, splitLine: {{ lineStyle: {{ color: '#1e293b' }} }}, axisLine: {{ lineStyle: {{ color: '#1e293b' }} }} }},
  series: {series_str}
}});"""
    elif chart_type == "radar_chart":
        indicators = sec.get("indicators", [])
        ind_json = json.dumps([{"name": i.get("name", ""), "max": i.get("max", 100)} for i in indicators], ensure_ascii=False)
        series_data = sec.get("series", [])
        series_json = []
        for s in series_data:
            series_json.append({"name": s.get("name", ""), "value": s.get("data", [])})
        data_str = json.dumps(series_json, ensure_ascii=False)
        return f"""
var c_{chart_id.replace('-','_')} = echarts.init(document.getElementById('{chart_id}'));
c_{chart_id.replace('-','_')}.setOption({{
  backgroundColor: 'transparent',
  legend: {{ textStyle: {{ color: '#94a3b8', fontSize: 10 }}, bottom: 0 }},
  radar: {{ indicator: {ind_json}, shape: 'polygon',
    axisName: {{ color: '#94a3b8', fontSize: 9 }},
    splitLine: {{ lineStyle: {{ color: '#1e293b' }} }},
    splitArea: {{ areaStyle: {{ color: ['transparent'] }} }},
    axisLine: {{ lineStyle: {{ color: '#1e293b' }} }} }},
  series: [{{ type: 'radar', data: {data_str},
    areaStyle: {{ opacity: 0.15 }}, lineStyle: {{ width: 2 }} }}]
}});"""
    return ""


def build_rich_render_html(article_data, date_cn, tag="AI深度解读"):
    """Build production-grade dark-theme HTML from structured JSON article data."""
    global _chart_counter
    _chart_counter = 0

    title = article_data.get("title", "AI热点解读")
    subtitle = article_data.get("subtitle", "")
    sections = article_data.get("sections", [])

    # Render all sections
    section_html_parts = []
    chart_scripts = []

    for sec in sections:
        sec_type = sec.get("type", "text")
        renderer = SECTION_RENDERERS.get(sec_type)
        if not renderer:
            continue
        result = renderer(sec)
        # Chart renderers return tuple (html, chart_id, sec)
        if isinstance(result, tuple):
            html, chart_id, chart_sec = result
            section_html_parts.append(html)
            chart_scripts.append(_build_echart_script(chart_id, chart_sec))
        else:
            if result:
                section_html_parts.append(result)
        # Add divider between sections
        section_html_parts.append('<div class="divider"></div>')

    # Remove trailing divider
    if section_html_parts and section_html_parts[-1] == '<div class="divider"></div>':
        section_html_parts.pop()

    sections_html = "\n".join(section_html_parts)

    # ECharts script block
    echarts_script = ""
    if chart_scripts:
        echarts_script = f'<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>'
        echarts_init = "\n".join(chart_scripts)
        echarts_script += f'\n<script>document.addEventListener("DOMContentLoaded", function() {{\n{echarts_init}\n}});</script>'

    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=375">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@400;700;900&family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
{echarts_script}
<style>
{DARK_THEME_CSS}
</style></head><body>
<div class="wrapper">

<div class="cover">
  <div class="cover-grid"></div>
  <div class="cover-content">
    <div class="cover-tag">{_esc(tag)}</div>
    <div class="cover-date">{date_cn} / JK养虾 · Openclaw Agent</div>
    <h1 class="cover-title">{_esc(title)}</h1>
    <p class="cover-subtitle">{_md_inline(subtitle)}</p>
    <div class="cover-brand">JK养虾 · AI深度解读</div>
  </div>
</div>

{sections_html}

<div class="article-footer-v4">
  <p>JK养虾 · Openclaw Agent · {date_cn}</p>
  <p>关注公众号「JK养虾」每天一篇AI深度解读</p>
</div>

</div>
</body></html>"""


def build_render_html(title, date_cn, content, tag="AI深度解读"):
    """Build HTML for mobile-viewport screenshot (375px wide, like iPhone)."""
    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width={WX_IMAGE_WIDTH}">
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@300;400;500;700;900&family=Noto+Serif+SC:wght@400;600;700&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ width:{WX_IMAGE_WIDTH}px; font-family:'Noto Sans SC',-apple-system,sans-serif; background:#fafaf8; color:#1a1a1a; line-height:1.8; }}
.wrapper {{ padding:24px 20px 32px; }}
.tag {{ display:inline-block; font-size:11px; font-weight:500; color:#0077aa; background:#e8f4f8; padding:3px 10px; border-radius:4px; margin-bottom:12px; }}
h1 {{ font-family:'Noto Serif SC',Georgia,serif; font-size:22px; font-weight:700; line-height:1.35; margin-bottom:10px; }}
.meta {{ font-size:11px; color:#888; margin-bottom:20px; padding-bottom:12px; border-bottom:1px solid #e8e8e5; }}
.meta span + span::before {{ content:" · "; }}
.content h2 {{ font-family:'Noto Serif SC',Georgia,serif; font-size:18px; font-weight:700; margin:28px 0 12px; padding-bottom:8px; border-bottom:2px solid #0077aa; }}
.content p {{ margin-bottom:14px; font-size:15px; color:#333; }}
.content strong {{ color:#1a1a1a; font-weight:700; }}
.content blockquote {{ border-left:3px solid #0077aa; background:#e8f4f8; padding:12px 14px; margin:16px 0; border-radius:0 8px 8px 0; font-size:14px; color:#555; }}
.content ul,.content ol {{ margin:12px 0 18px 20px; }}
.content li {{ margin-bottom:6px; font-size:15px; color:#333; }}
.content hr {{ border:none; border-top:1px solid #e8e8e5; margin:24px 0; }}
{DATA_VIZ_CSS}
.footer {{ margin-top:28px; padding-top:16px; border-top:1px solid #e8e8e5; text-align:center; }}
.footer p {{ font-size:11px; color:#888; margin-bottom:4px; }}
</style></head><body>
<div class="wrapper">
  <span class="tag">{tag}</span>
  <h1>{title}</h1>
  <div class="meta"><span>JK养虾</span><span>{date_cn}</span><span>Openclaw Agent</span></div>
  <div class="content">{content}</div>
  <div class="footer"><p>关注公众号「JK养虾」，每天一篇AI深度解读</p></div>
</div></body></html>"""


# ============================================================
# Build website page for diary
# ============================================================
def build_diary_page_html(day_num, title, date_cn, content):
    day_str = f"{day_num:03d}"
    template_path = os.path.join(SITE_DIR, "day4.html")
    css_block = ""
    if os.path.exists(template_path):
        with open(template_path, "r", encoding="utf-8") as f:
            css_match = re.search(r'<style>(.*?)</style>', f.read(), re.DOTALL)
            if css_match:
                css_block = css_match.group(1)
    if not css_block:
        css_block = ":root { --bg: #fafaf8; --text: #1a1a1a; }"

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} | JK养虾</title>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@300;400;500;700;900&family=Noto+Serif+SC:wght@400;600;700&display=swap" rel="stylesheet">
<style>{css_block}</style></head><body>
<div class="article-wrapper">
<a href="diary.html" class="back-link">&larr; 返回日记列表</a>
<div class="article-header">
  <span class="article-tag">龙虾养成日记 #{day_str}</span>
  <h1>{title}</h1>
  <div class="article-meta"><span>Openclaw</span><span>{date_cn}</span><span>龙虾COO</span></div>
</div>
<div class="article-content">{content}</div>
<div class="article-footer">
  <p><em>本文由 Openclaw COO Agent 撰写，老板审核发布。</em></p>
</div>
</div></body></html>"""


# ============================================================
# Process one article: cover + screenshot + upload + draft
# ============================================================
def process_article(access_token, title, content, digest, theme_idx, tmpdir, tag="AI深度解读", is_diary=False):
    """Full pipeline for one article. V4 hotspot articles use rich dark-theme HTML; diary uses text mode."""
    # 1. Generate cover image (always needed)
    cover_path = os.path.join(tmpdir, f"cover_{theme_idx}.jpg")
    generate_cover_image(title, tag, theme_idx, cover_path)

    cover_media_id = None
    if access_token and os.path.exists(cover_path):
        mid, _ = upload_wx_image(access_token, cover_path)
        if mid:
            cover_media_id = mid

    if not access_token:
        return None

    # 2. Decide mode based on content type
    if isinstance(content, dict) and not is_diary:
        # V4 RICH MODE: JSON article data → dark-theme HTML → screenshot
        print(f"  [mode] V4 RICH — dark-theme template with {len(content.get('sections', []))} sections")
        render_html = build_rich_render_html(content, get_date_cn(), tag)
        image_paths = screenshot_and_split(render_html, tmpdir, num_parts=3, wait_ms=5000)

        if not image_paths:
            print("  [warn] V4 screenshot failed, falling back to text mode")
            # Fallback: extract text from sections for text mode
            text_parts = []
            for sec in content.get("sections", []):
                if sec.get("type") == "text":
                    text_parts.append(sec.get("content", ""))
            fallback_content = "\n\n".join(text_parts) if text_parts else "内容加载失败"
            wechat_html = build_wechat_text_html(title, get_date_cn(), f"<p>{fallback_content}</p>", tag)
            return push_to_wechat_draft(access_token, title, wechat_html, digest, cover_media_id)

        # Upload content images
        image_urls = []
        for img_path in image_paths:
            mid, wx_url = upload_wx_image(access_token, img_path)
            if wx_url:
                image_urls.append(wx_url)

        if not image_urls:
            return None

        wechat_html = build_image_article_html(image_urls)
    elif isinstance(content, str) and has_complex_visuals(content):
        # Legacy IMAGE MODE (old-style HTML with data viz)
        print(f"  [mode] IMAGE — has data viz elements")
        render_html = build_render_html(title, get_date_cn(), content, tag)
        image_paths = screenshot_and_split(render_html, tmpdir, num_parts=2)

        if not image_paths:
            print("  [warn] Screenshot failed, falling back to text mode")
            wechat_html = build_wechat_text_html(title, get_date_cn(), content, tag)
            return push_to_wechat_draft(access_token, title, wechat_html, digest, cover_media_id)

        image_urls = []
        for img_path in image_paths:
            mid, wx_url = upload_wx_image(access_token, img_path)
            if wx_url:
                image_urls.append(wx_url)

        if not image_urls:
            return None

        wechat_html = build_image_article_html(image_urls)
    else:
        # TEXT MODE: diary or plain text → inline-styled HTML
        print(f"  [mode] TEXT — plain text, pushing HTML directly")
        text_content = content if isinstance(content, str) else str(content)
        wechat_html = build_wechat_text_html(title, get_date_cn(), text_content, tag)

    # 3. Push draft
    return push_to_wechat_draft(access_token, title, wechat_html, digest, cover_media_id)


# ============================================================
# Main pipeline
# ============================================================
def main():
    day_num = get_day_number()
    date_str = get_date_str()
    date_cn = get_date_cn()

    print(f"{'='*55}")
    print(f"  JK养虾 Auto-Publish Pipeline v4")
    print(f"  Day {day_num:03d} | {date_str}")
    print(f"  Mode: 3 hotspot articles (JSON→rich HTML) + 1 diary")
    print(f"{'='*55}")

    # Step 1: Load hotspots
    print(f"\n--- Step 1: Load Hotspots ---")
    hotspots = load_hotspots()
    if not hotspots:
        print("[ERROR] No hotspots. Run update-hotspots.py first.")
        sys.exit(1)
    print(f"[ok] Loaded {len(hotspots)} hotspots")

    # Step 2: Select 3 topics
    print(f"\n--- Step 2: Select Topics ---")
    topics = select_topics(hotspots)
    if not topics or len(topics) < 2:
        print("[ERROR] Topic selection failed")
        sys.exit(1)
    topics = topics[:3]
    for i, t in enumerate(topics):
        print(f"  Topic {i+1}: {t['title']}")

    # Step 3: Generate articles
    # articles list: (title, content, digest, tag, is_diary)
    # content is dict (JSON) for hotspot articles, str for diary
    print(f"\n--- Step 3: Generate Articles ---")
    articles = []

    for i, topic in enumerate(topics):
        print(f"\n  [Article {i+1}/3] {topic['title']}")
        content = generate_hotspot_article(topic, hotspots, day_num, date_cn)
        if content:
            article_title = content.get("title", topic["title"]) if isinstance(content, dict) else topic["title"]
            articles.append((
                article_title,
                content,
                f"AI热点深度解读：{topic['topic'][:30]}",
                "AI深度解读",
                False,  # is_diary
            ))
            if isinstance(content, dict):
                print(f"  [ok] Generated V4 JSON: {len(content.get('sections', []))} sections")
            else:
                print(f"  [ok] Generated (fallback): {len(content)} chars")
        else:
            print(f"  [warn] Generation failed for topic {i+1}")

    # Generate diary
    print(f"\n  [Article 4/4] Diary")
    diary_title, diary_content = generate_diary(day_num, date_cn, hotspots)
    if diary_title and diary_content:
        articles.append((
            diary_title,
            diary_content,
            f"Day{day_num} 龙虾COO的工作日志",
            "龙虾养成日记",
            True,  # is_diary
        ))
        print(f"  [ok] Diary: {len(diary_content)} chars")

        # Save diary to website
        page_filename = f"day{day_num}.html"
        page_html = build_diary_page_html(day_num, diary_title, date_cn, diary_content)
        page_path = os.path.join(SITE_DIR, page_filename)
        with open(page_path, "w", encoding="utf-8") as f:
            f.write(page_html)
        print(f"  [ok] Website page saved: {page_filename}")

    # Step 4: Upload all to WeChat
    print(f"\n--- Step 4: Upload to WeChat ({len(articles)} articles) ---")
    access_token = get_wx_access_token()
    if not access_token:
        print("[skip] WeChat push skipped")
    else:
        with tempfile.TemporaryDirectory() as tmpdir:
            for i, (title, content, digest, tag, is_diary) in enumerate(articles):
                print(f"\n  --- Article {i+1}/{len(articles)}: {title} ---")
                art_dir = os.path.join(tmpdir, f"art_{i}")
                os.makedirs(art_dir)
                media_id = process_article(access_token, title, content, digest, i, art_dir, tag, is_diary=is_diary)
                if media_id:
                    print(f"  [ok] Pushed to draft: {title}")
                else:
                    print(f"  [warn] Failed: {title}")

    # Summary
    print(f"\n{'='*55}")
    print(f"  Pipeline Complete!")
    print(f"  Articles generated: {len(articles)}")
    for i, (t, _, _, tag, _) in enumerate(articles):
        print(f"    {i+1}. [{tag}] {t}")
    print(f"{'='*55}")


if __name__ == "__main__":
    main()
