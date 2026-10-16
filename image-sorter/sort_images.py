#!/usr/bin/env python3
"""Sort images in a folder into subfolders of 2 consecutive filename numbers.

Example: IMG_0735.jpg + IMG_0736.jpg -> IMG_0735-0736/
         IMG_0737.jpg + IMG_0738.jpg -> IMG_0737-0738/

An image whose neighbour number is missing (e.g. IMG_0306 when there's no
IMG_0307) goes into a folder by itself, IMG_0306/. So does a duplicate: a file
with the same content as another, or a number that's already been sorted
(e.g. "IMG_0735 (1).jpg"); those get a DUPLICATE_ prefix.

Videos are left unsorted in the main folder. Files sharing a name (e.g.
IMG_0735.HEIC and IMG_0735.DNG) count as one image and move together. The
newest unpaired image stays put until its partner arrives (use --all to give
it its own folder anyway).

Usage:
    python3 sort_images.py                   # watch ~/Image Inbox, sort new uploads (Ctrl+C to stop)
    python3 sort_images.py /path/to/folder   # watch a different folder
    python3 sort_images.py --once            # sort once and exit
    python3 sort_images.py --once --dry-run  # just show what would happen
"""
import argparse
import hashlib
import re
import shutil
import time
from collections import defaultdict
from pathlib import Path

DEFAULT_FOLDER = Path.home() / "Image Inbox"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".gif", ".tif", ".tiff",
              ".bmp", ".webp", ".dng", ".cr2", ".nef", ".arw"}
# Videos (.mov, .mp4, ...) aren't in the list, so they stay loose in the folder.
SETTLE_SECS = 5    # wait until files haven't changed for this long (still uploading)
POLL_SECS = 3      # how often watch mode checks the folder

_hash_cache = {}   # (path, size, mtime) -> sha1, so watch mode doesn't rehash


def is_image(f):
    return f.is_file() and f.suffix.lower() in IMAGE_EXTS and not f.name.startswith(".")


def image_number(stem):
    # The first number is the image number: "IMG_0735 2" -> 735, not 2.
    m = re.search(r"\d+", stem)
    return int(m.group()) if m else None


def file_hash(f):
    st = f.stat()
    key = (str(f), st.st_size, st.st_mtime)
    if key not in _hash_cache:
        h = hashlib.sha1()
        with open(f, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        _hash_cache[key] = h.hexdigest()
    return _hash_cache[key]


def pair_name(a, b):
    num = re.findall(r"\d+", b)
    return f"{a}-{num[0] if num else b}"


def sort_folder(folder, dry_run=False, move_odd=False, settle=0, quiet=False, log=print):
    cutoff = time.time() - settle
    by_stem = defaultdict(list)
    for f in folder.iterdir():
        if is_image(f):
            st = f.stat()
            # Finder copies keep the original mtime, so check ctime too.
            if max(st.st_mtime, st.st_ctime) > cutoff:
                return  # something is still uploading; try again next time
            by_stem[f.stem].append(f)

    # What's already been sorted into subfolders, to catch later duplicates.
    sorted_numbers, sorted_hashes = set(), set()
    for sub in folder.iterdir():
        if sub.is_dir() and not sub.name.startswith("."):
            for f in sub.iterdir():
                if is_image(f):
                    sorted_numbers.add(image_number(f.stem))
                    sorted_hashes.add(file_hash(f))

    # Plainest name first, so "IMG_0735" wins over "IMG_0735 (1)".
    stems = sorted(by_stem, key=lambda s: (image_number(s) is None, image_number(s) or 0, len(s), s))
    moves = []  # (folder name, [stems])
    originals = []
    seen_numbers, seen_hashes = set(sorted_numbers), set(sorted_hashes)
    for stem in stems:
        num = image_number(stem)
        hashes = {file_hash(f) for f in by_stem[stem]}
        if num in seen_numbers or hashes & seen_hashes:
            moves.append((f"DUPLICATE_{stem}", [stem]))
        else:
            originals.append(stem)
            if num is not None:
                seen_numbers.add(num)
        seen_hashes |= hashes

    # Pair consecutive numbers; anything without its neighbour goes alone.
    i = 0
    while i < len(originals):
        a = originals[i]
        b = originals[i + 1] if i + 1 < len(originals) else None
        na = image_number(a)
        if b is not None and na is not None and image_number(b) == na + 1:
            moves.append((pair_name(a, b), [a, b]))
            i += 2
        elif b is None and not move_odd:
            if not quiet:
                log(f"Leaving {a} in place until its partner arrives.")
            i += 1
        else:
            moves.append((a, [a]))
            i += 1

    for name, group in moves:
        dest = folder / name
        if not dry_run:
            dest.mkdir(exist_ok=True)
        for stem in group:
            for f in by_stem[stem]:
                target = dest / f.name
                if target.exists():
                    log(f"SKIP {f.name}: already exists in {dest.name}/")
                    continue
                log(f"{f.name} -> {dest.name}/")
                if not dry_run:
                    shutil.move(str(f), str(target))

    if not moves and not quiet:
        log("Nothing to sort.")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("folder", type=Path, nargs="?", default=DEFAULT_FOLDER)
    p.add_argument("--once", action="store_true", help="sort once and exit instead of watching")
    p.add_argument("--dry-run", action="store_true", help="show moves without doing them (implies --once)")
    p.add_argument("--all", action="store_true", help="also give the newest unpaired image its own folder")
    args = p.parse_args()

    folder = args.folder.expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)

    if args.once or args.dry_run:
        sort_folder(folder, args.dry_run, args.all)
        return

    print(f"Watching {folder} — drop images in to sort them. Press Ctrl+C to stop.")
    try:
        while True:
            sort_folder(folder, move_odd=args.all, settle=SETTLE_SECS, quiet=True)
            time.sleep(POLL_SECS)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
