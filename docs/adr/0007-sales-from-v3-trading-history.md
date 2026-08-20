# 成交紀錄取自 `/v3/products/{productCatalogId}/trading-history`

先前記錄的 `/v1/apparels/{id}/used/listings` 並不存在——它是猜出來的路徑，SNKRDUNK 對任何無法辨識的 `/v1/apparels/{id}/*` 一律回 400 `bad_input`，而不是 404，所以「400 不是 404」曾被誤讀為「端點存在、參數待解」。真正的端點由前端 JS bundle 中的產生式 hook `useGetV3ProductsIdTradingHistory` 找出，未經瀏覽器自動化、未帶任何登入憑證即可取得。

```
GET https://snkrdunk.com/v3/products/{productCatalogId}/trading-history
      ?range=all|oneWeek|oneMonth|threeMonths      # 省略時等同 all
      &condition_code=trading_card_single_psa10    # 省略＝全部狀態
      &variant_id={枚数選項 id}                     # 省略＝全部枚数
```

**路徑上的 id 是 `productCatalogId`，不是 apparel id。** 兩者不同號（apparel 91103 → productCatalogId 167274），必須先 `GET /v1/apparels/{id}` 取得。用 apparel id 去打會回 200 與一份空資料，不會報錯——這是會安靜說謊的那種錯，卡種主檔必須把 `productCatalogId` 一併存下來。

回應含三段：`filters`（可用的狀態與枚数選項）、`trades`（實際成交明細，`price` / `soldAt` / `title`（狀態）/ `label`（枚数））、`chart`（每日聚合的價格線）。

## Consequences

- **`condition_code` 與 `variant_id` 在來源端就解決了「多張一組」**。ADR-0004 列的三類髒資料中，`variant_id=1枚` 直接排除多張一組；`trades` 是已完成的成交（有 `soldAt`），不含下架未成交。**只剩離群值需要自行處理**，白名單策略本身維持不變。
- **`trades` 固定最多 20 筆，且無分頁**：`page` / `limit` / `offset` / `size` 皆被忽略，`range` 也不影響它——永遠是該篩選條件下最新的 20 筆。實測兩張卡的 PSA 10 成交密度約每月 2–4 筆，20 筆可覆蓋 5 個月以上，**近 30 天中位數（ADR-0002）不受影響**。但「近 3 個月成交筆數」在熱門卡上會被截頂於 20。**熱門度的定義不改**，改為每日爬取並累積寫入本地成交紀錄表——單日新增遠低於 20 筆，累積後筆數即完整。只有開始爬取之前的那 3 個月受上限影響，此後自動痊癒。這與「每天全量跑一遍 68 個卡種」的既有決定零衝突。
- **`chart` 可回填至數年前**（實測 PSA 10 線最早 2023-06-28），但它是**每日聚合**且價格不等於任何一筆實際成交（同日三筆 200/199/188 萬回傳 193 萬）。因此 chart 只能作為早期走勢的參考線，**不得當成交紀錄寫入資料庫**——寫進去就違反了原始值優先。
- `timestamp` 為毫秒，且對齊 JST 當日零時；`soldAt` 為 UTC。同一筆成交在兩處會差一天，日期一律以 JST 為準。
