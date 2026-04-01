"""
cogs/admin.py — 管理命令
/setchannel, /channels, /status
"""

import logging
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("research-bot.admin")

CATEGORY_CHOICES = [
    app_commands.Choice(name="🌏 國際新聞", value="international"),
    app_commands.Choice(name="🇹🇼 台灣新聞", value="taiwan"),
    app_commands.Choice(name="🔒 資安情報", value="security"),
    app_commands.Choice(name="🤖 AI/科技", value="ai_tech"),
    app_commands.Choice(name="🎮 遊戲資訊", value="gaming"),
    app_commands.Choice(name="☁️ 天氣預報", value="weather"),
    app_commands.Choice(name="📌 重要彙整", value="summary"),
    app_commands.Choice(name="🔎 追蹤議題", value="tracked"),
]

CATEGORY_NAMES = {c.value: c.name for c in CATEGORY_CHOICES}


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="setchannel", description="綁定類別到指定頻道")
    @app_commands.describe(category="類別", channel="目標頻道")
    @app_commands.choices(category=CATEGORY_CHOICES)
    @app_commands.default_permissions(administrator=True)
    async def setchannel_cmd(
        self,
        interaction: discord.Interaction,
        category: app_commands.Choice[str],
        channel: discord.TextChannel,
    ) -> None:
        await self.bot.db.set_channel(category.value, channel.id, interaction.guild_id)
        await interaction.response.send_message(
            f"✅ 已設定 {category.name} → {channel.mention}", ephemeral=True
        )
        log.info(f"頻道綁定: {category.value} → #{channel.name}")

    @app_commands.command(name="channels", description="顯示所有頻道綁定")
    async def channels_cmd(self, interaction: discord.Interaction) -> None:
        channels = await self.bot.db.get_all_channels()
        if not channels:
            await interaction.response.send_message("目前沒有任何頻道綁定。", ephemeral=True)
            return

        embed = discord.Embed(title="📺 頻道綁定", color=0x3498DB)
        for cat_key, cat_name in CATEGORY_NAMES.items():
            ch_id = channels.get(cat_key)
            value = f"<#{ch_id}>" if ch_id else "❌ 未設定"
            embed.add_field(name=cat_name, value=value, inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="status", description="顯示 Bot 運行狀態")
    async def status_cmd(self, interaction: discord.Interaction) -> None:
        db = self.bot.db
        last = await db.get_last_run()
        cache = await db.get_cache_stats()
        topics = await db.get_all_topics()
        channels = await db.get_all_channels()

        embed = discord.Embed(title="📊 Bot 狀態", color=0x2ECC71)

        # 運行狀態
        research_cog = self.bot.get_cog("ResearchCog")
        running = research_cog and research_cog._lock.locked()
        embed.add_field(
            name="🟢 狀態",
            value="⏳ 研究進行中" if running else "✅ 正常運行",
            inline=True,
        )

        # 上次執行
        if last:
            status_emoji = {"success": "✅", "failed": "❌", "running": "⏳", "all_duplicate": "ℹ️"}.get(last["status"], "❓")
            embed.add_field(
                name="📅 上次執行",
                value=f"{status_emoji} {last['status']} — {last['started_at'][:16]}",
                inline=True,
            )
        else:
            embed.add_field(name="📅 上次執行", value="尚無紀錄", inline=True)

        # 下次排程
        now_utc = datetime.now(timezone.utc)
        tw_tz = timezone(timedelta(hours=8))
        from cogs.research import SCHEDULE_TIMES
        next_times = []
        for t in SCHEDULE_TIMES:
            dt = datetime.combine(now_utc.date(), t, tzinfo=timezone.utc)
            if dt <= now_utc:
                dt = dt + timedelta(days=1)
            next_times.append(dt)
        next_run = min(next_times)
        next_tw = next_run.astimezone(tw_tz)
        embed.add_field(
            name="⏰ 下次排程",
            value=next_tw.strftime("%m/%d %H:%M (台灣)"),
            inline=True,
        )

        embed.add_field(name="💾 快取", value=f"{cache['total']} 則", inline=True)
        embed.add_field(name="🔎 追蹤", value=f"{len(topics)} 個議題", inline=True)
        embed.add_field(name="📺 頻道", value=f"{len(channels)}/8 已綁定", inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="test", description="測試所有頻道綁定是否正常")
    @app_commands.default_permissions(administrator=True)
    async def test_cmd(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        channels = await self.bot.db.get_all_channels()
        if not channels:
            await interaction.followup.send("❌ 尚未綁定任何頻道，請先用 `/setchannel` 設定。", ephemeral=True)
            return

        results = []
        all_categories = [
            ("summary", "📌 重要彙整"),
            ("international", "🌏 國際新聞"),
            ("taiwan", "🇹🇼 台灣新聞"),
            ("security", "🔒 資安情報"),
            ("ai_tech", "🤖 AI/科技"),
            ("gaming", "🎮 遊戲資訊"),
            ("weather", "☁️ 天氣預報"),
            ("tracked", "🔎 追蹤議題"),
        ]

        for cat_key, cat_name in all_categories:
            ch_id = channels.get(cat_key)
            if not ch_id:
                results.append(f"⬜ {cat_name} — 未綁定")
                continue

            channel = self.bot.get_channel(ch_id)
            if not channel:
                results.append(f"❌ {cat_name} — 頻道 ID {ch_id} 不存在或無權限")
                continue

            try:
                test_embed = discord.Embed(
                    title=f"🧪 頻道測試 — {cat_name}",
                    description=f"此頻道已綁定為 **{cat_name}** 的推送目標。\n測試由 {interaction.user.mention} 觸發。",
                    color=0x2ECC71,
                )
                test_embed.set_footer(text="Research Agent 測試訊息")
                await channel.send(embed=test_embed)
                results.append(f"✅ {cat_name} → <#{ch_id}>")
            except discord.Forbidden:
                results.append(f"❌ {cat_name} → <#{ch_id}> — 無發送權限")
            except Exception as e:
                results.append(f"❌ {cat_name} → <#{ch_id}> — {e}")

        passed = sum(1 for r in results if r.startswith("✅"))
        failed = sum(1 for r in results if r.startswith("❌"))
        unset = sum(1 for r in results if r.startswith("⬜"))

        embed = discord.Embed(
            title="🧪 頻道測試結果",
            description="\n".join(results),
            color=0x2ECC71 if failed == 0 else 0xED4245,
        )
        embed.set_footer(text=f"✅ {passed} 通過 • ❌ {failed} 失敗 • ⬜ {unset} 未綁定")
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
