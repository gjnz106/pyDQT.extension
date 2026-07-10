# -*- coding: utf-8 -*-
"""Align Viewports

Aligns viewports on multiple sheets to a chosen "Main" sheet, so the same
view lands at the exact same position on every sheet - regardless of what
annotation/content each view happens to show.

How it works: viewport alignment is done via Viewport.SetBoxCenter(), which
positions a viewport by its crop-region outline. That outline is affected by
whatever is currently visible in the view (tags, dimensions, etc.), so every
view involved is temporarily hidden (elements only, not the crop region)
before reading/writing box centers, and restored right after - this makes
the alignment purely geometric and independent of view content.

Differences from a typical "align viewports" tool:
  - Works with ANY alignable view type on the sheet (plan, section,
    elevation, 3D, drafting, legend, ...), not only floor/ceiling plans -
    each sheet's viewports are grouped by their underlying View.ViewType and
    matched against the Main sheet's viewports of the same type.
  - When a sheet has more than one viewport of the same view type (with
    "Overlap" enabled), viewports are paired by the underlying View's Name
    first, falling back to order only for leftovers - safer than assuming
    position/order alone.
  - One transaction per non-Main sheet (plus one to hide Main's views up
    front and one to restore them at the end), instead of several
    transactions per sheet - meaningfully fewer transactions on projects
    with many sheets.
  - A sheet that fails (e.g. a view type mismatch) is skipped with a
    warning; it does not abort the rest of the run. Everything still runs
    inside one TransactionGroup, so the whole operation is a single Undo.
  - Optionally aligns the View Title too (Viewport.LabelOffset), so the
    view name/number text lines up the same way the viewports do - not
    just the crop region.

Copyright (c) 2026 Dang Quoc Truong (DQT)
All rights reserved.
"""

__title__ = "Align\nViewports"
__author__ = "Dang Quoc Truong (DQT)"
__doc__ = "Align viewports on multiple sheets to a chosen Main sheet."

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('PresentationCore')
clr.AddReference('PresentationFramework')
clr.AddReference('WindowsBase')
clr.AddReference('System')

from Autodesk.Revit.DB import (
    Transaction, TransactionGroup, FilteredElementCollector,
    BuiltInCategory, BuiltInParameter, ElementId, ViewSheet, ViewType,
    TemporaryViewMode, XYZ
)
from pyrevit import forms

import System
from System.Windows import (
    Window, WindowStartupLocation, Thickness, HorizontalAlignment,
    TextWrapping, FontWeights, CornerRadius, SizeToContent, ResizeMode
)
from System.Windows.Controls import (
    StackPanel, Button, TextBlock, RadioButton, Border, CheckBox,
    Orientation, ScrollViewer
)
from System.Windows.Media import SolidColorBrush, Color, Colors, FontFamily

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

DQT_PRIMARY   = Color.FromRgb(0xF0, 0xCC, 0x88)
DQT_ACCENT    = Color.FromRgb(0xC8, 0x96, 0x50)
DQT_BG        = Color.FromRgb(0xFE, 0xF8, 0xE7)
DQT_DARK      = Color.FromRgb(0x3C, 0x3C, 0x3C)
DQT_WHITE     = Colors.White
DQT_BORDER    = Color.FromRgb(0xDD, 0xDD, 0xDD)
DQT_TEXT_DARK = Color.FromRgb(0x33, 0x33, 0x33)


def B(color):
    return SolidColorBrush(color)


# =====================================================================
#  HELPERS
# =====================================================================

def _eid_int(eid):
    """Get integer value from ElementId - works on Revit 2024 (.IntegerValue)
    and 2025+/2026 (.Value)."""
    try:
        return eid.Value
    except:
        return eid.IntegerValue


ALIGNABLE_VIEW_TYPES = set([
    ViewType.FloorPlan, ViewType.CeilingPlan, ViewType.EngineeringPlan,
    ViewType.AreaPlan, ViewType.Section, ViewType.Elevation,
    ViewType.Detail, ViewType.ThreeD, ViewType.DraftingView,
    ViewType.Legend, ViewType.Walkthrough,
])

CROPPABLE_VIEW_TYPES = set([
    ViewType.FloorPlan, ViewType.CeilingPlan, ViewType.EngineeringPlan,
    ViewType.AreaPlan, ViewType.Section, ViewType.Elevation,
    ViewType.Detail, ViewType.ThreeD, ViewType.DraftingView,
])


def get_target_sheets():
    """Sheets pre-selected in the UI if there are >=2, otherwise a picker
    listing every sheet in the document."""
    sheets = []
    try:
        sel_ids = uidoc.Selection.GetElementIds()
        for eid in sel_ids:
            e = doc.GetElement(eid)
            if isinstance(e, ViewSheet):
                sheets.append(e)
    except:
        pass
    if len(sheets) >= 2:
        return sheets

    all_sheets = list(FilteredElementCollector(doc)
                       .OfClass(ViewSheet).WhereElementIsNotElementType())
    if not all_sheets:
        forms.alert("No sheets found in the document.", title=__title__,
                    exitscript=True)

    display = {"{} - {}".format(s.SheetNumber, s.Name): s for s in all_sheets}
    picked = forms.SelectFromList.show(
        sorted(display.keys()), title="Select Sheets to Align (min. 2)",
        multiselect=True, button_name="Select Sheets")
    if not picked:
        return []
    return [display[k] for k in picked]


def get_viewports_by_type(sheet, include_legend):
    """Dict: ViewType -> [Viewport, ...] for the alignable viewports on a sheet."""
    types = ALIGNABLE_VIEW_TYPES if include_legend else (
        ALIGNABLE_VIEW_TYPES - set([ViewType.Legend]))
    groups = {}
    for vp_id in sheet.GetAllViewports():
        vp = doc.GetElement(vp_id)
        view = doc.GetElement(vp.ViewId)
        if view is None or view.ViewType not in types:
            continue
        groups.setdefault(view.ViewType, []).append(vp)
    return groups


def match_viewports(main_groups, other_groups, overlap, warnings, sheet_number):
    """Pair up (main_viewport, other_viewport) for every shared view type.
    Single-vs-single pairs are matched directly. When either side has more
    than one viewport of a type, pairing requires 'overlap' and is done by
    the underlying View's Name first, falling back to order for leftovers."""
    pairs = []
    for vt, main_list in main_groups.items():
        other_list = other_groups.get(vt)
        if not other_list:
            continue

        if len(main_list) == 1 and len(other_list) == 1:
            pairs.append((main_list[0], other_list[0]))
            continue

        if not overlap:
            warnings.append(
                "Sheet {}: multiple {} viewports - enable 'Overlap same-type "
                "viewports' to align them".format(sheet_number, vt.ToString()))
            continue

        other_by_name = {}
        for vp in other_list:
            v = doc.GetElement(vp.ViewId)
            other_by_name.setdefault(v.Name, []).append(vp)

        used_other = set()
        unmatched_main = []
        for vp in main_list:
            v = doc.GetElement(vp.ViewId)
            bucket = other_by_name.get(v.Name, [])
            picked = None
            for cand in bucket:
                if _eid_int(cand.Id) not in used_other:
                    picked = cand
                    break
            if picked is not None:
                pairs.append((vp, picked))
                used_other.add(_eid_int(picked.Id))
            else:
                unmatched_main.append(vp)

        leftover_other = [vp for vp in other_list
                          if _eid_int(vp.Id) not in used_other]
        for m_vp, o_vp in zip(unmatched_main, leftover_other):
            pairs.append((m_vp, o_vp))
        if len(unmatched_main) != len(leftover_other):
            warnings.append(
                "Sheet {}: could not match all {} viewports by view name"
                .format(sheet_number, vt.ToString()))

    return pairs


def copy_crop_scope(main_view, other_view):
    """Best-effort copy of crop/scope box from main_view to other_view.
    Never raises - a failed copy just leaves other_view's crop untouched."""
    try:
        crop_param = other_view.get_Parameter(BuiltInParameter.VIEWER_CROP_REGION)
        if crop_param and not crop_param.IsReadOnly and not crop_param.AsInteger():
            crop_param.Set(1)
    except:
        pass

    main_scope_id = ElementId.InvalidElementId
    try:
        p = main_view.get_Parameter(BuiltInParameter.VIEWER_VOLUME_OF_INTEREST_CROP)
        if p:
            main_scope_id = p.AsElementId()
    except:
        pass

    if main_scope_id != ElementId.InvalidElementId:
        try:
            other_p = other_view.get_Parameter(
                BuiltInParameter.VIEWER_VOLUME_OF_INTEREST_CROP)
            if other_p and not other_p.IsReadOnly:
                other_p.Set(main_scope_id)
        except:
            pass
    else:
        try:
            shapes = main_view.GetCropRegionShapeManager().GetCropShape()
            if shapes and len(shapes) > 0:
                other_view.GetCropRegionShapeManager().SetCropShape(shapes[0])
        except:
            pass


def copy_label_offset(main_vp, other_vp):
    """Best-effort copy of the View Title's offset from main_vp to other_vp,
    so the title/name text lines up the same way as the crop region.
    Never raises - a failed copy just leaves other_vp's title where it was."""
    try:
        offset = main_vp.GetLabelOffset()
        other_vp.SetLabelOffset(offset)
        return True
    except Exception:
        return False


def get_titleblock(sheet):
    """The sheet's single title block, or None if there isn't exactly one."""
    tbs = list(FilteredElementCollector(doc, sheet.Id)
               .OfCategory(BuiltInCategory.OST_TitleBlocks)
               .WhereElementIsNotElementType())
    return tbs[0] if len(tbs) == 1 else None


def handle_titleblock(main_tb, other_tb, snap_origin, match_type):
    if main_tb is None or other_tb is None:
        return
    if match_type:
        try:
            other_tb.Symbol = main_tb.Symbol
        except Exception:
            pass
    if snap_origin:
        zero = XYZ(0, 0, 0)
        try:
            if not main_tb.Location.Point.IsAlmostEqualTo(zero):
                main_tb.Location.Point = zero
        except:
            pass
        try:
            if not other_tb.Location.Point.IsAlmostEqualTo(zero):
                other_tb.Location.Point = zero
        except:
            pass


def hide_view_elements(view):
    elems = FilteredElementCollector(doc, view.Id) \
        .WhereElementIsNotElementType().ToElementIds()
    view.HideElementsTemporary(elems)


def unhide_view(view):
    try:
        view.DisableTemporaryViewMode(TemporaryViewMode.TemporaryHideIsolate)
    except:
        pass


# =====================================================================
#  DIALOG
# =====================================================================

class AlignViewportsDialog(Window):
    def __init__(self, sheet_keys):
        self.sheet_keys = sheet_keys
        self.result = None
        self._build()

    def _st(self, t):
        b = TextBlock(); b.Text = t; b.FontSize = 12
        b.FontWeight = FontWeights.SemiBold; b.Foreground = B(DQT_ACCENT)
        b.Margin = Thickness(0, 0, 0, 6); return b

    def _cb(self, t, c=True):
        x = CheckBox(); x.Content = t
        x.IsChecked = System.Nullable[System.Boolean](c)
        x.Margin = Thickness(4, 3, 0, 3); x.FontSize = 11.5
        x.Foreground = B(DQT_TEXT_DARK); return x

    def _nt(self, t):
        b = TextBlock(); b.Text = t; b.FontSize = 10
        b.Foreground = B(Color.FromRgb(0x99, 0x99, 0x99))
        b.TextWrapping = TextWrapping.Wrap
        b.Margin = Thickness(24, 0, 0, 2); return b

    def _rb(self, t, checked=False):
        r = RadioButton(); r.Content = t; r.GroupName = "MainSheet"
        r.IsChecked = System.Nullable[System.Boolean](checked)
        r.Margin = Thickness(4, 3, 0, 3); r.FontSize = 11.5
        r.Foreground = B(DQT_TEXT_DARK); return r

    def _cd(self, ch):
        b = Border(); b.Background = B(DQT_WHITE)
        b.BorderBrush = B(DQT_BORDER); b.BorderThickness = Thickness(1)
        b.CornerRadius = CornerRadius(4)
        b.Margin = Thickness(16, 10, 16, 0)
        b.Padding = Thickness(12, 10, 12, 10)
        p = StackPanel()
        for c in ch:
            p.Children.Add(c)
        b.Child = p; return b

    def _build(self):
        self.Title = "Align Viewports - DQT"
        self.Width = 440; self.SizeToContent = SizeToContent.Height
        self.WindowStartupLocation = WindowStartupLocation.CenterScreen
        self.ResizeMode = ResizeMode.NoResize; self.Background = B(DQT_BG)

        m = StackPanel()

        # Header
        hd = Border(); hd.Background = B(DQT_DARK)
        hd.Padding = Thickness(16, 12, 16, 12)
        hp = StackPanel()
        t = TextBlock(); t.Text = "Align Viewports"
        t.FontSize = 16; t.FontWeight = FontWeights.Bold
        t.Foreground = B(DQT_PRIMARY); t.FontFamily = FontFamily("Segoe UI")
        hp.Children.Add(t)
        s = TextBlock(); s.Text = "Dang Quoc Truong (DQT)"
        s.FontSize = 10; s.Foreground = B(DQT_ACCENT)
        s.Margin = Thickness(0, 2, 0, 0); hp.Children.Add(s)
        hd.Child = hp; m.Children.Add(hd)

        # Main sheet picker
        self.radios = []
        rp = StackPanel()
        for i, key in enumerate(self.sheet_keys):
            rb = self._rb(key, checked=(i == 0))
            self.radios.append(rb)
            rp.Children.Add(rb)
        sv = ScrollViewer()
        sv.MaxHeight = 160
        sv.Content = rp
        m.Children.Add(self._cd([
            self._st("Main Sheet ({} selected)".format(len(self.sheet_keys))),
            sv]))

        # Options
        self.chk_overlap = self._cb(
            "Overlap same-type viewports (match by view name)", False)
        self.chk_crop = self._cb("Apply same Crop / Scope Box", False)
        self.chk_title = self._cb("Align View Titles (label position)", False)
        self.chk_legend = self._cb("Include Legends", False)
        self.chk_tb_type = self._cb("Match TitleBlock Type", False)
        self.chk_tb_zero = self._cb("Snap TitleBlocks to origin (0,0,0)", True)
        m.Children.Add(self._cd([
            self._st("Options"),
            self.chk_overlap,
            self._nt("Needed when a sheet has more than one viewport of the "
                     "same view type."),
            self.chk_crop, self.chk_title, self.chk_legend, self.chk_tb_type,
            self.chk_tb_zero]))

        # Buttons
        bp = StackPanel(); bp.Orientation = Orientation.Horizontal
        bp.HorizontalAlignment = HorizontalAlignment.Right
        bp.Margin = Thickness(16, 14, 16, 14)
        bc = Button(); bc.Content = "Cancel"; bc.Width = 90; bc.Height = 32
        bc.FontSize = 12; bc.Margin = Thickness(0, 0, 8, 0)
        bc.Background = B(DQT_WHITE); bc.Foreground = B(DQT_TEXT_DARK)
        bc.Click += self._cancel; bp.Children.Add(bc)
        br = Button(); br.Content = "Align Viewports"
        br.Width = 140; br.Height = 32; br.FontSize = 12
        br.FontWeight = FontWeights.SemiBold
        br.Background = B(DQT_ACCENT); br.Foreground = B(DQT_WHITE)
        br.Click += self._run; bp.Children.Add(br)
        m.Children.Add(bp)

        # Footer
        f = Border(); f.Background = B(DQT_DARK)
        f.Padding = Thickness(16, 6, 16, 6)
        ft = TextBlock()
        ft.Text = "Copyright (c) 2026 Dang Quoc Truong (DQT)"
        ft.FontSize = 9; ft.Foreground = B(DQT_ACCENT)
        ft.HorizontalAlignment = HorizontalAlignment.Center
        f.Child = ft; m.Children.Add(f)
        self.Content = m

    def _cancel(self, s, e):
        self.result = None; self.Close()

    def _run(self, s, e):
        main_key = None
        for rb in self.radios:
            if rb.IsChecked:
                main_key = str(rb.Content)
                break
        if main_key is None:
            forms.alert("Select a Main sheet.", title=__title__)
            return

        self.result = {
            'main': main_key,
            'overlap': self.chk_overlap.IsChecked == True,
            'crop': self.chk_crop.IsChecked == True,
            'title': self.chk_title.IsChecked == True,
            'legend': self.chk_legend.IsChecked == True,
            'tb_type': self.chk_tb_type.IsChecked == True,
            'tb_zero': self.chk_tb_zero.IsChecked == True,
        }
        self.Close()


# =====================================================================
#  MAIN
# =====================================================================

def main():
    sheets = get_target_sheets()
    if not sheets:
        return
    if len(sheets) < 2:
        forms.alert("Select at least 2 sheets.", title=__title__, exitscript=True)

    sheet_map = {"{} - {}".format(s.SheetNumber, s.Name): s for s in sheets}

    dlg = AlignViewportsDialog(sorted(sheet_map.keys()))
    dlg.ShowDialog()
    if dlg.result is None:
        return
    opts = dlg.result

    main_sheet = sheet_map[opts['main']]
    other_sheets = [s for k, s in sheet_map.items() if k != opts['main']]

    main_groups = get_viewports_by_type(main_sheet, opts['legend'])
    if not main_groups:
        forms.alert("Main sheet has no alignable viewports.", title=__title__,
                    exitscript=True)
    main_tb = get_titleblock(main_sheet)

    warnings = []
    aligned_count = 0
    titles_aligned = 0
    processed_sheets = 0
    error_sheets = []

    tg = TransactionGroup(doc, __title__)
    tg.Start()
    try:
        main_view_ids = set()
        for vps in main_groups.values():
            for vp in vps:
                main_view_ids.add(vp.ViewId)

        t0 = Transaction(doc, "DQT - Prepare Main Sheet Views")
        t0.Start()
        for vid in main_view_ids:
            try:
                hide_view_elements(doc.GetElement(vid))
            except Exception as ex:
                warnings.append("Could not hide elements in a Main view: {}".format(ex))
        t0.Commit()

        for other_sheet in other_sheets:
            other_groups = get_viewports_by_type(other_sheet, opts['legend'])
            pairs = match_viewports(main_groups, other_groups, opts['overlap'],
                                    warnings, other_sheet.SheetNumber)

            if not pairs:
                warnings.append("Sheet {}: no matching viewports to align"
                                .format(other_sheet.SheetNumber))
                continue

            t = Transaction(doc, "DQT - Align Viewports - {}".format(
                other_sheet.SheetNumber))
            t.Start()
            try:
                other_view_ids = set(vp.ViewId for _, vp in pairs)
                for vid in other_view_ids:
                    hide_view_elements(doc.GetElement(vid))

                sheet_ok = 0
                for main_vp, other_vp in pairs:
                    main_view = doc.GetElement(main_vp.ViewId)
                    other_view = doc.GetElement(other_vp.ViewId)

                    if opts['crop'] and main_view.ViewType in CROPPABLE_VIEW_TYPES:
                        copy_crop_scope(main_view, other_view)

                    try:
                        other_vp.SetBoxCenter(main_vp.GetBoxCenter())
                        sheet_ok += 1
                    except Exception:
                        warnings.append("Sheet {}: could not align '{}'".format(
                            other_sheet.SheetNumber, other_view.Name))
                        continue

                    if opts['title']:
                        if copy_label_offset(main_vp, other_vp):
                            titles_aligned += 1
                        else:
                            warnings.append(
                                "Sheet {}: could not align title of '{}'".format(
                                    other_sheet.SheetNumber, other_view.Name))

                for vid in other_view_ids:
                    unhide_view(doc.GetElement(vid))

                if opts['tb_type'] or opts['tb_zero']:
                    other_tb = get_titleblock(other_sheet)
                    handle_titleblock(main_tb, other_tb, opts['tb_zero'],
                                      opts['tb_type'])

                t.Commit()
                aligned_count += sheet_ok
                processed_sheets += 1
            except Exception as ex:
                t.RollBack()
                error_sheets.append((other_sheet.SheetNumber, str(ex)))

        t2 = Transaction(doc, "DQT - Restore Main Sheet Views")
        t2.Start()
        for vid in main_view_ids:
            unhide_view(doc.GetElement(vid))
        t2.Commit()

        tg.Assimilate()

    except Exception:
        tg.RollBack()
        import traceback
        print(traceback.format_exc())
        forms.alert("Align Viewports failed - all changes rolled back.\n\n{}"
                    .format(traceback.format_exc()), title=__title__)
        return

    print("\n" + "=" * 60)
    print("ALIGN VIEWPORTS - Main: {}".format(opts['main']))
    print("=" * 60)
    print("Sheets processed: {}/{}".format(processed_sheets, len(other_sheets)))
    print("Viewports aligned: {}".format(aligned_count))
    if opts['title']:
        print("View titles aligned: {}".format(titles_aligned))
    if error_sheets:
        print("Sheets with errors: {}".format(len(error_sheets)))
        for num, err in error_sheets:
            print("  {} : {}".format(num, err))
    if warnings:
        print("Warnings: {}".format(len(warnings)))
        for w in warnings:
            print("  {}".format(w))
    print("=" * 60)

    summary = (
        "Align Viewports Complete!\n\n"
        "Main sheet: {}\n"
        "Sheets processed: {}/{}\n"
        "Viewports aligned: {}"
    ).format(opts['main'], processed_sheets, len(other_sheets), aligned_count)
    if opts['title']:
        summary += "\nView titles aligned: {}".format(titles_aligned)
    if error_sheets:
        summary += "\n\n{} sheet(s) failed - see the pyRevit output for details."\
            .format(len(error_sheets))
    if warnings:
        summary += "\n\n{} warning(s) - see the pyRevit output for details."\
            .format(len(warnings))

    forms.alert(summary, title=__title__)


if __name__ == "__main__":
    main()
