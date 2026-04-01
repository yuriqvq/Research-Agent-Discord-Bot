# Research-Agent-DiscordBot

自動搜尋新聞並以 Discord Embed 推送的情報摘要系統。透過 Claude Code CLI 搜尋網路、產生結構化報告，再分類推送至 Discord 頻道。

## 功能

- **每日自動排程** — 每天 4 次自動搜尋推送（台灣 00:00 / 07:00 / 12:00 / 19:00）
- **6 大新聞類別** — 國際、台灣、資安、AI/科技、遊戲、天氣
- **控制面板** — Discord 內互動按鈕面板，支援手動觸發、狀態查看、頻道設定
- **總開關** — 一鍵啟用/停用排程
- **議題追蹤** — 自訂追蹤主題，自動搜尋並統整摘要
- **新聞去重** — SQLite 快取，3 天內重複新聞自動過濾
- **OG 圖片** — 自動擷取新聞來源的 Open Graph 圖片
- **重要彙整** — 自動收集各類別重大新聞至獨立彙整頻道
- **失敗自動重試** — Claude CLI 超時或失敗時自動重試（最多 3 次）

## 預覽

```
控制面板按鈕佈局：
第一排：[⚡ 總開關] [🔄 全部更新] [📊 詳細狀態] [⚙️ 設定頻道]
第二排：[🌏 國際] [🇹🇼 台灣] [🔒 資安]
第三排：[🤖 AI] [🎮 遊戲] [☁️ 天氣]
第四排：[🔎 追蹤] [➕ 新增追蹤] [➖ 移除追蹤] [📋 追蹤清單]
```

## 前置需求

- **Python 3.10+**
- **[Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code)** — 已安裝並登入
- **Discord Bot Token** — 在 [Discord Developer Portal](https://discord.com/developers/applications) 建立

### Discord Bot 權限設定

在 Developer Portal 中：
1. **Bot** → 開啟 `Send Messages`、`Embed Links`、`Use Application Commands`
2. **OAuth2 → URL Generator** → 勾選 `bot` + `applications.commands`
3. 邀請連結加入你的 Discord 伺服器

## 安裝

```bash
git clone https://github.com/yourname/Research-Agent-DiscordBot.git
cd Research-Agent-DiscordBot

# 安裝 Python 依賴
pip install -r requirements.txt

# 設定環境變數
cp .env.example .env
# 編輯 .env，填入 DISCORD_TOKEN
```

## 設定

### 環境變數

| 變數 | 必填 | 說明 | 預設值 |
|------|------|------|--------|
| `DISCORD_TOKEN` | ✅ | Discord Bot Token | — |
| `CLAUDE_BIN` | — | Claude CLI 路徑 | `~/.local/bin/claude` |
| `CLAUDE_MODEL` | — | Claude 模型 | `claude-sonnet-4-6` |
| `CLAUDE_TIMEOUT` | — | CLI 超時秒數 | `600` |

### 排程時間

預設排程在 `cogs/research.py` 中的 `SCHEDULE_TIMES`（UTC 時間）：

```python
SCHEDULE_TIMES = [
    time(16, 0),   # 台灣 00:00
    time(23, 0),   # 台灣 07:00
    time(4, 0),    # 台灣 12:00
    time(11, 0),   # 台灣 19:00
]
```

可依需求修改。

## 啟動

### 手動執行

```bash
python3 bot.py
```

### systemd 服務（推薦）

```bash
# 編輯 research-bot.service，將 /path/to/Research-Agent 替換為實際路徑
sudo cp research-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now research-bot

# 查看狀態
sudo systemctl status research-bot
sudo journalctl -u research-bot -f
```

## Discord 內初始設定

Bot 上線後在 Discord 中執行：

1. **`/panel`** — 建立控制面板
2. **在面板按 ⚙️ 設定頻道** — 綁定 8 個類別到對應頻道
3. **按 🔄 全部更新** — 手動觸發第一次搜尋，確認一切正常

### 斜線命令

| 命令 | 說明 |
|------|------|
| `/panel` | 建立控制面板 |
| `/update [category]` | 手動觸發研究 |
| `/track <topic>` | 新增追蹤議題 |
| `/untrack <topic>` | 移除追蹤議題 |
| `/topics` | 列出追蹤議題 |
| `/setchannel <category> <#channel>` | 綁定類別到頻道 |
| `/channels` | 顯示所有頻道綁定 |
| `/status` | Bot 運行狀態 |
| `/test` | 測試所有頻道綁定 |

## 頻道類別

| 類別 | 內容 |
|------|------|
| 📌 重要彙整 | 各類別 🔴 重大項目 |
| 🌏 國際新聞 | 國際衝突、外交、經貿 |
| 🇹🇼 台灣新聞 | 政策、兩岸、經濟、社會 |
| 🔒 資安情報 | CVE、APT、惡意軟體 |
| 🤖 AI/科技 | AI 模型、半導體、開源 |
| 🎮 遊戲資訊 | 新作、電競、硬體 |
| ☁️ 天氣預報 | 四大區域天氣 + 警報 |
| 🔎 追蹤議題 | 自訂主題追蹤 |

## 專案結構

```
Research-Agent/
├── bot.py                  ← 主程式入口
├── requirements.txt        ← Python 依賴
├── .env                    ← 環境變數（不納入版控）
├── research-bot.service    ← systemd 服務範本
│
├── cogs/
│   ├── research.py         ← 排程研究 + /update
│   ├── panel.py            ← 控制面板（按鈕互動）
│   ├── tracking.py         ← /track, /untrack, /topics
│   └── admin.py            ← /setchannel, /status, /channels, /test
│
├── core/
│   ├── claude_runner.py    ← Claude CLI 非同步執行器
│   ├── report_parser.py    ← 報告解析（markdown → 結構化）
│   ├── embed_builder.py    ← Discord Embed 建構
│   ├── og_fetcher.py       ← OG 圖片擷取
│   └── dedup.py            ← 新聞去重（SQLite）
│
├── database/
│   └── db.py               ← SQLite CRUD
│
├── prompts/
│   ├── daily-research.md   ← 全類別 prompt
│   └── tracked-search.md   ← 追蹤議題 prompt
│
├── data/                   ← SQLite 資料庫（自動建立）
├── reports/                ← 報告存檔（自動建立）
└── logs/                   ← 日誌（自動建立）
```

## 自訂 Prompt

搜尋行為由 `prompts/` 中的 prompt 控制：

- **`daily-research.md`** — 主要 prompt，定義搜尋範圍、評級標準、輸出格式
- **`tracked-search.md`** — 追蹤議題專用輕量 prompt

可自行修改搜尋類別、語言、來源偏好等。

## License

MIT
