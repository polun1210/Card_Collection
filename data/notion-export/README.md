# Notion 匯出原始資料

從 Notion 匯出的原始 CSV 放這裡，**原樣保存、永不改寫**（原始值優先，見 `CONTEXT.md`）。

程式讀取後所有正規化的結果都另存為衍生欄位，不回頭改這裡的檔案。

## 目前的檔案

| 檔名 | 內容 | 用途 |
|---|---|---|
| `pokemon_project.csv` | 100 列持有品，涵蓋 68 個相異卡種 | 卡種對應（#1）與持有品匯入（#7）的共同輸入 |

一列是一筆**持有品**，不是一個卡種。同一個卡種可以佔多列，欄位完全相同的兩列是兩張實體卡。

欄位：`card name`, `card num`, `cost`, `grading score`, `purchase date`, `set name`, `sold date`, `sold price`。

未售出的列，`sold date` 與 `sold price` 一律留白，**不以 0 表示**（ADR-0009）。金額為新台幣。
