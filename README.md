# Side Projects

| Project | Stack | What it is |
| --- | --- | --- |
| [image-sorter](image-sorter/) | Python, Tkinter | Pick a folder of images and sort them in pairs into store folders, named from the store label (e.g. MCD7958DT) read off the photos. Preview mode shows the result without moving anything. |
| [js-calendar](js-calendar/) | HTML, CSS, JS | Calendar widget (git submodule → [Zataku/js-calendar](https://github.com/Zataku/js-calendar)). |
| [pdf-to-sheet](pdf-to-sheet/) | Google Apps Script (+ optional Python) | Upload Acrelec picking-list PDFs to a Drive folder; the store number, address, ship date and install date are filled into the McDonalds tab of a Google Sheet. |
| [store-lookup](store-lookup/) | Python, Tkinter | Look up a Tim Hortons store's merchant IDs, address and phone from its 6-digit gift card code, check or edit the report, and save it with a MerchantConnect (CCTAG) config file for each kiosk (K1 → `301`, K2 → `302`, ...). |

## Running

```sh
# Python projects
python image-sorter/image_sorter_app.py      # needs: pip install -r image-sorter/requirements.txt
python store-lookup/store_lookup.py    # needs the two data CSVs and template.cfg (see below)
```

## Building image-sorter

The same code runs on both systems; only the build script differs. Both use PyInstaller and put the result in `image-sorter/dist/`.

| | Windows | Mac |
| --- | --- | --- |
| Build | run `image-sorter\build_windows.bat` | `sh image-sorter/build_mac.sh` |
| Output | `ImageSorter.exe` | `ImageSorter.app` |
| Store label reading | Windows.Media.Ocr, then RapidOCR if it finds no label | Apple Vision |
| Sounds | winsound | afplay |
| Notes | | Built for the Mac's chip (Apple Silicon or Intel). Unsigned, so the first time on another Mac: right-click → Open. |

Label reading runs entirely on the computer. RapidOCR's models ship inside the `rapidocr` package and the Windows build bundles them, so nothing is downloaded or uploaded. RapidOCR is Windows-only: on the Mac, Apple Vision already reads the labels, and RapidOCR would add about 220 MB for no gain. The Windows build uses [windows.spec](image-sorter/windows.spec), which leaves out parts of OpenCV and onnxruntime the app never loads.

store-lookup builds the same way: run `store-lookup\build_windows.bat` on Windows or `sh store-lookup/build_mac.sh` on a Mac. Both bundle the CSVs and `template.cfg` into the app, and put it in `store-lookup/dist/`.

## Notes

- **store-lookup data is not in the repo.** It reads `Chase TH Active Accounts - Canada 2(Data).csv`, `Tim Hortons - Gift Card MIDs(Sheet 1).csv` and `template.cfg` (a working kiosk config that every saved kiosk file is copied from) from its own folder. They are git-ignored on purpose because they hold private merchant data.
- After cloning, run `git submodule update --init` to fetch `js-calendar`.
