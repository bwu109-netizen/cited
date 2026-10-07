---
name: Earnings Checker — Terminal Ledger
source: visual tokens adapted from the user's Stitch project "Financial Trading Dashboard UI" (design system "Institutional Terminal Precision"); content rules from docs/PRD_web.md
---

# Earnings Checker — design system

A dark, dense, hairline-framed workspace for checking figures copied out of company filings. Visual language borrowed from the reference trading-terminal design (palette, Inter + JetBrains Mono, 1px hairlines, 4px corners, compact tables, status badges). **Content is not borrowed**: no candlestick charts, price tickers, % change, live quotes, order books or market data of any kind. The core of every screen is a metrics table with status badges, page numbers and verbatim quotes from the filing.

## Colors

| Token | Hex | Use |
|---|---|---|
| canvas | #0b0d11 | page background, table header rows, inputs |
| panel | #12151c | cards, panels, table rows |
| elevated | #1a1e27 | hover rows, menus, drawers |
| hairline | #262c38 | 1px borders and dividers |
| hairline-strong | #3a4254 | hover / active borders |
| text | #f1f5f9 | primary text |
| text-muted | #94a3b8 | secondary labels, metadata |
| text-faint | #64748b | units, column headers, hints |
| accent | #38bdf8 | primary buttons, focus, selected nav, links |
| accent-hover | #7dd3fc | primary button hover |
| accent-2 | #6366f1 | cross-references (page links inside quotes) — sparingly |
| bad | #f43f5e | status "Needs review" (❌) — fill rgba(244,63,94,0.12), border rgba(244,63,94,0.30) |
| warn | #f59e0b | status "No external figure" (⚠️) — fill rgba(245,158,11,0.12), border rgba(245,158,11,0.30) |
| ok | #10b981 | status "Passed checks" (✅) — fill rgba(16,185,129,0.12), border rgba(16,185,129,0.30) |

Red, amber and green are used **only** for the three verification states, always together with an icon and a text label. Never as decoration, never for "up / down".

## Typography

- Inter for all prose, controls and titles; tabular figures on. Chinese fallback: "Noto Sans SC", "PingFang SC", sans-serif.
- JetBrains Mono for every figure, ticker, period, page marker and the uppercase column labels.

| Level | Font | Size / line | Weight | Tracking |
|---|---|---|---|---|
| display (landing headline only) | Inter | 40px / 48px | 600 | -0.02em |
| headline-xl | Inter | 24px / 32px | 600 | -0.02em |
| headline-lg | Inter | 18px / 24px | 600 | -0.015em |
| headline-md | Inter | 15px / 20px | 600 | -0.01em |
| body-md | Inter | 13px / 18px | 400 | 0 |
| body-sm | Inter | 12px / 16px | 400 | 0 |
| data-lg | JetBrains Mono | 16px / 20px | 500 | -0.01em |
| data-md | JetBrains Mono | 12px / 16px | 500 | -0.01em |
| data-sm | JetBrains Mono | 11px / 14px | 400 | 0 |
| label-caps | JetBrains Mono | 10px / 12px | 600 | +0.06em, uppercase |

## Shape, spacing, depth

- Radius 4px for cards, inputs, tables; 2px for badges; 6px max for drawers. No pill buttons.
- 4/8px spacing grid; table rows 32px (28px compact); header row 28px.
- Depth only through surface steps and 1px hairlines. No soft shadows, no gradients, no glow; menus may use one sharp shadow 0 4px 12px rgba(0,0,0,0.7).

## Components

- **Primary button**: accent background, #0b0d11 text, 32px high, Inter 12px semibold. **Secondary**: panel background, hairline border.
- **Status badge**: [icon] + label, 20px high, JetBrains Mono 10px uppercase, 2px radius, colors as above. Labels: "NEEDS REVIEW / 需要复核", "NO EXTERNAL FIGURE / 无可比数据", "PASSED CHECKS / 通过核验".
- **Metrics table**: header row canvas + label-caps in text-faint; rows panel with 1px #1a1e27 separators; numbers right-aligned in JetBrains Mono; text left-aligned in Inter. Red rows sorted first, with a one-sentence reason under the metric name.
- **Page link**: "p.5" in JetBrains Mono, accent color, opens the source-page drawer.
- **Quote**: verbatim line from the filing in JetBrains Mono 11px, text-muted, on canvas with hairline border; the matched number highlighted with rgba(56,189,248,0.15).
- **Source-page drawer**: right side, 420px, elevated surface; page image on top, parsed text below with the number highlighted.

## Content bans (from PRD §1.5)

No invented claims or numbers. In particular: no "more accurate than asking AI", no "zero silent errors", no "catches every error", no "verified correct / 100% accurate", no confidence or OCR scores, no run IDs or hashes, no "processed locally / never stored", no user avatars, no testimonials, logos or usage counts, no photos, 3D, illustrations or emoji.
