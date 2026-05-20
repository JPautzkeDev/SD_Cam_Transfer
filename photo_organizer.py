"""
Photo Organizer — Copy photos from SD card / camera into YYYYMMDD date folders.

Requirements (install all for best results):
    pip install pillow rawpy

    pillow  — improved EXIF reading for JPEG/TIFF
    rawpy   — capture-date reading for RAF (Fujifilm RAW) and other RAW formats

Python 3.8+ with tkinter (ships with the standard Windows Python installer).
Run with:  pythonw photo_organizer.py   (no console window)
       or: python  photo_organizer.py   (console visible)
"""

import os
import shutil
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from datetime import datetime
from pathlib import Path
import struct

# ── Optional EXIF support via Pillow ──────────────────────────────────────────
try:
    from PIL import Image
    from PIL.ExifTags import TAGS
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False

# ── Optional RAW support via rawpy (handles RAF, CR2, NEF, ARW, etc.) ─────────
try:
    import rawpy
    RAWPY_AVAILABLE = True
except ImportError:
    RAWPY_AVAILABLE = False

# ── EXIF date helpers ──────────────────────────────────────────────────────────

def _exif_date_pillow(path: Path) -> datetime | None:
    """Try to read DateTimeOriginal / DateTime from EXIF via Pillow."""
    try:
        with Image.open(path) as img:
            exif_data = img._getexif()
            if not exif_data:
                return None
            tag_map = {v: k for k, v in TAGS.items()}
            for tag_name in ("DateTimeOriginal", "DateTimeDigitized", "DateTime"):
                tag_id = tag_map.get(tag_name)
                if tag_id and tag_id in exif_data:
                    raw = exif_data[tag_id]
                    return datetime.strptime(raw, "%Y:%m:%d %H:%M:%S")
    except Exception:
        pass
    return None


def _exif_date_raw(path: Path) -> datetime | None:
    """
    Minimal JPEG EXIF parser — no dependencies.
    Looks for DateTimeOriginal (tag 0x9003) or DateTime (tag 0x0132).
    """
    JPEG_EXIF_TAGS = {0x9003, 0x0132, 0x9004}
    try:
        with open(path, "rb") as f:
            if f.read(2) != b"\xff\xd8":
                return None          # not a JPEG
            while True:
                marker = f.read(2)
                if len(marker) < 2:
                    break
                if marker == b"\xff\xe1":  # APP1
                    seg_len = struct.unpack(">H", f.read(2))[0] - 2
                    seg = f.read(seg_len)
                    if seg[:6] != b"Exif\x00\x00":
                        continue
                    tiff = seg[6:]
                    byte_order = tiff[:2]
                    bo = "<" if byte_order == b"II" else ">"
                    ifd_offset = struct.unpack(bo + "I", tiff[4:8])[0]
                    num_entries = struct.unpack(bo + "H", tiff[ifd_offset:ifd_offset + 2])[0]
                    pos = ifd_offset + 2
                    for _ in range(num_entries):
                        entry = tiff[pos:pos + 12]
                        if len(entry) < 12:
                            break
                        tag = struct.unpack(bo + "H", entry[:2])[0]
                        if tag in JPEG_EXIF_TAGS:
                            offset = struct.unpack(bo + "I", entry[8:12])[0]
                            raw = tiff[offset:offset + 19].decode("ascii", errors="ignore")
                            try:
                                return datetime.strptime(raw, "%Y:%m:%d %H:%M:%S")
                            except ValueError:
                                pass
                        pos += 12
                    # also check SubIFD (Exif IFD pointer, tag 0x8769)
                    break
                elif marker[0:1] == b"\xff" and marker[1:2] not in (b"\x00", b"\xd9"):
                    length = struct.unpack(">H", f.read(2))[0] - 2
                    f.seek(length, 1)
                else:
                    break
    except Exception:
        pass
    return None


def _exif_date_rawpy(path: Path) -> datetime | None:
    """
    Extract capture date from any RAW file supported by rawpy / LibRaw.
    Covers: RAF (Fujifilm), CR2/CR3 (Canon), NEF (Nikon), ARW (Sony), etc.
    rawpy exposes the EXIF timestamp directly as a Unix epoch value.
    """
    if not RAWPY_AVAILABLE:
        return None
    try:
        with rawpy.imread(str(path)) as raw:
            ts = raw.metadata.timestamp   # seconds since epoch, or 0 if missing
            if ts:
                return datetime.fromtimestamp(ts)
    except Exception:
        pass
    return None


# RAW file extensions that rawpy / LibRaw can handle
RAW_EXTENSIONS = {
    ".raf",  # Fujifilm
    ".cr2", ".cr3",  # Canon
    ".nef", ".nrw",  # Nikon
    ".arw", ".srf", ".sr2",  # Sony
    ".dng",  # Adobe / various
    ".orf",  # Olympus
    ".rw2",  # Panasonic
    ".pef",  # Pentax
    ".srw",  # Samsung
    ".x3f",  # Sigma
    ".3fr",  # Hasselblad
    ".mef",  # Mamiya
    ".mrw",  # Minolta
}

JPEG_EXTENSIONS = {".jpg", ".jpeg", ".tiff", ".tif"}


def get_photo_date(path: Path) -> datetime:
    """
    Return the best available capture date for a photo file.

    Priority order:
      1. rawpy  — for RAW files (RAF, CR2, NEF, ARW, DNG, …)
      2. Pillow — for JPEG / TIFF (reads EXIF DateTimeOriginal)
      3. Built-in minimal JPEG EXIF parser (no deps)
      4. File system modification time (fallback)
    """
    dt = None
    ext = path.suffix.lower()

    if ext in RAW_EXTENSIONS:
        dt = _exif_date_rawpy(path)

    elif ext in JPEG_EXTENSIONS:
        if PILLOW_AVAILABLE:
            dt = _exif_date_pillow(path)
        if dt is None:
            dt = _exif_date_raw(path)

    # For any other extension (MP4, PNG, HEIC, …) fall straight through to mtime
    if dt is None:
        dt = datetime.fromtimestamp(path.stat().st_mtime)
    return dt


# ── GUI ────────────────────────────────────────────────────────────────────────

DARK_BG   = "#1a1a2e"
PANEL_BG  = "#16213e"
ACCENT    = "#e94560"
ACCENT2   = "#0f3460"
TEXT      = "#eaeaea"
SUBTEXT   = "#8892a4"
SUCCESS   = "#2ecc71"
WARNING   = "#f39c12"
ENTRY_BG  = "#0d1b2a"


class PhotoOrganizerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Photo Organizer")
        self.geometry("720x620")
        self.resizable(True, True)
        self.configure(bg=DARK_BG)
        self.minsize(620, 520)

        self._src = tk.StringVar()
        self._dst = tk.StringVar()
        self._copy_mode = tk.BooleanVar(value=True)   # True = copy, False = move
        self._overwrite = tk.BooleanVar(value=False)
        self._running = False
        self._cancel = False

        self._build_ui()

    # ── UI Construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        # Header
        header = tk.Frame(self, bg=ACCENT, height=6)
        header.pack(fill="x")

        title_frame = tk.Frame(self, bg=DARK_BG, pady=18)
        title_frame.pack(fill="x", padx=30)
        tk.Label(title_frame, text="📷  Photo Organizer",
                 font=("Segoe UI", 20, "bold"), bg=DARK_BG, fg=TEXT).pack(side="left")
        tk.Label(title_frame,
                 text="Copy / move photos into YYYYMMDD folders by capture date",
                 font=("Segoe UI", 9), bg=DARK_BG, fg=SUBTEXT).pack(side="left", padx=14)

        # Main card
        card = tk.Frame(self, bg=PANEL_BG, padx=24, pady=20,
                        highlightbackground=ACCENT2, highlightthickness=1)
        card.pack(fill="both", expand=False, padx=20, pady=(0, 10))

        self._dir_row("Source Directory  (SD card / camera)", self._src,
                      self._browse_src, card)
        self._dir_row("Destination Directory  (on your PC)", self._dst,
                      self._browse_dst, card)

        # Options row
        opts = tk.Frame(card, bg=PANEL_BG)
        opts.pack(fill="x", pady=(10, 2))

        self._checkbox(opts, "Copy files  (keep originals)", self._copy_mode)
        self._checkbox(opts, "Move files  (delete originals after copy)",
                       self._copy_mode, invert=True)
        self._checkbox(opts, "Overwrite existing files", self._overwrite)

        # Buttons
        btn_row = tk.Frame(self, bg=DARK_BG)
        btn_row.pack(fill="x", padx=20, pady=8)

        self._start_btn = tk.Button(
            btn_row, text="▶  Start", font=("Segoe UI", 11, "bold"),
            bg=ACCENT, fg="white", relief="flat", padx=20, pady=8,
            cursor="hand2", activebackground="#c73652", activeforeground="white",
            command=self._start)
        self._start_btn.pack(side="left", padx=(0, 10))

        self._cancel_btn = tk.Button(
            btn_row, text="■  Cancel", font=("Segoe UI", 11),
            bg=ACCENT2, fg=TEXT, relief="flat", padx=20, pady=8,
            cursor="hand2", state="disabled",
            command=self._request_cancel)
        self._cancel_btn.pack(side="left")

        self._status_lbl = tk.Label(btn_row, text="", font=("Segoe UI", 9),
                                    bg=DARK_BG, fg=SUBTEXT)
        self._status_lbl.pack(side="right", padx=10)

        # Progress bar
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Org.Horizontal.TProgressbar",
                        troughcolor=PANEL_BG, background=ACCENT,
                        bordercolor=PANEL_BG, lightcolor=ACCENT, darkcolor=ACCENT)
        self._progress = ttk.Progressbar(self, style="Org.Horizontal.TProgressbar",
                                         length=400, mode="determinate")
        self._progress.pack(fill="x", padx=20, pady=(0, 6))

        # Log area
        log_frame = tk.Frame(self, bg=PANEL_BG, highlightbackground=ACCENT2,
                             highlightthickness=1)
        log_frame.pack(fill="both", expand=True, padx=20, pady=(0, 16))

        log_header = tk.Frame(log_frame, bg=ACCENT2, padx=10, pady=4)
        log_header.pack(fill="x")
        tk.Label(log_header, text="Log", font=("Segoe UI", 8, "bold"),
                 bg=ACCENT2, fg=TEXT).pack(side="left")

        self._log = tk.Text(log_frame, bg=ENTRY_BG, fg=TEXT,
                            font=("Consolas", 9), relief="flat",
                            state="disabled", wrap="word",
                            padx=8, pady=6)
        scrollbar = tk.Scrollbar(log_frame, command=self._log.yview,
                                 bg=PANEL_BG, troughcolor=PANEL_BG)
        self._log.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self._log.pack(fill="both", expand=True)

        # Tag colors for log
        self._log.tag_configure("ok",      foreground=SUCCESS)
        self._log.tag_configure("warn",    foreground=WARNING)
        self._log.tag_configure("err",     foreground=ACCENT)
        self._log.tag_configure("info",    foreground=SUBTEXT)
        self._log.tag_configure("section", foreground=ACCENT2, font=("Consolas", 9, "bold"))

        # Show library status on startup
        self._show_lib_status()

    def _show_lib_status(self):
        """Log which optional libraries are available."""
        rawpy_status = ("✔  rawpy   — RAF / RAW date extraction active", "ok") \
            if RAWPY_AVAILABLE else \
            ("⚠  rawpy   not installed — RAF files will use file-modified date  "
             "(run: pip install rawpy)", "warn")
        pillow_status = ("✔  Pillow  — enhanced JPEG/TIFF date extraction active", "ok") \
            if PILLOW_AVAILABLE else \
            ("⚠  Pillow  not installed — using built-in JPEG parser  "
             "(run: pip install pillow)", "warn")
        self._log_line("Library status:", "section")
        self._log_line(f"  {rawpy_status[0]}", rawpy_status[1])
        self._log_line(f"  {pillow_status[0]}", pillow_status[1])
        self._log_line("", "info")

    def _dir_row(self, label, var, cmd, parent):
        row = tk.Frame(parent, bg=PANEL_BG, pady=6)
        row.pack(fill="x")
        tk.Label(row, text=label, font=("Segoe UI", 9, "bold"),
                 bg=PANEL_BG, fg=SUBTEXT, width=38, anchor="w").pack(side="left")
        tk.Entry(row, textvariable=var, bg=ENTRY_BG, fg=TEXT,
                 insertbackground=TEXT, relief="flat", font=("Segoe UI", 10),
                 highlightbackground=ACCENT2, highlightthickness=1).pack(
                     side="left", fill="x", expand=True, padx=(6, 6))
        tk.Button(row, text="Browse…", font=("Segoe UI", 9),
                  bg=ACCENT2, fg=TEXT, relief="flat", padx=10,
                  cursor="hand2", command=cmd).pack(side="left")

    def _checkbox(self, parent, text, var, invert=False):
        """Render a styled checkbox. invert=True flips the variable logic (radio-like pair)."""
        def toggle():
            if invert:
                var.set(not var.get())
        frame = tk.Frame(parent, bg=PANEL_BG, padx=0, pady=2)
        frame.pack(side="left", padx=(0, 20))
        cb = tk.Checkbutton(
            frame, text=text, font=("Segoe UI", 9),
            bg=PANEL_BG, fg=TEXT, selectcolor=ENTRY_BG,
            activebackground=PANEL_BG, activeforeground=TEXT,
            relief="flat", cursor="hand2",
            variable=var, onvalue=(not invert), offvalue=invert,
            command=toggle if invert else None)
        cb.pack()

    # ── Browse ─────────────────────────────────────────────────────────────────

    def _browse_src(self):
        d = filedialog.askdirectory(title="Select Source Directory")
        if d:
            self._src.set(d)

    def _browse_dst(self):
        d = filedialog.askdirectory(title="Select Destination Directory")
        if d:
            self._dst.set(d)

    # ── Logging ────────────────────────────────────────────────────────────────

    def _log_line(self, msg, tag="info"):
        self._log.configure(state="normal")
        self._log.insert("end", msg + "\n", tag)
        self._log.see("end")
        self._log.configure(state="disabled")

    def _clear_log(self):
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

    # ── Worker ─────────────────────────────────────────────────────────────────

    def _start(self):
        src = self._src.get().strip()
        dst = self._dst.get().strip()
        if not src or not dst:
            messagebox.showwarning("Missing Input", "Please choose both source and destination directories.")
            return
        if not os.path.isdir(src):
            messagebox.showerror("Invalid Source", f"Source directory not found:\n{src}")
            return
        os.makedirs(dst, exist_ok=True)

        self._cancel = False
        self._running = True
        self._start_btn.configure(state="disabled")
        self._cancel_btn.configure(state="normal")
        self._clear_log()
        self._progress["value"] = 0

        thread = threading.Thread(target=self._worker, args=(src, dst), daemon=True)
        thread.start()

    def _request_cancel(self):
        self._cancel = True
        self._status_lbl.configure(text="Cancelling…", fg=WARNING)

    def _worker(self, src: str, dst: str):
        do_copy = self._copy_mode.get()
        overwrite = self._overwrite.get()
        action = "Copying" if do_copy else "Moving"

        # Collect all files recursively
        all_files = [p for p in Path(src).rglob("*") if p.is_file()]
        total = len(all_files)

        self._log_line(f"{'─'*60}", "section")
        self._log_line(f"  {action} {total} file(s)", "section")
        self._log_line(f"  Source : {src}", "section")
        self._log_line(f"  Dest   : {dst}", "section")
        self._log_line(f"{'─'*60}", "section")

        if total == 0:
            self._log_line("No files found in source directory.", "warn")
            self._finish(0, 0, 0)
            return

        copied = skipped = errors = 0

        for idx, filepath in enumerate(all_files, 1):
            if self._cancel:
                self._log_line("⚠  Cancelled by user.", "warn")
                break

            # Progress
            pct = int(idx / total * 100)
            self.after(0, lambda v=pct: self._progress.configure(value=v))
            self.after(0, lambda i=idx, t=total: self._status_lbl.configure(
                text=f"{i}/{t} files", fg=SUBTEXT))

            try:
                dt = get_photo_date(filepath)
                date_folder = dt.strftime("%Y%m%d")
                dest_dir = Path(dst) / date_folder
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest_file = dest_dir / filepath.name

                # Handle name collisions
                if dest_file.exists() and not overwrite:
                    stem = filepath.stem
                    suffix = filepath.suffix
                    counter = 1
                    while dest_file.exists():
                        dest_file = dest_dir / f"{stem}_{counter}{suffix}"
                        counter += 1

                if do_copy:
                    shutil.copy2(str(filepath), str(dest_file))
                else:
                    shutil.move(str(filepath), str(dest_file))

                self._log_line(
                    f"  ✔  [{date_folder}]  {filepath.name}  →  {dest_file.name}", "ok")
                copied += 1

            except Exception as exc:
                self._log_line(f"  ✘  {filepath.name}  —  {exc}", "err")
                errors += 1

        self._finish(copied, skipped, errors)

    def _finish(self, copied, skipped, errors):
        self.after(0, self._progress.configure, {"value": 100})
        self.after(0, self._log_line, f"{'─'*60}", "section")
        self.after(0, self._log_line,
                   f"  Done — {copied} copied,  {skipped} skipped,  {errors} error(s)", "section")
        self.after(0, self._log_line, f"{'─'*60}", "section")
        self.after(0, self._status_lbl.configure,
                   {"text": f"Done — {copied} copied, {errors} errors",
                    "fg": SUCCESS if errors == 0 else WARNING})
        self.after(0, self._start_btn.configure,  {"state": "normal"})
        self.after(0, self._cancel_btn.configure, {"state": "disabled"})
        self._running = False


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = PhotoOrganizerApp()
    app.mainloop()
