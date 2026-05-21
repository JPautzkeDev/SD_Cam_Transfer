# 📷 Photo Organizer

A Windows desktop application that copies or moves photos from an SD card or USB camera into date-based folders on your PC. Folders are named in `YYYYMMDD` format based on the actual capture date embedded in each photo's EXIF data.

---

## Files

| File | Description |
|---|---|
| `photo_organizer.py` | Main application |
| `launch_photo_organizer.bat` | Double-click launcher (no console window) |
| `README.md` | This file |

---

## Requirements

### Python
Python 3.8 or later is required. Download from [python.org](https://www.python.org/downloads/).

> **Important:** During installation, check **"Add Python to PATH"**.

### Python Libraries
Open a Command Prompt and run:

```
pip install pillow rawpy pywin32
```

| Library | Purpose | Without it |
|---|---|---|
| `pillow` | Enhanced EXIF reading for JPEG and TIFF files | Falls back to built-in parser |
| `rawpy` | Capture-date extraction from RAF and other RAW files | RAF files use file-modified date instead |
| `pywin32` | USB camera (MTP) browsing via Windows Shell | USB camera button is disabled |

---

## How to Launch

Double-click **`launch_photo_organizer.bat`**.

No console window will appear. If it fails to open, see the Troubleshooting section below.

---

## Using the App

### SD Card (Recommended)

1. Insert your SD card — it will appear as a drive letter (e.g. `E:\`)
2. Click **Browse…** next to *Source Directory* and navigate to the card (typically the `DCIM` folder)
3. Click **Browse…** next to *Destination Directory* and choose a folder on your PC
4. Choose **Copy** (keeps originals on card) or **Move** (removes originals after transfer)
5. Click **▶ Start**

### USB Camera (MTP)

Some cameras connected by USB are exposed as MTP devices and do not get a drive letter. To import from these:

1. Connect your camera via USB and turn it on
2. Click **📷 Camera (USB)…** — this opens the native Windows folder picker, which can see MTP devices
3. Navigate to your camera under **This PC** and select the `DCIM` folder (or a sub-folder)
4. The source field will turn purple to confirm USB/MTP mode is active
5. Choose your destination, copy/move option, then click **▶ Start**

> **Note:** MTP support requires `pywin32` to be installed. If the button is greyed out, run `pip install pywin32` and restart the app.

---

## How Dates Are Determined

The app reads the photo's actual capture date in this priority order:

1. **EXIF `DateTimeOriginal`** — the timestamp written by the camera at the moment of capture (most accurate)
2. **EXIF `DateTime`** — fallback EXIF field
3. **File modification date** — used if no EXIF data is available (less reliable; can change during transfers)

### Supported File Types

| Type | Extensions | Date Source |
|---|---|---|
| Fujifilm RAW | `.raf` | rawpy (EXIF) |
| Other RAW formats | `.cr2` `.cr3` `.nef` `.arw` `.dng` `.orf` `.rw2` and more | rawpy (EXIF) |
| JPEG / TIFF | `.jpg` `.jpeg` `.tiff` `.tif` | Pillow or built-in parser (EXIF) |
| All other files | `.mp4` `.png` `.heic` etc. | File modification date |

---

## Destination Folder Structure

Photos are organized into sub-folders inside your chosen destination:

```
Destination/
├── 20240315/
│   ├── DSCF0001.RAF
│   ├── DSCF0001.JPG
│   └── DSCF0002.RAF
├── 20240316/
│   ├── DSCF0050.RAF
│   └── DSCF0051.RAF
└── 20240320/
    └── DSCF0100.RAF
```

---

## Options

| Option | Description |
|---|---|
| **Copy files** | Copies photos to destination; originals remain on the card/camera |
| **Move files** | Copies to destination, then deletes originals from the source |
| **Auto-rename** | If a file with the same name already exists in the date folder, a number suffix is appended (e.g. `DSCF0001_1.RAF`). Default behavior. |
| **Skip** | If a file with the same name already exists, it is left on the source and not copied. Useful for incremental imports where you don't want to re-copy photos already transferred. |
| **Overwrite** | Replaces any existing file in the destination with the same name |

---

## Log Panel

The log at the bottom of the app shows real-time status for every file:

- **Green ✔** — file copied successfully, showing its date folder and final filename
- **Yellow ⚠** — warning (e.g. a file could not be deleted from camera in Move mode)
- **Red ✘** — error copying a file (file is skipped; others continue)
- **Purple** — MTP/USB camera activity

Library status (rawpy, Pillow, pywin32) is shown each time the app starts so you can confirm all features are active.

---

## Troubleshooting

**App does not open when I double-click the .bat file**
- Confirm Python is installed: open Command Prompt and type `python --version`
- If not found, reinstall Python and check "Add Python to PATH" during setup

**📷 Camera (USB)… button is greyed out**
- Run `pip install pywin32` in Command Prompt, then restart the app

**RAF files are sorted into wrong date folders**
- Run `pip install rawpy` — without it, file-modified date is used instead of capture date
- After installing, restart the app; the log should show `✔ rawpy` in green

**USB camera mode finds 0 files**
- Make sure you selected the correct folder (usually `DCIM` or a folder inside it)
- Try selecting a deeper sub-folder if the top-level folder appears empty
- Some cameras require you to set the USB mode to "PC Transfer" or "MTP" in the camera menu
- As a fallback, use the SD card directly in a card reader — this is always the most reliable method

**Files have wrong dates after transfer**
- Check the log on startup — if rawpy or Pillow show a warning, install them with `pip install rawpy pillow`
- Verify your camera's date/time setting is correct

---

## Tips

- A card reader is always more reliable than USB cable for bulk transfers
- For Fujifilm cameras, the SD card typically appears as `DCIM\100_FUJI` or similar
- The **Cancel** button stops the transfer cleanly between files — any file already copied is kept
- You can run the app multiple times safely; files that already exist in a date folder will get a number suffix rather than being overwritten (unless Overwrite is checked)
