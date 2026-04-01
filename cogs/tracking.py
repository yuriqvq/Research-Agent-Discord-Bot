"""
cogs/tracking.py — 議題追蹤命令
/track, /untrack, /topics
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("research-bot.tracking")


class TrackingCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="track", description="新增追蹤議題")
    @app_commands.describe(topic="要追蹤的議題名稱")
    async def track_cmd(self, interaction: discord.Interaction, topic: str) -> None:
        topic = topic.strip()[:100]
        if not topic:
            await interaction.response.send_message("❌ 議題名稱不能為空。", ephemeral=True)
            return

        success = await self.bot.db.add_topic(topic, interaction.user.id)
        if success:
            await interaction.response.send_message(f"✅ 已開始追蹤：**{topic}**", ephemeral=True)
            log.info(f"新增追蹤議題: {topic} (by {interaction.user})")
            await self._refresh_panel()
        else:
            await interaction.response.send_message(f"ℹ️ 「{topic}」已在追蹤清單中。", ephemeral=True)

    @app_commands.command(name="untrack", description="移除追蹤議題")
    @app_commands.describe(topic="要移除的議題名稱")
    async def untrack_cmd(self, interaction: discord.Interaction, topic: str) -> None:
        success = await self.bot.db.remove_topic(topic.strip())
        if success:
            await interaction.response.send_message(f"✅ 已停止追蹤：**{topic}**", ephemeral=True)
            log.info(f"移除追蹤議題: {topic} (by {interaction.user})")
            await self._refresh_panel()
        else:
            await interaction.response.send_message(f"❌ 找不到議題：「{topic}」", ephemeral=True)

    @untrack_cmd.autocomplete("topic")
    async def _untrack_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        topics = await self.bot.db.get_all_topics()
        return [
            app_commands.Choice(name=t["topic"][:100], value=t["topic"][:100])
            for t in topics
            if current.lower() in t["topic"].lower()
        ][:25]

    @app_commands.command(name="topics", description="列出所有追蹤中的議題")
    async def topics_cmd(self, interaction: discord.Interaction) -> None:
        topics = await self.bot.db.get_all_topics()
        if not topics:
            await interaction.response.send_message("📋 目前沒有追蹤的議題。", ephemeral=True)
            return

        embed = discord.Embed(
            title="🔎 追蹤議題清單",
            color=0x3498DB,
        )
        for i, t in enumerate(topics, 1):
            embed.add_field(
                name=f"{i}. {t['topic']}",
                value=f"新增者：<@{t['added_by']}>\n新增時間：{t['created_at'][:10]}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _refresh_panel(self) -> None:
        panel_cog = self.bot.get_cog("PanelCog")
        if panel_cog and hasattr(panel_cog, "refresh_panel"):
            try:
                await panel_cog.refresh_panel()
            except Exception:
                pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TrackingCog(bot))
