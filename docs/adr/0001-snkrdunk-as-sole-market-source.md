# SNKRDUNK 為唯一市場資料源

收藏 100% 為日版卡，日本才是主場市場。查證後發現 eBay 官方無法取得成交價（Finding/Shopping API 已於 2025-02-05 停用，Browse API 只有在售商品，唯一有成交資料的 Marketplace Insights API 是 Limited Release 且不開放新申請），而第三方聚合 API 以美國市場為主、日版覆蓋差且無 SNKRDUNK 資料。因此刪除 eBay 與所有第三方付費 API，只用 SNKRDUNK。

## Consequences

- 所有市值只反映日本市場。**刻意不在 UI 上標註**——這是單人使用的工具，使用者自己清楚資料來源。若日後有第二個使用者，這個決定必須重新檢視。
- 幣別鏈簡化為單一路徑 JPY → TWD。
- PSA 10 張數在 SNKRDUNK 沒有來源，改由 PriceCharting 取得（見 ADR-0005）。
- SNKRDUNK 有可用的 JSON API（`GET /v1/apparels/{id}`，已驗證），提供英文卡名、日文卡名、官方去背卡圖與結構化卡種代碼，因此卡種主檔也以 SNKRDUNK 為權威——主檔與價格同源，不會出現「主檔有這張卡但抓不到價格」的鬼卡。
