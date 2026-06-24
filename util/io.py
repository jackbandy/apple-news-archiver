import csv
import json
import os


STORY_COLUMNS = [
    'link', 'rank', 'section', 'run_time', 'pub_time',
    'publication', 'author', 'headline', 'article_headline',
    'link_status', 'resolved_link', 'web_headline',
]


def save_stories(stories, output_file):
    '''Append story rows to output_file, writing the header if the file is new.'''
    write_header = not os.path.exists(output_file)
    with open(output_file, 'a', newline='') as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(STORY_COLUMNS)
        for row in stories:
            link = row[0]
            is_plus = len(row) > 9 and row[9]
            link_status = 'P' if is_plus else ('U' if link else 'M')
            writer.writerow(list(row[:9]) + [link_status, '', ''])


def save_json(stories, run_time, output_folder):
    '''Write a per-run JSON file to output_folder/json/<run_time>.json.'''
    json_folder = os.path.join(output_folder, 'json')
    os.makedirs(json_folder, exist_ok=True)
    filename = run_time.replace(':', '-').replace(' ', '_') + '.json'
    path = os.path.join(json_folder, filename)

    keys = STORY_COLUMNS[:9]
    records = []
    for row in stories:
        d = dict(zip(keys, row))
        if len(row) > 9 and row[9]:
            d['link_status'] = 'P'
        records.append(d)

    payload = {'run_time': run_time, 'story_count': len(records), 'stories': records}
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print("JSON saved to {}".format(path))
