# Momentum Trading Simulator — project guidelines for Claude

## CSS — buttons

The project uses a `.sim-btn` class for ALL buttons. It's a **global** class — every button
that should look like a themed button just gets `class="sim-btn"`. Modifiers:

- `.sim-btn` — base (dark bg, bordered, mono font)
- `.sim-btn.primary` — accent-colored CTA
- `.sim-btn.danger` — red-bordered, destructive
- `.sim-btn.sim-btn-sm` — compact size for table rows / inline actions

### Rules

1. **Never use inline `style="padding:...;font-size:...;"` on buttons.** The size modifier
   classes (`.sim-btn-sm` or the scoped `.sim-modal .sim-btn` override) handle that.
2. **Never re-scope `.sim-btn`** to something like `.sim-panel .sim-btn` or
   `.my-new-section .sim-btn` — it's global. Adding a scope breaks buttons that live
   in any other container (this has happened three times already).
3. **Never invent ad-hoc button styles** using `.otc-btn`, a fresh class, or inline CSS,
   when the button is a first-class action. Use `.sim-btn` with a modifier.
4. **Hover states are in the global CSS** — don't duplicate them inline.
5. When adding a new button, the default `class="sim-btn"` should give you the right
   appearance immediately. If it doesn't, the theme scoping is wrong — fix the CSS, not
   the button tag.

Exception: the `.otc-btn` class exists specifically for dense controls inside
trade cards (tiny buttons like `25%`, `Set`, `B/E`). Only use it there.

## Trading domain

See `memory/reference_stop_limit_semantics.md` for order-type semantics (stop-limit is
NOT a plain limit, never auto-cancel on gap, etc.). When implementing any order type,
match the behavior of real brokers (ToS/IBKR/Fidelity) — do not invent semantics.

## Secondary chart — time sync (CRITICAL)

The secondary chart above the main chart MUST be date-synced with the main chart.
Two symbols have different histories (AMBA and SPY don't share bar-index-to-date
mapping), so logical/bar-index sync is WRONG.

### Hard rules

1. **Sync uses LOGICAL RANGE with a date-computed offset.** Do NOT try to sync
   via `setVisibleRange(getVisibleRange())` alone — `getVisibleRange()` clamps
   to the chart's data bounds, so when the user zooms out into whitespace, the
   time range doesn't change and chart2 appears stuck. Logical range DOES change
   with every zoom/pan. The trick is: the two charts have different data
   histories, so bar #100 on one is a different date than bar #100 on the other.
   Compute the offset = (chart2's bar index of main's first-bar date) and shift
   main's logical range by that offset before applying to chart2.
2. **Do NOT subscribe to `visibleTimeRangeChange` / `visibleLogicalRangeChange` on
   the MAIN chart** to push into chart2. These events also fire on programmatic
   setData calls (sim advance), and interact with the existing volume-pane sync
   to produce a progressive-zoom bug where the main chart narrows until one bar
   fills the screen.
3. **Secondary chart has `handleScroll:false, handleScale:false`.** It does not
   initiate its own range changes. Sync is one-way: main → secondary.
4. **Sync happens in TWO places only:**
   a) `secondaryApplyBars()` — on every sim advance/retreat, force-pushes main's
      current visible range onto chart2.
   b) DOM events (wheel/mousemove/mouseup) on `chart-wrap` — fires only on real
      user interaction, not on programmatic updates.
5. **During a sim, chart2 MUST filter out bars whose date > current sim-bar's
   date.** No lookahead. Pre-sim-start bars are fine (context + MA formation).
6. **On sim load, restore chart2 AFTER `simAllBars` and `simIdx` are set** —
   otherwise the no-lookahead filter has no valid cutoff date.
7. **The secondary chart's time axis is HIDDEN** (`timeScale.visible:false`).
   The main chart's timeline is authoritative. Two stacked visible time axes
   produce overlapping date labels.

## Main grid layout — never leave inline style across mode changes

`.main` uses `grid-template-columns` defined in CSS, with a `.sim-active` variant
for the 3-column sim layout. The panel-resize drag handler sets
`main.style.gridTemplateColumns` as an inline override for user-chosen widths.

**An inline style ALWAYS wins over CSS class rules.** If you leave a stale inline
style in place when toggling between sim-active and non-sim modes, you get a
broken layout — e.g. a 3-column inline rule when there are only 2 items (empty
right slot) or a 2-column inline rule when there are 3 items (third wraps to
row 2, overlapping things).

**Rule:** any code that toggles `sim-active` on `.main` must also clear the
inline `gridTemplateColumns` (`main.style.gridTemplateColumns=''`). See
`simSetLayoutActive`.

## Simulation persistence — exit/unload flushing

`simAutoSave` is DEBOUNCED by 500ms for efficiency during interactive work.
However, `simExit`, `simPause`, and page unload must call `simFlushSave` instead
(which sends the PUT immediately with `keepalive:true`). If you call `simAutoSave`
in those paths, the timer will fire AFTER `simId` is cleared or the page is gone,
and the save silently drops. This is how the secondary-chart symbol and other
tradePrefs previously failed to persist.
