# Collect additional sections: Editor's Picks and Popular in News+

## Sections to add
- **Editor's Picks** — curated section, distinct from Top Stories
- **Popular in News+** — currently in the section dropdown but unclear if it's being collected

## Notes
- Identify the XCUITest element labels for each section tab in the Apple News app
- Add them to the section-scraping loop in `get_stories.py` alongside the existing Top Stories / Trending pass
- Add corresponding `section` values to the CSV (e.g. `editors_picks`, `popular`)
- Update the frontend section filter dropdown and badge styles to include the new sections
