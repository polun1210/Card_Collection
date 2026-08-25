# 候選卡種取自 `/search?keywords=`（複數），非 API

比對候選來自 SNKRDUNK 的**搜尋頁**，而非任何 JSON API：

```
GET https://snkrdunk.com/search?keywords=<系列代碼> <卡號補零三位>
```

此頁為伺服器端渲染，`https://snkrdunk.com/apparels/{id}` 連結直接寫在 HTML 裡，免登入、不需瀏覽器自動化。取得 apparel id 後再逐一打 `GET /v1/apparels/{id}` 取英文卡名、日文卡名、官方去背卡圖與 `productCatalogId`。

## Considered Options

**`/v3/search`（真正的 API）確實存在**——由前端 JS bundle 的產生式 hook `useGetV3Search` 解出——但參數名試了 11 種（`keyword`／`q`／`query`／`word`／`text`／`searchWord`／`freeWord`／加分頁／加分類⋯⋯）一律回 400 `bad_request`，缺的必填參數未解。相對地搜尋頁已足夠且更穩定：SSR 的 HTML 結構比未公開 API 的參數契約更不容易一夜改變。

`GET /v1/apparels?keyword=` 看似可用，實際上**永遠回 `{"apparels": []}`**——200 而空，是會安靜說謊的那種回應，與 ADR-0007 記載的同一類陷阱。

sitemap（`sitemap-index-jp-apparels.xml`、`sitemap-index-en-product-trading-card-single.xml`）能取得全部約 27 萬個トレカ單張的 apparel id，但**只有 id、沒有卡名**，無法用於比對。

## Consequences

- **參數名是 `keywords`（複數）。** 單數的 `keyword` 不會報錯，而是回傳一份與關鍵字完全無關的推薦清單——實測 `S-P 104`、`Pikachu`、`zzzzznonsense` 三個關鍵字回傳一模一樣的 33 筆。這是本專案第三次遇到「200 但內容是假的」，白名單策略（ADR-0004）的價值再次得到印證。
- **卡號必須先補零至三位**：實測 `S8a 1` 回 0 筆、`S8a 001` 回 5 筆。ADR 記載的正規化規則不是可有可無的清理，是搜尋能否運作的前提。
- 每個候選要多打一次 `/v1/apparels/{id}`，因此候選數上限設為 8，且所有請求序列化並保持固定間隔。實測 70 個卡種中，單一查詢最多回 5 筆。
- 搜尋會混入其他系列與英文版卡（例如查 `M1L 078` 會一併回 `MEG EN 160/132`）。**這正是人工確認存在的理由**，不視為缺陷。
- **`M2a 228` 的錯體版確認為獨立上架**（`744296` `MEGA Lucario ex MA :Chinese Text Printing Error`，與正常版 `722241` 並存），ADR-0008 的待驗證前提成立。
- 測試 fixture 為錄下的真實回應（4 份搜尋 HTML、8 份卡種 JSON），存於 `tests/fixtures/snkrdunk/`。SNKRDUNK 改格式時測試會紅。
