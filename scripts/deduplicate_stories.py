#!/usr/bin/env python3
import argparse
import fcntl
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from util.story_rows import deduplicate_rows, read_csv_rows, write_csv_rows_atomic

LOCK_PATH = '/tmp/apple_news_scraper.lock'


def main():
    parser = argparse.ArgumentParser(
        description='Merge duplicate story observations in a CSV.'
    )
    parser.add_argument('path', nargs='?', default='docs/data/stories.csv')
    parser.add_argument(
        '--check',
        action='store_true',
        help='Report duplicates without changing the file.',
    )
    args = parser.parse_args()

    lock_fd = open(LOCK_PATH, 'a')
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        rows = read_csv_rows(args.path)
        merged, removed = deduplicate_rows(rows)
        print('{}: {} rows, {} duplicate observations'.format(
            args.path, len(rows), removed
        ))
        if removed and not args.check:
            write_csv_rows_atomic(args.path, merged)
            print('Wrote {} merged rows'.format(len(merged)))
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()
    return 1 if args.check and removed else 0


if __name__ == '__main__':
    raise SystemExit(main())
