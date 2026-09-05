# Card Collection UI/UX Specification

> Status: Approved for implementation  
> Date: 2026-09-05  
> Scope: UI/UX redesign of the existing personal Pokémon PSA 10 collection tracking dashboard

This document is the implementation specification for the UI/UX redesign. Domain terminology follows `CONTEXT.md`; domain and technical decisions follow `docs/adr/`; current implementation constraints follow `docs/interface.md`.

If this document conflicts with `CONTEXT.md` or an accepted ADR, this document is wrong.

---

## 1. Product UX Principles

### 1.1 Product positioning

The product is a **personal collection dashboard with portfolio analytics**, not a generic admin panel and not a trading terminal.

Visual weighting:

- **60% Collection**
- **40% Portfolio**

The UI should feel like a **Premium Dark Gallery**: the interface recedes, Pokémon card art becomes the primary visual color source, and financial information is precise but visually restrained.

### 1.2 Primary user tasks

The homepage is optimized for this priority order:

1. **What is my current held collection worth?**
2. **What cards do I own / have owned?**
3. **How has the collection value moved recently?**

Desktop is the primary operating environment. Mobile is primarily a read-only viewing environment.

### 1.3 Core interaction model

- **收藏總覽 `/`**: Browse → Inspect
- **持有品 `/holdings`**: Find → Manage
- **卡種對應 `/queue`**: Find Exception → Resolve

The homepage is read-only for holding management. Create / edit / sell / unsell / delete operations belong to `/holdings`.

### 1.4 Truthfulness over convenience

The interface must not make incomplete or unavailable data appear complete.

The redesign must preserve these rules:

- Missing numeric values are never replaced with fake zeroes.
- Unrealized P&L and realized P&L are never combined.
- Return rate remains `(result − cost) ÷ cost`.
- Market Value always stays tied to its sample metadata.
- Trend coverage remains visible and visually distinguishable when incomplete.
- A card kind without market value remains visible in the collection.
- System-level stale market data and card-level stale market value remain distinct states.
- Liquidity remains a paired concept: PSA 10 population + 3-month sales count.
- Destructive holding deletion must identify the exact holding and its effect.

---

## 2. Information Architecture

### 2.1 Global navigation

All three pages share one global header.

Primary navigation:

- 收藏總覽
- 持有品
- 卡種對應

Primary global action:

- `＋ 新增持有品`

`更新行情` is not a permanent primary action. Market crawling is scheduled. Manual update is surfaced when needed, especially when market data is stale or failed.

### 2.2 Page responsibilities

| Route | Role | Primary question |
|---|---|---|
| `/` | Collection dashboard | What is my held collection worth, what do I own, and how is it moving? |
| `/holdings` | Holding ledger / workbench | Which physical holding do I need to inspect or modify? |
| `/queue` | Mapping reconciliation workspace | Which card kind requires manual SNKRDUNK mapping? |

---

## 3. Global Layout System

### 3.1 Main container

Desktop design target:

- Maximum content width: approximately **1440px**
- Horizontal safety margin: approximately **24–32px**
- Do not make the dashboard fully fluid edge-to-edge on large screens.

### 3.2 Breakpoint strategy

Use three main layout bands rather than many micro-breakpoints.

#### Large desktop — `>= 1280px`

- Homepage Hero uses approximately 7:3 chart-to-summary proportion.
- Collection gallery targets approximately 6 columns.
- Desktop detail drawer is approximately 460px wide.

#### Tablet / small desktop — approximately `768–1279px`

- Hero stacks vertically.
- Gallery drops to approximately 3–4 columns.
- Drawer may use a larger viewport proportion.

#### Mobile — `< 768px`

- Summary appears before chart.
- Collection gallery targets 2 columns.
- Card details open as a full-screen sheet.
- Mobile homepage must not horizontally scroll.

---

## 4. Visual Direction

### 4.1 Style

Adopt **Premium Dark Gallery**.

Do:

- graphite / charcoal surfaces
- restrained blue accent
- subdued borders
- bright card art as the main color source
- limited semantic green/red/amber usage

Do not:

- use gaming neon
- theme the interface around Pokémon yellow/red
- add glassmorphism or heavy blur
- add decorative gradients to major surfaces
- use large glowing shadows
- make the UI chrome visually louder than the collection itself

### 4.2 Color scheme

The interface is permanently dark-only. It does not follow OS theme and does not expose a theme toggle.

Set:

```css
color-scheme: dark;
```

Provisional design tokens:

```css
:root {
  --bg-app: #0B0F14;
  --bg-surface: #111821;
  --bg-elevated: #18212B;

  --border-default: #26313D;
  --border-strong: #364453;

  --text-primary: #E6EDF3;
  --text-secondary: #A0AEC0;
  --text-muted: #718096;

  --accent: #6EA8FE;
  --positive: #59C98C;
  --negative: #F07178;
  --warning: #D9A441;
  --danger: #F07178;
}
```

Final implementation values may be adjusted after contrast validation, but the semantic structure and visual direction should remain unchanged.

### 4.3 Semantic color rules

**Accent blue** is used for:

- active navigation
- primary CTA
- selected candidate
- focus state
- links
- active tabs / controls

**Positive / Negative** are used only for directional numeric meaning, such as return rate and P&L.

Do not color neutral numbers such as:

- market value
- cost
- holding count
- PSA 10 population
- sales count

**Warning amber** is for attention states such as:

- system market data stale
- card-level market value stale

Missing / pending data is neutral, not warning-colored.

### 4.4 Typography

Do not add a web-font dependency.

Use a system font stack:

```css
font-family:
  system-ui,
  -apple-system,
  BlinkMacSystemFont,
  "Segoe UI",
  "Microsoft JhengHei",
  sans-serif;
```

All numeric content keeps:

```css
font-variant-numeric: tabular-nums;
```

Suggested type scale:

| Role | Size | Weight |
|---|---:|---:|
| Hero Value | 34px | 700 |
| Page Title | 26px | 700 |
| Section Heading | 20px | 650 |
| Component Title | 16px | 600 |
| Body | 15px | 400 |
| Metadata | 13px | 400 |
| Micro metadata | 12px | 400 |

Avoid overusing bold weight. Prefer hierarchy through size, spacing and contrast.

### 4.5 Spacing

Use a 4px base grid.

```css
--space-1: 4px;
--space-2: 8px;
--space-3: 12px;
--space-4: 16px;
--space-6: 24px;
--space-8: 32px;
--space-12: 48px;
--space-16: 64px;
```

### 4.6 Radius

Suggested radii:

- Small tag: 6px
- Button / Input: 8px
- Gallery tile: 10px
- Large surface / Drawer / Dialog: 12px

Avoid pill shapes as the default language.

### 4.7 Borders and shadows

Structure is created primarily through surface tone and subtle borders.

- Default border: `1px var(--border-default)`
- Hover / stronger boundary: `var(--border-strong)`
- Selected: accent border / focus treatment

Shadows are limited to true floating layers:

- Drawer
- Dialog
- Gallery tile hover

Do not use heavy shadows on Hero, ordinary sections or workbench rows.

---

## 5. Shared CSS Architecture

A shared design foundation is introduced.

Recommended structure:

```text
static/
├── design.css
├── portfolio.css
├── holdings.css
└── queue.css
```

### `design.css`

Contains shared design language:

- color tokens
- typography
- spacing
- radii
- buttons
- inputs
- tabs
- status states
- global header
- shared dialog / drawer foundation

### Page-specific stylesheets

Contain page layout and page-specific components only.

Do not reintroduce three independently maintained copies of the same color, button, input or status styling.

---

## 6. Global Header

Desktop header contains:

- product title: `Pokémon Collection`
- 收藏總覽
- 持有品
- 卡種對應
- `＋ 新增持有品`

Active navigation should use text contrast plus a restrained accent indicator / underline, not a large filled button.

`＋ 新增持有品` is the single persistent primary CTA.

Do not add unnecessary SaaS chrome such as profile avatars, notification bells or settings icons unless a later requirement introduces them.

---

## 7. 收藏總覽 `/`

### 7.1 Page-level structure

Do not repeat a large `收藏總覽` content heading below the global header.

Normal page order:

1. Global header
2. Global market warning only when abnormal
3. Portfolio Hero
4. 我的收藏

### 7.2 Global market warning

Healthy market freshness is not displayed as a permanent banner.

Only stale / failed system market state shows a warning between header and Hero.

Example:

```text
⚠ 行情超過 24 小時未成功更新                    立即更新行情
```

This warning is system-level and must not be confused with a card whose market value is stale because the card itself has not traded recently.

### 7.3 Portfolio Hero

Desktop Hero is one continuous surface using approximately **70% trend / 30% summary**.

Do not render the chart and summary as separate card widgets.

#### Left — Trend

Contains:

- `資產走勢`
- range control: `7D / 1M / 3M / YTD / ALL`
- Market Value line
- Cost line
- Coverage visualization
- hover / pointer tooltip

`YTD` is hidden when the underlying data is insufficient according to existing domain behavior.

Remove instructional paragraphs below the chart.

Chart values should identify themselves through compact labels / legend / direct annotation.

Trend lines and coverage remain neutral in color. Do not use green/red chart lines as P&L semantics.

Tooltip example:

```text
2026/09/03
總市值   NT$ 1,036,566
總成本   NT$ 1,016,730
涵蓋     62 / 62
```

Low-coverage portions must remain visually distinguishable, not only discoverable through tooltip text.

#### Right — Held Portfolio Summary

Only held-portfolio information appears here.

Hierarchy:

1. **持有中總市值** — largest financial number
2. 未實現損益 + 報酬率
3. 持有中總成本
4. 持有中張數 + 卡種數

Example:

```text
持有中總市值
NT$ 1,036,566

+19,836          +2.0%
未實現損益        報酬率

持有中總成本
NT$ 1,016,730

89 張 · 62 卡種
```

Do not display realized P&L or sold counts in the Hero.

Primary displayed monetary values use `NT$` because the explanatory currency paragraph is removed.

### 7.4 我的收藏

This is the primary collection area, not a technical `card wall` concept in user-facing language.

Tabs:

- `持有中 N`
- `已售出 N`

Use text tabs with an active accent indicator. Do not use large boxed tab buttons.

### 7.5 Gallery layout

Desktop target: approximately **6 columns** at a ~1440px content width.

Use responsive auto-fill / minmax behavior rather than hard-coding six columns.

Mobile target: **2 columns**.

### 7.6 Card artwork

Use:

```css
aspect-ratio: 63 / 88;
object-fit: contain;
```

Do not use the obsolete `10 / 7` image area.

Do not use `object-fit: cover` because card edges and visual identity must remain intact.

Gallery tiles are **art-first**, not container-first.

The normal tile should have little or no visible box framing. Hover / focus may introduce a restrained surface and border.

Do not grayscale sold artwork.

### 7.7 Held Gallery tile

Collapsed tile contains only:

- card artwork
- card name
- series + card number + holding count where applicable
- return rate

Example:

```text
Pikachu
XY-P #203 · 2 張
+95.9%
```

Do not show:

- Market Value
- Momentum
- Liquidity
- CRUD buttons

No market value / no calculable return:

```text
—
```

Do not replace missing return with `0.0%`.

### 7.8 Sold Gallery tile

Uses the same visual system as Held.

Collapsed state contains:

- card artwork
- identity
- sold count in metadata
- realized return rate

Example:

```text
Mew
S12a #183 · 已售出 2 張
+64.3%
```

Do not show purchase cost, sale date or realized P&L directly on the collapsed Gallery tile.

---

## 8. Card Detail Drawer / Mobile Sheet

### 8.1 Interaction

Clicking a Gallery tile does **not** expand the grid in place.

Desktop:

- Open an overlay right-side Drawer.
- The Gallery does not reflow.
- Target width: approximately 460px.

Mobile:

- Open a full-screen detail sheet.
- Use a back-style affordance rather than treating it as a small modal.

The existing lazy data strategy remains: detailed card data is fetched only when the card is opened.

### 8.2 Drawer visual structure

- Sticky identity header: card name + series / number + close control
- Medium card artwork, approximately 40–45% of content width
- Card artwork sits directly on the Drawer surface; no separate image well
- Large sections separated mainly by spacing, with a subtle divider between major sections
- No nested dashboard-card grid
- No sticky footer CTA

### 8.3 Held Drawer

Order:

1. Identity / artwork
2. 我的持有
3. 市場
4. 我的持有明細
5. `查看持有品明細 →`

#### 我的持有

Contains:

- held aggregate current value
- total cost
- unrealized P&L
- return rate

#### 市場

Contains:

- single-card Market Value
- Market Value sample count + sample period, or stale age
- Momentum
- Liquidity pair

Market Value and its sample metadata remain adjacent.

Examples:

```text
單張市值
NT$ 12,480
18 筆 · 08/06～09/03
```

or

```text
單張市值
NT$ 8,900
已過期 41 天
```

Liquidity must show both components together:

```text
PSA 10 張數       近 3 月成交
1,234             46
```

If Momentum / Liquidity are not ready, use a neutral state such as:

```text
資料累積中
```

Do not add explanatory onboarding copy.

#### 我的持有明細

Show read-only per-holding purchase date and purchase cost.

No edit / sell / delete controls appear in the Drawer.

### 8.4 Sold Drawer

Sold Drawer represents **collection history**, not current market analysis.

Do not show:

- current Market Value
- Momentum
- Liquidity

Order:

1. Identity / artwork
2. 我的歷史
3. 售出紀錄
4. `查看持有品明細 →`

#### 我的歷史

Contains:

- total cost
- total sale proceeds
- realized P&L
- realized return rate

#### 售出紀錄

Display each sold Holding as a lifecycle:

```text
購入資訊 → 售出資訊
```

Do not split purchase and sale into unrelated tables.

---

## 9. 持有品 `/holdings`

### 9.1 Page role

This page is a desktop-first ledger / management workbench.

It does not repeat the homepage Portfolio dashboard.

Top area contains:

- `持有品`
- client-side search field

Normal freshness is not shown. A global stale market warning may still appear across pages when the system is abnormal.

### 9.2 Search

Add lightweight client-side search over already-rendered data.

Search fields:

- card name
- series code
- card number

No advanced search, search submit button or filter drawer.

Filtering occurs as the user types.

No result state:

```text
找不到符合項目的持有品
```

### 9.3 Card Kind group

Holdings are grouped by Card Kind.

The Card Kind row is visually stronger and contains:

- small card artwork where available
- card name
- series / number
- held count
- sold count where relevant
- total cost
- single-card Market Value where available
- aggregate unrealized P&L

If the Card Kind has no Market Value, show `—`, not zero, and keep the group visible.

### 9.4 Holding rows

Each physical Holding is a subordinate row.

Held and Sold holdings remain together under the same Card Kind group so the full lifecycle is visible in one place.

Suggested fields:

- purchase date
- purchase cost
- status
- individual unrealized / realized P&L
- sale information when sold
- actions

Do not repeat identical single-card Market Value on every Holding row if the Card Kind summary already provides it.

### 9.5 Row actions

Held Holding:

- `售出` — strongest row action, but not destructive red
- `編輯`
- `⋯` → `刪除`

Sold Holding:

- `編輯`
- `⋯` → `改回持有中`, `刪除`

Low-frequency actions should not all be permanently visible.

### 9.6 Sell flow

Sell is launched from a **specific Holding row**.

The UI context itself selects the physical Holding, preserving the domain rule that the system never auto-selects FIFO / highest-cost / another holding.

Dialog includes:

- card identity
- purchase date
- purchase cost
- sale date (default today, editable)
- sale price

### 9.7 Create / edit

Global `＋ 新增持有品` opens the create dialog.

Core fields:

- Card Kind
- purchase date (default today, editable)
- purchase cost

If the Card Kind does not exist, the user may create a new Card Kind and still complete Holding creation immediately. That Card Kind enters the existing mapping queue independently.

Do not force SNKRDUNK mapping before Holding creation.

Held edit form shows only purchase fields.

Sold edit form additionally shows sale date and sale price.

### 9.8 Delete confirmation

Deletion must identify the exact Holding.

Held deletion confirmation includes:

- Card Kind
- purchase date
- purchase cost
- irreversible-action message

Sold deletion confirmation additionally includes:

- sale date
- sale price
- exact realized P&L amount that will disappear after deletion

Do not replace this with a generic `確定嗎？` dialog.

---

## 10. 卡種對應 `/queue`

### 10.1 Page role

This is a focused mapping reconciliation workspace.

The priority is:

> Focus → Compare → Decide

Do not design the Pending workflow as a dense admin table.

### 10.2 Page summary

Show a lightweight summary:

```text
待處理 N     已確認 N     不納入行情 N
```

Only `待處理` gets stronger emphasis when pending work exists.

### 10.3 No Pending state

When pending count is zero, do not render an empty table header.

Use a concise neutral state:

```text
目前沒有待處理卡種
```

Then continue to history.

### 10.4 Single-focus Pending workflow

Only one Pending Card Kind is actively resolved at a time.

Show progress such as:

```text
1 / 4
```

The workspace contains:

1. 我的卡種
2. SNKRDUNK 候選
3. candidate selection / confirmation
4. `跳過，稍後處理`

Skipping does not modify domain status; it only advances to another pending item.

### 10.5 我的卡種

Show:

- card name
- series / number
- held count where useful

If no mapped artwork exists yet, do not invent a fake image. Text identity is sufficient.

### 10.6 Candidate comparison

Candidate cards are selectable comparison targets.

Show only information useful to the mapping decision:

- official card artwork
- SNKRDUNK card name
- series / number
- variant wording when needed

Do not show:

- apparel ID
- productCatalogId
- API/debug metadata

Candidate tiles may use stronger borders than Gallery tiles because here the container itself represents a selectable target.

### 10.7 Select, then confirm

Do not confirm mapping immediately when a candidate is clicked.

Flow:

```text
選擇 candidate
→ selected state
→ 確認對應
```

Selected state:

- accent border
- subtle elevated surface
- small check mark

Avoid large filled blue blocks.

### 10.8 No candidate vs network failure

These states must remain distinct.

Successful search with zero candidates:

```text
沒有找到候選
```

Source/network failure:

```text
無法取得 SNKRDUNK 候選
重試
```

Do not represent source failure as `沒有候選`.

### 10.9 不納入行情

This is a strong user decision meaning:

> This Card Kind should not establish a SNKRDUNK market mapping.

It is not equivalent to `目前找不到正確候選`.

If no correct candidate exists today, the Card Kind remains Pending.

`不納入行情` is a secondary action placed under `⋯`, not beside normal candidate confirmation.

Confirmation states the real effect:

- no SNKRDUNK market mapping
- existing Holdings are not deleted

### 10.10 Success flow

After confirm:

- show concise inline / toast feedback
- automatically advance to the next Pending item
- if none remain, show `目前沒有待處理卡種`

Do not interrupt every successful mapping with a modal.

### 10.11 History

History appears below the Pending workspace.

Tabs:

- 已確認 N
- 不納入行情 N

Add lightweight client-side search over:

- card name
- series
- card number

#### Confirmed history row

Represent the relationship as:

```text
我的 Card Kind ↔ SNKRDUNK Card
```

Keep technical IDs out of the default UI.

`推翻對應` belongs under `⋯`.

Confirmation for undo states that:

- the Card Kind returns to Pending
- market information will be unavailable until remapped
- existing Holdings remain intact

Do not add a `不納入行情 → Pending` recovery capability unless separately specified later.

---

## 11. Responsive / Mobile Rules

### 11.1 Mobile navigation

Use compact top header + menu.

Do not add sticky bottom navigation.

Mobile menu contains:

- 收藏總覽
- 持有品
- 卡種對應
- 新增持有品

`新增持有品` does not need to remain a prominent persistent mobile CTA because mobile is not the primary write environment.

### 11.2 Mobile homepage order

Mobile order:

1. Header
2. Global warning only if abnormal
3. Held Portfolio summary
4. Trend chart
5. 我的收藏

This intentionally differs from the desktop horizontal 7:3 layout.

### 11.3 Mobile Gallery

Target: **2 columns**.

Do not default to 3-column micro-thumbnails.

Tile information remains identical to desktop; do not add extra metadata on mobile.

### 11.4 Mobile detail

Desktop Drawer becomes full-screen detail sheet.

Use back-style navigation, e.g.:

```text
← Pikachu · XY-P #203
```

No CRUD actions are added to the sheet.

### 11.5 Holdings mobile behavior

Do not create a second mobile-specific card-management UI.

The workbench may use a controlled internal horizontal scrolling container on narrow screens.

The page itself must not create uncontrolled horizontal overflow.

### 11.6 Queue mobile behavior

Candidates stack vertically.

No separate mobile workflow is required beyond responsive stacking and usable touch targets.

---

## 12. Component State Language

Use four semantic state families.

### 12.1 Normal

No status decoration is required.

Examples:

- market successfully updated within threshold
- normal Card Kind

### 12.2 Warning

Data exists but requires attention.

Examples:

- system market data stale
- card Market Value stale

### 12.3 Pending / Missing

Not an error.

Examples:

- no Market Value yet
- Momentum accumulating
- no mapping candidate currently selected
- no candidate found in a successful search

Use neutral styling.

### 12.4 Error / Destructive

Reserve for actual failure or destructive action.

Examples:

- crawl failure
- SNKRDUNK request failure
- holding deletion
- mapping undo

Do not flood normal admin screens with red controls.

---

## 13. Component Rules

### 13.1 Buttons

Three main visual strengths:

#### Primary

Examples:

- `＋ 新增持有品`
- `確認`
- `確認對應`

Accent fill.

#### Secondary

Examples:

- `取消`
- `編輯`
- `售出`
- `重試`

Neutral surface + border.

#### Destructive

Examples:

- `刪除`
- `推翻對應`

Normal state may use dark background + red text / border. Strong filled destructive treatment is reserved for final confirmation dialogs.

### 13.2 Inputs

- Standard label above input
- No floating labels
- Placeholder does not replace label
- Accent focus border + subtle focus ring
- Error shows red boundary plus clear error text

### 13.3 Tabs

Use text tabs with active underline / indicator.

Avoid large boxed button tabs.

### 13.4 Empty states

Keep empty states concise.

Examples:

- `目前沒有待處理卡種`
- `資料累積中`
- `找不到符合項目的持有品`

Do not add onboarding paragraphs, decorative illustrations or large empty-state icons.

---

## 14. Non-goals

The UI/UX redesign does **not** include:

- React / Vue migration
- SPA conversion
- Web fonts
- icon-library dependency requirement
- Light Mode
- theme toggle
- bottom navigation
- glassmorphism
- gaming neon visual treatment
- Pokémon yellow/red UI theming
- Gallery Momentum
- Gallery Market Value
- homepage CRUD controls
- Holdings advanced filter system
- Queue technical IDs
- Sold current-market analytics
- complex animation framework
- new backend financial calculations

These are intentionally excluded, not forgotten.

---

## 15. Implementation Slices

Implement in the following order.

### Slice 1 — Foundation

- add shared `design.css`
- dark tokens
- typography
- spacing
- button / input / tabs
- global header
- responsive container
- `color-scheme: dark`

Functional behavior should remain unchanged.

### Slice 2 — Portfolio Hero

- replace old totals / freshness / toolbar / trend composition
- global warning behavior
- desktop 7:3 Hero
- Held Portfolio summary
- trend refinements

Do not change Gallery interaction yet.

### Slice 3 — Collection Gallery + Drawer

- 63/88 image ratio
- Gallery responsive layout
- Held / Sold tabs
- Gallery tile redesign
- remove inline `<details>` expansion
- desktop overlay Drawer
- mobile full-screen detail
- preserve lazy detail fetch
- read-only Drawer

### Slice 4 — Holdings Workbench

- remove duplicate Portfolio KPI area
- add client-side search
- Card Kind groups
- Holding rows
- Held + Sold lifecycle together
- individual P&L
- row action hierarchy
- dialog redesign
- exact delete confirmation

Do not redesign CRUD backend behavior.

### Slice 5 — Queue

- Pending single-focus workspace
- candidate comparison
- select then confirm
- skip / later
- no-candidate vs error states
- `不納入行情`
- history relationship view
- history search
- remove technical IDs from default UI
- destructive actions under `⋯`

### Slice 6 — Responsive + Cleanup

Validate at representative widths:

- 1440px+
- 1280px
- 1024px
- tablet
- 430px
- 390px
- 375px

Then remove:

- obsolete light CSS
- obsolete `<details>` styles
- duplicated visual rules
- obsolete JS
- obsolete implementation-specific test assertions

---

## 16. Testing Strategy

Before each implementation slice:

```bash
uv run python -m pytest -q
```

After each slice:

```bash
uv run python -m pytest -q
```

Classify new failures before changing anything.

### Tier 1 — Behavioral truth constraints

If these fail, fix the UI implementation, not the test intent.

Examples:

- sample count shown with Market Value
- sample period shown with Market Value
- stale age shown
- no use of return multiples
- card without Market Value still present
- Momentum empty state
- Liquidity pair
- viewport / mobile accessibility

### Tier 2 — Correct intent, obsolete implementation coupling

Examples:

- `auto-fill` string assertion
- exact `.wall .soon` class
- radio checked implementation
- `<table>` absence
- exact overflow CSS string

If the new UI still satisfies the intent, update the assertion to reflect the new implementation.

### Tier 3 — JS / DOM implementation coupling

Examples:

- function names such as `openSale()` / `openEdit()`
- exact data attributes
- exact dialog ID
- `location.reload()`
- exact helper function names

These are expected to change during the interaction redesign and should be rewritten around the new behavior contract.

---

## 17. Acceptance Criteria

### 17.1 Global

- Dark-only UI.
- Shared visual tokens across all pages.
- No external font dependency.
- No new frontend framework.
- Global navigation is consistent across all three pages.
- `＋ 新增持有品` is the single persistent primary CTA on desktop.
- Global stale-market warning appears only when abnormal.

### 17.2 Portfolio homepage

- Desktop Hero approximately 7:3.
- Hero contains Held Portfolio only.
- Held Market Value is the largest financial number.
- Realized P&L is absent from Hero.
- Trend retains Coverage.
- Low Coverage remains visually distinguishable.
- Healthy freshness is not permanently displayed.
- Gallery follows Hero.
- Desktop Gallery targets ~6 columns.
- Mobile Gallery targets 2 columns.
- Card artwork uses 63/88 + contain.
- Tile displays identity + return only.
- Missing return displays `—`.
- Sold artwork stays full-color.
- Clicking a card does not reflow the Gallery.

### 17.3 Drawer / Sheet

- Desktop opens overlay Drawer.
- Mobile opens full-screen detail sheet.
- Drawer is read-only.
- Held and Sold use different data schemas.
- Market Value metadata remains adjacent to Market Value.
- No homepage CRUD controls.
- Detailed holding records remain visible read-only.

### 17.4 Holdings

- Search works client-side for name / series / number.
- Held and Sold holdings coexist under one Card Kind group.
- User can identify and operate on a specific physical Holding.
- Sell launches from that Holding row.
- Individual P&L is visible.
- Missing Market Value never becomes zero.
- Delete confirmation identifies the exact Holding.
- Sold deletion states the realized-P&L impact.

### 17.5 Queue

- Pending resolution is single-focus.
- Candidates are compared visually.
- Candidate selection and mapping confirmation are separate steps.
- Technical IDs are absent from normal UI.
- No-candidate and network failure states are distinct.
- `不納入行情` is secondary and intentional.
- Confirmed history shows Card Kind ↔ SNKRDUNK relationship.
- Pending count zero does not leave an empty table skeleton.

### 17.6 Mobile

- Homepage never horizontally scrolls.
- Summary appears before trend chart.
- Gallery targets two columns.
- Detail uses full-screen sheet.
- No sticky bottom navigation.

---

## 18. Post-implementation Documentation

After the redesign is fully implemented and validated:

1. Update `docs/interface.md` so it describes the new actual interface rather than the pre-redesign state.
2. Remove or rewrite obsolete sections such as the old light color table, old `10/7` image ratio, inline `<details>` interaction and duplicated page-style assumptions.
3. Keep `docs/uiux-spec.md` as the design intent / implementation reference.
4. Keep ADR-0023 as the architecture decision for shared design tokens and page-level stylesheet separation.
