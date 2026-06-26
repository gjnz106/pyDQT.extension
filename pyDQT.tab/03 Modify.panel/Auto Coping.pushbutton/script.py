# -*- coding: utf-8 -*-
"""Auto Coping - DQT
Batch apply / remove coping on steel beams, following Revit's own logic:
first pick the element(s) to be CUT (coped), then pick the CUTTING element(s).
Coping is applied for every cut x cutter pair whose bounding boxes overlap.

Copyright (c) 2026 by Dang Quoc Truong (DQT)
"""

__title__ = "Auto\nCoping"
__author__ = "Dang Quoc Truong (DQT)"
__doc__ = ("Batch coping for steel: pick the beams to be CUT, then the CUTTING "
           "elements (girders/columns).\nCopyright (c) 2026 by Dang Quoc Truong (DQT)")

from Autodesk.Revit.DB import (
    FilteredElementCollector, FamilyInstance, BuiltInCategory, Transaction,
    ElementId
)
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
from pyrevit import forms, script

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
output = script.get_output()

MODE_APPLY = "Apply coping"
MODE_REMOVE = "Remove coping"
BBOX_TOL = 0.05  # ft, ~15mm padding for the overlap test


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


def is_cutter(elem):
    return isinstance(elem, FamilyInstance) and _bic(elem) in (
        BuiltInCategory.OST_StructuralFraming,
        BuiltInCategory.OST_StructuralColumns)


def bbox_overlap(a, b):
    try:
        ba = a.get_BoundingBox(None)
        bb = b.get_BoundingBox(None)
        if ba is None or bb is None:
            return True
        t = BBOX_TOL
        return not (ba.Max.X + t < bb.Min.X or ba.Min.X - t > bb.Max.X or
                    ba.Max.Y + t < bb.Min.Y or ba.Min.Y - t > bb.Max.Y or
                    ba.Max.Z + t < bb.Min.Z or ba.Min.Z - t > bb.Max.Z)
    except:
        return True


class _FramingFilter(ISelectionFilter):
    def AllowElement(self, e):
        return is_framing(e)

    def AllowReference(self, r, p):
        return False


class _CutterFilter(ISelectionFilter):
    def AllowElement(self, e):
        return is_cutter(e)

    def AllowReference(self, r, p):
        return False


def get_cut_targets():
    """Step 1: the elements that will be CUT (coped). Use the current
    selection if it is framing, else let the user pick."""
    sel = [doc.GetElement(i) for i in uidoc.Selection.GetElementIds()]
    beams = [e for e in sel if is_framing(e)]
    if beams:
        return beams
    try:
        refs = uidoc.Selection.PickObjects(
            ObjectType.Element, _FramingFilter(),
            "STEP 1: select the beams to be CUT (coped), then Finish")
    except:
        return []
    return [doc.GetElement(r.ElementId) for r in refs]


def pick_cutters(msg):
    """Step 2: the CUTTING elements (girders / columns)."""
    try:
        refs = uidoc.Selection.PickObjects(
            ObjectType.Element, _CutterFilter(), msg)
    except:
        return []
    return [doc.GetElement(r.ElementId) for r in refs]


def main():
    mode = forms.SelectFromList.show(
        [MODE_APPLY, MODE_REMOVE], title="Auto Coping - mode",
        multiselect=False, button_name="Next")
    if not mode:
        return

    # Step 1 - elements to be cut
    cut_targets = get_cut_targets()
    if not cut_targets:
        forms.alert("No elements to cut were selected.", title="Auto Coping")
        return

    # Step 2 - cutting elements
    remove_all = False
    if mode == MODE_APPLY:
        cutters = pick_cutters(
            "STEP 2: select the CUTTING elements (girders/columns), then Finish")
        if not cutters:
            forms.alert("No cutting elements selected.", title="Auto Coping")
            return
    else:
        cutters = pick_cutters(
            "STEP 2: select the CUTTING elements to un-cope - "
            "or press Esc to remove ALL coping from the selected beams")
        if not cutters:
            remove_all = True

    applied = 0
    removed = 0

    t = Transaction(doc, "DQT - Auto Coping")
    t.Start()
    try:
        for beam in cut_targets:
            if not is_framing(beam):
                continue
            beam_id = _eid_int(beam.Id)

            if mode == MODE_REMOVE and remove_all:
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

            try:
                existing = set(_eid_int(x) for x in beam.GetCopingList())
            except:
                existing = set()

            for cutter in cutters:
                cid = _eid_int(cutter.Id)
                if cid == beam_id:
                    continue
                if not bbox_overlap(beam, cutter):
                    continue
                if mode == MODE_APPLY:
                    if cid in existing:
                        continue
                    try:
                        beam.AddCoping(cutter)
                        applied += 1
                        existing.add(cid)
                    except:
                        pass
                else:
                    if cid not in existing:
                        continue
                    try:
                        beam.RemoveCoping(cutter)
                        removed += 1
                    except:
                        pass
        t.Commit()
    except Exception as ex:
        t.RollBack()
        forms.alert("Auto Coping failed:\n{}".format(ex), title="Auto Coping")
        return

    if mode == MODE_APPLY:
        msg = "Applied coping to {} connection(s) on {} beam(s).".format(
            applied, len(cut_targets))
    else:
        msg = "Removed {} coping(s) from {} beam(s).".format(
            removed, len(cut_targets))
    output.print_md("**Auto Coping** - {}".format(msg))
    forms.alert(msg, title="Auto Coping")


if __name__ == "__main__":
    main()
