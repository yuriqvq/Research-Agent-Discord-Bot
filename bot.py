#!/usr/bin/env python3
"""
bot.py — Research Agent Discord Bot 主程式
每日自動情報摘要系統，支援排程推送、手動更新、議題追蹤、控制面板。
"""

import asyncio
import logging
import sys
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv
import os

from database.db import Database

# 日誌設定
LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "bot.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("research-bot")

# Cog 列表
COG_EXTENSIONS = [
    "cogs.research",
    "cogs.tracking",
    "cogs.panel",
    "cogs.admin",
]


class ResearchBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(
            command_prefix="!",
            intents=intents,
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="每日情報",
            ),
        )
        self.db = Database()

    async def setup_hook(self) -> None:
        # 初始化資料庫
        await self.db.init()
        log.info("資料庫初始化完成")

        # 載入 Cogs
        for ext in COG_EXTENSIONS:
            try:
                await self.load_extension(ext)
                log.info(f"Cog 載入成功: {ext}")
            except Exception as e:
                log.error(f"Cog 載入失敗: {ext} — {e}")

        # 同步斜線命令
        synced = await self.tree.sync()
        log.info(f"已同步 {len(synced)} 個斜線命令")

    async def on_ready(self) -> None:
        log.info(f"Bot 已上線: {self.user} (ID: {self.user.id})")
        log.info(f"伺服器數量: {len(self.guilds)}")

    async def close(self) -> None:
        await self.db.close()
        await super().close()


async def main() -> None:
    load_dotenv()
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        log.error("DISCORD_TOKEN 未設定。請在 .env 檔案中設定。")
        sys.exit(1)

    bot = ResearchBot()
    async with bot:
        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
