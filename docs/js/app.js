fetch('../data_output/stories.csv')
  .then(r => { if (!r.ok) throw new Error(r.statusText); return r.text(); })
  .then(text => { stories = dedup(parseCSV(text)); populateFilters(); render(); })
  .catch(err => {
    document.getElementById('message').textContent =
      'Could not load data. Run a local server (e.g. python3 -m http.server) from the repo root. (' + err.message + ')';
  });

['filter-section', 'filter-pub', 'search', 'filter-edited', 'filter-has-link'].forEach(id =>
  document.getElementById(id).addEventListener('input', render)
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
