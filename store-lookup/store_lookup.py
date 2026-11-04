"""
Tim Hortons store lookup (no extra packages needed - uses only Python's standard library).

Type the 6-digit gift card code (ALT_MERCHANT_ID) starting with 10 or 12, e.g. 105417,
and get:
  - the gift card Merchant ID from the Gift Card MIDs file
  - the store's Merchant ID from the Chase TH Active Accounts file
  - the store's phone number and address from the Tim Hortons store locator
    (the 6-digit code is Tim Hortons' own store ID, so no API key is needed)

How the files are linked:
  * Gift card file: ALT_MERCHANT_ID (the 6-digit input)  ->  MERCHANT_ID
  * Chase file:     the LAST 4 DIGITS of the input are looked up in the number at
                    the end of "Cust Name" (e.g. "Tim Hortons #0001"), then the
                    "Merchant ID" column is returned.
                    10xxxx matches 4-digit store numbers   (105417 -> #5417)
                    12xxxx matches 5-digit store numbers   (120024 -> #20024)
                    (the prefix keeps #0024 and #20024 apart, since both end in 0024)

The result is shown as a short report (Chase MID, address, phone, gift card MID);
The report can be edited in the window (e.g. to type in a missing phone number) before saving.
"Save" (or Cmd+S / Ctrl+S) saves everything in one folder, Downloads/<code>/: the report as
shown (edits included) as <code>.txt, plus one kiosk (MCM) config file per kiosk:
K1 -> "301", K2 -> "302", ... (set how many with "Kiosks:"). Each kiosk file is a copy of
template.cfg (a working CCTAG / MerchantConnect config, kept next to the CSVs) with these
written in: Authorization Terminal + Gift Card Terminal ID (301 / 0301), PIN pad IP
(K1 192.168.1.240, K2 .241, ...), receipt header (store name/code, address, phone),
Chase Merchant ID, gift card Merchant ID and Alternate Merchant ID (00000<code>).
If the report is missing something the config needs (no Chase or gift card match, no phone,
...), only the .txt is saved and the window says what's missing.

Usage:   python store_lookup.py           (opens a lookup window)
         python store_lookup.py 105417    (print the report in the terminal)

Optional backup: if the Tim Hortons lookup fails, a Google Maps Platform API key (with the
"Places API (New)" enabled) is used to search Google by the Chase address. Set it in the window
("Google key..." button), or in the GOOGLE_MAPS_API_KEY environment variable, or in this file:
~/Library/Application Support/Store Lookup/google_api_key.txt   (Mac)
%APPDATA%/Store Lookup/google_api_key.txt                       (Windows)
"""

import csv
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request

# ---- EDIT IF YOUR FILE NAMES DIFFER -----------------------------------------
CHASE_NAME = "Chase TH Active Accounts - Canada 2(Data).csv"
GIFT_NAME = "Tim Hortons - Gift Card MIDs(Sheet 1).csv"
# -----------------------------------------------------------------------------


def find_data(name):
    """Look for a CSV next to the script / app first, then inside the packaged app."""
    if getattr(sys, "frozen", False):
        # Mac: sys.executable is .../Store Lookup.app/Contents/MacOS/Store Lookup
        # Windows: sys.executable is ...\Store Lookup.exe
        exe_dir = os.path.dirname(sys.executable)
        candidates = [os.path.join(exe_dir, name), os.path.join(sys._MEIPASS, name)]
        if sys.platform == "darwin":
            app_dir = os.path.abspath(os.path.join(exe_dir, "..", "..", ".."))
            candidates.insert(0, os.path.join(app_dir, name))
    else:
        candidates = [os.path.join(os.path.dirname(os.path.abspath(__file__)), name)]
    for path in candidates:
        if os.path.exists(path):
            return path
    return candidates[-1]


CHASE_FILE = find_data(CHASE_NAME)
GIFT_FILE = find_data(GIFT_NAME)
TEMPLATE_FILE = find_data("template.cfg")   # sample .cfg that saved .cfg files are based on

if sys.platform == "win32":
    KEY_FILE = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "Store Lookup",
                            "google_api_key.txt")
else:
    KEY_FILE = os.path.expanduser("~/Library/Application Support/Store Lookup/google_api_key.txt")
MAX_KIOSKS = 15   # PIN pad IPs run 192.168.1.240 (K1) to .254 (K15)
KIOSK_FILE = os.path.join(os.path.dirname(KEY_FILE), "kiosk_count.txt")   # last "Kiosks:" value
MONO = "Consolas" if sys.platform == "win32" else "Menlo"
PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
# Undocumented endpoint behind the timhortons.ca store finder - may change without notice.
TH_URL = "https://use1-prod-th-gateway.rbictg.com/graphql"
TH_QUERY = ("query GetRestaurant($storeId: String) { restaurant(storeId: $storeId) { "
            "storeId phoneNumber physicalAddress { address1 city stateProvince postalCode } } }")


def read_rows(path):
    """Read a CSV into a list of dicts (everything stays text, so leading zeros survive)."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def parse_store(text):
    """Return (last4, name_digits, alt) from the 6-digit input, or None if invalid."""
    alt = str(text).strip()
    if not re.fullmatch(r"1[02]\d{4}", alt):
        return None
    last4 = alt[-4:]
    name_len = 4 if alt.startswith("10") else 5   # 10xxxx -> #NNNN, 12xxxx -> #NNNNN
    return last4, name_len, alt


def load():
    chase = read_rows(CHASE_FILE)
    for row in chase:
        # number at the end of Cust Name, e.g. "Tim Hortons #0001" -> "0001"
        m = re.search(r"(\d+)\s*$", row.get("Cust Name") or "")
        row["_name_num"] = m.group(1) if m else ""
    gift = read_rows(GIFT_FILE)
    return chase, gift


def lookup(chase, gift, text):
    parsed = parse_store(text)
    if parsed is None:
        return None
    last4, name_len, alt = parsed
    chase_hits = [r for r in chase
                  if r["_name_num"].endswith(last4) and len(r["_name_num"]) == name_len]
    gift_hits = [r for r in gift if (r.get("ALT_MERCHANT_ID") or "").strip() == alt]
    return alt, chase_hits, gift_hits


def load_api_key():
    key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if not key and os.path.exists(KEY_FILE):
        with open(KEY_FILE) as f:
            key = f.read().strip()
    return key


def load_kiosk_count():
    try:
        with open(KIOSK_FILE) as f:
            return min(max(int(f.read().strip()), 1), MAX_KIOSKS)
    except (OSError, ValueError):
        return 1


def save_kiosk_count(n):
    os.makedirs(os.path.dirname(KIOSK_FILE), exist_ok=True)
    with open(KIOSK_FILE, "w") as f:
        f.write(str(n))


def save_api_key(key):
    os.makedirs(os.path.dirname(KEY_FILE), exist_ok=True)
    with open(KEY_FILE, "w") as f:
        f.write(key.strip())


def ssl_context():
    """python.org Python ships without CA certificates, so point it at a known bundle."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        if os.path.exists("/etc/ssl/cert.pem"):   # macOS system bundle
            return ssl.create_default_context(cafile="/etc/ssl/cert.pem")
        return ssl.create_default_context()


def store_address(r):
    return f"{r['Cust Addr 1']}, {r['Cust City']}, {r['Cust State Cd']} {r['Cust Postal Zip Cd']}"


def post_json(url, payload, headers, source):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=15, context=ssl_context()) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            msg = json.load(e)["error"]["message"]
        except Exception:
            msg = str(e)
        raise RuntimeError(f"{source} error: {msg}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error: {e.reason}") from None


def th_store(store_id):
    """Ask the Tim Hortons store locator about this store. Returns (phone, address dict) or None."""
    data = post_json(TH_URL, {"operationName": "GetRestaurant", "variables": {"storeId": store_id},
                              "query": TH_QUERY},
                     {"x-ui-language": "en", "x-ui-region": "CA", "x-ui-platform": "web"},
                     "Tim Hortons")
    store = (data.get("data") or {}).get("restaurant")
    if not store:
        return None
    return store.get("phoneNumber"), store.get("physicalAddress") or {}


def find_phone(address, api_key):
    """Ask Google Places for the Tim Hortons at this address. Returns (phone, name, address)."""
    data = post_json(PLACES_URL, {"textQuery": f"Tim Hortons, {address}", "regionCode": "CA"}, {
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.nationalPhoneNumber",
    }, "Google")
    places = data.get("places") or []
    if not places:
        return None
    p = places[0]
    return (p.get("nationalPhoneNumber"), (p.get("displayName") or {}).get("text", ""),
            p.get("formattedAddress", ""))


PROVINCES = {"Alberta": "AB", "British Columbia": "BC", "Manitoba": "MB", "New Brunswick": "NB",
             "Newfoundland and Labrador": "NL", "Nova Scotia": "NS", "Ontario": "ON",
             "Prince Edward Island": "PE", "Quebec": "QC", "Québec": "QC", "Saskatchewan": "SK",
             "Northwest Territories": "NT", "Nunavut": "NU", "Yukon": "YT"}


def get_phone(result, api_key):
    """Look up the store's phone (needs the network): Tim Hortons first, then Google.
    Returns (phone, tim_hortons_address, problem) - problem is None when all went well."""
    key, chase_hits, _ = result
    try:
        th = th_store(key)
    except RuntimeError as e:
        th, problem = None, f"Tim Hortons lookup failed ({e})."
    else:
        problem = "Store not found in the Tim Hortons store locator."
    th_addr = th[1] if th else None
    if th and th[0]:
        return th[0], th_addr, None
    if th:
        problem = "Tim Hortons store locator has no phone number for this store."
    if api_key and chase_hits:
        try:
            found = find_phone(store_address(chase_hits[0]), api_key)
        except RuntimeError as e:
            return None, th_addr, f"{problem} Google backup also failed ({e})."
        if found and found[0]:
            return found[0], th_addr, f"{problem} Phone taken from Google ({found[1]}, {found[2]})."
    return None, th_addr, problem


def report_fields(result, phone, th_addr):
    """The values shared by the .txt and .cfg files. Missing values are "" (or [] for gift_mids)."""
    key, chase_hits, gift_hits = result
    if chase_hits:
        r = chase_hits[0]
        mid = r["Merchant ID"]
        street = r["Cust Addr 1"].upper()
        city = f"{r['Cust City']}, {r['Cust State Cd']}".upper()
        postal = r["Cust Postal Zip Cd"].upper()
    else:
        # No Chase account - fall back to the Tim Hortons store locator address
        mid = ""
        a = th_addr or {}
        street = (a.get("address1") or "").upper()
        prov = PROVINCES.get(a.get("stateProvince"), a.get("stateProvince") or "")
        city = f"{a.get('city', '')}, {prov}".upper() if a else ""
        postal = (a.get("postalCode") or "").upper()
    d = re.sub(r"\D", "", phone or "")
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    phone_line = f"{d[:3]}-{d[3:6]}-{d[6:]}" if len(d) == 10 else (phone or "")
    # CA and US wallet rows normally share one merchant ID, so list each ID once
    gift_mids = list(dict.fromkeys(r["MERCHANT_ID"] for r in gift_hits))
    return {"code": key, "mid": mid, "street": street, "city": city, "postal": postal,
            "phone": phone_line, "gift_mids": gift_mids}


def build_report(result, phone, th_addr):
    """The text that goes in the .txt file, in this layout:
        <Chase Merchant ID>
        (blank)
        <street> / <city, province> / <postal code>
        <phone, e.g. 418-889-8891>
        (blank)
        <gift card Merchant ID>
    """
    f = report_fields(result, phone, th_addr)
    return "\n".join([f["mid"] or "NO CHASE MATCH", "", f["street"] or "ADDRESS NOT FOUND",
                      f["city"], f["postal"], f["phone"] or "PHONE NOT FOUND", "",
                      *(f["gift_mids"] or ["NO GIFT CARD MATCH"])]) + "\n"


# The .cfg is a fixed-layout binary file. TEMPLATE_FILE is a working one (store 102561, terminal
# 201); only these fields are replaced: (byte offset, field size incl. the ending NUL, value).
def cfg_fields(f, kiosk):
    terminal = kiosk_terminal(kiosk)
    return [
        (0, 13, terminal),                                    # Authorization Terminal (1st box)
        (2011, 4, terminal),                                  # Authorization Terminal (2nd box)
        (2116, 16, kiosk_pinpad_ip(kiosk)),                   # Devices > PIN Pad IP Address
        (3796, 5, terminal.zfill(4)),                         # Gift Card Terminal ID, e.g. 0301
        (139, 41, f"Tim Hortons Store/Resto {f['code']}"),   # receipt header line 1
        (180, 41, f["street"]),                               # header line 2
        (221, 41, f["city"]),                                 # header line 3
        (262, 41, f["postal"]),                               # header line 4
        (303, 41, f["phone"]),                                # header line 5
        (1154, 14, f["mid"]),                                 # Chase Merchant ID
        (3911, 17, (f["gift_mids"] or [""])[0]),              # gift card Merchant ID
        (3949, 12, f["code"].zfill(11)),                      # store code, e.g. 00000102561
    ]


def kiosk_terminal(kiosk):
    """Kiosk K1 -> terminal/file name "301", K2 -> "302", ..."""
    return str(300 + kiosk)


def kiosk_pinpad_ip(kiosk):
    """Kiosk K1 -> PIN pad at 192.168.1.240, K2 -> .241, ... (K1-K15)."""
    return f"192.168.1.{239 + kiosk}"


PLACEHOLDERS = {"NO CHASE MATCH", "ADDRESS NOT FOUND", "PHONE NOT FOUND", "NO GIFT CARD MATCH",
                "LOOKING UP PHONE..."}


def parse_report(code, text):
    """Read the (possibly hand-edited) report text back into fields for the kiosk files.
    Blank lines are ignored, so the non-blank lines must be, in order:
        Chase MID, street, city/province, postal code, phone, gift card MID (extra lines ignored).
    Returns (fields, problems, clean_text); problems is a list of what to fix before saving."""
    lines = [ln.strip() for ln in text.splitlines()]
    clean_text = "\n".join(lines).strip("\n") + "\n"
    names = ["Chase Merchant ID", "Street", "City, province", "Postal code", "Phone",
             "Gift card Merchant ID"]
    values = [ln for ln in lines if ln][:6]
    values += [""] * (6 - len(values))
    problems = []
    for name, value in zip(names, values):
        if not value or value.upper() in PLACEHOLDERS:
            problems.append(f"{name} is missing")
    mid, street, city, postal, phone, gift_mid = values
    for name, value in (("Chase Merchant ID", mid), ("Gift card Merchant ID", gift_mid)):
        if value and value.upper() not in PLACEHOLDERS and not value.isdigit():
            problems.append(f"{name} should be digits only ({value})")
    for name, value in zip(names[1:5], values[1:5]):
        if len(value) > 40:
            problems.append(f"{name} is {len(value)} characters - the receipt header fits 40")
    fields = {"code": code, "mid": mid, "street": street, "city": city, "postal": postal,
              "phone": phone, "gift_mids": [gift_mid]}
    return fields, problems, clean_text


def build_cfg(fields, kiosk):
    """Return the config bytes for one kiosk: TEMPLATE_FILE with this store's details written in.
    fields comes from report_fields() or parse_report()."""
    import unicodedata
    with open(TEMPLATE_FILE, "rb") as fh:
        data = bytearray(fh.read())
    for offset, size, value in cfg_fields(fields, kiosk):
        # plain ASCII (e.g. QUÉBEC -> QUEBEC), cut to fit, NUL-padded to the field size
        text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore")[:size - 1]
        data[offset:offset + size] = text.ljust(size, b"\0")
    return bytes(data)


def run_gui(chase, gift):
    import queue
    import threading
    import tkinter as tk
    from tkinter import scrolledtext, simpledialog

    root = tk.Tk()
    root.title("Tim Hortons Store Lookup")

    top = tk.Frame(root, padx=10, pady=10)
    top.pack(fill="x")
    tk.Label(top, text="6-digit code (e.g. 105417):").pack(side="left")
    entry = tk.Entry(top, width=12, font=(MONO, 14))
    entry.pack(side="left", padx=6)

    output = scrolledtext.ScrolledText(root, width=50, height=10, font=(MONO, 13))
    output.pack(fill="both", expand=True, padx=10)
    status = tk.Label(root, text="", anchor="w", justify="left", wraplength=480, padx=10, pady=6)
    status.pack(fill="x")

    phones = queue.Queue()    # (lookup number, phone result) from the background thread
    current = [0]             # ignore phone results from an older lookup
    code_ready = [None]       # store code whose report is in the box and ready to save

    def show(text, editable):
        output.config(state="normal")
        output.delete("1.0", "end")
        output.insert("1.0", text)
        output.config(state="normal" if editable else "disabled")

    def do_lookup(event=None):
        result = lookup(chase, gift, entry.get())
        entry.select_range(0, "end")   # so the next code can be typed straight over it
        current[0] += 1
        code_ready[0] = None
        save_btn.config(state="disabled")
        if result is None:
            show("", False)
            status.config(text="Please enter a 6-digit code starting with 10 or 12 (e.g. 105417).")
            return
        # locked until the phone lookup finishes, so the result can't overwrite your edits
        show(build_report(result, "Looking up phone...", None), False)
        status.config(text="Looking up phone number...")
        n, key = current[0], load_api_key()
        threading.Thread(target=lambda: phones.put((n, result, get_phone(result, key))),
                         daemon=True).start()

    def check_phones():
        while not phones.empty():
            n, result, (phone, th_addr, problem) = phones.get()
            if n == current[0]:
                show(build_report(result, phone, th_addr), True)
                code_ready[0] = result[0]
                save_btn.config(state="normal")
                hint = "Check the report (you can edit it), then Save."
                status.config(text=f"{problem}\n{hint}" if problem else hint)
        root.after(100, check_phones)

    def save(event=None):
        code = code_ready[0]
        if code is None:
            return
        # everything is saved from the box as it is now, including your edits
        fields, problems, text = parse_report(code, output.get("1.0", "end"))
        try:
            kiosks = int(kiosk_box.get())
            assert 1 <= kiosks <= MAX_KIOSKS
        except (ValueError, AssertionError):
            status.config(text=f"Kiosks must be a number from 1 to {MAX_KIOSKS}.")
            return
        save_kiosk_count(kiosks)
        # everything for a store goes in one folder: Downloads/<code>/<code>.txt, 301, 302, ...
        folder = os.path.join(os.path.expanduser("~/Downloads"), code)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, f"{code}.txt"), "w") as f:
            f.write(text)
        # clear kiosk files from an earlier save, so a stale 303 can't be left behind
        for k in range(1, MAX_KIOSKS + 1):
            old = os.path.join(folder, kiosk_terminal(k))
            if os.path.isfile(old):
                os.remove(old)
        if not os.path.exists(TEMPLATE_FILE):
            problems.append("template.cfg not found next to the app")
        if problems:
            # the store is missing something the kiosk config needs: save the .txt only
            status.config(text=f"Saved Downloads/{code}/{code}.txt - no MCM files for this store:\n  "
                               + "\n  ".join(problems)
                               + "\nFill these in above and Save again to make the MCM files.")
            return
        names = [kiosk_terminal(k) for k in range(1, kiosks + 1)]
        for k, name in enumerate(names, 1):
            with open(os.path.join(folder, name), "wb") as f:
                f.write(build_cfg(fields, k))
        status.config(text=f"Saved to Downloads/{code}/: {code}.txt, {', '.join(names)}")

    def set_key():
        key = simpledialog.askstring("Google API key", "Optional backup if the Tim Hortons lookup fails.\n"
                                     "Google Maps Platform API key (Places API (New) enabled):",
                                     initialvalue=load_api_key(), parent=root)
        if key is not None:
            save_api_key(key)

    tk.Button(top, text="Look up", command=do_lookup).pack(side="left")
    save_btn = tk.Button(top, text="Save", command=save, state="disabled")
    save_btn.pack(side="left", padx=6)
    tk.Label(top, text="Kiosks:").pack(side="left", padx=(6, 0))
    kiosk_box = tk.Spinbox(top, from_=1, to=MAX_KIOSKS, width=3, font=(MONO, 14))
    kiosk_box.delete(0, "end")
    kiosk_box.insert(0, str(load_kiosk_count()))
    kiosk_box.pack(side="left", padx=4)
    tk.Button(top, text="Google key...", command=set_key).pack(side="right")
    entry.bind("<Return>", do_lookup)
    root.bind("<Command-s>" if sys.platform == "darwin" else "<Control-s>", save)
    entry.focus_set()
    check_phones()
    root.mainloop()


def main():
    chase, gift = load()
    if len(sys.argv) > 1:
        result = lookup(chase, gift, sys.argv[1])
        if result is None:
            sys.exit("Please enter a 6-digit code starting with 10 or 12 (e.g. 105417).")
        phone, th_addr, problem = get_phone(result, load_api_key())
        print(build_report(result, phone, th_addr), end="")
        if problem:
            print(f"\nNote: {problem}", file=sys.stderr)
        return
    run_gui(chase, gift)


if __name__ == "__main__":
    main()
