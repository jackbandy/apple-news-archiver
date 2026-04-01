const COVERAGE_SECTIONS = ['top', 'trending', 'reader_favorites', 'popular'];

const COVERAGE_LABELS = {
  top:              'Top Stories',
  trending:         'Trending',
  reader_favorites: 'Reader Favorites',
  popular:          'Popular in News+',
};

function fmtRunTime(s) {
  const d = new Date(s.replace(' ', 'T'));
  return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

function buildCoverageMatrix() {
  // Aggregate story counts per (run_time, section) from all deduplicated stories.
  const runSection = {};
  stories.forEach(s => {
    s.appearances.forEach(a => {
      if (!runSection[a.run_time]) runSection[a.run_time] = {};
      runSection[a.run_time][a.section] = (runSection[a.run_time][a.section] || 0) + 1;
    });
  });

  const runs = Object.keys(runSection).sort();
  const cells = {};
  runs.forEach(run => {
    cells[run] = {};
    COVERAGE_SECTIONS.forEach(sec => {
      const count = runSection[run][sec] || 0;
      cells[run][sec] = { collected: count > 0, count };
    });
  });
  return { runs, cells };
}

function renderCoverage() {
  const container = document.getElementById('coverage');
  if (!stories.length) {
    container.innerHTML = '<p class="cv-empty">No data loaded.</p>';
    return;
  }

  const { runs, cells } = buildCoverageMatrix();

  const rows = COVERAGE_SECTIONS.map(sec => {
    const tds = runs.map(run => {
      const { collected, count } = cells[run][sec];
      const label = COVERAGE_LABELS[sec];
      const tipText = collected
        ? `${fmtRunTime(run)} \u2014 ${label}: \u2713 ${count} stor${count === 1 ? 'y' : 'ies'} collected`
        : `${fmtRunTime(run)} \u2014 ${label}: \u2717 no data`;
      const cls = collected ? `cv-cell cv-hit cv-${sec}` : 'cv-cell cv-miss';
      return `<td class="${cls}" data-tip="${esc(tipText)}">${collected ? '\u2713' : ''}</td>`;
    }).join('');
    return `<tr><th class="cv-row-label">${COVERAGE_LABELS[sec]}</th>${tds}</tr>`;
  }).join('');

  container.innerHTML =
    `<div class="cv-header">` +
    `<span class="cv-meta">${runs.length} runs &mdash; ${COVERAGE_SECTIONS.length} sections</span>` +
    `</div>` +
    `<div class="cv-scroll">` +
    `<table class="cv-table"><tbody>${rows}</tbody></table>` +
    `</div>`;

  // Auto-scroll to rightmost (most recent) column.
  const scroll = container.querySelector('.cv-scroll');
  scroll.scrollLeft = scroll.scrollWidth;
}
