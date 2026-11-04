#!/bin/sh
# Builds ImageSorter.app. Run this on a Mac that has Python 3 installed:
#   sh build_mac.sh
cd "$(dirname "$0")" || exit 1
python3 -m pip install --upgrade pyinstaller pillow -r requirements.txt || exit 1
# pillow lets PyInstaller turn icon.ico into the Mac icon format.
# RapidOCR is Windows-only (see requirements.txt); leave it and its libraries out even if they're
# installed, or PyInstaller bundles ~220 MB the Mac app never uses.
python3 -m PyInstaller --noconfirm --windowed --icon icon.ico --name ImageSorter \
    --exclude-module rapidocr --exclude-module onnxruntime --exclude-module cv2 \
    --exclude-module numpy --exclude-module PIL \
    image_sorter_app.py || exit 1
echo
echo "Done! Your program is at: $(pwd)/dist/ImageSorter.app"
