"""
Photo Organizer — Copy photos from SD card / USB camera into YYYYMMDD date folders.

Requirements (install all for best results):
    pip install pillow rawpy pywin32

    pillow  — improved EXIF reading for JPEG/TIFF
    rawpy   — capture-date reading for RAF (Fujifilm RAW) and other RAW formats
    pywin32 — MTP/USB camera browsing via Windows Shell (same engine as File Explorer)

Python 3.8+ with tkinter (ships with the standard Windows Python installer).
Run with:  pythonw photo_organizer.py   (no console window)
       or: python  photo_organizer.py   (console visible, useful for debugging)
"""

import os
import shutil
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from datetime import datetime
from pathlib import Path
import struct
import tempfile
import time

# ── Optional: Pillow (JPEG/TIFF EXIF) ────────────────────────────────────────
try:
    from PIL import Image
    from PIL.ExifTags import TAGS
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False

# ── Optional: rawpy (RAF and other RAW formats) ───────────────────────────────
try:
    import rawpy
    RAWPY_AVAILABLE = True
except ImportError:
    RAWPY_AVAILABLE = False

# ── Optional: pywin32 (MTP / USB camera via Windows Shell) ───────────────────
try:
    import win32com.client
    import pythoncom
    PYWIN32_AVAILABLE = True
except ImportError:
    PYWIN32_AVAILABLE = False


# ═══════════════════════════════════════════════════════════════════════════════
# EXIF / date extraction
# ═══════════════════════════════════════════════════════════════════════════════

def _exif_date_pillow(path: Path) -> datetime | None:
    """Read DateTimeOriginal from JPEG/TIFF via Pillow."""
    try:
        with Image.open(path) as img:
            exif_data = img._getexif()
            if not exif_data:
                return None
            tag_map = {v: k for k, v in TAGS.items()}
            for tag_name in ("DateTimeOriginal", "DateTimeDigitized", "DateTime"):
                tag_id = tag_map.get(tag_name)
                if tag_id and tag_id in exif_data:
                    return datetime.strptime(exif_data[tag_id], "%Y:%m:%d %H:%M:%S")
    except Exception:
        pass
    return None


def _exif_date_raw(path: Path) -> datetime | None:
    """Minimal no-dependency JPEG EXIF parser."""
    JPEG_EXIF_TAGS = {0x9003, 0x0132, 0x9004}
    try:
        with open(path, "rb") as f:
            if f.read(2) != b"\xff\xd8":
                return None
            while True:
                marker = f.read(2)
                if len(marker) < 2:
                    break
                if marker == b"\xff\xe1":
                    seg_len = struct.unpack(">H", f.read(2))[0] - 2
                    seg = f.read(seg_len)
                    if seg[:6] != b"Exif\x00\x00":
                        continue
                    tiff = seg[6:]
                    bo = "<" if tiff[:2] == b"II" else ">"
                    ifd_offset = struct.unpack(bo + "I", tiff[4:8])[0]
                    num_entries = struct.unpack(bo + "H",
                                               tiff[ifd_offset:ifd_offset + 2])[0]
                    pos = ifd_offset + 2
                    for _ in range(num_entries):
                        entry = tiff[pos:pos + 12]
                        if len(entry) < 12:
                            break
                        tag = struct.unpack(bo + "H", entry[:2])[0]
                        if tag in JPEG_EXIF_TAGS:
                            offset = struct.unpack(bo + "I", entry[8:12])[0]
                            raw_str = tiff[offset:offset + 19].decode(
                                "ascii", errors="ignore")
                            try:
                                return datetime.strptime(raw_str, "%Y:%m:%d %H:%M:%S")
                            except ValueError:
                                pass
                        pos += 12
                    break
                elif marker[0:1] == b"\xff" and marker[1:2] not in (b"\x00", b"\xd9"):
                    f.seek(struct.unpack(">H", f.read(2))[0] - 2, 1)
                else:
                    break
    except Exception:
        pass
    return None


def _exif_date_rawpy(path: Path) -> datetime | None:
    """Extract capture date from RAW files via rawpy / LibRaw."""
    if not RAWPY_AVAILABLE:
        return None
    try:
        with rawpy.imread(str(path)) as raw:
            ts = raw.metadata.timestamp
            if ts:
                return datetime.fromtimestamp(ts)
    except Exception:
        pass
    return None


RAW_EXTENSIONS  = {".raf", ".cr2", ".cr3", ".nef", ".nrw", ".arw", ".srf",
                   ".sr2", ".dng", ".orf", ".rw2", ".pef", ".srw", ".x3f",
                   ".3fr", ".mef", ".mrw"}
JPEG_EXTENSIONS = {".jpg", ".jpeg", ".tiff", ".tif"}


def get_photo_date(path: Path) -> datetime:
    """
    Return the best available capture date for a photo file.
    Priority: rawpy (RAW) -> Pillow (JPEG) -> built-in JPEG parser -> file mtime.
    """
    dt  = None
    ext = path.suffix.lower()
    if ext in RAW_EXTENSIONS:
        dt = _exif_date_rawpy(path)
    elif ext in JPEG_EXTENSIONS:
        if PILLOW_AVAILABLE:
            dt = _exif_date_pillow(path)
        if dt is None:
            dt = _exif_date_raw(path)
    return dt or datetime.fromtimestamp(path.stat().st_mtime)


# ═══════════════════════════════════════════════════════════════════════════════
# MTP helpers  (pywin32 / Windows Shell)
# ═══════════════════════════════════════════════════════════════════════════════

def _shell_browse_for_mtp_folder(parent_hwnd: int) -> str | None:
    """
    Open the Windows Shell folder-picker (SHBrowseForFolder).
    Unlike tkinter's askdirectory this dialog can see MTP/WPD devices
    because it uses the same namespace as File Explorer.

    Returns the selected path string or None if cancelled.
    """
    pythoncom.CoInitialize()
    try:
        shell  = win32com.client.Dispatch("Shell.Application")
        # BIF_USENEWUI (0x50) = modern resizable dialog with edit box,
        # without BIF_RETURNONLYFSDIRS so virtual MTP folders are selectable.
        folder = shell.BrowseForFolder(
            parent_hwnd,
            "Select the folder on your camera or SD card to import from",
            0x50)
        if folder is None:
            return None
        item = folder.Self
        path = item.Path
        return path if path else item.Name
    except Exception:
        return None
    finally:
        pythoncom.CoUninitialize()


def _enumerate_mtp_files(mtp_path: str, log_cb) -> list:
    """
    Walk an MTP device path via Windows Shell and return a list of
    Shell item objects representing files (not folders).
    """
    pythoncom.CoInitialize()
    results = []
    try:
        shell  = win32com.client.Dispatch("Shell.Application")
        folder = shell.Namespace(mtp_path)
        if folder is None:
            log_cb(f"  Could not open MTP path: {mtp_path}", "err")
            return results
        _recurse_mtp(folder, results, log_cb)
    except Exception as e:
        log_cb(f"  MTP enumeration error: {e}", "err")
    finally:
        pythoncom.CoUninitialize()
    return results


def _recurse_mtp(folder, results: list, log_cb):
    """Recursively collect file shell-items from a Shell folder object."""
    try:
        items = folder.Items()
        for i in range(items.Count):
            item = items.Item(i)
            if item.IsFolder:
                sub = folder.ParseName(item.Name)
                if sub:
                    _recurse_mtp(sub.GetFolder, results, log_cb)
            else:
                results.append(item)
    except Exception as e:
        log_cb(f"  MTP walk error: {e}", "warn")


def copy_mtp_file_to_temp(shell_item) -> Path | None:
    """
    Copy a single MTP shell item to a system temp file so rawpy / Pillow
    can open it (they need a real filesystem path).
    Returns the temp Path on success, or None on failure.
    Caller is responsible for deleting the temp file afterwards.
    """
    pythoncom.CoInitialize()
    try:
        name   = shell_item.Name
        suffix = Path(name).suffix
        tmp    = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.close()
        tmp_path = Path(tmp.name)

        shell       = win32com.client.Dispatch("Shell.Application")
        dest_folder = shell.Namespace(str(tmp_path.parent))
        # 0x14 = FOF_SILENT | FOF_NOCONFIRMATION — no UI, no prompts
        dest_folder.CopyHere(shell_item, 0x14)

        # CopyHere is asynchronous — poll until the file has content
        expected = tmp_path.parent / name
        for _ in range(100):          # up to ~10 seconds
            time.sleep(0.1)
            target = expected if expected.exists() else tmp_path
            if target.exists() and target.stat().st_size > 0:
                if target != tmp_path:
                    target.replace(tmp_path)
                return tmp_path

        return None
    except Exception:
        return None
    finally:
        pythoncom.CoUninitialize()


# ═══════════════════════════════════════════════════════════════════════════════
# GUI
# ═══════════════════════════════════════════════════════════════════════════════

DARK_BG  = "#1a1a2e"
PANEL_BG = "#16213e"
ACCENT   = "#e94560"
ACCENT2  = "#0f3460"
TEXT     = "#eaeaea"
SUBTEXT  = "#8892a4"
SUCCESS  = "#2ecc71"
WARNING  = "#f39c12"
ENTRY_BG = "#0d1b2a"
MTP_CLR  = "#9b59b6"   # purple — MTP / camera mode indicator


class PhotoOrganizerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Photo Organizer")
        self.geometry("780x670")
        self.resizable(True, True)
        self.configure(bg=DARK_BG)
        self.minsize(660, 560)

        self._src       = tk.StringVar()
        self._dst       = tk.StringVar()
        self._copy_mode = tk.BooleanVar(value=True)   # True=copy, False=move
        self._overwrite = tk.BooleanVar(value=False)
        self._mtp_mode  = False     # True when source is an MTP device
        self._mtp_path  = None      # raw MTP path string from Shell
        self._running   = False
        self._cancel    = False

        self._build_ui()

    # ── UI construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        tk.Frame(self, bg=ACCENT, height=6).pack(fill="x")

        hdr = tk.Frame(self, bg=DARK_BG, pady=16)
        hdr.pack(fill="x", padx=30)
        tk.Label(hdr, text="📷  Photo Organizer",
                 font=("Segoe UI", 20, "bold"), bg=DARK_BG, fg=TEXT).pack(side="left")
        tk.Label(hdr, text="Copy / move photos into YYYYMMDD folders by capture date",
                 font=("Segoe UI", 9), bg=DARK_BG, fg=SUBTEXT).pack(side="left", padx=14)

        card = tk.Frame(self, bg=PANEL_BG, padx=24, pady=18,
                        highlightbackground=ACCENT2, highlightthickness=1)
        card.pack(fill="both", expand=False, padx=20, pady=(0, 10))

        self._build_source_row(card)
        self._dir_row("Destination Directory  (on your PC)",
                      self._dst, self._browse_dst, card)

        opts = tk.Frame(card, bg=PANEL_BG)
        opts.pack(fill="x", pady=(10, 2))
        self._checkbox(opts, "Copy files  (keep originals)", self._copy_mode)
        self._checkbox(opts, "Move files  (delete originals after copy)",
                       self._copy_mode, invert=True)
        self._checkbox(opts, "Overwrite existing files", self._overwrite)

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
            cursor="hand2", state="disabled", command=self._request_cancel)
        self._cancel_btn.pack(side="left")

        self._status_lbl = tk.Label(btn_row, text="", font=("Segoe UI", 9),
                                    bg=DARK_BG, fg=SUBTEXT)
        self._status_lbl.pack(side="right", padx=10)

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Org.Horizontal.TProgressbar",
                        troughcolor=PANEL_BG, background=ACCENT,
                        bordercolor=PANEL_BG, lightcolor=ACCENT, darkcolor=ACCENT)
        self._progress = ttk.Progressbar(self, style="Org.Horizontal.TProgressbar",
                                         mode="determinate")
        self._progress.pack(fill="x", padx=20, pady=(0, 6))

        log_frame = tk.Frame(self, bg=PANEL_BG,
                             highlightbackground=ACCENT2, highlightthickness=1)
        log_frame.pack(fill="both", expand=True, padx=20, pady=(0, 16))

        log_hdr = tk.Frame(log_frame, bg=ACCENT2, padx=10, pady=4)
        log_hdr.pack(fill="x")
        tk.Label(log_hdr, text="Log", font=("Segoe UI", 8, "bold"),
                 bg=ACCENT2, fg=TEXT).pack(side="left")

        self._log = tk.Text(log_frame, bg=ENTRY_BG, fg=TEXT,
                            font=("Consolas", 9), relief="flat",
                            state="disabled", wrap="word", padx=8, pady=6)
        sb = tk.Scrollbar(log_frame, command=self._log.yview,
                          bg=PANEL_BG, troughcolor=PANEL_BG)
        self._log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._log.pack(fill="both", expand=True)

        self._log.tag_configure("ok",      foreground=SUCCESS)
        self._log.tag_configure("warn",    foreground=WARNING)
        self._log.tag_configure("err",     foreground=ACCENT)
        self._log.tag_configure("info",    foreground=SUBTEXT)
        self._log.tag_configure("mtp",     foreground=MTP_CLR)
        self._log.tag_configure("section", foreground=ACCENT2,
                                font=("Consolas", 9, "bold"))

        self._show_lib_status()

    def _build_source_row(self, parent):
        """Source row with two browse buttons: normal folder and MTP camera."""
        row = tk.Frame(parent, bg=PANEL_BG, pady=6)
        row.pack(fill="x")

        tk.Label(row, text="Source Directory  (SD card / camera)",
                 font=("Segoe UI", 9, "bold"),
                 bg=PANEL_BG, fg=SUBTEXT, width=38, anchor="w").pack(side="left")

        self._src_entry = tk.Entry(
            row, textvariable=self._src, bg=ENTRY_BG, fg=TEXT,
            insertbackground=TEXT, relief="flat", font=("Segoe UI", 10),
            highlightbackground=ACCENT2, highlightthickness=1)
        self._src_entry.pack(side="left", fill="x", expand=True, padx=(6, 6))

        tk.Button(row, text="Browse…", font=("Segoe UI", 9),
                  bg=ACCENT2, fg=TEXT, relief="flat", padx=10,
                  cursor="hand2", command=self._browse_src).pack(side="left", padx=(0, 4))

        mtp_ok    = PYWIN32_AVAILABLE
        mtp_tip   = ("Browse USB camera via Windows Shell (MTP)" if mtp_ok
                     else "Install pywin32 to enable USB camera browsing:\n"
                          "  pip install pywin32")
        self._mtp_btn = tk.Button(
            row, text="📷 Camera (USB)…", font=("Segoe UI", 9),
            bg=MTP_CLR if mtp_ok else ACCENT2, fg="white",
            relief="flat", padx=10,
            cursor="hand2" if mtp_ok else "arrow",
            state="normal" if mtp_ok else "disabled",
            command=self._browse_mtp)
        self._mtp_btn.pack(side="left")
        self._add_tooltip(self._mtp_btn, mtp_tip)

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
        def toggle():
            if invert:
                var.set(not var.get())
        f = tk.Frame(parent, bg=PANEL_BG, pady=2)
        f.pack(side="left", padx=(0, 20))
        tk.Checkbutton(f, text=text, font=("Segoe UI", 9),
                       bg=PANEL_BG, fg=TEXT, selectcolor=ENTRY_BG,
                       activebackground=PANEL_BG, activeforeground=TEXT,
                       relief="flat", cursor="hand2",
                       variable=var, onvalue=(not invert), offvalue=invert,
                       command=toggle if invert else None).pack()

    def _add_tooltip(self, widget, text):
        tip = None
        def show(e):
            nonlocal tip
            tip = tk.Toplevel(widget)
            tip.wm_overrideredirect(True)
            tip.wm_geometry(f"+{e.x_root + 10}+{e.y_root + 20}")
            tk.Label(tip, text=text, font=("Segoe UI", 8),
                     bg="#ffffcc", fg="#333", relief="solid",
                     borderwidth=1, padx=6, pady=3).pack()
        def hide(e):
            nonlocal tip
            if tip:
                tip.destroy()
                tip = None
        widget.bind("<Enter>", show)
        widget.bind("<Leave>", hide)

    # ── Library status banner ──────────────────────────────────────────────────

    def _show_lib_status(self):
        def s(ok, name, feature, pkg):
            if ok:
                return f"  ✔  {name:<8} — {feature}", "ok"
            return (f"  ⚠  {name:<8} not installed — {feature}"
                    f"  (pip install {pkg})"), "warn"

        self._log_line("Library status:", "section")
        for line, tag in [
            s(RAWPY_AVAILABLE,   "rawpy",   "RAF/RAW capture-date extraction", "rawpy"),
            s(PILLOW_AVAILABLE,  "Pillow",  "enhanced JPEG/TIFF EXIF reading", "pillow"),
            s(PYWIN32_AVAILABLE, "pywin32", "USB camera (MTP) browsing",       "pywin32"),
        ]:
            self._log_line(line, tag)
        self._log_line("", "info")

    # ── Browse handlers ────────────────────────────────────────────────────────

    def _browse_src(self):
        d = filedialog.askdirectory(title="Select Source Directory (SD card / folder)")
        if d:
            self._mtp_mode = False
            self._mtp_path = None
            self._src.set(d)
            self._src_entry.configure(fg=TEXT)

    def _browse_dst(self):
        d = filedialog.askdirectory(title="Select Destination Directory")
        if d:
            self._dst.set(d)

    def _browse_mtp(self):
        """Open the Windows Shell folder picker — works with MTP/USB cameras."""
        self._log_line("Opening Windows Shell folder picker for USB camera…", "mtp")
        self._log_line("  Navigate to your camera under 'This PC' and select a folder.", "mtp")

        hwnd = int(self.winfo_id())
        path = _shell_browse_for_mtp_folder(hwnd)

        if not path:
            self._log_line("  Cancelled.", "info")
            return

        self._mtp_mode = True
        self._mtp_path = path
        display = path if len(path) <= 72 else "…" + path[-69:]
        self._src.set(display)
        self._src_entry.configure(fg=MTP_CLR)
        self._log_line(f"  ✔  Camera folder selected: {path}", "mtp")

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

    # ── Start / cancel ─────────────────────────────────────────────────────────

    def _start(self):
        dst = self._dst.get().strip()
        if not dst:
            messagebox.showwarning("Missing Input",
                                   "Please choose a destination directory.")
            return

        if self._mtp_mode:
            if not self._mtp_path:
                messagebox.showwarning(
                    "No Camera Selected",
                    "Please use 'Browse Camera (USB)…' to select a folder on your camera.")
                return
        else:
            src = self._src.get().strip()
            if not src:
                messagebox.showwarning("Missing Input",
                                       "Please choose a source directory.")
                return
            if not os.path.isdir(src):
                messagebox.showerror("Invalid Source",
                                     f"Source directory not found:\n{src}")
                return

        os.makedirs(dst, exist_ok=True)
        self._cancel  = False
        self._running = True
        self._start_btn.configure(state="disabled")
        self._cancel_btn.configure(state="normal")
        self._clear_log()
        self._progress["value"] = 0

        if self._mtp_mode:
            t = threading.Thread(
                target=self._worker_mtp, args=(self._mtp_path, dst), daemon=True)
        else:
            t = threading.Thread(
                target=self._worker_fs,  args=(self._src.get().strip(), dst), daemon=True)
        t.start()

    def _request_cancel(self):
        self._cancel = True
        self._status_lbl.configure(text="Cancelling…", fg=WARNING)

    # ── Filesystem worker (SD card / normal drive) ─────────────────────────────

    def _worker_fs(self, src: str, dst: str):
        do_copy   = self._copy_mode.get()
        action    = "Copying" if do_copy else "Moving"
        all_files = [p for p in Path(src).rglob("*") if p.is_file()]
        total     = len(all_files)

        self._log_line(f"{'─'*60}", "section")
        self._log_line(f"  {action} {total} file(s)  [SD card / folder mode]", "section")
        self._log_line(f"  Source : {src}", "section")
        self._log_line(f"  Dest   : {dst}", "section")
        self._log_line(f"{'─'*60}", "section")

        if total == 0:
            self._log_line("No files found in source directory.", "warn")
            self._finish(0, 0)
            return

        copied = errors = 0
        for idx, fp in enumerate(all_files, 1):
            if self._cancel:
                self._log_line("⚠  Cancelled by user.", "warn")
                break
            self._update_progress(idx, total)
            try:
                dest = self._dest_for(fp, fp.name, dst)
                if do_copy:
                    shutil.copy2(str(fp), str(dest))
                else:
                    shutil.move(str(fp), str(dest))
                self._log_line(
                    f"  ✔  [{dest.parent.name}]  {fp.name}  →  {dest.name}", "ok")
                copied += 1
            except Exception as exc:
                self._log_line(f"  ✘  {fp.name}  —  {exc}", "err")
                errors += 1

        self._finish(copied, errors)

    # ── MTP worker (USB camera via Windows Shell) ──────────────────────────────

    def _worker_mtp(self, mtp_path: str, dst: str):
        """
        Enumerate files on the MTP device, temp-copy each for EXIF reading,
        determine the YYYYMMDD folder, then copy to destination.
        Move mode attempts to delete originals from the camera via Shell.
        """
        self._log_line(f"{'─'*60}", "section")
        self._log_line("  Enumerating files on camera  [MTP/USB mode]…", "mtp")
        self._log_line(f"  Source : {mtp_path}", "section")
        self._log_line(f"  Dest   : {dst}", "section")
        self._log_line(f"{'─'*60}", "section")

        items = _enumerate_mtp_files(mtp_path, self._log_line)
        total = len(items)

        if total == 0:
            self._log_line("No files found on camera. "
                           "Check that you selected the correct folder "
                           "(e.g. DCIM or a sub-folder).", "warn")
            self._finish(0, 0)
            return

        self._log_line(f"  Found {total} file(s).  Starting transfer…", "mtp")

        do_copy = self._copy_mode.get()
        copied  = errors = 0

        for idx, item in enumerate(items, 1):
            if self._cancel:
                self._log_line("⚠  Cancelled by user.", "warn")
                break
            self._update_progress(idx, total)

            name     = item.Name
            tmp_path = None
            try:
                self._log_line(f"  Transferring  {name}…", "info")
                tmp_path = copy_mtp_file_to_temp(item)

                if tmp_path is None or not tmp_path.exists():
                    raise RuntimeError(
                        "Temporary copy failed — file did not appear on disk. "
                        "Try running the app as Administrator, or use the SD card instead.")

                dt       = get_photo_date(tmp_path)
                dest     = self._dest_for(tmp_path, name, dst, override_dt=dt)
                shutil.copy2(str(tmp_path), str(dest))

                self._log_line(
                    f"  ✔  [{dest.parent.name}]  {name}  →  {dest.name}", "ok")
                copied += 1

                # Move mode: ask Shell to delete the original from the camera
                if not do_copy:
                    try:
                        pythoncom.CoInitialize()
                        item.InvokeVerb("delete")
                        pythoncom.CoUninitialize()
                    except Exception:
                        self._log_line(
                            f"  ⚠  Could not delete {name} from camera — "
                            "please delete manually if needed.", "warn")

            except Exception as exc:
                self._log_line(f"  ✘  {name}  —  {exc}", "err")
                errors += 1
            finally:
                if tmp_path and tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except Exception:
                        pass

        self._finish(copied, errors)

    # ── Shared helpers ─────────────────────────────────────────────────────────

    def _dest_for(self, src_path: Path, name: str, dst: str,
                  override_dt: datetime | None = None) -> Path:
        """Return resolved destination Path (date folder + collision-safe name)."""
        dt       = override_dt or get_photo_date(src_path)
        dest_dir = Path(dst) / dt.strftime("%Y%m%d")
        dest_dir.mkdir(parents=True, exist_ok=True)
        return self._resolve_collision(dest_dir / name)

    def _resolve_collision(self, dest: Path) -> Path:
        if not dest.exists() or self._overwrite.get():
            return dest
        stem, suffix, n = dest.stem, dest.suffix, 1
        while dest.exists():
            dest = dest.parent / f"{stem}_{n}{suffix}"
            n += 1
        return dest

    def _update_progress(self, idx: int, total: int):
        pct = int(idx / total * 100)
        self.after(0, lambda v=pct: self._progress.configure(value=v))
        self.after(0, lambda i=idx, t=total: self._status_lbl.configure(
            text=f"{i}/{t} files", fg=SUBTEXT))

    def _finish(self, copied: int, errors: int):
        self.after(0, lambda: self._progress.configure(value=100))
        self.after(0, self._log_line, f"{'─'*60}", "section")
        self.after(0, self._log_line,
                   f"  Done — {copied} copied,  {errors} error(s)", "section")
        self.after(0, self._log_line, f"{'─'*60}", "section")
        self.after(0, lambda: self._status_lbl.configure(
            text=f"Done — {copied} copied, {errors} errors",
            fg=SUCCESS if errors == 0 else WARNING))
        self.after(0, lambda: self._start_btn.configure(state="normal"))
        self.after(0, lambda: self._cancel_btn.configure(state="disabled"))
        self._running = False


# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app = PhotoOrganizerApp()
    app.mainloop()
