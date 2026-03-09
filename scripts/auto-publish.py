#!/usr/bin/env python3
"""
JK养虾 Auto-Publish Pipeline.
1. Read today's hotspots
2. Select top topic + decide article type (diary vs hotspot analysis)
3. Generate article via LLM (Volcengine Doubao)
4. Build HTML page for website
5. Convert to WeChat-compatible HTML
6. Push to WeChat draft box
7. Commit to GitHub (triggers Vercel deploy)
"""
import json
import os
import re
import sys
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

# --- Style template ---
# placeholder: filled in from reading past articles
STYLE_PROMPT = ""  # will be set in main


def get_day_number():
    now = datetime.now(CST)
    delta = now.date() - PROJECT_START_DATE.date()
    return delta.days + 1


def get_date_str():
    return datetime.now(CST).strftime("%Y-%m-%d")


def get_date_cn():
    now = datetime.now(CST)
    return f"{now.year}年{now.month}月{now.day}日"


# ============================================================
# Step 1: Read today's hotspots
# ============================================================
def load_hotspots():
    """Load today's hotspot data."""
    json_path = os.path.join(SITE_DIR, "hotspots-latest.json")
    if not os.path.exists(json_path):
        print("[warn] hotspots-latest.json not found")
        return []
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("hotspots", [])


# ============================================================
# Step 2: Call LLM to generate article
# ============================================================
def call_llm(system_prompt, user_prompt, max_tokens=4000, temperature=0.7):
    """Call Volcengine Doubao API."""
    if not VOLCENGINE_API_KEY:
        print("[ERROR] VOLCENGINE_API_KEY not set")
        return None

    resp = requests.post(
        f"{VOLCENGINE_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {VOLCENGINE_API_KEY}",
            "Content-Type": "application/json",
        },
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
    else:
        print(f"[ERROR] LLM call failed: {json.dumps(data, ensure_ascii=False)[:300]}")
        return None


def generate_article(day_num, date_cn, hotspots):
    """Generate a full article using LLM."""
    day_str = f"{day_num:03d}"

    # Build hotspot context
    hotspot_lines = []
    for i, h in enumerate(hotspots[:8], 1):
        plat = h.get("platform", "搜索")
        hotspot_lines.append(f"{i}. [{h['heat_score']}分] {h['title']} (来源:{h['source']}/{plat})")
    hotspot_context = "\n".join(hotspot_lines)

    system_prompt = f"""你是「JK养虾」公众号的COO龙虾Agent。你负责每天写一篇「龙虾养成日记」。

## 写作身份
- 你是一个AI Agent（龙虾COO），你的老板是一个人类创业者
- 你在用AI工具（OpenClaw多Agent团队）构建一个自动化内容生产系统
- 整个项目是从零开始，每天记录进展，Day {day_str}是第{day_num}天
- 项目开始日期：2026年3月3日

## 写作风格（严格遵守）
- 口语化，像在跟朋友聊天，不要书面语
- 短句+长句交替，形成阅读节奏
- 每段都要有一个独立观点或信息增量，不要废话
- 用具体数字和事实，不要空洞描述
- 用**加粗**标注核心观点（每篇5-8处）
- 绝对不要用「首先、其次、最后、总而言之、综上所述」这种套话
- 不要用排比句式和对偶句式
- 每篇结尾要有「Skill #N」技能总结（延续上一篇的编号，上一篇到了Skill #12）
- 文章要有一个「彩蛋」部分，放有趣的花絮或数据对比
- 结尾有CTA引导关注

## 文章结构
1. 用一个热点事件或具体事实开头（不要用"今天"开头）
2. 交代背景，让不关注AI的读者也能看懂
3. 展开主题，分3-5个小节，每节有h2标题
4. 总结今天做了什么
5. 彩蛋部分
6. CTA引导关注

## 输出格式
输出纯HTML片段（不含head/body/style标签），使用以下HTML标签：
- <h2>章节标题</h2>
- <p>段落</p>，用<strong>加粗</strong>
- <blockquote>引用</blockquote>
- <ul><li>列表</li></ul> 或 <ol><li>有序列表</li></ol>
- <hr> 分隔线
- <div class="egg-section"><h2>彩蛋标题</h2><p>内容</p></div>
- <div class="cta-box"><p><strong>CTA文案</strong></p></div>

不要输出任何非HTML内容（不要markdown，不要代码块标记）。"""

    user_prompt = f"""今天是 {date_cn}，Day {day_str}。

今日AI热点Top 8：
{hotspot_context}

请根据今日热点，选择最有话题性的1-2个热点作为切入点，写一篇龙虾养成日记。

要求：
- 标题格式：Day {day_num}：[你起的标题，15字以内]
- 文章2000-3000字
- 结合热点谈我们AI团队的建设进展（可以是：系统优化、新功能上线、踩坑记录、行业观察等）
- Skill编号从#13开始，本篇增加2-3条新Skill
- 彩蛋要有趣，可以是数据对比、时间线、冷知识

请先输出一行标题（格式：TITLE: Day {day_num}：xxx），然后空一行，再输出HTML正文内容。"""

    print(f"[info] Calling LLM to generate article...")
    result = call_llm(system_prompt, user_prompt, max_tokens=4000, temperature=0.72)
    if not result:
        return None, None

    # Parse title and content
    lines = result.strip().split("\n")
    title = ""
    content_start = 0
    for i, line in enumerate(lines):
        if line.strip().startswith("TITLE:"):
            title = line.strip().replace("TITLE:", "").strip()
            content_start = i + 1
            break

    # Skip empty lines after title
    while content_start < len(lines) and not lines[content_start].strip():
        content_start += 1

    content = "\n".join(lines[content_start:])

    # Clean up: remove markdown code fences if LLM added them
    content = re.sub(r'^```html?\s*\n?', '', content)
    content = re.sub(r'\n?```\s*$', '', content)

    if not title:
        title = f"Day {day_num}：AI热点日报"

    print(f"[ok] Article generated: {title}")
    print(f"[info] Content length: {len(content)} chars")
    return title, content


# ============================================================
# Step 3: Build website HTML page
# ============================================================
def build_page_html(day_num, title, date_cn, content):
    """Build a full HTML page for the website."""
    day_str = f"{day_num:03d}"

    # Read CSS from day4.html template
    template_path = os.path.join(SITE_DIR, "day4.html")
    css_block = ""
    if os.path.exists(template_path):
        with open(template_path, "r", encoding="utf-8") as f:
            tmpl = f.read()
        css_match = re.search(r'<style>(.*?)</style>', tmpl, re.DOTALL)
        if css_match:
            css_block = css_match.group(1)

    if not css_block:
        css_block = ":root { --bg: #fafaf8; --text: #1a1a1a; }"

    page = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} | JK养虾</title>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@300;400;500;700;900&family=Noto+Serif+SC:wght@400;600;700&display=swap" rel="stylesheet">
<style>
{css_block}
</style>
</head>
<body>
<div class="article-wrapper">

<a href="diary.html" class="back-link">&larr; 返回日记列表</a>
<span class="wechat-label">JK养虾 · 文章预览</span>

<div class="article-header">
  <span class="article-tag">龙虾养成日记 #{day_str}</span>
  <h1>{title}</h1>
  <div class="article-meta">
    <span>Openclaw</span>
    <span>{date_cn}</span>
    <span>龙虾COO撰写</span>
  </div>
</div>

<div class="article-content">
{content}
</div>

<div class="article-footer">
  <p><em>本文由 豆包AI + Openclaw COO Agent 联合撰写，老板审核发布。</em></p>
  <p><em>关注公众号「JK养虾」，每天一篇龙虾养成日记，见证AI从0到1的成长。</em></p>
</div>

</div>
</body>
</html>"""
    return page


# ============================================================
# Step 4: Convert to WeChat-compatible HTML
# ============================================================
def convert_to_wechat_html(content):
    """Convert article content to WeChat inline-styled HTML."""
    html = content

    # Inline styles
    styles = {
        "h2": 'style="font-size:20px;font-weight:bold;color:#1a1a1a;margin:30px 0 15px;padding-bottom:8px;border-bottom:2px solid #07a;font-family:\'Noto Serif SC\',Georgia,serif;"',
        "p": 'style="margin-bottom:16px;font-size:16px;color:#333;line-height:1.9;"',
        "blockquote": 'style="border-left:4px solid #07a;background:#e8f4f8;padding:16px 20px;margin:24px 0;border-radius:0 8px 8px 0;font-size:15px;color:#555;"',
        "ul": 'style="margin:16px 0 24px 24px;"',
        "ol": 'style="margin:16px 0 24px 24px;"',
        "li": 'style="margin-bottom:8px;font-size:16px;color:#333;"',
        "hr": 'style="border:none;border-top:1px solid #e8e8e5;margin:40px 0;"',
    }

    # egg-section
    html = re.sub(
        r'<div class="egg-section">',
        '<div style="background:linear-gradient(135deg,#f0f8ff,#fff0f5);border-radius:12px;padding:32px 28px;margin:40px 0;">',
        html
    )
    # cta-box
    html = re.sub(
        r'<div class="cta-box">',
        '<div style="background:#ffffff;border:2px solid #07a;border-radius:12px;padding:28px 24px;margin:32px 0;text-align:center;">',
        html
    )

    # Apply styles to tags (skip already styled ones)
    for tag, style in styles.items():
        if tag == "hr":
            html = re.sub(r'<hr[^>]*/?>',  f'<hr {style}>', html)
        else:
            html = re.sub(
                rf'<{tag}(?:\s+[^>]*)?>',
                lambda m, t=tag, s=style: m.group(0) if 'style=' in m.group(0) else f'<{t} {s}>',
                html
            )

    # Remove remaining class attributes
    html = re.sub(r'\s+class="[^"]*"', '', html)

    # Wrap in container
    output = f"""<div style="max-width:720px;margin:0 auto;padding:20px 16px;font-family:-apple-system,'Noto Sans SC',sans-serif;color:#1a1a1a;line-height:1.9;">
{html}

<div style="margin-top:48px;padding-top:24px;border-top:1px solid #e8e8e5;text-align:center;">
<p style="font-size:13px;color:#888;margin-bottom:6px;line-height:1.9;"><em>本文由 豆包AI + Openclaw COO Agent 联合撰写，老板审核发布。</em></p>
<p style="font-size:13px;color:#888;margin-bottom:6px;line-height:1.9;"><em>关注公众号「JK养虾」，每天一篇龙虾养成日记，见证AI从0到1的成长。</em></p>
</div>
</div>"""
    return output


# ============================================================
# Step 5: Push to WeChat draft box
# ============================================================
def get_wx_access_token():
    """Get WeChat access token."""
    if not WX_APPID or not WX_APPSECRET:
        print("[warn] WX_APPID or WX_APPSECRET not set, skipping WeChat push")
        return None
    url = f"https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={WX_APPID}&secret={WX_APPSECRET}"
    resp = requests.get(url, timeout=10)
    data = resp.json()
    if "access_token" in data:
        print(f"[ok] WeChat access token obtained")
        return data["access_token"]
    else:
        print(f"[warn] WeChat token failed: {data}")
        return None


def push_to_wechat_draft(access_token, title, wechat_html, day_num):
    """Push article to WeChat draft box."""
    url = f"https://api.weixin.qq.com/cgi-bin/draft/add?access_token={access_token}"

    # Truncate title to fit WeChat's 64-byte limit
    title_bytes = title.encode("utf-8")
    if len(title_bytes) > 60:
        # Truncate safely
        while len(title.encode("utf-8")) > 56:
            title = title[:-1]
        title = title + "..."

    payload = {
        "articles": [{
            "title": title,
            "author": "JK养虾",
            "content": wechat_html,
            "digest": f"Day{day_num} 龙虾养成日记",
            "thumb_media_id": WX_COVER_MEDIA_ID,
            "need_open_comment": 1,
            "only_fans_can_comment": 0,
        }]
    }

    json_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    resp = requests.post(
        url,
        data=json_bytes,
        headers={"Content-Type": "application/json; charset=utf-8"},
        timeout=30,
    )
    data = resp.json()
    if "media_id" in data:
        print(f"[ok] WeChat draft created: {data['media_id']}")
        return data["media_id"]
    else:
        print(f"[warn] WeChat draft failed: {data}")
        return None


# ============================================================
# Main pipeline
# ============================================================
def main():
    day_num = get_day_number()
    date_str = get_date_str()
    date_cn = get_date_cn()
    day_str = f"{day_num:03d}"

    print(f"{'='*50}")
    print(f"  JK养虾 Auto-Publish Pipeline")
    print(f"  Day {day_str} | {date_str}")
    print(f"{'='*50}")

    # Step 1: Load hotspots
    print(f"\n--- Step 1: Load Hotspots ---")
    hotspots = load_hotspots()
    if not hotspots:
        print("[ERROR] No hotspots available. Run update-hotspots.py first.")
        sys.exit(1)
    print(f"[ok] Loaded {len(hotspots)} hotspots")

    # Step 2: Generate article via LLM
    print(f"\n--- Step 2: Generate Article ---")
    title, content = generate_article(day_num, date_cn, hotspots)
    if not title or not content:
        print("[ERROR] Article generation failed")
        sys.exit(1)

    # Step 3: Build website page
    print(f"\n--- Step 3: Build Website Page ---")
    page_filename = f"day{day_num}.html"
    page_html = build_page_html(day_num, title, date_cn, content)
    page_path = os.path.join(SITE_DIR, page_filename)
    with open(page_path, "w", encoding="utf-8") as f:
        f.write(page_html)
    print(f"[ok] Website page saved: {page_filename} ({len(page_html)} bytes)")

    # Step 4: Convert to WeChat HTML
    print(f"\n--- Step 4: Convert for WeChat ---")
    wechat_html = convert_to_wechat_html(content)
    print(f"[ok] WeChat HTML: {len(wechat_html)} chars")

    # Step 5: Push to WeChat draft
    print(f"\n--- Step 5: Push to WeChat ---")
    access_token = get_wx_access_token()
    if access_token:
        media_id = push_to_wechat_draft(access_token, title, wechat_html, day_num)
        if media_id:
            print(f"[ok] Article pushed to WeChat draft box")
        else:
            print(f"[warn] WeChat push failed, but website page is saved")
    else:
        print(f"[skip] WeChat push skipped (no credentials)")

    # Summary
    print(f"\n{'='*50}")
    print(f"  Pipeline Complete!")
    print(f"  Title: {title}")
    print(f"  Page: {page_filename}")
    print(f"  Website: commit + push will trigger Vercel deploy")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
