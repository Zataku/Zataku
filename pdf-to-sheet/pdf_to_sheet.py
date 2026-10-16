"""Watch a folder for Acrelec picking-list PDFs and append each one to a Google Sheet.

Pulls the store number, delivery address, scheduled ship date and scheduled
install date out of each PDF, appends them as one row, then moves the PDF to
Processed/ (or Failed/ if something couldn't be read).

    python pdf_to_sheet.py                  # watch the inbox folder
    python pdf_to_sheet.py --test file.pdf  # just print what would be sent
"""

import argparse
import json
import re
import shutil
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import pdfplumber

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"
LOG_PATH = APP_DIR / "processed.json"  # sales order numbers already sent, so nothing is added twice

FIELDS = ("store_number", "street", "city", "province", "postal_code", "address",
          "ship_date", "install_date", "sales_order")


# ---------- PDF parsing ----------

def parse_pdf(path):
    """Return a dict of FIELDS read from one picking-list PDF. Raises ValueError if any are missing."""
    with pdfplumber.open(path) as pdf:
        page = pdf.pages[0]
        full_text = page.extract_text() or ""
        # The delivery address sits in the right-hand column; crop to it so the
        # left-hand Customer block doesn't get interleaved line-by-line.
        right_col = page.crop((page.width * 0.6, 0, page.width, page.height * 0.4)).extract_text() or ""

    def find(pattern, text, name):
        m = re.search(pattern, text)
        if not m:
            raise ValueError(f"couldn't find {name}")
        return m.group(1).strip()

    data = {
        "sales_order": find(r"SO\s*#\s*:\s*(\S+)", full_text, "sales order number"),
        "ship_date": find(r"Scheduled Ship Date:\s*(\d{4}-\d{2}-\d{2})", full_text, "scheduled ship date"),
        "install_date": find(r"Scheduled Install Date:\s*(\d{4}-\d{2}-\d{2})", full_text, "scheduled install date"),
    }

    # Delivery Address block: "Attn: ...", "McDonald's 7228", street..., "City PROV POSTAL", "Canada", "Email: ..."
    block = right_col.split("Customer - Delivery Address", 1)
    if len(block) < 2:
        raise ValueError("couldn't find the delivery address block")
    lines = [ln.strip() for ln in block[1].splitlines() if ln.strip()]
    store_idx = next((i for i, ln in enumerate(lines) if re.match(r"McDonald.s\s+\d+", ln)), None)
    if store_idx is None:
        raise ValueError("couldn't find the store number")
    data["store_number"] = re.search(r"\d+", lines[store_idx]).group()

    address = []
    for ln in lines[store_idx + 1:]:
        if ln.startswith(("Email:", "Phone:")) or ln == "Canada":
            break
        address.append(ln)
    # Last line is "City PROV POSTAL", e.g. "Ste-Marie QC G6E1M2"; everything before it is the street.
    m = re.fullmatch(r"(.+?)\s+([A-Z]{2})\s+([A-Z]\d[A-Z])\s?(\d[A-Z]\d)", address[-1]) if len(address) >= 2 else None
    if not m:
        raise ValueError(f"couldn't read the address: {address}")
    data["street"] = tidy_case(", ".join(address[:-1]))
    data["city"], data["province"] = tidy_case(m.group(1)), m.group(2)
    data["postal_code"] = f"{m.group(3)} {m.group(4)}"
    data["address"] = f"{data['street']}, {data['city']} {data['province']} {data['postal_code']}"
    return data


SMALL_WORDS = {"de", "du", "des", "la", "le", "les", "sur", "en", "au", "aux", "et", "of", "the"}
DIRECTIONS = {"ne", "nw", "se", "sw"}  # single letters (N, E, ...) are always uppercased


def tidy_case(text):
    """Capitalize an address the way the sheet's hand-entered rows are:
    "900 blvd vachon n" -> "900 Blvd Vachon N", "424 RUE DE LA RIVIÈRE" -> "424 Rue de la Rivière".
    Words already in mixed case (McCowan) and the street type itself (Rd vs Road) are left as they are."""
    # Split into words and the separators between them (spaces, hyphens, dots, commas, slashes).
    tokens = re.split(r"([\s\-.,/]+)", text)
    out, seen_word = [], False
    for i, tok in enumerate(tokens):
        if not tok or re.fullmatch(r"[\s\-.,/]+", tok):
            out.append(tok)
            continue
        if (re.fullmatch(r"[A-Za-z]{2}", tok) and i + 2 < len(tokens)
                and tokens[i + 1] == "-" and tokens[i + 2][:1].isdigit()):
            out.append(tok.upper())  # highway codes: ON-7, QC-138
            seen_word = True
            continue
        first = not seen_word
        if re.search(r"[^\W\d_]", tok) and not re.fullmatch(r"[\d#]+\w*", tok):
            seen_word = True  # civic numbers like "424" or "#20" don't count as the first word
        out.append(_fix_word(tok, first))
    return "".join(out)


def _fix_word(word, first):
    low = word.lower()
    if not word.isupper() and not word.islower():
        return word  # mixed case already, e.g. McCowan
    if re.search(r"\d", word):
        # 52ND -> 52nd, 1RE -> 1re; anything else with digits (ON-7, #20, T2G) stays as-is
        return low if re.fullmatch(r"\d+(st|nd|rd|th|re|er|e)", low) else word
    letters = re.sub(r"[^\w]", "", low)
    if len(letters) == 1 or letters in DIRECTIONS:
        return word.upper()
    if low in ("ième", "ieme"):  # "8 ième Rue"
        return low
    if low in SMALL_WORDS and not first:
        return low
    m = re.fullmatch(r"([ld]['’])(.+)", low)  # French elision: l'église -> l'Église
    if m:
        return m.group(1) + _cap(m.group(2))
    if re.fullmatch(r"mc\w{2,}", low):  # mcnaughton -> McNaughton
        return "Mc" + _cap(low[2:])
    return _cap(low)


def _cap(s):
    """Uppercase the first letter, skipping leading quotes/brackets."""
    m = re.search(r"[^\W\d_]", s)
    return s[:m.start()] + s[m.start()].upper() + s[m.start() + 1:] if m else s


# ---------- Google Sheets (via the Apps Script web app in Code.gs) ----------

def add_to_sheet(config, data):
    """Send one PDF's values to the sheet. Returns the web app's reply: {"ok", "row", "duplicate"}."""
    payload = {
        "secret": config["secret"],
        "worksheet": config.get("worksheet", ""),
        "cells": {col: data[field] for col, field in config["columns"].items()},
        "duplicate_check": config.get("duplicate_check", []),
    }
    req = urllib.request.Request(
        config["web_app_url"],
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    # Apps Script answers with a redirect to the result; urllib follows it.
    with urllib.request.urlopen(req, timeout=30) as resp:
        text = resp.read().decode()
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        raise RuntimeError("the web app didn't reply with JSON - check web_app_url and that it's deployed "
                           "with access set to 'Anyone'") from None
    if not result.get("ok"):
        raise RuntimeError(result.get("error", "unknown error"))
    return result


# ---------- Processing ----------

def load_log():
    try:
        return json.loads(LOG_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def move_to(path, folder):
    folder.mkdir(exist_ok=True)
    dest = folder / path.name
    if dest.exists():
        dest = folder / f"{path.stem} {datetime.now():%Y%m%d-%H%M%S}{path.suffix}"
    shutil.move(str(path), dest)


def wait_until_written(path, timeout=30):
    """Downloads and copies show up before they're finished; wait for the size to settle."""
    last = -1
    for _ in range(timeout * 2):
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            return False
        if size == last and size > 0:
            return True
        last = size
        time.sleep(0.5)
    return True


def process(path, config):
    path = Path(path)
    inbox = path.parent
    stamp = f"{datetime.now():%Y-%m-%d %H:%M:%S}"
    if not wait_until_written(path):
        return
    try:
        data = parse_pdf(path)
    except Exception as e:
        print(f"[{stamp}] FAILED  {path.name}: {e}")
        move_to(path, inbox / "Failed")
        return

    log = load_log()
    so = data["sales_order"]
    if so in log:
        print(f"[{stamp}] SKIPPED {path.name}: {so} was already added on {log[so]}")
        move_to(path, inbox / "Processed")
        return

    try:
        result = add_to_sheet(config, data)
    except Exception as e:
        # Leave the PDF in the inbox so it's retried next time the watcher starts.
        print(f"[{stamp}] ERROR   {path.name}: couldn't write to the sheet: {e}")
        return

    log[so] = stamp
    LOG_PATH.write_text(json.dumps(log, indent=2))
    move_to(path, inbox / "Processed")
    if result.get("duplicate"):
        print(f"[{stamp}] SKIPPED {path.name}: store {data['store_number']} is already in the sheet (row {result['row']})")
    else:
        print(f"[{stamp}] ADDED   {path.name} to row {result['row']}: store {data['store_number']}, "
              f"ship {data['ship_date']}, install {data['install_date']}")


def watch(config):
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    inbox = Path(config["inbox"]).expanduser()
    inbox.mkdir(parents=True, exist_ok=True)
    def is_pdf(p):
        p = Path(p)
        return p.parent == inbox and p.suffix.lower() == ".pdf" and not p.name.startswith(".")

    # Anything dropped in while the watcher wasn't running.
    for p in sorted(inbox.iterdir()):
        if is_pdf(p):
            process(p, config)

    class Handler(FileSystemEventHandler):
        def on_created(self, event):
            if not event.is_directory and is_pdf(event.src_path):
                process(event.src_path, config)

        def on_moved(self, event):  # browsers download to a temp name, then rename
            if not event.is_directory and is_pdf(event.dest_path):
                process(event.dest_path, config)

    observer = Observer()
    observer.schedule(Handler(), str(inbox), recursive=False)
    observer.start()
    print(f"Watching {inbox} — drop PDFs in. Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--test", nargs="+", metavar="PDF", help="print what would be read from these PDFs; sends nothing")
    args = ap.parse_args()

    if args.test:
        for f in args.test:
            try:
                print(f"{Path(f).name}: {parse_pdf(f)}")
            except Exception as e:
                print(f"{Path(f).name}: FAILED - {e}")
        return

    if not CONFIG_PATH.exists():
        sys.exit(f"Missing {CONFIG_PATH.name}. Copy config.example.json to config.json and fill it in.")
    config = json.loads(CONFIG_PATH.read_text())
    missing = [k for k in ("web_app_url", "secret", "inbox", "columns") if not config.get(k)]
    if missing:
        sys.exit(f"config.json is missing: {', '.join(missing)}")
    bad = [f for f in config["columns"].values() if f not in FIELDS]
    bad += [c for c in list(config["columns"]) + config.get("duplicate_check", []) if not re.fullmatch(r"[A-Z]{1,2}", c)]
    if bad:
        sys.exit(f"Problem in config.json columns: {bad}. Keys are column letters (A, B, ...); "
                 f"values are any of: {', '.join(FIELDS)}")
    watch(config)


if __name__ == "__main__":
    main()
