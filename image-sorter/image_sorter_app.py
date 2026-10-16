"""Image Sorter — pick a folder of images and sort it.

Images are sorted into folders of 2 consecutive numbers (see sort_images.py
for the rules). Preview shows what would happen without moving anything.
"""
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from sort_images import sort_folder


class App:
    def __init__(self, root):
        self.root = root
        self.messages = queue.Queue()

        root.title("Image Sorter")
        root.geometry("640x440")
        root.minsize(480, 300)

        ttk.Label(root, text="Choose a folder of images to sort into pairs:",
                  padding=(10, 10, 10, 4)).pack(anchor="w")

        row = ttk.Frame(root, padding=(10, 0))
        row.pack(fill="x")
        self.folder = tk.StringVar()
        ttk.Entry(row, textvariable=self.folder).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse…", command=self.browse).pack(side="left", padx=(6, 0))

        buttons = ttk.Frame(root, padding=10)
        buttons.pack(fill="x")
        self.preview_btn = ttk.Button(buttons, text="Preview", command=lambda: self.run(dry_run=True))
        self.preview_btn.pack(side="left")
        self.sort_btn = ttk.Button(buttons, text="Sort", command=lambda: self.run(dry_run=False))
        self.sort_btn.pack(side="left", padx=6)
        ttk.Button(buttons, text="Open folder", command=self.open_folder).pack(side="right")

        self.log_box = scrolledtext.ScrolledText(root, height=15, state="disabled", wrap="word")
        self.log_box.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.root.after(100, self.drain_messages)

    def log(self, msg):
        self.messages.put(msg)  # safe to call from the worker thread

    def drain_messages(self):
        while not self.messages.empty():
            msg = self.messages.get()
            if msg is None:  # worker finished
                self.preview_btn.configure(state="normal")
                self.sort_btn.configure(state="normal")
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

        def work():
            try:
                # One-off sort: a leftover image gets its own folder instead of waiting.
                sort_folder(folder, dry_run=dry_run, move_odd=True, log=self.log)
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
