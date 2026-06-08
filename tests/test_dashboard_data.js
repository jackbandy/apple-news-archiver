const assert = require('node:assert/strict');
const {
  deduplicateObservations,
} = require('../docs/js/data.js');

const sparse = {
  link: 'https://apple.news/story',
  rank: '1',
  section: 'top',
  run_time: '2026-06-08 12:00:00',
  headline: 'Headline',
  link_status: 'U',
};
const rich = {
  ...sparse,
  publication: 'Publisher',
  article_headline: 'Full headline',
  link_status: 'V',
  resolved_link: 'https://example.com/story',
};

const merged = deduplicateObservations([sparse, rich]);
assert.equal(merged.length, 1);
assert.equal(merged[0].publication, 'Publisher');
assert.equal(merged[0].article_headline, 'Full headline');
assert.equal(merged[0].link_status, 'V');

const differentRank = deduplicateObservations([sparse, { ...sparse, rank: '2' }]);
assert.equal(differentRank.length, 2);

const linkless = deduplicateObservations([
  { run_time: sparse.run_time, section: 'top', rank: 'plus', publication: 'A', headline: 'First' },
  { run_time: sparse.run_time, section: 'top', rank: 'plus', publication: 'B', headline: 'Second' },
]);
assert.equal(linkless.length, 2);
