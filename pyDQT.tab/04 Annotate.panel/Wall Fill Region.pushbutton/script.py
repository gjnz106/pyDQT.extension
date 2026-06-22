# -*- coding: utf-8 -*-
"""
Wall Fill Region v1.0 - DQT
Automatically creates a single Filled Region in the active view that covers
every Wall currently shown in that view (one region masking all walls).

Copyright (c) 2026 Dang Quoc Truong (DQT)
All rights reserved.

Author: Dang Quoc Truong (DQT)
License: All rights reserved - pyDQT Suite
"""

__title__ = "Wall Fill\nRegion"
__author__ = "Dang Quoc Truong (DQT)"
__doc__ = ("Create ONE filled region covering all walls visible in the active view.\n"
           "Copyright (c) 2026 Dang Quoc Truong (DQT)")

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')

from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, Transaction,
    XYZ, Line, Arc, CurveLoop, LocationCurve,
    FilledRegion, FilledRegionType,
    GeometryCreationUtilities, BooleanOperationsUtils, BooleanOperationType,
    PlanarFace, ViewType
)
from System.Collections.Generic import List

from pyrevit import forms, script

# ============================================================================
# REVIT CONTEXT
# ============================================================================
doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
view = doc.ActiveView
output = script.get_output()

# Flatten everything onto a single horizontal plane so the resulting curve
# loops are guaranteed coplanar (required for a single FilledRegion).
Z0 = 0.0
TOL = 1e-9
EXTRUDE_HEIGHT = 10.0  # ft, arbitrary positive height for the helper solids


def _flat(p):
    """Project a point onto the Z0 plane."""
    return XYZ(p.X, p.Y, Z0)


def _wall_footprint_loop(wall):
    """Return a closed CurveLoop describing the plan footprint of a wall.

    Handles straight (Line) and curved (Arc) walls. Returns None for walls
    without a usable location curve or width (e.g. curtain / in-place walls).
    """
    loc = wall.Location
    if not isinstance(loc, LocationCurve):
        return None

    curve = loc.Curve
    try:
        width = wall.Width
    except Exception:
        return None
    if width <= TOL:
        return None
    half = width / 2.0

    if isinstance(curve, Line):
        p0 = _flat(curve.GetEndPoint(0))
        p1 = _flat(curve.GetEndPoint(1))
        direction = p1 - p0
        if direction.GetLength() <= TOL:
            return None
        direction = direction.Normalize()
        normal = XYZ.BasisZ.CrossProduct(direction).Normalize()
        offset = normal.Multiply(half)
        a = p0 + offset
        b = p1 + offset
        c = p1 - offset
        d = p0 - offset
        loop = CurveLoop()
        loop.Append(Line.CreateBound(a, b))
        loop.Append(Line.CreateBound(b, c))
        loop.Append(Line.CreateBound(c, d))
        loop.Append(Line.CreateBound(d, a))
        return loop

    if isinstance(curve, Arc):
        a0 = _flat(curve.GetEndPoint(0))
        a1 = _flat(curve.GetEndPoint(1))
        amid = _flat(curve.Evaluate(0.5, True))
        try:
            flat_arc = Arc.Create(a0, a1, amid)
            outer = flat_arc.CreateOffset(half, XYZ.BasisZ)
            inner = flat_arc.CreateOffset(-half, XYZ.BasisZ)
        except Exception:
            return None
        o0 = outer.GetEndPoint(0)
        o1 = outer.GetEndPoint(1)
        i0 = inner.GetEndPoint(0)
        i1 = inner.GetEndPoint(1)
        loop = CurveLoop()
        loop.Append(outer)
        loop.Append(Line.CreateBound(o1, i1))
        loop.Append(inner.CreateReversed())
        loop.Append(Line.CreateBound(i0, o0))
        return loop

    return None


def _loop_to_solid(loop):
    """Extrude a flat curve loop into a thin solid for boolean merging."""
    loops = List[CurveLoop]()
    loops.Add(loop)
    return GeometryCreationUtilities.CreateExtrusionGeometry(
        loops, XYZ.BasisZ, EXTRUDE_HEIGHT)


def _merge_solids(solids):
    """Union overlapping footprint solids so adjoining walls share a single
    outline. Disjoint groups (or pairs Revit refuses to union) are kept as
    separate solids - their loops will not overlap inside one FilledRegion."""
    merged = []
    for solid in solids:
        placed = False
        for idx in range(len(merged)):
            try:
                merged[idx] = BooleanOperationsUtils.ExecuteBooleanOperation(
                    merged[idx], solid, BooleanOperationType.Union)
                placed = True
                break
            except Exception:
                continue
        if not placed:
            merged.append(solid)
    return merged


def _bottom_loops(solid):
    """Collect the curve loops of the horizontal bottom face(s) of a solid.
    These sit on the Z0 plane, so they are coplanar across all solids."""
    loops = []
    for face in solid.Faces:
        if isinstance(face, PlanarFace) and face.FaceNormal.Z < -0.9:
            for cl in face.GetEdgesAsCurveLoops():
                loops.append(cl)
    return loops


# ============================================================================
# MAIN
# ============================================================================
def main():
    # Filled regions can only live in 2D-capable views.
    if view.ViewType in (ViewType.ThreeD, ViewType.Schedule,
                          ViewType.DrawingSheet, ViewType.Undefined):
        forms.alert("Active view does not support filled regions.\n"
                    "Open a plan, section, elevation, callout or drafting view "
                    "and try again.", title="Wall Fill Region")
        return

    frt = FilteredElementCollector(doc).OfClass(FilledRegionType).FirstElement()
    if frt is None:
        forms.alert("No Filled Region Type found in this project.\n"
                    "Create one (Annotate > Region) and try again.",
                    title="Wall Fill Region")
        return

    walls = (FilteredElementCollector(doc, view.Id)
             .OfCategory(BuiltInCategory.OST_Walls)
             .WhereElementIsNotElementType()
             .ToElements())

    if not walls:
        forms.alert("No walls are visible in the active view.",
                    title="Wall Fill Region")
        return

    solids = []
    skipped = 0
    for wall in walls:
        try:
            loop = _wall_footprint_loop(wall)
            if loop is None:
                skipped += 1
                continue
            solids.append(_loop_to_solid(loop))
        except Exception:
            skipped += 1

    if not solids:
        forms.alert("Could not build a footprint for any visible wall.\n"
                    "(Curtain / in-place / profile-edited walls are not "
                    "supported.)", title="Wall Fill Region")
        return

    merged = _merge_solids(solids)

    profile = List[CurveLoop]()
    for solid in merged:
        for loop in _bottom_loops(solid):
            profile.Add(loop)

    if profile.Count == 0:
        forms.alert("Failed to extract boundaries from the wall footprints.",
                    title="Wall Fill Region")
        return

    t = Transaction(doc, "DQT - Wall Fill Region")
    t.Start()
    try:
        region = FilledRegion.Create(doc, frt.Id, view.Id, profile)
        t.Commit()
    except Exception as ex:
        t.RollBack()
        forms.alert("Revit refused to create the filled region:\n{}".format(ex),
                    title="Wall Fill Region")
        return

    used = len(solids)
    msg = "Created 1 filled region covering {} wall(s).".format(used)
    if skipped:
        msg += "\n{} wall(s) skipped (no usable footprint).".format(skipped)
    output.print_md("**Wall Fill Region** - {}".format(msg))
    forms.toast(msg, title="Wall Fill Region")


if __name__ == "__main__":
    main()
