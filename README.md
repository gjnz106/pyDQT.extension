# pyDQT

**pyRevit extension for Autodesk Revit — professional BIM automation tools.**

> 69 tools · 10 panels · Revit 2024 – 2027

pyDQT adds a single **pyDQT** tab to the Revit ribbon, organised into ten panels that
follow the modelling workflow from interface setup and element selection, through
modelling and annotation, to data exchange, IFC-SG compliance and model cleanup.

Author: **Dang Quoc Truong (DQT)**

---

## Requirements

- **Autodesk Revit** 2024, 2025, 2026 or 2027
- **pyRevit** 4.8 or newer (tested on 6.1+), with the **IronPython** engine (default)
- **Windows** 10 / 11 (administrator rights for the first install)
- Internet access to download the pyRevit installer

## Installation

### 1. Install pyRevit

1. Download the latest installer from
   [github.com/pyrevitlabs/pyRevit/releases](https://github.com/pyrevitlabs/pyRevit/releases)
   (`pyRevit_x.x.x_signed.exe`).
2. Close every running Revit session.
3. Run the installer with the default options. pyRevit installs to
   `%AppData%\pyRevit-Master` and attaches to all detected Revit versions.
4. Start Revit — a **pyRevit** tab should appear on the ribbon. If prompted to load the
   add-in, choose **Always Load**.

### 2. Install pyDQT

1. Get the `pyDQT.zip` package.
2. Create this folder if it does not exist:
   ```
   %AppData%\pyRevit\Extensions\pyDQT
   ```
   (Paste `%AppData%\pyRevit\Extensions` into the File Explorer address bar to jump there.)
3. Extract the ZIP so the final structure is exactly:
   ```
   ...\pyRevit\Extensions\pyDQT\pyDQT.extension\pyDQT.tab\...
   ```
   > The `pyDQT.extension` folder name (with the `.extension` suffix) is required by
   > pyRevit — **do not rename it**. If you end up with
   > `pyDQT.extension\pyDQT.extension`, move the inner folder up one level.

### 3. Register the extension path

1. In Revit, open the **pyRevit** tab → **Settings**.
2. Under **Custom Extension Directories**, click **Add folder** and select the **parent
   folder that contains `pyDQT.extension`** (the `pyDQT` folder) — not `pyDQT.extension`
   itself, and not `pyDQT.tab`.
3. Click **Save Settings & Reload**. The **pyDQT** tab appears with 10 panels.

**To update later:** delete the old `pyDQT.extension` folder, extract the new ZIP to the
same location, and press the pyRevit **Reload** button.

## Ribbon overview

| Panel | Purpose |
|-------|---------|
| **UI** | Revit interface utilities: manage ribbon tabs, shorten ribbon names, set the canvas background theme. |
| **Select** | Find and select elements quickly — by category, family, type, material or link. |
| **Inquiry** | Model auditing and QC: health checks, warnings, in-place statistics. |
| **Modify** | Geometry editing: split walls/floors/columns, convert CAD to model elements, adjust walls, align grids and levels. |
| **Annotate** | Dimensioning, tagging and annotation management between views and models. |
| **Views-Sheets** | View and sheet management: batch operations, templates, numbering, section boxes. |
| **Data** | Schedules, Excel export/import, parameter transfer, BCF coordination data. |
| **IFC-SG** | IFC-SG (CORENET X) compliance workflow for Singapore submissions. |
| **Settings** | Project standards: families, parameters, line styles, line patterns, text types, filled regions, color overrides. |
| **Cleanup** | Smart purge of unused content and safe batch deletion. |

## Tools

### UI
- **BG Theme** — Set the model-view background colour from a themed picker (presets, RGB sliders, HEX, live preview). `SHIFT + Click` quick-cycles Black → Gray → White.
- **Ribbon Names** — Shorten or restore Revit ribbon tab names.
- **Tab Manager** — Toggle the visibility of unwanted ribbon tabs.

### Select
- **Material Select** — Material statistics with element finder.
- **Quick Select** — Hierarchical Category → Family → Type → Instance browser; search, zoom and select (including hidden elements).
- **Select Linked** — Unhide linked elements.
- **Select** (drop-down): Deselect Grouped Elements · Select In-Place Elements · Select By Category · On Sheets (DWGs / Title Blocks) · Select Similar by Category / Family / Type (in Model or in View).

### Inquiry
- **Health Check** — Color-coded model-health dashboard (file size, warnings, CAD imports, in-place families, links, worksets, views, sheets…).
- **InPlace Model** — Manage and check in-place models.
- **Material List** — Standalone material manager.
- **Model Checker** — Rule-based BIM compliance checker with customizable JSON checksets and Excel reporting.
- **Warning** — Manage and resolve Revit warnings.

### Modify
- **AutoJoin** — Auto-join elements with rule-based category pairs (save/load settings).
- **CAD to Floor** — Create Floors or Parts (DirectShape) from linked/imported DWG geometry.
- **CAD to Wall** — Detect parallel CAD line pairs, compute centerlines, auto-create matching wall types.
- **Gridline** (drop-down): Align Gridline · Convert Gridline (swap 3D ↔ 2D extents).
- **Level** (drop-down): Align Level · Convert Level (swap 3D ↔ 2D extents, bubble control).
- **Room to Area** — Create Areas from selected Rooms with matching boundaries.
- **Split** (drop-down): Column Split · Floor Split · Wall Split.
- **Wall Cut Profile** — Create wall openings from intersecting linked elements.
- **Wall Adjust Base** — Auto-adjust Base Offset when changing Base Constraint to keep position.

### Annotate
- **Copy Annotation** — Copy annotations (dimensions, tags, text, detail items/lines) between matching views in two open documents.
- **Dimension** (drop-down): Dim Column · Dim Wall · Snap Dimension (round to nearest gridline).
- **Renumber by spline** — Renumber doors/rooms by proximity along a spline.
- **Tag Checker** — Check whether elements in the current view are fully tagged.

### Views-Sheets
- **Linked Element Box** — Section box around linked elements.
- **Sheet re-number** — Batch sheet renumbering.
- **Sheet Manager** — Advanced sheet management.
- **View Manager** — Advanced view management with summary cards.
- **View Template** — Standalone view-template manager.

### Data
- **BCF Reader** — Read BCF files from IFC Delta Viewer and navigate issues in Revit.
- **Contains Manager** — Find elements in Rooms/Areas/Spaces and assign parameter values.
- **Foundation Volume** — Write built-in volume into a selected parameter on structural foundations.
- **Room Data Collector** — Aggregate parameter values from elements into spatial elements (reverse of Contains Manager).
- **Schedule Export/Import Pro** — Export/import schedules to Excel, reading directly from elements.
- **Schedule Copy** — Advanced schedule duplicator with template options.
- **Text to Element** — Transfer Text Note values to intersecting elements.
- **Transfer Para** — Transfer values between parameters on the same elements (all storage types).

### IFC-SG
- **Auto Assign** — Assign IFC export parameters per family type from the LTA Industry Mapping Excel.
- **Subtype Definer** — Batch-assign IFC entity & predefined type for CORENET X.
- **IFCSG Checker** — Verify required IFC-SG parameters exist and have values.
- **Manual Assign** — Manually assign IFC export parameters.
- **Parameter Loader** — Add required IFC-SG project parameters bound to the correct categories.

### Settings
- **Color Splasher** — Auto-color elements by parameter value (gradient/random, legend, view filters).
- **Family Manager** — Manage and check families.
- **Hatching** — Manage and rename fill patterns.
- **Line Pattern** — Manage line patterns.
- **Line Style Edit** — Manage and rename line styles.
- **ParaManager** — Standalone parameter manager.
- **Text** — Manage text note types.

### Cleanup
- **Advanced Purge** — Power-user purge operations. ⚠️ Contains dangerous operations — always preview first.
- **Smart Delete** — Analyze element dependencies before safe deletion.
- **Smart Purge** — Scan and purge unused elements (materials, line patterns…) with preview, dry-run and undo.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| pyDQT tab does not appear after reload | The extension path is wrong. It must point to the **parent folder** containing `pyDQT.extension` — not `pyDQT.extension` itself, and not `pyDQT.tab`. |
| Tab appears but some panels are empty/missing | The ZIP was extracted with a nested `pyDQT.extension\pyDQT.extension` folder, or extraction was incomplete. Delete and re-extract, then Reload. |
| `Save Settings` fails: *pyRevit.addin … being used by another process* | Another Revit session or antivirus is locking the manifest. Close all Revit instances, run `pyrevit attach master default --installed`, then restart Revit. |
| Errors in the pyRevit output window during Reload | Screenshot the full error (it names the file) and send it to DQT. The tab still loads the remaining tools. |
| A tool crashes with an IronPython error | Confirm the active engine is IronPython (pyRevit Settings → Engines). Screenshot the traceback and send it to DQT. |
| Buttons show without icons | Extraction was incomplete or icon files were blocked. Right-click the ZIP → Properties → **Unblock** before extracting, then extract again. |

## License

See the [LICENSE](LICENSE) file.

---

**Made for the AEC community** · pyDQT by Dang Quoc Truong (DQT)
