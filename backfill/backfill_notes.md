# Backfill Links - Session Notes

## Goal
Fill `link` column for ~2136 rows in `data_output/stories.csv` where it's empty.
Sections affected: `top` (plus/audio rank), `reader_favorites`, `trending`.

## Scripts written
- `backfill_links.py` — Appium/simulator approach (abandoned: "search is unavailable" in iOS 26.4 simulator)
- `backfill_links_desktop.py` — macOS News.app approach (in progress)

## macOS News.app accessibility findings

### Prerequisites
- Terminal must have Accessibility access: System Settings → Privacy & Security → Accessibility

### Window structure
- Window title: "Search" (when in search view)
- Window position: ~(361, 34), size: 1300x1073
- Main content area starts at x≈621 (sidebar takes ~260px)

### Correct navigation to search
1. Click the Search sidebar item:
   ```applescript
   set base to group 1 of group 3 of group 1 of group 1 of group 1 of group 1 of group 1 of group 1 of group 1 of window 1
   click UI element 4 of base   -- UI element 4 = "Search" sidebar nav item
   ```
2. Type query (field is auto-focused after clicking Search)
3. **Must press Return to submit** — without Return, the app shows topic grid, not story results

### What we see BEFORE pressing Return (still in topic-browse mode)
- `AXButton` elements: Sports, Entertainment, Politics, Business, Tech, etc. (topic grid)
- `AXButton desc=Clear` at x≈1581 (confirms text IS in the search field)
- 2x `AXHeading desc=heading` at x=621

### What happens AFTER pressing Return — NOT YET CONFIRMED
- Still exploring: the topic grid was still showing in last test; unclear if results load

### Story elements structure (from `entire contents` dump, search active)
- Stories appear as `UI element N of base` (N=9,10,11,12...) where:
  - Channel results: `AXGenericElement` + inner `group 1 of image 1` (logo)
  - Story results: `AXGenericElement` + `static text 1` (headline) + `static text 2` (pub)
- Story headings show as `AXHeading desc=heading` at x=621

### Three-dot button
- User confirmed: buttons are ALWAYS visible (not hover-triggered)
- NOT appearing as `AXButton` in tree scans so far
- Could be inside the story element at a depth we haven't reached
- Or triggered by `perform action "AXShowMenu"` on the story element

### Known element positions (sidebar, found reliably)
- UI element 4 of base = AXGenericElement "Search" at (379, 95) — the sidebar Search button
- UI element 6 of base = AXGenericElement "Today" at (379, 127)
- UI element 5 of base = AXGroup at (569, 86) — main content container (shows 0 children when queried directly)

### What DIDN'T work
- `Cmd+F` — focuses inline search in sidebar view, not the story search
- `click` on search sidebar + type + NO Return → shows topic grid, not results
- Reading `every UI element of base` during search returns sidebar items (x=379), not stories
- Filtering by x > 500 in `entire contents` finds 0 elements during search (positions may be relative or oddly reported)
- `perform action "AXShowMenu"` on sidebar item = "AXShowMenu succeeded" but menu not found after
- `AXShowMenu` then searching for `every menu` → error

## Next steps to try
1. Click Search sidebar → type query → **press Return** → wait 3-4s → re-scan
2. After Return, check if `entire contents` now shows story elements with x > 600
3. Try `AXShowMenu` on the AXHeading elements at x=621 (these might be story cards)
4. Try pressing Down arrow after Return to navigate to first story, then check focused element
5. Check if the three-dot button appears as `AXStaticText` or nested inside story's AXGenericElement children

## Candidate interaction once story element is found
```applescript
-- Option A: AXShowMenu on story element
perform action "AXShowMenu" of storyEl
-- then click "Copy Link to Story" from menu

-- Option B: click "..." button if found
click dotsButton
-- then click "Copy Link" from menu

-- Option C: right-click via mouse (CoreGraphics ctypes)
-- Already implemented in backfill_links_desktop.py but may not be needed
```

## CSV state
- Total rows: 6805
- Missing links: 2136
- Unique searchable headlines: ~1800 (after dedup and filtering short/generic ones)
