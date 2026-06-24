# iPad Scraper Plan

## Motivation

The iPhone scraper needs 30–40 scroll attempts, while the iPad shows many story cards per screen across multiple columns, so the
same content fits in far fewer passes. Also, the ellipsis (`...`) button on each card makes for easier link-extraction.

Output still has a JSON file per run and rows appended to stories.csv, but also keeps screenshots.

See `reference/` for screenshots and full accessibility trees from the live simulator.

---

## Four target sections

**Top Stories is always present and always at the top of the feed.**
The other three sections are optional — they may appear in any order below Top Stories,
or be absent entirely on a given run. The scraper must handle all combinations gracefully.

All sections use a **3-column layout** in landscape on iPad Pro 13-inch (M5).
Content area starts at x=320 (left sidebar occupies x=0–280).

| Section | Always present? | Header element | Landscape layout | Label format |
|---|---|---|---|---|
| **Top Stories** | Yes | `StaticText` name=`"Top Stories"` | 3-col, x=320/664/1008, w=328 | `"Publication, Headline, time ago, Author"` |
| **Trending Stories** | No | `StaticText` name=`"Trending Stories"` | 3-col, x=320/668/1016, w=320, h=112 | `"Headline, time ago, Author"` (no publication) |
| **Reader Favorites** | No | `StaticText` name=`"Reader Favorites"` | 3-col, x=320/664/1008, w=328, h=421 | `"Apple News Plus, Publication, Headline, Author"` (no time; all News+) |
| **Featured Recipe** | No | `StaticText` value=`"Featured Recipe"` | Full-width nested CollectionView | `name="Title, RECIPE"`, `value="description"` |

---

## Reference traces

### Orientation
Use **landscape**. The reference screenshots were taken in portrait; landscape will be used
for the actual scraper. 

### Screen & layout
- The `XCUIElementTypeCollectionView` is named `"Today Feed"`
- Column widths and x-positions vary by section (see table above)
- Scroll bar reports **15 pages** total at the 2-screen mark — but all 4 target sections appear within the first ~2 screens

### Apple News Plus detection
"Apple News Plus" appears in labels in different positions depending on section:
- **Top Stories**: `"Publication, Apple News Plus, Headline, ..."` — second token
- **Trending**: `"Headline, Apple News Plus, time ago, Author"` — after headline
- **Reader Favorites**: `"Apple News Plus, Publication, Headline, Author"` — first token

Check `'Apple News Plus' in label` to detect; don't rely on position.

### Scrolling — W3C touch actions

Use W3C `ActionChains` with a `PointerInput` touch. Swipe x=800 (content area, well
away from the sidebar at x=0–280) from y=750 to y=280 to advance one screenful:

```python
from appium.webdriver.common.action_chains import ActionChains
from appium.webdriver.common.actions.action_builder import ActionBuilder
from appium.webdriver.common.actions.pointer_input import PointerInput

def swipe_up(driver, x=800, from_y=750, to_y=280):
    actions = ActionChains(driver)
    actions.w3c_actions = ActionBuilder(driver, mouse=PointerInput('touch', 'touch'))
    actions.w3c_actions.pointer_action.move_to_location(x, from_y)
    actions.w3c_actions.pointer_action.pointer_down()
    actions.w3c_actions.pointer_action.pause(0.05)
    actions.w3c_actions.pointer_action.move_to_location(x, to_y)
    actions.w3c_actions.pointer_action.pause(0.05)
    actions.w3c_actions.pointer_action.release()
    actions.perform()
```

**Why not `mobile: scroll`**: Two confirmed failures during reference capture —
1. Without `elementId`, it scrolled the left sidebar CollectionView (x=10), not the feed.
2. With `elementId` + `distance=0.8`, the scroll started near the screen bottom and triggered
   iPad's multitasking App Switcher (system gesture zone), exiting the app.

The W3C swipe at x=800 (safely in the content pane) clears both issues.

After each scroll, scan for newly visible section headers. Stop when all visible
sections are collected or max passes reached.

### Link extraction — ellipsis button
Each story card has a `...` button at the bottom-right corner (confirmed in screenshot).
Tapping it opens a floating action card with **Copy Link** as a direct button.

The `...` button is not exposed as an accessibility element in the tree at rest.
Approach: coordinate-based tap at the cell's bottom-right.

```python
ellipsis_x = cell_x + cell_w - 20
ellipsis_y = cell_y + cell_h - 20
tap(driver, ellipsis_x, ellipsis_y)
copy_btn = driver.find_element(AppiumBy.ACCESSIBILITY_ID, 'Copy Link')
copy_btn.click()
link = driver.get_clipboard_text()
```

Apple News Plus stories likely have no "Copy Link" option — skip them (same as iPhone).
Reader Favorites are all News+, so no link attempts needed for that section.

### Trending Stories label parsing
No publication prefix. Time marker is reliable:
```python
# "Headline, time ago, Author"
m = re.search(r',\s*\d+\s+(?:minute|hour|day|week|month)s?\s+ago', label)
headline = label[:m.start()].strip() if m else label.strip()
author   = label[m.end():].lstrip(', ').strip() if m else ''
```
Strip `", Apple News Plus"` from headline if present (same as iPhone trending parser).

### Reader Favorites label parsing
Format: `"Apple News Plus, Publication, Headline, Author"` — no time field.
```python
# Drop the leading "Apple News Plus, " prefix, then split on ", " heuristically
parts = label.split(', ', 2)  # ["Apple News Plus", "Publication", "Headline, Author"]
publication = parts[1] if len(parts) > 1 else ''
# headline/author: no reliable separator; store the rest as headline
```

### Featured Recipe cell
The recipe lives inside a **nested `XCUIElementTypeCollectionView`** — it won't appear
when querying top-level `XCUIElementTypeCell` elements from "Today Feed". Find it
explicitly:

```python
# Detect the "Featured Recipe" sub-header
try:
    recipe_header = driver.find_element(AppiumBy.XPATH,
        '//XCUIElementTypeStaticText[@value="Featured Recipe"]')
except Exception:
    recipe_header = None

if recipe_header:
    # The recipe cell is the first XCUIElementTypeCell inside the nested CollectionView
    # that follows the Food header. Find by value/name pattern.
    recipe_els = driver.find_elements(AppiumBy.XPATH,
        '//XCUIElementTypeCollectionView//XCUIElementTypeOther[contains(@name, "RECIPE")]')
    for el in recipe_els:
        title = el.get_attribute('name')   # "Toasted-Coconut Cold-Brew Iced Coffee, RECIPE"
        description = el.get_attribute('value')  # "A refreshing, creamy drink..."
        # strip ", RECIPE" suffix
        title = re.sub(r',\s*RECIPE\s*$', '', title).strip()
```

Recipes are content articles — tap `...` to try for a link, but save the row even
without one (recipes may not have apple.news short links).

### Section header detection
Headers can be located by `ACCESSIBILITY_ID` for section-boundary logic:
- `driver.find_element(AppiumBy.ACCESSIBILITY_ID, 'Trending Stories')` → y-position
- `driver.find_element(AppiumBy.ACCESSIBILITY_ID, 'Reader Favorites')` → y-position
- `driver.find_element(AppiumBy.ACCESSIBILITY_ID, 'Featured Recipe')` → y-position (StaticText inside Food header)

XCUITest returns scrolled-past elements with negative y values, so boundaries stay
active after scrolling — same behavior as the iPhone scraper.

---

## Collection Flow

### 1. Boot and open Apple News
Appium launches the app in landscape orientation, wait ~8 s for feed to load.

### 2. Collect Top Stories (always present)
Top Stories is always at the top of the feed and always visible on load — no scrolling needed.
Take a screenshot, scan visible cells, tap `...` → Copy Link for each non-News+ story.

### 3. Scroll-and-discover loop for optional sections
The three remaining sections (Trending, Reader Favorites, Featured Recipe) may appear in
any order or not at all. Use a scan-as-you-scroll loop:

```python
OPTIONAL_SECTIONS = {'Trending Stories', 'Reader Favorites', 'Featured Recipe'}
found_sections = set()

for _ in range(MAX_PASSES):
    if found_sections >= OPTIONAL_SECTIONS:
        break  # all sections collected

    # Check for newly visible section headers
    for section_name in OPTIONAL_SECTIONS - found_sections:
        try:
            el = driver.find_element(AppiumBy.ACCESSIBILITY_ID, section_name)
            if el.location['y'] > 0:  # on-screen (negative y = scrolled past)
                collect_section(section_name)
                found_sections.add(section_name)
        except Exception:
            pass  # section not present in feed today

    swipe_up(driver)  # W3C touch action at x=800, from_y=750 → to_y=280
```

Featured Recipe requires a special XPATH lookup after the header is detected (it's in a
nested CollectionView — see above).

### 4. Save outputs
- `save_json()` / `save_stories()` — same columns as iPhone CSV
- Screenshots: one per scroll pass, named by section and datetime, e.g.
  `apple-news-trending-2026-06-24 at 12.33.35.png`, saved to `data_output_ipad/screenshots/`
- Screenshots captured in landscape must be **rotated 90° clockwise** after saving
  (simulator outputs them in a rotated pixel buffer). Use `PIL.Image.rotate(-90, expand=True)`.

---

## Device rotation

Six iPad simulators on iOS 26.4, defined in `ipad/ipad_config_real.py` - The same shuffled-rotation logic from `config.py` will be reused in `ipad_scraper.py`.

---

## File Layout

```
ipad/
  ipad_scraper.py        # new entry point
  ipad_config_real.py    # 6-device DEVICES list, APP_PATH, output paths
  IPAD-PLAN.md           # this file
  reference/
    screenshot_home.png           # top stories view (2026-06-24)
    accessibility_tree.xml        # top stories tree
    screenshot_trending.png       # trending + reader favorites + recipe (2026-06-24)
    accessibility_tree_trending.xml
util/                    # shared unchanged
data_output_ipad/        # separate from iPhone data
  screenshots/           # per-pass PNGs
  json/                  # per-run JSON files
  stories.csv            # iPad-specific CSV
```

---

## Before drafting the script

| Item | Status | Notes |
|---|---|---|
| Landscape reference trace | **Done** | 3 screenshots + trees captured (`ipad/reference/landscape/`). All sections 3-column. Content at x≥320. Scrolling via W3C swipe confirmed. |
| Section caps | **Unset** | How many stories to collect per section (like `MAX_TOP_HOME`, `MAX_TRENDING` on iPhone)? Decide before scripting. |
| `...` button offset | **Unverified in landscape** | In landscape tree_2 the ellipsis button appears at x=1306 for the section header (w=66). For individual cells, use `cell_x + cell_w - 20, cell_y + cell_h - 20` — verify on first run. |
| `find_element(ACCESSIBILITY_ID, 'Copy Link')` timing | **Unknown** | Likely needs a short `sleep(0.5)` or explicit wait after tapping `...`. |
| Do recipes have an apple.news link? | **Unknown** | Try `...` → Copy Link; save the row regardless. |
| Reader Favorites author separator | **Unknown** | No time field to split on. May need heuristic or store as headline blob. |
| Should iPad replace or supplement iPhone scraper? | **Open** | Supplement initially to cross-validate, then decide. |
