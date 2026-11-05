# 卡片明細抽屜的傾斜與反光自己寫，不引入套件

Status: Accepted  
Date: 2026-11-05

## Decision

卡片明細抽屜（`_portfolio_wall.html` 的 `<dialog id="card-drawer">`）裡的大卡圖，
滑鼠移上去（手機用手指拖）會 3D 傾斜並出現反光。

- **範圍只限抽屜。** 卡圖牆 62 格不上（理由見 `docs/interface.md` §7.5：牆的任務是
  掃視找卡，特效會干擾；且 62 格同時掛載有手機效能風險）。
- **手寫，約 25 行 vanilla JS ＋ 一段 CSS**，沒有新增任何檔案依賴：JS 放進
  `_portfolio_wall.html` 既有的 `<script>`，CSS 放進 `portfolio.css`。
- 結構：`.tilt`（perspective）> `.tilt__card`（rotateX／rotateY／scale，由 CSS 變數驅動）>
  `img.drawer__art` ＋ `.tilt__glare`（radial-gradient ＋ `mix-blend-mode: overlay`）。
- 手感數值：最大傾斜 14 度、放大 1.04 倍、反光中等強度。這組數值來自使用者已看過並認可的樣品。
- `prefers-reduced-motion: reduce` 時不傾斜、不顯示反光。
- 沒有 JS 時，抽屜卡圖照常顯示，只是不會動。

## Context

`docs/interface.md` §7.5 盤點過這個特效，起點是 pokemon-cards-css，作者另提供輕量版
hover-tilt（Web Component）。原計畫是把 hover-tilt 的 dist 檔 vendor 進
`static/vendor/`。動工前查證發現不能照原計畫走。

## Considered Options

### vendor hover-tilt

否決理由：

1. **授權說法不一致。** npm 上的 `hover-tilt@1.0.0` 標示 MPL-2.0，GitHub 倉庫的
   LICENSE 檔卻是 MIT。在作者釐清之前，本 repo 無法確定該寫哪一份授權聲明。
2. **會讓「沒有前端框架」（§1）打折。** bundle 約 180 KB，內含一份 Svelte runtime。
   原始碼看不到框架，但它確實存在。
3. 使用者已看過手寫樣品的手感並認可，不需要為更順的彈簧物理付這個代價。

### 使用 pokemon-cards-css

否決理由：

1. 授權是 GPL-3.0；本 repo 是公開的且尚未掛授權，引入會有 copyleft 疑慮。
2. 彩虹 shine 層需要稀有度資料，而 `CONTEXT.md` 刻意把稀有度列在 `_Avoid_`，
   不為了視覺效果把它請回系統。
3. 要 Vite 建置步驟與約 4.4 MB 材質圖。

### 手寫（採用）

## Consequences

- §1 的「零外部資源」與「沒有前端框架」**原樣保留**，不需要例外條款。
- 代價：沒有彈簧物理。放開滑鼠時是 CSS transition 回正，不是彈簧回彈。以後要調手感，
  直接改 `portfolio.css` 的 transition 與 `_portfolio_wall.html` 的 `MAX_DEG`。
- 抽屜內容是開啟時才 clone 進 DOM，所以事件綁在 `#card-drawer-body` 上用事件委派
  （event delegation），不需要每次開抽屜重新綁。
- 抽屜裡的卡圖改為 `object-fit: cover` 並套卡片圓角，讓傾斜與反光貼著卡的形狀。
  卡圖牆 `.wall .art` 的 `object-fit: contain`（§7.1）**不動**。
