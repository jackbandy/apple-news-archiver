import os
import tempfile
import unittest

from util.story_rows import (
    CSV_FIELDS,
    deduplicate_rows,
    read_csv_rows,
    write_csv_rows_atomic,
)


def row(**values):
    result = {field: '' for field in CSV_FIELDS}
    result.update(values)
    return result


class StoryRowsTests(unittest.TestCase):
    def test_merges_richest_metadata_for_same_observation(self):
        sparse = row(
            link='https://apple.news/story',
            rank='1',
            section='top',
            run_time='2026-06-08 12:00:00',
            headline='Headline',
            link_status='U',
        )
        rich = row(
            link='https://apple.news/story',
            rank='1',
            section='top',
            run_time='2026-06-08 12:00:00',
            publication='Publisher',
            headline='Headline',
            article_headline='Full headline',
            link_status='V',
            resolved_link='https://example.com/story',
        )

        merged, removed = deduplicate_rows([sparse, rich])

        self.assertEqual(removed, 1)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]['publication'], 'Publisher')
        self.assertEqual(merged[0]['article_headline'], 'Full headline')
        self.assertEqual(merged[0]['link_status'], 'V')
        self.assertEqual(merged[0]['resolved_link'], 'https://example.com/story')

    def test_same_link_at_different_ranks_is_preserved(self):
        first = row(
            link='https://apple.news/story',
            rank='1',
            section='top',
            run_time='2026-06-08 12:00:00',
        )
        second = dict(first, rank='2')

        merged, removed = deduplicate_rows([first, second])

        self.assertEqual(removed, 0)
        self.assertEqual(len(merged), 2)

    def test_linkless_rows_use_publication_and_headline_identity(self):
        first = row(
            rank='plus',
            section='top',
            run_time='2026-06-08 12:00:00',
            publication='Publisher A',
            headline='First',
        )
        second = dict(first, publication='Publisher B', headline='Second')

        merged, removed = deduplicate_rows([first, second])

        self.assertEqual(removed, 0)
        self.assertEqual(len(merged), 2)

    def test_atomic_write_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'stories.csv')
            expected = [row(
                link='https://apple.news/story',
                rank='1',
                section='top',
                run_time='2026-06-08 12:00:00',
            )]

            write_csv_rows_atomic(path, expected)

            self.assertEqual(read_csv_rows(path), expected)
            self.assertFalse(any(name.startswith('.stories-') for name in os.listdir(directory)))


if __name__ == '__main__':
    unittest.main()
