# 操作指引

這份文件涵蓋**讓系統每天自己跑起來**要做的事：註冊排程、常駐服務、設定死人開關
（dead man's switch），以及出事時去哪裡查。

決策的**理由**不在這裡，在 `docs/adr/0019-daily-crawl-runs-on-a-local-scheduler.md`。
這裡只寫**怎麼做**。

---

## 0. 一張圖看懂在跑什麼

```
Windows 工作排程器  ──每天 20:00──▶  scripts/crawl.py  ──▶  SNKRDUNK ＋ 臺銀
    （即使沒開瀏覽器也會跑）              │
                                        ├──▶  SQLite（成交紀錄 ＋ 爬取帳本）
                                        ├──▶  data/logs/crawl-YYYY-MM-DD.log
                                        └──▶  心跳 ping（healthchecks.io）
                                                    │
                                    該來的沒來 ──▶  手機收到通知
```

三個角色各自負責一種失敗：

| 角色 | 抓得到的失敗 | 你怎麼發現 |
|---|---|---|
| **爬取帳本**（crawl ledger，資料庫裡的 `crawl_run` 表） | 跑了但出錯 | 持有品頁的警示、`/api/market/runs` |
| **頁面過期警示** | 太久沒成功更新 | 打開持有品頁就看得到（被動） |
| **心跳／死人開關** | **根本沒跑**（電腦關機、排程被停用、腳本崩潰） | 手機主動收到通知 |

第三個是唯一抓得到「沉默」的機制——腳本沒跑起來時，它自己沒辦法通知你。

---

## 1. 先手動跑一次（不發任何請求）

註冊排程之前，先用 `--dry-run`（乾跑，只列出會做什麼、**一個對外請求都不發**）確認
路徑與環境是對的：

```powershell
uv run python scripts/crawl.py --dry-run
```

預期看到已確認的卡種清單、心跳是否已設定，以及 log 檔的位置。若這一步就錯，排程也
一定會錯。

> ⚠️ **接下來這個指令會真的對外發送網路請求，也會寫入資料庫。**
> 一輪約 105 秒（79 個請求，其中 75% 的時間是刻意的禮貌間隔）。確認上面的乾跑沒問題
> 再執行：
>
> ```powershell
> uv run python scripts/crawl.py
> ```

### 結束碼（exit code）

工作排程器的執行歷程只看得到這個數字，所以它們刻意分開：

| 碼 | 意思 | 要不要處理 |
|---|---|---|
| `0` | 跑完，沒有卡種失敗 | 不用 |
| `1` | **整輪失敗**（來源掛了、資料庫寫不進去……） | 要，看當天的 log |
| `2` | 跑完了，但有卡種失敗 | 看情況，失敗的卡種名與原因在 log 與持有品頁 |
| `3` | 已經有一輪在跑，這次什麼都沒做 | 不用，這是正常的互斥行為 |

---

## 2. 註冊每日排程

在 PowerShell 執行（會建立一個 Windows 排程工作，可隨時刪除）：

```powershell
$uv = (Get-Command uv).Source
$action = New-ScheduledTaskAction -Execute $uv `
    -Argument "run python scripts/crawl.py" `
    -WorkingDirectory "C:\Project\Card_Collection"
$trigger = New-ScheduledTaskTrigger -Daily -At 20:00
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
Register-ScheduledTask -TaskName "CardCollection-DailyCrawl" `
    -Action $action -Trigger $trigger -Settings $settings `
    -Description "每日爬取 SNKRDUNK 成交紀錄與臺銀匯率"
```

幾個參數不是可有可無的：

- **`-StartWhenAvailable`**：錯過的那一輪在電腦開機後**補跑**。它是**安全網，不是主要
  機制**——見下面「為什麼是晚上 8 點」。少了它，臨時關機那天就完全沒爬，而漏掉的成交
  補不回來（ADR-0019）。
- **`-RunOnlyIfNetworkAvailable`**：沒網路時不跑，免得在帳本上留下一筆假的失敗。
- **`-ExecutionTimeLimit 30 分鐘`**：與帳本的鎖自解門檻一致（`STALE_LOCK_MINUTES`）。
  一輪只要 1.7 分鐘，掛著 30 分鐘的不是慢，是死了。

### 為什麼是晚上 8 點

**唯一重要的條件是「那個時間你的電腦通常開著」。** 20:00 不是算出來的，是照這條規則挑的。

一個直覺的選擇是半夜跑（離峰、不跟自己搶網路），但那個直覺會**弄壞死人開關**：

```
昨天 09:10  開機後補跑成功，心跳送出          ✅
今天 03:00  排程時間到 —— 電腦是關的，什麼都沒發生
今天 05:10  healthchecks 等超過 24+2 小時 → 手機收到「掛了」通知   ❌
今天 09:15  你開機，補跑成功，心跳送出 → 恢復綠燈                  ✅
```

**系統其實好好的，但每天早上都會收到一次假警報。** 收個三天就不會再有人認真看那個
通知了——那比沒有通知更糟。

因此**排程時間與 §4 的 Grace Time 必須對齊**：把排程放在電腦一定開著的時段，
`-StartWhenAvailable` 就退回它該待的位置——只在臨時關機時救一次，而不是天天靠它。

放棄半夜的代價只有一項：台灣 03:00 剛好是日本 04:00，前一個「日本日」已完整結束，
而 20:00 是日本 21:00，當天還沒過完。**這個代價趨近於零**——兩次爬取之間仍然是 24
小時，每張卡「最新 20 筆」要涵蓋的時間長度完全沒變，只是窗口的起點不同。

至於「跑的時候人在用電腦」：一輪 105 秒，其中 75% 是刻意的禮貌間隔（在等，不是在算），
你多半不會察覺。

**驗證它註冊成功**（這只是讀取，不會執行）：

```powershell
Get-ScheduledTask -TaskName "CardCollection-DailyCrawl" | Get-ScheduledTaskInfo
```

**立刻手動觸發一次**（⚠️ 會真的爬）：

```powershell
Start-ScheduledTask -TaskName "CardCollection-DailyCrawl"
```

**移除排程**（⚠️ 刪掉之後就不會再自動爬，漏掉的日子補不回來）：

```powershell
Unregister-ScheduledTask -TaskName "CardCollection-DailyCrawl" -Confirm:$false
```

---

## 3. 常駐 web 服務

排程與服務是**互相獨立**的：服務沒開，排程照樣爬；服務只是拿來看結果的。

```powershell
uv run uvicorn card_collection.main:app --host 0.0.0.0 --port 8000
```

`--host 0.0.0.0` 是為了讓同一個私有網路內的手機連得到。**服務不對公網開放，也沒有
登入機制**——目前的前提是走 Tailscale 這類私有網路。若日後改成公開網址，登入是**必須
先做**的前置條件。

要讓它開機自動常駐，同樣用工作排程器，把觸發條件改成 `-AtStartup`：

```powershell
$uv = (Get-Command uv).Source
$action = New-ScheduledTaskAction -Execute $uv `
    -Argument "run uvicorn card_collection.main:app --host 0.0.0.0 --port 8000" `
    -WorkingDirectory "C:\Project\Card_Collection"
Register-ScheduledTask -TaskName "CardCollection-Web" `
    -Action $action -Trigger (New-ScheduledTaskTrigger -AtStartup) `
    -Settings (New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1))
```

> 兩個行程（常駐服務 ＋ 排程叫起來的 CLI）會同時寫同一個 SQLite 檔案。這是安全的：
> `connect()` 開了 **WAL**（Write-Ahead Logging，寫入不擋讀取）與 `busy_timeout`。
> 這不是最佳化，是這個部署形態的必要條件（ADR-0019）。

---

## 4. 死人開關（healthchecks.io）

### 為什麼需要它

電腦關機、排程被停用、腳本啟動時就崩潰——這幾種情況下，**系統不會留下任何紀錄**，
因為出事的行程沒辦法通知你它沒跑起來。死人開關判斷的是「**該來的心跳沒來**」，所以
它是唯一抓得到這種沉默的機制。

### 申請與設定

1. 到 <https://healthchecks.io> 註冊（**免費方案足夠**，一個 check 就夠了，不需要付費）。
2. 建立一個 check，設定：
   - **Period（週期）**：`1 day`——你每天爬一次。
   - **Grace Time（寬限）**：`2 hours`——爬取本身只要 2 分鐘，寬限是留給臨時晚開機的。
     **這個值與 §2 的排程時間綁在一起**：若之後把排程改到電腦不一定開著的時段，寬限
     必須跟著放寬（否則每天收假警報），或乾脆把排程搬回開著的時段。
   - **Notification（通知）**：加上手機能收到的管道（email／Telegram／推播）。
3. 複製它給的 **Ping URL**，長得像 `https://hc-ping.com/xxxxxxxx-xxxx-...`。

> 🔒 **這個 URL 等同密碼。** 知道它的人可以偽造心跳，讓你以為一切正常——那比沒有監控
> 更糟。**絕不 commit 進 repo**，只放環境變數。

4. 設成使用者層級的環境變數（排程工作以你的身分執行，因此讀得到）：

```powershell
setx CARD_COLLECTION_HEALTHCHECK_URL "https://hc-ping.com/貼上你的URL"
```

`setx` 寫進的是**未來**開啟的行程，目前這個視窗讀不到。**重新開一個 PowerShell 視窗**
再驗證：

```powershell
uv run python scripts/crawl.py --dry-run   # 應顯示「心跳：已設定」
```

**沒設定這個變數時心跳完全是 no-op**（什麼都不做）——本機開發與測試不受影響，也不會
誤送。

### 心跳送出什麼

一輪爬取送三次：開始（`/start`）、成功（無後綴）、失敗（`/fail`）。

內容**只有健康狀態**：幾個卡種、抓到幾筆、新增幾筆、待審幾筆、哪幾張卡失敗與原因。
**任何金額都不出門**——市值、成本、售出價、損益一律不送。訊息由具名欄位逐個組出來，
就是為了防止日後有人往那個字典加欄位時，安靜地把新欄位一起送出去。

心跳自己失敗時**爬取仍然算成功**：通知管道掛掉不該反過來弄壞資料。它會寫進 log，不會
無聲消失。

---

## 5. 出事時去哪裡查

依「離現場遠近」排序：

### a. 當天的 log 檔

```powershell
Get-Content data\logs\crawl-2026-08-26.log -Tail 30
```

每一輪的完整流水帳都在這裡，包含失敗的卡種名與原因。排程跑的時候沒有人在看畫面，
所以這是唯一留得下來的紀錄。

### b. 爬取帳本（API）

```powershell
# 最近幾輪的流水帳
curl http://localhost:8000/api/market/runs
# 上次成功是什麼時候、現在算不算過期
curl http://localhost:8000/api/market/runs/latest
```

帳本分得出這一輪是**手動按的**（`manual`）還是**排程跑的**（`scheduled`）——排程到底
有沒有在動，看這個欄位就知道。

### c. 持有品頁

打開 <http://localhost:8000/holdings>。壞消息**不摺疊**：上一輪的匯率錯誤、卡種失敗
直接顯示在頁面上方，不必展開。超過 24 小時沒有成功更新會出現明顯的過期警示。

### d. 工作排程器的執行歷程

```powershell
Get-ScheduledTaskInfo -TaskName "CardCollection-DailyCrawl"
```

`LastTaskResult` 就是上面那張表的結束碼。這一層看得到「腳本根本沒被叫起來」——那是
前三層都看不到的。

---

## 6. 常見情況

| 症狀 | 多半是什麼 | 怎麼辦 |
|---|---|---|
| 手動按「更新行情」回 **409** | 排程正在跑（同時只允許一輪） | 等它跑完再重新整理。這是正常的互斥行為，不是錯誤 |
| 結束碼 `3`，log 寫「跳過」 | 同上 | 同上 |
| 畫面顯示「上一輪的匯率沒抓到」 | 臺銀擋人或暫時不可用（ADR-0017） | **成交已用日圓原幣入庫，一筆都沒丟**。下一輪會自動重試補上換算（ADR-0016） |
| 手機收到死人開關通知 | 排程沒跑起來（關機／被停用／崩潰） | 先看 §5d 的執行歷程，再看 §5a 的 log |
| 上一輪卡在 `running` | 執行它的行程死了 | 不用處理。超過 30 分鐘後，下一輪會自動解鎖並把它標成 `failed`，原因寫明是判定行程已死 |
| 按更新行情時「連線中斷」 | 手機或網路斷了 | **爬取多半仍在伺服器端跑完**（同步端點跑在 threadpool，斷線不會中止它）。重新整理即可看到真實結果 |
