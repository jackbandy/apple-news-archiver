let stories = [];
let sortCol = 'last_seen', sortDir = -1;

function dedup(rows) {
  const map = new Map();
  rows.forEach(r => {
    const key = r.link || `${r.headline}||${r.publication}`;
    if (!map.has(key)) {
      map.set(key, { link: r.link, headline: r.headline, article_headline: r.article_headline, publication: r.publication, appearances: [] });
    }
    map.get(key).appearances.push({ run_time: r.run_time, rank: r.rank, section: r.section });
  });
  map.forEach(s => {
    s.appearances.sort((a, b) => a.run_time > b.run_time ? 1 : -1);
    s.first_seen = s.appearances[0].run_time;
    s.last_seen  = s.appearances[s.appearances.length - 1].run_time;
    s.section    = s.appearances[s.appearances.length - 1].section;
  });
  return [...map.values()];
}

function populateFilters() {
  const pubs = [...new Set(stories.map(s => s.publication).filter(Boolean))].sort();
  const sel  = document.getElementById('filter-pub');
  pubs.forEach(p => sel.appendChild(new Option(p, p)));

  const n = stories.length;
  document.getElementById('total-count').textContent =
    `${n.toLocaleString()} unique stor${n === 1 ? 'y' : 'ies'}`;
}

function getFiltered() {
  const section = document.getElementById('filter-section').value;
  const pub     = document.getElementById('filter-pub').value;
  const q       = document.getElementById('search').value.toLowerCase();
  return stories.filter(s => {
    if (section && s.section !== section) return false;
    if (pub     && s.publication !== pub) return false;
    if (q       && !`${s.headline} ${s.publication}`.toLowerCase().includes(q)) return false;
    return true;
  });
}

function getSorted(list) {
  return [...list].sort((a, b) => {
    const av = a[sortCol] || '', bv = b[sortCol] || '';
    return av < bv ? -sortDir : av > bv ? sortDir : 0;
  });
}
