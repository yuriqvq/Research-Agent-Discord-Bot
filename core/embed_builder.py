"""
core/embed_builder.py — Discord Embed 建構模組
將解析後的報告資料轉換為 discord.Embed 物件。
"""

from datetime import datetime, timezone

import discord

from core.og_fetcher import extract_first_url
from core.report_parser import NON_NEWS_CATEGORIES, parse_tracked, parse_weather

CATEGORY_LABELS = {
    "international": "🌏 國際新聞 / 地緣政治",
    "taiwan": "🇹🇼 台灣本地新聞",
    "security": "🔒 資安 / 漏洞 / CVE",
    "ai_tech": "🤖 AI / 科技趨勢",
    "weather": "☁️ 台灣天氣預報",
    "gaming": "🎮 遊戲資訊",
    "tracked": "🔎 追蹤議題",
}

IMPORTANCE_COLORS = {
    "🔴": 0xED4245,
    "🟠": 0xF0A500,
    "⚪": 0x95A5A6,
}

IMPORTANCE_LABELS = {
    "🔴": "🔴 重大",
    "🟠": "🟠 重要",
    "⚪": "⚪ 一般",
}

VERIFIED_LABELS = {
    "verified": "✅ 已驗證",
    "unverified": "⚠️ 待查證",
}

REGION_EMOJIS = {
    "北部": "🏙️",
    "中部": "🏞️",
    "南部": "🌴",
    "東部": "🏔️",
}


def build_news_embeds(
    section: dict,
    category_label: str,
    og_images: dict[str, str] | None = None,
) -> list[discord.Embed]:
    """建構新聞類別的 embed 列表（每則新聞一個 embed）。"""
    embeds = []
    og_images = og_images or {}
    now = datetime.now(timezone.utc)

    for item in section["items"]:
        first_url = extract_first_url(item.get("sources", ""))

        footer_parts = [IMPORTANCE_LABELS.get(item["importance"], "⚪ 一般")]
        if item.get("verified"):
            footer_parts.append(VERIFIED_LABELS.get(item["verified"], ""))
        footer_parts.append(category_label)

        embed = discord.Embed(
            title=item["title"][:256],
            description=item["description"][:4096],
            color=IMPORTANCE_COLORS.get(item["importance"], 0x95A5A6),
            timestamp=now,
        )
        if first_url:
            embed.url = first_url
        embed.set_footer(text=" • ".join(footer_parts))

        if first_url and first_url in og_images:
            embed.set_image(url=og_images[first_url])

        if item["sources"]:
            embed.add_field(name="🔗 來源", value=item["sources"][:1024], inline=False)

        embeds.append(embed)

    return embeds


def build_weather_embeds(section: dict) -> list[discord.Embed]:
    """建構天氣預報的 embed 列表（總覽 + 每區獨立 embed）。"""
    weather = parse_weather(section["raw"])
    now = datetime.now(timezone.utc)
    footer_text = f"資料來源：{weather['source'][:200]}" if weather["source"] else "中央氣象署"
    embeds = []

    # 總覽 embed
    desc_parts = []
    if weather["alert"]:
        desc_parts.append(weather["alert"])
    else:
        desc_parts.append("目前無特殊天氣警報")
    if weather["weekly"]:
        desc_parts.append(f"\n📆 **一週天氣展望**\n{weather['weekly']}")

    overview = discord.Embed(
        title="☁️ 台灣天氣預報",
        description="\n".join(desc_parts)[:4096],
        color=0xFEE75C,
        timestamp=now,
    )
    overview.set_footer(text=footer_text)
    embeds.append(overview)

    # 區域 embeds
    for region in weather["regions"]:
        region_emoji = REGION_EMOJIS.get(region["name"], "🗺️")
        embed = discord.Embed(
            title=f"{region_emoji} {region['name']}",
            color=0x3498DB,
            timestamp=now,
        )
        for city in region.get("cities", []):
            embed.add_field(
                name=f"📍 {city['name']}",
                value=city["details"][:1024] or "—",
                inline=True,
            )
        if embed.fields:
            embeds.append(embed)

    return embeds


def build_tracked_embeds(section: dict) -> list[discord.Embed]:
    """建構追蹤議題的 embed 列表（每個議題一個統整 embed）。"""
    topics = parse_tracked(section["raw"])
    now = datetime.now(timezone.utc)
    embeds = []

    for topic in topics:
        desc_parts = []
        if topic["summary"]:
            desc_parts.append(f"**📌 最新進展**\n{topic['summary']}")
        if topic["data"]:
            desc_parts.append(f"\n**📊 關鍵數據**\n{topic['data']}")
        if topic["sources"]:
            desc_parts.append(f"\n🔗 {topic['sources']}")

        embed = discord.Embed(
            title=f"🔎 {topic['name']}",
            description="\n".join(desc_parts)[:4096],
            color=0x5865F2,
            timestamp=now,
        )
        embed.set_footer(text="🔎 追蹤議題")
        embeds.append(embed)

    return embeds


def build_summary_embeds(
    parsed: dict,
    og_images: dict[str, str] | None = None,
) -> list[discord.Embed]:
    """建構重要資訊彙整（每則獨立 embed）。"""
    og_images = og_images or {}
    now = datetime.now(timezone.utc)
    collected = []

    # 收集 🔴 重大項目
    for cat_key, cat_label in CATEGORY_LABELS.items():
        if cat_key in NON_NEWS_CATEGORIES:
            continue
        section = parsed["sections"].get(cat_key)
        if not section or not section["items"]:
            continue
        for item in section["items"]:
            if item["importance"] == "🔴":
                collected.append((item, cat_label))

    # 若無 🔴，取各類別第一則 🟠
    if not collected:
        for cat_key, cat_label in CATEGORY_LABELS.items():
            if cat_key in NON_NEWS_CATEGORIES:
                continue
            section = parsed["sections"].get(cat_key)
            if not section or not section["items"]:
                continue
            important = [i for i in section["items"] if i["importance"] == "🟠"]
            if important:
                collected.append((important[0], cat_label))

    if not collected:
        return []

    embeds = []
    for item, cat_label in collected:
        first_url = extract_first_url(item.get("sources", ""))
        cat_emoji = cat_label.split()[0]

        desc = item["description"]
        if item["sources"]:
            desc += f"\n\n🔗 {item['sources']}"

        footer_parts = [IMPORTANCE_LABELS.get(item["importance"], "⚪ 一般")]
        if item.get("verified"):
            footer_parts.append(VERIFIED_LABELS.get(item["verified"], ""))
        footer_parts.append(cat_label)

        embed = discord.Embed(
            title=f"{cat_emoji} {item['title']}"[:256],
            description=desc[:4096],
            color=IMPORTANCE_COLORS.get(item["importance"], 0x95A5A6),
            timestamp=now,
        )
        if first_url:
            embed.url = first_url
        embed.set_footer(text=" • ".join(footer_parts))

        if first_url and first_url in og_images:
            embed.set_image(url=og_images[first_url])

        embeds.append(embed)

    return embeds
