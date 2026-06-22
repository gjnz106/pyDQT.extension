# -*- coding: utf-8 -*-
"""
Wall Fill Region v3.0 - DQT
Creates filled region(s) in the active plan view covering the walls and/or
columns that are cut by the view's cut plane. Elements can come from the host
model AND/OR from selected linked Revit files.

Features:
- Pick the source(s): Host model and/or any loaded Revit link.
- Pick which categories to cover (Walls / Architectural Columns / Structural
  Columns).
- Pick the Filled Region Type (pattern).
- Only elements cut by the plan cut plane are used; for links the geometry is
  transformed into host coordinates. Results are limited to the view crop.

Copyright (c) 2026 Dang Quoc Truong (DQT)
All rights reserved.

Author: Dang Quoc Truong (DQT)
License: All rights reserved - pyDQT Suite
"""

__title__ = "Wall Fill\nRegion"
__author__ = "Dang Quoc Truong (DQT)"
__doc__ = ("Create filled region(s) covering walls/columns cut by the active "
           "plan view, from the host model or linked files.\n"
           "Copyright (c) 2026 Dang Quoc Truong (DQT)")

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')

from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, Transaction,
    XYZ, Line, Arc, CurveLoop, LocationCurve, Element,
    FilledRegion, FilledRegionType,
    GeometryCreationUtilities, BooleanOperationsUtils, BooleanOperationsType,
    PlanarFace, Solid, GeometryInstance, Options, ViewDetailLevel,
    ViewPlan, PlanViewPlane, ElementId, RevitLinkInstance
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

Z0 = 0.0
TOL = 1e-9
EPS_Z = 1e-4
CROP_MARGIN = 0.1      # ft, tolerance around the crop box
EXTRUDE_HEIGHT = 10.0

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
    return XYZ(p.X, p.Y, Z0)


def _flatten_curve(curve):
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


def _transform_flatten_loop(loop, transform):
    """Transform a curve loop into host coords (if transform) then flatten."""
    new_loop = CurveLoop()
    for curve in loop:
        c = curve.CreateTransformed(transform) if transform else curve
        flat = _flatten_curve(c)
        if isinstance(flat, list):
            for seg in flat:
                new_loop.Append(seg)
        else:
            new_loop.Append(flat)
    return new_loop


def _iter_solids(geo):
    if geo is None:
        return
    for g in geo:
        if isinstance(g, Solid):
            if g.Volume > TOL:
                yield g
        elif isinstance(g, GeometryInstance):
            for s in _iter_solids(g.GetInstanceGeometry()):
                yield s


def _wall_footprint_loops(wall, transform):
    """Plan footprint of a wall, in host coords, built from its location curve
    and width."""
    loc = wall.Location
    if not isinstance(loc, LocationCurve):
        return []
    curve = loc.Curve
    if transform is not None:
        curve = curve.CreateTransformed(transform)
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
        # Extend both ends so footprints of joined walls overlap at corners.
        p0 = p0 - direction.Multiply(half)
        p1 = p1 + direction.Multiply(half)
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


def _solid_footprint_loops(elem, transform):
    """Plan footprint (host coords) from the bottom face of the element's
    largest solid - used for columns."""
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
            return [_transform_flatten_loop(cl, transform)
                    for cl in face.GetEdgesAsCurveLoops()]
    return []


def _footprint_loops(elem, kind, transform):
    if kind == "wall":
        return _wall_footprint_loops(elem, transform)
    return _solid_footprint_loops(elem, transform)


def _loop_to_solid(loop):
    loops = List[CurveLoop]()
    loops.Add(loop)
    return GeometryCreationUtilities.CreateExtrusionGeometry(
        loops, XYZ.BasisZ, EXTRUDE_HEIGHT)


def _merge_solids(solids):
    merged = []
    for solid in solids:
        placed = False
        for idx in range(len(merged)):
            try:
                merged[idx] = BooleanOperationsUtils.ExecuteBooleanOperation(
                    merged[idx], solid, BooleanOperationsType.Union)
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
# VIEW HELPERS
# ============================================================================
def _cut_plane_z():
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


def _is_cut(elem, cut_z, transform):
    """True if the element is cut by the host cut plane. The element bbox (in
    its own/link coords) is mapped to host Z via the link transform."""
    if cut_z is None:
        return True
    bb = elem.get_BoundingBox(None)
    if bb is None:
        return True
    if transform is None:
        zmin, zmax = bb.Min.Z, bb.Max.Z
    else:
        zs = []
        for ix in (bb.Min.X, bb.Max.X):
            for iy in (bb.Min.Y, bb.Max.Y):
                for iz in (bb.Min.Z, bb.Max.Z):
                    zs.append(transform.OfPoint(XYZ(ix, iy, iz)).Z)
        zmin, zmax = min(zs), max(zs)
    return (zmin - EPS_Z) <= cut_z <= (zmax + EPS_Z)


def _crop_xy_bbox():
    """Axis-aligned model-space XY bounds of the view crop, or None if the crop
    is not active."""
    if not view.CropBoxActive:
        return None
    cb = view.CropBox
    t = cb.Transform
    xs, ys = [], []
    for ix in (cb.Min.X, cb.Max.X):
        for iy in (cb.Min.Y, cb.Max.Y):
            for iz in (cb.Min.Z, cb.Max.Z):
                p = t.OfPoint(XYZ(ix, iy, iz))
                xs.append(p.X)
                ys.append(p.Y)
    return (min(xs), min(ys), max(xs), max(ys))


def _loops_in_crop(loops, crop):
    """True if any footprint vertex falls inside the crop XY bounds."""
    if crop is None:
        return True
    minx, miny, maxx, maxy = crop
    for loop in loops:
        for c in loop:
            p = c.GetEndPoint(0)
            if (minx - CROP_MARGIN) <= p.X <= (maxx + CROP_MARGIN) and \
               (miny - CROP_MARGIN) <= p.Y <= (maxy + CROP_MARGIN):
                return True
    return False


def _name(e):
    return Element.Name.GetValue(e)


# ============================================================================
# MAIN
# ============================================================================
def main():
    if not isinstance(view, ViewPlan):
        forms.alert("This tool works in plan views only (floor / structural / "
                    "ceiling / area plan).\nOpen a plan view and try again.",
                    title="Wall Fill Region")
        return

    # --- 1) Choose source(s): host + loaded links ---------------------------
    sources = [("Host model", None, None)]  # (label, link_instance, transform)
    seen = {"Host model": 1}
    links = (FilteredElementCollector(doc, view.Id)
             .OfCategory(BuiltInCategory.OST_RvtLinks)
             .WhereElementIsNotElementType()
             .ToElements())
    for li in links:
        if not isinstance(li, RevitLinkInstance):
            continue
        if li.GetLinkDocument() is None:
            continue  # unloaded link
        base = "LINK: " + _name(li)
        label = base
        if label in seen:
            seen[base] += 1
            label = "{} ({})".format(base, seen[base])
        else:
            seen[base] = 1
        sources.append((label, li, li.GetTotalTransform()))

    src_labels = [s[0] for s in sources]
    picked_src = forms.SelectFromList.show(
        src_labels, title="Wall Fill Region - source model(s)",
        multiselect=True, button_name="Next")
    if not picked_src:
        return
    chosen_sources = [s for s in sources if s[0] in picked_src]

    # --- 2) Choose categories -----------------------------------------------
    labels = [c[0] for c in CATEGORY_CHOICES]
    picked = forms.SelectFromList.show(
        labels, title="Wall Fill Region - elements to cover",
        multiselect=True, button_name="Next")
    if not picked:
        return
    chosen_cats = [c for c in CATEGORY_CHOICES if c[0] in picked]

    # --- 3) Choose filled region type ---------------------------------------
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

    # --- 4) Collect cut elements & build footprints -------------------------
    cut_z = _cut_plane_z()
    crop = _crop_xy_bbox()
    all_loops = []
    counts = {}
    skipped = 0
    for label, li, transform in chosen_sources:
        src_doc = li.GetLinkDocument() if li is not None else doc
        for clabel, bic, kind in chosen_cats:
            if li is None:
                elems = (FilteredElementCollector(doc, view.Id)
                         .OfCategory(bic).WhereElementIsNotElementType()
                         .ToElements())
            else:
                elems = (FilteredElementCollector(src_doc)
                         .OfCategory(bic).WhereElementIsNotElementType()
                         .ToElements())
            for elem in elems:
                if not _is_cut(elem, cut_z, transform):
                    continue
                try:
                    loops = _footprint_loops(elem, kind, transform)
                except Exception:
                    loops = []
                if not loops or not _loops_in_crop(loops, crop):
                    continue
                all_loops.extend(loops)
                counts[clabel] = counts.get(clabel, 0) + 1

    if not all_loops:
        forms.alert("No cut walls/columns were found in this view for the "
                    "selected source(s).\n"
                    "Check that the link is loaded and the cut plane passes "
                    "through the elements.", title="Wall Fill Region")
        return

    # --- 5) Merge footprints and create region(s) ---------------------------
    solids = []
    for loop in all_loops:
        try:
            solids.append(_loop_to_solid(loop))
        except Exception:
            skipped += 1
    merged = _merge_solids(solids)

    def _try_create(loop_list):
        coll = List[CurveLoop]()
        for lp in loop_list:
            coll.Add(lp)
        if coll.Count == 0:
            return False
        try:
            FilledRegion.Create(doc, frt.Id, view.Id, coll)
            return True
        except Exception:
            return False

    created = 0
    t = Transaction(doc, "DQT - Wall Fill Region")
    t.Start()
    try:
        for solid in merged:
            loops = _bottom_loops(solid)
            if not loops:
                continue
            if _try_create(loops):
                created += 1
            else:
                for lp in loops:
                    if _try_create([lp]):
                        created += 1
        if created == 0:
            t.RollBack()
            forms.alert("Could not create any filled region from the selected "
                        "elements.", title="Wall Fill Region")
            return
        t.Commit()
    except Exception as ex:
        t.RollBack()
        forms.alert("Revit refused to create the filled region:\n{}".format(ex),
                    title="Wall Fill Region")
        return

    detail = ", ".join("{}: {}".format(k, v) for k, v in counts.items())
    msg = "Created {} filled region(s) covering {}.".format(created, detail)
    if skipped:
        msg += "\n{} footprint(s) skipped.".format(skipped)
    output.print_md("**Wall Fill Region** - {}".format(msg))
    forms.alert(msg, title="Wall Fill Region")


if __name__ == "__main__":
    main()
