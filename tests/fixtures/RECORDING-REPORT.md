# fixture 錄製結果（issue #8）

錄製時間：2026-08-25T12:54:14.177814+00:00

本檔由 `scripts/record_market_fixtures.py` 產生。
用來回答 issue #8 的待驗證問題，決定後請寫成 ADR。

> **結論已寫入 ADR-0014（匯率來源）與 ADR-0015（樣本揭露）。**
> 下方標為「200 但沒有資料」的四個回應，其檔案在結論落地後已刪除——
> 留著會讓 fixture 目錄看起來像有四個可用的匯率來源。本報告即是它們的紀錄。
> `tests/fixtures/fx/` 現存三個檔：定案採用的 `bot_jpy_l6m_csv_upper.txt.gz`，
> 以及兩個內容為真、但因無歷史或格式較難解析而未採用的備查回應。

## 匯率來源探測

**要回答的問題**：哪一個來源直接提供 JPY→TWD？若只提供美元，就得走交叉匯率——那是兩次換算的誤差疊加，且不會報錯。

### bot_jpy_l6m_html

- 說明：臺銀｜日圓近六個月牌告 HTML（**已實測可用**：124 個營業日、含現金與即期）
- 網址：`https://rate.bot.com.tw/xrt/quote/l6m/JPY`
- 回應：200｜text/html｜1,875 bytes
- 存檔：`bot_jpy_l6m_html.txt`
- **狀態 200 但沒有資料：被機器人驗證擋下** → 此來源不可用
- 前 200 字：'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no"><title>Challenge Validation</title><link rel="styleshee'

### bot_jpy_l6m_csv_upper

- 說明：臺銀｜日圓近六個月牌告 CSV，大寫路徑（小寫版回「找不到資料」）
- 網址：`https://rate.bot.com.tw/xrt/flcsv/0/L6M/JPY`
- 回應：200｜text/csv｜23,180 bytes
- 存檔：`bot_jpy_l6m_csv_upper.txt.gz`
- 提及日圓：是
- 提及美元：否
- 前 200 字：'\ufeff資料日期,幣別,匯率,現金,即期,遠期10天,遠期30天,遠期60天,遠期90天,遠期120天,遠期150天,遠期180天,匯率,現金,即期,遠期10天,遠期30天,遠期60天,遠期90天,遠期120天,遠期150天,遠期180天\r\n20260825,JPY,本行買入,0.19060,0.19790,0.19790,0.19780,0.19790,0.19800,0.19810,0.19810,'

### bot_today_all_csv

- 說明：臺銀｜今日全幣別牌告 CSV（實測回機器人驗證頁）
- 網址：`https://rate.bot.com.tw/xrt/flcsv/0/day`
- 回應：200｜text/csv｜3,715 bytes
- 存檔：`bot_today_all_csv.txt`
- 提及日圓：是
- 提及美元：是
- 前 200 字：'\ufeff幣別,匯率,現金,即期,遠期10天,遠期30天,遠期60天,遠期90天,遠期120天,遠期150天,遠期180天,匯率,現金,即期,遠期10天,遠期30天,遠期60天,遠期90天,遠期120天,遠期150天,遠期180天\r\nUSD,本行買入,31.47000,31.79500,31.80200,31.74600,31.68600,31.62000,31.55700,31.49500,31.432'

### cbc_exchange_rate_index

- 說明：央行｜匯率專區入口（實測回的是外匯存底頁）
- 網址：`https://www.cbc.gov.tw/tw/lp-644-1.html`
- 回應：200｜text/html; charset=utf-8｜44,401 bytes
- 存檔：`cbc_exchange_rate_index.txt.gz`
- **狀態 200 但沒有資料：回的是外匯存底頁，不是匯率頁** → 此來源不可用
- 前 200 字：'<!DOCTYPE html><html lang="zh-Hant" class="no-js">\r\n  <head>\r\n    <meta http-equiv="Content-Type" content="text/html; charset=utf-8">\r\n    <meta http-equiv="X-UA-Compatible" content="IE=edge" charset='

### cbc_usd_closing

- 說明：央行｜新臺幣對美元銀行間收盤匯率（實測回轉址 stub）
- 網址：`https://www.cbc.gov.tw/tw/np-1053-1.html`
- 回應：200｜text/html; charset=utf-8｜52 bytes
- 存檔：`cbc_usd_closing.txt`
- **狀態 200 但沒有資料：只是轉址 stub，沒有內容** → 此來源不可用
- 前 200 字："<script>location.href='/tw/lp-1053-1.html';</script>"


## SNKRDUNK 成交紀錄

測試需要兩種卡種各至少一個：**近 30 天有成交**（驗證市值計算）與**近 30 天無成交**（驗證沿用舊市值並標註過期天數）。請從下方的「距今幾天」挑選。

### trading_217570

- 說明：apparel 141410｜Pikachu [s8a 001/028](Expansion Pack "25th Anniversary Colle
- 網址：`https://snkrdunk.com/v3/products/217570/trading-history?condition_code=trading_card_single_psa10`
- 回應：200｜application/json; charset=utf-8｜19,753 bytes
- 存檔：`trading_217570.json`
- trades 20 筆
- 最舊 2026-08-25、最新 2026-08-25
- 距今 0 天 → 近 30 天有成交
- 枚数標籤 ['10枚', '1枚']
- 狀態標籤 ['PSA10']
- **有 4 組完全相同的成交**（最多 5 筆）→ 唯一鍵必須含同批次內的重複序號
- chart 398 點（僅供參考，ADR-0007 明令不得寫入資料庫）
- filters 枚数選項 ['1枚', '2枚', '3枚', '4枚', '5枚', '6枚', '7枚', '8枚', '9枚', '10枚']

### trading_217570_variant_2116195

- 說明：1 枚篩選｜Pikachu [s8a 001/028](Expansion Pack "25th Anniversary Colle
- 網址：`https://snkrdunk.com/v3/products/217570/trading-history?condition_code=trading_card_single_psa10&variant_id=2116195`
- 回應：200｜application/json; charset=utf-8｜19,564 bytes
- 存檔：`trading_217570_variant_2116195.json`
- trades 20 筆
- 最舊 2026-08-24、最新 2026-08-25
- 距今 0 天 → 近 30 天有成交
- 枚数標籤 ['1枚']
- 狀態標籤 ['PSA10']
- **有 4 組完全相同的成交**（最多 5 筆）→ 唯一鍵必須含同批次內的重複序號
- chart 395 點（僅供參考，ADR-0007 明令不得寫入資料庫）

### trading_217566

- 說明：apparel 141411｜Pikachu: Mirror [s8a 001/028](Expansion Pack "25th Anniversa
- 網址：`https://snkrdunk.com/v3/products/217566/trading-history?condition_code=trading_card_single_psa10`
- 回應：200｜application/json; charset=utf-8｜19,229 bytes
- 存檔：`trading_217566.json`
- trades 20 筆
- 最舊 2026-08-23、最新 2026-08-25
- 距今 0 天 → 近 30 天有成交
- 枚数標籤 ['1枚']
- 狀態標籤 ['PSA10']
- chart 382 點（僅供參考，ADR-0007 明令不得寫入資料庫）
- filters 枚数選項 ['1枚', '2枚', '3枚', '4枚', '5枚', '6枚', '7枚', '8枚', '9枚', '10枚']

### trading_217566_variant_2116235

- 說明：1 枚篩選｜Pikachu: Mirror [s8a 001/028](Expansion Pack "25th Anniversa
- 網址：`https://snkrdunk.com/v3/products/217566/trading-history?condition_code=trading_card_single_psa10&variant_id=2116235`
- 回應：200｜application/json; charset=utf-8｜18,932 bytes
- 存檔：`trading_217566_variant_2116235.json`
- trades 20 筆
- 最舊 2026-08-23、最新 2026-08-25
- 距今 0 天 → 近 30 天有成交
- 枚数標籤 ['1枚']
- 狀態標籤 ['PSA10']
- chart 375 點（僅供參考，ADR-0007 明令不得寫入資料庫）

### trading_834208

- 說明：apparel 722241｜MEGA Lucario ex MA [M2a 228/193](High Class Pack "MEGA Dream
- 網址：`https://snkrdunk.com/v3/products/834208/trading-history?condition_code=trading_card_single_psa10`
- 回應：200｜application/json; charset=utf-8｜10,229 bytes
- 存檔：`trading_834208.json`
- trades 20 筆
- 最舊 2026-08-24、最新 2026-08-25
- 距今 0 天 → 近 30 天有成交
- 枚数標籤 ['1枚', '2枚']
- 狀態標籤 ['PSA10']
- **有 1 組完全相同的成交**（最多 3 筆）→ 唯一鍵必須含同批次內的重複序號
- chart 168 點（僅供參考，ADR-0007 明令不得寫入資料庫）
- filters 枚数選項 ['1枚', '2枚', '3枚', '4枚', '5枚', '6枚', '7枚', '8枚', '9枚', '10枚']

### trading_834208_variant_9595830

- 說明：1 枚篩選｜MEGA Lucario ex MA [M2a 228/193](High Class Pack "MEGA Dream
- 網址：`https://snkrdunk.com/v3/products/834208/trading-history?condition_code=trading_card_single_psa10&variant_id=9595830`
- 回應：200｜application/json; charset=utf-8｜10,180 bytes
- 存檔：`trading_834208_variant_9595830.json`
- trades 20 筆
- 最舊 2026-08-24、最新 2026-08-25
- 距今 0 天 → 近 30 天有成交
- 枚数標籤 ['1枚']
- 狀態標籤 ['PSA10']
- **有 1 組完全相同的成交**（最多 3 筆）→ 唯一鍵必須含同批次內的重複序號
- chart 167 點（僅供參考，ADR-0007 明令不得寫入資料庫）

### trading_859607

- 說明：apparel 744296｜MEGA Lucario ex MA :Chinese Text Printing Error [M2a 228/193
- 網址：`https://snkrdunk.com/v3/products/859607/trading-history?condition_code=trading_card_single_psa10`
- 回應：200｜application/json; charset=utf-8｜5,946 bytes
- 存檔：`trading_859607.json`
- trades 20 筆
- 最舊 2026-06-17、最新 2026-08-25
- 距今 0 天 → 近 30 天有成交
- 枚数標籤 ['1枚']
- 狀態標籤 ['PSA10']
- chart 64 點（僅供參考，ADR-0007 明令不得寫入資料庫）
- filters 枚数選項 ['1枚', '2枚', '3枚', '4枚', '5枚', '6枚', '7枚', '8枚', '9枚', '10枚']

### trading_859607_variant_9772399

- 說明：1 枚篩選｜MEGA Lucario ex MA :Chinese Text Printing Error [M2a 228/193
- 網址：`https://snkrdunk.com/v3/products/859607/trading-history?condition_code=trading_card_single_psa10&variant_id=9772399`
- 回應：200｜application/json; charset=utf-8｜5,946 bytes
- 存檔：`trading_859607_variant_9772399.json`
- trades 20 筆
- 最舊 2026-06-17、最新 2026-08-25
- 距今 0 天 → 近 30 天有成交
- 枚数標籤 ['1枚']
- 狀態標籤 ['PSA10']
- chart 64 點（僅供參考，ADR-0007 明令不得寫入資料庫）

### trading_167274

- 說明：apparel 91103｜Charizard VMAX HR: PROMO[S-P 104](S-P Promotional cards)
- 網址：`https://snkrdunk.com/v3/products/167274/trading-history?condition_code=trading_card_single_psa10`
- 回應：200｜application/json; charset=utf-8｜6,179 bytes
- 存檔：`trading_167274.json`
- trades 20 筆
- 最舊 2026-03-09、最新 2026-08-06
- 距今 19 天 → 近 30 天有成交
- 枚数標籤 ['1枚']
- 狀態標籤 ['PSA10']
- chart 66 點（僅供參考，ADR-0007 明令不得寫入資料庫）
- filters 枚数選項 ['1枚', '2枚', '3枚', '4枚', '5枚', '6枚', '7枚', '8枚', '9枚', '10枚']

### trading_167274_variant_1871404

- 說明：1 枚篩選｜Charizard VMAX HR: PROMO[S-P 104](S-P Promotional cards)
- 網址：`https://snkrdunk.com/v3/products/167274/trading-history?condition_code=trading_card_single_psa10&variant_id=1871404`
- 回應：200｜application/json; charset=utf-8｜6,179 bytes
- 存檔：`trading_167274_variant_1871404.json`
- trades 20 筆
- 最舊 2026-03-09、最新 2026-08-06
- 距今 19 天 → 近 30 天有成交
- 枚数標籤 ['1枚']
- 狀態標籤 ['PSA10']
- chart 66 點（僅供參考，ADR-0007 明令不得寫入資料庫）

### trading_167326

- 說明：apparel 91155｜Pikachu V[S8a-G 001/015](25th Anniversary Golden Box)
- 網址：`https://snkrdunk.com/v3/products/167326/trading-history?condition_code=trading_card_single_psa10`
- 回應：200｜application/json; charset=utf-8｜41,825 bytes
- 存檔：`trading_167326.json.gz`
- trades 20 筆
- 最舊 2026-08-23、最新 2026-08-25
- 距今 0 天 → 近 30 天有成交
- 枚数標籤 ['1枚']
- 狀態標籤 ['PSA10']
- **有 3 組完全相同的成交**（最多 2 筆）→ 唯一鍵必須含同批次內的重複序號
- chart 908 點（僅供參考，ADR-0007 明令不得寫入資料庫）
- filters 枚数選項 ['1枚', '2枚', '3枚', '4枚', '5枚', '6枚', '7枚', '8枚', '9枚', '10枚']

### trading_167326_variant_1871931

- 說明：1 枚篩選｜Pikachu V[S8a-G 001/015](25th Anniversary Golden Box)
- 網址：`https://snkrdunk.com/v3/products/167326/trading-history?condition_code=trading_card_single_psa10&variant_id=1871931`
- 回應：200｜application/json; charset=utf-8｜41,695 bytes
- 存檔：`trading_167326_variant_1871931.json.gz`
- trades 20 筆
- 最舊 2026-08-23、最新 2026-08-25
- 距今 0 天 → 近 30 天有成交
- 枚数標籤 ['1枚']
- 狀態標籤 ['PSA10']
- **有 3 組完全相同的成交**（最多 2 筆）→ 唯一鍵必須含同批次內的重複序號
- chart 905 點（僅供參考，ADR-0007 明令不得寫入資料庫）

### trading_167327

- 說明：apparel 91156｜Charizard: PROMO[S8a-P 001/025](Promo Card Pack 25th Anniver
- 網址：`https://snkrdunk.com/v3/products/167327/trading-history?condition_code=trading_card_single_psa10`
- 回應：200｜application/json; charset=utf-8｜42,515 bytes
- 存檔：`trading_167327.json.gz`
- trades 20 筆
- 最舊 2026-08-21、最新 2026-08-25
- 距今 0 天 → 近 30 天有成交
- 枚数標籤 ['1枚']
- 狀態標籤 ['PSA10']
- **有 1 組完全相同的成交**（最多 2 筆）→ 唯一鍵必須含同批次內的重複序號
- chart 930 點（僅供參考，ADR-0007 明令不得寫入資料庫）
- filters 枚数選項 ['1枚', '2枚', '3枚', '4枚', '5枚', '6枚', '7枚', '8枚', '9枚', '10枚']

### trading_167327_variant_1871951

- 說明：1 枚篩選｜Charizard: PROMO[S8a-P 001/025](Promo Card Pack 25th Anniver
- 網址：`https://snkrdunk.com/v3/products/167327/trading-history?condition_code=trading_card_single_psa10&variant_id=1871951`
- 回應：200｜application/json; charset=utf-8｜42,468 bytes
- 存檔：`trading_167327_variant_1871951.json.gz`
- trades 20 筆
- 最舊 2026-08-21、最新 2026-08-25
- 距今 0 天 → 近 30 天有成交
- 枚数標籤 ['1枚']
- 狀態標籤 ['PSA10']
- **有 1 組完全相同的成交**（最多 2 筆）→ 唯一鍵必須含同批次內的重複序號
- chart 929 點（僅供參考，ADR-0007 明令不得寫入資料庫）

### trading_171973

- 說明：apparel 95803｜Pikachu V In A Sleeve[S8a-G 001/015](25th Anniversary Golden
- 網址：`https://snkrdunk.com/v3/products/171973/trading-history?condition_code=trading_card_single_psa10`
- 回應：200｜application/json; charset=utf-8｜2,490 bytes
- 存檔：`trading_171973.json`
- trades 7 筆
- 最舊 2023-07-10、最新 2025-09-12
- 距今 347 天 → **近 30 天無成交**
- 枚数標籤 ['1枚']
- 狀態標籤 ['PSA10']
- chart 6 點（僅供參考，ADR-0007 明令不得寫入資料庫）
- filters 枚数選項 ['1枚', '2枚', '3枚', '4枚', '5枚', '6枚', '7枚', '8枚', '9枚', '10枚']

### trading_171973_variant_1901702

- 說明：1 枚篩選｜Pikachu V In A Sleeve[S8a-G 001/015](25th Anniversary Golden
- 網址：`https://snkrdunk.com/v3/products/171973/trading-history?condition_code=trading_card_single_psa10&variant_id=1901702`
- 回應：200｜application/json; charset=utf-8｜2,490 bytes
- 存檔：`trading_171973_variant_1901702.json`
- trades 7 筆
- 最舊 2023-07-10、最新 2025-09-12
- 距今 347 天 → **近 30 天無成交**
- 枚数標籤 ['1枚']
- 狀態標籤 ['PSA10']
- chart 6 點（僅供參考，ADR-0007 明令不得寫入資料庫）

