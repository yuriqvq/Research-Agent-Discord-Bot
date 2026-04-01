"""
core/dedup.py — 新聞去重模組（SQLite 版）
核心邏輯提取自 dedup.py，改用 Database 取代 JSON 快取。
"""

import hashlib
import re

from core.report_parser import SEPARATOR, NON_NEWS_CATEGORIES, detect_category
from database.db import Database


def normalize_title(title: str) -> str:
    """正規化標題：去除空白、標點、轉小寫。"""
    title = title.strip()
    title = re.sub(r"[\s\u3000]+", " ", title)
    title = re.sub(r"[【】\[\]「」『』《》\(\)（）]", "", title)
    return title.lower()


def hash_title(title: str) -> str:
    """產生標題的 SHA256 雜湊（取前 16 字元）。"""
    normalized = normalize_title(title)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _parse_news_items(section_text: str) -> list[dict]:
    """從單一區塊中解析出個別新聞項目（帶 hash）。"""
    items = []
    parts = re.split(r"(?=▸)", section_text)
    for part in parts:
        part = part.strip()
        if not part.startswith("▸"):
            continue
        lines = part.split("\n")
        title_line = lines[0].lstrip("▸").strip()
        title_line = re.sub(r"^[🔴🟠🟡⚪]\s*(重大|重要|一般)[｜|]\s*", "", title_line)
        title_line = re.sub(r"^[✅⚠️]\s*[｜|]?\s*", "", title_line)
        title_clean = re.sub(r"^\[(.+)\]$", r"\1", title_line)
        items.append({
            "title": title_clean,
            "raw": part,
            "hash": hash_title(title_clean),
        })
    return items


async def process_report(report: str, db: Database) -> tuple[str, int, int]:
    """
    處理報告：解析各區塊的新聞、去重、重組。

    Args:
        report: 原始報告文字
        db: Database 實例

    Returns:
        (去重後報告, 新項目數, 重複項目數)
    """
    sections = report.split(SEPARATOR)
    new_count = 0
    dup_count = 0
    rebuilt_sections = []
    new_hashes = []

    for section in sections:
        stripped = section.strip()
        if not stripped:
            continue

        # 天氣類別不去重
        category = detect_category(stripped)
        if category in NON_NEWS_CATEGORIES:
            rebuilt_sections.append(stripped)
            continue

        items = _parse_news_items(stripped)
        if not items:
            rebuilt_sections.append(stripped)
            continue

        first_item_pos = stripped.find("▸")
        section_header = stripped[:first_item_pos].strip() if first_item_pos > 0 else ""

        new_items = []
        for item in items:
            if await db.is_duplicate(item["hash"]):
                dup_count += 1
            else:
                new_items.append(item)
                new_hashes.append((item["hash"], item["title"]))
                new_count += 1

        if new_items:
            parts = [section_header] if section_header else []
            parts.extend(item["raw"] for item in new_items)
            rebuilt_sections.append("\n\n".join(parts))
        elif section_header:
            rebuilt_sections.append(
                f"{section_header}\n\n（本時段無新增內容，先前已報導。）"
            )

    # 批次寫入新 hash
    if new_hashes:
        await db.add_hashes(new_hashes)

    deduped_report = ("\n\n" + SEPARATOR + "\n\n").join(rebuilt_sections)
    return deduped_report, new_count, dup_count
