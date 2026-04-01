"""
core/claude_runner.py — Claude CLI 非同步執行器
使用 asyncio subprocess 呼叫 claude -p，不阻塞 Discord 事件迴圈。
"""

import asyncio
import logging
import os
from pathlib import Path

log = logging.getLogger("research-bot.claude")

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "daily-research.md"
TRACKED_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "tracked-search.md"
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", os.path.expanduser("~/.local/bin/claude"))
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
TIMEOUT_SECONDS = int(os.environ.get("CLAUDE_TIMEOUT", "600"))
MAX_RETRIES = 2
RETRY_DELAY = 30


def _build_prompt(topics: list[str] | None = None, category: str | None = None) -> str:
    """讀取 prompt 模板，注入追蹤議題，可選過濾類別。"""

    # 追蹤議題專用輕量 prompt（~50 行 vs 完整 302 行）
    if category == "tracked" and topics:
        prompt = TRACKED_PROMPT_PATH.read_text(encoding="utf-8")
        topic_list = "\n".join(f"- {t}" for t in topics)
        prompt = prompt.replace("{TRACKED_TOPICS}", topic_list)
        return prompt

    prompt = PROMPT_PATH.read_text(encoding="utf-8")

    # 注入追蹤議題（插入在 "## 3. 評級標準" 之前）
    if topics:
        topic_block = "\n### 2.7 🔎 追蹤主題\n\n"
        topic_block += "以下為用戶特別追蹤的主題，請在各領域搜尋時特別留意相關資訊：\n\n"
        for t in topics:
            topic_block += f"- {t}\n"
        topic_block += "\n若有找到與追蹤主題相關的新聞，請在對應類別中納入，並在標題中標注 `🔎`。\n"
        topic_block += "若追蹤主題的新聞不屬於既有類別，歸入最接近的類別中。\n\n"

        anchor = "## 3. 評級標準"
        if anchor in prompt:
            prompt = prompt.replace(anchor, topic_block + anchor)

    # 單類別過濾：在角色定義後加入限制指令
    if category:
        category_map = {
            "international": "🌏 國際新聞 / 地緣政治",
            "taiwan": "🇹🇼 台灣本地新聞",
            "security": "🔒 資安 / 漏洞 / CVE",
            "ai_tech": "🤖 AI / 科技趨勢",
            "gaming": "🎮 遊戲資訊",
            "weather": "☁️ 台灣天氣預報",
        }
        cat_name = category_map.get(category, category)
        filter_block = (
            f"\n> **本次僅搜尋「{cat_name}」類別。**\n"
            f"> 其他類別不需要搜尋，輸出格式中只包含此類別的區塊即可。\n\n"
        )
        anchor = "## 2. 搜尋範圍"
        if anchor in prompt:
            prompt = prompt.replace(anchor, anchor + "\n" + filter_block)

    return prompt


async def _call_claude(prompt: str, category: str | None) -> str:
    """單次呼叫 claude -p，回傳報告文字。"""
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    env.pop("CLAUDE_CODE_ENTRYPOINT", None)

    cmd = [
        CLAUDE_BIN,
        "-p", prompt,
        "--model", CLAUDE_MODEL,
        "--dangerously-skip-permissions",
        "--output-format", "text",
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=str(PROMPT_PATH.parent.parent),
        )

        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise TimeoutError(f"Claude CLI 超時（{TIMEOUT_SECONDS} 秒）")

    report = stdout.decode("utf-8", errors="replace")
    err_output = stderr.decode("utf-8", errors="replace")

    if err_output:
        log.warning(f"Claude stderr: {err_output[:500]}")

    if proc.returncode != 0:
        raise RuntimeError(
            f"Claude CLI 失敗（exit code {proc.returncode}）: {err_output[:300]}"
        )

    if not report.strip():
        raise RuntimeError("Claude CLI 回傳空結果")

    return report


async def run_research(
    topics: list[str] | None = None,
    category: str | None = None,
) -> str:
    """
    呼叫 claude -p 執行研究，失敗時自動重試。

    最多重試 MAX_RETRIES 次，間隔 RETRY_DELAY 秒。
    """
    prompt = _build_prompt(topics, category)
    cat_label = category or "all"
    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 2):  # 1 次原始 + MAX_RETRIES 次重試
        if attempt > 1:
            log.warning(f"第 {attempt} 次嘗試（category={cat_label}），{RETRY_DELAY} 秒後重試...")
            await asyncio.sleep(RETRY_DELAY)

        log.info(f"開始執行 Claude CLI（category={cat_label}，第 {attempt} 次）")

        try:
            report = await _call_claude(prompt, category)
            if attempt > 1:
                log.info(f"重試成功（第 {attempt} 次）")
            log.info(f"Claude CLI 完成，報告長度: {len(report)} 字元")
            return report
        except (TimeoutError, RuntimeError) as e:
            last_error = e
            log.warning(f"第 {attempt} 次失敗: {e}")

    raise last_error
