// ── Tooltip ──────────────────────────────────────────────────
const _tip = document.createElement('div');
_tip.id = 'chart-tooltip';
document.body.appendChild(_tip);

document.addEventListener('mousemove', e => {
  const el = e.target.closest('[data-tip]');
  if (!el) { _tip.style.display = 'none'; return; }
  _tip.textContent = el.getAttribute('data-tip');
  _tip.style.display = 'block';
  const tw = _tip.offsetWidth, th = _tip.offsetHeight;
  let x = e.clientX + 14, y = e.clientY - th - 10;
  if (x + tw > window.innerWidth - 6) x = e.clientX - tw - 14;
  if (y < 6) y = e.clientY + 14;
  _tip.style.left = x + 'px';
  _tip.style.top  = y + 'px';
});

// ── Stats ─────────────────────────────────────────────────────
const NOT_A_SOURCE = new Set(['Apple News Plus', 'Apple News Today']);

function computeSectionStats(section, slots) {
  const sectionStories = stories.filter(s =>
    s.appearances.some(a => a.section === section)
  );
  if (!sectionStories.length) return null;

  // Overall dataset date range (same observation window for all sections)
  let minT = Infinity, maxT = -Infinity;
  stories.forEach(s => s.appearances.forEach(a => {
    const t = new Date(a.run_time.replace(' ', 'T')).getTime();
    if (t < minT) minT = t;
    if (t > maxT) maxT = t;
  }));
  const totalDays = (maxT - minT) / 864e5;

  // Avg + median duration in section: last_observed − first_observed per story
  const durations = sectionStories.map(s => {
    const times = s.appearances
      .filter(a => a.section === section)
      .map(a => new Date(a.run_time.replace(' ', 'T')).getTime());
    return Math.max(...times) - Math.min(...times);
  });
  const avgDurationHrs = durations.reduce((a, b) => a + b, 0) / durations.length / 36e5;
  const sortedDur = [...durations].sort((a, b) => a - b);
  const mid = Math.floor(sortedDur.length / 2);
  const medianDurationHrs = (sortedDur.length % 2 === 0
    ? (sortedDur[mid - 1] + sortedDur[mid]) / 2
    : sortedDur[mid]) / 36e5;

  // Avg appearances per story in this section
  const totalApps = sectionStories.reduce((sum, s) =>
    sum + s.appearances.filter(a => a.section === section).length, 0);
  const avgAppearances = totalApps / sectionStories.length;

  // Headline edit rate (only meaningful for top)
  const headlineEditRate = section === 'top'
    ? sectionStories.filter(s => s.article_headline && s.headline !== s.article_headline).length / sectionStories.length * 100
    : null;

  // % stories with a scraped link
  const pctWithLink = sectionStories.filter(s => s.link).length / sectionStories.length * 100;

  // Source counts (exclude non-publisher entries)
  const srcCounts = {};
  sectionStories.forEach(s => {
    if (s.publication && !NOT_A_SOURCE.has(s.publication))
      srcCounts[s.publication] = (srcCounts[s.publication] || 0) + 1;
  });
  const singleSources = Object.entries(srcCounts)
    .filter(([, c]) => c === 1)
    .map(([pub]) => pub)
    .sort();
  const sortedCounts = Object.values(srcCounts).sort((a, b) => b - a);
  const totalWithPub = sortedCounts.reduce((a, b) => a + b, 0);
  const S = sortedCounts.length;

  let shannonJ = null, meanShare = null, medianShare = null;
  let top1 = null, top3 = null, top10 = null;

  if (S > 0 && totalWithPub > 0) {
    // Shannon H = −Σ pᵢ ln(pᵢ)
    let H = 0;
    sortedCounts.forEach(c => { const p = c / totalWithPub; H -= p * Math.log(p); });
    // Pielou's J (Shannon Equitability) = H / ln(S)
    shannonJ = Math.log(S) > 0 ? H / Math.log(S) : 1;

    // Source shares as % of stories with a known source
    const shares = sortedCounts.map(c => c / totalWithPub * 100); // descending
    meanShare   = 100 / S; // always equals (Σ shares) / S
    medianShare = S % 2 === 0
      ? (shares[S / 2 - 1] + shares[S / 2]) / 2
      : shares[Math.floor(S / 2)];
    top1  = shares.slice(0,  1).reduce((a, b) => a + b, 0);
    top3  = shares.slice(0,  3).reduce((a, b) => a + b, 0);
    top10 = shares.slice(0, 10).reduce((a, b) => a + b, 0);
  }

  return {
    totalStories:     sectionStories.length,
    avgDurationHrs,   medianDurationHrs,
    avgStoriesPerDay: totalDays > 0 ? sectionStories.length / totalDays : 0,
    avgPerSlot:       totalDays > 0 ? sectionStories.length / totalDays / slots : 0,
    avgAppearances,   headlineEditRate,  pctWithLink,
    uniqueSources:    S,
    singleSources,
    shannonJ, meanShare, medianShare, top1, top3, top10,
  };
}

// ── Charts ───────────────────────────────────────────────────
function renderCharts() {
  if (!stories.length) return;

  function countBySection(section) {
    const counts = {};
    stories.forEach(s => {
      if (!s.publication) return;
      if (s.appearances.some(a => a.section === section))
        counts[s.publication] = (counts[s.publication] || 0) + 1;
    });
    return counts;
  }

  const topCounts   = countBySection('top');
  const trendCounts = countBySection('trending');
  const topTotal    = Object.values(topCounts).reduce((a, b) => a + b, 0);
  const trendTotal  = Object.values(trendCounts).reduce((a, b) => a + b, 0);

  const topData = Object.entries(topCounts)
    .filter(([pub]) => !NOT_A_SOURCE.has(pub))
    .map(([pub, count]) => ({ pub, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 20);

  const trendData = Object.entries(trendCounts)
    .map(([pub, count]) => ({ pub, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 20);

  const allPubs = new Set([...Object.keys(topCounts), ...Object.keys(trendCounts)]);
  const compData = [...allPubs]
    .map(pub => ({
      pub,
      topCount:   topCounts[pub]   || 0,
      trendCount: trendCounts[pub] || 0,
      topRate:    ((topCounts[pub]   || 0) / topTotal)   * 100,
      trendRate:  ((trendCounts[pub] || 0) / trendTotal) * 100,
    }))
    .sort((a, b) => (b.topCount + b.trendCount) - (a.topCount + a.trendCount))
    .slice(0, 20);

  const compMaxRate = Math.max(...compData.map(d => Math.max(d.topRate, d.trendRate)), 1);

  renderPaperTable();
  renderSingleChart('chart-top-sources',      topData,   'top',      'Top Stories: Sources');
  renderSingleChart('chart-trending-sources', trendData, 'trending', 'Trending: Sources');
  renderCompChart(  'chart-comparison',       compData,  compMaxRate);
  renderHourChart('chart-top-hour',      'top',      'Top Stories: Hour of First Appearance',      '#8b0000');
  renderHourChart('chart-trending-hour', 'trending', 'Trending: Hour of First Appearance',         '#c95000');
}

function renderSingleChart(id, data, cls, title) {
  const maxCount = data[0]?.count || 1;
  document.getElementById(id).innerHTML = `
    <div class="chart-card">
      <h3 class="chart-title">${title}</h3>
      <p class="chart-sub">Unique stories per source &mdash; top ${data.length}, sorted by count</p>
      ${data.map(({ pub, count }) => `
        <div class="bar-row" data-tip="${count} stor${count === 1 ? 'y' : 'ies'} from ${esc(pub)}" data-pub="${esc(pub)}">
          <span class="bar-label">${esc(pub)}</span>
          <div class="bar-track">
            <div class="bar-fill ${cls}" style="width:${(count / maxCount * 100).toFixed(1)}%"></div>
          </div>
          <span class="bar-count">${count}</span>
        </div>`).join('')}
    </div>`;
}

function renderCompChart(id, data, maxRate) {
  document.getElementById(id).innerHTML = `
    <div class="chart-card">
      <h3 class="chart-title">Comparing Source Rates in Top &amp; Trending</h3>
      <p class="chart-sub">% of stories in each section from each source &mdash; top 20 by combined total</p>
      <div class="chart-legend">
        <span class="legend-swatch top"></span> Top Stories
        <span class="legend-swatch trending"></span> Trending
      </div>
      ${data.map(({ pub, topCount, trendCount, topRate, trendRate }) => `
        <div class="comp-group" data-pub="${esc(pub)}">
          <span class="comp-label">${esc(pub)}</span>
          <div class="comp-bars">
            <div class="comp-bar-row" data-tip="${topCount} stor${topCount === 1 ? 'y' : 'ies'} from ${esc(pub)} in Top Stories">
              <div class="bar-track">
                <div class="bar-fill top" style="width:${(topRate / maxRate * 100).toFixed(1)}%"></div>
              </div>
              <span class="bar-count">${topCount}</span>
            </div>
            <div class="comp-bar-row" data-tip="${trendCount} stor${trendCount === 1 ? 'y' : 'ies'} from ${esc(pub)} in Trending">
              <div class="bar-track">
                <div class="bar-fill trending" style="width:${(trendRate / maxRate * 100).toFixed(1)}%"></div>
              </div>
              <span class="bar-count">${trendCount}</span>
            </div>
          </div>
        </div>`).join('')}
    </div>`;
}

function renderHourChart(containerId, section, title, fillColor) {
  const counts = new Array(24).fill(0);
  let total = 0;
  stories.forEach(s => {
    const apps = s.appearances.filter(a => a.section === section);
    if (!apps.length) return;
    const hour = new Date(apps[0].run_time.replace(' ', 'T')).getHours();
    if (hour >= 0 && hour < 24) { counts[hour]++; total++; }
  });
  if (!total) return;

  const pcts = counts.map(c => c / total * 100);
  const yMax = Math.max(Math.ceil(Math.max(...pcts) / 5) * 5, 5);
  const CHART_H = 160;

  function fmtHour(h) {
    if (h === 0)  return '12am';
    if (h === 12) return '12pm';
    return h < 12 ? `${h}am` : `${h - 12}pm`;
  }

  function tipText(h, c) {
    const pct = pcts[h].toFixed(1);
    return `${fmtHour(h)}\u2013${fmtHour(h === 23 ? 0 : h + 1)} \u2014 ${pct}% of stories (${c} stor${c === 1 ? 'y' : 'ies'})`;
  }

  const yTicks = [];
  for (let v = 0; v <= yMax; v += 5) yTicks.push(v);

  const gridLines = yTicks.map(v => {
    const bottom = (v / yMax * 100).toFixed(2);
    return `<div class="hour-gridline" style="bottom:${bottom}%"></div>`;
  }).join('');

  const bars = counts.map((c, h) => {
    const hPct = (pcts[h] / yMax * 100).toFixed(2);
    return `<div class="hour-bar" style="height:${hPct}%;background:${fillColor}" data-tip="${tipText(h, c)}"></div>`;
  }).join('');

  const yAxisTicks = yTicks.map(v => {
    const bottom = (v / yMax * 100).toFixed(2);
    return `<span class="hour-ytick" style="bottom:${bottom}%">${v}%</span>`;
  }).join('');

  const xLabels = [0, 3, 6, 9, 12, 15, 18, 21].map(h => {
    const left = (h / 23 * 100).toFixed(2);
    return `<span class="hour-xlabel" style="left:${left}%">${fmtHour(h)}</span>`;
  }).join('');

  document.getElementById(containerId).innerHTML =
    `<div class="chart-card">` +
    `<h3 class="chart-title">${title}</h3>` +
    `<p class="chart-sub">% of stories first observed in this section at each hour of day (n\u202f=\u202f${total.toLocaleString()})</p>` +
    `<div class="hour-body">` +
    `<div class="hour-yaxis" style="height:${CHART_H}px">${yAxisTicks}</div>` +
    `<div class="hour-plot">` +
    `<div class="hour-bars-area" style="height:${CHART_H}px">${gridLines}<div class="hour-bars">${bars}</div></div>` +
    `<div class="hour-xlabels">${xLabels}</div>` +
    `</div>` +
    `</div>` +
    `</div>`;
}

function ohwDropdown(label, sources) {
  if (!sources.length) return '';
  const items = sources.map(s => `<li><span class="ohw-source" data-pub="${esc(s)}">${esc(s)}</span></li>`).join('');
  return `<details class="ohw-details"><summary>${label} (${sources.length})</summary>` +
    `<p class="paper-note" style="margin:6px 0 8px">Sources that appeared in this section only once across the entire observation period.</p>` +
    `<ul class="ohw-list">${items}</ul></details>`;
}

function renderPaperTable() {
  const top   = computeSectionStats('top',      6);
  const trend = computeSectionStats('trending', 5);
  if (!top || !trend) return;

  // Observation period (shared across both sections)
  let minT = Infinity, maxT = -Infinity;
  stories.forEach(s => s.appearances.forEach(a => {
    const t = new Date(a.run_time.replace(' ', 'T')).getTime();
    if (t < minT) minT = t;
    if (t > maxT) maxT = t;
  }));
  const days = ((maxT - minT) / 864e5).toFixed(1);

  const f1  = v => v === null ? '—' : v.toFixed(1);
  const f3  = v => v === null ? '—' : v.toFixed(3);
  const pct = v => v === null ? '—' : v.toFixed(1) + '%';

  function row(label, topVal, trendVal) {
    return `<tr><td>${label}</td><td>${topVal}</td><td>${trendVal}</td></tr>`;
  }
  function sec(label) {
    return `<tr class="paper-section-header"><td colspan="3">${label}</td></tr>`;
  }

  document.getElementById('chart-paper-table').innerHTML =
    `<div class="chart-card">` +
    `<h3 class="chart-title">Summary of Results</h3>` +
    `<p class="chart-sub">Calculated from ${days} days of collected data.</p>` +
    `<table class="paper-table"><thead><tr><th></th><th>Curation</th><th>Algorithmic</th></tr></thead><tbody>` +
    sec('Churn Rate') +
    row('Total Stories Analyzed',        top.totalStories.toLocaleString(),   trend.totalStories.toLocaleString()) +
    row('Avg. Story Duration',           f1(top.avgDurationHrs) + ' hrs',     f1(trend.avgDurationHrs) + ' hrs') +
    row('Median Story Duration',         f1(top.medianDurationHrs) + ' hrs',  f1(trend.medianDurationHrs) + ' hrs') +
    row('Avg. Stories per Day',          f1(top.avgStoriesPerDay),             f1(trend.avgStoriesPerDay)) +
    row('Avg. Stories per Day per Slot', f1(top.avgPerSlot),                   f1(trend.avgPerSlot)) +
    sec('Source Distribution') +
    row('Total Unique Sources',          top.uniqueSources,                    trend.uniqueSources) +
    row('Shannon Equitability Index',    f3(top.shannonJ),                     f3(trend.shannonJ)) +
    row('Mean Source Share',             pct(top.meanShare),                   pct(trend.meanShare)) +
    row('Median Source Share',           pct(top.medianShare),                 pct(trend.medianShare)) +
    row('Top Source Share',              pct(top.top1),                        pct(trend.top1)) +
    row('Top 3 Sources Share',           pct(top.top3),                        pct(trend.top3)) +
    row('Top 10 Sources Share',          pct(top.top10),                       pct(trend.top10)) +
    sec('Scraper Statistics') +
    row('Avg. Appearances per Story',    f1(top.avgAppearances),               f1(trend.avgAppearances)) +
    row('Headline Edit Rate',            pct(top.headlineEditRate),            '—') +
    row('% Stories with Recovered Links',pct(top.pctWithLink),                 pct(trend.pctWithLink)) +
    row('Sources Appearing Only Once',   top.singleSources.length,             trend.singleSources.length) +
    `</tbody></table>` +
    ohwDropdown('Curation one-hit wonders', top.singleSources) +
    ohwDropdown('Algorithmic one-hit wonders', trend.singleSources) +
    `</div>`;
}
