# Card Collection：寶可夢 PSA 10 鑑定卡收藏儀表板

追蹤自己收藏的寶可夢鑑定卡**現在值多少錢**。系統每天自動到日本最大的球鞋與卡牌交易平台
SNKRDUNK 抓回真實成交紀錄，用成交當天的匯率換成新台幣，算出每張卡的市值、整體收藏的
未實現與已實現損益，以及資產走勢。

這是我自己每天在用的工具，涵蓋資料蒐集、清洗、估價、介面到自動化排程的完整流程。

---

## 它解決什麼問題

收藏鑑定卡的人通常只能手動記帳：買了什麼、花多少錢記在 Notion 或試算表裡，但**現在
值多少**得一張一張上網查，而且日本市場的價格是日圓，查到的又多半是「掛賣價」，不是
真的成交價。

這個專案把那件事自動化，並且刻意做到**不說謊**：

- 市值只用**真實成交價**，不用掛賣價。
- 每個價格旁邊都寫出它是「幾筆成交、哪段期間」撐起來的。兩筆撐起來的價格和二十筆
  撐起來的價格，不該長得一模一樣。
- 抓不到資料就顯示「沒有」，不用 0 或猜測值填空。

## 功能

| 頁面 | 做什麼 |
|---|---|
| **收藏總覽** `/` | 總市值、未實現／已實現損益、報酬率、資產走勢圖（7D／1M／3M／YTD／ALL）、卡圖牆。點卡片會打開明細抽屜，裡面的卡圖會隨滑鼠 3D 傾斜並有彩虹反光 |
| **持有品** `/holdings` | 逐筆對帳：購入日、成本、售出紀錄的新增、編輯與刪除 |
| **卡種對應** `/queue` | 把自己記帳時寫的卡名，對應到 SNKRDUNK 上的正確商品；系統會先列出候選讓我確認 |

背後還有：

- **每日自動更新**：Windows 工作排程器每天晚上跑一輪爬取，不需要開著瀏覽器。
- **斷線偵測**：每輪爬取結束會發一次心跳（heartbeat）給 healthchecks.io。哪天電腦沒開、
  排程沒跑，手機會主動收到通知。這是一種「死人開關（dead man's switch）」，專門抓「什麼
  都沒發生」這種最難察覺的失敗。
- **髒資料隔離**：認不出是「單張、PSA 10、這個卡種」的成交紀錄，一律放進待審區，附上
  原因，不參與任何計算。

## 系統架構

```
 Notion 匯出的 CSV ──一次性匯入──┐
                                 ▼
 SNKRDUNK 成交紀錄 ──每日爬取──▶ 資料清洗（白名單）──▶ SQLite ◀── FastAPI ──▶ 瀏覽器／手機
 臺灣銀行 日圓牌告 ──每日爬取──▶ 成交日匯率換算 ───────┘              │
                                                                     └ Jinja2 樣板＋原生 JS
 Windows 工作排程器 ──每天觸發──▶ scripts/crawl.py ──心跳──▶ healthchecks.io ──▶ 手機通知
```

| 層 | 技術 | 為什麼這樣選 |
|---|---|---|
| 後端 | Python 3.12、FastAPI、SQLite | 個人工具，單機就夠；SQLite 免安裝、整份資料庫就是一個檔案 |
| 前端 | Jinja2 伺服器端渲染、原生 CSS／JS | **沒有前端框架、沒有建置步驟、不載入任何外部資源**。走勢圖用手寫 SVG 畫，卡片特效也是自己寫 |
| 爬取 | httpx、curl_cffi | 臺灣銀行的網站會擋一般程式的請求，需要模擬 Chrome 的 TLS 指紋才連得上（ADR-0017） |
| 影像 | Pillow | 卡圖下載後自動裁掉四周的透明留白 |
| 測試 | pytest | 測試以錄下來的真實 API 回應回放，不需要連網 |
| 套件管理 | uv | |

## 工程上的取捨

這一段說明遇到問題時怎麼想、怎麼取捨。每一個決定都寫成一份架構決策
紀錄（ADR, Architecture Decision Record），放在 [`docs/adr/`](docs/adr/)，目前共 25 份。
其中幾個例子：

- **市值用 30 天成交中位數，不用最新一筆成交價**（[ADR-0002](docs/adr/0002-market-value-is-30-day-median.md)）
  鑑定卡成交很稀疏，多數卡一個月只有個位數成交，一筆急售或輸入錯誤就會讓總市值劇烈
  跳動，中位數比較能代表行情。同理也拿掉了「1 天」這個區間：對這種資產，單日走勢
  不是一條水平線就是假暴跌。
- **換匯鎖定成交當天的匯率，不用今天的匯率回頭重算**（[ADR-0006](docs/adr/0006-jpy-to-twd-at-sale-date-rate.md)）
  否則日圓一升一貶，過去所有成交的台幣價格都會跟著變，歷史走勢就失真了。
- **髒資料採白名單：寧可漏抓，不可污染**（[ADR-0004](docs/adr/0004-whitelist-data-cleaning.md)）
  即使平台提供 PSA 10 篩選，還是會混進「多張一組」（總價被當成單張價）、「下架但沒成交」
  這類資料，混進一筆就會拉偏中位數。只收高信心確認的資料，其餘隔離並附上原因，事後
  可以人工救回（[ADR-0016](docs/adr/0016-quarantine-can-recover.md)）。
- **走勢圖用「當時持有」計算，不用「今天持有」往回推**（[ADR-0003](docs/adr/0003-chart-uses-point-in-time-holdings.md)）
  已經賣掉的卡不該出現在它被賣掉之後的走勢裡；售出前的資料點也不該因為賣出而改變。
- **原始值優先（Raw-First）**：外部來的金額、卡號、系列代碼一律原樣保存，正規化後的值
  另存一欄。之後發現正規化規則錯了，隨時可以從原始值重算。
- **排程跑在本機，不用 GitHub Actions**（[ADR-0019](docs/adr/0019-daily-crawl-runs-on-a-local-scheduler.md)）
  資料庫在自己電腦上，而且雲端機房的 IP 比較容易被網站擋下。
- **不用現成的卡片特效套件，自己寫**（[ADR-0024](docs/adr/0024-card-drawer-tilt-is-hand-written.md)）
  評估過的兩個開源專案，一個是 GPL-3.0 授權，會傳染到這個公開 repo；另一個在 GitHub
  與 npm 上標示的授權不一致，還會帶進一整份框架執行環境。自己寫只要幾十行。

詞彙也有定義：「卡種」「持有品」「成交紀錄」「市值」「涵蓋率」等用語的確切意思，都寫在
[`CONTEXT.md`](CONTEXT.md)，程式碼、測試與文件都統一使用這些詞。

## 開發方式

- **測試驅動開發（TDD, Test-Driven Development）**：先寫會失敗的測試，再寫實作讓它通過。
  目前有 367 條測試，測試程式碼（約 5,900 行）比產品程式碼（約 3,600 行）還多。
- **測試名稱用中文寫行為**，例如 `test_賣出一張卡之後售出日之前的資料點完全不變`。測試
  失敗時，一眼就看得出壞掉的是哪個行為。
- **用 GitHub Issue 拆工作，每項改動走 Pull Request** 再合併（目前 27 張 issue、20 個已合併的 PR）。
- **不能違反的規則寫成文件**：[`docs/interface.md`](docs/interface.md) 列出介面改版時絕對
  不能違反的約束，例如「缺數字就讓它不存在，不顯示 0」，並標出哪些測試是守這些約束的
  紅線。

## 專案結構

```
src/card_collection/
├── snkrdunk.py、fx.py        # 外部資料來源：SNKRDUNK 成交紀錄、臺銀匯率
├── normalization.py           # 卡號、系列代碼的正規化（原始值另存）
├── market.py、trend.py        # 市值（30 天中位數）、逐日資產走勢
├── holdings.py、sales.py      # 持有品與售出
├── mapping.py                 # 卡種 ↔ SNKRDUNK 商品對應
├── crawl_runs.py、heartbeat.py# 爬取帳本、死人開關
├── api.py、app.py             # FastAPI 路由與組裝
├── templates/、static/        # Jinja2 樣板、CSS
scripts/                       # 每日爬取、補匯率、背景圖前處理
tests/                         # pytest，含錄下的真實 API 回應
docs/adr/                      # 25 份架構決策紀錄
```

---

## 在自己電腦上執行

需要先安裝 [uv](https://docs.astral.sh/uv/)（Python 專案與套件管理工具）。

```powershell
uv sync                                              # 安裝相依套件（只做一次）
uv run uvicorn card_collection.main:app --reload     # 啟動伺服器
```

看到 `Uvicorn running on http://127.0.0.1:8000` 之後，用瀏覽器打開 <http://127.0.0.1:8000>。
在 PowerShell 按 `Ctrl + C` 關閉。

> ⚠️ 首頁的「更新行情」按鈕會真的連到 SNKRDUNK 爬一輪資料（約 105 秒、對外發送 79 個
> 請求）。只想看畫面的話先別按。

<details>
<summary>用手機看（同一個區網）</summary>

1. 啟動時把 host 改成 `0.0.0.0`，接受區網內其他裝置的連線：

   ```powershell
   uv run uvicorn card_collection.main:app --host 0.0.0.0 --port 8000
   ```

2. 第一次執行時 Windows 防火牆會跳出詢問視窗，勾選**私人網路（Private）**並允許。
3. 用 `ipconfig` 查電腦的 `IPv4 位址`（通常長得像 `192.168.1.23`）。
4. 手機瀏覽器打開 `http://192.168.1.23:8000`（換成你查到的 IP）。

</details>

跑測試：

```powershell
uv run python -m pytest -q
```

## 文件索引

| 文件 | 內容 |
|---|---|
| [`CONTEXT.md`](CONTEXT.md) | 領域詞彙表（glossary） |
| [`docs/adr/`](docs/adr/) | 架構決策紀錄（ADR） |
| [`docs/operations.md`](docs/operations.md) | 每日自動爬取、排程、死人開關、常駐 web 服務 |
| [`docs/interface.md`](docs/interface.md) | 介面現況、不可違反的約束、測試分層 |
