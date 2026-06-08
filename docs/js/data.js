let stories = [];
let sortCol = 'last_seen', sortDir = -1;
let dateDays = [], dateMinIdx = 0, dateMaxIdx = 0;
let filterRunTime = '', filterRunSection = '';

function parseReaderAuthor(headline) {
  // "., Author" pattern — period-comma split (e.g. "Story., Katharine Chan, MSc, BSc, PMP")
  const pcIdx = headline.indexOf('., ');
  if (pcIdx !== -1) {
    return { headline: headline.slice(0, pcIdx + 1), author: headline.slice(pcIdx + 3) };
  }
  // Trailing ", Name" pattern — last comma followed by a capitalized name (e.g. "Story, Daniel Liberto")
  const commaIdx = headline.lastIndexOf(', ');
  if (commaIdx !== -1) {
    const suffix = headline.slice(commaIdx + 2);
    if (/^[A-Z][A-Za-z'-]*(?: [A-Z][A-Za-z'-]*){0,3}$/.test(suffix)) {
      return { headline: headline.slice(0, commaIdx), author: suffix };
    }
  }
  return { headline, author: null };
}

const STORY_LABELS = new Set(['Video', 'DEVELOPING', 'BREAKING', 'LIVE']);

// Bandaid: podcast cards where the episode title is mistakenly scraped as publication
const SUPPRESS_PUBLICATION = new Set([
  'https://apple.news/AYZ4Iae4tSyySB4dYS_daqw', // "The chaotic road from Twitter to X" — podcast episode title, not a publisher
]);

function extractStoryLabel(headline, publication) {
  // Pattern A: publication field is the label, real pub is the headline prefix
  // e.g. publication="Video", headline="CBS News, actual headline"
  if (STORY_LABELS.has(publication)) {
    const ci = headline.indexOf(', ');
    if (ci !== -1)
      return { headline: headline.slice(ci + 2), publication: headline.slice(0, ci), label: publication };
  }
  // Pattern B: headline starts with a label prefix
  // e.g. headline="DEVELOPING, actual headline"
  for (const lbl of STORY_LABELS) {
    if (headline.startsWith(lbl + ', '))
      return { headline: headline.slice(lbl.length + 2), publication, label: lbl };
  }
  return { headline, publication, label: null };
}

function observationKey(row) {
  const base = [row.run_time || '', row.section || '', row.rank || ''];
  return JSON.stringify(row.link
    ? [...base, 'link', row.link]
    : [...base, 'text', row.publication || '', row.headline || '']);
}

function rowRichness(row) {
  const weights = {
    link: 3,
    publication: 2,
    author: 1,
    headline: 3,
    article_headline: 2,
    resolved_link: 2,
    web_headline: 1,
  };
  const statusPriority = { '': 0, M: 1, P: 2, U: 3, V: 4 };
  return Object.entries(weights).reduce(
    (score, [field, weight]) => score + (row[field] ? weight : 0),
    statusPriority[row.link_status || ''] || 0
  );
}

function mergeObservationRows(rows) {
  const statusPriority = { '': 0, M: 1, P: 2, U: 3, V: 4 };
  const best = rows.reduce(
    (current, row) => rowRichness(row) > rowRichness(current) ? row : current,
    rows[0]
  );
  const merged = { ...best };
  rows.forEach(row => {
    Object.entries(row).forEach(([field, value]) => {
      if (value && !merged[field]) merged[field] = value;
    });
    if ((statusPriority[row.link_status || ''] || 0) >
        (statusPriority[merged.link_status || ''] || 0)) {
      merged.link_status = row.link_status;
    }
  });
  return merged;
}

function deduplicateObservations(rows) {
  const groups = new Map();
  rows.forEach(row => {
    const key = observationKey(row);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  });
  return [...groups.values()].map(mergeObservationRows);
}

function dedup(inputRows) {
  const rows = deduplicateObservations(inputRows);
  const map = new Map();
  rows.forEach(r => {
    const { headline: h0, publication: pub0, label } = extractStoryLabel(r.headline || '', r.publication || '');
    const key = r.link || `${h0}||${pub0}`;
    const normalizedPublication = SUPPRESS_PUBLICATION.has(r.link) ? '' : pub0;
    if (!map.has(key)) {
      let headline = h0;
      let author = r.author || null;
      if (r.section === 'reader_favorites' && headline) {
        const parsed = parseReaderAuthor(headline);
        headline = parsed.headline;
        author = parsed.author || author;
      }
      map.set(key, { link: r.link, headline, article_headline: r.article_headline, publication: normalizedPublication, author, label, appearances: [] });
    }
    const story = map.get(key);
    if (!story.article_headline && r.article_headline) story.article_headline = r.article_headline;
    if (!story.publication && normalizedPublication) story.publication = normalizedPublication;
    if (!story.author && r.author) story.author = r.author;
    if (!story.label && label) story.label = label;
    story.appearances.push({ run_time: r.run_time, rank: r.rank, section: r.section });
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

  const sectionCounts = { top: 0, trending: 0, reader_favorites: 0 };
  stories.forEach(s => { if (s.section in sectionCounts) sectionCounts[s.section]++; });
  const sectionLabels = { top: 'Top', trending: 'Trending', reader_favorites: 'Favorites' };
  const rows = Object.keys(sectionCounts).map(sec =>
    `<div class="stats-row"><span class="stats-label">${sectionLabels[sec]}</span><span class="stats-val">${sectionCounts[sec].toLocaleString()}</span></div>`
  ).join('');
  document.getElementById('stats-tooltip').innerHTML =
    `<div class="stats-table">${rows}</div>`;

  // Find latest run_time
  let latestRun = '';
  stories.forEach(s => {
    s.appearances.forEach(a => {
      if (a.run_time && a.run_time > latestRun) latestRun = a.run_time;
    });
  });
  const latestDate = latestRun ? new Date(latestRun).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—';
  document.getElementById('latest-run').textContent = `Latest scraper run: ${latestDate}`;
  document.getElementById('total-count').textContent = `${stories.length.toLocaleString()} stories`;
}

// Labels/sources that Apple News appends after a comma at the end
const TRAILING_LABELS_RE = /,\s*(MORE DETAILS|MORE COVERAGE|DEVELOPING STORY|BREAKING NEWS|WATCH LIVE|LIVE UPDATES?|APPLE NEWS PLUS|LIVE)\s*$/gi;

function normalizeHeadlineWords(str) {
  return str
    .replace(/[^\w\s]/g, '')
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .join(' ');
}

function stripAppleNewsExtras(headline, publication) {
  let h = headline;
  // Strip pipe or em/en-dash separated source: "Headline | Source" or "Headline — Source"
  h = h.replace(/\s*[|—–]\s*.+$/, '');
  // Strip leading source/label before comma: "CBS News, Headline" or "DEVELOPING, Headline"
  // Matches a short title-case/all-caps label (≤40 chars) followed by ", " and a headline-start char.
  // Loop to handle multi-part prefixes like "Local News, Chicago, Headline".
  const prefixRe = /^[A-Z][A-Za-z.]*(?:\s+[A-Z][A-Za-z.]*){0,6},\s+(?=[A-Z0-9"'\u201c])/;
  for (let i = 0; i < 3; i++) {
    const h2 = h.replace(prefixRe, '');
    if (h2 === h) break;
    h = h2;
  }
  // Strip trailing label after comma: "Headline, MORE DETAILS"
  h = h.replace(TRAILING_LABELS_RE, '');
  // Strip the publication name if it appears at start or end (with optional comma)
  if (publication) {
    const escaped = publication.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    h = h.replace(new RegExp('^' + escaped + ',?\\s*', 'i'), '');
    h = h.replace(new RegExp(',?\\s*' + escaped + '\\s*$', 'i'), '');
  }
  return h.replace(/\s+/g, ' ').trim();
}

function headlinesWordDiffer(appleHeadline, articleHeadline, publication) {
  const stripped = stripAppleNewsExtras(appleHeadline, publication);
  return normalizeHeadlineWords(stripped) !== normalizeHeadlineWords(articleHeadline);
}

function getFiltered() {
  if (filterRunTime) {
    return stories.filter(s =>
      s.appearances.some(a => a.run_time === filterRunTime && a.section === filterRunSection)
    );
  }
  const section  = document.getElementById('filter-section').value;
  const pub      = document.getElementById('filter-pub').value;
  const q        = document.getElementById('search').value.toLowerCase();
  const edited   = document.getElementById('filter-edited').checked;
  const hasLink  = document.getElementById('filter-has-link').checked;
  return stories.filter(s => {
    if (!s.headline && !s.publication) return false;
    if (section && s.section !== section) return false;
    if (pub     && s.publication !== pub) return false;
    if (q       && !`${s.headline} ${s.publication}`.toLowerCase().includes(q)) return false;
    if (edited  && !(s.section === 'top' && s.article_headline && headlinesWordDiffer(s.headline, s.article_headline, s.publication))) return false;
    if (hasLink && !s.link) return false;
    if (dateDays.length) {
      const minDate = dateDays[dateMinIdx];
      const maxDate = dateDays[dateMaxIdx];
      if (s.first_seen && s.first_seen.slice(0, 10) > maxDate) return false;
      if (s.last_seen  && s.last_seen.slice(0, 10)  < minDate) return false;
    }
    return true;
  });
}

function getSorted(list) {
  return [...list].sort((a, b) => {
    const av = a[sortCol] || '', bv = b[sortCol] || '';
    return av < bv ? -sortDir : av > bv ? sortDir : 0;
  });
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    deduplicateObservations,
    mergeObservationRows,
    observationKey,
  };
}
