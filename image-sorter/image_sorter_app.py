"""Image Sorter — pick a folder of images and sort it.

Images are sorted into folders of 2 consecutive numbers, each named after the
store label in the photos (see sort_images.py for the rules). Preview shows
what would happen without moving anything.

The window is styled after the "Upload Data" task in Among Us.
"""
import os
import queue
import random
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext

import sounds
from sort_images import sort_folder

# Colours and font for the upload panel
BEZEL = "#8e9297"
PANEL = "#4b7aa6"
STRIPE = "#5784ae"
STRIPE_LIGHT = "#6690b8"
OUTLINE = "#15171a"
FOLDER = "#f7d79c"
FOLDER_DARK = "#e5bf7f"
FOLDER_EDGE = "#c9a45e"
PAPER = "#eef2f6"
PAPER_EDGE = "#b9c3cd"
# Crewmate colours as (body, backpack shade); it changes colour on every jump.
CREW_COLOURS = [
    ("#c51111", "#7a0838"),  # red
    ("#132ed1", "#09158e"),  # blue
    ("#117f2d", "#0a4d2e"),  # green
    ("#ed54ba", "#ab2bad"),  # pink
    ("#ef7d0d", "#b33e15"),  # orange
    ("#f5f557", "#c38823"),  # yellow
    ("#3f474e", "#1e1f26"),  # black
    ("#d6e0f0", "#8394bf"),  # white
    ("#6b2fbb", "#3b177c"),  # purple
    ("#71491e", "#5e2615"),  # brown
    ("#38fedc", "#24a8be"),  # cyan
    ("#50ef39", "#15a742"),  # lime
]
VISOR = "#95cade"
CREW_SCALE = 1.4
BAR_GREEN = "#228b22"
FONT = ("Consolas", 17, "bold")

# Colours for the controls under the panel
BG = "#2b2e33"
FG = "#e6e8eb"
FIELD = "#1e2024"

W, H = 680, 330                      # panel canvas size
BAR = (100, 245, 515, 271)           # progress bar track
CREW_FROM, CREW_TO = (122, 50), (522, 70)   # where the crewmate jumps out and lands


def format_duration(secs):
    secs = round(secs)
    if secs < 60:
        return f"{secs} sec"
    mins, secs = divmod(secs, 60)
    if mins < 60:
        return f"{mins} min {secs:02d} sec"
    hours, mins = divmod(mins, 60)
    return f"{hours} hr {mins:02d} min"


def format_eta(secs):
    """Among Us style: "14m 41s"."""
    mins, secs = divmod(round(secs), 60)
    hours, mins = divmod(mins, 60)
    return f"{hours}h {mins:02d}m" if hours else f"{mins}m {secs:02d}s"


def round_rect(x0, y0, x1, y1, r):
    """Points for a rounded rectangle, drawn as a smoothed polygon."""
    r = min(r, (x1 - x0) / 2, (y1 - y0) / 2)
    return [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
            x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]


class UploadPanel(tk.Canvas):
    """Two folders, a crewmate running between them, a progress bar and a status line."""

    def __init__(self, master):
        super().__init__(master, width=W, height=H, bg=BEZEL, highlightthickness=0)
        self.busy = False
        self.crew_t = 0.0
        self.crew_at = CREW_FROM
        self.crew_colour = CREW_COLOURS[0]
        self.frame = 0

        # Panel with glossy diagonal stripes, inside a dark border
        self.create_polygon(round_rect(14, 14, W - 14, H - 14, 18), smooth=True, fill=PANEL)
        top, bottom, slant = 17, H - 17, 170
        for x, width, colour in [(40, 70, STRIPE), (130, 14, STRIPE_LIGHT), (250, 110, STRIPE),
                                 (395, 18, STRIPE_LIGHT), (440, 60, STRIPE)]:
            self.create_polygon(x, bottom, x + width, bottom, x + width + slant, top, x + slant, top,
                                fill=colour, outline="")
        self.create_polygon(round_rect(14, 14, W - 14, H - 14, 18), smooth=True, fill="",
                            outline=OUTLINE, width=5)

        # Left: a closed folder with papers sticking out
        self.create_polygon(round_rect(70, 64, 112, 92, 6), smooth=True, fill=FOLDER,
                            outline=FOLDER_EDGE, width=3)
        self.create_polygon(98, 86, 126, 50, 152, 86, fill=PAPER, outline=PAPER_EDGE, width=2)
        self.create_polygon(130, 86, 165, 44, 202, 86, fill=PAPER, outline=PAPER_EDGE, width=2)
        self.create_rectangle(70, 82, 235, 192, fill=FOLDER, outline=FOLDER_EDGE, width=3)

        # Right: an open folder; the crewmate lands in between its back and front
        self.create_polygon(round_rect(478, 64, 520, 92, 6), smooth=True, fill=FOLDER,
                            outline=FOLDER_EDGE, width=3)
        self.create_rectangle(478, 82, 612, 192, fill=FOLDER, outline=FOLDER_EDGE, width=3)
        self.crewmate(*CREW_FROM)
        self.itemconfigure("crew", state="hidden")
        self.create_polygon(440, 112, 584, 112, 612, 192, 468, 192, fill=FOLDER_DARK,
                            outline=FOLDER_EDGE, width=3)

        self.from_label = self.text(152, 215, "Photos")
        self.text(545, 215, "Store Folders")

        # Progress bar, percentage and status line
        self.create_polygon(round_rect(*BAR, 10), smooth=True, fill="white", outline=OUTLINE, width=3)
        self.bar_fill = self.create_polygon(round_rect(*BAR, 10), smooth=True, fill=BAR_GREEN,
                                            outline=OUTLINE, width=3, state="hidden")
        self.percent = self.text(545, 258, "0%", anchor="w")
        self.status = self.text(80, 297, "Ready.", anchor="w")

    def crewmate(self, x, y):
        """A crewmate facing right, top-left corner at x, y. Legs come in two poses
        (tags "stepA" and "stepB") that are swapped to make it run; "crew_body" and
        "crew_shade" are the parts recoloured by set_crew_colour()."""
        def part(x0, y0, x1, y1, r, fill, tags=()):
            k = CREW_SCALE
            self.create_polygon(round_rect(x + x0 * k, y + y0 * k, x + x1 * k, y + y1 * k, r * k), smooth=True,
                                fill=fill, outline=OUTLINE, width=3, tags=("crew",) + tags)
        body, shade = self.crew_colour
        part(8, 34, 17, 45, 3, body, ("crew_body", "stepA"))    # back leg down
        part(21, 34, 30, 41, 3, body, ("crew_body", "stepA"))   # front leg up
        part(8, 34, 17, 41, 3, body, ("crew_body", "stepB"))    # back leg up
        part(21, 34, 30, 45, 3, body, ("crew_body", "stepB"))   # front leg down
        part(0, 12, 10, 32, 4, shade, ("crew_shade",))           # backpack
        part(5, 2, 33, 38, 13, body, ("crew_body",))             # body
        part(17, 9, 37, 21, 6, VISOR)                            # visor
        k = CREW_SCALE
        self.create_polygon(round_rect(x + 26 * k, y + 11 * k, x + 33 * k, y + 15 * k, 2 * k), smooth=True,
                            fill="white", outline="", tags="crew")

    def set_crew_colour(self):
        """Switch the crewmate to a random colour, never the same one twice in a row."""
        self.crew_colour = random.choice([c for c in CREW_COLOURS if c != self.crew_colour])
        body, shade = self.crew_colour
        self.itemconfigure("crew_body", fill=body)
        self.itemconfigure("crew_shade", fill=shade)

    def text(self, x, y, value, anchor="center"):
        """White text with a dark drop shadow; returns both items so they change together."""
        shadow = self.create_text(x + 2, y + 2, text=value, fill=OUTLINE, font=FONT, anchor=anchor)
        front = self.create_text(x, y, text=value, fill="white", font=FONT, anchor=anchor)
        return shadow, front

    def set_text(self, items, value):
        for item in items:
            self.itemconfigure(item, text=value)

    def set_source(self, name):
        self.set_text(self.from_label, name if len(name) <= 14 else name[:13] + "…")

    def set_status(self, value):
        self.set_text(self.status, value)

    def set_progress(self, fraction):
        fraction = max(0.0, min(1.0, fraction))
        x0, y0, x1, y1 = BAR
        right = x0 + (x1 - x0) * fraction
        if right - x0 < 6:
            self.itemconfigure(self.bar_fill, state="hidden")
        else:
            self.coords(self.bar_fill, *round_rect(x0, y0, right, y1, 10))
            self.itemconfigure(self.bar_fill, state="normal")
        self.set_text(self.percent, f"{round(fraction * 100)}%")

    def start(self):
        if self.busy:
            return
        self.busy = True
        self.crew_t = 0.0
        self.itemconfigure("crew", state="normal")
        self.run_crewmate()

    def stop(self):
        self.busy = False
        self.itemconfigure("crew", state="hidden")

    def run_crewmate(self):
        """Jump the crewmate along an arc from the left folder into the right one, on repeat,
        swapping its legs every few frames so it looks like it's running."""
        if not self.busy:
            return
        self.crew_t += 0.012
        if self.crew_t >= 1.0:  # landed: start the next jump in a new colour
            self.crew_t -= 1.0
            self.set_crew_colour()
        t = self.crew_t
        (ax, ay), (bx, by) = CREW_FROM, CREW_TO
        x = ax + (bx - ax) * t
        y = ay + (by - ay) * t - 110 * t * (1 - t)
        self.move("crew", x - self.crew_at[0], y - self.crew_at[1])
        self.crew_at = (x, y)

        self.frame += 1
        step = (self.frame // 5) % 2
        self.itemconfigure("stepA", state="normal" if step else "hidden")
        self.itemconfigure("stepB", state="hidden" if step else "normal")
        self.after(20, self.run_crewmate)


class Button(tk.Button):
    def __init__(self, master, text, command, colour="#d9dde2", text_colour="#111111"):
        def click():
            sounds.play("click")
            command()
        super().__init__(master, text=text, command=click, bg=colour, fg=text_colour,
                         activebackground="white", activeforeground="#111111",
                         disabledforeground="#7a7f86", font=("Consolas", 11, "bold"),
                         relief="flat", bd=0, padx=14, pady=5, cursor="hand2",
                         highlightthickness=2, highlightbackground=OUTLINE)


class App:
    def __init__(self, root):
        self.root = root
        self.messages = queue.Queue()

        root.title("Image Sorter")
        root.geometry("720x680")
        root.minsize(720, 560)
        root.configure(bg=BG)

        self.panel = UploadPanel(root)
        self.panel.pack(pady=(16, 8))

        tk.Label(root, text="Choose a folder of images to sort into store folders:",
                 bg=BG, fg=FG, font=("Consolas", 10)).pack(anchor="w", padx=20, pady=(4, 4))

        row = tk.Frame(root, bg=BG)
        row.pack(fill="x", padx=20)
        self.folder = tk.StringVar()
        self.folder.trace_add("write", lambda *_: self.panel.set_source(
            Path(self.folder.get().strip()).name or "Photos"))
        tk.Entry(row, textvariable=self.folder, bg=FIELD, fg=FG, insertbackground=FG,
                 relief="flat", font=("Consolas", 10), highlightthickness=1,
                 highlightbackground="#555a61", highlightcolor="#8fb3d9").pack(
            side="left", fill="x", expand=True, ipady=5)
        Button(row, "Browse…", self.browse).pack(side="left", padx=(8, 0))

        buttons = tk.Frame(root, bg=BG)
        buttons.pack(fill="x", padx=20, pady=10)
        self.preview_btn = Button(buttons, "Preview", lambda: self.run(dry_run=True))
        self.preview_btn.pack(side="left")
        self.sort_btn = Button(buttons, "Sort", lambda: self.run(dry_run=False),
                               colour="#3fa34d", text_colour="white")
        self.sort_btn.pack(side="left", padx=8)
        Button(buttons, "Open folder", self.open_folder).pack(side="right")

        self.log_box = scrolledtext.ScrolledText(root, height=8, state="disabled", wrap="word",
                                                 bg=FIELD, fg="#cfd3d8", font=("Consolas", 10),
                                                 relief="flat", insertbackground=FG)
        self.log_box.pack(fill="both", expand=True, padx=20, pady=(0, 16))

        self.root.after(100, self.drain_messages)
        threading.Thread(target=sounds.prepare, daemon=True).start()

    def log(self, msg):
        self.messages.put(msg)  # safe to call from the worker thread

    def progress(self, done, total):
        self.messages.put(("progress", done, total, time.monotonic()))  # safe from the worker thread

    def show_progress(self, done, total, now):
        if done == 0:
            self.read_start = now  # time it from the first photo, not from the duplicate check
        self.panel.set_progress(done / total if total else 0)
        if total == 0:
            self.panel.set_status("No new photos to read.")
        elif done == 0:
            self.panel.set_status("Estimated Time: --m --s")
        elif done < total:
            # Average time per photo so far, times the photos still to go.
            left = (now - self.read_start) / done * (total - done)
            self.panel.set_status(f"Estimated Time: {format_eta(left)}")
        else:
            self.panel.set_status("Sorting into folders…")

    def drain_messages(self):
        while not self.messages.empty():
            msg = self.messages.get()
            if msg is None:  # worker finished
                self.preview_btn.configure(state="normal")
                self.sort_btn.configure(state="normal")
                self.panel.stop()
                self.panel.set_progress(1.0)
                self.panel.set_status(f"Finished in {format_duration(time.monotonic() - self.run_start)}.")
                sounds.play("complete")
                continue
            if isinstance(msg, tuple):
                self.show_progress(*msg[1:])
                continue
            self.log_box.configure(state="normal")
            self.log_box.insert("end", msg + "\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        self.root.after(100, self.drain_messages)

    def get_folder(self):
        text = self.folder.get().strip()
        folder = Path(text).expanduser() if text else None
        if not folder or not folder.is_dir():
            messagebox.showwarning("Image Sorter", "Please choose a folder first.")
            return None
        return folder.resolve()

    def browse(self):
        chosen = filedialog.askdirectory(initialdir=self.folder.get() or str(Path.home()))
        if chosen:
            self.folder.set(chosen)

    def open_folder(self):
        folder = self.get_folder()
        if not folder:
            return
        if sys.platform == "win32":
            os.startfile(folder)
        else:
            subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", str(folder)])

    def run(self, dry_run):
        folder = self.get_folder()
        if not folder:
            return
        if not dry_run and not messagebox.askyesno(
                "Image Sorter", f"Sort the images in:\n{folder}\n\nFiles will be moved into subfolders."):
            return

        self.preview_btn.configure(state="disabled")
        self.sort_btn.configure(state="disabled")
        self.log(f"\n{'Preview of' if dry_run else 'Sorting'} {folder}")
        self.run_start = time.monotonic()
        self.panel.set_progress(0)
        self.panel.set_status("Checking for new photos…")
        self.panel.start()
        sounds.play("start")

        def work():
            try:
                # One-off sort: a leftover image gets its own folder instead of waiting.
                sort_folder(folder, dry_run=dry_run, move_odd=True, log=self.log, progress=self.progress)
                self.log("Preview done — nothing was moved." if dry_run else "Done!")
            except Exception as e:
                self.log(f"Error: {e}")
            self.messages.put(None)

        threading.Thread(target=work, daemon=True).start()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
