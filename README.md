# scroller-brawler
A native Windows productivity tool that summons an instant radial conversion &amp; editing pie menu when dragging files with Shift held.
# Scrawler Brawler 

> Brawl through file conversions, crops, and backdrop stylings on Windows with a single drag-and-drop gesture.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)
![Platform](https://img.shields.io/badge/Platform-Windows-0078D6?logo=windows)
![Framework](https://img.shields.io/badge/UI-PyQt6-41CD52?logo=qt)
![License](https://img.shields.io/badge/License-MIT-green)

---

What is Scrawler Brawler?

Scrawler Brawler cuts out the tedious friction of converting and polishing desktop files. Instead of opening browser converters, dealing with ad-riddled upload sites, or fighting bloated context menus, Scrawler Brawler intercepts native drag gestures directly on your Desktop or inside File Explorer:

1. **Click and drag** any PDF or image file.
2. **Hold `Shift`** while moving the cursor.
3. A translucent radial pie menu appears directly beneath your cursor.
4. **Drop** onto your desired target format or utility action.

---

Key Features

- **Context-Aware Radial Menus:**
  - **PDF Dropped:** Displays instant conversions to **DOCX**, **PNG**, **JPG**, **TXT**, and **RTF**.
  - **Image Dropped (Convert Mode):** Quick export to **PNG**, **WEBP**, **HEIC**, **GIF**, **AVIF**, **BMP**, **TIFF**, **PDF**, or **DOCX**.
  - **Image Dropped (Tools Mode):** Instant access to utilities including **Crop**, **Add BG**, **Compress**, and **Metadata Wipe**.
- **Interactive Crop Studio:**
  - Freeform or aspect-ratio locked cropping (`1:1`, `16:9`, `4:3`, `3:2`, `9:16`).
  - Interactive drag handles, rule-of-thirds grid, and live pixel dimension readouts.
- **"Add BG" Canvas Studio:**
  - Curated gradient and solid backdrop presets.
  - Granular controls for canvas padding, image corner radius, and realistic Gaussian drop shadows.
- **100% Offline & Private:**
  - Zero cloud dependencies. All rendering, document parsing, and format conversions happen locally on your hardware.
- **Silent System Tray Utility:**
  - Sits unobtrusively in your taskbar with near-zero idle CPU usage.

---

Shortcut & Control Map

| Action | Shortcut / Trigger |
| :--- | :--- |
| **Summon Radial Menu** | Left-click drag any file + hold **`Shift`** |
| **Switch Modes (Images)** | Press **`Tab`** while dragging, or hover the bottom `⚙` toggle |
| **Dismiss Menu** | Release the mouse button outside the radial circle |
| **Close Editor Dialogs** | Press **`Esc`** or click **Cancel** |

---

Quick Start (Pre-built Executable)

1. Download `ScrawlerBrawler.exe` from the [Releases](https://github.com/your-username/ScrawlerBrawler/releases) tab.
2. Double-click to launch. The app icon will appear in your Windows System Tray (bottom-right near the clock).
3. Drag any `.png`, `.jpg`, or `.pdf` on your desktop, hold **`Shift`**, and drop onto a slice!

---

Building & Running from Source

Prerequisites
- Windows 10 or 11
- Python 3.10+

Installation

```powershell
# Clone the repository
git clone [https://github.com/your-username/ScrawlerBrawler.git](https://github.com/your-username/ScrawlerBrawler.git)
cd ScrawlerBrawler

# Create and activate virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Run the app
python radial_drop.py
