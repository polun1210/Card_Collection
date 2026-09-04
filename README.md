# Card Collection

個人使用的寶可夢（Pokémon）PSA 10 鑑定卡追蹤儀表板。這是一個**跑在自己電腦上的個人工具**，
不是公開網站——領域詞彙看 `CONTEXT.md`，設計決策看 `docs/adr/`。

## 這個「網頁」是什麼

```
[瀏覽器 / 手機]  ──HTTP──▶  [uvicorn 本機伺服器 :8000]  ──讀──▶  [SQLite 資料庫 + 卡圖]
                              （跑在你的電腦上，預設只有自己連得到）
```

- **uvicorn**（web server，網頁伺服器）：把 Python 程式變成一個會回應瀏覽器的服務。
  它「開門營業」之後，瀏覽器才連得到。
- **port（連接埠）8000**：伺服器等待連線的「門牌號碼」，所以網址要帶 `:8000`。
- **127.0.0.1 / localhost**：意思是「這台電腦自己」，區網外或別人都連不到。

三個頁面：

| 網址 | 頁面 | 給誰用 |
|---|---|---|
| `/` | 收藏總覽 | 日常主畫面 |
| `/holdings` | 持有品逐筆明細 | 對帳 |
| `/queue` | 卡種對應 | 後台作業 |

## 事前準備（只做一次）

1. 安裝 [uv](https://docs.astral.sh/uv/)（Python 專案與套件管理工具）。
2. 在專案資料夾安裝相依套件：

   ```powershell
   uv sync
   ```

## 在自己電腦上開啟

1. 開 PowerShell，切到專案資料夾：

   ```powershell
   cd C:\Project\Card_Collection
   ```

2. 啟動伺服器：

   ```powershell
   uv run uvicorn card_collection.main:app --reload
   ```

   `--reload`（自動重載）是開發用的，改到程式碼會自動重啟。

3. 看到這一行就代表成功了：

   ```
   Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
   ```

4. 瀏覽器打開 <http://127.0.0.1:8000>。

5. 要關閉：回到 PowerShell 視窗按 `Ctrl + C`。資料庫檔案會留著，下次再啟動即可。

> ⚠️ 首頁的「更新行情」按鈕會真的連去 SNKRDUNK（日本網站）爬一輪資料（約 105 秒、
> 對外送 79 個請求）。只是想看畫面的話先別按，資料庫裡已有現成資料可顯示。

## 用手機看

手機和電腦連到同一個路由器時：

1. 啟動時把 host 改成 `0.0.0.0`（代表「接受區網內任何一台的連線」，不再只限自己這台）：

   ```powershell
   uv run uvicorn card_collection.main:app --host 0.0.0.0 --port 8000
   ```

2. 第一次執行時 Windows 防火牆會跳出詢問視窗，勾**私人網路（Private）**並允許。
3. 查電腦的區網 IP：

   ```powershell
   ipconfig
   ```

   找 `IPv4 位址`，通常長得像 `192.168.1.23`。
4. 手機瀏覽器打開 `http://192.168.1.23:8000`（換成你查到的 IP）。


## 相關文件

| 文件 | 內容 |
|---|---|
| `CONTEXT.md` | 領域詞彙表（glossary） |
| `docs/adr/` | 設計決策紀錄（ADR） |
| `docs/operations.md` | 每日自動爬取、排程、死人開關、常駐 web 服務 |
| `docs/interface.md` | 介面現況與 UIUX 交接 |

## 跑測試

```powershell
uv run python -m pytest -q
```
