# -*- coding: utf-8 -*-
"""Auto Coping - DQT
Batch-apply (or remove) coping on steel beams where they frame into girders or
columns - instead of doing it one connection at a time.

For each selected beam the tool looks at its two ends, finds the structural
framing / columns there, and applies coping (beam.AddCoping(cuttingElement)).

Copyright (c) 2026 by Dang Quoc Truong (DQT)
"""

__title__ = "Auto\nCoping"
__author__ = "Dang Quoc Truong (DQT)"
__doc__ = ("Batch apply/remove coping on steel beams at the girders/columns "
           "they frame into.\nCopyright (c) 2026 by Dang Quoc Truong (DQT)")

from Autodesk.Revit.DB import (
    FilteredElementCollector, FamilyInstance, BuiltInCategory, Transaction,
    XYZ, Outline, BoundingBoxIntersectsFilter, LocationCurve, ElementId
)
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
from pyrevit import forms, script

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
output = script.get_output()

MM = 1.0 / 304.8

MODE_APPLY = "Apply coping"
MODE_REMOVE = "Remove coping"

TARGET_FRAMING = "Girders (Structural Framing)"
TARGET_COLUMNS = "Structural Columns"


def _eid_int(eid):
    try:
        return eid.Value
    except:
        try:
            return eid.IntegerValue
        except:
            return -1


def _bic(elem):
    try:
        return elem.Category.BuiltInCategory
    except:
        return None


def is_framing(elem):
    return isinstance(elem, FamilyInstance) and \
        _bic(elem) == BuiltInCategory.OST_StructuralFraming


def _dir(elem):
    loc = elem.Location
    if isinstance(loc, LocationCurve):
        c = loc.Curve
        try:
            v = c.GetEndPoint(1) - c.GetEndPoint(0)
            if v.GetLength() > 1e-9:
                return v.Normalize()
        except:
            pass
    return None


def beam_endpoints(beam):
    loc = beam.Location
    if isinstance(loc, LocationCurve):
        c = loc.Curve
        try:
            return [c.GetEndPoint(0), c.GetEndPoint(1)]
        except:
            return []
    return []


def candidates_near(pt, radius, want_columns):
    mn = XYZ(pt.X - radius, pt.Y - radius, pt.Z - radius)
    mx = XYZ(pt.X + radius, pt.Y + radius, pt.Z + radius)
    bbf = BoundingBoxIntersectsFilter(Outline(mn, mx))
    col = (FilteredElementCollector(doc).OfClass(FamilyInstance)
           .WhereElementIsNotElementType().WherePasses(bbf))
    out = []
    for e in col:
        bic = _bic(e)
        if bic == BuiltInCategory.OST_StructuralFraming:
            out.append(e)
        elif want_columns and bic == BuiltInCategory.OST_StructuralColumns:
            out.append(e)
    return out


class _FramingFilter(ISelectionFilter):
    def AllowElement(self, e):
        return is_framing(e)

    def AllowReference(self, r, p):
        return False


def get_beams():
    sel = [doc.GetElement(i) for i in uidoc.Selection.GetElementIds()]
    beams = [e for e in sel if is_framing(e)]
    if beams:
        return beams
    try:
        refs = uidoc.Selection.PickObjects(
            ObjectType.Element, _FramingFilter(),
            "Select the steel beams to cope, then Finish")
    except:
        return []
    return [doc.GetElement(r.ElementId) for r in refs]


def main():
    beams = get_beams()
    if not beams:
        forms.alert("No steel beams selected.", title="Auto Coping")
        return

    mode = forms.SelectFromList.show(
        [MODE_APPLY, MODE_REMOVE], title="Auto Coping - mode",
        multiselect=False, button_name="Next")
    if not mode:
        return

    want_columns = True
    radius = 300.0 * MM
    if mode == MODE_APPLY:
        targets = forms.SelectFromList.show(
            [TARGET_FRAMING, TARGET_COLUMNS],
            title="Auto Coping - cope against", multiselect=True,
            button_name="Next")
        if not targets:
            return
        want_columns = TARGET_COLUMNS in targets
        want_framing = TARGET_FRAMING in targets
        if not want_framing and not want_columns:
            return
        r_str = forms.ask_for_string(
            default="300",
            prompt="Search distance at each beam end (mm):",
            title="Auto Coping")
        if not r_str:
            return
        try:
            radius = float(r_str) * MM
        except:
            radius = 300.0 * MM

    applied = 0
    removed = 0
    processed = 0

    t = Transaction(doc, "DQT - Auto Coping")
    t.Start()
    try:
        for beam in beams:
            processed += 1

            if mode == MODE_REMOVE:
                try:
                    for cid in list(beam.GetCopingList()):
                        try:
                            ce = doc.GetElement(cid)
                            if ce is not None:
                                beam.RemoveCoping(ce)
                                removed += 1
                        except:
                            pass
                except:
                    pass
                continue

            beam_id = _eid_int(beam.Id)
            beam_dir = _dir(beam)
            try:
                done = set(_eid_int(x) for x in beam.GetCopingList())
            except:
                done = set()

            if not is_framing(beam):
                continue

            for pt in beam_endpoints(beam):
                for cand in candidates_near(pt, radius, want_columns):
                    cid = _eid_int(cand.Id)
                    if cid == beam_id or cid in done:
                        continue
                    # Skip parallel/collinear framing (a continuation beam,
                    # not a coping target). Columns have no curve direction.
                    cdir = _dir(cand)
                    if beam_dir is not None and cdir is not None and \
                            abs(beam_dir.DotProduct(cdir)) > 0.985:
                        continue
                    try:
                        beam.AddCoping(cand)
                        applied += 1
                        done.add(cid)
                    except:
                        pass
        t.Commit()
    except Exception as ex:
        t.RollBack()
        forms.alert("Auto Coping failed:\n{}".format(ex), title="Auto Coping")
        return

    if mode == MODE_REMOVE:
        msg = "Removed coping from {} connection(s) on {} beam(s).".format(
            removed, processed)
    else:
        msg = "Applied coping to {} connection(s) on {} beam(s).".format(
            applied, processed)
    output.print_md("**Auto Coping** - {}".format(msg))
    forms.alert(msg, title="Auto Coping")


if __name__ == "__main__":
    main()
