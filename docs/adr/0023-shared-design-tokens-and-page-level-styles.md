# 共用 Design Token，頁面 Layout 樣式分離

Status: Accepted  
Date: 2026-09-05

## Decision

UI/UX 重做後，三個頁面不再各自維護一套完整的視覺樣式。改採：

```text
static/
├── design.css
├── portfolio.css
├── holdings.css
└── queue.css
```

`design.css` 負責全站共用的 Design Language：

- 深色 color tokens
- typography
- spacing
- radius
- border / elevation 基礎
- button
- input
- tabs
- status states
- global header
- shared dialog / drawer foundation

三個頁面各自的 CSS 只負責：

- page layout
- page-specific component arrangement
- page-specific responsive behavior

也就是：

> **Design language 共用，page layout 分離。**

介面固定採單一深色系；`color-scheme` 使用 `dark`。不導入 Web Font，不新增前端框架，不把三頁合併成 SPA。

## Context

`docs/interface.md` 原本記錄的分工是「共用 markup / 行為，但外觀不共用」：`portfolio.html` 與 `holdings.html` 雖然都有 `.totals`、`.freshness`、`.toolbar`、`button` 等近似區塊，CSS 仍各自維護一份。

當時的理由是 UI/UX 版面尚未定案，共用樣式會讓頁面在重做之前互相綁住。該文件也明確把「UIUX 階段是否建立共用設計 token 或樣式表」留作後續決策。

ADR-0022 又進一步決定：

- 介面固定深色
- 不做 Light Mode
- `color-scheme` 改為 `dark`
- 舊的淺色視覺語彙表必須全面重校

完成 UI/UX 設計後，三頁已經共享同一套視覺語言：Premium Dark Gallery、相同的背景層級、文字層級、accent、semantic color、button、input、tabs、status 與 spacing system。

若繼續讓三頁各自維護一份完整視覺樣式，會產生下列問題：

1. 同一個 Accent、Warning、Button、Input 需要修改三次。
2. 同一語意可能在三頁慢慢漂移成不同顏色與尺寸。
3. Dark-only 的 token 調整必須同步維護多份值。
4. UIUX Spec 無法對應到單一可查找的 design foundation。
5. 之後新增共用 component 時，會被迫再複製視覺規則。

但反過來把所有 CSS 都塞進一個單檔也不可取：三頁的工作模型不同，首頁是 Gallery / Portfolio、持有品是 Ledger、Queue 是 reconciliation workflow；如果連 layout 都強制共用，會重現 UIUX 前刻意避免的耦合問題。

因此採中間方案：**只共用視覺系統，不共用頁面 layout。**

## Considered Options

### 三頁繼續完全各自維護 CSS

優點是頁面互不影響。

否決理由是 UIUX 已經定案，不再需要用「完全不共用」保護尚未確定的版面。這個模式會讓已經明確共用的視覺語言重複三份，之後每次調整都增加漂移風險。

### 全站只留一個 CSS 檔

優點是所有規則集中。

否決理由是首頁、持有品與 Queue 的版面職責不同。一個巨型 stylesheet 會把 Global Design Token、Gallery、Ledger、Queue workflow 全混在同一個命名與 cascade 範圍，維護上反而更難判斷哪些規則可以共用、哪些只能改單頁。

### 共用 Design Foundation + Page Styles（採用）

把全站有共同語意的視覺規則集中到 `design.css`，每頁保留自己的 layout stylesheet。

這保留了兩個優點：

- 全站視覺一致、Design Token 只維護一份
- 頁面仍可獨立重排，不因一個 layout 修改連動其他頁

## Consequences

- `docs/uiux-spec.md` 成為 UI/UX 施工規格；`design.css` 是其中 Design System 在程式碼裡的主要落點。
- 原本三頁重複的色彩、button、input、tabs、status、global header 等規則應移入 `design.css`。
- `portfolio.css`、`holdings.css`、`queue.css` 只保留各頁布局與特殊 component 規則。
- `color-scheme: dark` 應由共用 foundation 定義，而不是三頁各寫一次。
- 不導入 Web Font。Typography 使用 system font stack，保留 `font-variant-numeric: tabular-nums`。
- 不導入 React / Vue 或其他前端框架。這份 ADR 只改 CSS architecture，不改 Jinja2 + Vanilla JS 的技術方向。
- UIUX 重做期間，現有 HTML 字串測試若只鎖住 class name、函式名或特定 CSS 實作，應依 `docs/interface.md` 的測試分層原則判斷是否更新；資料誠實性相關的第一層約束不得因重構而放寬。
- UIUX 真正實作完成後，再更新 `docs/interface.md` 成新的介面現況。此 ADR 不要求在設計施工開始前先把現況文件寫成未來狀態。
- 如果未來新增第四個頁面，只要它使用相同設計語言，即應優先沿用 `design.css` 的 token 與基礎 component，而不是複製一份新的全套視覺樣式。
