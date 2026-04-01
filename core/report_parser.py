"""
core/report_parser.py — 報告解析模組
從 Claude 產生的 markdown 報告中解析出結構化資料。
直接提取自 dispatcher.py 的解析邏輯。
"""

import re

CATEGORY_PATTERNS = [
    ("weather", re.compile(r"☁️|天氣預報")),
    ("international", re.compile(r"🌏|國際新聞|地緣政治")),
    ("taiwan", re.compile(r"🇹🇼|台灣.{0,2}新聞")),
    ("security", re.compile(r"🔒|資安|漏洞|CVE")),
    ("ai_tech", re.compile(r"🤖|AI|科技趨勢")),
    ("gaming", re.compile(r"🎮|遊戲資訊")),
    ("tracked", re.compile(r"🔎|追蹤主題")),
]

NON_NEWS_CATEGORIES = {"weather", "tracked"}

SEPARATOR = "━━━━━━━━━━━━━━━━━━━━"

IMPORTANCE_ORDER = {"🔴": 0, "🟠": 1, "⚪": 2}


def detect_category(text: str) -> str | None:
    """只檢查前 3 行（標題區域），避免內文關鍵字誤判類別。"""
    header = "\n".join(text.split("\n")[:3])
    for key, pattern in CATEGORY_PATTERNS:
        if pattern.search(header):
            return key
    return None


def parse_news_item(raw: str) -> dict:
    """從單則新聞的 raw text 解析出結構化資料。"""
    lines = raw.split("\n")

    title_line = lines[0].lstrip("▸").strip()
    importance = "⚪"
    for tag in IMPORTANCE_ORDER:
        if tag in title_line:
            importance = tag
            break
    title = re.sub(r"^[🔴🟠⚪]\s*(重大|重要|一般)[｜|]\s*", "", title_line)

    verified = None
    if title.startswith("✅"):
        verified = "verified"
        title = re.sub(r"^✅\s*[｜|]?\s*", "", title)
    elif title.startswith("⚠️"):
        verified = "unverified"
        title = re.sub(r"^⚠️\s*[｜|]?\s*", "", title)

    desc_lines = []
    sources = ""
    for line in lines[1:]:
        stripped = line.strip()
        if stripped.startswith("🔗"):
            sources = stripped[1:].strip()
        elif not sources and stripped:
            desc_lines.append(stripped)

    return {
        "importance": importance,
        "verified": verified,
        "title": title,
        "description": "\n".join(desc_lines),
        "sources": sources,
        "raw": raw,
    }


def parse_items(section_text: str) -> list[dict]:
    """從區塊中解析所有新聞項目。"""
    items = []
    parts = re.split(r"(?=▸)", section_text)
    for part in parts:
        part = part.strip()
        if not part.startswith("▸"):
            continue
        items.append(parse_news_item(part))
    return items


def parse_weather(raw: str) -> dict:
    """解析天氣區塊為結構化資料（區域制 + 城市明細 + 一週展望）。"""
    regions = []
    alert = ""
    weekly = ""
    source = ""

    lines = raw.split("\n")
    alert_lines = []
    weekly_lines = []
    in_alert = False
    in_weekly = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("⚠️"):
            in_alert = True
            in_weekly = False
            alert_lines.append(stripped)
        elif stripped.startswith("📆"):
            in_weekly = True
            in_alert = False
        elif stripped.startswith("🗺️") or stripped.startswith("🔗"):
            in_alert = False
            in_weekly = False
            if stripped.startswith("🔗"):
                source = stripped[1:].strip()
        else:
            if in_alert and stripped:
                alert_lines.append(stripped)
            elif in_weekly and stripped:
                weekly_lines.append(stripped)

    alert = "\n".join(alert_lines) if alert_lines else ""
    weekly = "\n".join(weekly_lines) if weekly_lines else ""

    region_parts = re.split(r"(?=🗺️)", raw)
    for rpart in region_parts:
        rpart = rpart.strip()
        if not rpart.startswith("🗺️"):
            continue
        rlines = rpart.split("\n")
        region_name = rlines[0].lstrip("🗺️").strip()
        cities = []
        city_parts = re.split(r"(?=📍)", "\n".join(rlines[1:]))
        for cpart in city_parts:
            cpart = cpart.strip()
            if not cpart.startswith("📍"):
                continue
            clines = cpart.split("\n")
            city_name = clines[0].lstrip("📍").strip()
            detail_lines = [
                l.strip() for l in clines[1:]
                if l.strip() and not l.strip().startswith("🔗")
            ]
            cities.append({"name": city_name, "details": "\n".join(detail_lines)})
        regions.append({"name": region_name, "cities": cities})

    return {"regions": regions, "alert": alert, "weekly": weekly, "source": source}


def parse_tracked(raw: str) -> list[dict]:
    """解析追蹤議題區塊為統整摘要列表。"""
    topics = []
    parts = re.split(r"(?=🏷️)", raw)
    for part in parts:
        part = part.strip()
        if not part.startswith("🏷️"):
            continue

        lines = part.split("\n")
        topic_name = lines[0].replace("🏷️", "").strip()

        summary_lines = []
        data_lines = []
        sources = ""
        in_summary = False
        in_data = False

        for line in lines[1:]:
            stripped = line.strip()
            if stripped.startswith("📌"):
                in_summary = True
                in_data = False
                rest = stripped.replace("📌", "").strip()
                if rest and rest != "最新進展":
                    summary_lines.append(rest)
            elif stripped.startswith("📊"):
                in_data = True
                in_summary = False
                rest = stripped.replace("📊", "").strip()
                if rest and rest != "關鍵數據":
                    data_lines.append(rest)
            elif stripped.startswith("🔗"):
                in_summary = False
                in_data = False
                sources = stripped[1:].strip()
            else:
                if in_summary and stripped:
                    summary_lines.append(stripped)
                elif in_data and stripped:
                    data_lines.append(stripped)

        topics.append({
            "name": topic_name,
            "summary": "\n".join(summary_lines),
            "data": "\n".join(data_lines),
            "sources": sources,
        })

    return topics


def parse_report(report: str) -> dict:
    """解析完整報告為結構化資料。"""
    sections = report.split(SEPARATOR)
    result = {"header": "", "footer": "", "sections": {}}

    for section in sections:
        stripped = section.strip()
        if not stripped:
            continue

        category = detect_category(stripped)
        if category:
            items = parse_items(stripped) if category not in NON_NEWS_CATEGORIES else []
            first_item = stripped.find("▸")
            header = stripped[:first_item].strip() if first_item > 0 else stripped.split("\n")[0]
            result["sections"][category] = {
                "header": header,
                "items": items,
                "raw": stripped,
            }
        elif "每日情報摘要" in stripped or "📅" in stripped:
            result["header"] = stripped
        elif "報告產生時間" in stripped or "⏰" in stripped:
            result["footer"] = stripped

    return result
