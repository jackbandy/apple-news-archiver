import csv
import os
import tempfile


CSV_FIELDS = [
    'link',
    'rank',
    'section',
    'run_time',
    'pub_time',
    'publication',
    'author',
    'headline',
    'article_headline',
    'link_status',
    'resolved_link',
    'web_headline',
]

_STATUS_PRIORITY = {'': 0, 'M': 1, 'P': 2, 'U': 3, 'V': 4}
_RICHNESS_WEIGHTS = {
    'link': 3,
    'publication': 2,
    'author': 1,
    'headline': 3,
    'article_headline': 2,
    'resolved_link': 2,
    'web_headline': 1,
}


def _text(value):
    return '' if value is None else str(value).strip()


def observation_key(row):
    """Return the identity of one story observation within one scraper run."""
    base = (
        _text(row.get('run_time')),
        _text(row.get('section')),
        _text(row.get('rank')),
    )
    link = _text(row.get('link'))
    if link:
        return base + ('link', link)
    return base + (
        'text',
        _text(row.get('publication')),
        _text(row.get('headline')),
    )


def _row_richness(row):
    score = sum(
        weight
        for field, weight in _RICHNESS_WEIGHTS.items()
        if _text(row.get(field))
    )
    return score + _STATUS_PRIORITY.get(_text(row.get('link_status')), 0)


def merge_rows(rows):
    """Merge duplicate observations while preserving the richest metadata."""
    rows = list(rows)
    if not rows:
        return {}

    best_index = max(range(len(rows)), key=lambda i: (_row_richness(rows[i]), -i))
    merged = {field: _text(rows[best_index].get(field)) for field in CSV_FIELDS}

    for row in rows:
        for field in CSV_FIELDS:
            value = _text(row.get(field))
            if value and not merged[field]:
                merged[field] = value

        status = _text(row.get('link_status'))
        if _STATUS_PRIORITY.get(status, 0) > _STATUS_PRIORITY.get(merged['link_status'], 0):
            merged['link_status'] = status

    return merged


def deduplicate_rows(rows):
    """Return merged rows in first-seen order and the number removed."""
    grouped = {}
    order = []
    input_count = 0

    for row in rows:
        input_count += 1
        key = observation_key(row)
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(row)

    merged = [merge_rows(grouped[key]) for key in order]
    return merged, input_count - len(merged)


def read_csv_rows(path):
    if not os.path.exists(path):
        return []
    with open(path, newline='', encoding='utf-8') as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != CSV_FIELDS:
            raise ValueError(
                "Unexpected CSV columns in {}: {}".format(path, reader.fieldnames)
            )
        return list(reader)


def write_csv_rows_atomic(path, rows):
    """Replace a CSV only after its complete replacement has been written."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix='.stories-', suffix='.csv', dir=directory)
    try:
        with os.fdopen(fd, 'w', newline='', encoding='utf-8') as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=CSV_FIELDS,
                lineterminator='\r\n',
            )
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def story_tuple_to_row(story):
    link = story[0]
    is_plus = len(story) > 9 and story[9]
    link_status = 'P' if is_plus else ('U' if link else 'M')
    values = list(story[:9]) + [link_status, '', '']
    return dict(zip(CSV_FIELDS, values))
