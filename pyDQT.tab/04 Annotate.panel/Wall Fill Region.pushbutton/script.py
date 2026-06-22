# -*- coding: utf-8 -*-
"""
Wall Fill Region v2.0 - DQT
Creates a single Filled Region in the active view that covers the elements
(walls and, optionally, columns) that are CUT by the view's cut plane.

Features:
- Pick which categories to cover (Walls / Architectural Columns / Structural Columns).
- Pick the Filled Region Type (pattern) from a dialog.
- Only elements cut by the plan view range are included (low walls below the
  cut plane are ignored).

Copyright (c) 2026 Dang Quoc Truong (DQT)
All rights reserved.

Author: Dang Quoc Truong (DQT)
License: All rights reserved - pyDQT Suite
"""

__title__ = "Wall Fill\nRegion"
__author__ = "Dang Quoc Truong (DQT)"
__doc__ = ("Create ONE filled region covering the walls/columns cut by the "
           "active view.\nCopyright (c) 2026 Dang Quoc Truong (DQT)")

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')

from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, Transaction,
    XYZ, Line, Arc, CurveLoop, LocationCurve, Element,
    FilledRegion, FilledRegionType,
    GeometryCreationUtilities, BooleanOperationsUtils, BooleanOperationType,
    PlanarFace, Solid, GeometryInstance, Options, ViewDetailLevel,
    ViewType, ViewPlan, PlanViewPlane, ElementId
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

# Flatten everything onto one horizontal plane so the curve loops are
# guaranteed coplanar (required for a single FilledRegion).
Z0 = 0.0
TOL = 1e-9
EPS_Z = 1e-4           # ~0.03 mm tolerance for the cut-plane test
EXTRUDE_HEIGHT = 10.0  # ft, arbitrary positive height for the helper solids

# (label, BuiltInCategory, kind)
CATEGORY_CHOICES = [
    ("Walls", BuiltInCategory.OST_Walls, "wall"),
    ("Columns (Architectural)", BuiltInCategory.OST_Columns, "column"),
    ("Structural Columns", BuiltInCategory.OST_StructuralColumns, "column"),
]


# ============================================================================
# GEOMETRY HELPERS
# ============================================================================
def _flat(p):
    """Project a point onto the Z0 plane."""
    return XYZ(p.X, p.Y, Z0)


def _flatten_curve(curve):
    """Return a flattened copy of a curve (Line/Arc), else a list of line
    segments from a tessellation fallback."""
    if isinstance(curve, Line):
        return Line.CreateBound(_flat(curve.GetEndPoint(0)),
                                _flat(curve.GetEndPoint(1)))
    if isinstance(curve, Arc):
        return Arc.Create(_flat(curve.GetEndPoint(0)),
                          _flat(curve.GetEndPoint(1)),
                          _flat(curve.Evaluate(0.5, True)))
    pts = curve.Tessellate()
    segs = []
    for i in range(len(pts) - 1):
        a = _flat(pts[i])
        b = _flat(pts[i + 1])
        if a.DistanceTo(b) > TOL:
            segs.append(Line.CreateBound(a, b))
    return segs


def _flatten_loop(loop):
    """Rebuild a CurveLoop onto the Z0 plane."""
    new_loop = CurveLoop()
    for curve in loop:
        flat = _flatten_curve(curve)
        if isinstance(flat, list):
            for seg in flat:
                new_loop.Append(seg)
        else:
            new_loop.Append(flat)
    return new_loop


def _iter_solids(geo):
    """Yield all non-empty solids in a GeometryElement (recurses instances)."""
    if geo is None:
        return
    for g in geo:
        if isinstance(g, Solid):
            if g.Volume > TOL:
                yield g
        elif isinstance(g, GeometryInstance):
            for s in _iter_solids(g.GetInstanceGeometry()):
                yield s


def _wall_footprint_loops(wall):
    """Plan footprint of a wall built from its location curve and width."""
    loc = wall.Location
    if not isinstance(loc, LocationCurve):
        return []
    curve = loc.Curve
    try:
        width = wall.Width
    except Exception:
        return []
    if width <= TOL:
        return []
    half = width / 2.0

    if isinstance(curve, Line):
        p0 = _flat(curve.GetEndPoint(0))
        p1 = _flat(curve.GetEndPoint(1))
        direction = p1 - p0
        if direction.GetLength() <= TOL:
            return []
        direction = direction.Normalize()
        normal = XYZ.BasisZ.CrossProduct(direction).Normalize()
        offset = normal.Multiply(half)
        a, b = p0 + offset, p1 + offset
        c, d = p1 - offset, p0 - offset
        loop = CurveLoop()
        loop.Append(Line.CreateBound(a, b))
        loop.Append(Line.CreateBound(b, c))
        loop.Append(Line.CreateBound(c, d))
        loop.Append(Line.CreateBound(d, a))
        return [loop]

    if isinstance(curve, Arc):
        a0 = _flat(curve.GetEndPoint(0))
        a1 = _flat(curve.GetEndPoint(1))
        amid = _flat(curve.Evaluate(0.5, True))
        try:
            flat_arc = Arc.Create(a0, a1, amid)
            outer = flat_arc.CreateOffset(half, XYZ.BasisZ)
            inner = flat_arc.CreateOffset(-half, XYZ.BasisZ)
        except Exception:
            return []
        loop = CurveLoop()
        loop.Append(outer)
        loop.Append(Line.CreateBound(outer.GetEndPoint(1), inner.GetEndPoint(1)))
        loop.Append(inner.CreateReversed())
        loop.Append(Line.CreateBound(inner.GetEndPoint(0), outer.GetEndPoint(0)))
        return [loop]

    return []


def _solid_footprint_loops(elem):
    """Plan footprint of any element taken from the bottom face of its
    largest solid (used for columns)."""
    opt = Options()
    opt.DetailLevel = ViewDetailLevel.Fine
    opt.ComputeReferences = False
    geo = elem.get_Geometry(opt)
    best = None
    for solid in _iter_solids(geo):
        if best is None or solid.Volume > best.Volume:
            best = solid
    if best is None:
        return []
    for face in best.Faces:
        if isinstance(face, PlanarFace) and face.FaceNormal.Z < -0.9:
            return [_flatten_loop(cl) for cl in face.GetEdgesAsCurveLoops()]
    return []


def _footprint_loops(elem, kind):
    if kind == "wall":
        return _wall_footprint_loops(elem)
    return _solid_footprint_loops(elem)


def _loop_to_solid(loop):
    loops = List[CurveLoop]()
    loops.Add(loop)
    return GeometryCreationUtilities.CreateExtrusionGeometry(
        loops, XYZ.BasisZ, EXTRUDE_HEIGHT)


def _merge_solids(solids):
    """Union overlapping footprints so adjoining elements share one outline.
    Disjoint groups (or pairs Revit refuses to union) stay separate - their
    loops will not overlap inside one FilledRegion."""
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
    loops = []
    for face in solid.Faces:
        if isinstance(face, PlanarFace) and face.FaceNormal.Z < -0.9:
            for cl in face.GetEdgesAsCurveLoops():
                loops.append(cl)
    return loops


# ============================================================================
# VIEW / CUT-PLANE HELPERS
# ============================================================================
def _cut_plane_z():
    """Elevation of the active plan view's cut plane, or None for views that
    have no plan cut plane (sections, elevations, drafting...)."""
    if not isinstance(view, ViewPlan):
        return None
    try:
        vr = view.GetViewRange()
        lvl_id = vr.GetLevelId(PlanViewPlane.CutPlane)
        offset = vr.GetOffset(PlanViewPlane.CutPlane)
        if lvl_id is not None and lvl_id != ElementId.InvalidElementId:
            base_z = doc.GetElement(lvl_id).Elevation
        else:
            gen = view.GenLevel
            if gen is None:
                return None
            base_z = gen.Elevation
        return base_z + offset
    except Exception:
        return None


def _is_cut(elem, cut_z):
    """True if the element is cut by the plan cut plane (or always, when the
    view has no cut plane)."""
    if cut_z is None:
        return True
    bb = elem.get_BoundingBox(None)
    if bb is None:
        return True
    return (bb.Min.Z - EPS_Z) <= cut_z <= (bb.Max.Z + EPS_Z)


def _name(e):
    return Element.Name.GetValue(e)


# ============================================================================
# MAIN
# ============================================================================
def main():
    if view.ViewType in (ViewType.ThreeD, ViewType.Schedule,
                          ViewType.DrawingSheet, ViewType.Undefined):
        forms.alert("Active view does not support filled regions.\n"
                    "Open a plan, section, elevation, callout or drafting view "
                    "and try again.", title="Wall Fill Region")
        return

    # --- 1) Choose categories ------------------------------------------------
    labels = [c[0] for c in CATEGORY_CHOICES]
    picked = forms.SelectFromList.show(
        labels, title="Wall Fill Region - elements to cover",
        multiselect=True, button_name="Next")
    if not picked:
        return
    chosen = [c for c in CATEGORY_CHOICES if c[0] in picked]

    # --- 2) Choose filled region type ---------------------------------------
    frts = list(FilteredElementCollector(doc).OfClass(FilledRegionType))
    if not frts:
        forms.alert("No Filled Region Type found in this project.\n"
                    "Create one (Annotate > Region) and try again.",
                    title="Wall Fill Region")
        return
    name_map = {}
    for frt in frts:
        name_map[_name(frt)] = frt
    chosen_name = forms.SelectFromList.show(
        sorted(name_map.keys()), title="Wall Fill Region - region type",
        multiselect=False, button_name="Create")
    if not chosen_name:
        return
    frt = name_map[chosen_name]

    # --- 3) Collect cut elements & build footprints -------------------------
    cut_z = _cut_plane_z()
    all_loops = []
    counts = {}
    skipped = 0
    for label, bic, kind in chosen:
        elems = (FilteredElementCollector(doc, view.Id)
                 .OfCategory(bic)
                 .WhereElementIsNotElementType()
                 .ToElements())
        used = 0
        for elem in elems:
            if not _is_cut(elem, cut_z):
                continue
            try:
                loops = _footprint_loops(elem, kind)
            except Exception:
                loops = []
            if loops:
                all_loops.extend(loops)
                used += 1
            else:
                skipped += 1
        counts[label] = used

    if not all_loops:
        forms.alert("No cut elements with a usable footprint were found in "
                    "this view.", title="Wall Fill Region")
        return

    # --- 4) Merge footprints into one set of boundaries ---------------------
    solids = []
    for loop in all_loops:
        try:
            solids.append(_loop_to_solid(loop))
        except Exception:
            skipped += 1
    merged = _merge_solids(solids)

    profile = List[CurveLoop]()
    for solid in merged:
        for loop in _bottom_loops(solid):
            profile.Add(loop)
    if profile.Count == 0:
        forms.alert("Failed to extract boundaries from the footprints.",
                    title="Wall Fill Region")
        return

    # --- 5) Create the single filled region ---------------------------------
    t = Transaction(doc, "DQT - Wall Fill Region")
    t.Start()
    try:
        FilledRegion.Create(doc, frt.Id, view.Id, profile)
        t.Commit()
    except Exception as ex:
        t.RollBack()
        forms.alert("Revit refused to create the filled region:\n{}".format(ex),
                    title="Wall Fill Region")
        return

    detail = ", ".join("{}: {}".format(k, v) for k, v in counts.items())
    msg = "Created 1 filled region ({}).".format(detail)
    if skipped:
        msg += "\n{} element(s) skipped (no usable footprint).".format(skipped)
    output.print_md("**Wall Fill Region** - {}".format(msg))
    forms.alert(msg, title="Wall Fill Region")


if __name__ == "__main__":
    main()
