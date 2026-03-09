#!/usr/bin/env python3
"""
JK养虾 Auto-Publish Pipeline v2.
1. Read today's hotspots
2. Two-step LLM generation: outline → full article (tighter logic)
3. Build stunning HTML page for website
4. Screenshot HTML → split into 2-3 images for WeChat
5. Upload images to WeChat → push as image-rich article
6. Commit to GitHub (triggers Vercel deploy)
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

# WeChat image article: max image width 1080px, recommended ~900px
WX_IMAGE_WIDTH = 900


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
# Step 1: Load hotspots
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
# Step 2: LLM calls
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


def generate_outline(day_num, date_cn, hotspots):
    """Step 2a: Generate article outline via LLM."""
    hotspot_lines = []
    for i, h in enumerate(hotspots[:8], 1):
        plat = h.get("platform", "搜索")
        hotspot_lines.append(f"{i}. [{h['heat_score']}分] {h['title']} (来源:{h['source']}/{plat})")
    hotspot_context = "\n".join(hotspot_lines)

    system_prompt = """你是「JK养虾」公众号的选题策划。你的任务是根据今日AI热点，策划一篇龙虾养成日记的大纲。

要求：
- 选择1-2个最有话题性的热点作为主切入点
- 用普通人能理解的角度解读，不要堆技术术语
- 每个小节要有明确的信息增量和观点
- 整体叙事要有递进逻辑，不是热点罗列

输出JSON格式（不要代码块标记）：
{
  "title": "Day N：标题（15字以内，口语化、有悬念）",
  "hook": "开头50字：用什么事实或热点抓住读者",
  "sections": [
    {"h2": "小节标题", "points": ["要讲的核心观点1", "要讲的核心观点2"], "data": "用什么具体数据支撑"},
    ...
  ],
  "egg_title": "彩蛋标题",
  "egg_idea": "彩蛋创意（数据对比、时间线、冷知识）",
  "skills": ["Skill #N：一句话总结", "Skill #N+1：一句话总结"],
  "cta": "CTA引导语"
}"""

    user_prompt = f"""今天是 {date_cn}，Day {day_num}（项目第{day_num}天，从2026年3月3日开始）。

今日AI热点Top 8：
{hotspot_context}

请策划一篇龙虾养成日记的大纲。Skill编号从#13开始（上一篇到了#12）。"""

    print("[info] Step 2a: Generating outline...")
    result = call_llm(system_prompt, user_prompt, max_tokens=1500, temperature=0.75)
    if not result:
        return None

    # Clean markdown fences
    result = re.sub(r'^```(?:json)?\s*\n?', '', result.strip())
    result = re.sub(r'\n?```\s*$', '', result)

    try:
        outline = json.loads(result)
        print(f"[ok] Outline: {outline.get('title', 'untitled')}")
        print(f"     Sections: {len(outline.get('sections', []))}")
        return outline
    except json.JSONDecodeError as e:
        print(f"[warn] Outline JSON parse failed: {e}")
        print(f"[warn] Raw: {result[:200]}")
        return None


def generate_article(day_num, date_cn, outline):
    """Step 2b: Generate full article from outline."""
    day_str = f"{day_num:03d}"
    outline_json = json.dumps(outline, ensure_ascii=False, indent=2)

    system_prompt = f"""你是「JK养虾」公众号的COO龙虾Agent，负责写「龙虾养成日记」。

## 写作身份
- 你是AI Agent（龙虾COO），老板是人类创业者
- 你用OpenClaw多Agent团队构建自动化内容生产系统
- 项目从零开始，Day {day_str}是第{day_num}天（起始日2026年3月3日）

## 写作风格（死守这些规则）
- 像跟朋友面对面聊天，口语化，有情绪起伏
- 短句打节奏，长句讲道理，交替使用
- 每段必须有一个独立观点或新信息，删掉所有废话
- 必须用具体数字/事实/案例支撑观点，禁止空洞描述
- 用<strong>加粗</strong>标注5-8处核心金句
- 禁止：「首先其次最后」「总而言之」「综上所述」「值得注意的是」「需要指出的是」
- 禁止：排比句、对偶句、四字成语堆砌
- 开头必须用一个具体事实/热点/数据开头，禁止用"今天"开头
- 技术概念要「翻译」成人话，假设读者是完全不懂技术的普通人
- 适当穿插比喻和类比，让抽象概念具象化（比如：大模型迭代速度比奶茶上新还快）

## 范文风格参考（模仿这种语感）
"3月4日凌晨，通义千问技术负责人林俊旸在X上发了一句话：'me stepping down. bye my beloved qwen.' 13500个赞，1700条评论，整个中文AI圈炸了。而我们的热点追踪系统，6点准时抓到了这条新闻..."

## 输出格式
输出纯HTML片段（不含head/body/style标签），使用：
- <h2>章节标题</h2>
- <p>段落</p>，核心观点用<strong>加粗</strong>
- <blockquote>引用/金句</blockquote>
- <ul><li>列表</li></ul>
- <hr> 分隔线
- <div class="egg-section"><h2>彩蛋标题</h2>内容</div>
- <div class="cta-box"><p><strong>CTA文案</strong></p></div>

禁止输出markdown、代码块标记、任何非HTML内容。"""

    user_prompt = f"""请按照以下大纲，写一篇2500-3500字的龙虾养成日记。

大纲：
{outline_json}

要求：
- 严格按大纲的结构和观点展开，但文字要自然流畅，不要像在念大纲
- 每个观点都要有具体的数据、案例或场景来支撑
- 技术概念要翻译成普通人能懂的话
- 结尾的Skill总结和彩蛋部分要精彩
- 文章字数2500-3500字，宁多不少"""

    print("[info] Step 2b: Generating full article...")
    result = call_llm(system_prompt, user_prompt, max_tokens=6000, temperature=0.72)
    if not result:
        return None, None

    # Clean up code fences
    result = re.sub(r'^```html?\s*\n?', '', result.strip())
    result = re.sub(r'\n?```\s*$', '', result)

    title = outline.get("title", f"Day {day_num}：AI日报")
    content = result

    print(f"[ok] Article generated: {title}")
    print(f"[info] Content length: {len(content)} chars")
    return title, content


# ============================================================
# Step 3: Build website HTML page (stunning layout)
# ============================================================
def build_page_html(day_num, title, date_cn, content):
    """Build a full HTML page with premium styling for website + screenshot."""
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
<span class="wechat-label">JK养虾 &middot; 文章预览</span>

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


def build_wechat_render_html(day_num, title, date_cn, content):
    """Build a self-contained HTML for WeChat screenshot rendering.

    This version embeds all fonts and styles inline so the screenshot
    looks perfect without external resources.
    """
    day_str = f"{day_num:03d}"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width={WX_IMAGE_WIDTH}">
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@300;400;500;700;900&family=Noto+Serif+SC:wght@400;600;700&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
  width: {WX_IMAGE_WIDTH}px;
  font-family: 'Noto Sans SC', -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif;
  background: #fafaf8;
  color: #1a1a1a;
  line-height: 1.9;
  -webkit-font-smoothing: antialiased;
}}
.wrapper {{ padding: 48px 56px 60px; }}
.tag {{
  display: inline-block;
  font-size: 12px; font-weight: 500;
  color: #0077aa; background: #e8f4f8;
  padding: 4px 14px; border-radius: 4px;
  margin-bottom: 18px; letter-spacing: 0.5px;
}}
h1 {{
  font-family: 'Noto Serif SC', Georgia, serif;
  font-size: 32px; font-weight: 700;
  line-height: 1.4; margin-bottom: 14px;
}}
.meta {{
  font-size: 13px; color: #888;
  margin-bottom: 36px; padding-bottom: 20px;
  border-bottom: 1px solid #e8e8e5;
}}
.meta span + span::before {{ content: " · "; }}
.content h2 {{
  font-family: 'Noto Serif SC', Georgia, serif;
  font-size: 22px; font-weight: 700;
  margin: 44px 0 18px;
  padding-bottom: 10px;
  border-bottom: 2px solid #0077aa;
}}
.content p {{
  margin-bottom: 18px; font-size: 16px; color: #333;
}}
.content strong {{ color: #1a1a1a; font-weight: 700; }}
.content blockquote {{
  border-left: 4px solid #0077aa;
  background: #e8f4f8;
  padding: 16px 20px; margin: 24px 0;
  border-radius: 0 8px 8px 0;
  font-size: 15px; color: #555;
}}
.content ul, .content ol {{ margin: 16px 0 24px 24px; }}
.content li {{ margin-bottom: 8px; font-size: 16px; color: #333; }}
.content hr {{
  border: none; border-top: 1px solid #e8e8e5;
  margin: 40px 0;
}}
.egg-section {{
  background: linear-gradient(135deg, #f0f8ff, #fff0f5);
  border-radius: 12px; padding: 32px 28px; margin: 40px 0;
}}
.egg-section h2 {{
  border: none !important; margin-top: 0 !important;
  font-size: 20px !important; padding-bottom: 0 !important;
}}
.cta-box {{
  background: #fff; border: 2px solid #0077aa;
  border-radius: 12px; padding: 28px 24px;
  margin: 32px 0; text-align: center;
}}
.cta-box p {{ font-weight: 500; font-size: 17px !important; color: #1a1a1a !important; }}
.footer {{
  margin-top: 48px; padding-top: 24px;
  border-top: 1px solid #e8e8e5; text-align: center;
}}
.footer p {{ font-size: 13px; color: #888; margin-bottom: 6px; }}
</style>
</head>
<body>
<div class="wrapper">
  <span class="tag">龙虾养成日记 #{day_str}</span>
  <h1>{title}</h1>
  <div class="meta">
    <span>Openclaw</span>
    <span>{date_cn}</span>
    <span>龙虾COO撰写</span>
  </div>
  <div class="content">
{content}
  </div>
  <div class="footer">
    <p><em>本文由 豆包AI + Openclaw COO Agent 联合撰写，老板审核发布。</em></p>
    <p><em>关注公众号「JK养虾」，每天一篇龙虾养成日记，见证AI从0到1的成长。</em></p>
  </div>
</div>
</body>
</html>"""


# ============================================================
# Step 4: HTML → Screenshot → Split images
# ============================================================
def screenshot_and_split(html_content, output_dir, num_parts=3):
    """Render HTML page and split into multiple images for WeChat.

    Uses Playwright to screenshot the full page, then Pillow to split.
    Returns list of image file paths.
    """
    from PIL import Image

    # Write HTML to temp file
    html_path = os.path.join(output_dir, "render.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    full_screenshot = os.path.join(output_dir, "full.png")

    # Use Python Playwright to take full-page screenshot
    print("[info] Taking full-page screenshot via Playwright...")
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
        print("[ERROR] Screenshot failed")
        return []

    # Split image
    img = Image.open(full_screenshot)
    width, height = img.size
    print(f"[ok] Full screenshot: {width}x{height}px")

    # Calculate split points: aim for num_parts, each ~1200-2000px tall
    # WeChat recommends images not exceeding ~2000px height
    max_height = 2000
    min_parts = max(2, math.ceil(height / max_height))
    actual_parts = max(min_parts, num_parts)
    part_height = math.ceil(height / actual_parts)

    image_paths = []
    for i in range(actual_parts):
        top = i * part_height
        bottom = min((i + 1) * part_height, height)
        if bottom - top < 100:  # Skip tiny remnants
            continue
        part = img.crop((0, top, width, bottom))
        part_path = os.path.join(output_dir, f"part_{i+1}.jpg")
        part.save(part_path, "JPEG", quality=95)
        image_paths.append(part_path)
        print(f"  [ok] Part {i+1}: {width}x{bottom-top}px -> {part_path}")

    return image_paths


# ============================================================
# Step 5: WeChat functions
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
        print("[ok] WeChat access token obtained")
        return data["access_token"]
    else:
        print(f"[warn] WeChat token failed: {data}")
        return None


def upload_wx_image(access_token, image_path):
    """Upload an image to WeChat as permanent material, returns media_id."""
    url = f"https://api.weixin.qq.com/cgi-bin/material/add_material?access_token={access_token}&type=image"
    with open(image_path, "rb") as f:
        resp = requests.post(
            url,
            files={"media": (os.path.basename(image_path), f, "image/jpeg")},
            timeout=30,
        )
    data = resp.json()
    if "media_id" in data:
        wx_url = data.get("url", "")
        print(f"  [ok] Uploaded {os.path.basename(image_path)} -> media_id={data['media_id'][:20]}...")
        return data["media_id"], wx_url
    else:
        print(f"  [warn] Upload failed: {data}")
        return None, None


def build_image_article_html(image_urls):
    """Build WeChat article HTML that displays images sequentially."""
    parts = []
    for url in image_urls:
        parts.append(
            f'<p style="text-align:center;margin:0;padding:0;line-height:0;">'
            f'<img src="{url}" style="width:100%;display:block;" />'
            f'</p>'
        )
    return "\n".join(parts)


def push_to_wechat_draft(access_token, title, wechat_html, day_num):
    """Push article to WeChat draft box."""
    url = f"https://api.weixin.qq.com/cgi-bin/draft/add?access_token={access_token}"

    # Truncate title to fit WeChat's 64-byte limit
    while len(title.encode("utf-8")) > 60:
        title = title[:-1]
    if len(title.encode("utf-8")) > 56:
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

    print(f"{'='*55}")
    print(f"  JK养虾 Auto-Publish Pipeline v2")
    print(f"  Day {day_str} | {date_str}")
    print(f"{'='*55}")

    # Step 1: Load hotspots
    print(f"\n--- Step 1: Load Hotspots ---")
    hotspots = load_hotspots()
    if not hotspots:
        print("[ERROR] No hotspots available. Run update-hotspots.py first.")
        sys.exit(1)
    print(f"[ok] Loaded {len(hotspots)} hotspots")

    # Step 2a: Generate outline
    print(f"\n--- Step 2a: Generate Outline ---")
    outline = generate_outline(day_num, date_cn, hotspots)
    if not outline:
        print("[ERROR] Outline generation failed")
        sys.exit(1)

    # Step 2b: Generate full article from outline
    print(f"\n--- Step 2b: Generate Article ---")
    title, content = generate_article(day_num, date_cn, outline)
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

    # Step 4: Screenshot → split images for WeChat
    print(f"\n--- Step 4: Screenshot & Split ---")
    render_html = build_wechat_render_html(day_num, title, date_cn, content)
    with tempfile.TemporaryDirectory() as tmpdir:
        image_paths = screenshot_and_split(render_html, tmpdir, num_parts=3)

        if not image_paths:
            print("[warn] Screenshot failed, falling back to text-only WeChat article")
            # Fallback: use inline-styled HTML directly
            wechat_html = f"<p>{content}</p>"
        else:
            # Step 5: Upload images & build WeChat article
            print(f"\n--- Step 5: Upload to WeChat ---")
            access_token = get_wx_access_token()
            if access_token:
                image_urls = []
                for img_path in image_paths:
                    media_id, wx_url = upload_wx_image(access_token, img_path)
                    if wx_url:
                        image_urls.append(wx_url)

                if image_urls:
                    wechat_html = build_image_article_html(image_urls)
                    print(f"[ok] Built image article with {len(image_urls)} images")
                else:
                    print("[warn] No images uploaded, using text fallback")
                    wechat_html = f"<p>{content}</p>"

                # Push to draft
                print(f"\n--- Step 6: Push Draft ---")
                media_id = push_to_wechat_draft(access_token, title, wechat_html, day_num)
                if media_id:
                    print("[ok] Article pushed to WeChat draft box")
                else:
                    print("[warn] WeChat push failed, but website page is saved")
            else:
                print("[skip] WeChat push skipped (no credentials)")

    # Summary
    print(f"\n{'='*55}")
    print(f"  Pipeline Complete!")
    print(f"  Title: {title}")
    print(f"  Page: {page_filename}")
    print(f"  Website: commit + push will trigger Vercel deploy")
    print(f"{'='*55}")


if __name__ == "__main__":
    main()
