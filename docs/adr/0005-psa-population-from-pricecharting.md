# PSA 10 張數改由 PriceCharting 取得

PSA 官方 API 只提供 cert number 查詢，不含族群報告；官網的 population report 雖然免費且不需 cert number（按系列與卡號瀏覽即可），但受 Cloudflare 保護，需要真實瀏覽器才能取得。PriceCharting 提供同樣的資料，純伺服器端渲染、無 Cloudflare，且 **PSA 與 CGC 是分開的欄位**而非合併總數。因此改用 PriceCharting，每月爬取一次。

## Consequences

不需要記錄任何持有品的 cert number。爬取頻率為每月一次，因為族群數量變動極慢。
