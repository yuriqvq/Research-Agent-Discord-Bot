"""
cogs/research.py — 排程研究 + /update 命令
負責定時與手動觸發研究、去重、分派到 Discord 頻道。
"""

import asyncio
import logging
from datetime import datetime, time, timezone, timedelta
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.claude_runner import run_research
from core.dedup import process_report
from core.embed_builder import (
    CATEGORY_LABELS,
    build_news_embeds,
    build_summary_embeds,
    build_tracked_embeds,
    build_weather_embeds,
)
from core.og_fetcher import fetch_og_images
from core.report_parser import NON_NEWS_CATEGORIES, parse_report

log = logging.getLogger("research-bot.research")

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

# 排程時間（UTC）→ 台灣 00:00 / 07:00 / 12:00 / 19:00
SCHEDULE_TIMES = [
    time(16, 0, tzinfo=timezone.utc),   # 台灣 00:00
    time(23, 0, tzinfo=timezone.utc),   # 台灣 07:00
    time(4, 0, tzinfo=timezone.utc),    # 台灣 12:00
    time(11, 0, tzinfo=timezone.utc),   # 台灣 19:00
]

CATEGORY_CHOICES = [
    app_commands.Choice(name="🌏 國際新聞", value="international"),
    app_commands.Choice(name="🇹🇼 台灣新聞", value="taiwan"),
    app_commands.Choice(name="🔒 資安情報", value="security"),
    app_commands.Choice(name="🤖 AI/科技", value="ai_tech"),
    app_commands.Choice(name="🎮 遊戲資訊", value="gaming"),
    app_commands.Choice(name="☁️ 天氣預報", value="weather"),
    app_commands.Choice(name="🔎 追蹤議題", value="tracked"),
]


class ResearchCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._lock = asyncio.Lock()
        self._stage = ""  # 面板顯示的當前階段

    async def cog_load(self) -> None:
        self.scheduled_research.start()
        log.info("排程研究已啟動")

    async def cog_unload(self) -> None:
        self.scheduled_research.cancel()

    # --- 排程 ---

    @tasks.loop(time=SCHEDULE_TIMES)
    async def scheduled_research(self) -> None:
        enabled = await self.bot.db.get_state("enabled")
        if enabled == "0":
            log.info("排程觸發：總開關已停用，跳過")
            return
        log.info("排程觸發：開始全類別研究")
        await self._run_full_research("scheduled")

    @scheduled_research.before_loop
    async def _before_scheduled(self) -> None:
        await self.bot.wait_until_ready()

    # --- 斜線命令 ---

    @app_commands.command(name="update", description="手動觸發情報研究")
    @app_commands.describe(category="指定單一類別（留空=全部）")
    @app_commands.choices(category=CATEGORY_CHOICES)
    async def update_cmd(
        self,
        interaction: discord.Interaction,
        category: app_commands.Choice[str] | None = None,
    ) -> None:
        if self._lock.locked():
            await interaction.response.send_message("⏳ 研究正在進行中，請稍候。")
            return

        cat_value = category.value if category else None
        await interaction.response.defer(thinking=True)

        result = await self._run_full_research(
            trigger="manual" if not cat_value else "manual_category",
            category=cat_value,
        )

        try:
            if result["status"] == "success":
                await interaction.followup.send(
                    f"✅ 研究完成！新增 {result['new_count']} 則，重複 {result['dup_count']} 則。",
                    ephemeral=True,
                )
            elif result["status"] == "all_duplicate":
                await interaction.followup.send("ℹ️ 本次所有新聞皆已報導過，無新內容。")
            else:
                await interaction.followup.send(
                    f"❌ 研究失敗：{result.get('error', '未知錯誤')}", ephemeral=True,
                )
        except discord.NotFound:
            log.warning("interaction token 已過期，無法回覆（研究結果已推送至頻道）")

    # --- 核心研究流程 ---

    async def _run_full_research(
        self,
        trigger: str,
        category: str | None = None,
    ) -> dict:
        """
        執行完整研究流程。回傳結果 dict。
        可由排程、斜線命令、面板按鈕呼叫。
        """
        if self._lock.locked():
            return {"status": "busy", "error": "研究正在進行中"}

        async with self._lock:
            self._stage = "⏳ 準備中..."
            await self._refresh_panel()

            db = self.bot.db
            log_id = await db.log_start(trigger, category)

            try:
                # 取得追蹤議題
                topics_data = await db.get_all_topics()
                topics = [t["topic"] for t in topics_data] if topics_data else None

                # 執行 Claude CLI
                cat_label = category or "all"
                self._stage = f"🔍 正在搜尋新聞（{cat_label}）..."
                await self._refresh_panel()

                report = await run_research(topics=topics, category=category)

                # 存檔
                now_str = datetime.now().strftime("%Y%m%d_%H%M")
                report_path = REPORTS_DIR / f"{now_str}.md"

                # 追蹤議題不去重，直接推送
                if category == "tracked":
                    report_path.write_text(report, encoding="utf-8")
                    log.info(f"報告已存檔: {report_path}")
                    self._stage = "📤 正在推送追蹤議題..."
                    await self._refresh_panel()
                    await self._dispatch_report(report)
                    await db.log_finish(log_id, "success", str(report_path),
                                        new_count=1, dup_count=0)
                    log.info("追蹤議題推送完成")
                    self._stage = ""
                    await self._refresh_panel()
                    return {"status": "success", "new_count": 1, "dup_count": 0}

                # 去重
                self._stage = "📝 正在處理報告..."
                await self._refresh_panel()

                await db.purge_expired(retention_days=3)
                deduped, new_count, dup_count = await process_report(report, db)

                report_path.write_text(deduped, encoding="utf-8")
                log.info(f"報告已存檔: {report_path}")

                if new_count == 0:
                    await db.log_finish(log_id, "all_duplicate", str(report_path),
                                        new_count=0, dup_count=dup_count)
                    log.info("全部重複，跳過推送")
                    self._stage = ""
                    await self._refresh_panel()
                    return {"status": "all_duplicate", "new_count": 0, "dup_count": dup_count}

                # 分派推送
                self._stage = f"📤 正在推送 {new_count} 則新聞..."
                await self._refresh_panel()

                await self._dispatch_report(deduped)

                await db.log_finish(log_id, "success", str(report_path),
                                    new_count=new_count, dup_count=dup_count)

                log.info(f"研究完成：新增 {new_count}，重複 {dup_count}")

                # 全類別更新後，自動追加追蹤議題統整搜尋
                if not category and topics:
                    tracked_ch = await db.get_channel_id("tracked")
                    if tracked_ch:
                        await self._run_tracked_search(topics)

                self._stage = ""
                await self._refresh_panel()
                return {"status": "success", "new_count": new_count, "dup_count": dup_count}

            except Exception as e:
                log.error(f"研究失敗: {e}", exc_info=True)
                await db.log_finish(log_id, "failed", error_msg=str(e)[:500])
                self._stage = ""
                await self._refresh_panel()
                return {"status": "failed", "error": str(e)[:200]}

    async def _run_tracked_search(self, topics: list[str]) -> None:
        """全部更新後自動追加追蹤議題統整搜尋。"""
        try:
            self._stage = "🔎 正在搜尋追蹤議題..."
            await self._refresh_panel()

            report = await run_research(topics=topics, category="tracked")
            parsed = parse_report(report)

            if "tracked" not in parsed["sections"]:
                log.info("追蹤議題搜尋無結果")
                return

            channel_id = await self.bot.db.get_channel_id("tracked")
            if not channel_id:
                return
            channel = self.bot.get_channel(channel_id)
            if not channel:
                try:
                    channel = await self.bot.fetch_channel(channel_id)
                except Exception:
                    return

            embeds = build_tracked_embeds(parsed["sections"]["tracked"])
            if embeds:
                await self._send_embeds(channel, embeds)
                log.info(f"追蹤議題已推送：{len(embeds)} 個議題")
        except Exception as e:
            log.warning(f"追蹤議題搜尋失敗: {e}")

    async def _dispatch_report(self, report: str) -> None:
        """解析報告 → 擷取 OG 圖片 → 建構 embed → 發送到各頻道。"""
        parsed = parse_report(report)
        db = self.bot.db

        # 收集所有新聞項目的 OG 圖片
        all_items = []
        for cat_key, section in parsed["sections"].items():
            if cat_key not in NON_NEWS_CATEGORIES:
                all_items.extend(section.get("items", []))
        og_images = await fetch_og_images(all_items) if all_items else {}

        # 各類別推送
        for cat_key in ["international", "taiwan", "security", "ai_tech", "gaming", "weather", "tracked"]:
            if cat_key not in parsed["sections"]:
                continue

            section = parsed["sections"][cat_key]

            # 跳過全重複的一般新聞類別（天氣和追蹤用不同格式，不檢查 items）
            if cat_key not in NON_NEWS_CATEGORIES and cat_key != "tracked":
                if not section["items"] and "無新增內容" in section.get("raw", ""):
                    continue

            channel_id = await db.get_channel_id(cat_key)
            if not channel_id:
                log.warning(f"類別 [{cat_key}] 未綁定頻道，跳過")
                continue

            channel = self.bot.get_channel(channel_id)
            if not channel:
                try:
                    channel = await self.bot.fetch_channel(channel_id)
                except Exception:
                    log.warning(f"類別 [{cat_key}] 頻道 {channel_id} 不存在")
                    continue

            # 建構 embed
            if cat_key == "tracked":
                embeds = build_tracked_embeds(section)
            elif cat_key in NON_NEWS_CATEGORIES:
                embeds = build_weather_embeds(section)
            else:
                embeds = build_news_embeds(section, CATEGORY_LABELS[cat_key], og_images)

            if embeds:
                await self._send_embeds(channel, embeds)
                log.info(f"已推送 [{cat_key}] → #{channel.name}（{len(embeds)} 個 embed）")
                await asyncio.sleep(1)

        # 交叉推送：從所有類別收集 🔎 標記的追蹤議題新聞 → tracked 頻道
        tracked_channel_id = await db.get_channel_id("tracked")
        if tracked_channel_id and "tracked" not in parsed["sections"]:
            tracked_items = []
            for cat_key, section in parsed["sections"].items():
                if cat_key in NON_NEWS_CATEGORIES:
                    continue
                for item in section.get("items", []):
                    if "🔎" in item.get("title", ""):
                        tracked_items.append(item)
            if tracked_items:
                channel = self.bot.get_channel(tracked_channel_id)
                if not channel:
                    try:
                        channel = await self.bot.fetch_channel(tracked_channel_id)
                    except Exception:
                        channel = None
                if channel:
                    embeds = build_news_embeds(
                        {"items": tracked_items}, CATEGORY_LABELS["tracked"], og_images
                    )
                    if embeds:
                        await self._send_embeds(channel, embeds)
                        await asyncio.sleep(1)

        # 重要資訊彙整
        summary_channel_id = await db.get_channel_id("summary")
        if summary_channel_id:
            channel = self.bot.get_channel(summary_channel_id)
            if not channel:
                try:
                    channel = await self.bot.fetch_channel(summary_channel_id)
                except Exception:
                    channel = None
            if channel:
                embeds = build_summary_embeds(parsed, og_images)
                if embeds:
                    await self._send_embeds(channel, embeds)

    async def _send_embeds(self, channel: discord.TextChannel, embeds: list[discord.Embed]) -> None:
        """批次發送 embed（每批最多 10 個，間隔 1 秒）。"""
        for i in range(0, len(embeds), 10):
            batch = embeds[i:i + 10]
            try:
                await channel.send(embeds=batch)
            except discord.HTTPException as e:
                log.error(f"推送到 #{channel.name} 失敗: {e}")
            if i + 10 < len(embeds):
                await asyncio.sleep(1)

    async def _refresh_panel(self) -> None:
        """嘗試刷新控制面板（若已載入 PanelCog）。"""
        panel_cog = self.bot.get_cog("PanelCog")
        if panel_cog and hasattr(panel_cog, "refresh_panel"):
            try:
                await panel_cog.refresh_panel()
            except Exception as e:
                log.warning(f"面板刷新失敗: {e}")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ResearchCog(bot))
