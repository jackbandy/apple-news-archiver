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

function dedup(rows) {
  const map = new Map();
  rows.forEach(r => {
    const { headline: h0, publication: pub0, label } = extractStoryLabel(r.headline || '', r.publication || '');
    const key = r.link || `${h0}||${pub0}`;
    if (!map.has(key)) {
      let headline = h0;
      let author = null;
      if (r.section === 'reader_favorites' && headline) {
        ({ headline, author } = parseReaderAuthor(headline));
      }
      const publication = SUPPRESS_PUBLICATION.has(r.link) ? '' : pub0;
      map.set(key, { link: r.link, headline, article_headline: r.article_headline, publication, author, label, appearances: [] });
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

// Labels/sources that Apple News appends after a comma at the end
const TRAILING_LABELS_RE = /,\s*(MORE DETAILS|MORE COVERAGE|DEVELOPING STORY|BREAKING NEWS|WATCH LIVE|LIVE UPDATES?|APPLE NEWS PLUS)\s*$/gi;

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
  // Matches a short title-case/all-caps label (≤40 chars) followed by ", " and a headline-start char
  h = h.replace(/^[A-Z][A-Za-z\s.]{0,39},\s+(?=[A-Z0-9"'\u201c])/, '');
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
