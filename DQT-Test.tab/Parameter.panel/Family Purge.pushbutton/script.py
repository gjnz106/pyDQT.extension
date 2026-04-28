# -*- coding: utf-8 -*-
"""
Batch Purge Families Tool
Automatically purges all .rfa family files inside a selected folder.
Compatible : Revit 2024 / 2025 · PyRevit
UI         : WPF — NV Pink / Rose Design System
"""

__title__ = "Purge\nFamilies"
__doc__   = "Automatically purge unused elements in all .rfa files inside a selected folder."
__author__ = "NV"

import os
import re
import zipfile
import datetime

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")
clr.AddReference("System.Windows.Forms")   # FolderBrowserDialog + DoEvents only

import System.IO                            # DirectoryInfo, FileInfo — used for backup deletion

from Autodesk.Revit.DB import (
    OpenOptions, SaveAsOptions, ModelPathUtils,
    FailureProcessingResult, IFailuresPreprocessor, FailureSeverity,
    Transaction, DetachFromCentralOption,
    FilteredElementCollector, FamilySymbol, FamilyInstance,
    ImportInstance, Material, ViewFamilyType
)
import Autodesk.Revit.DB as DB

from System.Windows.Forms import FolderBrowserDialog
from System.Windows.Forms import DialogResult as FDResult
from System.Windows.Forms import Application  as WFApp

import System
from System.Windows import (
    Window, Thickness, FontWeights,
    MessageBox, MessageBoxButton, MessageBoxImage, MessageBoxResult,
    HorizontalAlignment, VerticalAlignment, Visibility
)
from System.Windows.Controls import (
    DockPanel, StackPanel, Border, ScrollViewer,
    TextBlock, TextBox, Button, CheckBox,
    ListBox, ListBoxItem, ProgressBar,
    Orientation, ScrollBarVisibility, SelectionMode
)
from System.Windows.Media import SolidColorBrush, Color, FontFamily

# ---------------------------------------------------------------------------
#  Revit handles
# ---------------------------------------------------------------------------
app   = __revit__.Application
uidoc = __revit__


# ===========================================================================
#  NV BRAND COLORS — Gold / Warm variant  (NV_UI_Reference.html)
# ===========================================================================
def _c(r, g, b):  return Color.FromRgb(r, g, b)

CLR_HEADER      = _c(240, 204, 136)   # #F0CC88  gold header
CLR_HEADER_TEXT = _c( 51,  51,  51)   # #333333  dark text on gold
CLR_HEADER_SUB  = _c(102, 102, 102)   # #666666  subtitle under title
CLR_ACCENT      = _c( 93,  78,  55)   # #5D4E37  brown accent (labels, badge)
CLR_BG          = _c(254, 248, 231)   # #FEF8E7  cream window background
CLR_CARD        = _c(255, 255, 255)   # #FFFFFF  card surface
CLR_BORDER      = _c(212, 184, 122)   # #D4B87A  gold border
CLR_FOOTER      = _c(245, 240, 224)   # #F5F0E0  footer bar background
CLR_TEXT        = _c( 51,  51,  51)   # #333333  body text
CLR_MUTED       = _c(153, 153, 153)   # #999999  muted / status text
CLR_ALT         = _c(255, 248, 238)   # #FFF8EE  summary box background
CLR_LIST_BG     = _c(255, 253, 245)   # warm-tinted list background
CLR_APPLY_BG    = _c(200, 230, 201)   # #C8E6C9  green success (semantic)
CLR_APPLY_BDR   = _c(129, 199, 132)   # #81C784
CLR_APPLY_TEXT  = _c( 46, 125,  50)   # #2E7D32

FONT_UI   = FontFamily("Segoe UI")
FONT_MONO = FontFamily("Consolas")

# ---------------------------------------------------------------------------
#  Revit backup file patterns  (from reference API code)
#
#  Revit saves backups as:
#    FamilyName.0001.rfa   (family backup)
#    ProjectName.0001.rvt  (project backup)
#
#  Pattern: <name>.<4digits>.<rfa|rvt>
#  This is DIFFERENT from what was assumed before (FamilyName.0001 with no .rfa).
# ---------------------------------------------------------------------------
_BACKUP_RFA_RE = re.compile(r'^.+\.\d{4}\.rfa$', re.IGNORECASE)
_BACKUP_RVT_RE = re.compile(r'^.+\.\d{4}\.rvt$', re.IGNORECASE)

def _is_revit_backup(filename):
    """
    Return True for Revit automatic backup files:
      FamilyName.0001.rfa   ProjectName.0042.rvt
    Non-matches: FamilyName.rfa  report.xlsx  FamilyName.0001 (no extension after digits)
    """
    return bool(_BACKUP_RFA_RE.match(filename) or _BACKUP_RVT_RE.match(filename))


# ===========================================================================
#  Failure Preprocessor — silently dismiss all warnings during purge
# ===========================================================================
class SilentFailurePreprocessor(IFailuresPreprocessor):
    def PreprocessFailures(self, fa):
        for f in fa.GetFailureMessages():
            if f.GetSeverity() == FailureSeverity.Warning:
                fa.DeleteWarning(f)
            else:
                fa.ResolveFailure(f)
        return FailureProcessingResult.Continue


# ===========================================================================
#  Helper — safe ElementId integer value (Revit 2024 vs 2025+)
# ===========================================================================
def _eid_int(eid):
    """Return the integer value of an ElementId across Revit versions."""
    try:
        return eid.IntegerValue
    except AttributeError:
        return eid.Value


def _apply_failure_handler(transaction):
    """Attach SilentFailurePreprocessor to a transaction."""
    opts = transaction.GetFailureHandlingOptions()
    opts.SetFailuresPreprocessor(SilentFailurePreprocessor())
    transaction.SetFailureHandlingOptions(opts)


# ===========================================================================
#  Comprehensive Unused Element Collector  (fallback for Revit 2024)
#
#  GetUnusedElements() on Revit 2024 misses many categories that the
#  native Purge Unused dialog catches.  This collector replicates the
#  native behavior by checking each category individually.
# ===========================================================================
def _collect_unused_elements(doc):
    """
    Manually collect unused purgeable elements across all categories
    that the Revit native Purge Unused dialog would show.
    Returns a Python list of ElementId.
    """
    unused = []

    # ── 1) Unused FamilySymbol (family types with zero placed instances) ──
    used_type_ids = set()
    try:
        for inst in FilteredElementCollector(doc).OfClass(FamilyInstance):
            tid = inst.GetTypeId()
            if tid and tid != DB.ElementId.InvalidElementId:
                used_type_ids.add(_eid_int(tid))
    except Exception:
        pass

    try:
        for sym in FilteredElementCollector(doc).OfClass(FamilySymbol):
            if _eid_int(sym.Id) not in used_type_ids:
                unused.append(sym.Id)
    except Exception:
        pass

    # ── 2) Unused Materials ──────────────────────────────────────────────
    #  Collect materials referenced by elements, then find unreferenced ones.
    used_mat_ids = set()
    try:
        for elem in FilteredElementCollector(doc).WhereElementIsNotElementType():
            try:
                mat_ids = elem.GetMaterialIds(False)
                for mid in mat_ids:
                    if mid and mid != DB.ElementId.InvalidElementId:
                        used_mat_ids.add(_eid_int(mid))
            except Exception:
                pass
        # Also check element types for materials
        for elem in FilteredElementCollector(doc).WhereElementIsElementType():
            try:
                mat_ids = elem.GetMaterialIds(False)
                for mid in mat_ids:
                    if mid and mid != DB.ElementId.InvalidElementId:
                        used_mat_ids.add(_eid_int(mid))
            except Exception:
                pass
    except Exception:
        pass

    try:
        for mat in FilteredElementCollector(doc).OfClass(Material):
            if _eid_int(mat.Id) not in used_mat_ids:
                unused.append(mat.Id)
    except Exception:
        pass

    # ── 3) Unused ImportInstance (orphan CAD links) ──────────────────────
    try:
        for imp in FilteredElementCollector(doc).OfClass(ImportInstance):
            if not imp.IsLinked:
                unused.append(imp.Id)
    except Exception:
        pass

    # ── 4) Unused ViewFamilyType ─────────────────────────────────────────
    used_vft_ids = set()
    try:
        for v in FilteredElementCollector(doc).OfClass(DB.View):
            try:
                vtid = v.GetTypeId()
                if vtid and vtid != DB.ElementId.InvalidElementId:
                    used_vft_ids.add(_eid_int(vtid))
            except Exception:
                pass
    except Exception:
        pass

    try:
        for vft in FilteredElementCollector(doc).OfClass(ViewFamilyType):
            if _eid_int(vft.Id) not in used_vft_ids:
                unused.append(vft.Id)
    except Exception:
        pass

    # ── 5) Unused LinePatternElement ─────────────────────────────────────
    try:
        LinePatternElement = getattr(DB, "LinePatternElement", None)
        if LinePatternElement:
            all_lp = {}
            for lp in FilteredElementCollector(doc).OfClass(LinePatternElement):
                all_lp[_eid_int(lp.Id)] = lp.Id
            # Check references via GraphicsStyle
            used_lp = set()
            for gs in FilteredElementCollector(doc).OfClass(DB.GraphicsStyle):
                try:
                    cat = gs.GraphicsStyleCategory
                    if cat:
                        for gst in [DB.GraphicsStyleType.Projection, DB.GraphicsStyleType.Cut]:
                            try:
                                lpid = cat.GetLinePatternId(gst)
                                if lpid and lpid != DB.ElementId.InvalidElementId:
                                    used_lp.add(_eid_int(lpid))
                            except Exception:
                                pass
                except Exception:
                    pass
            for lp_val, lp_id in all_lp.items():
                if lp_val not in used_lp:
                    unused.append(lp_id)
    except Exception:
        pass

    # ── 6) Unused FillPatternElement ─────────────────────────────────────
    try:
        FillPatternElement = getattr(DB, "FillPatternElement", None)
        if FillPatternElement:
            all_fp = {}
            for fp in FilteredElementCollector(doc).OfClass(FillPatternElement):
                all_fp[_eid_int(fp.Id)] = fp.Id
            # Fill patterns used by materials
            used_fp = set()
            for mat in FilteredElementCollector(doc).OfClass(Material):
                for attr_name in [
                    "SurfaceForegroundPatternId", "SurfaceBackgroundPatternId",
                    "CutForegroundPatternId", "CutBackgroundPatternId"
                ]:
                    try:
                        fpid = getattr(mat, attr_name, None)
                        if fpid and callable(fpid):
                            fpid = fpid()
                        if fpid and fpid != DB.ElementId.InvalidElementId:
                            used_fp.add(_eid_int(fpid))
                    except Exception:
                        pass
            for fp_val, fp_id in all_fp.items():
                if fp_val not in used_fp:
                    unused.append(fp_id)
    except Exception:
        pass

    # ── 7) Unused Groups (GroupType with no placed instances) ────────────
    try:
        GroupType = getattr(DB, "GroupType", None)
        Group     = getattr(DB, "Group", None)
        if GroupType and Group:
            used_gt = set()
            for g in FilteredElementCollector(doc).OfClass(Group):
                try:
                    gtid = g.GetTypeId()
                    if gtid and gtid != DB.ElementId.InvalidElementId:
                        used_gt.add(_eid_int(gtid))
                except Exception:
                    pass
            for gt in FilteredElementCollector(doc).OfClass(GroupType):
                if _eid_int(gt.Id) not in used_gt:
                    unused.append(gt.Id)
    except Exception:
        pass

    return unused


# ===========================================================================
#  Purge Engine  (Revit 2024 + 2025 compatible)
# ===========================================================================
def purge_document(doc, max_passes=5):
    """
    Repeatedly delete unused elements until nothing remains or max_passes hit.
    Strategy:
      1) Try GetUnusedElements() each pass — works fully on 2025,
         partially on 2024.
      2) When GetUnusedElements returns 0, run comprehensive manual
         collector (_collect_unused_elements) to catch what it missed.
      3) All transactions use SilentFailurePreprocessor to suppress
         warning dialogs that would block the batch process.
    Returns (total_elements_deleted, passes_used).
    """
    total_purged  = 0
    passes_done   = 0
    tried_fallback = False

    for i in range(max_passes):
        passes_done = i + 1
        ids = None

        # --- Primary: GetUnusedElements (Revit 2024+) ---
        try:
            ids = doc.GetUnusedElements(
                System.Collections.Generic.HashSet[DB.ElementId]()
            )
        except Exception:
            ids = None

        primary_count = 0
        if ids is not None:
            primary_count = ids.Count if hasattr(ids, "Count") else len(list(ids))

        # --- Fallback: comprehensive manual collector ---
        if primary_count == 0:
            if tried_fallback:
                break  # already ran fallback last pass, nothing left
            tried_fallback = True
            fallback = _collect_unused_elements(doc)
            if fallback:
                ids = fallback
            else:
                break
        else:
            tried_fallback = False  # reset so fallback can run again later

        count = ids.Count if hasattr(ids, "Count") else len(list(ids))
        if count == 0:
            break

        # --- Delete batch with failure handler ---
        try:
            t = Transaction(doc, "Purge Pass {}".format(i + 1))
            _apply_failure_handler(t)
            t.Start()
            doc.Delete(ids)
            t.Commit()
            total_purged += count
        except Exception:
            try: t.RollBack()
            except: pass
            # One-by-one fallback for locked / protected elements
            deleted = 0
            for eid in ids:
                try:
                    t2 = Transaction(doc, "Purge Single")
                    _apply_failure_handler(t2)
                    t2.Start()
                    doc.Delete(eid)
                    t2.Commit()
                    deleted += 1
                except:
                    try: t2.RollBack()
                    except: pass
            total_purged += deleted
            if deleted == 0:
                break

    return total_purged, passes_done


def process_family_file(filepath, max_passes=10):
    """
    Open one .rfa, purge, overwrite-save, close.
    Returns a result dict used for the Excel log.
    """
    result = {
        "file"         : os.path.basename(filepath),
        "path"         : filepath,
        "status"       : "Pending",
        "purged_count" : 0,
        "passes"       : 0,
        "error"        : "",
        "size_before"  : 0,
        "size_after"   : 0,
        "time"         : ""
    }
    doc = None
    try:
        result["size_before"] = os.path.getsize(filepath) // 1024

        open_opts = OpenOptions()
        open_opts.DetachFromCentralOption = DetachFromCentralOption.DoNotDetach
        model_path = ModelPathUtils.ConvertUserVisiblePathToModelPath(filepath)
        doc = app.OpenDocumentFile(model_path, open_opts)

        if doc is None:
            result["status"] = "Error"
            result["error"]  = "Could not open file"
            return result

        result["purged_count"], result["passes"] = purge_document(doc, max_passes)

        save_opts = SaveAsOptions()
        save_opts.OverwriteExistingFile = True
        doc.SaveAs(filepath, save_opts)
        doc.Close(False)

        result["size_after"] = os.path.getsize(filepath) // 1024
        result["status"]     = "Success"

    except Exception as ex:
        result["status"] = "Error"
        result["error"]  = str(ex)
        if doc:
            try: doc.Close(False)
            except: pass

    return result


# ===========================================================================
#  Backup File Deletion  — uses System.IO (same API as reference script)
#
#  WHY System.IO instead of os.remove()?
#    os.remove() can silently fail on:
#      - Windows long paths (>260 chars)
#      - Read-only file attributes
#      - Network drives with special permissions
#    System.IO.FileInfo.Delete() handles all these correctly, mirrors
#    what the reference script does with file.Delete().
# ===========================================================================
def delete_backup_files(folder, recursive):
    """
    Scan folder for Revit backup files (*.0001.rfa / *.0001.rvt) and delete
    them using System.IO.FileInfo.Delete().
    Returns (deleted_count, freed_bytes, failed_list_of_(name, error_str)).

    Uses a mutable list _counters = [deleted_count, freed_bytes] because
    IronPython 2.7 does not support the 'nonlocal' keyword.
    """
    _counters = [0, 0]   # [deleted_count, freed_bytes]
    failed    = []

    def _process_dir(dir_path):
        try:
            dir_info = System.IO.DirectoryInfo(dir_path)
        except Exception:
            return

        # Recurse into sub-directories first (mirrors reference script order)
        if recursive:
            try:
                for sub_dir in dir_info.GetDirectories():
                    _process_dir(sub_dir.FullName)
            except Exception:
                pass

        # Scan files in this directory
        try:
            for file_info in dir_info.EnumerateFiles():
                if _is_revit_backup(file_info.Name):
                    size = file_info.Length
                    try:
                        file_info.Delete()
                        _counters[0] += 1
                        _counters[1] += size
                    except Exception as ex:
                        failed.append((file_info.Name, str(ex)))
        except Exception:
            pass

    _process_dir(folder)
    return _counters[0], _counters[1], failed



# ===========================================================================
#  Excel Export — Open XML format (no openpyxl / no external library needed)
#
#  WHY NOT openpyxl?
#    openpyxl is a CPython library. PyRevit runs on IronPython 2.7, which
#    cannot import CPython C-extension wheels. Attempting to import openpyxl
#    in PyRevit will always raise ImportError.
#
#  SOLUTION — Open XML (.xlsx) is just a ZIP containing XML files.
#    We write the XML by hand and zip it up. The result opens correctly in
#    Excel, LibreOffice, and Google Sheets with full formatting.
#
#  PURPOSE of the Excel log:
#    - Audit trail  : which families were processed and when.
#    - Size report  : KB before vs after → instantly see space freed.
#    - Error column : exception messages for any file that failed,
#                     so you can fix and re-run without guessing.
#    - Pass column  : how many iterations were needed — use this to tune
#                     the "Max purge passes" setting.
# ===========================================================================

def _xml_escape(s):
    """Escape characters that would break XML string attributes/content."""
    s = str(s)
    s = s.replace("&",  "&amp;")
    s = s.replace("<",  "&lt;")
    s = s.replace(">",  "&gt;")
    s = s.replace('"',  "&quot;")
    s = s.replace("'",  "&apos;")
    # Strip non-printable ASCII that XML 1.0 forbids
    s = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', s)
    return s

def _xlsx_cell(col, row, value, style_id=0):
    """
    Return a <c> element string for one cell.
    Numbers are written as numbers; everything else as inline strings.
    style_id maps to the <xf> index in the stylesheet (0=default, 1=header).
    """
    cell_ref = "{}{}".format(col, row)
    if style_id:
        s_attr = ' s="{}"'.format(style_id)
    else:
        s_attr = ''

    # Try numeric
    try:
        num = float(value) if value != "" else None
    except (ValueError, TypeError):
        num = None

    if num is not None and value != "":
        return '<c r="{}"{}><v>{}</v></c>'.format(cell_ref, s_attr, num)
    else:
        escaped = _xml_escape(value)
        return '<c r="{}"{}  t="inlineStr"><is><t>{}</t></is></c>'.format(
            cell_ref, s_attr, escaped)

# Column letters A-G (7 columns — Time and Path removed)
_COLS = ["A","B","C","D","E","F","G"]

_HEADERS = [
    "File Name",
    "Status",
    "Elements Purged",
    "Passes",
    "Size Before (KB)",
    "Size After (KB)",
    "Saved (KB)",
]

_COL_WIDTHS = [38, 10, 17, 8, 17, 16, 12]

def export_excel(results, out_path):
    """
    Write results list to an .xlsx file at out_path.
    Uses only stdlib (zipfile, re, os) — safe for IronPython.
    Returns (True, "") on success or (False, error_message) on failure.
    """

    # ── [Content_Types].xml ─────────────────────────────────────────────────
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml"  ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml"'
        ' ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml"'
        ' ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml"'
        ' ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '</Types>'
    )

    # ── _rels/.rels ──────────────────────────────────────────────────────────
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"'
        ' Target="xl/workbook.xml"/>'
        '</Relationships>'
    )

    # ── xl/_rels/workbook.xml.rels ───────────────────────────────────────────
    wb_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"'
        ' Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles"'
        ' Target="styles.xml"/>'
        '</Relationships>'
    )

    # ── xl/workbook.xml ──────────────────────────────────────────────────────
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
        ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets>'
        '<sheet name="Purge Log" sheetId="1" r:id="rId1"/>'
        '</sheets>'
        '</workbook>'
    )

    # ── xl/styles.xml ────────────────────────────────────────────────────────
    # Style index 0 = default, Style index 1 = header (bold, pink fill, white text)
    styles = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2">'
          '<font><sz val="10"/><name val="Segoe UI"/></font>'                          # 0 normal
          '<font><b/><sz val="10"/><name val="Segoe UI"/>'                            # 1 header bold
            '<color rgb="FF333333"/>'
          '</font>'
        '</fonts>'
        '<fills count="3">'
          '<fill><patternFill patternType="none"/></fill>'                             # 0 required
          '<fill><patternFill patternType="gray125"/></fill>'                          # 1 required
          '<fill><patternFill patternType="solid">'                                    # 2 gold header
            '<fgColor rgb="FFF0CC88"/>'
          '</patternFill></fill>'
        '</fills>'
        '<borders count="2">'
          '<border><left/><right/><top/><bottom/><diagonal/></border>'                 # 0 no border
          '<border>'                                                                    # 1 thin all
            '<left   style="thin"><color rgb="FFD4B87A"/></left>'
            '<right  style="thin"><color rgb="FFD4B87A"/></right>'
            '<top    style="thin"><color rgb="FFD4B87A"/></top>'
            '<bottom style="thin"><color rgb="FFD4B87A"/></bottom>'
            '<diagonal/>'
          '</border>'
        '</borders>'
        '<cellStyleXfs count="1">'
          '<xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>'
        '</cellStyleXfs>'
        '<cellXfs count="3">'
          '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0">'             # 0 data cell
            '<alignment wrapText="0"/>'
          '</xf>'
          '<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0">'             # 1 header cell
            '<alignment horizontal="center" vertical="center"/>'
          '</xf>'
          '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0">'             # 2 number cell
            '<alignment horizontal="right"/>'
          '</xf>'
        '</cellXfs>'
        '</styleSheet>'
    )

    # ── xl/worksheets/sheet1.xml ─────────────────────────────────────────────
    # Column widths
    col_defs = "".join(
        '<col min="{c}" max="{c}" width="{w}" customWidth="1"/>'.format(
            c=i+1, w=_COL_WIDTHS[i])
        for i in range(len(_COLS))
    )

    # Header row (row 1) — style_id=1 (bold, pink bg)
    header_cells = "".join(
        _xlsx_cell(_COLS[i], 1, _HEADERS[i], style_id=1)
        for i in range(len(_HEADERS))
    )
    rows_xml = '<row r="1" ht="18" customHeight="1">{}</row>'.format(header_cells)

    # Data rows
    numeric_cols = {2, 3, 4, 5, 6}   # 0-based indices of numeric columns
    for row_idx, r in enumerate(results):
        saved_kb = r.get("size_before", 0) - r.get("size_after", 0)
        values = [
            r.get("file", ""),
            r.get("status", ""),
            r.get("purged_count", 0),
            r.get("passes", 0),
            r.get("size_before", 0),
            r.get("size_after", 0),
            saved_kb,
            # Time and Path removed per user request
        ]
        excel_row = row_idx + 2   # 1-indexed, header is row 1
        cells = "".join(
            _xlsx_cell(_COLS[i], excel_row, values[i],
                       style_id=2 if i in numeric_cols else 0)
            for i in range(len(_COLS))
        )
        rows_xml += '<row r="{}">{}</row>'.format(excel_row, cells)

    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetViews><sheetView workbookViewId="0" showGridLines="1"/></sheetViews>'
        '<sheetFormatPr defaultRowHeight="15"/>'
        '<cols>{}</cols>'
        '<sheetData>{}</sheetData>'
        '<sheetProtection/>'
        '</worksheet>'
    ).format(col_defs, rows_xml)

    # ── Assemble ZIP (.xlsx) ──────────────────────────────────────────────────
    try:
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("[Content_Types].xml",         content_types)
            zf.writestr("_rels/.rels",                  rels)
            zf.writestr("xl/workbook.xml",              workbook)
            zf.writestr("xl/_rels/workbook.xml.rels",   wb_rels)
            zf.writestr("xl/styles.xml",                styles)
            zf.writestr("xl/worksheets/sheet1.xml",     sheet)
        return True, ""
    except Exception as ex:
        return False, str(ex)


# ===========================================================================
#  WPF UI Helpers
# ===========================================================================
def _tb(text, size=11, bold=False, color=None, font=None, wrap=False):
    t = TextBlock()
    t.Text       = text
    t.FontSize   = size
    t.FontFamily = font or FONT_UI
    t.FontWeight = FontWeights.SemiBold if bold else FontWeights.Normal
    t.Foreground = SolidColorBrush(color if color else CLR_TEXT)
    if wrap:
        t.TextWrapping = System.Windows.TextWrapping.Wrap
    return t

def _section_lbl(text):
    t = TextBlock()
    t.Text       = text.upper()
    t.FontSize   = 9
    t.FontFamily = FONT_UI
    t.FontWeight = FontWeights.SemiBold
    t.Foreground = SolidColorBrush(CLR_ACCENT)
    t.Margin     = Thickness(0, 0, 0, 5)
    return t

def _card(child, margin=None):
    b = Border()
    b.Child           = child
    b.Background      = SolidColorBrush(CLR_CARD)
    b.BorderBrush     = SolidColorBrush(CLR_BORDER)
    b.BorderThickness = Thickness(1)
    b.CornerRadius    = System.Windows.CornerRadius(4)
    b.Padding         = Thickness(12)
    if margin:
        b.Margin = Thickness(*margin) if isinstance(margin, tuple) else margin
    return b

def _btn(text, bg, fg, bdr=None, h=30, w=None, bold=False, size=11):
    b = Button()
    b.Content         = text
    b.Height          = h
    b.FontSize        = size
    b.FontFamily      = FONT_UI
    b.FontWeight      = FontWeights.SemiBold if bold else FontWeights.Normal
    b.Background      = SolidColorBrush(bg)
    b.Foreground      = SolidColorBrush(fg)
    b.BorderBrush     = SolidColorBrush(bdr if bdr else CLR_BORDER)
    b.BorderThickness = Thickness(1)
    b.Padding         = Thickness(10, 0, 10, 0)
    b.Cursor          = System.Windows.Input.Cursors.Hand
    if w:
        b.Width = w
    return b

def _chk(label, checked=False):
    c = CheckBox()
    c.Content           = label
    c.FontSize          = 11
    c.FontFamily        = FONT_UI
    c.Foreground        = SolidColorBrush(CLR_TEXT)
    c.IsChecked         = checked
    c.VerticalAlignment = VerticalAlignment.Center
    return c


# ===========================================================================
#  Main WPF Window
# ===========================================================================
class PurgeFamiliesWindow(Window):

    def __init__(self):
        self.Title      = "Batch Purge Families"
        self.Width      = 820
        self.Height     = 700
        self.MinWidth   = 680
        self.MinHeight  = 560
        self.WindowStartupLocation = System.Windows.WindowStartupLocation.CenterScreen
        self.ResizeMode = System.Windows.ResizeMode.CanResize
        self.Background = SolidColorBrush(CLR_BG)
        self.family_files = []
        self.results      = []
        self.Content = self._build_root()

    # -----------------------------------------------------------------------
    def _build_root(self):
        root = DockPanel()
        root.LastChildFill = True

        header = self._make_header()
        DockPanel.SetDock(header, System.Windows.Controls.Dock.Top)
        root.Children.Add(header)

        footer = self._make_footer()
        DockPanel.SetDock(footer, System.Windows.Controls.Dock.Bottom)
        root.Children.Add(footer)

        sv = ScrollViewer()
        sv.VerticalScrollBarVisibility   = ScrollBarVisibility.Auto
        sv.HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled
        sv.Content = self._make_body()
        root.Children.Add(sv)
        return root

    # -----------------------------------------------------------------------
    #  HEADER — horizontal: [icon] | title + subtitle | NV badge
    # -----------------------------------------------------------------------
    def _make_header(self):
        hdr = Border()
        hdr.Background = SolidColorBrush(CLR_HEADER)
        hdr.Padding    = Thickness(16, 0, 16, 0)

        dp = DockPanel()
        dp.LastChildFill = False

        # RIGHT: NV badge + Help button
        right_sp = StackPanel()
        right_sp.Orientation       = Orientation.Horizontal
        right_sp.VerticalAlignment = VerticalAlignment.Center

        # ? Help button
        btn_help = Button()
        btn_help.Content         = "?"
        btn_help.Width           = 24
        btn_help.Height          = 24
        btn_help.FontSize        = 12
        btn_help.FontWeight      = FontWeights.Bold
        btn_help.FontFamily      = FONT_UI
        btn_help.Background      = SolidColorBrush(_c(212, 168, 80))   # slightly darker gold
        btn_help.Foreground      = SolidColorBrush(CLR_HEADER_TEXT)
        btn_help.BorderBrush     = SolidColorBrush(CLR_ACCENT)
        btn_help.BorderThickness = Thickness(1)
        btn_help.Cursor          = System.Windows.Input.Cursors.Hand
        btn_help.ToolTip         = (
            "1. Browse: select folder containing .rfa families.\n"
            "2. Scan Folder: find all .rfa files (preview list).\n"
            "3. Start Purge: open each file, delete unused elements,\n"
            "   overwrite-save, then close — automatically.\n"
            "4. Delete backups: removes *.0001.rfa backup copies\n"
            "   that Revit creates on every save.\n"
            "5. Export Excel: saves a result table (file, status,\n"
            "   elements purged, size before/after) in the folder."
        )
        btn_help.Click += self.on_help
        btn_help.Margin = Thickness(0, 0, 12, 0)
        right_sp.Children.Add(btn_help)

        # NV badge (vertical stack)
        badge = StackPanel()
        badge.Orientation         = Orientation.Vertical
        badge.VerticalAlignment   = VerticalAlignment.Center
        badge.HorizontalAlignment = HorizontalAlignment.Right

        b1 = TextBlock()
        b1.Text                = "NV"
        b1.FontSize            = 15
        b1.FontWeight          = FontWeights.Bold
        b1.FontFamily          = FONT_UI
        b1.Foreground          = SolidColorBrush(CLR_ACCENT)
        b1.HorizontalAlignment = HorizontalAlignment.Right
        badge.Children.Add(b1)

        b2 = TextBlock()
        b2.Text                = "Revit 2024 / 2025"
        b2.FontSize            = 9
        b2.FontFamily          = FONT_UI
        b2.Foreground          = SolidColorBrush(CLR_HEADER_SUB)
        b2.HorizontalAlignment = HorizontalAlignment.Right
        badge.Children.Add(b2)

        right_sp.Children.Add(badge)

        DockPanel.SetDock(right_sp, System.Windows.Controls.Dock.Right)
        dp.Children.Add(right_sp)

        # CENTER / LEFT: title + subtitle (fills remaining space)
        center = StackPanel()
        center.Orientation       = Orientation.Vertical
        center.VerticalAlignment = VerticalAlignment.Center
        center.Margin            = Thickness(0, 12, 0, 12)

        t1 = TextBlock()
        t1.Text       = "Batch Purge Families"
        t1.FontSize   = 17
        t1.FontWeight = FontWeights.Bold
        t1.FontFamily = FONT_UI
        t1.Foreground = SolidColorBrush(CLR_HEADER_TEXT)
        center.Children.Add(t1)

        t2 = TextBlock()
        t2.Text       = "Purge unused elements in all .rfa files inside a folder"
        t2.FontSize   = 10
        t2.FontFamily = FONT_UI
        t2.Foreground = SolidColorBrush(CLR_HEADER_SUB)
        t2.Margin     = Thickness(0, 2, 0, 0)
        center.Children.Add(t2)

        DockPanel.SetDock(center, System.Windows.Controls.Dock.Left)
        dp.Children.Add(center)

        hdr.Child = dp
        return hdr

    # -----------------------------------------------------------------------
    #  FOOTER — status (left) | Export Excel + Close (right)
    # -----------------------------------------------------------------------
    def _make_footer(self):
        ftr = Border()
        ftr.Background      = SolidColorBrush(CLR_FOOTER)
        ftr.BorderBrush     = SolidColorBrush(CLR_BORDER)
        ftr.BorderThickness = Thickness(0, 1, 0, 0)
        ftr.Padding         = Thickness(14, 8, 14, 8)
        ftr.CornerRadius    = System.Windows.CornerRadius(0, 0, 3, 3)

        dp = DockPanel()
        dp.LastChildFill = True

        btn_row = StackPanel()
        btn_row.Orientation = Orientation.Horizontal

        self.btn_export = _btn("Export Excel Log", CLR_CARD, CLR_TEXT)
        self.btn_export.Margin    = Thickness(0, 0, 8, 0)
        self.btn_export.IsEnabled = False
        self.btn_export.Click    += self.on_export
        btn_row.Children.Add(self.btn_export)

        btn_close = _btn("Close", CLR_CARD, CLR_TEXT)
        btn_close.Click += lambda s, e: self.Close()
        btn_row.Children.Add(btn_close)

        DockPanel.SetDock(btn_row, System.Windows.Controls.Dock.Right)
        dp.Children.Add(btn_row)

        self.lbl_status = TextBlock()
        self.lbl_status.Text              = "Ready."
        self.lbl_status.FontSize          = 10
        self.lbl_status.FontFamily        = FONT_UI
        self.lbl_status.Foreground        = SolidColorBrush(CLR_MUTED)
        self.lbl_status.VerticalAlignment = VerticalAlignment.Center
        self.lbl_status.TextTrimming      = System.Windows.TextTrimming.CharacterEllipsis
        dp.Children.Add(self.lbl_status)

        ftr.Child = dp
        return ftr

    # -----------------------------------------------------------------------
    #  BODY — stacked cards
    # -----------------------------------------------------------------------
    def _make_body(self):
        body = StackPanel()
        body.Orientation = Orientation.Vertical
        body.Margin      = Thickness(15)
        body.Children.Add(self._make_card_folder())
        body.Children.Add(self._make_card_scan())
        body.Children.Add(self._make_card_progress())
        body.Children.Add(self._make_card_actions())
        return body

    # ── CARD 1: Folder ──────────────────────────────────────────────────────
    def _make_card_folder(self):
        sp = StackPanel()
        sp.Orientation = Orientation.Vertical
        sp.Children.Add(_section_lbl("Folder"))

        folder_row = DockPanel()
        folder_row.LastChildFill = True
        folder_row.Margin        = Thickness(0, 0, 0, 10)

        self.btn_browse = _btn("Browse...", CLR_CARD, CLR_TEXT, w=84)
        self.btn_browse.Click += self.on_browse
        DockPanel.SetDock(self.btn_browse, System.Windows.Controls.Dock.Right)
        folder_row.Children.Add(self.btn_browse)

        self.txt_folder = TextBox()
        self.txt_folder.IsReadOnly               = True
        self.txt_folder.Text                     = "No folder selected..."
        self.txt_folder.FontSize                 = 11
        self.txt_folder.FontFamily               = FONT_UI
        self.txt_folder.Foreground               = SolidColorBrush(CLR_MUTED)
        self.txt_folder.Background               = SolidColorBrush(_c(250, 244, 247))
        self.txt_folder.BorderBrush              = SolidColorBrush(CLR_BORDER)
        self.txt_folder.BorderThickness          = Thickness(1)
        self.txt_folder.Padding                  = Thickness(6, 0, 6, 0)
        self.txt_folder.Height                   = 28
        self.txt_folder.Margin                   = Thickness(0, 0, 6, 0)
        self.txt_folder.VerticalContentAlignment = VerticalAlignment.Center
        folder_row.Children.Add(self.txt_folder)
        sp.Children.Add(folder_row)

        opt = StackPanel()
        opt.Orientation = Orientation.Horizontal

        self.chk_recursive = _chk("Include subfolders", checked=True)
        self.chk_recursive.Margin = Thickness(0, 0, 20, 0)
        opt.Children.Add(self.chk_recursive)

        lbl_passes = _tb("Max purge passes:", color=CLR_TEXT)
        lbl_passes.VerticalAlignment = VerticalAlignment.Center
        lbl_passes.Margin            = Thickness(0, 0, 6, 0)
        opt.Children.Add(lbl_passes)

        self.txt_passes = TextBox()
        self.txt_passes.Text                     = "10"
        self.txt_passes.FontSize                 = 11
        self.txt_passes.Width                    = 38
        self.txt_passes.Height                   = 26
        self.txt_passes.TextAlignment            = System.Windows.TextAlignment.Center
        self.txt_passes.BorderBrush              = SolidColorBrush(CLR_BORDER)
        self.txt_passes.BorderThickness          = Thickness(1)
        self.txt_passes.VerticalContentAlignment = VerticalAlignment.Center
        self.txt_passes.Margin                   = Thickness(0, 0, 24, 0)
        opt.Children.Add(self.txt_passes)

        self.chk_delete_backups = _chk("Delete backup files (.0001, .0002...)", checked=False)
        self.chk_delete_backups.Margin = Thickness(0, 0, 24, 0)
        opt.Children.Add(self.chk_delete_backups)

        self.chk_log = _chk("Export Excel log when done", checked=False)
        opt.Children.Add(self.chk_log)

        sp.Children.Add(opt)
        return _card(sp, margin=(0, 0, 0, 10))

    # ── CARD 2: Scan & Preview ──────────────────────────────────────────────
    def _make_card_scan(self):
        sp = StackPanel()
        sp.Orientation = Orientation.Vertical

        scan_row = DockPanel()
        scan_row.LastChildFill = False
        scan_row.Margin        = Thickness(0, 0, 0, 10)

        self.btn_scan = _btn("Scan Folder", CLR_CARD, CLR_TEXT, w=110)
        self.btn_scan.Click += self.on_scan
        DockPanel.SetDock(self.btn_scan, System.Windows.Controls.Dock.Left)
        scan_row.Children.Add(self.btn_scan)

        count_sp = StackPanel()
        count_sp.Orientation       = Orientation.Horizontal
        count_sp.VerticalAlignment = VerticalAlignment.Center
        count_sp.Margin            = Thickness(12, 0, 0, 0)

        lbl_found = _tb("Files found: ", color=CLR_MUTED)
        lbl_found.VerticalAlignment = VerticalAlignment.Center
        count_sp.Children.Add(lbl_found)

        self.lbl_count = TextBlock()
        self.lbl_count.Text              = u"\u2014"
        self.lbl_count.FontSize          = 15
        self.lbl_count.FontWeight        = FontWeights.Bold
        self.lbl_count.FontFamily        = FONT_UI
        self.lbl_count.Foreground        = SolidColorBrush(CLR_HEADER)
        self.lbl_count.VerticalAlignment = VerticalAlignment.Center
        count_sp.Children.Add(self.lbl_count)

        scan_row.Children.Add(count_sp)
        sp.Children.Add(scan_row)

        sp.Children.Add(_section_lbl("Preview / Results"))

        self.list_files = ListBox()
        self.list_files.Height                     = 200
        self.list_files.FontSize                   = 11
        self.list_files.FontFamily                 = FONT_MONO
        self.list_files.Foreground                 = SolidColorBrush(CLR_TEXT)
        self.list_files.Background                 = SolidColorBrush(CLR_LIST_BG)
        self.list_files.BorderBrush                = SolidColorBrush(CLR_BORDER)
        self.list_files.BorderThickness            = Thickness(1)
        self.list_files.SelectionMode              = SelectionMode.Extended
        self.list_files.HorizontalContentAlignment = HorizontalAlignment.Left
        sp.Children.Add(self.list_files)

        return _card(sp, margin=(0, 0, 0, 10))

    # ── CARD 3: Progress ────────────────────────────────────────────────────
    def _make_card_progress(self):
        sp = StackPanel()
        sp.Orientation = Orientation.Vertical
        sp.Children.Add(_section_lbl("Progress"))

        prog_row = DockPanel()
        prog_row.LastChildFill = True
        prog_row.Margin        = Thickness(0, 0, 0, 8)

        self.lbl_prog_text = TextBlock()
        self.lbl_prog_text.Text              = "0 / 0"
        self.lbl_prog_text.FontSize          = 10
        self.lbl_prog_text.FontFamily        = FONT_UI
        self.lbl_prog_text.Foreground        = SolidColorBrush(CLR_MUTED)
        self.lbl_prog_text.Width             = 50
        self.lbl_prog_text.TextAlignment     = System.Windows.TextAlignment.Right
        self.lbl_prog_text.VerticalAlignment = VerticalAlignment.Center
        DockPanel.SetDock(self.lbl_prog_text, System.Windows.Controls.Dock.Right)
        prog_row.Children.Add(self.lbl_prog_text)

        self.progress = ProgressBar()
        self.progress.Height          = 12
        self.progress.Minimum         = 0
        self.progress.Maximum         = 100
        self.progress.Value           = 0
        self.progress.Foreground      = SolidColorBrush(CLR_HEADER)
        self.progress.Background      = SolidColorBrush(_c(225, 205, 215))
        self.progress.BorderThickness = Thickness(0)
        self.progress.Margin          = Thickness(0, 0, 10, 0)
        prog_row.Children.Add(self.progress)
        sp.Children.Add(prog_row)

        self.summary_border = Border()
        self.summary_border.Background      = SolidColorBrush(CLR_ALT)
        self.summary_border.BorderBrush     = SolidColorBrush(CLR_BORDER)
        self.summary_border.BorderThickness = Thickness(1)
        self.summary_border.CornerRadius    = System.Windows.CornerRadius(3)
        self.summary_border.Padding         = Thickness(10, 7, 10, 7)
        self.summary_border.Visibility      = Visibility.Collapsed

        self.lbl_summary = TextBlock()
        self.lbl_summary.FontSize     = 11
        self.lbl_summary.FontFamily   = FONT_UI
        self.lbl_summary.Foreground   = SolidColorBrush(CLR_ACCENT)
        self.lbl_summary.TextWrapping = System.Windows.TextWrapping.Wrap
        self.summary_border.Child = self.lbl_summary
        sp.Children.Add(self.summary_border)

        return _card(sp, margin=(0, 0, 0, 10))

    # ── CARD 4: Run ─────────────────────────────────────────────────────────
    def _make_card_actions(self):
        dp = DockPanel()
        dp.LastChildFill = False

        self.btn_run = _btn(
            u"\u25b6  Start Purge",
            CLR_APPLY_BG, CLR_APPLY_TEXT,
            bdr=CLR_APPLY_BDR, h=34, bold=True, size=13
        )
        self.btn_run.Padding   = Thickness(22, 0, 22, 0)
        self.btn_run.IsEnabled = False
        self.btn_run.Click    += self.on_run
        DockPanel.SetDock(self.btn_run, System.Windows.Controls.Dock.Left)
        dp.Children.Add(self.btn_run)

        return _card(dp, margin=(0, 0, 0, 4))

    # =======================================================================
    #  Event Handlers
    # =======================================================================

    def on_help(self, sender, e):
        MessageBox.Show(
            "BATCH PURGE FAMILIES — Quick Guide\n"
            "\n"
            "1. Browse       Select the folder containing .rfa families.\n"
            "2. Scan Folder  Find all .rfa files; preview list with sizes.\n"
            "3. Start Purge  Opens each file, deletes all unused elements,\n"
            "                saves over the original, then closes it.\n"
            "\n"
            "OPTIONS\n"
            "  Include subfolders   Also scan nested folders recursively.\n"
            "  Max purge passes     Repeat purge up to N times per file\n"
            "                       (some elements only appear after others\n"
            "                       are deleted — more passes = cleaner).\n"
            "  Delete backup files  Remove *.0001.rfa / *.0001.rvt copies\n"
            "                       that Revit auto-creates on every save.\n"
            "  Export Excel log     Save a result table (.xlsx) in the\n"
            "                       target folder after purge completes.\n"
            "\n"
            "NOTE  Files are overwritten in place. Back up first if needed.",
            "Help — Batch Purge Families",
            MessageBoxButton.OK, MessageBoxImage.Information)

    def on_browse(self, sender, e):
        dlg = FolderBrowserDialog()
        dlg.Description       = "Select folder containing .rfa files to purge"
        dlg.ShowNewFolderButton = False
        if dlg.ShowDialog() == FDResult.OK:
            self.txt_folder.Text      = dlg.SelectedPath
            self.txt_folder.Foreground = SolidColorBrush(CLR_TEXT)
            self.family_files          = []
            self.list_files.Items.Clear()
            self.lbl_count.Text             = u"\u2014"
            self.btn_run.IsEnabled          = False
            self.summary_border.Visibility  = Visibility.Collapsed
            self.lbl_status.Text            = "Folder selected. Click Scan to find files."

    def on_scan(self, sender, e):
        folder = self.txt_folder.Text
        if not folder or not os.path.isdir(folder):
            MessageBox.Show("Please select a valid folder first.",
                            "Notice", MessageBoxButton.OK, MessageBoxImage.Warning)
            return

        self.family_files = []
        if self.chk_recursive.IsChecked:
            for root, dirs, files in os.walk(folder):
                for f in files:
                    if f.lower().endswith(".rfa"):
                        self.family_files.append(os.path.join(root, f))
        else:
            # Use os.listdir + isfile to avoid picking up subfolder names
            for f in os.listdir(folder):
                fp = os.path.join(folder, f)
                if os.path.isfile(fp) and f.lower().endswith(".rfa"):
                    self.family_files.append(fp)

        self.family_files.sort()
        self.list_files.Items.Clear()

        for fp in self.family_files:
            size_kb = os.path.getsize(fp) // 1024
            rel     = os.path.relpath(fp, folder)
            item    = ListBoxItem()
            item.Content = "  [{:>7} KB]  {}".format(size_kb, rel)
            item.Padding = Thickness(2, 1, 2, 1)
            self.list_files.Items.Add(item)

        count = len(self.family_files)
        self.lbl_count.Text            = str(count)
        self.btn_run.IsEnabled         = count > 0
        self.summary_border.Visibility = Visibility.Collapsed

        if count == 0:
            self.lbl_status.Text = "No .rfa files found in this folder."
        else:
            self.lbl_status.Text = "Found {} .rfa file(s). Click 'Start Purge' to continue.".format(count)

    def on_run(self, sender, e):
        if not self.family_files:
            return

        confirm = MessageBox.Show(
            "About to purge and OVERWRITE {} .rfa file(s).\n\nAre you sure?".format(
                len(self.family_files)),
            "Confirm", MessageBoxButton.YesNo, MessageBoxImage.Warning)
        if confirm != MessageBoxResult.Yes:
            return

        self.btn_run.IsEnabled    = False
        self.btn_scan.IsEnabled   = False
        self.btn_export.IsEnabled = False
        self.summary_border.Visibility = Visibility.Collapsed
        self.results = []

        try:
            max_passes = max(1, min(20, int(self.txt_passes.Text.strip())))
        except:
            max_passes = 5

        total     = len(self.family_files)
        folder    = self.txt_folder.Text
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        self.progress.Maximum = total
        self.progress.Value   = 0

        # Process each .rfa
        for idx, fp in enumerate(self.family_files):
            fname = os.path.basename(fp)
            self.lbl_status.Text    = "Processing ({}/{}): {}".format(idx+1, total, fname)
            self.lbl_prog_text.Text = "{} / {}".format(idx+1, total)
            WFApp.DoEvents()

            result = process_family_file(fp, max_passes)
            result["time"] = datetime.datetime.now().strftime("%H:%M:%S")
            self.results.append(result)

            rel  = os.path.relpath(fp, folder)
            item = self.list_files.Items[idx]
            if result["status"] == "Success":
                saved = result["size_before"] - result["size_after"]
                item.Content = (
                    u"  \u2714  [{}->{} KB  \u2212{} KB"
                    u"  |  {} elements  |  {} passes]  {}"
                ).format(result["size_before"], result["size_after"], saved,
                         result["purged_count"], result["passes"], rel)
                item.Foreground = SolidColorBrush(CLR_APPLY_TEXT)
            else:
                item.Content = u"  \u2718  [ERROR: {}]  {}".format(
                    result["error"][:50], rel)
                item.Foreground = SolidColorBrush(_c(180, 50, 50))

            self.progress.Value = idx + 1
            WFApp.DoEvents()

        # Delete backup files if requested
        deleted_count = 0
        freed_bytes   = 0
        failed_backups = []
        if self.chk_delete_backups.IsChecked:
            self.lbl_status.Text = "Deleting backup files (*.0001.rfa / *.0001.rvt)..."
            WFApp.DoEvents()
            deleted_count, freed_bytes, failed_backups = delete_backup_files(
                folder, bool(self.chk_recursive.IsChecked))

        # Summary
        success      = sum(1 for r in self.results if r["status"] == "Success")
        errors       = total - success
        total_purged = sum(r["purged_count"] for r in self.results)

        summary_parts = [
            u"\u2714  Done!    Success: {}    Errors: {}    "
            u"Total elements purged: {}".format(success, errors, total_purged)
        ]
        if self.chk_delete_backups.IsChecked:
            freed_mb = round(freed_bytes / (1024.0 * 1024.0), 2)
            summary_parts.append(
                "Backup files deleted: {}  ({} MB freed){}".format(
                    deleted_count, freed_mb,
                    "  ({} failed)".format(len(failed_backups)) if failed_backups else ""))

        self.lbl_summary.Text          = "    ".join(summary_parts)
        self.summary_border.Visibility = Visibility.Visible
        self.lbl_status.Text           = "Done — {}/{} succeeded.".format(success, total)
        self.progress.Value            = total
        self.btn_run.IsEnabled         = True
        self.btn_scan.IsEnabled        = True
        self.btn_export.IsEnabled      = True

        # Auto-export Excel log
        if self.chk_log.IsChecked:
            self._export_excel(folder, timestamp, silent=True)

        # Final popup
        popup = [
            "PURGE COMPLETE!",
            "",
            "Success         : {}".format(success),
            "Errors          : {}".format(errors),
            "Elements purged : {}".format(total_purged),
        ]
        if self.chk_delete_backups.IsChecked:
            freed_mb = round(freed_bytes / (1024.0 * 1024.0), 2)
            popup += [
                "",
                "Backup files deleted : {}".format(deleted_count),
                "Disk space freed     : {} MB".format(freed_mb),
            ]
            if failed_backups:
                popup.append("Failed to delete     : {}".format(len(failed_backups)))

        MessageBox.Show("\n".join(popup), "Result",
                        MessageBoxButton.OK, MessageBoxImage.Information)

    def on_export(self, sender, e):
        if not self.results:
            return
        self._export_excel(
            self.txt_folder.Text,
            datetime.datetime.now().strftime("%Y%m%d_%H%M%S"),
            silent=False)

    def _export_excel(self, folder, timestamp, silent=False):
        if not folder or not os.path.isdir(folder):
            MessageBox.Show("Cannot export log: target folder is not valid.",
                            "Error", MessageBoxButton.OK, MessageBoxImage.Error)
            return

        out_path = os.path.join(folder, "purge_log_{}.xlsx".format(timestamp))
        ok, err = export_excel(self.results, out_path)

        if ok:
            self.lbl_status.Text = "Excel log saved: {}".format(os.path.basename(out_path))
            # Always show popup — silent only shortens the message, never hides it
            if silent:
                MessageBox.Show(
                    "Excel log saved:\n{}".format(os.path.basename(out_path)),
                    "Export Complete",
                    MessageBoxButton.OK, MessageBoxImage.Information)
            else:
                MessageBox.Show(
                    "Excel log saved to:\n{}".format(out_path),
                    "Export Complete",
                    MessageBoxButton.OK, MessageBoxImage.Information)
        else:
            MessageBox.Show("Could not export Excel log:\n{}".format(err),
                            "Error", MessageBoxButton.OK, MessageBoxImage.Error)


# ===========================================================================
#  Entry Point
# ===========================================================================
PurgeFamiliesWindow().ShowDialog()