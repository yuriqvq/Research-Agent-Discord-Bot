"""
cogs/panel.py — 控制面板（持久化按鈕互動）
提供 /panel 建立面板，所有按鈕操作透過 custom_id 路由。
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("research-bot.panel")

AUTO_DELETE_SECONDS = 10


async def _auto_delete_interaction(interaction: discord.Interaction, seconds: int = AUTO_DELETE_SECONDS) -> None:
    """延遲後自動刪除 interaction 回覆。"""
    try:
        await asyncio.sleep(seconds)
        await interaction.delete_original_response()
    except (discord.NotFound, discord.HTTPException):
        pass


async def _auto_delete_msg(msg: discord.Message, seconds: int = AUTO_DELETE_SECONDS) -> None:
    """延遲後自動刪除 followup 訊息。"""
    try:
        await asyncio.sleep(seconds)
        await msg.delete()
    except (discord.NotFound, discord.HTTPException):
        pass


class PanelView(discord.ui.View):
    """持久化控制面板 View，timeout=None 確保不過期。"""

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(timeout=None)
        self.bot = bot

    # --- 第一排：主要操作 ---

    @discord.ui.button(
        label="總開關", emoji="⚡", style=discord.ButtonStyle.secondary,
        custom_id="panel:toggle_power", row=0,
    )
    async def btn_toggle_power(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        db = self.bot.db
        current = await db.get_state("enabled")
        new_state = "0" if current != "0" else "1"
        await db.set_state("enabled", new_state)
        label = "🟢 已啟用" if new_state == "1" else "🔴 已停用排程"
        await interaction.response.send_message(label)
        asyncio.create_task(_auto_delete_interaction(interaction))
        panel_cog = self.bot.get_cog("PanelCog")
        if panel_cog:
            await panel_cog.refresh_panel()

    @discord.ui.button(
        label="全部更新", emoji="🔄", style=discord.ButtonStyle.primary,
        custom_id="panel:update_all", row=0,
    )
    async def btn_update_all(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._handle_update(interaction, category=None)

    @discord.ui.button(
        label="詳細狀態", emoji="📊", style=discord.ButtonStyle.secondary,
        custom_id="panel:status", row=0,
    )
    async def btn_status(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        db = self.bot.db
        last = await db.get_last_run()
        cache = await db.get_cache_stats()
        topics = await db.get_all_topics()
        channels = await db.get_all_channels()

        embed = discord.Embed(title="📊 詳細狀態", color=0x3498DB)

        # 上次執行
        if last:
            status_emoji = {"success": "✅", "failed": "❌", "running": "⏳", "all_duplicate": "ℹ️"}.get(last["status"], "❓")
            embed.add_field(
                name="上次執行",
                value=(
                    f"觸發：{last['trigger']}\n"
                    f"狀態：{status_emoji} {last['status']}\n"
                    f"新增：{last['new_count']} / 重複：{last['dup_count']}\n"
                    f"時間：{last['started_at'][:16]}"
                ),
                inline=False,
            )
        else:
            embed.add_field(name="上次執行", value="尚無執行紀錄", inline=False)

        embed.add_field(name="快取", value=f"共 {cache['total']} 則", inline=True)
        embed.add_field(name="追蹤議題", value=f"{len(topics)} 個", inline=True)
        embed.add_field(name="已綁定頻道", value=f"{len(channels)}/8", inline=True)

        await interaction.response.send_message(embed=embed)
        asyncio.create_task(_auto_delete_interaction(interaction, 30))

    @discord.ui.button(
        label="設定頻道", emoji="⚙️", style=discord.ButtonStyle.secondary,
        custom_id="panel:setup", row=0,
    )
    async def btn_setup(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        view = ChannelSetupView(self.bot)
        embed = await view.build_embed()
        await interaction.response.send_message(embed=embed, view=view)
        asyncio.create_task(_auto_delete_interaction(interaction, 60))

    # --- 第二排：單類別更新 ---

    @discord.ui.button(
        label="國際", emoji="🌏", style=discord.ButtonStyle.secondary,
        custom_id="panel:update:international", row=1,
    )
    async def btn_international(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._handle_update(interaction, "international")

    @discord.ui.button(
        label="台灣", emoji="🇹🇼", style=discord.ButtonStyle.secondary,
        custom_id="panel:update:taiwan", row=1,
    )
    async def btn_taiwan(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._handle_update(interaction, "taiwan")

    @discord.ui.button(
        label="資安", emoji="🔒", style=discord.ButtonStyle.secondary,
        custom_id="panel:update:security", row=1,
    )
    async def btn_security(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._handle_update(interaction, "security")

    # --- 第三排：單類別更新（續）---

    @discord.ui.button(
        label="AI", emoji="🤖", style=discord.ButtonStyle.secondary,
        custom_id="panel:update:ai_tech", row=2,
    )
    async def btn_ai(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._handle_update(interaction, "ai_tech")

    @discord.ui.button(
        label="遊戲", emoji="🎮", style=discord.ButtonStyle.secondary,
        custom_id="panel:update:gaming", row=2,
    )
    async def btn_gaming(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._handle_update(interaction, "gaming")

    @discord.ui.button(
        label="天氣", emoji="☁️", style=discord.ButtonStyle.secondary,
        custom_id="panel:update:weather", row=2,
    )
    async def btn_weather(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._handle_update(interaction, "weather")

    # --- 第四排：議題追蹤 ---

    @discord.ui.button(
        label="追蹤", emoji="🔎", style=discord.ButtonStyle.secondary,
        custom_id="panel:update:tracked", row=3,
    )
    async def btn_tracked(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        topics = await self.bot.db.get_all_topics()
        if not topics:
            await interaction.response.send_message("❌ 尚未設定追蹤議題，請先用 ➕ 新增。")
            asyncio.create_task(_auto_delete_interaction(interaction))
            return
        await self._handle_update(interaction, "tracked")

    @discord.ui.button(
        label="新增追蹤", emoji="➕", style=discord.ButtonStyle.success,
        custom_id="panel:track_add", row=3,
    )
    async def btn_track_add(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(AddTopicModal(self.bot))

    @discord.ui.button(
        label="移除追蹤", emoji="➖", style=discord.ButtonStyle.danger,
        custom_id="panel:track_remove", row=3,
    )
    async def btn_track_remove(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        topics = await self.bot.db.get_all_topics()
        if not topics:
            await interaction.response.send_message("目前沒有追蹤的議題。")
            asyncio.create_task(_auto_delete_interaction(interaction))
            return
        view = RemoveTopicView(self.bot, topics)
        await interaction.response.send_message("選擇要移除的議題：", view=view)
        asyncio.create_task(_auto_delete_interaction(interaction, 30))

    @discord.ui.button(
        label="追蹤清單", emoji="📋", style=discord.ButtonStyle.secondary,
        custom_id="panel:topics", row=3,
    )
    async def btn_topics(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        topics = await self.bot.db.get_all_topics()
        if not topics:
            await interaction.response.send_message("📋 目前沒有追蹤的議題。")
            asyncio.create_task(_auto_delete_interaction(interaction))
            return
        lines = [f"**{i}.** {t['topic']}" for i, t in enumerate(topics, 1)]
        embed = discord.Embed(
            title="🔎 追蹤議題清單",
            description="\n".join(lines),
            color=0x3498DB,
        )
        await interaction.response.send_message(embed=embed)
        asyncio.create_task(_auto_delete_interaction(interaction, 30))

    # --- 共用邏輯 ---

    async def _handle_update(self, interaction: discord.Interaction, category: str | None) -> None:
        research_cog = self.bot.get_cog("ResearchCog")
        if not research_cog:
            await interaction.response.send_message("❌ Research 模組未載入。")
            asyncio.create_task(_auto_delete_interaction(interaction))
            return

        if research_cog._lock.locked():
            await interaction.response.send_message("⏳ 研究正在進行中，請稍候。")
            asyncio.create_task(_auto_delete_interaction(interaction))
            return

        await interaction.response.defer(thinking=True)

        trigger = "panel" if not category else "panel_category"
        result = await research_cog._run_full_research(trigger=trigger, category=category)

        try:
            if result["status"] == "success":
                msg = await interaction.followup.send(
                    f"✅ 完成！新增 {result['new_count']} 則，重複 {result['dup_count']} 則。",
                    wait=True,
                )
            elif result["status"] == "all_duplicate":
                msg = await interaction.followup.send(
                    "ℹ️ 本次所有新聞皆已報導過，無新內容。", wait=True,
                )
            else:
                msg = await interaction.followup.send(
                    f"❌ 研究失敗：{result.get('error', '未知錯誤')}",
                    wait=True,
                )
            asyncio.create_task(_auto_delete_msg(msg))
        except discord.NotFound:
            log.warning("interaction token 已過期，無法回覆（研究結果已推送至頻道）")


class AddTopicModal(discord.ui.Modal, title="➕ 新增追蹤議題"):
    """新增追蹤議題的 Modal 輸入框。"""

    topic_input = discord.ui.TextInput(
        label="議題名稱",
        placeholder="例如：Switch 2、GTA 6",
        max_length=100,
    )

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        topic = self.topic_input.value.strip()
        if not topic:
            await interaction.response.send_message("❌ 議題名稱不能為空。")
            asyncio.create_task(_auto_delete_interaction(interaction))
            return

        success = await self.bot.db.add_topic(topic, interaction.user.id)
        if success:
            await interaction.response.send_message(f"✅ 已開始追蹤：**{topic}**")
            asyncio.create_task(_auto_delete_interaction(interaction))
            panel_cog = self.bot.get_cog("PanelCog")
            if panel_cog:
                await panel_cog.refresh_panel()
        else:
            await interaction.response.send_message(f"ℹ️ 「{topic}」已在追蹤清單中。")
            asyncio.create_task(_auto_delete_interaction(interaction))


class RemoveTopicView(discord.ui.View):
    """移除追蹤議題的 Select Menu。"""

    def __init__(self, bot: commands.Bot, topics: list[dict]) -> None:
        super().__init__(timeout=120)
        self.bot = bot
        options = [
            discord.SelectOption(label=t["topic"][:100], value=str(t["id"]))
            for t in topics[:25]
        ]
        self.select = discord.ui.Select(
            placeholder="選擇要移除的議題",
            options=options,
            min_values=1,
            max_values=min(len(options), 25),
        )
        self.select.callback = self._on_select
        self.add_item(self.select)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        removed = []
        topics = await self.bot.db.get_all_topics()
        topic_map = {str(t["id"]): t["topic"] for t in topics}
        for topic_id in self.select.values:
            topic_name = topic_map.get(topic_id)
            if topic_name and await self.bot.db.remove_topic(topic_name):
                removed.append(topic_name)

        if removed:
            names = "、".join(f"**{n}**" for n in removed)
            await interaction.response.send_message(f"✅ 已移除：{names}")
            asyncio.create_task(_auto_delete_interaction(interaction))
            panel_cog = self.bot.get_cog("PanelCog")
            if panel_cog:
                await panel_cog.refresh_panel()
        else:
            await interaction.response.send_message("❌ 移除失敗。")
            asyncio.create_task(_auto_delete_interaction(interaction))
        self.stop()


class ChannelSetupView(discord.ui.View):
    """頻道設定介面（類別 Select + 頻道 Select + 儲存按鈕）。"""

    CATEGORIES = [
        ("international", "🌏 國際新聞"),
        ("taiwan", "🇹🇼 台灣新聞"),
        ("security", "🔒 資安情報"),
        ("ai_tech", "🤖 AI/科技"),
        ("gaming", "🎮 遊戲資訊"),
        ("weather", "☁️ 天氣預報"),
        ("summary", "📌 重要彙整"),
        ("tracked", "🔎 追蹤議題"),
    ]

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(timeout=300)
        self.bot = bot
        self._selected_category: str | None = None
        self._selected_channel: discord.TextChannel | None = None

    async def build_embed(self) -> discord.Embed:
        channels = await self.bot.db.get_all_channels()
        embed = discord.Embed(title="⚙️ 頻道設定", color=0x3498DB)
        lines = []
        for cat_key, cat_name in self.CATEGORIES:
            ch_id = channels.get(cat_key)
            if ch_id:
                lines.append(f"{cat_name} → <#{ch_id}> ✅")
            else:
                lines.append(f"{cat_name} → （未設定）❌")
        embed.description = "\n".join(lines)
        embed.set_footer(text="選擇類別和頻道後按「💾 儲存」")
        return embed

    @discord.ui.select(
        placeholder="選擇類別",
        options=[
            discord.SelectOption(label=name, value=key)
            for key, name in CATEGORIES
        ],
        row=0,
    )
    async def category_select(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        self._selected_category = select.values[0]
        cat_name = dict(self.CATEGORIES).get(self._selected_category, self._selected_category)
        await interaction.response.send_message(f"已選擇類別：{cat_name}，請選擇頻道。")
        asyncio.create_task(_auto_delete_interaction(interaction, 5))

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        placeholder="選擇頻道",
        channel_types=[discord.ChannelType.text],
        row=1,
    )
    async def channel_select(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect) -> None:
        self._selected_channel = select.values[0]
        await interaction.response.send_message(f"已選擇頻道：<#{self._selected_channel.id}>")
        asyncio.create_task(_auto_delete_interaction(interaction, 5))

    @discord.ui.button(label="儲存", emoji="💾", style=discord.ButtonStyle.success, row=2)
    async def save_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not self._selected_category or not self._selected_channel:
            await interaction.response.send_message("❌ 請先選擇類別和頻道。")
            asyncio.create_task(_auto_delete_interaction(interaction, 5))
            return

        await self.bot.db.set_channel(
            self._selected_category,
            self._selected_channel.id,
            interaction.guild_id,
        )
        cat_name = dict(self.CATEGORIES).get(self._selected_category, self._selected_category)
        await interaction.response.send_message(
            f"✅ 已設定 {cat_name} → <#{self._selected_channel.id}>",
        )
        asyncio.create_task(_auto_delete_interaction(interaction))

        # 刷新面板
        panel_cog = self.bot.get_cog("PanelCog")
        if panel_cog:
            await panel_cog.refresh_panel()


class PanelCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._panel_view = PanelView(bot)

    async def cog_load(self) -> None:
        # 恢復持久化 View
        self.bot.add_view(self._panel_view)
        log.info("控制面板 View 已掛載")

    @app_commands.command(name="panel", description="建立控制面板（每個 server 一個）")
    @app_commands.default_permissions(administrator=True)
    async def panel_cmd(self, interaction: discord.Interaction) -> None:
        embed = await self._build_panel_embed()
        msg = await interaction.channel.send(embed=embed, view=self._panel_view)
        await self.bot.db.set_state("panel_message_id", str(msg.id))
        await self.bot.db.set_state("panel_channel_id", str(msg.channel.id))
        await interaction.response.send_message("✅ 控制面板已建立！")
        asyncio.create_task(_auto_delete_interaction(interaction))
        log.info(f"控制面板建立於 #{interaction.channel.name} (msg_id={msg.id})")

    async def _build_panel_embed(self) -> discord.Embed:
        """動態生成面板 Embed。"""
        db = self.bot.db
        last = await db.get_last_run()
        topics = await db.get_all_topics()
        channels = await db.get_all_channels()
        tw_tz = timezone(timedelta(hours=8))

        embed = discord.Embed(title="📡 Research Agent 控制面板", color=0x2B2D31)

        # 總開關狀態
        enabled = await db.get_state("enabled")
        is_enabled = enabled != "0"
        power_label = "🟢 已啟用" if is_enabled else "🔴 已停用排程"

        # 狀態（用 _stage 判斷，不用 _lock，因為最後刷新時 lock 尚未釋放）
        research_cog = self.bot.get_cog("ResearchCog")
        stage = getattr(research_cog, "_stage", "") if research_cog else ""
        if stage:
            embed.add_field(name="狀態", value=f"{power_label}｜{stage}", inline=True)
        else:
            status_text = f"{power_label}｜待命中" if is_enabled else power_label
            embed.add_field(name="狀態", value=status_text, inline=True)

        # 上次更新
        if last:
            status_map = {
                "success": "✅",
                "failed": "❌",
                "running": "⏳",
                "all_duplicate": "ℹ️",
            }
            emoji = status_map.get(last["status"], "❓")
            ts = last["started_at"][:16].replace("T", " ")
            count_info = f"{last['new_count']} 則新聞" if last["new_count"] else "無新內容"
            embed.add_field(
                name="📅 上次更新",
                value=f"{ts} — {emoji} {count_info}",
                inline=False,
            )
        else:
            embed.add_field(name="📅 上次更新", value="尚無紀錄", inline=False)

        # 下次排程
        now_utc = datetime.now(timezone.utc)
        from cogs.research import SCHEDULE_TIMES
        next_times = []
        for t in SCHEDULE_TIMES:
            dt = datetime.combine(now_utc.date(), t, tzinfo=timezone.utc)
            if dt <= now_utc:
                dt = dt + timedelta(days=1)
            next_times.append(dt)
        next_run = min(next_times)
        next_tw = next_run.astimezone(tw_tz)
        delta = next_run - now_utc
        hours = int(delta.total_seconds() // 3600)
        minutes = int((delta.total_seconds() % 3600) // 60)
        embed.add_field(
            name="⏰ 下次排程",
            value=f"{next_tw.strftime('%m/%d %H:%M')}（{hours}h{minutes}m 後）",
            inline=True,
        )

        # 追蹤議題
        if topics:
            topic_preview = "、".join(t["topic"] for t in topics[:5])
            if len(topics) > 5:
                topic_preview += f"...（共 {len(topics)} 個）"
            embed.add_field(name="🔎 追蹤議題", value=topic_preview, inline=False)
        else:
            embed.add_field(name="🔎 追蹤議題", value="無", inline=False)

        # 追蹤頻道
        tracked_ch = channels.get("tracked")
        if tracked_ch:
            embed.add_field(name="📌 追蹤頻道", value=f"<#{tracked_ch}>", inline=True)

        embed.set_footer(text="點選按鈕操作 • Research Agent")
        return embed

    async def refresh_panel(self) -> None:
        """刷新控制面板 Embed。"""
        db = self.bot.db
        msg_id = await db.get_state("panel_message_id")
        ch_id = await db.get_state("panel_channel_id")
        if not msg_id or not ch_id:
            return

        channel = self.bot.get_channel(int(ch_id))
        if not channel:
            return

        try:
            msg = await channel.fetch_message(int(msg_id))
            embed = await self._build_panel_embed()
            await msg.edit(embed=embed, view=self._panel_view)
            log.info("面板已自動刷新")
        except discord.NotFound:
            log.warning("面板訊息已刪除，清除狀態")
            await db.set_state("panel_message_id", "")
            await db.set_state("panel_channel_id", "")
        except Exception as e:
            log.warning(f"面板刷新失敗: {e}")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PanelCog(bot))
