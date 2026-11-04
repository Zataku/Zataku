#!/bin/sh
# Builds "Store Lookup.app" on a Mac. Needs Python 3 from python.org.
# Keep this file in the same folder as store_lookup.py, the two CSVs and template.cfg, then run:
#   sh build_mac.sh
cd "$(dirname "$0")" || exit 1

python3 -m venv build_env || exit 1
build_env/bin/python -m pip install --quiet pyinstaller certifi || exit 1

build_env/bin/pyinstaller --noconfirm --windowed --name "Store Lookup" \
    --hidden-import certifi \
    --add-data "Chase TH Active Accounts - Canada 2(Data).csv:." \
    --add-data "Tim Hortons - Gift Card MIDs(Sheet 1).csv:." \
    --add-data "template.cfg:." \
    store_lookup.py || exit 1

echo
echo "Done! The program is at: $(pwd)/dist/Store Lookup.app"
