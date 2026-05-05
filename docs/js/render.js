function fmtDate(s) {
  return s ? s.replace('T', ' ').slice(0, 16) : '—';
}

function esc(s) {
  return (s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

const SECTION_LABELS = { reader_favorites: 'Reader Favorites', popular: 'Popular in News+', top: 'Top', trending: 'Trending' };
function badge(section) {
  const label = SECTION_LABELS[section] || section;
  return `<span class="badge ${section}">${label}</span>`;
}

function render() {
  const sorted = getSorted(getFiltered());
  document.getElementById('result-count').textContent =
    `${sorted.length} stor${sorted.length === 1 ? 'y' : 'ies'}`;

  const tbody = document.getElementById('story-body');
  tbody.innerHTML = '';

  const empty = sorted.length === 0;
  document.getElementById('story-table').style.display = empty ? 'none' : '';
  const msg = document.getElementById('message');
  msg.style.display = empty ? '' : 'none';
  if (empty) { msg.textContent = 'No stories match your filters.'; return; }

  sorted.forEach(s => {
    const tr = document.createElement('tr');
    const n  = s.appearances.length;
    const countNote = n > 1 ? ` <span class="count">(${n}&times;)</span>` : '';
    const displayHeadline = s.section === 'trending'
      ? s.headline.replace(/,\s*\d+\s+\w+\s+ago.*$/i, '').replace(/,\s*apple news plus.*$/i, '').trim()
      : s.headline;
    const link = s.link
      ? `<a href="${esc(s.link)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">${esc(displayHeadline)}</a>`
      : esc(displayHeadline) || '—';
    const isEdited = s.section === 'top' && s.article_headline && headlinesWordDiffer(s.headline, s.article_headline, s.publication);
    const editedBadge = isEdited ? ' <span class="badge-edited">edited</span>' : '';
    const labelBadge = s.label ? ` <span class="badge-label">${esc(s.label)}</span>` : '';
    tr.innerHTML = `
      <td>${badge(s.section)}</td>
      <td class="headline">${link}${countNote}${editedBadge}${labelBadge}</td>
      <td class="pub">${esc(s.publication) || '—'}</td>
      <td class="time">${fmtDate(s.first_seen)}</td>
      <td class="time">${fmtDate(s.last_seen)}</td>`;
    tr.addEventListener('click', () => openModal(s));
    tbody.appendChild(tr);
  });

  document.querySelectorAll('#story-table thead th').forEach(th => {
    th.classList.remove('sorted-asc', 'sorted-desc');
    if (th.dataset.col === sortCol) th.classList.add(sortDir === 1 ? 'sorted-asc' : 'sorted-desc');
  });
}
