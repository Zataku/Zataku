# Side Projects

| Project | Stack | What it is |
| --- | --- | --- |
| [image-sorter](image-sorter/) | Python, Tkinter | Pick a folder of images and sort them into numbered folders. Preview mode shows the result without moving anything. |
| [js-calendar](js-calendar/) | HTML, CSS, JS | Calendar widget (git submodule → [Zataku/js-calendar](https://github.com/Zataku/js-calendar)). |
| react-portfolio-website | React (CRA) | Personal portfolio site (not published yet). |
| [space-invaders](space-invaders/) | Python, pygame | Space Invaders clone. |
| [store-lookup](store-lookup/) | Python, Tkinter | Look up a Tim Hortons store's merchant IDs, address and phone from its 6-digit gift card code. |

## Running

```sh
# Python projects
python image-sorter/image_sorter_app.py
python space-invaders/main.py          # needs: pip install pygame
python store-lookup/store_lookup.py    # needs the two data CSVs (see below)

# React portfolio
cd react-portfolio-website && npm install && npm start
```

Windows builds: run `build_windows.bat` in `image-sorter/` or `store-lookup/` (uses PyInstaller, output goes to `dist/`).

## Notes

- **store-lookup data is not in the repo.** It reads `Chase TH Active Accounts - Canada 2(Data).csv` and `Tim Hortons - Gift Card MIDs(Sheet 1).csv` from its own folder. They are git-ignored on purpose because they hold private merchant data.
- After cloning, run `git submodule update --init` to fetch `js-calendar`.
