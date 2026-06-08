import os
import tempfile
import unittest
from unittest import mock

import get_stories
from util.story_rows import read_csv_rows


STORY = (
    'https://apple.news/story',
    1,
    'top',
    '2026-06-08 12:00:00',
    '',
    'Publisher',
    '',
    'Headline',
    'Headline',
    False,
)


class FakeDriver:
    def __init__(self):
        self.terminated = False
        self.quit_called = False

    def terminate_app(self, app_id):
        self.terminated = True

    def quit(self):
        self.quit_called = True

    def find_element(self, *args):
        raise RuntimeError('not found')


class ScraperExitTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.pending = os.path.join(self.tempdir.name, 'pending')
        self.lock = os.path.join(self.tempdir.name, 'lock')
        self.patchers = [
            mock.patch.object(get_stories, 'PENDING_PATH', self.pending),
            mock.patch.object(get_stories, 'LOCK_PATH', self.lock),
            mock.patch.object(get_stories, 'sleep'),
            mock.patch.object(get_stories.subprocess, 'run'),
            mock.patch.object(get_stories, 'glob', return_value=[]),
            mock.patch.object(get_stories, 'wda_needs_reinstall', return_value=False),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_lock_contention_is_success(self):
        with mock.patch.object(get_stories, '_acquire_run_lock', return_value=None):
            self.assertEqual(get_stories.main(), 0)
        self.assertFalse(os.path.exists(self.pending))

    def test_appium_connection_failure_is_nonzero(self):
        with mock.patch.object(get_stories, 'start_driver', side_effect=RuntimeError('offline')):
            self.assertEqual(get_stories.main(), 1)
        self.assertFalse(os.path.exists(self.pending))

    def test_empty_collection_is_nonzero_and_cleans_up_driver(self):
        driver = FakeDriver()
        with (
            mock.patch.object(get_stories, 'start_driver', return_value=driver),
            mock.patch.object(get_stories, 'collect_home_page', return_value=[]),
        ):
            self.assertEqual(get_stories.main(), 1)
        self.assertTrue(driver.terminated)
        self.assertTrue(driver.quit_called)

    def test_partial_collection_is_success(self):
        driver = FakeDriver()
        with (
            mock.patch.object(get_stories, 'start_driver', return_value=driver),
            mock.patch.object(get_stories, 'collect_home_page', return_value=[STORY]),
            mock.patch.object(get_stories, 'save_json'),
            mock.patch.object(get_stories, 'save_stories', return_value=(1, 0)),
        ):
            self.assertEqual(get_stories.main(), 0)

    def test_persistence_failure_is_nonzero(self):
        driver = FakeDriver()
        with (
            mock.patch.object(get_stories, 'start_driver', return_value=driver),
            mock.patch.object(get_stories, 'collect_home_page', return_value=[STORY]),
            mock.patch.object(get_stories, 'save_json', side_effect=OSError('disk full')),
            mock.patch.object(get_stories.traceback, 'print_exc'),
        ):
            self.assertEqual(get_stories.main(), 1)

    def test_required_top_stories_view_missing_fails(self):
        driver = FakeDriver()
        with (
            mock.patch.object(get_stories, 'COLLECT_TOP_STORIES', True),
            mock.patch.object(get_stories, 'collect_home_page', return_value=[STORY]),
        ):
            with self.assertRaises(get_stories.ScraperRunError):
                get_stories._collect_run(driver, '2026-06-08 12:00:00')

    def test_save_stories_is_idempotent(self):
        path = os.path.join(self.tempdir.name, 'stories.csv')
        with mock.patch.object(get_stories, 'output_file', path):
            first_added, first_merged = get_stories.save_stories([STORY])
            second_added, second_merged = get_stories.save_stories([STORY])

        self.assertEqual((first_added, first_merged), (1, 0))
        self.assertEqual((second_added, second_merged), (0, 1))
        self.assertEqual(len(read_csv_rows(path)), 1)


if __name__ == '__main__':
    unittest.main()
