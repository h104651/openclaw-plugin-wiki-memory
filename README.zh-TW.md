# openclaw-plugin-wiki-memory

OpenClaw 記憶外掛，底層由 **Markdown 式 LLM Wiki** 搭配混合語意搜尋（embedding + FTS）驅動。

一層輕量 adapter，將 [`astor-wiki-memory`](https://github.com/h104651/astor-wiki-memory) CLI 工具封裝成 OpenClaw 可呼叫的工具。
Fail-open 設計：CLI 不可用或索引不存在時不回堵 agent，而是優雅降級。

## 功能

- **人類可讀的記憶** — 每筆記憶就是一則 Markdown 檔案，沒有二進位鎖定或專屬格式。
- **混合搜尋** — embedding + FTS 分數融合，召回相關內容。
- **容錯降級** — CLI 錯誤、索引遺失、工具不可用都不會讓 agent 卡住。
- **寫入後自動索引** — 可選的 `autoIndexAfterWrite`，每次寫入後自動重建索引，新記憶立即能被搜到。
- **10 個工具** — `memory_recall`, `wiki_recall`, `wiki_get`, `memory_store`, `wiki_crystallize`, `memory_update`, `memory_forget`, `wiki_index_update`, `memory_stats`, `wiki_stats`。

## 前置要求

- **Node.js 20+**（ESM）
- **OpenClaw**（測試於 v0.6+）
- **`astor-wiki-memory` CLI** — 實際負責索引與搜尋的二進位檔。從 [h104651/astor-wiki-memory](https://github.com/h104651/astor-wiki-memory) 安裝或自行編譯。
- **LLM Wiki** — 一組 Markdown 檔案的目錄。見上游專案的設定說明。

## 安裝

1. **安裝 CLI**（見上游 README）。
2. **將此 plugin clone 到 OpenClaw workspace 中**：
   ```bash
   cd /path/to/your/openclaw/workspace
   git clone https://github.com/h104651/openclaw-plugin-wiki-memory.git
   ```
3. **加入 `openclaw.json`**：
   ```json
   {
     "plugins": {
       "slots": {
         "memory": "astor-wiki-memory"
       },
       "allow": ["astor-wiki-memory"],
       "load": {
         "paths": ["/path/to/openclaw-plugin-wiki-memory"],
         "allowFail": true
       }
     }
   }
   ```
4. **（選擇性）設定 CLI 路徑** — 若 `astor-wiki-memory` 不在 `/usr/local/bin/astor-wiki-memory`：
   ```json
   {
     "plugins": {
       "config": {
         "astor-wiki-memory": {
           "cliPath": "/custom/path/astor-wiki-memory",
           "autoIndexAfterWrite": true
         }
       }
     }
   }
   ```

## 可用工具

| Tool | 說明 |
|------|------|
| `memory_recall` | 對 wiki 進行混合語意搜尋（embedding + FTS）。 |
| `wiki_recall` | 同上，但強制 token 預算。 |
| `wiki_get` | 依 ID 取回單一 chunk（來自 recall 結果）。 |
| `memory_store` | 以 Markdown 寫入新記憶頁；啟用 auto-index 時會自動重建索引。 |
| `wiki_crystallize` | 同 `memory_store`，wiki 環境下的別名。 |
| `memory_update` | 寫入取代或修正後的記憶。 |
| `memory_forget` | 安全護欄 — 不自動刪除，而是告知 agent 手動編輯 wiki 檔案。 |
| `wiki_index_update` | 手動從 Markdown 原始檔重建搜尋索引。 |
| `memory_stats` | 顯示索引 chunk 數量與 DB 路徑。 |
| `wiki_stats` | 同 `memory_stats`。 |

## 架構

```
┌─────────────┐   tool calls    ┌──────────────────────┐   exec    ┌──────────────────┐
│  OpenClaw   │ ──────────────▶ │  openclaw-plugin-    │ ────────▶ │ astor-wiki-memory │
│  Agent      │ ◀────────────── │  wiki-memory         │ ◀──────── │ CLI              │
└─────────────┘                 └──────────────────────┘           └──────────────────┘
                                                                         │
                                                                         ▼
                                                                ┌──────────────────┐
                                                                │  LLM Wiki        │
                                                                │  (Markdown files) │
                                                                │                  │
                                                                │  SQLite index     │
                                                                │  (hybrid search)  │
                                                                └──────────────────┘
```

- **事實來源**: Markdown 檔案。可直接用任何編輯器修改。
- **搜尋索引**: SQLite 為底，按需重建（`wiki_index_update`）或寫入後自動重建。
- **無向量 DB 綁定**: 索引是本地、基於檔案、可攜帶的。

## 致謝

此 plugin 的設計參考了 LLM 原生記憶領域的多個專案。未複製任何程式碼；架構、工具形狀與容錯降級方式皆為獨立開發。

### 知識庫結構

Wiki 目錄結構（`wiki/entities/`, `wiki/topics/`, `wiki/sources/`, `raw/`, `index.md`, `log.md`）繼承自：

- **[Karpathy's llm-wiki](https://gist.github.com/karpathy/193a681de9e5f5c1d049e1e2c290eff9)** — AI 維護 Markdown wiki 作為長期記憶的原始概念
- **[sdyckjq-lab/llm-wiki-skill](https://github.com/sdyckjq-lab/llm-wiki-skill)** (v3.3.0) — Karpathy 方法論的多平台實作，塑造了本專案的檔案佈局與工作流程

### 架構與 API 設計

- **[QMD](https://github.com/tobi/qmd)** — Markdown 收集、BM25/向量混合搜尋、MCP agent 工作流程
- **[Pyrite](https://github.com/markramm/pyrite)** — Markdown/YAML 事實來源 + SQLite 索引、MCP/REST 存取模式
- **[sage-wiki](https://github.com/xoai/sage-wiki)** — chunk 層級索引、Wiki Q&A、混合搜尋
- **[LanceDB](https://github.com/lancedb/lancedb)** — 作用域隔離與 recall/writeback API 設計靈感

## 授權條款

MIT
