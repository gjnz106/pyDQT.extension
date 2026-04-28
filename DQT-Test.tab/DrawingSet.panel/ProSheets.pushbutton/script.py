# -*- coding: utf-8 -*-
# pyRevit persistent engine
__persistentengine__ = True
"""
ProSheets v3.0  —  Batch Export Sheets & Views (PDF / DWG)
WPF UI rewrite matching NV ColorSplasher design pattern.

Author : Nhat Vu (NV)
"""

# ── Module-level: only stdlib + pyrevit wrapper (no Revit DB types)
# Revit DB imports (ViewSheet, FilteredElementCollector, etc.) trigger
# Revit's graphics regeneration when imported at module level.
# All DB imports are deferred into _load_revit_imports() below.
import clr, json, os

# pyrevit is a thin wrapper — does NOT trigger view regeneration
from pyrevit import revit, script

# System core — lightweight, no Revit involvement
clr.AddReference('System')
import System
import System.IO
import System.Collections.Generic

# doc/uidoc accessed via properties on demand — no module-level access
def _get_doc():
    return revit.doc

def _get_uidoc():
    return revit.uidoc


def _load_revit_imports():
    """
    Import Revit DB types. Deferred so they do NOT run at module parse time.
    Called once at entry point. With __persistentengine__ = True this is a
    no-op on subsequent clicks (types already in IronPython's import cache).
    """
    clr.AddReference('RevitAPI')
    clr.AddReference('RevitAPIUI')
    global FilteredElementCollector, ViewSheet, View, ViewType
    global ViewSheetSet, Transaction, BuiltInParameter, ElementId
    global BuiltInCategory, FamilyInstance, doc, uidoc
    from Autodesk.Revit.DB import (
        FilteredElementCollector, ViewSheet, View, ViewType,
        ViewSheetSet, Transaction, BuiltInParameter, ElementId,
        BuiltInCategory, FamilyInstance,
    )
    doc   = revit.doc
    uidoc = revit.uidoc

    # Resolve BIP string names to enum values now that BuiltInParameter is loaded
    global _BIP_MAP
    for k, name in _BIP_MAP_NAMES.items():
        try:
            _BIP_MAP[k] = getattr(BuiltInParameter, name)
        except Exception:
            pass

# Placeholders — set by _load_revit_imports() before any function uses them
FilteredElementCollector = ViewSheet = View = ViewType = None
ViewSheetSet = Transaction = BuiltInParameter = ElementId = None
BuiltInCategory = FamilyInstance = None
doc = uidoc = None


def _load_wpf_imports():
    """
    Load WPF and heavy .NET assemblies.
    Called once when the tool window is created — NOT at module parse time.
    This is the main trick: PresentationCore/PresentationFramework are large
    assemblies that trigger Revit's rendering pipeline when loaded.
    Deferring them to here means the button click returns instantly and the
    window appears before any heavy loading.
    """
    clr.AddReference('PresentationCore')
    clr.AddReference('PresentationFramework')
    clr.AddReference('WindowsBase')
    clr.AddReference('System.Windows.Forms')

    global Window, Thickness, HorizontalAlignment, VerticalAlignment
    global GridLength, GridUnitType, WindowStartupLocation, TextWrapping, Visibility
    global WPFGrid, StackPanel, TextBlock, TextBox, Button
    global ComboBox, ListBox, Border, ScrollViewer, Label
    global ColumnDefinition, RowDefinition, ScrollBarVisibility
    global Orientation, SelectionMode, CheckBox, RadioButton
    global TabControl, TabItem, DataGrid, DataGridTextColumn
    global DataGridCheckBoxColumn, DataGridTemplateColumn
    global Separator, Canvas, ToggleButton
    global SolidColorBrush, Color, Key
    global ObservableCollection
    global MessageBox, MessageBoxButtons, MessageBoxIcon, DialogResult, FolderBrowserDialog

    from System.Windows import (
        Window, Thickness, HorizontalAlignment, VerticalAlignment,
        GridLength, GridUnitType, WindowStartupLocation, TextWrapping,
        Visibility,
    )
    from System.Windows.Controls import (
        Grid as WPFGrid, StackPanel, TextBlock, TextBox, Button,
        ComboBox, ListBox, Border, ScrollViewer, Label,
        ColumnDefinition, RowDefinition, ScrollBarVisibility,
        Orientation, SelectionMode, CheckBox, RadioButton,
        TabControl, TabItem, DataGrid, DataGridTextColumn,
        DataGridCheckBoxColumn, DataGridTemplateColumn,
        Separator, Canvas,
    )
    from System.Windows.Controls.Primitives import ToggleButton
    from System.Windows.Media import SolidColorBrush, Color
    from System.Windows.Input import Key
    import System.Windows.Data
    from System.Collections.ObjectModel import ObservableCollection
    from System.Windows.Forms import (
        MessageBox, MessageBoxButtons, MessageBoxIcon,
        DialogResult, FolderBrowserDialog,
    )

# Placeholder globals so module-level code that references them doesn't crash
# (they are set properly inside _load_wpf_imports before any Window is created)
Window = None; Thickness = None; SolidColorBrush = None; Color = None
WPFGrid = None; StackPanel = None; TextBlock = None; Button = None
ObservableCollection = None; MessageBox = None; Visibility = None

# =====================================================
# NV BRAND COLORS — initialized after WPF is loaded
# =====================================================
# Placeholders; set by _init_colors() which runs after _load_wpf_imports()
CLR_HEADER = CLR_HEADER_TEXT = CLR_HEADER_SUB = CLR_ACCENT = None
CLR_BG = CLR_CARD = CLR_BORDER = CLR_FOOTER = CLR_TEXT = None
CLR_MUTED = CLR_ALT = CLR_APPLY_BG = CLR_APPLY_BD = CLR_APPLY_FG = None
CLR_ERR = CLR_WARN = CLR_OK = CLR_OK_LIGHT = CLR_PILL = None


def _init_colors():
    """Initialize Color constants after WPF Color type is available."""
    global CLR_HEADER, CLR_HEADER_TEXT, CLR_HEADER_SUB, CLR_ACCENT
    global CLR_BG, CLR_CARD, CLR_BORDER, CLR_FOOTER, CLR_TEXT
    global CLR_MUTED, CLR_ALT, CLR_APPLY_BG, CLR_APPLY_BD, CLR_APPLY_FG
    global CLR_ERR, CLR_WARN, CLR_OK, CLR_OK_LIGHT, CLR_PILL
    CLR_HEADER      = Color.FromRgb(240, 204, 136)
    CLR_HEADER_TEXT = Color.FromRgb( 51,  51,  51)
    CLR_HEADER_SUB  = Color.FromRgb(102, 102, 102)
    CLR_ACCENT      = Color.FromRgb( 93,  78,  55)
    CLR_BG          = Color.FromRgb(254, 248, 231)
    CLR_CARD        = Color.FromRgb(255, 255, 255)
    CLR_BORDER      = Color.FromRgb(212, 184, 122)
    CLR_FOOTER      = Color.FromRgb(245, 240, 224)
    CLR_TEXT        = Color.FromRgb( 51,  51,  51)
    CLR_MUTED       = Color.FromRgb(153, 153, 153)
    CLR_ALT         = Color.FromRgb(255, 248, 238)
    CLR_APPLY_BG    = Color.FromRgb(200, 230, 201)
    CLR_APPLY_BD    = Color.FromRgb(129, 199, 132)
    CLR_APPLY_FG    = Color.FromRgb( 46, 125,  50)
    CLR_ERR         = Color.FromRgb(192,  57,  43)
    CLR_WARN        = Color.FromRgb(230, 160,  20)
    CLR_OK          = Color.FromRgb( 46, 125,  50)
    CLR_OK_LIGHT    = Color.FromRgb(200, 230, 201)
    CLR_PILL        = Color.FromRgb(240, 237, 225)

# =====================================================
# CONSTANTS
# =====================================================
TOOL_NAME    = u'ProSheets'
TOOL_VER     = u'v3.0'
TOOL_AUTHOR  = u'Nhat Vu (NV)'

CUSTOM_PARAM_NAME = u'Custom File Name'

PARAM_OPTIONS = [
    (u'Sheet Number',   u'__bip_SHEET_NUMBER__'),
    (u'Sheet Name',     u'__bip_SHEET_NAME__'),
    (u'Revision',       u'__bip_REVISION__'),
    (u'Sheet Size',     u'Sheet Size'),
    (u'Drawn By',       u'__bip_DRAWN_BY__'),
    (u'Checked By',     u'__bip_CHECKED_BY__'),
    (u'Designed By',    u'__bip_DESIGNED_BY__'),
    (u'Approved By',    u'__bip_APPROVED_BY__'),
    (u'Project Name',   u'__bip_PROJECT_NAME__'),
    (u'Project Number', u'__bip_PROJECT_NUMBER__'),
]
SEP_OPTIONS = [
    (u'_  Underscore', u'_'),
    (u'-  Dash',       u'-'),
    (u'.  Dot',        u'.'),
    (u'   Space',      u' '),
    (u'(none)',        u''),
]
# _BIP_MAP stores string BIP names — resolved to actual enum values
# inside _load_revit_imports() after BuiltInParameter is available.
_BIP_MAP_NAMES = {
    u'__bip_SHEET_NUMBER__'         : u'SHEET_NUMBER',
    u'__bip_SHEET_NAME__'           : u'SHEET_NAME',
    u'__bip_REVISION__'             : u'SHEET_CURRENT_REVISION',
    u'__bip_DRAWN_BY__'             : u'SHEET_DRAWN_BY',
    u'__bip_CHECKED_BY__'           : u'SHEET_CHECKED_BY',
    u'__bip_DESIGNED_BY__'          : u'SHEET_DESIGNED_BY',
    u'__bip_APPROVED_BY__'          : u'SHEET_APPROVED_BY',
    u'__bip_PROJECT_NAME__'         : u'PROJECT_NAME',
    u'__bip_PROJECT_NUMBER__'       : u'PROJECT_NUMBER',
    u'__bip_PROJECT_ADDRESS__'      : u'PROJECT_ADDRESS',
    u'__bip_PROJECT_STATUS__'       : u'PROJECT_STATUS',
    u'__bip_CLIENT_NAME__'          : u'CLIENT_NAME',
    u'__bip_PROJECT_AUTHOR__'       : u'PROJECT_AUTHOR',
    u'__bip_BUILDING_NAME__'        : u'BUILDING_NAME',
    u'__bip_ORGANIZATION_NAME__'    : u'ORGANIZATION_NAME',
    u'__bip_ORGANIZATION_DESCRIPTION__': u'ORGANIZATION_DESCRIPTION',
    u'__bip_PROJECT_ISSUE_DATE__'       : u'PROJECT_ISSUE_DATE',
}
_BIP_MAP = {}   # filled by _load_revit_imports()


# =====================================================
# WPF HELPER FACTORIES  (pattern from ColorSplasher)
# =====================================================
def _row(grid, h):
    rd = RowDefinition(); rd.Height = h; grid.RowDefinitions.Add(rd)

def _col(grid, w):
    cd = ColumnDefinition(); cd.Width = w; grid.ColumnDefinitions.Add(cd)

def _tb(text, size=11, bold=False, color=None, wrap=False, margin=None):
    t = TextBlock()
    t.Text = text
    t.FontSize = size
    if bold:
        t.FontWeight = System.Windows.FontWeights.Bold
    if color:
        t.Foreground = SolidColorBrush(color)
    if wrap:
        t.TextWrapping = TextWrapping.Wrap
    if margin:
        t.Margin = margin
    return t

def _section_lbl(text):
    """UPPERCASE section label — NV accent bold 11px"""
    l = TextBlock()
    l.Text = text
    l.FontSize = 11
    l.FontWeight = System.Windows.FontWeights.Bold
    l.Foreground = SolidColorBrush(CLR_ACCENT)
    l.Margin = Thickness(0, 0, 0, 5)
    return l

def _card(corner=4, padding=12):
    """White card with gold border — Pattern 2"""
    b = Border()
    b.Background       = SolidColorBrush(CLR_CARD)
    b.BorderBrush      = SolidColorBrush(CLR_BORDER)
    b.BorderThickness  = Thickness(1)
    b.CornerRadius     = System.Windows.CornerRadius(corner)
    b.Padding          = Thickness(padding)
    return b

def _make_btn(text, bg=None, fg=None, width=None, height=30, bold=False, font_size=11):
    """Standard NV button — white bg, gold border, dark text"""
    b = Button()
    b.Content    = text
    b.Height     = height
    b.FontSize   = font_size
    b.FontWeight = (System.Windows.FontWeights.Bold if bold
                    else System.Windows.FontWeights.SemiBold)
    b.Background  = SolidColorBrush(bg  if bg  else CLR_CARD)
    b.Foreground  = SolidColorBrush(fg  if fg  else CLR_TEXT)
    b.BorderBrush = SolidColorBrush(CLR_BORDER)
    b.Padding     = Thickness(10, 0, 10, 0)
    if width:
        b.Width = width
    return b

def _apply_btn(text=u'Apply', width=130, height=34):
    """Green apply button — primary action"""
    b = Button()
    b.Content         = text
    b.Width           = width
    b.Height          = height
    b.FontSize        = 13
    b.FontWeight      = System.Windows.FontWeights.Bold
    b.Background      = SolidColorBrush(CLR_APPLY_BG)
    b.Foreground      = SolidColorBrush(CLR_APPLY_FG)
    b.BorderBrush     = SolidColorBrush(CLR_APPLY_BD)
    b.BorderThickness = Thickness(1)
    b.Padding         = Thickness(14, 0, 14, 0)
    return b

def _sep_v():
    """Vertical separator"""
    s = Separator()
    s.Margin = Thickness(6, 2, 6, 2)
    return s

def _header_block(title, subtitle):
    """Pattern 1 — Gold header with NV badge"""
    hdr = Border()
    hdr.Background   = SolidColorBrush(CLR_HEADER)
    hdr.Padding      = Thickness(14, 10, 14, 10)
    hdr.CornerRadius = System.Windows.CornerRadius(5)
    hdr.Margin       = Thickness(12, 12, 12, 0)

    hg = WPFGrid()
    _col(hg, GridLength(1, GridUnitType.Star))
    _col(hg, GridLength.Auto)

    hs = StackPanel()
    t1 = TextBlock(); t1.Text = title
    t1.FontSize = 20; t1.FontWeight = System.Windows.FontWeights.Bold
    t1.Foreground = SolidColorBrush(CLR_HEADER_TEXT)
    t2 = TextBlock(); t2.Text = subtitle
    t2.FontSize = 11; t2.Foreground = SolidColorBrush(CLR_HEADER_SUB)
    t2.Margin = Thickness(0, 3, 0, 0)
    hs.Children.Add(t1); hs.Children.Add(t2)
    WPFGrid.SetColumn(hs, 0); hg.Children.Add(hs)

    badge = StackPanel()
    badge.VerticalAlignment   = VerticalAlignment.Center
    badge.HorizontalAlignment = HorizontalAlignment.Right
    b1 = TextBlock(); b1.Text = u'NV'
    b1.FontSize = 14; b1.FontWeight = System.Windows.FontWeights.Bold
    b1.Foreground = SolidColorBrush(CLR_ACCENT)
    b1.HorizontalAlignment = HorizontalAlignment.Right
    b2 = TextBlock(); b2.Text = TOOL_VER
    b2.FontSize = 9; b2.Foreground = SolidColorBrush(CLR_MUTED)
    b2.HorizontalAlignment = HorizontalAlignment.Right
    badge.Children.Add(b1); badge.Children.Add(b2)
    WPFGrid.SetColumn(badge, 1); hg.Children.Add(badge)
    hdr.Child = hg
    return hdr

def _footer_bar():
    """Pattern 3 — Cream footer with tool/author info"""
    fb = Border()
    fb.Background   = SolidColorBrush(CLR_FOOTER)
    fb.CornerRadius = System.Windows.CornerRadius(0, 0, 3, 3)
    fb.Padding      = Thickness(8, 4, 8, 4)

    fbg = WPFGrid()
    _col(fbg, GridLength(1, GridUnitType.Star))
    _col(fbg, GridLength.Auto)

    fbl = TextBlock()
    fbl.Text = u'{0} {1}  |  {2}'.format(TOOL_NAME, TOOL_VER, TOOL_AUTHOR)
    fbl.FontSize = 9; fbl.Foreground = SolidColorBrush(CLR_MUTED)
    WPFGrid.SetColumn(fbl, 0); fbg.Children.Add(fbl)

    fbr = TextBlock()
    try:
        fbr.Text = doc.Title or u''
    except Exception:
        fbr.Text = u''
    fbr.FontSize = 9; fbr.Foreground = SolidColorBrush(CLR_MUTED)
    WPFGrid.SetColumn(fbr, 1); fbg.Children.Add(fbr)
    fb.Child = fbg
    return fb

def safe_string(element, param_name):
    try:
        p = element.LookupParameter(param_name)
        if p is None or not p.HasValue:
            return u''
        v = p.AsString()
        return v if v is not None else u''
    except Exception:
        return u''


def safe_bip(element, bip):
    try:
        p = element.get_Parameter(bip)
        if p is None or not p.HasValue:
            return u''
        v = p.AsString()
        return v if v is not None else u''
    except Exception:
        return u''


def cell_bool(val):
    if val is None:
        return False
    try:
        return bool(val)
    except Exception:
        return False


def rollback_safe(t):
    try:
        if t.HasStarted() and not t.HasEnded():
            t.RollbackIfNotStarted()
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════
#  PARAM RESOLVER
# ═══════════════════════════════════════════════════════════
def resolve_param(elem, key):
    """Resolve a param key to its string value.
    Project Information BIPs must be read from doc.ProjectInformation,
    not from the sheet/view element.
    """
    if key.startswith(u'__custom__'):
        return key[len(u'__custom__'):]
    if key in _BIP_MAP:
        bip = _BIP_MAP[key]
        # Project Info params: try on element first, fallback to ProjectInformation
        val = safe_bip(elem, bip)
        if not val:
            try:
                pi = doc.ProjectInformation
                if pi is not None:
                    val = safe_bip(pi, bip)
            except Exception:
                pass
        return val
    if key.startswith(u'__param__'):
        pname = key[len(u'__param__'):]
        val = safe_string(elem, pname)
        if not val:
            try:
                pi = doc.ProjectInformation
                if pi is not None:
                    val = safe_string(pi, pname)
            except Exception:
                pass
        return val
    return safe_string(elem, key)


def apply_rule(elem, parts):
    """parts: list of (label, key, sep)  — sep of last part ignored."""
    if not parts:
        return u''
    tokens = []
    for i, (label, key, sep) in enumerate(parts):
        val = resolve_param(elem, key)
        if val:
            tokens.append(val)
            if sep and i < len(parts) - 1:
                tokens.append(sep)
    return u''.join(tokens)


def apply_rule_v2(elem, parts):
    # parts: list of (label, key, sep, prefix, suffix)
    # sep of last part is ignored when building the string.
    if not parts:
        return u''
    tokens = []
    n = len(parts)
    for i, part in enumerate(parts):
        key    = part[1]
        sep    = part[2] if len(part) > 2 else u''
        prefix = part[3] if len(part) > 3 else u''
        suffix = part[4] if len(part) > 4 else u''
        val    = resolve_param(elem, key) or u''
        token  = u'{0}{1}{2}'.format(prefix, val, suffix)
        tokens.append(token)
        if sep and i < n - 1:
            tokens.append(sep)
    return u''.join(tokens)


# ═══════════════════════════════════════════════════════════
#  TRANSACTION HELPERS
# ═══════════════════════════════════════════════════════════
def write_single(elem, value):
    """Write one value to Custom File Name. Validates before t.Start()."""
    t = Transaction(doc, u'ProSheets: Set Custom File Name')
    try:
        p = elem.LookupParameter(CUSTOM_PARAM_NAME)
        if p is None:
            MessageBox.Show(
                u'Parameter \u201c{0}\u201d not found.'.format(CUSTOM_PARAM_NAME),
                u'ProSheets', MessageBoxButtons.OK, MessageBoxIcon.Warning)
            return False
        if p.IsReadOnly:
            MessageBox.Show(
                u'Parameter \u201c{0}\u201d is read-only.'.format(CUSTOM_PARAM_NAME),
                u'ProSheets', MessageBoxButtons.OK, MessageBoxIcon.Warning)
            return False
        t.Start()
        p.Set(value if value else u'')
        t.Commit()
        return True
    except Exception as ex:
        rollback_safe(t)
        MessageBox.Show(u'Write failed:\n{0}'.format(str(ex)),
                        u'ProSheets', MessageBoxButtons.OK, MessageBoxIcon.Error)
        return False


def write_bulk(pairs):
    """
    Write multiple (ElementId, str) pairs in one transaction.
    Return (ok_count, err_count, err_list).
    """
    ok_n = 0
    err_n = 0
    errs = []

    # Validate trước khi mở transaction
    skip_ids = set()
    for (eid, val) in pairs:
        elem = doc.GetElement(eid)
        if elem is None:
            skip_ids.add(eid.IntegerValue)
            err_n += 1
            errs.append(u'Id {0}: element not found'.format(eid.IntegerValue))
            continue
        p = elem.LookupParameter(CUSTOM_PARAM_NAME)
        if p is None or p.IsReadOnly:
            skip_ids.add(eid.IntegerValue)
            err_n += 1
            errs.append(u'Id {0}: param missing/read-only'.format(eid.IntegerValue))

    valid_pairs = [(eid, val) for (eid, val) in pairs
                   if eid.IntegerValue not in skip_ids]

    if not valid_pairs:
        return 0, err_n, errs

    if err_n > 0:
        res = MessageBox.Show(
            u'{0} item(s) skipped (param missing or read-only).\n'
            u'Continue writing the remaining {1} item(s)?'.format(
                err_n, len(valid_pairs)),
            u'ProSheets', MessageBoxButtons.YesNo, MessageBoxIcon.Warning)
        if res == DialogResult.No:
            return 0, err_n, errs

    t = Transaction(doc, u'ProSheets: Apply Naming Rule')
    try:
        t.Start()
        for (eid, val) in valid_pairs:
            try:
                elem = doc.GetElement(eid)
                p    = elem.LookupParameter(CUSTOM_PARAM_NAME)
                p.Set(val if val else u'')
                ok_n += 1
            except Exception as ex:
                err_n += 1
                errs.append(str(ex))
        t.Commit()
    except Exception as ex:
        rollback_safe(t)
        errs.append(u'Transaction error: ' + str(ex))

    return ok_n, err_n, errs


# ═══════════════════════════════════════════════════════════
#  DATA COLLECTION
# ═══════════════════════════════════════════════════════════
def collect_revit_sets():
    """Collect Revit ViewSheetSets from the document."""
    results = []
    try:
        for s in (FilteredElementCollector(doc)
                  .OfClass(ViewSheetSet).ToElements()):
            if s is None:
                continue
            name = u''
            try:
                name = s.Name if s.Name else u''
            except Exception:
                pass
            if not name:
                continue
            ids = []
            try:
                for v in s.Views:
                    if v is not None:
                        ids.append(v.Id.IntegerValue)
            except Exception:
                pass
            results.append({'name': name, 'ids': set(ids)})
        results.sort(key=lambda x: x['name'])
    except Exception:
        pass
    return results


def _get_title_block_name(sheet):
    """Fast: read paper size from sheet parameters only.
    No scoped collector — avoids forcing Revit to regenerate graphics.
    """
    try:
        w = sheet.get_Parameter(BuiltInParameter.SHEET_WIDTH)
        h = sheet.get_Parameter(BuiltInParameter.SHEET_HEIGHT)
        if w and h and w.HasValue and h.HasValue:
            wm = int(round(w.AsDouble() * 304.8))
            hm = int(round(h.AsDouble() * 304.8))
            return u'{0}x{1}mm'.format(wm, hm)
    except Exception:
        pass
    val = safe_string(sheet, u'Sheet Size')
    if val:
        return val
    return u''


def collect_sheets():
    rows = []
    try:
        for s in (FilteredElementCollector(doc)
                  .OfClass(ViewSheet).ToElements()):
            if s is None:
                continue
            rows.append({
                'id'      : s.Id,
                'number'  : safe_bip(s, BuiltInParameter.SHEET_NUMBER),
                'name'    : safe_bip(s, BuiltInParameter.SHEET_NAME),
                'revision': safe_bip(s, BuiltInParameter.SHEET_CURRENT_REVISION),
                'size'    : _get_title_block_name(s),
                'custom'  : safe_string(s, CUSTOM_PARAM_NAME),
            })
        rows.sort(key=lambda x: x['number'])
    except Exception as ex:
        MessageBox.Show(u'Failed to collect sheets:\n' + str(ex),
                        u'ProSheets', MessageBoxButtons.OK, MessageBoxIcon.Error)
    return rows


_VIEW_TYPE_LABELS = {
    u'ThreeD': u'3D', u'AreaPlan': u'Area Plan', u'CeilingPlan': u'Ceiling Plan',
    u'Detail': u'Detail', u'DraftingView': u'Drafting View', u'Elevation': u'Elevation',
    u'FloorPlan': u'Floor Plan', u'Legend': u'Legend', u'Rendering': u'Rendering',
    u'Section': u'Section', u'Walkthrough': u'Walkthrough',
}
def _view_type_label(vt):
    name = str(vt)
    if u'.' in name: name = name.split(u'.')[-1]
    return _VIEW_TYPE_LABELS.get(name, name)
def _view_scale_str(v):
    try:
        s = v.Scale
        if s and s > 0: return u'1:{0}'.format(s)
    except Exception: pass
    return u'Custom'
def _detail_level_str(v):
    try:
        name = str(v.DetailLevel)
        if u'.' in name: name = name.split(u'.')[-1]
        return name
    except Exception: return u''
def _discipline_str(v):
    try:
        p = v.get_Parameter(BuiltInParameter.VIEW_DISCIPLINE)
        if p and p.HasValue: return p.AsValueString() or u''
    except Exception: pass
    return u''

def collect_views():
    rows = []
    excluded = [ViewType.DrawingSheet, ViewType.ProjectBrowser,
                ViewType.SystemBrowser, ViewType.Undefined]
    try:
        for v in (FilteredElementCollector(doc).OfClass(View).ToElements()):
            if v is None or v.IsTemplate: continue
            if v.ViewType in excluded: continue
            rows.append({
                'id': v.Id, 'number': u'',
                'name': v.Name if v.Name else u'',
                'revision': u'', 'size': u'',
                'custom': safe_string(v, CUSTOM_PARAM_NAME),
                'view_type': _view_type_label(v.ViewType),
                'view_scale': _view_scale_str(v),
                'detail_level': _detail_level_str(v),
                'discipline': _discipline_str(v),
            })
        rows.sort(key=lambda x: x['name'])
    except Exception as ex:
        MessageBox.Show(u'Failed to collect views:\n' + str(ex),
                        u'ProSheets', MessageBoxButtons.OK, MessageBoxIcon.Error)
    return rows


# ═══════════════════════════════════════════════════════════
#  VS SET MANAGER  (JSON — tool-created sets)
# ═══════════════════════════════════════════════════════════
class VSSetManager(object):
    def __init__(self):
        self._sets = {}
        self._path = self._resolve_path()
        self._load()

    def _resolve_path(self):
        # Try to place JSON beside the .rvt file.
        # If the .rvt lives in a write-protected directory (e.g. Program Files
        # sample files) we silently fall back to %APPDATA%/ProSheets/.
        try:
            p = doc.PathName
            if p:
                folder = os.path.dirname(p)
                stem   = os.path.splitext(os.path.basename(p))[0]
                candidate = os.path.join(
                    folder, u'{0}_ProSheets_Sets.json'.format(stem))
                # Quick write-access check — try to open for append
                try:
                    with open(candidate, 'a') as _f:
                        pass
                    return candidate          # writable — use it
                except (IOError, OSError):
                    pass                      # not writable — fall through
        except Exception:
            pass
        # Fallback: user APPDATA
        appdata = os.environ.get('APPDATA') or os.path.expanduser(u'~')
        folder  = os.path.join(appdata, u'ProSheets')
        try:
            if not os.path.exists(folder):
                os.makedirs(folder)
        except Exception:
            folder = os.path.expanduser(u'~')
        stem = u'default'
        try:
            p = doc.PathName
            if p:
                stem = os.path.splitext(os.path.basename(p))[0]
        except Exception:
            pass
        return os.path.join(folder, u'{0}_ProSheets_Sets.json'.format(stem))

    def _load(self):
        try:
            if os.path.exists(self._path):
                with open(self._path, 'r') as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._sets = data
        except Exception:
            self._sets = {}

    def _save(self):
        # Try primary path; if it fails re-resolve to a writable fallback.
        try:
            with open(self._path, 'w') as f:
                json.dump(self._sets, f, indent=2)
            return   # success
        except (IOError, OSError):
            pass

        # Primary path unwritable — re-resolve to APPDATA fallback and retry
        try:
            appdata = os.environ.get('APPDATA') or os.path.expanduser(u'~')
            folder  = os.path.join(appdata, u'ProSheets')
            if not os.path.exists(folder):
                os.makedirs(folder)
            stem = u'default'
            try:
                p = doc.PathName
                if p:
                    stem = os.path.splitext(os.path.basename(p))[0]
            except Exception:
                pass
            self._path = os.path.join(
                folder, u'{0}_ProSheets_Sets.json'.format(stem))
            with open(self._path, 'w') as f:
                json.dump(self._sets, f, indent=2)
        except Exception:
            pass   # silently ignore — sets are still in memory for this session

    def names(self):
        return sorted(self._sets.keys())

    def save(self, name, eids):
        if not name or not name.strip():
            return False
        self._sets[name.strip()] = [e.IntegerValue for e in eids]
        self._save()
        return True

    def get_ids(self, name):
        return set(self._sets.get(name, []))

    def delete(self, name):
        if name in self._sets:
            del self._sets[name]
            self._save()
            return True
        return False


# ═══════════════════════════════════════════════════════════
#  NAMING RULE PANEL
# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════
#  NAMING RULE DIALOG  (popup — replaces inline panel)
#
#  Opened when user clicks "Naming Rule..." button in toolbar.
#  Builds a list of (param, separator) slots, shows live pattern
#  preview, and returns parts on OK.
# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════
#  NAMING RULE DIALOG  — dual-panel picker
#
#  Layout (matches reference image 2):
#
#   ┌──────────────────────────────────────────────────────┐
#   │  Sheet Parameters          │  Selected Parameters    │
#   │  ┌──────────────────────┐  │  ┌──────────────────┐   │
#   │  │ Approved By          │  │  │ Sheet Number     │   │
#   │  │ Checked By           │  │  │ Sheet Name       │   │
#   │  │ Current Revision     │  │► │                  │   │
#   │  │ ...                  │  │◄ │                  │   │
#   │  └──────────────────────┘  │  └──────────────────┘   │
#   │  □ Include Project Info    │  Field Separator: [ _ ] │
#   │  Custom Field: [     ] [+] │  ▲ ▲ ▼ ▼ ↺              │
#   └──────────────────────────────────────────────────────┘
#   Preview:  [Sheet Number]_[Sheet Name]
#   ──────────────────────────────────────── [Cancel] [OK]
#
#  result_parts = list of (label, key, sep)
#  sep is uniform (one separator for all) stored in _separator
# ═══════════════════════════════════════════════════════════

# ── Load WPF assemblies and initialize colors NOW, before any class is parsed.
# IronPython 2 evaluates base class expressions (Window, etc.) at parse time,
# so these must run before class NamingRuleDialog(Window) is defined.
# With __persistentengine__ = True, clr.AddReference is a fast no-op on
# subsequent clicks because assemblies are already loaded in the process.
_load_revit_imports()
_load_wpf_imports()
_init_colors()

# =====================================================
# DATA ROW CLASSES  (WPF DataGrid requires real properties)
# IronPython 2: plain object with __dict__ exposed as properties.
# We use a thin wrapper that DataGrid can bind via PropertyDescriptor.
# =====================================================
class SheetRow(object):
    """Row for sheet and view modes."""
    def __init__(self, num, number, name, revision, size, custom, eid,
                 view_type=u"", view_scale=u"", detail_level=u"", discipline=u""):
        self.Num=num; self.Number=number; self.Name=name
        self.Revision=revision; self.Size=size; self.Custom=custom
        self.Checked=False; self._id=eid; self._orig_custom=custom
        self.ViewType=view_type; self.ViewScale=view_scale
        self.DetailLevel=detail_level; self.Discipline=discipline


class ExportRow(object):
    """Row object for the Create tab DataGrid."""
    def __init__(self, number, name, file_name, fmt, size, orient, eid, fmt_key):
        self.Number   = number
        self.Name     = name
        self.FileName = file_name
        self.Format   = fmt
        self.Size     = size
        self.Orient   = orient
        self.Progress = u''
        self._id      = eid
        self._fmt     = fmt_key


class OrderItem(object):
    """Row in Order Sheets/Views dialog DataGrid."""
    def __init__(self, num, name, eid):
        self.num  = num
        self.name = name
        self._id  = eid


# =====================================================
# NAMING RULE DIALOG  — redesign matching reference UI
#
# Layout:
#  Left: Dropdown filter + full param list from Revit
#  Mid:  ▶ / ◀ arrows
#  Right: DataGrid  [Parameter Name | Prefix | Sample Value | Suffix | Separator]
#         Reorder: ▲▲ ▲ ▼ ▼▼ ↺
#  Bottom: Custom Name Preview strip
# =====================================================

def collect_all_sheet_params():
    """
    Collect all parameter names available on ViewSheet elements.
    Returns sorted list of (display_name, key) tuples.
    key = param name string (used for lookup at apply time).
    Special BIP params use __bip_XXX__ keys.
    """
    param_names = set()
    # Add hardcoded BIP params first (always available)
    bip_params = [
        (u'Sheet Number',    u'__bip_SHEET_NUMBER__'),
        (u'Sheet Name',      u'__bip_SHEET_NAME__'),
        (u'Current Revision',u'__bip_REVISION__'),
        (u'Drawn By',        u'__bip_DRAWN_BY__'),
        (u'Checked By',      u'__bip_CHECKED_BY__'),
        (u'Designed By',     u'__bip_DESIGNED_BY__'),
        (u'Approved By',     u'__bip_APPROVED_BY__'),
    ]
    # Also track proj param display names to avoid duplicates
    _proj_display_names = {
        u'project name', u'project number', u'project address',
        u'project status', u'project issue date', u'client name',
        u'author', u'building name',
        u'organization name', u'organization description',
    }
    sheet_params  = list(bip_params)
    sheet_keys    = set(k for (l, k) in bip_params)

    proj_params = [
        (u'Project Name',        u'__bip_PROJECT_NAME__'),
        (u'Project Number',      u'__bip_PROJECT_NUMBER__'),
        (u'Project Address',     u'__bip_PROJECT_ADDRESS__'),
        (u'Project Status',      u'__bip_PROJECT_STATUS__'),
        (u'Project Issue Date',  u'__bip_PROJECT_ISSUE_DATE__'),
        (u'Client Name',         u'__bip_CLIENT_NAME__'),
        (u'Author',              u'__bip_PROJECT_AUTHOR__'),
        (u'Building Name',       u'__bip_BUILDING_NAME__'),
        (u'Organization Name',   u'__bip_ORGANIZATION_NAME__'),
        (u'Organization Desc',   u'__bip_ORGANIZATION_DESCRIPTION__'),
    ]
    # Design Option and IFC params come from sheet's LookupParameter scan —
    # they appear in sheet_params group since they are per-sheet/view params,
    # not project-level. collect_all_sheet_params() will pick them up automatically.

    # Track display names of BIP params so we skip them when scanning
    bip_display_names = set(l.lower() for (l, k) in bip_params)

    # Scan first sheet for additional parameters
    try:
        sheets = (FilteredElementCollector(doc)
                  .OfClass(ViewSheet).ToElements())
        for s in sheets:
            for p in s.Parameters:
                try:
                    name = p.Definition.Name
                    if not name or name.startswith(u'_'):
                        continue
                    # Skip if already covered by a BIP or project param (by display name)
                    nl = name.lower()
                    if nl in bip_display_names or nl in _proj_display_names:
                        continue
                    key = u'__param__' + name
                    if key not in sheet_keys:
                        sheet_keys.add(key)
                        sheet_params.append((name, key))
                except Exception:
                    pass
            break   # only need 1 sheet
    except Exception:
        pass

    sheet_params.sort(key=lambda x: x[0])
    proj_params.sort(key=lambda x: x[0])
    return sheet_params, proj_params


class SelectedParam(object):
    """Row in the right DataGrid — one selected parameter with per-item formatting."""
    def __init__(self, label, key, prefix=u'', suffix=u'', separator=u'-', sample=u''):
        self.ParamName  = label
        self._key       = key
        self.Prefix     = prefix
        self.SampleValue = sample or label   # live value filled later
        self.Suffix     = suffix
        self.Separator  = separator


class NamingRuleDialog(Window):
    """
    Naming Rule builder matching reference UI:
    Left  : dropdown filter (All / Sheet Parameters / Project Info)
            + scrollable list of all params available on sheets
    Centre: ▶ add  /  ◀ remove
    Right : DataGrid [Parameter Name | Prefix | Sample Value | Suffix | Separator]
            Reorder buttons: ▲▲  ▲  ▼  ▼▼  ↺
    Bottom: Custom Name Preview
    result_parts: list of (label, key, sep, prefix, suffix) or None on Cancel
    """
    def __init__(self, initial_parts=None, sample_sheet=None):
        self.result_parts  = None
        self._sheet_params = []   # (label, key) for Sheet category
        self._proj_params  = []   # (label, key) for Project Info
        self._sel_rows     = []   # list of SelectedParam
        self._sample_elem  = sample_sheet  # for live sample values

        self.Title                 = u'Naming Rule  \u2014  ProSheets'
        self.Width                 = 900
        self.Height                = 560
        self.MinWidth              = 720
        self.MinHeight             = 440
        self.WindowStartupLocation = WindowStartupLocation.CenterOwner
        self.Background            = SolidColorBrush(CLR_BG)
        self.ResizeMode            = System.Windows.ResizeMode.CanResizeWithGrip

        # Load params
        self._sheet_params, self._proj_params = collect_all_sheet_params()

        self._build()

        # Load initial state
        if initial_parts:
            for part in initial_parts:
                lbl = part[0]; key = part[1]
                sep = part[2] if len(part) > 2 else u'-'
                prefix = part[3] if len(part) > 3 else u''
                suffix = part[4] if len(part) > 4 else u''
                sample = self._get_sample(key)
                row = SelectedParam(lbl, key, prefix, suffix, sep, sample)
                self._sel_rows.append(row)

        self._refresh_avail()
        self._refresh_sel()
        self._update_preview()

    # ── Build UI ───────────────────────────────────────────
    def _build(self):
        root = WPFGrid()
        _row(root, GridLength.Auto)                   # 0 header
        _row(root, GridLength(1, GridUnitType.Star))  # 1 body
        _row(root, GridLength.Auto)                   # 2 preview
        _row(root, GridLength.Auto)                   # 3 btn row
        _row(root, GridLength.Auto)                   # 4 footer

        # Header
        hdr = _header_block(u'NAMING RULE',
                            u'Build Custom File Name by selecting and formatting parameters')
        WPFGrid.SetRow(hdr, 0); root.Children.Add(hdr)

        # Body: Left | Centre | Right
        body = WPFGrid()
        body.Margin = Thickness(12, 10, 12, 0)
        _col(body, GridLength(280))          # Left fixed
        _col(body, GridLength(48))           # Centre arrows
        _col(body, GridLength(1, GridUnitType.Star))  # Right fills
        WPFGrid.SetRow(body, 1); root.Children.Add(body)

        # ── LEFT: Available Parameters ──────────────────────
        left_card = _card(padding=10)
        lg = WPFGrid()
        _row(lg, GridLength.Auto)   # section label
        _row(lg, GridLength.Auto)   # filter dropdown
        _row(lg, GridLength(1, GridUnitType.Star))  # listbox

        lbl_avail = _section_lbl(u'AVAILABLE PARAMETERS')
        WPFGrid.SetRow(lbl_avail, 0); lg.Children.Add(lbl_avail)

        # Filter dropdown: All / Sheet Parameters / Project Info
        self._cmb_filter = ComboBox()
        self._cmb_filter.Height = 28; self._cmb_filter.FontSize = 11
        self._cmb_filter.Margin = Thickness(0, 4, 0, 6)
        self._cmb_filter.BorderBrush = SolidColorBrush(CLR_BORDER)
        self._cmb_filter.Background  = SolidColorBrush(CLR_CARD)
        for item in [u'All', u'Sheet Parameters', u'Project Information Parameters']:
            self._cmb_filter.Items.Add(item)
        self._cmb_filter.SelectedIndex = 0
        self._cmb_filter.SelectionChanged += lambda s, e: self._refresh_avail()
        WPFGrid.SetRow(self._cmb_filter, 1); lg.Children.Add(self._cmb_filter)

        self._lb_avail = ListBox()
        self._lb_avail.FontSize = 11
        self._lb_avail.BorderBrush = SolidColorBrush(CLR_BORDER)
        self._lb_avail.BorderThickness = Thickness(1)
        self._lb_avail.Background = SolidColorBrush(CLR_CARD)
        self._lb_avail.SelectionMode = SelectionMode.Single
        self._lb_avail.MouseDoubleClick += lambda s, e: self._on_add()
        WPFGrid.SetRow(self._lb_avail, 2); lg.Children.Add(self._lb_avail)

        left_card.Child = lg
        WPFGrid.SetColumn(left_card, 0); body.Children.Add(left_card)

        # ── CENTRE: ▶ / ◀ ─────────────────────────────────
        arr = StackPanel()
        arr.VerticalAlignment   = VerticalAlignment.Center
        arr.HorizontalAlignment = HorizontalAlignment.Center
        arr.Margin              = Thickness(6, 0, 6, 0)

        btn_add = _make_btn(u'\u25ba', width=36, height=34)  # ► filled
        btn_add.Margin   = Thickness(0, 0, 0, 10)
        btn_add.FontSize = 13
        btn_add.Click   += lambda s, e: self._on_add()
        arr.Children.Add(btn_add)

        btn_rem = _make_btn(u'\u25c4', width=36, height=34)  # ◄ filled
        btn_rem.FontSize = 13
        btn_rem.Click   += lambda s, e: self._on_remove()
        arr.Children.Add(btn_rem)
        WPFGrid.SetColumn(arr, 1); body.Children.Add(arr)

        # ── RIGHT: Selected Parameters DataGrid ────────────
        right_card = _card(padding=10)
        rg = WPFGrid()
        _row(rg, GridLength.Auto)                   # label
        _row(rg, GridLength(1, GridUnitType.Star))  # datagrid
        _row(rg, GridLength.Auto)                   # reorder buttons

        lbl_sel = _section_lbl(u'SELECTED PARAMETERS')
        lbl_sel.Margin = Thickness(0, 0, 0, 6)
        WPFGrid.SetRow(lbl_sel, 0); rg.Children.Add(lbl_sel)

        # DataGrid
        self._dg_sel = DataGrid()
        self._dg_sel.AutoGenerateColumns     = False
        self._dg_sel.CanUserAddRows          = False
        self._dg_sel.CanUserDeleteRows       = False
        self._dg_sel.HeadersVisibility       = System.Windows.Controls.DataGridHeadersVisibility.Column
        self._dg_sel.SelectionMode           = System.Windows.Controls.DataGridSelectionMode.Single
        self._dg_sel.FontSize                = 11
        self._dg_sel.RowBackground           = SolidColorBrush(CLR_CARD)
        self._dg_sel.AlternatingRowBackground = SolidColorBrush(CLR_ALT)
        self._dg_sel.BorderBrush             = SolidColorBrush(CLR_BORDER)
        self._dg_sel.BorderThickness         = Thickness(1)
        self._dg_sel.GridLinesVisibility     = System.Windows.Controls.DataGridGridLinesVisibility.Horizontal
        self._dg_sel.HorizontalGridLinesBrush = SolidColorBrush(
            Color.FromRgb(220, 210, 190))
        self._dg_sel.Background              = SolidColorBrush(CLR_CARD)
        self._dg_sel.ColumnHeaderHeight      = 28
        self._dg_sel.RowHeight               = 28
        self._dg_sel.CellEditEnding         += self._on_cell_edit

        DGL = System.Windows.Controls.DataGridLength
        DGLU = System.Windows.Controls.DataGridLengthUnitType

        def _dgcol(header, path, w, is_star=False, read_only=True):
            c = DataGridTextColumn()
            c.Header    = header
            c.Binding   = System.Windows.Data.Binding(path)
            c.IsReadOnly = read_only
            c.Width = DGL(w, DGLU.Star) if is_star else DGL(w)
            return c

        self._dg_sel.Columns.Add(_dgcol(u'Parameter Name', u'ParamName', 1, is_star=True, read_only=True))
        self._dg_sel.Columns.Add(_dgcol(u'Prefix',         u'Prefix',     70, read_only=False))
        self._dg_sel.Columns.Add(_dgcol(u'Sample Value',   u'SampleValue',120, read_only=True))
        self._dg_sel.Columns.Add(_dgcol(u'Suffix',         u'Suffix',     70, read_only=False))
        self._dg_sel.Columns.Add(_dgcol(u'Separator',      u'Separator',  80, read_only=False))

        WPFGrid.SetRow(self._dg_sel, 1); rg.Children.Add(self._dg_sel)

        # Reorder buttons row: ▲▲  ▲  ▼  ▼▼  |  ↺
        re_row = StackPanel()
        re_row.Orientation = Orientation.Horizontal
        re_row.Margin      = Thickness(0, 8, 0, 0)

        for (sym, delta, tip) in [
            (u'\u25b2\u25b2', -999, u'Move to Top'),
            (u'\u25b2',        -1,  u'Move Up'),
            (u'\u25bc',         1,  u'Move Down'),
            (u'\u25bc\u25bc',  999, u'Move to Bottom'),
        ]:
            def make_mv(d):
                def h(ss, ev): self._move(d)
                return h
            b = _make_btn(sym, width=34, height=28)
            b.Margin  = Thickness(0, 0, 4, 0)
            b.ToolTip = tip
            b.Click  += make_mv(delta)
            re_row.Children.Add(b)

        # Divider
        div = Border()
        div.Width = 1; div.Background = SolidColorBrush(CLR_BORDER)
        div.Margin = Thickness(4, 2, 8, 2)
        re_row.Children.Add(div)

        # Clear all ↺
        btn_clr = _make_btn(u'\u21ba', width=34, height=28)
        btn_clr.Foreground = SolidColorBrush(CLR_ERR)
        btn_clr.ToolTip    = u'Clear all'
        btn_clr.Click     += lambda s, e: self._clear_sel()
        re_row.Children.Add(btn_clr)

        WPFGrid.SetRow(re_row, 2); rg.Children.Add(re_row)

        right_card.Child = rg
        WPFGrid.SetColumn(right_card, 2); body.Children.Add(right_card)

        # ── Preview strip ──────────────────────────────────
        prev_border = Border()
        prev_border.Background = SolidColorBrush(CLR_ALT)
        prev_border.BorderBrush = SolidColorBrush(CLR_BORDER)
        prev_border.BorderThickness = Thickness(1)
        prev_border.CornerRadius = System.Windows.CornerRadius(3)
        prev_border.Padding = Thickness(12, 6, 12, 6)
        prev_border.Margin  = Thickness(12, 8, 12, 0)
        WPFGrid.SetRow(prev_border, 2); root.Children.Add(prev_border)

        prev_g = WPFGrid()
        _col(prev_g, GridLength.Auto)
        _col(prev_g, GridLength(1, GridUnitType.Star))

        lbl_prev_title = TextBlock()
        lbl_prev_title.Text      = u'Custom Name Preview:  '
        lbl_prev_title.FontSize  = 11
        lbl_prev_title.Foreground = SolidColorBrush(CLR_MUTED)
        lbl_prev_title.VerticalAlignment = VerticalAlignment.Center
        WPFGrid.SetColumn(lbl_prev_title, 0); prev_g.Children.Add(lbl_prev_title)

        self._lbl_prev = TextBlock()
        self._lbl_prev.FontFamily = System.Windows.Media.FontFamily(u'Consolas')
        self._lbl_prev.FontSize   = 11
        self._lbl_prev.FontWeight = System.Windows.FontWeights.SemiBold
        self._lbl_prev.Foreground = SolidColorBrush(Color.FromRgb(40, 100, 180))
        self._lbl_prev.Text       = u'(empty)'
        self._lbl_prev.VerticalAlignment = VerticalAlignment.Center
        WPFGrid.SetColumn(self._lbl_prev, 1); prev_g.Children.Add(self._lbl_prev)
        prev_border.Child = prev_g

        # ── Button row ─────────────────────────────────────
        btn_row = Border()
        btn_row.Background = SolidColorBrush(CLR_BG)
        btn_row.Padding    = Thickness(12, 8, 12, 8)
        WPFGrid.SetRow(btn_row, 3); root.Children.Add(btn_row)

        brg = WPFGrid()
        _col(brg, GridLength(1, GridUnitType.Star))
        _col(brg, GridLength.Auto)
        _col(brg, GridLength.Auto)

        btn_can = _make_btn(u'Cancel', width=88)
        btn_can.Margin = Thickness(0, 0, 8, 0)
        btn_can.Click += lambda s, e: self.Close()
        WPFGrid.SetColumn(btn_can, 1); brg.Children.Add(btn_can)

        btn_ok = _make_btn(u'\u2714  OK', width=88)
        btn_ok.Click += lambda s, e: self._on_ok()
        WPFGrid.SetColumn(btn_ok, 2); brg.Children.Add(btn_ok)
        btn_row.Child = brg

        # ── Footer ─────────────────────────────────────────
        fb = _footer_bar()
        WPFGrid.SetRow(fb, 4); root.Children.Add(fb)

        self.Content = root

    # ── Data helpers ────────────────────────────────────────
    def _get_sample(self, key):
        """Get sample value for a param key from first sheet."""
        try:
            if self._sample_elem is None:
                sheets = list(FilteredElementCollector(doc)
                              .OfClass(ViewSheet).ToElements())
                if sheets:
                    self._sample_elem = sheets[0]
            if self._sample_elem is None:
                return u''
            return resolve_param(self._sample_elem, key) or u''
        except Exception:
            return u''

    def _all_params(self):
        flt = self._cmb_filter.SelectedIndex if self._cmb_filter else 0
        if flt == 1:   return self._sheet_params
        if flt == 2:   return self._proj_params
        return self._sheet_params + self._proj_params

    def _refresh_avail(self):
        self._lb_avail.Items.Clear()
        sel_keys = set(r._key for r in self._sel_rows)
        for (lbl, key) in self._all_params():
            if key not in sel_keys:
                self._lb_avail.Items.Add(lbl)

    def _refresh_sel(self):
        col = ObservableCollection[object]()
        for r in self._sel_rows:
            col.Add(r)
        self._dg_sel.ItemsSource = col

    def _on_add(self):
        idx = self._lb_avail.SelectedIndex
        if idx < 0:
            return
        # Find matching param from visible list
        sel_keys = set(r._key for r in self._sel_rows)
        visible  = [(l, k) for (l, k) in self._all_params() if k not in sel_keys]
        if idx >= len(visible):
            return
        lbl, key  = visible[idx]
        sample    = self._get_sample(key)
        row       = SelectedParam(lbl, key, u'', u'', u'-', sample)
        self._sel_rows.append(row)
        self._refresh_avail()
        self._refresh_sel()
        self._dg_sel.SelectedIndex = len(self._sel_rows) - 1
        self._update_preview()

    def _on_remove(self):
        idx = self._dg_sel.SelectedIndex
        if idx < 0 or idx >= len(self._sel_rows):
            return
        del self._sel_rows[idx]
        self._refresh_avail()
        self._refresh_sel()
        if self._sel_rows:
            self._dg_sel.SelectedIndex = min(idx, len(self._sel_rows) - 1)
        self._update_preview()

    def _clear_sel(self):
        self._sel_rows = []
        self._refresh_avail()
        self._refresh_sel()
        self._update_preview()

    def _move(self, delta):
        idx = self._dg_sel.SelectedIndex
        if idx < 0 or not self._sel_rows:
            return
        if delta <= -999:  new_idx = 0
        elif delta >= 999: new_idx = len(self._sel_rows) - 1
        else:              new_idx = max(0, min(len(self._sel_rows) - 1, idx + delta))
        if new_idx == idx: return
        item = self._sel_rows.pop(idx)
        self._sel_rows.insert(new_idx, item)
        self._refresh_sel()
        self._dg_sel.SelectedIndex = new_idx
        self._update_preview()

    def _on_current_cell_chg(self, s, e):
        pass   # reserved for future use

    def _on_cell_edit(self, s, e):
        # Prefix/Suffix/Separator edited inline — update preview
        self._update_preview()

    def _update_preview(self):
        if not self._sel_rows:
            self._lbl_prev.Text = u'(empty)'
            return
        parts = []
        for i, r in enumerate(self._sel_rows):
            token = u'{0}{1}{2}'.format(r.Prefix or u'', r.SampleValue or r.ParamName, r.Suffix or u'')
            parts.append(token)
            if i < len(self._sel_rows) - 1:
                sep = r.Separator or u'-'
                parts.append(sep)
        self._lbl_prev.Text = u''.join(parts)

    def _get_parts(self):
        """
        Return list of (label, key, separator, prefix, suffix).
        Separator of last item = '' (ignored).
        """
        n = len(self._sel_rows)
        result = []
        for i, r in enumerate(self._sel_rows):
            sep = (r.Separator or u'-') if i < n - 1 else u''
            result.append((r.ParamName, r._key, sep, r.Prefix or u'', r.Suffix or u''))
        return result

    def _on_ok(self):
        self.result_parts = self._get_parts()
        self.Close()



# =====================================================
# MAIN WINDOW  — ProSheetsWindow (WPF)
# =====================================================
class ProSheetsWindow(Window):
    """
    3-tab WPF window matching NV ColorSplasher design pattern.
    Tabs: Selection | Format | Create
    """

    def __init__(self):
        # ── State
        self._vs_mgr          = VSSetManager()
        self._all_data        = []
        self._mode             = u'Sheet'
        self._view_type_filter = u''
        self._active_set       = None
        self._checked_sheet    = set()   # ElementId.IntegerValue of checked sheets
        self._checked_view     = set()   # ElementId.IntegerValue of checked views
        self._active_src      = None
        self._rule_parts      = []
        self._pdf_settings    = {}
        self._dwg_settings    = {}
        self._active_fmts     = [u'pdf']
        self._paper_override  = u''
        self._orient_override = u''
        self._out_folder      = u''

        # ── Window setup
        self.Title                 = u'ProSheets - By NV'
        self.Width                 = 1060
        self.Height                = 740
        self.MinWidth              = 860
        self.MinHeight             = 560
        self.WindowStartupLocation = WindowStartupLocation.CenterScreen
        self.Background            = SolidColorBrush(CLR_BG)

        self._build()

    # ══════════════════════════════════════════════════
    # BUILD MAIN WINDOW
    # ══════════════════════════════════════════════════
    def _build(self):
        root = WPFGrid()
        _row(root, GridLength.Auto)                  # 0 header
        _row(root, GridLength(1, GridUnitType.Star)) # 1 content (tabs)
        _row(root, GridLength.Auto)                  # 2 btn row
        _row(root, GridLength.Auto)                  # 3 footer

        # ── Header
        hdr = _header_block(u'PROSHEETS',
                            u'Batch Export Sheets & Views  \u2014  PDF  |  DWG')
        WPFGrid.SetRow(hdr, 0); root.Children.Add(hdr)

        # ── Tab control
        self._tc = TabControl()
        self._tc.Margin = Thickness(12, 8, 12, 0)
        self._tc.Background = SolidColorBrush(CLR_BG)
        WPFGrid.SetRow(self._tc, 1); root.Children.Add(self._tc)

        ti1 = TabItem(); ti1.Header = u'  Selection  '
        ti2 = TabItem(); ti2.Header = u'  Format  '
        ti3 = TabItem(); ti3.Header = u'  Create  '
        for ti in [ti1, ti2, ti3]:
            ti.Background = SolidColorBrush(CLR_CARD)
            self._tc.Items.Add(ti)

        ti1.Content = self._build_selection_tab()
        ti2.Content = self._build_format_tab()
        ti3.Content = self._build_create_tab()

        self._tc.SelectionChanged += self._on_tab_changed

        # ── Button row
        btn_row = Border()
        btn_row.Background = SolidColorBrush(CLR_BG)
        btn_row.Padding    = Thickness(12, 8, 12, 8)
        WPFGrid.SetRow(btn_row, 2); root.Children.Add(btn_row)

        brg = WPFGrid()
        _col(brg, GridLength(1, GridUnitType.Star))
        _col(brg, GridLength.Auto)
        _col(brg, GridLength.Auto)
        _col(brg, GridLength.Auto)

        # Status left
        self._lbl_status = TextBlock()
        self._lbl_status.Text = u'0 sheets selected.  Total: 0'
        self._lbl_status.FontSize = 11
        self._lbl_status.Foreground = SolidColorBrush(CLR_MUTED)
        self._lbl_status.VerticalAlignment = VerticalAlignment.Center
        WPFGrid.SetColumn(self._lbl_status, 0); brg.Children.Add(self._lbl_status)

        self._btn_back = _make_btn(u'\u25c4  Back', width=88)
        self._btn_back.Margin = Thickness(0, 0, 8, 0)
        self._btn_back.Click += lambda s, e: self._nav(-1)
        WPFGrid.SetColumn(self._btn_back, 1); brg.Children.Add(self._btn_back)

        self._btn_next = _make_btn(u'Next  \u25b6', width=88)
        self._btn_next.Margin = Thickness(0, 0, 8, 0)
        self._btn_next.Click += lambda s, e: self._nav(1)
        WPFGrid.SetColumn(self._btn_next, 2); brg.Children.Add(self._btn_next)

        self._btn_create = _apply_btn(u'\u25b6  Create', width=120, height=34)
        self._btn_create.Visibility = Visibility.Collapsed
        self._btn_create.Click += lambda s, e: self._on_create()
        WPFGrid.SetColumn(self._btn_create, 3); brg.Children.Add(self._btn_create)

        btn_row.Child = brg

        # ── Footer bar
        fb = _footer_bar()
        WPFGrid.SetRow(fb, 3); root.Children.Add(fb)

        self.Content = root

        # Deferred load
        self.Loaded += lambda s, e: self._deferred_load()

    # ══════════════════════════════════════════════════
    # TAB 1 — SELECTION
    # ══════════════════════════════════════════════════
    def _build_selection_tab(self):
        tab = WPFGrid()
        tab.Background = SolidColorBrush(CLR_BG)
        tab.Margin = Thickness(0, 8, 0, 0)
        _row(tab, GridLength.Auto)                  # toolbar
        _row(tab, GridLength.Auto)                  # filter/rule strips
        _row(tab, GridLength(1, GridUnitType.Star)) # grid

        # ── Toolbar
        tb = Border()
        tb.Background = SolidColorBrush(CLR_HEADER)
        tb.Padding    = Thickness(10, 6, 10, 6)
        tb.CornerRadius = System.Windows.CornerRadius(4, 4, 0, 0)
        WPFGrid.SetRow(tb, 0); tab.Children.Add(tb)

        tbb = WPFGrid()
        _col(tbb, GridLength(1, GridUnitType.Star))
        _col(tbb, GridLength(200))
        sp_left = StackPanel()
        sp_left.Orientation = Orientation.Horizontal

        # Sheets / Views radios
        self._rb_sh = RadioButton()
        self._rb_sh.Content = u'Sheets'; self._rb_sh.IsChecked = True
        self._rb_sh.FontSize = 11; self._rb_sh.Margin = Thickness(0,0,10,0)
        self._rb_sh.Foreground = SolidColorBrush(CLR_TEXT)
        self._rb_sh.VerticalAlignment = VerticalAlignment.Center
        self._rb_sh.Checked += lambda s, e: self._on_mode()
        sp_left.Children.Add(self._rb_sh)

        self._rb_vw = RadioButton()
        self._rb_vw.Content = u'Views'
        self._rb_vw.FontSize = 11; self._rb_vw.Margin = Thickness(0,0,16,0)
        self._rb_vw.Foreground = SolidColorBrush(CLR_TEXT)
        self._rb_vw.VerticalAlignment = VerticalAlignment.Center
        self._rb_vw.Checked += lambda s, e: self._on_mode()
        sp_left.Children.Add(self._rb_vw)

        sep2 = Separator(); sep2.Margin = Thickness(0, 0, 12, 0)
        sp_left.Children.Add(sep2)

        self._btn_flt  = _make_btn(u'\u2261  Filter by V/S Set')
        self._btn_flt.Margin = Thickness(0, 0, 6, 0)
        self._btn_flt.Click += self._show_filter_menu
        sp_left.Children.Add(self._btn_flt)

        self._btn_sav  = _make_btn(u'\u25bc  Save V/S Set')
        self._btn_sav.Margin = Thickness(0, 0, 6, 0)
        self._btn_sav.Click += self._show_save_menu
        sp_left.Children.Add(self._btn_sav)

        self._btn_rule = _make_btn(u'\u2699  Naming Rule')
        self._btn_rule.Margin = Thickness(0, 0, 6, 0)
        self._btn_rule.Click += self._open_naming_rule
        sp_left.Children.Add(self._btn_rule)

        self._btn_clrn = _make_btn(u'\u2715  Clear Names')
        self._btn_clrn.Foreground = SolidColorBrush(CLR_ERR)
        self._btn_clrn.Click += self._on_clear_names
        sp_left.Children.Add(self._btn_clrn)

        WPFGrid.SetColumn(sp_left, 0); tbb.Children.Add(sp_left)

        self._txt_srch = TextBox()
        self._txt_srch.FontSize    = 11
        self._txt_srch.Height      = 28
        self._txt_srch.BorderBrush = SolidColorBrush(CLR_BORDER)
        self._txt_srch.Margin      = Thickness(8, 0, 0, 0)
        self._txt_srch.VerticalContentAlignment = VerticalAlignment.Center
        self._txt_srch.Text = u'Search...'
        self._txt_srch.GotFocus  += lambda s, e: self._srch_focus(True)
        self._txt_srch.LostFocus += lambda s, e: self._srch_focus(False)
        self._txt_srch.TextChanged += lambda s, e: self._apply_filters()
        WPFGrid.SetColumn(self._txt_srch, 1); tbb.Children.Add(self._txt_srch)
        tb.Child = tbb

        # ── Info strips (filter active / rule active)
        strips = StackPanel()
        WPFGrid.SetRow(strips, 1); tab.Children.Add(strips)

        self._strip_filter = Border()
        self._strip_filter.Background = SolidColorBrush(CLR_PILL)
        self._strip_filter.Padding    = Thickness(10, 3, 10, 3)
        self._strip_filter.Visibility = Visibility.Collapsed
        sfg = WPFGrid()
        _col(sfg, GridLength(1, GridUnitType.Star))
        _col(sfg, GridLength.Auto)
        self._lbl_filt_txt = TextBlock()
        self._lbl_filt_txt.FontSize   = 10
        self._lbl_filt_txt.Foreground = SolidColorBrush(CLR_ACCENT)
        WPFGrid.SetColumn(self._lbl_filt_txt, 0); sfg.Children.Add(self._lbl_filt_txt)
        lnk_clr = TextBlock()
        lnk_clr.Text      = u'\u2715 Clear filter'
        lnk_clr.FontSize  = 10
        lnk_clr.Foreground = SolidColorBrush(CLR_ACCENT)
        lnk_clr.Cursor     = System.Windows.Input.Cursors.Hand
        lnk_clr.MouseLeftButtonUp += lambda s, e: self._clr_filter()
        WPFGrid.SetColumn(lnk_clr, 1); sfg.Children.Add(lnk_clr)
        self._strip_filter.Child = sfg
        strips.Children.Add(self._strip_filter)

        self._strip_rule = Border()
        self._strip_rule.Background = SolidColorBrush(CLR_ALT)
        self._strip_rule.Padding    = Thickness(10, 3, 10, 3)
        self._strip_rule.Visibility = Visibility.Collapsed
        srg = WPFGrid()
        _col(srg, GridLength(1, GridUnitType.Star))
        _col(srg, GridLength.Auto)
        self._lbl_rule_txt = TextBlock()
        self._lbl_rule_txt.FontSize = 10
        self._lbl_rule_txt.FontFamily = System.Windows.Media.FontFamily(u'Consolas')
        self._lbl_rule_txt.Foreground = SolidColorBrush(Color.FromRgb(40, 100, 180))
        WPFGrid.SetColumn(self._lbl_rule_txt, 0); srg.Children.Add(self._lbl_rule_txt)
        lnk_rule = TextBlock()
        lnk_rule.Text      = u'\u2715 Clear rule'
        lnk_rule.FontSize  = 10
        lnk_rule.Foreground = SolidColorBrush(CLR_ACCENT)
        lnk_rule.Cursor     = System.Windows.Input.Cursors.Hand
        lnk_rule.MouseLeftButtonUp += lambda s, e: self._clr_rule()
        WPFGrid.SetColumn(lnk_rule, 1); srg.Children.Add(lnk_rule)
        self._strip_rule.Child = srg
        strips.Children.Add(self._strip_rule)

        # ── DataGrid
        dg_wrap = Border()
        dg_wrap.Background = SolidColorBrush(CLR_CARD)
        dg_wrap.BorderBrush = SolidColorBrush(CLR_BORDER)
        dg_wrap.BorderThickness = Thickness(1)
        dg_wrap.CornerRadius = System.Windows.CornerRadius(0, 0, 4, 4)
        WPFGrid.SetRow(dg_wrap, 2); tab.Children.Add(dg_wrap)

        self._dg = DataGrid()
        self._dg.AutoGenerateColumns     = False
        self._dg.CanUserAddRows          = False
        self._dg.CanUserDeleteRows       = False
        self._dg.IsReadOnly              = False
        self._dg.HeadersVisibility       = System.Windows.Controls.DataGridHeadersVisibility.Column
        self._dg.SelectionMode           = System.Windows.Controls.DataGridSelectionMode.Extended
        self._dg.AlternatingRowBackground = SolidColorBrush(CLR_ALT)
        self._dg.RowBackground           = SolidColorBrush(CLR_CARD)
        self._dg.FontSize = 11
        self._dg.GridLinesVisibility = System.Windows.Controls.DataGridGridLinesVisibility.Horizontal
        self._dg.HorizontalGridLinesBrush = SolidColorBrush(Color.FromRgb(230, 220, 195))
        self._dg.Background = SolidColorBrush(CLR_CARD)

        # Columns
        col_chk = DataGridCheckBoxColumn()
        # Header checkbox for select/clear all
        hdr_chk = CheckBox()
        hdr_chk.ToolTip = u'Select / Clear All'
        hdr_chk.VerticalAlignment = VerticalAlignment.Center
        hdr_chk.HorizontalAlignment = HorizontalAlignment.Center
        self._hdr_chk = hdr_chk

        def _on_hdr_chk(ss, ev):
            new_state = (self._hdr_chk.IsChecked == True)
            for r in self._grid_rows:
                r.Checked = new_state
            self._populate_grid()
            self._upd_status()
        hdr_chk.Click += _on_hdr_chk

        col_chk.Header = hdr_chk
        col_chk.Width  = System.Windows.Controls.DataGridLength(30)
        col_chk.Binding = System.Windows.Data.Binding(u'Checked')
        self._dg.Columns.Add(col_chk)

        self._view_type_filter = u''
        self._rebuild_grid_columns()

        self._dg.CellEditEnding             += self._on_cell_edit
        self._dg.KeyDown                    += self._on_grid_key
        self._dg.CurrentCellChanged         += self._on_current_cell_chg
        self._dg.PreviewMouseLeftButtonDown += self._on_chk_click
        self._dg.PreviewMouseMove           += self._on_mouse_move
        dg_wrap.Child = self._dg
        self._grid_rows = []   # list of dict row objects

        return tab

    # ══════════════════════════════════════════════════
    # TAB 2 — FORMAT
    # ══════════════════════════════════════════════════
    def _build_format_tab(self):
        tab = WPFGrid()
        tab.Background = SolidColorBrush(CLR_BG)
        tab.Margin = Thickness(0, 8, 0, 0)
        _row(tab, GridLength.Auto)                   # format cards
        _row(tab, GridLength(1, GridUnitType.Star))  # settings

        # Format cards row
        cards = StackPanel()
        cards.Orientation = Orientation.Horizontal
        cards.Margin = Thickness(0, 0, 0, 10)
        WPFGrid.SetRow(cards, 0); tab.Children.Add(cards)

        self._fmt_cards   = {}  # key → Border (card)
        self._fmt_checked = {}  # key → bool

        for (key, label) in [(u'pdf', u'PDF'), (u'dwg', u'DWG')]:
            cb = CheckBox()
            cb.Content   = u''   # no label — big icon text is the label
            cb.IsChecked = (key == u'pdf')
            cb.Margin    = Thickness(0, 0, 0, 0)
            cb.VerticalAlignment = VerticalAlignment.Center

            card = Border()
            card.Background    = SolidColorBrush(CLR_CARD if key == u'pdf' else CLR_BG)
            card.BorderBrush   = SolidColorBrush(CLR_BORDER)
            card.BorderThickness = Thickness(1)
            card.CornerRadius   = System.Windows.CornerRadius(4)
            card.Padding        = Thickness(14, 8, 14, 8)
            card.Margin         = Thickness(0, 0, 8, 0)
            card.Cursor         = System.Windows.Input.Cursors.Hand

            csp = StackPanel()
            csp.Orientation = Orientation.Horizontal

            # File icon label
            icon_lbl = TextBlock()
            icon_lbl.Text      = label
            icon_lbl.FontSize  = 22
            icon_lbl.FontWeight = System.Windows.FontWeights.Bold
            icon_lbl.Foreground = SolidColorBrush(CLR_ACCENT)
            icon_lbl.Margin    = Thickness(0, 0, 8, 0)
            icon_lbl.VerticalAlignment = VerticalAlignment.Center
            csp.Children.Add(icon_lbl)

            # Card shows only the big format label; checkbox sits outside card
            # so clicking the label area activates the panel, checkbox toggles export
            inner = StackPanel()
            inner.VerticalAlignment = VerticalAlignment.Center
            inner.Children.Add(cb)
            csp.Children.Add(inner)
            card.Child = csp

            # Active underline
            underline = Border()
            underline.Height = 3
            underline.Background = SolidColorBrush(CLR_ACCENT)
            underline.Visibility = Visibility.Visible if key == u'pdf' else Visibility.Collapsed
            card.Tag = underline

            wrap = StackPanel()
            wrap.Children.Add(card)
            wrap.Children.Add(underline)
            cards.Children.Add(wrap)

            self._fmt_cards[key] = card
            self._fmt_checked[key] = (key == u'pdf')

            def make_click_handler(k, c_border, ul):
                def handler(s, e):
                    self._activate_fmt(k)
                return handler
            card.MouseLeftButtonUp += make_click_handler(key, card, underline)
            cb_ref = [cb, key]
            def make_cb_handler(r):
                def h(s, e):
                    k = r[1]
                    self._fmt_checked[k] = (r[0].IsChecked == True)
                    self._activate_fmt(k)
                return h
            cb.Checked   += make_cb_handler(cb_ref)
            cb.Unchecked += make_cb_handler(cb_ref)

        # Settings panels (swapped)
        self._fmt_panels = {}
        sp_wrap = Border()
        sp_wrap.Background = SolidColorBrush(CLR_CARD)
        sp_wrap.BorderBrush = SolidColorBrush(CLR_BORDER)
        sp_wrap.BorderThickness = Thickness(1)
        sp_wrap.CornerRadius = System.Windows.CornerRadius(4)
        sp_wrap.Padding = Thickness(16, 12, 16, 12)
        WPFGrid.SetRow(sp_wrap, 1); tab.Children.Add(sp_wrap)

        self._sp_container = WPFGrid()  # holds pdf/dwg panels
        sp_wrap.Child = self._sp_container

        self._fmt_panels[u'pdf'] = self._build_pdf_panel()
        self._fmt_panels[u'dwg'] = self._build_dwg_panel()

        for key, pnl in self._fmt_panels.items():
            pnl.Visibility = Visibility.Visible if key == u'pdf' else Visibility.Collapsed
            self._sp_container.Children.Add(pnl)

        return tab

    def _activate_fmt(self, key):
        for k, card in self._fmt_cards.items():
            is_active = (k == key)
            card.Background = SolidColorBrush(CLR_CARD if is_active else CLR_BG)
            ul = card.Tag
            if ul is not None:
                ul.Visibility = Visibility.Visible if is_active else Visibility.Collapsed
        for k, pnl in self._fmt_panels.items():
            pnl.Visibility = Visibility.Visible if k == key else Visibility.Collapsed

    def _build_pdf_panel(self):
        sv = ScrollViewer()
        sv.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
        sv.HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled

        root = WPFGrid()
        _col(root, GridLength(1, GridUnitType.Star))
        _col(root, GridLength(20))
        _col(root, GridLength(1, GridUnitType.Star))
        _col(root, GridLength(20))
        _col(root, GridLength(1, GridUnitType.Star))

        def _gb(title):
            # GroupBox-style card
            b = Border()
            b.BorderBrush = SolidColorBrush(CLR_BORDER)
            b.BorderThickness = Thickness(1)
            b.CornerRadius = System.Windows.CornerRadius(3)
            b.Margin = Thickness(0, 0, 0, 10)
            b.Padding = Thickness(10, 8, 10, 8)
            b.Background = SolidColorBrush(CLR_CARD)
            hdr = _section_lbl(title)
            hdr.Margin = Thickness(0, 0, 0, 8)
            sp = StackPanel()
            sp.Children.Add(hdr)
            b.Child = sp
            return b, sp

        def _field(sp, label, ctrl):
            fsq = StackPanel(); fsq.Margin = Thickness(0, 0, 0, 8)
            l = TextBlock(); l.Text = label; l.FontSize = 10
            l.Foreground = SolidColorBrush(CLR_MUTED)
            l.Margin = Thickness(0, 0, 0, 3)
            fsq.Children.Add(l); fsq.Children.Add(ctrl)
            sp.Children.Add(fsq)

        def _cmb(items, sel=0):
            cb = ComboBox(); cb.FontSize = 11; cb.Height = 28
            cb.BorderBrush = SolidColorBrush(CLR_BORDER)
            for it in items: cb.Items.Add(it)
            cb.SelectedIndex = sel; return cb

        def _chk(sp, text, checked=False):
            cb = CheckBox(); cb.Content = text; cb.IsChecked = checked
            cb.FontSize = 11; cb.Margin = Thickness(0, 0, 0, 6)
            sp.Children.Add(cb); return cb

        def _radio(sp, text, checked=False):
            rb = RadioButton(); rb.Content = text; rb.IsChecked = checked
            rb.FontSize = 11; rb.Margin = Thickness(0, 0, 0, 4)
            sp.Children.Add(rb); return rb

        # ── Col A: Paper Placement + Zoom + Printer ───
        col_a = StackPanel(); WPFGrid.SetColumn(col_a, 0); root.Children.Add(col_a)

        # Paper Placement GroupBox
        gb_paper, sp_paper = _gb(u'Paper Placement')
        self._pdf_rb_center = _radio(sp_paper, u'Center', checked=True)
        self._pdf_rb_offset = _radio(sp_paper, u'Offset from corner')

        # X / Y in mm — only editable when Offset is selected
        xy_row = WPFGrid()
        _col(xy_row, GridLength.Auto); _col(xy_row, GridLength(1, GridUnitType.Star))
        _col(xy_row, GridLength(10));  _col(xy_row, GridLength.Auto)
        _col(xy_row, GridLength(1, GridUnitType.Star))
        xy_row.Margin = Thickness(0, 4, 0, 4)
        for i, txt in enumerate([u'X (mm)', u'', u'', u'Y (mm)', u'']):
            if txt:
                lx = TextBlock(); lx.Text = txt; lx.FontSize = 10
                lx.Foreground = SolidColorBrush(CLR_MUTED)
                lx.VerticalAlignment = VerticalAlignment.Center
                WPFGrid.SetColumn(lx, i); xy_row.Children.Add(lx)
        self._pdf_x = TextBox(); self._pdf_x.Text = u'0.00'; self._pdf_x.FontSize = 10
        self._pdf_x.Height = 24; self._pdf_x.BorderBrush = SolidColorBrush(CLR_BORDER)
        self._pdf_x.IsEnabled = False
        WPFGrid.SetColumn(self._pdf_x, 1); xy_row.Children.Add(self._pdf_x)
        self._pdf_y = TextBox(); self._pdf_y.Text = u'0.00'; self._pdf_y.FontSize = 10
        self._pdf_y.Height = 24; self._pdf_y.BorderBrush = SolidColorBrush(CLR_BORDER)
        self._pdf_y.IsEnabled = False
        WPFGrid.SetColumn(self._pdf_y, 4); xy_row.Children.Add(self._pdf_y)
        sp_paper.Children.Add(xy_row)

        self._pdf_margin = _cmb([u'No Margin', u'Printer Limit', u'User Defined'])
        self._pdf_margin.IsEnabled = False
        _field(sp_paper, u'Margin', self._pdf_margin)

        # Offset from corner: enable Margin dropdown
        # X/Y only enabled when Margin = User Defined
        def _on_placement(ss, ev):
            is_offset = (self._pdf_rb_offset.IsChecked == True)
            self._pdf_margin.IsEnabled = is_offset
            is_user = (is_offset and
                       str(self._pdf_margin.SelectedItem or u'') == u'User Defined')
            self._pdf_x.IsEnabled = is_user
            self._pdf_y.IsEnabled = is_user

        def _on_margin_change(ss, ev):
            is_offset = (self._pdf_rb_offset.IsChecked == True)
            is_user = (is_offset and
                       str(self._pdf_margin.SelectedItem or u'') == u'User Defined')
            self._pdf_x.IsEnabled = is_user
            self._pdf_y.IsEnabled = is_user

        self._pdf_rb_center.Checked      += _on_placement
        self._pdf_rb_offset.Checked      += _on_placement
        self._pdf_margin.SelectionChanged += _on_margin_change
        col_a.Children.Add(gb_paper)

        # Zoom GroupBox
        gb_zoom, sp_zoom = _gb(u'Zoom')
        self._pdf_rb_fit  = _radio(sp_zoom, u'Fit to Page', checked=False)
        self._pdf_rb_fit.GroupName = u'pdf_zoom'
        zoom_row = StackPanel(); zoom_row.Orientation = Orientation.Horizontal
        zoom_row.Margin = Thickness(0, 0, 0, 4)
        self._pdf_rb_zoom = RadioButton(); self._pdf_rb_zoom.Content = u'Zoom'
        self._pdf_rb_zoom.GroupName = u'pdf_zoom'
        self._pdf_rb_zoom.IsChecked = True
        self._pdf_rb_zoom.FontSize = 11; self._pdf_rb_zoom.Margin = Thickness(0, 0, 8, 0)
        self._pdf_rb_zoom.VerticalAlignment = VerticalAlignment.Center
        zoom_row.Children.Add(self._pdf_rb_zoom)
        self._pdf_zoom_pct = TextBox(); self._pdf_zoom_pct.Text = u'100'
        self._pdf_zoom_pct.Width = 50; self._pdf_zoom_pct.Height = 24
        self._pdf_zoom_pct.FontSize = 11; self._pdf_zoom_pct.IsEnabled = True
        self._pdf_zoom_pct.BorderBrush = SolidColorBrush(CLR_BORDER)
        self._pdf_zoom_pct.VerticalContentAlignment = VerticalAlignment.Center
        zoom_row.Children.Add(self._pdf_zoom_pct)
        pct_lbl = TextBlock(); pct_lbl.Text = u' %'
        pct_lbl.VerticalAlignment = VerticalAlignment.Center; pct_lbl.FontSize = 11
        zoom_row.Children.Add(pct_lbl)
        sp_zoom.Children.Add(zoom_row)
        def _on_zoom_rb(ss, ev):
            self._pdf_zoom_pct.IsEnabled = (self._pdf_rb_zoom.IsChecked == True)
        self._pdf_rb_zoom.Checked   += _on_zoom_rb
        self._pdf_rb_fit.Checked    += _on_zoom_rb
        col_a.Children.Add(gb_zoom)

        # Printer GroupBox
        gb_prt, sp_prt = _gb(u'Printer')
        self._pdf_printer = _cmb([u'PDF24', u'Microsoft Print to PDF',
                                   u'Foxit PDF Printer', u'Adobe PDF'])
        _field(sp_prt, u'Printer', self._pdf_printer)
        col_a.Children.Add(gb_prt)

        # ── Col B: Hidden Line Views + Appearance ─────
        col_b = StackPanel(); WPFGrid.SetColumn(col_b, 2); root.Children.Add(col_b)

        gb_hidden, sp_hidden = _gb(u'Hidden Line Views')
        hl_lbl = TextBlock(); hl_lbl.Text = u'Remove Lines Using'
        hl_lbl.FontSize = 10; hl_lbl.Foreground = SolidColorBrush(CLR_MUTED)
        hl_lbl.Margin = Thickness(0, 0, 0, 6)
        sp_hidden.Children.Add(hl_lbl)
        self._pdf_rb_vector = _radio(sp_hidden, u'Vector Processing', checked=True)
        self._pdf_rb_raster = _radio(sp_hidden, u'Raster Processing')
        col_b.Children.Add(gb_hidden)

        gb_appear, sp_appear = _gb(u'Appearance')
        self._pdf_raster_q = _cmb([u'Low', u'Medium', u'High', u'Presentation'], sel=2)
        self._pdf_colors   = _cmb([u'Color', u'Black Lines', u'Grayscale'])
        _field(sp_appear, u'Raster Quality', self._pdf_raster_q)
        _field(sp_appear, u'Colors', self._pdf_colors)
        col_b.Children.Add(gb_appear)

        # ── Col C: Options + File ─────────────────────
        col_c = StackPanel(); WPFGrid.SetColumn(col_c, 4); root.Children.Add(col_c)

        gb_opt, sp_opt = _gb(u'Options')
        self._pdf_chk_links  = _chk(sp_opt, u'View links in blue (Color prints only)', False)
        self._pdf_chk_ref    = _chk(sp_opt, u'Hide ref/work planes',    True)
        self._pdf_chk_unref  = _chk(sp_opt, u'Hide unreferenced view tags', True)
        self._pdf_chk_scope  = _chk(sp_opt, u'Hide scope boxes',        True)
        self._pdf_chk_crop   = _chk(sp_opt, u'Hide crop boundaries',    True)
        self._pdf_chk_half   = _chk(sp_opt, u'Replace halftone with thin lines', False)
        self._pdf_chk_region = _chk(sp_opt, u'Region edges mask coincident lines', False)
        col_c.Children.Add(gb_opt)

        gb_file, sp_file = _gb(u'File')
        self._pdf_rb_separate = _radio(sp_file, u'Create separate files', checked=True)
        self._pdf_rb_combine  = _radio(sp_file, u'Combine multiple views/sheets into a single file')

        self._pdf_chk_keep_sz = _chk(sp_file, u'Keep Paper Size & Orientation', False)
        self._pdf_chk_keep_sz.IsEnabled = False

        # Custom File Name (shown when Combine)
        lbl_cfn = TextBlock(); lbl_cfn.Text = u'Custom File Name'
        lbl_cfn.FontSize = 10; lbl_cfn.Foreground = SolidColorBrush(CLR_MUTED)
        lbl_cfn.Margin = Thickness(0, 6, 0, 3); lbl_cfn.Visibility = Visibility.Collapsed
        sp_file.Children.Add(lbl_cfn)
        self._pdf_custom_name = TextBox()
        self._pdf_custom_name.FontSize = 11; self._pdf_custom_name.Height = 28
        self._pdf_custom_name.BorderBrush = SolidColorBrush(CLR_BORDER)
        self._pdf_custom_name.Margin = Thickness(0, 0, 0, 6)
        self._pdf_custom_name.Visibility = Visibility.Collapsed
        sp_file.Children.Add(self._pdf_custom_name)

        # Order sheets/views button (shown when Combine)
        self._btn_order = _make_btn(u'Order Sheets / Views ▾')
        self._btn_order.Margin = Thickness(0, 0, 0, 0)
        self._btn_order.Visibility = Visibility.Collapsed
        self._btn_order.Click += lambda ss, ev: self._show_order_dialog()
        sp_file.Children.Add(self._btn_order)

        def _on_file_rb(ss, ev):
            is_comb = (self._pdf_rb_combine.IsChecked == True)
            self._pdf_chk_keep_sz.IsEnabled       = is_comb
            lbl_cfn.Visibility                    = Visibility.Visible if is_comb else Visibility.Collapsed
            self._pdf_custom_name.Visibility      = Visibility.Visible if is_comb else Visibility.Collapsed
            self._btn_order.Visibility            = Visibility.Visible if is_comb else Visibility.Collapsed
        self._pdf_rb_separate.Checked += _on_file_rb
        self._pdf_rb_combine.Checked  += _on_file_rb
        col_c.Children.Add(gb_file)

        sv.Content = root
        return sv

    def _show_order_dialog(self):
        """Popup to reorder sheets/views for combined PDF export.
        Layout: DataGrid [Sheet Number | Sheet/View Name] + reorder buttons + OK.
        """
        dlg = Window()
        dlg.Title = u'Order Sheets / Views'
        dlg.Width = 540; dlg.Height = 660
        dlg.ResizeMode = System.Windows.ResizeMode.CanResizeWithGrip
        dlg.WindowStartupLocation = WindowStartupLocation.CenterOwner
        dlg.Background = SolidColorBrush(CLR_BG)
        dlg.Owner = self

        # Use saved custom order if available, else use checked rows from Selection
        if hasattr(self, '_pdf_order') and self._pdf_order:
            checked_ids = set(r._id.IntegerValue for r in self._grid_rows if r.Checked and r._id)
            order_items = [oi for oi in self._pdf_order
                           if oi._id and oi._id.IntegerValue in checked_ids]
            # Add any newly checked rows not yet in order list
            in_order = set(oi._id.IntegerValue for oi in order_items if oi._id)
            for r in self._grid_rows:
                if r.Checked and r._id and r._id.IntegerValue not in in_order:
                    order_items.append(OrderItem(r.Number or u'', r.Name or u'', r._id))
        else:
            rows = [r for r in self._grid_rows if r.Checked]
            order_items = [OrderItem(r.Number or u'', r.Name or u'', r._id)
                           for r in rows]

        root = WPFGrid(); root.Margin = Thickness(0)
        _row(root, GridLength(1, GridUnitType.Star))   # grid
        _row(root, GridLength.Auto)                    # reorder buttons
        _row(root, GridLength.Auto)                    # footer (total + OK)

        # DataGrid
        dg = DataGrid()
        dg.AutoGenerateColumns = False; dg.CanUserAddRows = False
        dg.IsReadOnly = True; dg.FontSize = 11
        dg.SelectionMode = System.Windows.Controls.DataGridSelectionMode.Single
        dg.RowBackground = SolidColorBrush(CLR_CARD)
        dg.AlternatingRowBackground = SolidColorBrush(CLR_ALT)
        dg.BorderBrush = SolidColorBrush(CLR_BORDER); dg.BorderThickness = Thickness(1)
        dg.GridLinesVisibility = System.Windows.Controls.DataGridGridLinesVisibility.Horizontal
        dg.HorizontalGridLinesBrush = SolidColorBrush(Color.FromRgb(220, 210, 190))
        dg.Background = SolidColorBrush(CLR_CARD)
        DGL = System.Windows.Controls.DataGridLength; DGLU = System.Windows.Controls.DataGridLengthUnitType

        c1 = DataGridTextColumn(); c1.Header = u'Sheet Number'
        c1.Binding = System.Windows.Data.Binding(u'num')
        c1.Width = DGL(120); c1.IsReadOnly = True
        dg.Columns.Add(c1)
        c2 = DataGridTextColumn(); c2.Header = u'Sheet / View Name'
        c2.Binding = System.Windows.Data.Binding(u'name')
        c2.Width = DGL(1, DGLU.Star); c2.IsReadOnly = True
        dg.Columns.Add(c2)

        def _refresh_order_dg():
            col2 = ObservableCollection[object]()
            for it in order_items: col2.Add(it)
            dg.ItemsSource = col2

        _refresh_order_dg()

        dg_wrap = Border(); dg_wrap.BorderBrush = SolidColorBrush(CLR_BORDER)
        dg_wrap.BorderThickness = Thickness(1); dg_wrap.Margin = Thickness(12, 12, 12, 0)
        dg_wrap.Child = dg
        WPFGrid.SetRow(dg_wrap, 0); root.Children.Add(dg_wrap)

        # Reorder buttons
        btn_bar = StackPanel(); btn_bar.Orientation = Orientation.Horizontal
        btn_bar.HorizontalAlignment = HorizontalAlignment.Center
        btn_bar.Margin = Thickness(12, 8, 12, 4)

        def move_item(delta):
            idx = dg.SelectedIndex
            if idx < 0 or not order_items: return
            if delta <= -999:  ni = 0
            elif delta >= 999: ni = len(order_items) - 1
            else:              ni = max(0, min(len(order_items)-1, idx+delta))
            if ni == idx: return
            order_items.insert(ni, order_items.pop(idx))
            _refresh_order_dg()
            dg.SelectedIndex = ni

        def reset_order():
            order_items.sort(key=lambda x: x.num)
            _refresh_order_dg()

        for (sym, delta) in [(u'\u25b2\u25b2',-999),(u'\u25b2',-1),(u'\u25bc',1),(u'\u25bc\u25bc',999)]:
            def mk(d):
                def h(ss,ev): move_item(d)
                return h
            b = _make_btn(sym, width=36, height=36)
            b.Margin = Thickness(4, 0, 4, 0); b.Click += mk(delta)
            btn_bar.Children.Add(b)

        btn_reset = _make_btn(u'\u21ba', width=36, height=36)
        btn_reset.Margin = Thickness(4, 0, 4, 0); btn_reset.Foreground = SolidColorBrush(CLR_ERR)
        btn_reset.Click += lambda ss, ev: reset_order()
        btn_bar.Children.Add(btn_reset)
        WPFGrid.SetRow(btn_bar, 1); root.Children.Add(btn_bar)

        # Footer: total count + OK
        footer = WPFGrid(); footer.Margin = Thickness(12, 4, 12, 12)
        _col(footer, GridLength(1, GridUnitType.Star)); _col(footer, GridLength.Auto)
        lbl_tot = TextBlock()
        lbl_tot.Text = u'Total number of items {0}'.format(len(order_items))
        lbl_tot.FontSize = 11; lbl_tot.Foreground = SolidColorBrush(CLR_MUTED)
        lbl_tot.VerticalAlignment = VerticalAlignment.Center
        WPFGrid.SetColumn(lbl_tot, 0); footer.Children.Add(lbl_tot)
        btn_ok = _make_btn(u'Ok', width=80, height=34)
        btn_ok.Click += lambda ss, ev: dlg.Close()
        WPFGrid.SetColumn(btn_ok, 1); footer.Children.Add(btn_ok)
        WPFGrid.SetRow(footer, 2); root.Children.Add(footer)

        dlg.Content = root
        dlg.ShowDialog()

        # Save new order to _pdf_order (used by combine export)
        self._pdf_order = list(order_items)

    def _build_dwg_panel(self):
        sv = ScrollViewer()
        sv.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
        sv.HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled

        root = StackPanel()
        root.Margin = Thickness(0, 0, 0, 0)

        def _gb_border(title):
            outer = Border()
            outer.BorderBrush = SolidColorBrush(CLR_BORDER)
            outer.BorderThickness = Thickness(1)
            outer.CornerRadius = System.Windows.CornerRadius(3)
            outer.Padding = Thickness(12, 10, 12, 10)
            outer.Margin = Thickness(0, 0, 0, 10)
            outer.Background = SolidColorBrush(CLR_CARD)
            sp = StackPanel()
            lbl = _section_lbl(title)
            lbl.Margin = Thickness(0, 0, 0, 8)
            sp.Children.Add(lbl)
            outer.Child = sp
            return outer, sp

        def _field(sp, label, ctrl):
            fsq = StackPanel(); fsq.Margin = Thickness(0, 0, 0, 8)
            l = TextBlock(); l.Text = label; l.FontSize = 10
            l.Foreground = SolidColorBrush(CLR_MUTED); l.Margin = Thickness(0,0,0,3)
            fsq.Children.Add(l); fsq.Children.Add(ctrl)
            sp.Children.Add(fsq)

        def _cmb(items, sel=0):
            cb = ComboBox(); cb.FontSize = 11; cb.Height = 28
            cb.BorderBrush = SolidColorBrush(CLR_BORDER)
            for it in items: cb.Items.Add(it)
            cb.SelectedIndex = sel; return cb

        def _chk(sp, text, checked=False, enabled=True):
            cb = CheckBox(); cb.Content = text; cb.IsChecked = checked
            cb.FontSize = 11; cb.Margin = Thickness(0, 0, 0, 6)
            cb.IsEnabled = enabled
            sp.Children.Add(cb); return cb

        # Select Export Setup GroupBox — load from Revit doc
        gb_setup, sp_setup = _gb_border(u'Select Export Setup')
        dwg_setup_names = [u'<in-session export settings>']
        try:
            from Autodesk.Revit.DB import DWGExportOptions as _DWGO
            # Collect all named export setups stored in the document
            setup_collector = (FilteredElementCollector(doc)
                               .OfClass(DWGExportOptions))
            for setup in setup_collector:
                try:
                    n = setup.Name if setup.Name else None
                    if n and n not in dwg_setup_names:
                        dwg_setup_names.append(n)
                except Exception:
                    pass
        except Exception:
            pass
        # Fallback: try ExportLayerTable / DWGExportSetup class
        if len(dwg_setup_names) == 1:
            try:
                from Autodesk.Revit.DB import ExportLayerMapping
                for elm in (FilteredElementCollector(doc)
                            .OfClass(ExportLayerMapping)):
                    try:
                        n = elm.Name
                        if n and n not in dwg_setup_names:
                            dwg_setup_names.append(n)
                    except Exception:
                        pass
            except Exception:
                pass
        self._dwg_setup = _cmb(dwg_setup_names)
        self._dwg_setup_names = dwg_setup_names
        _field(sp_setup, u'Name', self._dwg_setup)

        # DWG Version dropdown
        self._dwg_ver = _cmb([
            u'AutoCAD 2018  (R24)',
            u'AutoCAD 2013  (R19)',
            u'AutoCAD 2010  (R18)',
            u'AutoCAD 2007  (R17)',
            u'AutoCAD 2004  (R16)',
            u'AutoCAD 2000  (R15)',
        ])
        _field(sp_setup, u'DWG File Format', self._dwg_ver)
        root.Children.Add(gb_setup)

        # Options GroupBox
        gb_opt, sp_opt = _gb_border(u'Options')
        self._dwg_chk_xref = _chk(sp_opt, u'Export views on sheets and links as external references', False)
        self._dwg_chk_bind = _chk(sp_opt, u'Clean .png, .jpeg, .tif files after export', False)
        self._dwg_chk_pcp  = _chk(sp_opt, u'Clean .pcp files after export', False)
        root.Children.Add(gb_opt)

        sv.Content = root
        return sv

    # ══════════════════════════════════════════════════
    # TAB 3 — CREATE
    # ══════════════════════════════════════════════════
    def _build_create_tab(self):
        tab = WPFGrid()
        tab.Background = SolidColorBrush(CLR_BG)
        tab.Margin = Thickness(0, 8, 0, 0)
        _row(tab, GridLength.Auto)                    # export rules + progress
        _row(tab, GridLength.Auto)                    # sub-toolbar
        _row(tab, GridLength(1, GridUnitType.Star))   # preview grid

        # ── Row 0: Export Rules card (left) + Progress card (right)
        top_grid = WPFGrid()
        top_grid.Margin = Thickness(0, 0, 0, 10)
        _col(top_grid, GridLength(1, GridUnitType.Star))
        _col(top_grid, GridLength(16))
        _col(top_grid, GridLength(360))
        WPFGrid.SetRow(top_grid, 0); tab.Children.Add(top_grid)

        # Export Rules card
        er_card = _card(padding=14)
        er = WPFGrid()
        _row(er, GridLength.Auto)  # label + folder row
        _row(er, GridLength.Auto)  # env hint
        _row(er, GridLength.Auto)  # radios

        # Folder row
        fl_row = WPFGrid()
        _col(fl_row, GridLength.Auto)
        _col(fl_row, GridLength(1, GridUnitType.Star))
        _col(fl_row, GridLength.Auto)
        fl_row.Margin = Thickness(0, 0, 0, 4)

        fl_lbl = TextBlock(); fl_lbl.Text = u'Folder'
        fl_lbl.FontSize = 10; fl_lbl.Foreground = SolidColorBrush(CLR_MUTED)
        fl_lbl.VerticalAlignment = VerticalAlignment.Center
        fl_lbl.Margin = Thickness(0, 0, 8, 0)
        WPFGrid.SetColumn(fl_lbl, 0); fl_row.Children.Add(fl_lbl)

        self._txt_folder = TextBox()
        self._txt_folder.FontSize = 11; self._txt_folder.Height = 28
        self._txt_folder.BorderBrush = SolidColorBrush(CLR_BORDER)
        self._txt_folder.VerticalContentAlignment = VerticalAlignment.Center
        WPFGrid.SetColumn(self._txt_folder, 1); fl_row.Children.Add(self._txt_folder)

        btn_br = _make_btn(u'\u2026', width=32, height=28)
        btn_br.Margin = Thickness(6, 0, 0, 0)
        btn_br.Click += lambda s, e: self._on_browse()
        WPFGrid.SetColumn(btn_br, 2); fl_row.Children.Add(btn_br)
        WPFGrid.SetRow(fl_row, 0); er.Children.Add(fl_row)

        env_hint = TextBlock()
        env_hint.Text = u'Supports: %UserName%, %Y%, %m%, %d%'
        env_hint.FontSize = 9; env_hint.Foreground = SolidColorBrush(CLR_MUTED)
        env_hint.Margin = Thickness(0, 2, 0, 6)
        WPFGrid.SetRow(env_hint, 1); er.Children.Add(env_hint)

        self._rb_same = RadioButton()
        self._rb_same.Content = u'Save all files in the same folder'
        self._rb_same.IsChecked = True; self._rb_same.FontSize = 11
        self._rb_split = RadioButton()
        self._rb_split.Content = u'Save and split files by file format'
        self._rb_split.FontSize = 11
        rd_sp = StackPanel()
        rd_sp.Children.Add(self._rb_same); rd_sp.Children.Add(self._rb_split)
        WPFGrid.SetRow(rd_sp, 2); er.Children.Add(rd_sp)

        er_card.Child = er
        WPFGrid.SetColumn(er_card, 0); top_grid.Children.Add(er_card)

        # Progress card
        pr_card = _card(padding=14)
        pr = StackPanel()
        self._lbl_progress = TextBlock()
        self._lbl_progress.Text = u'Completed  0%'
        self._lbl_progress.FontSize = 12
        self._lbl_progress.Foreground = SolidColorBrush(CLR_MUTED)
        self._lbl_progress.Margin = Thickness(0, 0, 0, 10)
        pr.Children.Add(self._lbl_progress)




        pr_card.Child = pr
        WPFGrid.SetColumn(pr_card, 2); top_grid.Children.Add(pr_card)

        # ── Row 1: sub-toolbar
        sub = Border()
        sub.Background = SolidColorBrush(CLR_HEADER)
        sub.Padding    = Thickness(10, 6, 10, 6)
        sub.CornerRadius = System.Windows.CornerRadius(4, 4, 0, 0)
        sub.Margin     = Thickness(0, 0, 0, 0)
        WPFGrid.SetRow(sub, 1); tab.Children.Add(sub)

        sub_sp = StackPanel(); sub_sp.Orientation = Orientation.Horizontal

        self._btn_paper = _make_btn(u'Set Paper Size \u25be')
        self._btn_paper.Margin = Thickness(0, 0, 8, 0)
        self._btn_paper.Click += self._show_paper_menu
        sub_sp.Children.Add(self._btn_paper)

        self._btn_orient = _make_btn(u'Set Orientation \u25be')
        self._btn_orient.Margin = Thickness(0, 0, 8, 0)
        self._btn_orient.Click += self._show_orient_menu
        sub_sp.Children.Add(self._btn_orient)
        sub.Child = sub_sp

        # ── Row 2: preview grid
        dg_wrap = Border()
        dg_wrap.Background = SolidColorBrush(CLR_CARD)
        dg_wrap.BorderBrush = SolidColorBrush(CLR_BORDER)
        dg_wrap.BorderThickness = Thickness(1)
        dg_wrap.CornerRadius = System.Windows.CornerRadius(0, 0, 4, 4)
        WPFGrid.SetRow(dg_wrap, 2); tab.Children.Add(dg_wrap)

        self._dg_export = DataGrid()
        self._dg_export.AutoGenerateColumns = False
        self._dg_export.CanUserAddRows    = False
        self._dg_export.IsReadOnly        = True
        self._dg_export.FontSize          = 11
        self._dg_export.SelectionMode     = System.Windows.Controls.DataGridSelectionMode.Extended
        self._dg_export.GridLinesVisibility = System.Windows.Controls.DataGridGridLinesVisibility.Horizontal
        self._dg_export.HorizontalGridLinesBrush = SolidColorBrush(Color.FromRgb(230, 220, 195))
        self._dg_export.Background        = SolidColorBrush(CLR_CARD)
        self._dg_export.AlternationCount  = 2
        # RowBackground/AlternatingRowBackground intentionally NOT set here —
        # they override selection highlight. All row colors handled via XAML RowStyle.
        try:
            import System.Windows.Markup as _markup
            _row_xaml = (
                u'<Style xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" '
                u'       TargetType="{x:Type DataGridRow}" '
                u'       xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"> '
                u'  <Setter Property="Background" Value="#FFFEF7"/> '
                u'  <Style.Triggers> '
                u'    <Trigger Property="AlternationIndex" Value="1"> '
                u'      <Setter Property="Background" Value="#FFF8EE"/> '
                u'    </Trigger> '
                u'    <Trigger Property="IsSelected" Value="True"> '
                u'      <Setter Property="Background" Value="#ADD6F0"/> '
                u'      <Setter Property="Foreground" Value="#1E1E1E"/> '
                u'    </Trigger> '
                u'  </Style.Triggers> '
                u'</Style>'
            )
            self._dg_export.RowStyle = _markup.XamlReader.Parse(_row_xaml)
        except Exception:
            pass

        for (hdr, path, w, is_star) in [
            (u'View/Sheet Number', u'Number',   120, False),
            (u'View/Sheet Name',   u'Name',       1, True),
            (u'Output File Name',  u'FileName', 180, False),
            (u'Format',            u'Format',    60, False),
            (u'Size',              u'Size',      110, False),
            (u'Orientation',       u'Orient',     90, False),
            (u'Progress',          u'Progress',  160, False),
        ]:
            c = DataGridTextColumn()
            c.Header = hdr
            c.Binding = System.Windows.Data.Binding(path)
            c.IsReadOnly = True
            if is_star:
                c.Width = System.Windows.Controls.DataGridLength(
                    w, System.Windows.Controls.DataGridLengthUnitType.Star)
            else:
                c.Width = System.Windows.Controls.DataGridLength(w)
            self._dg_export.Columns.Add(c)

        dg_wrap.Child = self._dg_export
        self._export_rows = []

        return tab


    # ══════════════════════════════════════════════════
    # WINDOW EVENTS & NAVIGATION
    # ══════════════════════════════════════════════════
    def _deferred_load(self):
        self._load_data()

    def _nav(self, delta):
        idx = self._tc.SelectedIndex
        n   = self._tc.Items.Count
        new = max(0, min(n - 1, idx + delta))
        self._tc.SelectedIndex = new

    def _on_tab_changed(self, s, e):
        idx = self._tc.SelectedIndex
        # Show Create button only on last tab
        self._btn_create.Visibility = (
            Visibility.Visible if idx == 2 else Visibility.Collapsed)
        self._btn_next.Visibility = (
            Visibility.Collapsed if idx == 2 else Visibility.Visible)
        # Refresh create tab when activated
        if idx == 2:
            self._refresh_create_tab()
        # Hide row-selected on non-selection tabs
        if idx != 0:
            self._lbl_status.Text = self._status_text()

    # ══════════════════════════════════════════════════
    # SELECTION TAB LOGIC
    # ══════════════════════════════════════════════════
    def _load_data(self):
        self._all_data   = (collect_sheets() if self._mode == u'Sheet'
                            else collect_views())
        self._active_set = None
        self._active_src = None
        self._upd_filter_strip()
        self._apply_filters()

    def _rebuild_grid_columns(self):
        DGL = System.Windows.Controls.DataGridLength
        DGLU = System.Windows.Controls.DataGridLengthUnitType
        while self._dg.Columns.Count > 1:
            self._dg.Columns.RemoveAt(1)

        def _add(hdr, path, w, star=False, ro=True):
            dgc = DataGridTextColumn()
            dgc.Header = hdr
            dgc.Binding = System.Windows.Data.Binding(path)
            dgc.IsReadOnly = ro
            dgc.Width = DGL(w, DGLU.Star) if star else DGL(w)
            self._dg.Columns.Add(dgc)

        if self._mode == u'View':
            _add(u'View Name', u'Name', 1, star=True)
            # ViewType column with filter ComboBox in header
            vt_hdr = ComboBox()
            vt_hdr.FontSize = 10
            vt_hdr.Background = SolidColorBrush(CLR_HEADER)
            vt_hdr.BorderThickness = Thickness(0)
            vt_hdr.Margin = Thickness(-2, 0, -2, 0)
            for lbl in [u'All Views', u'3D', u'Area Plan', u'Ceiling Plan',
                        u'Detail', u'Drafting View', u'Elevation', u'Floor Plan',
                        u'Legend', u'Rendering', u'Section', u'Walkthrough']:
                vt_hdr.Items.Add(lbl)
            vt_hdr.SelectedIndex = 0
            self._vt_filter_cmb = vt_hdr
            def _vt_h(ss, ev):
                self._on_vt_filter(vt_hdr)
            vt_hdr.SelectionChanged += _vt_h
            _add(vt_hdr,              u'ViewType',     120)
            _add(u'View Scale',       u'ViewScale',    100)
            _add(u'Detail Level',     u'DetailLevel',   90)
            _add(u'Discipline',       u'Discipline',   130)
            _add(u'Custom File Name', u'Custom',       180, ro=False)
        else:
            _add(u'Sheet Number',     u'Number',       110)
            _add(u'Sheet Name',       u'Name',         1, star=True)
            _add(u'Revision',         u'Revision',      70)
            _add(u'Size',             u'Size',          120)
            _add(u'Custom File Name', u'Custom',       180, ro=False)

    def _on_vt_filter(self, cmb):
        sel = str(cmb.SelectedItem or u'All Views')
        self._view_type_filter = u'' if sel == u'All Views' else sel
        self._apply_filters()

    def _on_mode(self):
        new_mode = u'Sheet' if (self._rb_sh.IsChecked == True) else u'View'
        if new_mode != self._mode:
            # Save current checked state before switching mode
            self._save_checked_state()
            self._mode = new_mode
            self._view_type_filter = u''
            self._rebuild_grid_columns()
            self._load_data()

    def _save_checked_state(self):
        checked = set(r._id.IntegerValue for r in self._grid_rows
                      if r.Checked and r._id is not None)
        if self._mode == u'Sheet':
            self._checked_sheet = checked
        else:
            self._checked_view  = checked

    def _get_saved_checked(self):
        return self._checked_sheet if self._mode == u'Sheet' else self._checked_view

    def _srch_focus(self, got):
        if got and self._txt_srch.Text == u'Search...':
            self._txt_srch.Text = u''
        elif not got and not self._txt_srch.Text:
            self._txt_srch.Text = u'Search...'

    def _apply_filters(self):
        data = self._all_data[:]
        # V/S Set filter
        if self._active_set and self._active_src:
            if self._active_src == u'json':
                ids = self._vs_mgr.get_ids(self._active_set)
                data = [r for r in data if r['id'].IntegerValue in ids]
            else:
                for s in collect_revit_sets():
                    if s['name'] == self._active_set:
                        data = [r for r in data if r['id'].IntegerValue in s['ids']]
                        break
        # View Type filter
        if self._mode == u'View' and self._view_type_filter:
            data = [r for r in data if r.get('view_type', u'') == self._view_type_filter]

        # Search
        q = (self._txt_srch.Text or u'').strip().lower()
        if q and q != u'search...':
            data = [r for r in data
                    if q in r['number'].lower() or q in r['name'].lower()
                    or q in r.get('view_type', u'').lower()]
        # Save current checked state to mode-specific store, then restore from it
        for r in self._grid_rows:
            if r._id is not None:
                store = self._checked_sheet if self._mode == u'Sheet' else self._checked_view
                if r.Checked:
                    store.add(r._id.IntegerValue)
                else:
                    store.discard(r._id.IntegerValue)
        prev_checked = self._get_saved_checked()

        # Rebuild grid rows
        self._grid_rows = []
        for i, d in enumerate(data):
            row = SheetRow(
                num=str(i+1), number=d['number'], name=d['name'],
                revision=d['revision'], size=d.get('size', u''),
                custom=d['custom'], eid=d['id'],
                view_type=d.get('view_type', u''),
                view_scale=d.get('view_scale', u''),
                detail_level=d.get('detail_level', u''),
                discipline=d.get('discipline', u''),
            )
            # Restore checked state
            if d['id'].IntegerValue in prev_checked:
                row.Checked = True
            self._grid_rows.append(row)
        self._populate_grid()
        self._upd_status()

    def _populate_grid(self):
        col = ObservableCollection[object]()
        for r in self._grid_rows:
            col.Add(r)
        self._dg.ItemsSource = col
        # Sync header checkbox state
        try:
            if self._grid_rows:
                all_chk = all(r.Checked for r in self._grid_rows)
                any_chk = any(r.Checked for r in self._grid_rows)
                self._hdr_chk.IsChecked = True if all_chk else (None if any_chk else False)
        except Exception:
            pass

    def _on_grid_key(self, s, e):
        if e.Key == Key.Space:
            self._toggle_selected_rows()
            e.Handled = True

    def _toggle_selected_rows(self):
        # Determine new state: if ANY selected row is unchecked -> check all;
        # if ALL selected rows are checked -> uncheck all.
        sel_items = list(self._dg.SelectedItems)
        if not sel_items:
            return
        all_checked = all(getattr(r, 'Checked', False) for r in sel_items)
        new_state = not all_checked
        for r in sel_items:
            r.Checked = new_state
        self._populate_grid()
        self._upd_status()

    def _on_current_cell_chg(self, s, e):
        pass   # reserved for future use

    def _on_chk_click(self, s, e):
        """
        Method 1: Hover/click inside checkbox column (col 0) only.
          - Click: toggle the clicked row + all currently highlighted (Selected) rows.
          - Drag: check each row as cursor passes over it (see _on_mouse_move).
        Method 2: Normal WPF multi-select (click / Shift+click / Ctrl+click to
          highlight rows), then click any checkbox cell -> bulk toggle all highlighted.
        Other columns are NOT intercepted — normal WPF selection behaviour preserved.
        """
        try:
            # Hit-test: walk up visual tree to find which DataGridCell was clicked
            hit = self._dg.InputHitTest(e.GetPosition(self._dg))
            obj = hit
            in_chk_col = False
            clicked_row = None
            for _ in range(15):
                if obj is None:
                    break
                t = type(obj).__name__
                if t == u'DataGridCell':
                    in_chk_col = (self._dg.Columns.IndexOf(obj.Column) == 0)
                    break
                if t == u'DataGridRow' and clicked_row is None:
                    clicked_row = obj.Item
                try:
                    obj = System.Windows.Media.VisualTreeHelper.GetParent(obj)
                except Exception:
                    break

            if not in_chk_col:
                return   # let WPF handle normal selection in other columns

            # Find clicked row via separate walk (cell walk may reach row first)
            if clicked_row is None:
                obj = hit
                for _ in range(15):
                    if obj is None: break
                    if type(obj).__name__ == u'DataGridRow':
                        clicked_row = obj.Item; break
                    try: obj = System.Windows.Media.VisualTreeHelper.GetParent(obj)
                    except Exception: break

            if clicked_row is None or not hasattr(clicked_row, 'Checked'):
                return

            # New state: flip the clicked row; apply to ALL highlighted rows too
            new_state = not clicked_row.Checked
            clicked_row.Checked = new_state
            for r in list(self._dg.SelectedItems):
                if hasattr(r, 'Checked'):
                    r.Checked = new_state
            self._populate_grid()
            self._upd_status()
            e.Handled = True
        except Exception:
            pass

    def _on_mouse_move(self, s, e):
        """Drag-to-check: only inside checkbox column while left mouse held."""
        if e.LeftButton != System.Windows.Input.MouseButtonState.Pressed:
            return
        try:
            hit = self._dg.InputHitTest(e.GetPosition(self._dg))
            obj = hit
            in_chk_col = False
            for _ in range(10):
                if obj is None: break
                if type(obj).__name__ == u'DataGridCell':
                    in_chk_col = (self._dg.Columns.IndexOf(obj.Column) == 0)
                    break
                try: obj = System.Windows.Media.VisualTreeHelper.GetParent(obj)
                except Exception: break
            if not in_chk_col:
                return
            # Find row under cursor
            obj = hit
            for _ in range(15):
                if obj is None: break
                if type(obj).__name__ == u'DataGridRow':
                    row = obj.Item
                    if hasattr(row, 'Checked') and not row.Checked:
                        row.Checked = True
                        self._populate_grid()
                        self._upd_status()
                    break
                try: obj = System.Windows.Media.VisualTreeHelper.GetParent(obj)
                except Exception: break
        except Exception:
            pass

    def _on_cell_edit(self, s, e):
        try:
            if e.Column.Header == u'Custom File Name':
                row = e.Row.Item
                if row and hasattr(row, 'Custom'):
                    val = (row.Custom or u'').strip()
                    if row._id:
                        elem = doc.GetElement(row._id)
                        if elem:
                            write_single(elem, val)
        except Exception:
            pass

    def _upd_status(self):
        chk   = sum(1 for r in self._grid_rows if r.Checked)
        total = len(self._grid_rows)
        mode  = self._mode.lower() + u's'
        self._lbl_status.Text = u'{0} {1} selected.  Total: {2}'.format(
            chk, mode, total)
        self._lbl_status.Foreground = SolidColorBrush(
            CLR_APPLY_FG if chk > 0 else CLR_MUTED)

    def _status_text(self):
        chk   = sum(1 for r in self._grid_rows if r.Checked)
        total = len(self._grid_rows)
        mode  = self._mode.lower() + u's'
        return u'{0} {1} selected.  Total: {2}'.format(chk, mode, total)

    def get_checked_data(self):
        result = []
        for r in self._grid_rows:
            if r.Checked:
                result.append({
                    'id'    : r._id,
                    'number': r.Number,
                    'name'  : r.Name,
                    'custom': r.Custom or u'',
                })
        return result

    # ── Filter / V/S Set ─────────────────────────────
    def _upd_filter_strip(self):
        if self._active_set:
            tag = u'Tool' if self._active_src == u'json' else u'Revit'
            self._lbl_filt_txt.Text = (
                u'  Filtered [{0}]: \u201c{1}\u201d'.format(tag, self._active_set))
            self._strip_filter.Visibility = Visibility.Visible
        else:
            self._strip_filter.Visibility = Visibility.Collapsed

    def _clr_filter(self):
        self._active_set = None; self._active_src = None
        self._upd_filter_strip(); self._apply_filters()

    def _show_filter_menu(self, s, e):
        from System.Windows.Controls import ContextMenu, MenuItem
        ctx = ContextMenu()

        # Tool sets
        hdr_t = MenuItem(); hdr_t.Header = u'\u2014  Tool V/S Sets  \u2014'
        hdr_t.IsEnabled = False; ctx.Items.Add(hdr_t)
        names = self._vs_mgr.names()
        if names:
            for n in names:
                it = MenuItem(); it.Header = u'  \u25a1  ' + n
                def mk_h(nm):
                    def h(ss, ev): self._active_set = nm; self._active_src = u'json'; self._upd_filter_strip(); self._apply_filters()
                    return h
                it.Click += mk_h(n); ctx.Items.Add(it)
        else:
            emp = MenuItem(); emp.Header = u'  (None)'; emp.IsEnabled = False; ctx.Items.Add(emp)

        from System.Windows.Controls import Separator as WpfSep
        ctx.Items.Add(WpfSep())

        # Revit sets
        hdr_r = MenuItem(); hdr_r.Header = u'\u2014  Revit Sheet Sets  \u2014'
        hdr_r.IsEnabled = False; ctx.Items.Add(hdr_r)
        rsets = collect_revit_sets()
        if rsets:
            for rs in rsets:
                it = MenuItem(); it.Header = u'  \u25a1  ' + rs['name']
                def mk_rh(nm):
                    def h(ss, ev): self._active_set = nm; self._active_src = u'revit'; self._upd_filter_strip(); self._apply_filters()
                    return h
                it.Click += mk_rh(rs['name']); ctx.Items.Add(it)
        else:
            emp2 = MenuItem(); emp2.Header = u'  (None)'; emp2.IsEnabled = False; ctx.Items.Add(emp2)

        ctx.Items.Add(WpfSep())
        del_it = MenuItem(); del_it.Header = u'  \u2715  Delete Tool V/S Set...'
        del_it.Foreground = SolidColorBrush(CLR_ERR)
        del_it.Click += self._on_del_set; ctx.Items.Add(del_it)

        ctx.PlacementTarget = self._btn_flt
        ctx.IsOpen = True

    def _show_save_menu(self, s, e):
        from System.Windows.Controls import ContextMenu, MenuItem
        ctx = ContextMenu()

        save_it = MenuItem(); save_it.Header = u'  \u2714  Save selection as new Set...'
        save_it.Click += self._on_save_set; ctx.Items.Add(save_it)

        names = self._vs_mgr.names()
        if names:
            from System.Windows.Controls import Separator as WpfSep
            ctx.Items.Add(WpfSep())
            for n in names:
                ow = MenuItem(); ow.Header = u'  Overwrite: ' + n
                def mk_ow(nm):
                    def h(ss, ev): self._overwrite_set(nm)
                    return h
                ow.Click += mk_ow(n); ctx.Items.Add(ow)

        ctx.PlacementTarget = self._btn_sav
        ctx.IsOpen = True

    def _on_save_set(self, s, e):
        dlg = Window()
        dlg.Title = u'Save V/S Set'
        dlg.Width = 360
        dlg.SizeToContent = System.Windows.SizeToContent.Height
        dlg.ResizeMode = System.Windows.ResizeMode.NoResize
        dlg.WindowStartupLocation = WindowStartupLocation.CenterOwner
        dlg.Background = SolidColorBrush(CLR_BG)
        dlg.Owner = self

        g = WPFGrid(); g.Margin = Thickness(16, 14, 16, 14)
        _row(g, GridLength.Auto); _row(g, GridLength.Auto); _row(g, GridLength.Auto)
        g.Children.Add(_section_lbl(u'SET NAME'))

        txt = TextBox(); txt.Height = 28; txt.FontSize = 11
        txt.BorderBrush = SolidColorBrush(CLR_BORDER)
        txt.Margin = Thickness(0, 4, 0, 12)
        WPFGrid.SetRow(txt, 1); g.Children.Add(txt)

        btn_row_g = WPFGrid()
        _col(btn_row_g, GridLength(1, GridUnitType.Star))
        _col(btn_row_g, GridLength.Auto); _col(btn_row_g, GridLength.Auto)
        btn_ok = _make_btn(u'\u2714  Save', width=88)
        btn_ok.Margin = Thickness(0, 0, 8, 0)
        btn_can = _make_btn(u'Cancel', width=80)
        btn_can.Click += lambda ss, ev: dlg.Close()
        WPFGrid.SetColumn(btn_ok, 1); btn_row_g.Children.Add(btn_ok)
        WPFGrid.SetColumn(btn_can, 2); btn_row_g.Children.Add(btn_can)
        WPFGrid.SetRow(btn_row_g, 2); g.Children.Add(btn_row_g)
        dlg.Content = g

        result = [None]
        def do_save(ss, ev):
            result[0] = txt.Text.strip()
            dlg.Close()
        btn_ok.Click += do_save
        dlg.ShowDialog()

        name = result[0]
        if name:
            ids = [r._id for r in self._grid_rows if r.Checked]
            if not ids:
                MessageBox.Show(u'No rows checked.', u'ProSheets',
                                MessageBoxButtons.OK, MessageBoxIcon.Information)
                return
            if self._vs_mgr.save(name, ids):
                MessageBox.Show(u'Saved \u201c{0}\u201d ({1} items).'.format(name, len(ids)),
                                u'ProSheets', MessageBoxButtons.OK, MessageBoxIcon.Information)

    def _overwrite_set(self, name):
        ids = [r._id for r in self._grid_rows if r.Checked]
        if not ids:
            MessageBox.Show(u'No rows checked.', u'ProSheets',
                            MessageBoxButtons.OK, MessageBoxIcon.Information)
            return
        self._vs_mgr.save(name, ids)

    def _on_del_set(self, s, e):
        names = self._vs_mgr.names()
        if not names:
            MessageBox.Show(u'No Tool V/S Sets saved.', u'ProSheets',
                            MessageBoxButtons.OK, MessageBoxIcon.Information)
            return
        # Pick dialog
        dlg = Window()
        dlg.Title = u'Delete V/S Set'; dlg.Width = 320; dlg.Height = 240
        dlg.WindowStartupLocation = WindowStartupLocation.CenterOwner
        dlg.Background = SolidColorBrush(CLR_BG); dlg.Owner = self
        g = WPFGrid(); g.Margin = Thickness(12)
        _row(g, GridLength.Auto); _row(g, GridLength(1, GridUnitType.Star)); _row(g, GridLength.Auto)
        g.Children.Add(_section_lbl(u'SELECT SET TO DELETE'))
        lb = ListBox(); lb.FontSize = 11; lb.Margin = Thickness(0, 4, 0, 8)
        lb.BorderBrush = SolidColorBrush(CLR_BORDER)
        for n in names: lb.Items.Add(n)
        WPFGrid.SetRow(lb, 1); g.Children.Add(lb)
        brg = WPFGrid()
        _col(brg, GridLength(1, GridUnitType.Star)); _col(brg, GridLength.Auto); _col(brg, GridLength.Auto)
        btn_del = _make_btn(u'\u2715  Delete', width=88); btn_del.Margin = Thickness(0,0,8,0)
        btn_del.Foreground = SolidColorBrush(CLR_ERR)
        btn_can = _make_btn(u'Cancel', width=80)
        WPFGrid.SetColumn(btn_del, 1); brg.Children.Add(btn_del)
        WPFGrid.SetColumn(btn_can, 2); brg.Children.Add(btn_can)
        WPFGrid.SetRow(brg, 2); g.Children.Add(brg)
        dlg.Content = g
        result = [None]
        def do_del(ss, ev):
            result[0] = str(lb.SelectedItem) if lb.SelectedItem else None
            dlg.Close()
        btn_del.Click += do_del; btn_can.Click += lambda ss, ev: dlg.Close()
        dlg.ShowDialog()
        if result[0]:
            r = MessageBox.Show(u'Delete \u201c{0}\u201d?'.format(result[0]),
                                u'ProSheets', MessageBoxButtons.YesNo, MessageBoxIcon.Warning)
            if r == DialogResult.Yes:
                self._vs_mgr.delete(result[0])

    # ── Naming Rule ───────────────────────────────────
    def _open_naming_rule(self, s, e):
        # Pass first checked/available sheet for live sample values
        sample = None
        try:
            for r in self._grid_rows:
                if r._id:
                    sample = doc.GetElement(r._id)
                    break
        except Exception:
            pass
        dlg = NamingRuleDialog(initial_parts=self._rule_parts or None,
                               sample_sheet=sample)
        dlg.Owner = self
        dlg.ShowDialog()
        if dlg.result_parts is not None:
            self._rule_parts = dlg.result_parts
            self._upd_rule_strip()
            self._refresh_custom_col()
            # Auto-apply to checked rows (if any checked)
            if self._rule_parts:
                checked = [r for r in self._grid_rows if r.Checked]
                if checked:
                    self._on_apply_rule()

    def _upd_rule_strip(self):
        if self._rule_parts:
            tokens = []
            for i, part in enumerate(self._rule_parts):
                lbl = part[0]; sep = part[2] if len(part) > 2 else u''
                prefix = part[3] if len(part) > 3 else u''
                suffix = part[4] if len(part) > 4 else u''
                fmt = u'{0}[{1}]{2}'.format(prefix, lbl, suffix)
                tokens.append(fmt)
                if sep and i < len(self._rule_parts) - 1:
                    tokens.append(sep)
            self._lbl_rule_txt.Text = u'  Rule:  ' + u''.join(tokens)
            self._strip_rule.Visibility = Visibility.Visible
        else:
            self._strip_rule.Visibility = Visibility.Collapsed

    def _clr_rule(self):
        self._rule_parts = []
        self._upd_rule_strip()
        self._refresh_custom_col()

    def _refresh_custom_col(self):
        # Refresh preview for ALL rows (not just checked) so user sees result
        for r in self._grid_rows:
            if r._id is None:
                continue
            if self._rule_parts:
                elem = doc.GetElement(r._id)
                if elem:
                    r.Custom = apply_rule_v2(elem, self._rule_parts)
            else:
                r.Custom = r._orig_custom or u''
        self._populate_grid()

    def _on_apply_rule(self):
        pairs = []
        for r in self._grid_rows:
            if not r.Checked:
                continue
            if r._id is None:
                continue
            val = (r.Custom or u'').strip()
            pairs.append((r._id, val))
        if not pairs:
            return
        ok_n, err_n, errs = write_bulk(pairs)
        # Reload only unwritten rows
        written = set(eid.IntegerValue for (eid, val) in pairs)
        for r in self._grid_rows:
            if r._id and r._id.IntegerValue not in written:
                elem = doc.GetElement(r._id)
                if elem:
                    r.Custom = safe_string(elem, CUSTOM_PARAM_NAME)
        self._populate_grid()
        self._upd_status()

    def _on_clear_names(self, s, e):
        pairs = [(r._id, u'') for r in self._grid_rows
                 if r.Checked and r._id is not None]
        if not pairs:
            MessageBox.Show(u'No rows checked.', u'ProSheets',
                            MessageBoxButtons.OK, MessageBoxIcon.Information)
            return
        res = MessageBox.Show(
            u'Clear Custom File Name for {0} item(s)?'.format(len(pairs)),
            u'ProSheets', MessageBoxButtons.YesNo, MessageBoxIcon.Warning)
        if res != DialogResult.Yes:
            return
        write_bulk(pairs)
        for r in self._grid_rows:
            if r.Checked:
                r.Custom = u''
        self._populate_grid()

    # ══════════════════════════════════════════════════
    # FORMAT TAB LOGIC
    # ══════════════════════════════════════════════════
    def get_checked_formats(self):
        return [k for k, v in self._fmt_checked.items() if v]

    def _get_pdf_settings(self):
        return {
            'paper_placement' : str(self._pdf_placement.SelectedItem or u'Center'),
            'zoom_mode'       : str(self._pdf_zoom_mode.SelectedItem or u'Fit to Page'),
            'zoom_pct'        : self._pdf_zoom_pct.Text or u'100',
            'printer'         : str(self._pdf_printer.SelectedItem or u''),
            'hidden_lines'    : str(self._pdf_hidden_lines.SelectedItem or u'Vector Processing'),
            'raster_quality'  : str(self._pdf_raster_q.SelectedItem or u'Low'),
            'colors'          : str(self._pdf_colors.SelectedItem or u'Color'),
            'view_links_blue' : self._pdf_chk_links.IsChecked == True,
            'hide_ref'        : self._pdf_chk_ref.IsChecked == True,
            'hide_unref_tags' : self._pdf_chk_unref.IsChecked == True,
            'hide_scope'      : self._pdf_chk_scope.IsChecked == True,
            'hide_crop'       : self._pdf_chk_crop.IsChecked == True,
            'replace_halftone': self._pdf_chk_half.IsChecked == True,
            'region_edges'    : self._pdf_chk_region.IsChecked == True,
            'file_mode'       : str(self._pdf_file_mode.SelectedItem or u'Separate'),
        }

    def _get_dwg_settings(self):
        return {
            'dwg_version'  : str(self._dwg_ver.SelectedItem   or u''),
            'unit'         : str(self._dwg_unit.SelectedItem   or u'Millimeter'),
            'coordinates'  : str(self._dwg_coord.SelectedItem  or u''),
            'xref_type'    : str(self._dwg_xref.SelectedItem   or u'Attach'),
            'layer_mapping': str(self._dwg_layer.SelectedItem  or u''),
            'line_color'   : str(self._dwg_line_clr.SelectedItem or u''),
            'hatch_color'  : str(self._dwg_hatch_clr.SelectedItem or u''),
            'lt_scaling'   : str(self._dwg_lt_scale.SelectedItem or u''),
            'text_treatment': str(self._dwg_text.SelectedItem  or u''),
            'shared_coords': self._dwg_chk_shared.IsChecked == True,
            'hide_scope'   : self._dwg_chk_scope.IsChecked == True,
            'hide_unref'   : self._dwg_chk_unref.IsChecked == True,
            'merge_views'  : self._dwg_chk_merge.IsChecked == True,
            'export_rooms' : self._dwg_chk_rooms.IsChecked == True,
            'file_mode'    : str(self._dwg_file_mode.SelectedItem or u'Separate'),
        }

    # ══════════════════════════════════════════════════
    # CREATE TAB LOGIC
    # ══════════════════════════════════════════════════
    def _refresh_create_tab(self):
        sel_data = self.get_checked_data()
        formats  = self.get_checked_formats() or [u'pdf']
        self._export_rows = []
        for d in sel_data:
            for fmt_key in formats:
                custom = (d.get('custom') or u'').strip()
                if custom:
                    file_name = custom
                else:
                    file_name = (u'{0}_{1}'.format(d['number'], d['name'])
                                 .strip(u'_').replace(u' ', u'_'))
                self._export_rows.append(ExportRow(
                    number   = d['number'],
                    name     = d['name'],
                    file_name = file_name,
                    fmt      = fmt_key.upper(),
                    size     = self._paper_override or u'Sheet Size',
                    orient   = self._orient_override or u'As per sheet',
                    eid      = d['id'],
                    fmt_key  = fmt_key,
                ))
        self._refresh_export_dg()
        self._lbl_progress.Text = u'Completed  0%'

    def _on_browse(self):
        dlg = FolderBrowserDialog()
        dlg.Description = u'Select output folder'
        if self._txt_folder.Text.strip():
            dlg.SelectedPath = self._txt_folder.Text.strip()
        if dlg.ShowDialog() == DialogResult.OK:
            self._out_folder = dlg.SelectedPath
            self._txt_folder.Text = self._out_folder

    def _refresh_export_dg(self):
        col = ObservableCollection[object]()
        for r in self._export_rows:
            col.Add(r)
        self._dg_export.ItemsSource = col

    def _apply_size_to_selected(self, size_val):
        """Apply paper size to selected PDF rows, or all PDF rows if none selected.
        Also stores as override so new rows get same value."""
        # Update override state
        self._paper_override = size_val or u''
        try:
            selected = [r for r in list(self._dg_export.SelectedItems)
                        if hasattr(r, '_fmt') and r._fmt == u'pdf']
        except Exception:
            selected = []
        targets = selected if selected else [r for r in self._export_rows
                                             if hasattr(r, '_fmt') and r._fmt == u'pdf']
        for r in targets:
            r.Size = size_val or u'Sheet Size'
        self._refresh_export_dg()

    def _apply_orient_to_selected(self, orient_val):
        """Apply orientation to selected PDF rows, or all PDF rows if none selected.
        Also stores as override so new rows get same value."""
        # Update override state
        self._orient_override = orient_val or u''
        try:
            selected = [r for r in list(self._dg_export.SelectedItems)
                        if hasattr(r, '_fmt') and r._fmt == u'pdf']
        except Exception:
            selected = []
        targets = selected if selected else [r for r in self._export_rows
                                             if hasattr(r, '_fmt') and r._fmt == u'pdf']
        for r in targets:
            r.Orient = orient_val or u'As per sheet'
        self._refresh_export_dg()

    def _show_paper_menu(self, s, e):
        from System.Windows.Controls import ContextMenu, MenuItem

        PAPER_GROUPS = [
            (u'A',    [u'A0',u'A1',u'A2',u'A3',u'A4',u'A5',
                       u'A6',u'A7',u'A8',u'A9',u'A10']),
            (u'B',    [u'B0',u'B1',u'B2',u'B3',u'B4',u'B5']),
            (u'ARCH', [u'Arch A',u'Arch B',u'Arch C',
                       u'Arch D',u'Arch E',u'Arch E1']),
            (u'ANSI', [u'ANSI A (Letter)',u'ANSI B (Tabloid)',
                       u'ANSI C',u'ANSI D',u'ANSI E',u'ANSI F']),
            (u'Other',[u'As per sheet',u'Letter',u'Legal',
                       u'Tabloid',u'Executive']),
        ]

        ctx = ContextMenu()
        for (group_name, sizes) in PAPER_GROUPS:
            grp = MenuItem(); grp.Header = group_name
            for size in sizes:
                def mk_h(sz):
                    def h(ss, ev):
                        val = u'' if sz == u'As per sheet' else sz
                        self._btn_paper.Content = (
                            u'Set Paper Size \u25be' if not val
                            else u'Paper: {0} \u25be'.format(sz))
                        self._apply_size_to_selected(val)
                    return h
                sub = MenuItem(); sub.Header = size
                sub.Click += mk_h(size)
                grp.Items.Add(sub)
            ctx.Items.Add(grp)

        ctx.PlacementTarget = self._btn_paper; ctx.IsOpen = True

    def _show_orient_menu(self, s, e):
        from System.Windows.Controls import ContextMenu, MenuItem
        ctx = ContextMenu()
        for lbl in [u'As per sheet', u'Landscape', u'Portrait']:
            it = MenuItem(); it.Header = lbl
            def mk_h(l):
                def h(ss, ev):
                    val = u'' if l == u'As per sheet' else l
                    self._btn_orient.Content = (
                        u'Set Orientation \u25be' if not val
                        else u'Orient: {0} \u25be'.format(l))
                    self._apply_orient_to_selected(val)
                return h
            it.Click += mk_h(lbl); ctx.Items.Add(it)
        ctx.PlacementTarget = self._btn_orient; ctx.IsOpen = True

    def _on_create(self):
        folder = (self._txt_folder.Text or u'').strip()
        if not folder:
            MessageBox.Show(u'Please select an output folder first.',
                            u'ProSheets', MessageBoxButtons.OK, MessageBoxIcon.Warning)
            return
        if not System.IO.Directory.Exists(folder):
            try:
                System.IO.Directory.CreateDirectory(folder)
            except Exception as ex:
                MessageBox.Show(u'Cannot create folder:\n' + str(ex),
                                u'ProSheets', MessageBoxButtons.OK, MessageBoxIcon.Error)
                return
        total = len(self._export_rows)
        if total == 0:
            MessageBox.Show(u'No sheets to export. Go to Selection tab and check rows.',
                            u'ProSheets', MessageBoxButtons.OK, MessageBoxIcon.Information)
            return

        # Check if PDF Combine mode
        pdf_combine = (hasattr(self, '_pdf_rb_combine') and
                       self._pdf_rb_combine.IsChecked == True)

        ok_n = 0; err_n = 0

        # ── PDF Combine: collect all PDF rows, export in one call ─
        if pdf_combine:
            pdf_rows = [r for r in self._export_rows if r._fmt == u'pdf']
            other_rows = [r for r in self._export_rows if r._fmt != u'pdf']

            if pdf_rows:
                out_dir = folder
                if self._rb_split.IsChecked == True:
                    out_dir = System.IO.Path.Combine(folder, u'PDF')
                    if not System.IO.Directory.Exists(out_dir):
                        System.IO.Directory.CreateDirectory(out_dir)

                # Build ordered sheet ID list (use _pdf_order if set)
                if hasattr(self, '_pdf_order') and self._pdf_order:
                    ordered_ids = [oi._id for oi in self._pdf_order
                                   if oi._id is not None]
                    # Append any rows not in order list
                    in_order = set(i.IntegerValue for i in ordered_ids)
                    for r in pdf_rows:
                        if r._id and r._id.IntegerValue not in in_order:
                            ordered_ids.append(r._id)
                else:
                    ordered_ids = [r._id for r in pdf_rows if r._id]

                # Custom file name from UI or first sheet name
                custom_name = u''
                try:
                    custom_name = (self._pdf_custom_name.Text or u'').strip()
                except Exception:
                    pass
                if not custom_name:
                    custom_name = u'Combined_Export'

                for ch in u'\\/:*?"<>|':
                    custom_name = custom_name.replace(ch, u'_')

                for r in pdf_rows:
                    r.Progress = u'Combining...'
                self._lbl_progress.Text = u'Exporting combined PDF...'
                System.Windows.Forms.Application.DoEvents()

                ok, msg = self._export_pdf_combine(ordered_ids, out_dir, custom_name)
                if ok:
                    for r in pdf_rows:
                        r.Progress = u'\u2714 Done'
                    ok_n += len(pdf_rows)
                else:
                    for r in pdf_rows:
                        r.Progress = u'\u2715 ' + msg
                    err_n += len(pdf_rows)

            # Export non-PDF rows normally
            for i, row in enumerate(other_rows):
                self._run_single_export(row, folder, i, len(other_rows))
                if row.Progress.startswith(u'\u2714'):
                    ok_n += 1
                else:
                    err_n += 1

        else:
            # ── Separate files (default) ──────────────────────────
            for i, row in enumerate(self._export_rows):
                self._run_single_export(row, folder, i, total)
                if row.Progress.startswith(u'\u2714'):
                    ok_n += 1
                else:
                    err_n += 1
                pct = int((i + 1) * 100.0 / total)
                self._lbl_progress.Text = u'Completed  {0}%'.format(pct)

        self._lbl_progress.Text = u'Completed  100%'

        # Refresh grid
        col = ObservableCollection[object]()
        for r in self._export_rows:
            col.Add(r)
        self._dg_export.ItemsSource = col

        icon = MessageBoxIcon.Information if err_n == 0 else MessageBoxIcon.Warning
        MessageBox.Show(
            u'Export complete.\n\nSucceeded: {0}\nFailed: {1}\n\nOutput: {2}'.format(
                ok_n, err_n, folder),
            u'ProSheets \u2014 Create', MessageBoxButtons.OK, icon)

    def _run_single_export(self, row, folder, idx, total):
        eid = row._id; fmt_key = row._fmt
        base = row.FileName or u'export_{0}'.format(idx + 1)
        for ch in u'\\/:*?"<>|':
            base = base.replace(ch, u'_')
        if doc.GetElement(eid) is None:
            row.Progress = u'\u2715 Element not found'; return
        out_dir = folder
        if self._rb_split.IsChecked == True:
            out_dir = System.IO.Path.Combine(folder, fmt_key.upper())
            if not System.IO.Directory.Exists(out_dir):
                System.IO.Directory.CreateDirectory(out_dir)
        row.Progress = u'Exporting...'
        System.Windows.Forms.Application.DoEvents()
        ok, msg = self._export_one(eid, fmt_key, out_dir, base,
                                   paper_size=row.Size, orientation=row.Orient)
        row.Progress = u'\u2714 Done' if ok else u'\u2715 ' + msg

    def _export_pdf_combine(self, ordered_ids, out_dir, file_name):
        """Export multiple sheets into one combined PDF in the given order."""
        try:
            from Autodesk.Revit.DB import PDFExportOptions
        except Exception:
            return False, u'PDFExportOptions not available'
        try:
            opts = PDFExportOptions()
            opts.Combine = True
            import time as _time
            opts.FileName = u'_ps_comb_{0}'.format(int(_time.time()*1000) % 100000)
            before = set(System.IO.Directory.GetFiles(out_dir, u'*.pdf'))
            sheet_ids = System.Collections.Generic.List[ElementId]()
            for eid in ordered_ids:
                sheet_ids.Add(eid)
            doc.Export(out_dir, sheet_ids, opts)
            after = set(System.IO.Directory.GetFiles(out_dir, u'*.pdf'))
            new_files = [f for f in after if f not in before]
            if not new_files:
                return False, u'No combined PDF created'
            target = System.IO.Path.Combine(out_dir, file_name + u'.pdf')
            if System.IO.File.Exists(target):
                System.IO.File.Delete(target)
            System.IO.File.Move(new_files[0], target)
            return True, u''
        except Exception as ex:
            return False, u'PDF Combine: ' + str(ex)[:80]

    def _export_one(self, eid, fmt_key, out_dir, base_name,
                    combine=False, paper_size=u'', orientation=u''):
        if fmt_key == u'pdf':
            return self._export_pdf(eid, out_dir, base_name,
                                    combine=combine, paper_size=paper_size,
                                    orientation=orientation)
        elif fmt_key == u'dwg':
            return self._export_dwg(eid, out_dir, base_name)
        return False, u'Unknown format'

    # Map display name → (PDFExportOptions.PaperFormat int, description)
    # Revit PDFExportOptions.PaperFormat values (Revit 2022+):
    #   0 = Default (use sheet size)
    #   These are the standard values from Autodesk.Revit.DB.PDFExportOptions.PaperFormat
    # ExportPaperFormat enum → enum member name for getattr
    # Source: Revit 2025 API (rvtdocs.com/2025)
    _PAPER_FORMAT_ENUM = {
        u'A0': u'A0', u'A1': u'A1', u'A2': u'A2', u'A3': u'A3',
        u'A4': u'A4', u'A5': u'A5', u'A6': u'A6', u'A7': u'A7',
        u'A8': u'A8', u'A9': u'A9', u'A10': u'A10',
        u'B0': u'B0', u'B1': u'B1', u'B2': u'B2',
        u'B3': u'B3', u'B4': u'B4', u'B5': u'B5',
        u'Arch A': u'ArchA', u'Arch B': u'ArchB', u'Arch C': u'ArchC',
        u'Arch D': u'ArchD', u'Arch E': u'ArchE', u'Arch E1': u'ArchE1',
        u'ANSI A (Letter)': u'AnsiA', u'ANSI B (Tabloid)': u'AnsiB',
        u'ANSI C': u'AnsiC', u'ANSI D': u'AnsiD',
        u'ANSI E': u'AnsiE', u'ANSI F': u'AnsiF',
        u'Letter': u'AnsiA', u'Legal': u'Legal',
        u'Tabloid': u'AnsiB', u'Executive': u'Executive',
    }

    def _get_ui_bool(self, attr, default=False):
        """Safely read IsChecked from a UI checkbox."""
        try:
            return getattr(self, attr).IsChecked == True
        except Exception:
            return default

    def _get_ui_text(self, attr, default=u''):
        """Safely read SelectedItem text from a ComboBox."""
        try:
            v = getattr(self, attr).SelectedItem
            return str(v) if v is not None else default
        except Exception:
            return default

    def _export_pdf(self, eid, out_dir, base_name,
                    combine=False, paper_size=u'', orientation=u''):
        try:
            from Autodesk.Revit.DB import PDFExportOptions, ExportPaperFormat
        except Exception:
            try:
                from Autodesk.Revit.DB import PDFExportOptions
                ExportPaperFormat = None
            except Exception:
                return False, u'PDFExportOptions not available'
        try:
            opts = PDFExportOptions()
            opts.Combine = combine

            # ── PaperFormat ──────────────────────────────────────
            # Must set before PaperPlacement (Revit API constraint)
            paper_fmt_set = False
            if paper_size and paper_size not in (u'Sheet Size', u'As per sheet', u''):
                enum_name = self._PAPER_FORMAT_ENUM.get(paper_size)
                if enum_name and ExportPaperFormat is not None:
                    try:
                        pf_val = getattr(ExportPaperFormat, enum_name, None)
                        if pf_val is not None:
                            opts.PaperFormat = pf_val
                            paper_fmt_set = True
                    except Exception:
                        pass

            # ── PaperOrientation (Portrait/Landscape/Auto) ────────
            # API property name: PaperOrientation (not PageOrientationType)
            # Values: PageOrientationType enum — Portrait, Landscape, Auto
            if orientation and orientation not in (u'As per sheet', u''):
                try:
                    from Autodesk.Revit.DB import PageOrientationType
                    if orientation.lower() == u'landscape':
                        opts.PaperOrientation = PageOrientationType.Landscape
                    elif orientation.lower() == u'portrait':
                        opts.PaperOrientation = PageOrientationType.Portrait
                    else:
                        opts.PaperOrientation = PageOrientationType.Auto
                except Exception:
                    pass

            # ── PaperPlacement (Center / OffsetFromCorner) ────────
            # Only works when PaperFormat != Default (Revit API constraint)
            if paper_fmt_set:
                try:
                    from Autodesk.Revit.DB import PaperPlacementType
                    is_offset = (hasattr(self, '_pdf_rb_offset') and
                                 self._pdf_rb_offset.IsChecked == True)
                    if is_offset:
                        opts.PaperPlacement = PaperPlacementType.LowerLeft
                        # OriginOffsetX/Y in Feet (API stores in feet)
                        try:
                            x_mm = float(self._pdf_x.Text or u'0')
                            y_mm = float(self._pdf_y.Text or u'0')
                            opts.OriginOffsetX = x_mm / 304.8  # mm → feet
                            opts.OriginOffsetY = y_mm / 304.8
                        except Exception:
                            pass
                    else:
                        opts.PaperPlacement = PaperPlacementType.Center
                except Exception:
                    pass

            # ── ZoomType + ZoomPercentage ─────────────────────────
            try:
                from Autodesk.Revit.DB import ZoomType
                if self._get_ui_bool('_pdf_rb_zoom'):
                    opts.ZoomType = ZoomType.Zoom
                    try:
                        opts.ZoomPercentage = int(self._pdf_zoom_pct.Text or u'100')
                    except Exception:
                        opts.ZoomPercentage = 100
                else:
                    opts.ZoomType = ZoomType.FitToPage
            except Exception:
                pass

            # ── AlwaysUseRaster (Vector vs Raster hidden lines) ──
            try:
                opts.AlwaysUseRaster = self._get_ui_bool('_pdf_rb_raster')
            except Exception:
                pass

            # ── ExportQuality / RasterQuality ─────────────────────
            try:
                from Autodesk.Revit.DB import PDFExportQualityType, RasterQualityType
                rq = self._get_ui_text('_pdf_raster_q', u'Low').lower()
                q_map = {
                    u'low': PDFExportQualityType.DPI150,
                    u'medium': PDFExportQualityType.DPI300,
                    u'high': PDFExportQualityType.DPI600,
                    u'presentation': PDFExportQualityType.DPI1200,
                }
                opts.ExportQuality = q_map.get(rq, PDFExportQualityType.DPI300)
            except Exception:
                try:
                    rq = self._get_ui_text('_pdf_raster_q', u'Low').lower()
                    opts.RasterQuality = (
                        3 if u'present' in rq else
                        2 if u'high' in rq else
                        1 if u'medium' in rq else 0)
                except Exception:
                    pass

            # ── ColorDepth ────────────────────────────────────────
            try:
                from Autodesk.Revit.DB import ColorDepthType
                clr = self._get_ui_text('_pdf_colors', u'Color').lower()
                if u'black' in clr:
                    opts.ColorDepth = ColorDepthType.BlackLine
                elif u'gray' in clr:
                    opts.ColorDepth = ColorDepthType.GrayScale
                else:
                    opts.ColorDepth = ColorDepthType.Color
            except Exception:
                pass

            # ── Boolean options ───────────────────────────────────
            try: opts.ViewLinksInBlue        = self._get_ui_bool('_pdf_chk_links')
            except Exception: pass
            try: opts.HideReferencePlane     = self._get_ui_bool('_pdf_chk_ref')
            except Exception: pass
            try: opts.HideUnreferencedViewTags = self._get_ui_bool('_pdf_chk_unref')
            except Exception: pass
            try: opts.HideScopeBoxes         = self._get_ui_bool('_pdf_chk_scope')
            except Exception: pass
            try: opts.HideCropBoundaries     = self._get_ui_bool('_pdf_chk_crop')
            except Exception: pass
            try: opts.ReplaceHalftoneWithThinLines = self._get_ui_bool('_pdf_chk_half')
            except Exception: pass
            try: opts.MaskCoincidentLines    = self._get_ui_bool('_pdf_chk_region')
            except Exception: pass

            import time as _time
            opts.FileName = u'_ps_tmp_{0}'.format(int(_time.time()*1000) % 100000)
            before = set(System.IO.Directory.GetFiles(out_dir, u'*.pdf'))
            sheet_ids = System.Collections.Generic.List[ElementId]()
            sheet_ids.Add(eid)
            doc.Export(out_dir, sheet_ids, opts)
            after    = set(System.IO.Directory.GetFiles(out_dir, u'*.pdf'))
            new_files = [f for f in after if f not in before]
            if not new_files:
                return False, u'No PDF created'
            target = System.IO.Path.Combine(out_dir, base_name + u'.pdf')
            if System.IO.File.Exists(target):
                System.IO.File.Delete(target)
            System.IO.File.Move(new_files[0], target)
            return True, u''
        except Exception as ex:
            return False, u'PDF: ' + str(ex)[:80]

    def _export_dwg(self, eid, out_dir, base_name):
        try:
            from Autodesk.Revit.DB import DWGExportOptions
        except Exception:
            return False, u'DWGExportOptions not available'
        acad_ver = None
        try:
            from Autodesk.Revit.DB import ACADVersion
            _ver_map = [ACADVersion.R2018, ACADVersion.R2013, ACADVersion.R2010,
                        ACADVersion.R2007, ACADVersion.R2004, ACADVersion.R2000]
            try:
                ver_idx = self._dwg_ver.SelectedIndex
            except Exception:
                ver_idx = 0
            acad_ver = _ver_map[ver_idx] if 0 <= ver_idx < len(_ver_map) else ACADVersion.R2018
        except Exception:
            pass
        try:
            opts = DWGExportOptions()
            if acad_ver:
                opts.FileVersion = acad_ver
            # MergedViews: False = export viewports as XRefs (external refs)
            #              True  = merge all content into one DWG file
            try:
                opts.MergedViews = not (hasattr(self, '_dwg_chk_xref') and
                                        self._dwg_chk_xref.IsChecked == True)
            except Exception:
                opts.MergedViews = True

            # Note: BindImages/CleanPCP are not available in Revit API DWGExportOptions.
            # They are interactive UI-only features. We wire ExportingAreas instead.
            id_list = System.Collections.Generic.List[ElementId]()
            id_list.Add(eid)

            # Snapshot files before export to detect new ones created by Revit
            _img_exts = [u'*.png', u'*.jpg', u'*.jpeg', u'*.tif', u'*.tiff']
            _pcp_ext  = [u'*.pcp']
            def _snap(patterns):
                s = set()
                for pat in patterns:
                    try:
                        for f in System.IO.Directory.GetFiles(out_dir, pat):
                            s.add(f)
                    except Exception: pass
                return s

            snap_img = _snap(_img_exts)
            snap_pcp = _snap(_pcp_ext)

            doc.Export(out_dir, base_name, id_list, opts)

            # Clean .pcp — delete any NEW .pcp files that appeared
            try:
                if (hasattr(self, '_dwg_chk_pcp') and
                        self._dwg_chk_pcp.IsChecked == True):
                    for f in _snap(_pcp_ext) - snap_pcp:
                        try: System.IO.File.Delete(f)
                        except Exception: pass
            except Exception: pass

            # Clean image files — delete any NEW .png/.jpg/.tif that appeared
            try:
                if (hasattr(self, '_dwg_chk_bind') and
                        self._dwg_chk_bind.IsChecked == True):
                    for f in _snap(_img_exts) - snap_img:
                        try: System.IO.File.Delete(f)
                        except Exception: pass
            except Exception: pass

            return True, u''
        except Exception as ex:
            return False, u'DWG: ' + str(ex)[:80]


# =====================================================
# ENTRY POINT
# 1. _load_wpf_imports()  — loads WPF assemblies (deferred, ~fast after 1st run)
# 2. _init_colors()       — builds Color objects (needs WPF Color type)
# 3. ProSheetsWindow()    — builds UI
# 4. win.ShowDialog()     — shows window (pyRevit: never Application.Run)
# =====================================================
try:
    win = ProSheetsWindow()
    win.ShowDialog()
except Exception as ex:
    import traceback
    try:
        from System.Windows.Forms import MessageBox as _MB, MessageBoxButtons as _MBB, MessageBoxIcon as _MBI
        _MB.Show(
            u'ProSheets Error:\n{0}\n\n{1}'.format(str(ex), traceback.format_exc()),
            u'ProSheets - By NV', _MBB.OK, _MBI.Error)
    except Exception:
        print('ProSheets Error: ' + str(ex))

