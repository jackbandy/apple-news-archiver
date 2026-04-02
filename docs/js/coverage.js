const COVERAGE_SECTIONS = ['top', 'trending', 'reader_favorites', 'popular'];

const COVERAGE_COL_LABELS = {
  date:             'Date / Time',
  top:              'Top',
  trending:         'Trending',
  reader_favorites: 'Favorites',
  popular:          'News+',
};

const COVERAGE_COL_ORDER = ['date', 'top', 'trending', 'reader_favorites', 'popular'];

let cvSortCol = 'date';
let cvSortDir = -1;  // -1 = descending (newest first), 1 = ascending
let cvJumpDate = '';

function buildCoverageRows() {
  const runSection = {};
  stories.forEach(s => {
    s.appearances.forEach(a => {
      if (!a.run_time) return;
      if (!runSection[a.run_time]) runSection[a.run_time] = {};
      runSection[a.run_time][a.section] = (runSection[a.run_time][a.section] || 0) + 1;
    });
  });
  return Object.keys(runSection).map(run => {
    const row = { run };
    COVERAGE_SECTIONS.forEach(sec => { row[sec] = runSection[run][sec] || 0; });
    return row;
  });
}

function sortedCoverageRows(rows) {
  return rows.slice().sort((a, b) => {
    let av, bv;
    if (cvSortCol === 'date') {
      av = a.run; bv = b.run;
      return av < bv ? cvSortDir : av > bv ? -cvSortDir : 0;
    }
    av = a[cvSortCol]; bv = b[cvSortCol];
    if (av !== bv) return (bv - av) * -cvSortDir;
    return a.run < b.run ? -1 : a.run > b.run ? 1 : 0;
  });
}

function fmtCvDate(run) {
  const d = new Date(run.replace(' ', 'T'));
  return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

function renderCoverageInner(sorted) {
  const rows = cvJumpDate ? sorted.filter(r => r.run.slice(0, 10) === cvJumpDate) : sorted;

  const hdrs = COVERAGE_COL_ORDER.map(col => {
    const active = cvSortCol === col;
    const arrow = active ? (cvSortDir === -1 ? ' ↓' : ' ↑') : '';
    return `<th class="cv2-th${active ? ' cv2-sorted' : ''}" data-col="${col}">${COVERAGE_COL_LABELS[col]}${arrow}</th>`;
  }).join('');

  const trs = rows.map(row => {
    const cells = COVERAGE_COL_ORDER.map(col => {
      if (col === 'date') return `<td class="cv2-date">${fmtCvDate(row.run)}</td>`;
      const n = row[col];
      return `<td class="cv2-check${n > 0 ? ` cv2-hit cv2-${col}` : ' cv2-miss'}">${n > 0 ? '✓' : ''}</td>`;
    }).join('');
    return `<tr>${cells}</tr>`;
  }).join('');

  return `<table class="cv2-table"><thead><tr>${hdrs}</tr></thead><tbody>${trs}</tbody></table>`;
}

function renderCoverage() {
  const container = document.getElementById('coverage');
  if (!stories || !stories.length) {
    container.innerHTML = '<p class="cv-empty">No data loaded.</p>';
    return;
  }

  const allRows = buildCoverageRows();
  const sorted  = sortedCoverageRows(allRows);
  const dates   = [...new Set(allRows.map(r => r.run.slice(0, 10)))].sort().reverse();

  container.innerHTML =
    `<div class="cv2-controls">` +
      `<span class="cv2-meta">${allRows.length} runs</span>` +
      `<label class="cv2-jump-label">Jump to date&nbsp;` +
        `<input type="date" id="cv2-jump" value="${cvJumpDate}" />` +
        `<datalist id="cv2-datelist">${dates.map(d => `<option value="${d}">`).join('')}</datalist>` +
      `</label>` +
      (cvJumpDate ? `<button class="cv2-clear-btn" id="cv2-clear">Clear</button>` : '') +
    `</div>` +
    `<div class="cv2-scroll" id="cv2-scroll">${renderCoverageInner(sorted)}</div>`;

  container.querySelectorAll('.cv2-th').forEach(th => {
    th.addEventListener('click', () => {
      const col = th.dataset.col;
      if (cvSortCol === col) cvSortDir *= -1;
      else { cvSortCol = col; cvSortDir = -1; }
      renderCoverage();
    });
  });

  const jumpEl = document.getElementById('cv2-jump');
  jumpEl.addEventListener('change', () => { cvJumpDate = jumpEl.value; renderCoverage(); });

  const clearEl = document.getElementById('cv2-clear');
  if (clearEl) clearEl.addEventListener('click', () => { cvJumpDate = ''; renderCoverage(); });
}
