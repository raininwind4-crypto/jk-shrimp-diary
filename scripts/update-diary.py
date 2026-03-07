#!/usr/bin/env python3
"""
GitHub Actions diary updater for JK养虾.
Updates day counters and progress bars across the site.
"""
import os
import re
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
PROJECT_START_DATE = datetime(2026, 3, 3, tzinfo=CST)
SITE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_day_number():
    now = datetime.now(CST)
    delta = now.date() - PROJECT_START_DATE.date()
    return delta.days + 1


def get_date_str():
    return datetime.now(CST).strftime("%Y-%m-%d")


def update_diary_html(day_num):
    """Update diary.html day counter and progress bar."""
    path = os.path.join(SITE_DIR, "diary.html")
    if not os.path.exists(path):
        print(f"[warn] diary.html not found")
        return

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    day_str = f"{day_num:03d}"

    # Update hero Day counter
    content = re.sub(
        r'Day \d{3} · 持续更新中',
        f'Day {day_str} · 持续更新中',
        content
    )

    # Update recorded days stat
    content = re.sub(
        r'<span class="stat-num">\d+</span><span class="stat-label">已记录天数</span>',
        f'<span class="stat-num">{day_num}</span><span class="stat-label">已记录天数</span>',
        content
    )

    # Update progress bar text
    progress_pct = round(day_num / 365 * 100, 2)
    content = re.sub(
        r'Day \d{3} / 365',
        f'Day {day_str} / 365',
        content
    )
    # Update inline style width on progress-fill div
    content = re.sub(
        r'(style="width:) [\d.]+(%;")',
        f'\\g<1> {progress_pct}\\2',
        content
    )
    # Update .progress-fill CSS width
    content = re.sub(
        r'(\.progress-fill\s*\{[^}]*?width:)\s*[\d.]+(%)',
        lambda m: f'{m.group(1)} {progress_pct}{m.group(2)}',
        content
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[ok] diary.html updated to Day {day_str}")


def update_index_html(day_num):
    """Update index.html day counters."""
    path = os.path.join(SITE_DIR, "index.html")
    if not os.path.exists(path):
        print(f"[warn] index.html not found")
        return

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    day_str = f"{day_num:03d}"

    # Update hero status
    content = re.sub(
        r'第 \d{3} 天 · 持续进化中',
        f'第 {day_str} 天 · 持续进化中',
        content
    )

    # Update stat value
    content = re.sub(
        r'<span class="stat-value">\d{3}</span>\s*<span class="stat-label">运行天数</span>',
        f'<span class="stat-value">{day_str}</span>\n      <span class="stat-label">运行天数</span>',
        content
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[ok] index.html updated to Day {day_str}")


def main():
    day_num = get_day_number()
    date_str = get_date_str()
    day_str = f"{day_num:03d}"

    print(f"=== JK养虾 Diary Update ===")
    print(f"    Day {day_str} | {date_str}")
    print(f"===========================")

    update_diary_html(day_num)
    update_index_html(day_num)

    print("=== Diary update complete ===")


if __name__ == "__main__":
    main()
