#!/usr/bin/env python3
"""
JK养虾 Auto-Publish Pipeline v3.
Produces 4 articles daily:
  - 3 AI hotspot deep-dive articles (1 topic each, with data viz)
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

WX_IMAGE_WIDTH = 900

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
# Step 2: Generate single-topic deep-dive article
# ============================================================
HOTSPOT_ARTICLE_SYSTEM = """你是「JK养虾」公众号的主笔。公众号定位：用通俗易懂的方式，帮普通人看懂AI圈大事。

## 核心原则
- 本文只聚焦一个AI热点话题，写深写透
- 结构：事件本身 → 背景/原因 → 深度分析（独特视角）→ 对普通人的影响 → 实用建议
- 读者读完要有「学到东西了」的感觉，不是「又看了条新闻」

## 写作风格
- 像跟朋友面对面聊，口语化，有情绪
- 每段一个独立信息点，删掉废话
- 用具体数字/事实/引用支撑，禁止空洞描述
- 用<strong>加粗</strong>标注4-6处核心信息
- 禁止：「首先其次最后」「总而言之」「值得注意的是」
- 禁止：排比句、四字成语堆砌
- 开头用具体事实/数据切入，禁止用"今天"开头
- 技术概念翻译成人话

## 数据可视化（必须包含1-2个）
根据指定的data_visual类型，在文中插入对应HTML元素：

comparison_table:
<div class="data-table"><table><thead><tr><th>项目</th><th>A</th><th>B</th></tr></thead><tbody><tr><td>xxx</td><td>xxx</td><td>xxx</td></tr></tbody></table></div>

stat_cards:
<div class="stat-cards"><div class="stat-card"><div class="stat-number">数字</div><div class="stat-label">说明</div></div>...</div>

ranking:
<div class="ranking-chart"><div class="rank-item"><span class="rank-label">名称</span><div class="rank-bar" style="width:85%"><span>85分</span></div></div>...</div>

timeline:
<div class="timeline"><div class="timeline-item"><div class="timeline-date">日期</div><div class="timeline-content">事件</div></div>...</div>

highlight_box:
<div class="highlight-box"><span class="highlight-num">数字</span><span class="highlight-text">说明</span></div>

## 输出格式
纯HTML片段（不含head/body/style），使用h2/p/strong/blockquote/ul/li/hr和上述可视化元素。
末尾加：<div class="cta-box"><p><strong>CTA文案</strong></p></div>
禁止输出markdown。"""

def generate_hotspot_article(topic, hotspots, day_num, date_cn):
    """Generate a single deep-dive article for one topic."""
    idx = topic.get("hotspot_index", 0)
    hotspot = hotspots[idx] if idx < len(hotspots) else hotspots[0]

    user_prompt = f"""请围绕以下话题，写一篇1500-2000字的深度解读文章。

话题：{topic['topic']}
标题：{topic['title']}
独特角度：{topic['angle']}
可视化类型：{topic['data_visual']}
热点原文：{hotspot['title']}（来源：{hotspot.get('source', '')}）
日期：{date_cn}

要求：
- 只聚焦这一个话题，写深写透，提供独特视角和分析
- 包含1-2个指定类型的数据可视化HTML元素
- 结尾给读者1条实用建议
- 字数1500-2000字"""

    result = call_llm(HOTSPOT_ARTICLE_SYSTEM, user_prompt, max_tokens=4000, temperature=0.72)
    if not result:
        return None
    return clean_html(result)


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
def screenshot_and_split(html_content, output_dir, num_parts=3):
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
            page.wait_for_timeout(2000)
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
.data-table {{ margin:28px 0; overflow:hidden; border-radius:10px; border:1px solid #dde3e8; }}
.data-table table {{ width:100%; border-collapse:collapse; font-size:14px; }}
.data-table thead {{ background:linear-gradient(135deg,#0077aa,#005580); }}
.data-table thead th {{ color:#fff; padding:12px 16px; text-align:left; font-weight:600; }}
.data-table tbody tr {{ border-bottom:1px solid #eef1f4; }}
.data-table tbody tr:nth-child(even) {{ background:#f8fafb; }}
.data-table tbody td {{ padding:11px 16px; color:#333; }}
.stat-cards {{ display:flex; gap:14px; margin:28px 0; flex-wrap:wrap; }}
.stat-card {{ flex:1; min-width:120px; background:linear-gradient(135deg,#f0f8ff,#e8f4f8); border-radius:10px; padding:20px 16px; text-align:center; border:1px solid #d0e8f0; }}
.stat-number {{ font-size:28px; font-weight:900; color:#0077aa; display:block; line-height:1.2; }}
.stat-label {{ font-size:12px; color:#666; margin-top:6px; display:block; }}
.ranking-chart {{ margin:28px 0; }}
.rank-item {{ display:flex; align-items:center; margin-bottom:10px; }}
.rank-label {{ width:100px; font-size:13px; color:#333; font-weight:500; flex-shrink:0; }}
.rank-bar {{ background:linear-gradient(90deg,#0077aa,#00a5d4); height:28px; border-radius:6px; display:flex; align-items:center; padding:0 12px; }}
.rank-bar span {{ color:#fff; font-size:12px; font-weight:600; white-space:nowrap; }}
.timeline {{ margin:28px 0; padding-left:24px; border-left:3px solid #0077aa; }}
.timeline-item {{ margin-bottom:20px; position:relative; }}
.timeline-item::before {{ content:''; position:absolute; left:-30px; top:6px; width:12px; height:12px; background:#0077aa; border-radius:50%; border:2px solid #fff; box-shadow:0 0 0 2px #0077aa; }}
.timeline-date {{ font-size:12px; color:#0077aa; font-weight:700; margin-bottom:4px; }}
.timeline-content {{ font-size:14px; color:#333; line-height:1.6; }}
.highlight-box {{ display:flex; align-items:center; gap:16px; background:linear-gradient(135deg,#fff8e1,#fff3cd); border-left:4px solid #f5a623; border-radius:0 10px 10px 0; padding:20px 24px; margin:24px 0; }}
.highlight-num {{ font-size:36px; font-weight:900; color:#e67e00; flex-shrink:0; }}
.highlight-text {{ font-size:15px; color:#555; line-height:1.6; }}
.cta-box {{ background:#fff; border:2px solid #0077aa; border-radius:12px; padding:28px 24px; margin:32px 0; text-align:center; }}
.cta-box p {{ font-weight:500; font-size:17px !important; color:#1a1a1a !important; }}
"""

def build_render_html(title, date_cn, content, tag="AI深度解读"):
    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width={WX_IMAGE_WIDTH}">
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@300;400;500;700;900&family=Noto+Serif+SC:wght@400;600;700&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ width:{WX_IMAGE_WIDTH}px; font-family:'Noto Sans SC',-apple-system,sans-serif; background:#fafaf8; color:#1a1a1a; line-height:1.9; }}
.wrapper {{ padding:48px 56px 60px; }}
.tag {{ display:inline-block; font-size:12px; font-weight:500; color:#0077aa; background:#e8f4f8; padding:4px 14px; border-radius:4px; margin-bottom:18px; }}
h1 {{ font-family:'Noto Serif SC',Georgia,serif; font-size:32px; font-weight:700; line-height:1.4; margin-bottom:14px; }}
.meta {{ font-size:13px; color:#888; margin-bottom:36px; padding-bottom:20px; border-bottom:1px solid #e8e8e5; }}
.meta span + span::before {{ content:" · "; }}
.content h2 {{ font-family:'Noto Serif SC',Georgia,serif; font-size:22px; font-weight:700; margin:44px 0 18px; padding-bottom:10px; border-bottom:2px solid #0077aa; }}
.content p {{ margin-bottom:18px; font-size:16px; color:#333; }}
.content strong {{ color:#1a1a1a; font-weight:700; }}
.content blockquote {{ border-left:4px solid #0077aa; background:#e8f4f8; padding:16px 20px; margin:24px 0; border-radius:0 8px 8px 0; font-size:15px; color:#555; }}
.content ul,.content ol {{ margin:16px 0 24px 24px; }}
.content li {{ margin-bottom:8px; font-size:16px; color:#333; }}
.content hr {{ border:none; border-top:1px solid #e8e8e5; margin:40px 0; }}
{DATA_VIZ_CSS}
.footer {{ margin-top:48px; padding-top:24px; border-top:1px solid #e8e8e5; text-align:center; }}
.footer p {{ font-size:13px; color:#888; margin-bottom:6px; }}
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
def process_article(access_token, title, content, digest, theme_idx, tmpdir, tag="AI深度解读"):
    """Full pipeline for one article: cover → render → screenshot → upload → draft."""
    # 1. Generate cover image
    cover_path = os.path.join(tmpdir, f"cover_{theme_idx}.jpg")
    generate_cover_image(title, tag, theme_idx, cover_path)

    cover_media_id = None
    if access_token and os.path.exists(cover_path):
        mid, _ = upload_wx_image(access_token, cover_path)
        if mid:
            cover_media_id = mid

    # 2. Render HTML → screenshot → split
    render_html = build_render_html(title, get_date_cn(), content, tag)
    image_paths = screenshot_and_split(render_html, tmpdir, num_parts=2)

    if not image_paths or not access_token:
        return None

    # 3. Upload content images
    image_urls = []
    for img_path in image_paths:
        mid, wx_url = upload_wx_image(access_token, img_path)
        if wx_url:
            image_urls.append(wx_url)

    if not image_urls:
        return None

    # 4. Push draft
    wechat_html = build_image_article_html(image_urls)
    return push_to_wechat_draft(access_token, title, wechat_html, digest, cover_media_id)


# ============================================================
# Main pipeline
# ============================================================
def main():
    day_num = get_day_number()
    date_str = get_date_str()
    date_cn = get_date_cn()

    print(f"{'='*55}")
    print(f"  JK养虾 Auto-Publish Pipeline v3")
    print(f"  Day {day_num:03d} | {date_str}")
    print(f"  Mode: 3 hotspot articles + 1 diary")
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
    print(f"\n--- Step 3: Generate Articles ---")
    articles = []  # list of (title, content, digest, tag)

    for i, topic in enumerate(topics):
        print(f"\n  [Article {i+1}/3] {topic['title']}")
        content = generate_hotspot_article(topic, hotspots, day_num, date_cn)
        if content:
            articles.append((
                topic['title'],
                content,
                f"AI热点深度解读：{topic['topic'][:30]}",
                "AI深度解读"
            ))
            print(f"  [ok] Generated: {len(content)} chars")
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
            "龙虾养成日记"
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
            for i, (title, content, digest, tag) in enumerate(articles):
                print(f"\n  --- Article {i+1}/{len(articles)}: {title} ---")
                # Each article gets its own sub-directory to avoid file conflicts
                art_dir = os.path.join(tmpdir, f"art_{i}")
                os.makedirs(art_dir)
                media_id = process_article(access_token, title, content, digest, i, art_dir, tag)
                if media_id:
                    print(f"  [ok] Pushed to draft: {title}")
                else:
                    print(f"  [warn] Failed: {title}")

    # Summary
    print(f"\n{'='*55}")
    print(f"  Pipeline Complete!")
    print(f"  Articles generated: {len(articles)}")
    for i, (t, _, _, tag) in enumerate(articles):
        print(f"    {i+1}. [{tag}] {t}")
    print(f"{'='*55}")


if __name__ == "__main__":
    main()
