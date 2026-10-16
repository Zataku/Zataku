// pdf-to-sheet, all inside Google. See README.md for setup.
//
// Every 5 minutes, processInbox() looks in a Google Drive folder for Acrelec picking-list PDFs,
// reads the store number, delivery address, scheduled ship date and scheduled install date,
// and fills them into the first empty row of the McDonalds tab. Each PDF then moves to the
// folder's Processed/ subfolder, or to Failed/ (with the reason in its Drive description).

// ===== Settings =====
const FOLDER_ID = 'PASTE_THE_DRIVE_FOLDER_ID';  // from the folder's URL: drive.google.com/drive/folders/<this part>
const WORKSHEET = 'McDonalds';
const COLUMNS = {                                // column letter → value from the PDF
  A: 'store_number',
  C: 'street',
  D: 'city',
  E: 'province',
  F: 'postal_code',
  J: 'ship_date',
  M: 'install_date',
};
const DUPLICATE_CHECK = ['A', 'J'];              // skip a PDF if a row already has the same store and ship date
const SECRET = 'CHANGE_ME';                      // only used by pdf_to_sheet.py (the Mac version) via doPost


// ===== Run these from the editor =====

// Run once: checks the settings, makes Processed/ and Failed/, and starts the 5-minute timer.
function setup() {
  const folder = DriveApp.getFolderById(FOLDER_ID);
  subfolder(folder, 'Processed');
  subfolder(folder, 'Failed');
  if (!SpreadsheetApp.getActiveSpreadsheet().getSheetByName(WORKSHEET)) {
    throw new Error('No tab named "' + WORKSHEET + '"');
  }
  ScriptApp.getProjectTriggers()
    .filter(t => t.getHandlerFunction() === 'processInbox')
    .forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('processInbox').timeBased().everyMinutes(5).create();
  Logger.log('Watching "' + folder.getName() + '" every 5 minutes.');
}

// Reads the newest PDF in the folder (or in Processed/ / Failed/) and logs what it found. Writes nothing.
function testNewestPdf() {
  const folder = DriveApp.getFolderById(FOLDER_ID);
  let newest = null;
  [folder, subfolder(folder, 'Processed'), subfolder(folder, 'Failed')].forEach(f => {
    const it = f.getFilesByType(MimeType.PDF);
    while (it.hasNext()) {
      const file = it.next();
      if (!newest || file.getDateCreated() > newest.getDateCreated()) newest = file;
    }
  });
  if (!newest) return Logger.log('No PDFs found.');
  const text = pdfToText(newest);
  Logger.log('--- Text Google read from ' + newest.getName() + ' ---\n' + text);
  Logger.log('--- Values ---\n' + JSON.stringify(parsePickingList(text), null, 2));
}

// Stops the 5-minute timer.
function stop() {
  ScriptApp.getProjectTriggers()
    .filter(t => t.getHandlerFunction() === 'processInbox')
    .forEach(t => ScriptApp.deleteTrigger(t));
}


// ===== The timer =====

function processInbox() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(10000)) return;  // the previous run is still going
  try {
    const started = Date.now();
    const folder = DriveApp.getFolderById(FOLDER_ID);
    const processed = subfolder(folder, 'Processed');
    const failed = subfolder(folder, 'Failed');
    const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(WORKSHEET);
    const files = folder.getFilesByType(MimeType.PDF);

    // Apps Script stops a run after 6 minutes; leave the rest for the next run.
    while (files.hasNext() && Date.now() - started < 4.5 * 60 * 1000) {
      const file = files.next();
      try {
        const data = parsePickingList(pdfToText(file));
        const cells = {};
        for (const col in COLUMNS) cells[col] = data[COLUMNS[col]];
        const res = writeRow(sheet, cells, DUPLICATE_CHECK);
        file.setDescription(res.duplicate
          ? 'pdf-to-sheet: skipped, store ' + data.store_number + ' is already in row ' + res.row
          : 'pdf-to-sheet: added to row ' + res.row);
        file.moveTo(processed);
        Logger.log(file.getName() + ': ' + file.getDescription());
      } catch (err) {
        file.setDescription('pdf-to-sheet: FAILED - ' + err.message);
        file.moveTo(failed);
        Logger.log(file.getName() + ': FAILED - ' + err.message);
      }
    }
  } finally {
    lock.releaseLock();
  }
}

function subfolder(parent, name) {
  const it = parent.getFoldersByName(name);
  return it.hasNext() ? it.next() : parent.createFolder(name);
}

// Google Apps Script can't read PDFs directly: Drive converts it to a temporary Google Doc,
// we take its text, then delete the Doc. Needs the "Drive API" service (see README).
function pdfToText(file) {
  const doc = Drive.Files.create(
    { name: 'pdf-to-sheet temp - ' + file.getName(), mimeType: MimeType.GOOGLE_DOCS },
    file.getBlob());
  try {
    return DocumentApp.openById(doc.id).getBody().getText();
  } finally {
    Drive.Files.remove(doc.id);
  }
}


// ===== Reading the PDF text =====

const PROVINCES = 'AB|BC|MB|NB|NL|NS|NT|NU|ON|PE|QC|SK|YT';
const CITY_LINE = new RegExp('^(.+?)\\s+(' + PROVINCES + ')\\s+([A-Z]\\d[A-Z])\\s?(\\d[A-Z]\\d)$');
// The page has two columns; depending on how the text comes out, a left-column item can end up
// at the start of a delivery-address line ("Phone: +1418... Ste-Marie QC G6E1M2"). Strip those.
const LEFT_COLUMN = /^(?:Email\s*:\s*\S+|Phone\s*:\s*\S+|Date\s*:\s*\S+|Scheduled\s+\w+\s+Date\s*:\s*\S+)\s*/i;

function parsePickingList(text) {
  const find = (re, name) => {
    const m = text.match(re);
    if (!m) throw new Error("couldn't find the " + name);
    return m[1];
  };
  const data = {
    sales_order: find(/SO\s*#\s*:\s*(\S+)/, 'sales order number'),
    ship_date: find(/Scheduled\s+Ship\s+Date\s*:\s*(\d{4}-\d{2}-\d{2})/, 'scheduled ship date'),
    install_date: find(/Scheduled\s+Install\s+Date\s*:\s*(\d{4}-\d{2}-\d{2})/, 'scheduled install date'),
  };

  const lines = text.split(/\r?\n/).map(l => l.trim()).filter(Boolean);
  const clean = l => l.replace(LEFT_COLUMN, '').trim();

  // The "City PROV POSTAL" line only appears in the delivery address.
  const cityIdx = lines.findIndex(l => CITY_LINE.test(clean(l)));
  if (cityIdx < 0) throw new Error("couldn't find the city / province / postal code line");
  // The delivery address starts after the last "McDonald's 7228" above it.
  let storeIdx = -1;
  for (let i = cityIdx - 1; i >= 0; i--) {
    if (/McDonald.s\s+\d+/.test(lines[i])) { storeIdx = i; break; }
  }
  if (storeIdx < 0) throw new Error("couldn't find the store number");
  data.store_number = lines[storeIdx].match(/McDonald.s\s+(\d+)/)[1];

  const street = lines.slice(storeIdx + 1, cityIdx).map(clean)
    .filter(l => l && !/^(Attn|Email|Phone)\s*:/i.test(l));
  if (!street.length) throw new Error("couldn't find the street address");

  const m = clean(lines[cityIdx]).match(CITY_LINE);
  data.street = tidyCase(street.join(', '));
  data.city = tidyCase(m[1]);
  data.province = m[2];
  data.postal_code = m[3] + ' ' + m[4];
  data.address = data.street + ', ' + data.city + ' ' + data.province + ' ' + data.postal_code;
  return data;
}


// ===== Capitalizing addresses like the sheet's hand-entered rows =====
// "900 blvd vachon n" → "900 Blvd Vachon N", "424 RUE DE LA RIVIÈRE" → "424 Rue de la Rivière".
// Words already in mixed case (McCowan) and the street type itself (Rd vs Road) are left alone.
// Same rules as tidy_case() in pdf_to_sheet.py.

const SMALL_WORDS = new Set(['de', 'du', 'des', 'la', 'le', 'les', 'sur', 'en', 'au', 'aux', 'et', 'of', 'the']);
const DIRECTIONS = new Set(['ne', 'nw', 'se', 'sw']);  // single letters (N, E, ...) are always uppercased
const SEP = /^[\s\-.,/]+$/;

function tidyCase(text) {
  const tokens = text.split(/([\s\-.,/]+)/);
  const out = [];
  let seenWord = false;
  tokens.forEach((tok, i) => {
    if (!tok || SEP.test(tok)) return out.push(tok);
    if (/^[A-Za-z]{2}$/.test(tok) && tokens[i + 1] === '-' && /^\d/.test(tokens[i + 2] || '')) {
      seenWord = true;
      return out.push(tok.toUpperCase());  // highway codes: ON-7, QC-138
    }
    const first = !seenWord;
    if (/\p{L}/u.test(tok) && !/^[\d#]+[\p{L}\p{N}_]*$/u.test(tok)) seenWord = true;  // "424", "#20" aren't words
    out.push(fixWord(tok, first));
  });
  return out.join('');
}

function fixWord(word, first) {
  const low = word.toLowerCase(), up = word.toUpperCase();
  const isUpper = word === up && word !== low, isLower = word === low && word !== up;
  if (!isUpper && !isLower) return word;  // mixed case already, or no letters at all
  if (/\d/.test(word)) return /^\d+(st|nd|rd|th|re|er|e)$/.test(low) ? low : word;  // 52ND → 52nd; ON7, T2G stay
  const letters = low.replace(/[^\p{L}\p{N}_]/gu, '');
  if (letters.length === 1 || DIRECTIONS.has(letters)) return up;
  if (low === 'ième' || low === 'ieme') return low;
  if (SMALL_WORDS.has(low) && !first) return low;
  let m = low.match(/^([ld]['’])(.+)$/u);  // l'église → l'Église
  if (m) return m[1] + cap(m[2]);
  if (/^mc[\p{L}\p{N}_]{2,}$/u.test(low)) return 'Mc' + cap(low.slice(2));
  return cap(low);
}

function cap(s) {
  const i = s.search(/\p{L}/u);
  return i < 0 ? s : s.slice(0, i) + s[i].toUpperCase() + s.slice(i + 1);
}


// ===== Writing to the sheet =====

// Puts cells ({"A": "7228", "J": "2026-10-22", ...}) into the first row whose column A is empty.
// Only those columns are written, so formulas and dropdowns elsewhere are left alone.
function writeRow(sheet, cells, dupCols) {
  const tz = sheet.getParent().getSpreadsheetTimeZone();
  // Last used row = last row with something in column A. (getLastRow() would count
  // leftover formulas further down, e.g. the #REF! cells in column N.)
  const colA = sheet.getRange(1, 1, sheet.getMaxRows(), 1).getValues();
  let last = 0;
  colA.forEach((r, i) => { if (r[0] !== '') last = i + 1; });

  if (dupCols && dupCols.length && last > 1) {
    const asText = v => v instanceof Date ? Utilities.formatDate(v, tz, 'yyyy-MM-dd') : String(v).trim();
    const cols = dupCols.map(c => sheet.getRange(c + '2:' + c + last).getValues());
    for (let i = 0; i < last - 1; i++) {
      if (dupCols.every((c, k) => asText(cols[k][i][0]) === String(cells[c]))) return { duplicate: true, row: i + 2 };
    }
  }

  const row = last + 1;
  if (row > sheet.getMaxRows()) sheet.insertRowsAfter(sheet.getMaxRows(), 1);
  for (const col in cells) sheet.getRange(col + row).setValue(toCell(cells[col], tz));
  return { duplicate: false, row: row };
}

// "2026-10-22" → a real date (shown in the column's own format); "7228" → a number.
function toCell(v, tz) {
  if (typeof v !== 'string') return v;
  if (/^\d{4}-\d{2}-\d{2}$/.test(v)) return Utilities.parseDate(v, tz, 'yyyy-MM-dd');
  if (/^\d+$/.test(v)) return Number(v);
  return v;
}


// ===== Optional: receive rows from pdf_to_sheet.py on a Mac (Deploy → Web app) =====

function doPost(e) {
  const lock = LockService.getScriptLock();
  lock.waitLock(30000);  // two PDFs at once must not land on the same row
  try {
    const body = JSON.parse(e.postData.contents);
    if (SECRET === 'CHANGE_ME' || body.secret !== SECRET) return reply({ ok: false, error: 'wrong secret' });
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const sheet = body.worksheet ? ss.getSheetByName(body.worksheet) : ss.getSheets()[0];
    if (!sheet) return reply({ ok: false, error: 'no tab named "' + body.worksheet + '"' });
    const res = writeRow(sheet, body.cells, body.duplicate_check || []);
    return reply({ ok: true, duplicate: res.duplicate, row: res.row });
  } catch (err) {
    return reply({ ok: false, error: String(err) });
  } finally {
    lock.releaseLock();
  }
}

function reply(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
