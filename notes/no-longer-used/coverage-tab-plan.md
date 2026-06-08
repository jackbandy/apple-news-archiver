# Coverage Tab Plan

## Goal

Add a "Coverage" tab to the site showing a grid of data collection runs. Each cell represents one (run, section) pair. On hover, show the timestamp, section name, and whether data was collected successfully.

---

## Data Source

Everything comes from `stories.csv`, which already contains `run_time` and `section` per row.

**Deriving coverage from the CSV:**
1. Collect all unique `run_time` values → these are the collection runs (columns)
2. For each run, note which sections have at least one row → success
3. A (run, section) pair with no rows → failure (collection missed or crashed for that section)

The four sections to track: `top`, `trending`, `reader_favorites`, `popular`

**Detecting partial failures:**
- If a run_time exists in the CSV but a section has zero rows, that section failed.
- If a run_time is entirely absent, the whole run failed — but this is harder to detect from the CSV alone since there's no "heartbeat" row. For now, assume only section-level failures are trackable from the CSV.

---

## Grid Layout

```
           | run 1 | run 2 | run 3 | ... | run N |
-----------+-------+-------+-------+-----+-------+
top        |  ✓    |  ✓    |  ✗    |     |  ✓    |
trending   |  ✓    |  ✗    |  ✓    |     |  ✓    |
reader_fav |  ✓    |  ✓    |  ✓    |     |  ✓    |
popular    |  ✗    |  ✓    |  ✓    |     |  ✓    |
```

- **Rows** = sections (4 fixed rows)
- **Columns** = collection runs, sorted chronologically (newest on the right or left — TBD, probably newest-right)
- **Cell color**: green = success, red/pink = failure, gray = unknown
- There will be ~750+ columns (one per JSON snapshot), so the grid needs horizontal scrolling and probably auto-scrolls to the right edge on load

---

## Hover Tooltip

On hover over any cell, show a small tooltip (or popover) with:
- **Timestamp**: formatted run_time (e.g., "Apr 1, 2026 at 9:07 AM")
- **Section**: human-readable name (e.g., "Top Stories")
- **Status**: "✓ Collected (N stories)" or "✗ No data"
- **Story count**: number of stories in that section for that run (if success)

---

## Implementation Plan

### 1. Data processing (`js/data.js` or new `js/coverage.js`)

Add a `buildCoverageMatrix(rows)` function:
```
Input: raw CSV rows (same array app.js already has)
Output: {
  runs: ["2026-04-01 05:07:00", "2026-04-01 06:07:00", ...],  // sorted
  sections: ["top", "trending", "reader_favorites", "popular"],
  cells: {
    "2026-04-01 05:07:00": {
      top: { success: true, count: 5 },
      trending: { success: false, count: 0 },
      ...
    },
    ...
  }
}
```

This is a pure transform on the existing CSV data — no new fetch needed.

### 2. HTML (`index.html`)

- Add "Coverage" tab button alongside existing tabs
- Add a `<div id="coverage-view">` container (hidden by default)
- Tab switching logic already exists — just extend it

### 3. Rendering (`js/coverage.js` — new file)

`renderCoverage(matrix)`:
- Build a `<table>` with section rows and run columns
- Each `<td>` gets a class (`success` or `failure`) and a `data-*` attribute set for tooltip content
- Append table into `#coverage-view`
- Auto-scroll to right edge (most recent runs) on render

Tooltip behavior:
- Use CSS `title` attribute for simplest approach, or a lightweight JS tooltip (position a `<div>` on `mouseover`, hide on `mouseleave`)
- Keep it simple — no library needed

### 4. Styling (`style.css`)

```css
.coverage-table td.success { background: #c8e6c9; }  /* light green */
.coverage-table td.failure { background: #ffcdd2; }  /* light red */
.coverage-table td:hover { outline: 2px solid #333; cursor: default; }

.coverage-tooltip {
  position: fixed;
  background: #222;
  color: #fff;
  padding: 6px 10px;
  border-radius: 4px;
  font-size: 12px;
  pointer-events: none;
  white-space: nowrap;
}
```

Column headers (run timestamps) should be rotated 90° or abbreviated (e.g., "04/01 09:07") to keep cells narrow.

---

## Open Questions

1. **Newest-left vs newest-right?** Newest-right feels natural (timeline flows left → right) but requires scrolling to see recent data. Could add a "jump to latest" button.
2. **Full run failures** (run_time absent entirely): not detectable from CSV alone. Could cross-reference JSON snapshot filenames if we want to show these. Defer for now.
3. **Column width**: with 750+ columns, cells need to be very narrow (~12–16px wide). Labels would be truncated. Consider a date-range filter to reduce columns shown.
4. **Section name mapping**: `reader_favorites` → "Reader Favorites", `popular` → "Popular in News+" — add a display name map.

---

## Files to Create/Modify

| File | Change |
|------|--------|
| `docs/js/coverage.js` | New file — `buildCoverageMatrix()` + `renderCoverage()` |
| `docs/index.html` | Add tab button + `#coverage-view` div + `<script>` tag |
| `docs/style.css` | Coverage table + tooltip styles |
| `docs/js/app.js` | Call `renderCoverage()` when CSV loads, wire up tab switch |
