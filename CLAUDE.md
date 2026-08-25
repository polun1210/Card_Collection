## Agent skills

### Issue tracker

Issues tracked on GitHub via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context layout — `CONTEXT.md` + `docs/adr/` at repo root. See `docs/agents/domain.md`.

## 程式碼慣例

### 測試函式名使用中文

全域 `CLAUDE.md` 規定函式名維持英文。**本專案的測試函式名是例外**，一律使用中文，例如：

```python
def test_錯體版與正常版各自佔一列(client): ...
def test_原始欄位與來源CSV逐字相同(client, notion_csv): ...
```

理由：測試名是**行為描述**而非實作識別字，而本專案的領域詞彙（卡種、持有品、成交紀錄、待審、錯體版）在 `CONTEXT.md` 裡就是以中文定義的。翻成英文會與詞彙表對不起來，測試失敗時反而更難一眼看懂壞了什麼行為。

此例外**只適用於測試函式名**。產品程式碼的模組名、類別名、函式名、變數名一律維持英文 snake_case／PascalCase。
