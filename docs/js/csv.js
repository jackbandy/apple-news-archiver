// RFC4180-ish CSV parser:
// - commas separate fields
// - CRLF/LF separate records
// - fields may be quoted with "
// - inside quoted fields, "" represents a literal "
// - quoted fields may contain commas and newlines
//
// Returns an array of objects keyed by header name.
function parseCSV(text) {
  const rows = parseCSVRows(text);
  if (!rows.length) return [];

  const headers = rows[0].map(h => (h || '').trim());
  const out = [];
  for (let i = 1; i < rows.length; i++) {
    const vals = rows[i];
    const obj = {};
    for (let j = 0; j < headers.length; j++) {
      const key = headers[j];
      if (!key) continue;
      obj[key] = (vals[j] || '').trim();
    }
    out.push(obj);
  }
  return out;
}

function parseCSVRows(text) {
  const rows = [];
  let row = [];
  let field = '';
  let inQuote = false;

  // Iterate over characters so we can honor quoted newlines and escaped quotes.
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];

    if (inQuote) {
      if (ch === '"') {
        // Escaped quote: "" -> "
        if (text[i + 1] === '"') {
          field += '"';
          i++;
        } else {
          inQuote = false;
        }
      } else {
        field += ch;
      }
      continue;
    }

    if (ch === '"') {
      inQuote = true;
      continue;
    }

    if (ch === ',') {
      row.push(field);
      field = '';
      continue;
    }

    if (ch === '\n' || ch === '\r') {
      // Handle CRLF as a single record separator.
      if (ch === '\r' && text[i + 1] === '\n') i++;
      row.push(field);
      field = '';
      // Drop a final empty row if the file ends with a newline.
      if (row.length > 1 || row[0] !== '') rows.push(row);
      row = [];
      continue;
    }

    field += ch;
  }

  // Final field/row (for files that don't end with newline).
  row.push(field);
  if (row.length > 1 || row[0] !== '') rows.push(row);
  return rows;
}
