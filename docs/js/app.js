// ── Date Range ───────────────────────────────────────────────
let barEls = [];
let dragging = null;

function fmtSliderDate(d) {
  const [y, m, day] = d.split('-');
  return new Date(+y, +m - 1, +day).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function buildHistogram() {
  const counts = {};
  dateDays.forEach(d => { counts[d] = 0; });
  stories.forEach(s => s.appearances.forEach(a => {
    const d = a.run_time ? a.run_time.slice(0, 10) : null;
    if (d && d in counts) counts[d]++;
  }));
  const vals = dateDays.map(d => counts[d]);
  const maxVal = Math.max(...vals, 1);
  const hist = document.getElementById('histogram');
  hist.innerHTML = '';
  barEls = vals.map(v => {
    const bar = document.createElement('div');
    bar.className = 'hist-bar';
    bar.style.height = `${Math.max(3, Math.round((v / maxVal) * 100))}%`;
    hist.appendChild(bar);
    return bar;
  });
}

function updateDateUI() {
  const total = dateDays.length - 1;
  if (total <= 0) return;
  const minPct = (dateMinIdx / total) * 100;
  const maxPct = (dateMaxIdx / total) * 100;
  document.getElementById('handle-min').style.left = `${minPct}%`;
  document.getElementById('handle-max').style.left = `${maxPct}%`;
  document.getElementById('date-fill').style.left = `${minPct}%`;
  document.getElementById('date-fill').style.width = `${maxPct - minPct}%`;
  document.getElementById('label-min').textContent = fmtSliderDate(dateDays[dateMinIdx]);
  document.getElementById('label-max').textContent = fmtSliderDate(dateDays[dateMaxIdx]);
  barEls.forEach((b, i) => b.classList.toggle('dimmed', i < dateMinIdx || i > dateMaxIdx));
}

function initDateSlider() {
  const dateSet = new Set();
  stories.forEach(s => s.appearances.forEach(a => {
    if (a.run_time) dateSet.add(a.run_time.slice(0, 10));
  }));
  const observed = [...dateSet].sort();
  if (!observed.length) return;
  // Fill in every calendar day between first and last observation
  dateDays = [];
  const cur = new Date(observed[0] + 'T00:00:00');
  const end = new Date(observed[observed.length - 1] + 'T00:00:00');
  while (cur <= end) {
    dateDays.push(cur.toISOString().slice(0, 10));
    cur.setDate(cur.getDate() + 1);
  }
  dateMinIdx = 0;
  dateMaxIdx = dateDays.length - 1;
  buildHistogram();
  updateDateUI();
}

function idxFromEvent(e) {
  const rect = document.getElementById('date-track').getBoundingClientRect();
  const clientX = e.touches ? e.touches[0].clientX : e.clientX;
  return Math.round(Math.max(0, Math.min(1, (clientX - rect.left) / rect.width)) * (dateDays.length - 1));
}

document.getElementById('handle-min').addEventListener('mousedown', e => { dragging = 'min'; e.preventDefault(); });
document.getElementById('handle-max').addEventListener('mousedown', e => { dragging = 'max'; e.preventDefault(); });
document.getElementById('handle-min').addEventListener('touchstart', e => { dragging = 'min'; e.preventDefault(); }, { passive: false });
document.getElementById('handle-max').addEventListener('touchstart', e => { dragging = 'max'; e.preventDefault(); }, { passive: false });

document.addEventListener('mousemove', e => {
  if (!dragging) return;
  const idx = idxFromEvent(e);
  if (dragging === 'min') dateMinIdx = Math.min(idx, dateMaxIdx);
  else dateMaxIdx = Math.max(idx, dateMinIdx);
  updateDateUI(); updateClearBtn(); render();
});
document.addEventListener('touchmove', e => {
  if (!dragging) return;
  const idx = idxFromEvent(e);
  if (dragging === 'min') dateMinIdx = Math.min(idx, dateMaxIdx);
  else dateMaxIdx = Math.max(idx, dateMinIdx);
  updateDateUI(); updateClearBtn(); render();
}, { passive: false });
document.addEventListener('mouseup',  () => { dragging = null; });
document.addEventListener('touchend', () => { dragging = null; });

document.getElementById('date-track').addEventListener('click', e => {
  if (dragging) return;
  const idx = idxFromEvent(e);
  if (Math.abs(idx - dateMinIdx) <= Math.abs(idx - dateMaxIdx))
    dateMinIdx = Math.min(idx, dateMaxIdx);
  else
    dateMaxIdx = Math.max(idx, dateMinIdx);
  updateDateUI(); updateClearBtn(); render();
});

document.getElementById('date-reset').addEventListener('click', () => {
  dateMinIdx = 0; dateMaxIdx = dateDays.length - 1;
  updateDateUI(); updateClearBtn(); render();
});

document.getElementById('date-range-btn').addEventListener('click', e => {
  e.stopPropagation();
  const open = document.getElementById('date-panel').classList.toggle('open');
  document.getElementById('date-range-btn').classList.toggle('active', open);
});

document.addEventListener('click', e => {
  if (!document.getElementById('date-popup-anchor').contains(e.target)) {
    document.getElementById('date-panel').classList.remove('open');
    document.getElementById('date-range-btn').classList.remove('active');
  }
});

// ── Data load ────────────────────────────────────────────────
let trendingSources = {};

Promise.all([
  fetch('../data_output/stories.csv').then(r => { if (!r.ok) throw new Error(r.statusText); return r.text(); }),
  fetch('../data_output/trending_sources_bandaid.json').then(r => r.ok ? r.json() : {}).catch(() => ({}))
]).then(([csvText, bandaid]) => {
  trendingSources = bandaid;
  stories = dedup(parseCSV(csvText));
  // apply band-aid sources to trending stories missing a publication
  stories.forEach(s => {
    if (s.section === 'trending' && !s.publication && s.link && trendingSources[s.link]) {
      s.publication = trendingSources[s.link];
    }
  });
  populateFilters();
  initDateSlider();
  renderCharts();
  renderCoverage();
  render();
}).catch(err => {
  document.getElementById('message').textContent =
    'Could not load data. Run a local server (e.g. python3 -m http.server) from the repo root. (' + err.message + ')';
});

// ── Clear filters ────────────────────────────────────────────
function isFiltered() {
  return document.getElementById('filter-section').value ||
         document.getElementById('filter-pub').value ||
         document.getElementById('search').value ||
         document.getElementById('filter-edited').checked ||
         document.getElementById('filter-has-link').checked ||
         dateMinIdx !== 0 || dateMaxIdx !== dateDays.length - 1;
}

function updateClearBtn() {
  document.getElementById('clear-filters-btn').style.display = isFiltered() ? '' : 'none';
}

function clearFilters() {
  document.getElementById('filter-section').value = '';
  document.getElementById('filter-pub').value = '';
  document.getElementById('search').value = '';
  document.getElementById('filter-edited').checked = false;
  document.getElementById('filter-has-link').checked = false;
  dateMinIdx = 0; dateMaxIdx = dateDays.length - 1;
  updateDateUI();
  updateClearBtn();
  render();
}

document.getElementById('clear-filters-btn').addEventListener('click', clearFilters);

// ── Other listeners ──────────────────────────────────────────
['filter-section', 'filter-pub', 'search', 'filter-edited', 'filter-has-link'].forEach(id =>
  document.getElementById(id).addEventListener('input', () => { updateClearBtn(); render(); })
);

document.querySelectorAll('#story-table thead th[data-col]').forEach(th => {
  th.addEventListener('click', () => {
    if (sortCol === th.dataset.col) sortDir *= -1;
    else { sortCol = th.dataset.col; sortDir = 1; }
    render();
  });
});

document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(btn.dataset.tab).classList.add('active');
  });
});

// ── Chart source → Data Table ─────────────────────────────────
function jumpToSource(pub) {
  const sel = document.getElementById('filter-pub');
  // Only jump if the option exists in the select
  if (![...sel.options].some(o => o.value === pub)) return;
  sel.value = pub;
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelector('.tab-btn[data-tab="data-table"]').classList.add('active');
  document.getElementById('data-table').classList.add('active');
  updateClearBtn();
  render();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

document.getElementById('visuals').addEventListener('click', e => {
  const el = e.target.closest('[data-pub]');
  if (el) jumpToSource(el.dataset.pub);
});
