# -*- coding: utf-8 -*-
"""
Split Shaft Opening Tool

Splits a shaft opening that has several disconnected boundary loops into
separate individual shaft openings - one per boundary - while preserving
everything the original held: all instance parameters, any holes, and the
user-drawn symbolic lines inside the boundaries.

Method (mirrors the manual Revit workflow that reliably keeps symbolic
lines):
  For each outer boundary of the original shaft:
    1. COPY the whole shaft in place. The copy already contains every
       boundary, hole and symbolic line as real sketch members.
    2. EDIT that copy's sketch and DELETE the loops that belong to other
       openings, leaving one boundary (plus its holes / interior lines).
  Finally the original multi-boundary shaft is deleted.

CRITICAL correctness/stability rules (a shaft sketch requires EVERY line to
belong to a CLOSED loop; leaving a loop open produces an "Error - cannot be
ignored" that crashes Revit):
  * Sketch curves are grouped into connected components (chains sharing
    endpoints). We only ever keep or delete WHOLE components, so a boundary
    loop can never be left half-deleted / open.
  * Before committing the sketch edit we verify the surviving curves still
    form closed loops. If they don't, we CANCEL the edit instead of
    committing - turning what used to be an un-ignorable crash into a
    safely-reported failure.

Dang Quoc Truong - DQT (c) 2026
"""

__title__ = "Split\nShaft"
__author__ = "DQT"

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import ObjectType
from pyrevit import revit, DB, forms
from System.Collections.Generic import List

doc = revit.doc
uidoc = revit.uidoc

# Connectivity / endpoint-match tolerance in feet (~0.03 mm). Boundary
# vertices of a sketch coincide exactly; this only absorbs float noise.
TOL = 1e-4


def _eid_int(eid):
    """Integer value of an ElementId across Revit 2024-2027 (.IntegerValue is
    deprecated in 2024+ and removed in 2026+; use .Value)."""
    try:
        return eid.Value
    except:
        return eid.IntegerValue


class _SwallowFailures(IFailuresPreprocessor):
    """Silences the expected 'duplicate/overlapping elements' warnings while
    copies briefly overlap."""
    def PreprocessFailures(self, fa):
        return FailureProcessingResult.Continue


def is_shaft_opening(elem):
    if not isinstance(elem, Opening):
        return False
    try:
        cat = elem.Category
        return cat is not None and cat.Id == Category.GetCategory(
            doc, DB.BuiltInCategory.OST_ShaftOpening).Id
    except:
        return False


def get_sketch(elem):
    try:
        for did in elem.GetDependentElements(ElementClassFilter(Sketch)):
            s = doc.GetElement(did)
            if isinstance(s, Sketch):
                return s
    except:
        pass
    return None


def _midpoint(curve):
    try:
        return curve.Evaluate(0.5, True)
    except:
        try:
            return curve.GetEndPoint(0)
        except:
            return None


def point_in_loop(point, curves):
    """Even-odd horizontal ray-cast point-in-polygon test against a set of
    curves that form a closed ring (order does not matter)."""
    if point is None:
        return False
    ray_end = XYZ(point.X + 10000.0, point.Y, point.Z)
    try:
        ray = Line.CreateBound(point, ray_end)
    except:
        return False
    count = 0
    for curve in curves:
        try:
            if curve.Intersect(ray) == DB.SetComparisonResult.Overlap:
                count += 1
        except:
            pass
    return count % 2 == 1


def collect_sketch_curves(sketch):
    """[(element, curve)] for every dependent of the sketch that exposes a
    GeometryCurve (boundary edges + any symbolic lines)."""
    out = []
    seen = set()
    try:
        for did in sketch.GetDependentElements(None):
            key = _eid_int(did)
            if key in seen:
                continue
            seen.add(key)
            e = doc.GetElement(did)
            if e is None:
                continue
            try:
                g = e.GeometryCurve
            except:
                continue
            if g is not None:
                out.append((e, g))
    except Exception as ex:
        print("  Could not enumerate sketch curves: {}".format(ex))
    return out


def _share_endpoint(c1, c2, tol):
    p = [c1.GetEndPoint(0), c1.GetEndPoint(1)]
    q = [c2.GetEndPoint(0), c2.GetEndPoint(1)]
    for a in p:
        for b in q:
            if a.DistanceTo(b) < tol:
                return True
    return False


def build_components(curve_items, tol):
    """Group [(element, curve)] into connected components by shared endpoints.
    Returns a list of components, each a list of (element, curve)."""
    n = len(curve_items)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        ci = curve_items[i][1]
        for j in range(i + 1, n):
            if _share_endpoint(ci, curve_items[j][1], tol):
                union(i, j)

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(curve_items[i])
    return list(groups.values())


def curves_closed(curve_list, tol):
    """True if these curves form closed loops only - every endpoint is shared
    by an even number of curve ends (a free/open end has an odd count)."""
    pts = []
    for c in curve_list:
        pts.append(c.GetEndPoint(0))
        pts.append(c.GetEndPoint(1))
    used = [False] * len(pts)
    for i in range(len(pts)):
        if used[i]:
            continue
        cnt = 0
        for j in range(len(pts)):
            if not used[j] and pts[i].DistanceTo(pts[j]) < tol:
                used[j] = True
                cnt += 1
        if cnt % 2 != 0:
            return False
    return True


def _comp_rep_point(comp):
    for (_e, c) in comp:
        return _midpoint(c)
    return None


# ---------------------------------------------------------------------------
# Opening DETECTION uses Sketch.Profile - the proven-reliable source for how
# many boundary loops the shaft has (the same source the original working tool
# used). The element-component machinery above is used only for the safe
# WHOLE-loop deletion during trimming.
# ---------------------------------------------------------------------------

def get_profile_loops(sketch):
    """List of loops (each a list of Curve) from the sketch profile."""
    loops = []
    if sketch is None:
        return loops
    try:
        for curve_array in sketch.Profile:
            curves = [c for c in curve_array]
            if curves:
                loops.append(curves)
    except Exception as ex:
        print("  Could not read sketch profile: {}".format(ex))
    return loops


def _loop_area(curves):
    pts = []
    for c in curves:
        pts.append(c.GetEndPoint(0))
        pts.append(c.GetEndPoint(1))
    if not pts:
        return 0.0
    return (max(p.X for p in pts) - min(p.X for p in pts)) * \
           (max(p.Y for p in pts) - min(p.Y for p in pts))


def _loop_first_point(curves):
    for c in curves:
        return c.GetEndPoint(0)
    return None


def find_outer_loops(loops):
    """The loops that are NOT nested inside a larger loop - i.e. the separate
    openings (holes are excluded). Deterministic order."""
    data = [(l, _loop_area(l)) for l in loops]
    data.sort(key=lambda d: d[1], reverse=True)
    outers = []
    for (l, a) in data:
        nested = False
        for (m, am) in data:
            if m is l:
                continue
            if am > a and point_in_loop(_loop_first_point(l), m):
                nested = True
                break
        if not nested:
            outers.append(l)
    return outers


def get_outer_openings(opening):
    """List of outer boundary loops (each a list of Curve) for this shaft."""
    sketch = get_sketch(opening)
    if sketch is None:
        return []
    return find_outer_loops(get_profile_loops(sketch))


def _point_on_loop(point, curves, tol):
    """True if point lies on one of the loop's curves (within tol)."""
    if point is None:
        return False
    for c in curves:
        try:
            if c.Distance(point) < tol:
                return True
        except:
            pass
    return False


def _is_boundary_curve(curve, ref_boundary_curves, tol):
    """A sketch curve is a BOUNDARY curve (must belong to a closed loop) if its
    midpoint lies on one of the sketch's profile edges. Everything else is a
    symbolic line, which Revit allows to be OPEN and must be ignored by the
    closed-loop validation. Tested by point-on-geometry, so it is immune to the
    Profile-vs-element curve-splitting mismatch."""
    return _point_on_loop(_midpoint(curve), ref_boundary_curves, tol)


def boundary_closed(curves, ref_boundary_curves, tol):
    """True if the BOUNDARY curves among 'curves' form closed loops. Symbolic
    (open) lines are excluded so they never make this fail."""
    bnd = [c for c in curves
           if _is_boundary_curve(c, ref_boundary_curves, tol * 10.0)]
    return curves_closed(bnd, tol)


def trim_copy_to_outer_loop(copy, target_curves):
    """Edit the copy's sketch to keep only the boundary at target_curves (plus
    the holes / symbolic lines inside it), deleting every OTHER whole connected
    component. Only the BOUNDARY loops are required to stay closed - symbolic
    lines are allowed to remain open. Cancels rather than committing anything
    that would leave a boundary open (the un-ignorable crash). Returns
    (ok, message)."""
    sketch = get_sketch(copy)
    if sketch is None:
        return False, "copy has no sketch"

    # All profile edges of this copy - used to tell boundary curves from
    # symbolic lines during validation.
    ref_boundary = [c for loop in get_profile_loops(sketch) for c in loop]

    curve_items = collect_sketch_curves(sketch)
    comps = build_components(curve_items, TOL)
    print("      copy sketch: {} curve(s) in {} component(s)".format(
        len(curve_items), len(comps)))

    on_tol = TOL * 10.0
    del_ids = []
    kept_curves = []
    for comp in comps:
        rep = _comp_rep_point(comp)
        # Keep this whole component if it is the target boundary itself (edges
        # lie ON the target loop) or it sits inside the target boundary (a hole
        # or a symbolic line of this opening).
        keep = _point_on_loop(rep, target_curves, on_tol) or \
            point_in_loop(rep, target_curves)
        if keep:
            for (_e, c) in comp:
                kept_curves.append(c)
        else:
            for (e, _c) in comp:
                del_ids.append(e.Id)

    if not del_ids:
        # A genuine multi-boundary shaft must have other components to remove;
        # none found means the curve collection did not see them.
        return False, "no other components found to remove (collection issue)"

    # Guard: never commit if the surviving BOUNDARY would be open. (Symbolic
    # lines are allowed to be open and are excluded from this check.)
    if not boundary_closed(kept_curves, ref_boundary, TOL):
        return False, "surviving boundary would be open - not attempted"

    scope = SketchEditScope(doc, "DQT - Trim shaft copy")
    scope.Start(sketch.Id)
    t = Transaction(doc, "DQT - Remove other openings")
    t.Start()
    for cid in del_ids:
        try:
            doc.Delete(cid)
        except:
            pass
    t.Commit()

    # Re-check the ACTUAL surviving boundary before committing the scope;
    # cancel on any doubt so Revit never raises the un-ignorable
    # "lines must be in closed loops" crash.
    try:
        survivors = [c for (_e, c) in collect_sketch_curves(sketch)]
    except:
        survivors = kept_curves
    if not survivors or not boundary_closed(survivors, ref_boundary, TOL):
        scope.Cancel()
        return False, "post-delete boundary not closed - cancelled safely"

    try:
        scope.Commit(_SwallowFailures())
    except Exception as ex:
        try:
            scope.Cancel()
        except:
            pass
        return False, "sketch commit failed: {}".format(ex)
    return True, "ok"


def split_shaft(opening):
    """Split one multi-boundary shaft into N single-boundary openings by
    copy-in-place + trim. Returns (created, failed, n) or None."""
    outer_loops = get_outer_openings(opening)
    n = len(outer_loops)
    total_loops = len(get_profile_loops(get_sketch(opening)))
    print("  Sketch profile: {} loop(s), {} outer opening(s)".format(
        total_loops, n))
    if n <= 1:
        print("  Shaft has one boundary (or unreadable) - skipping")
        return None

    # PHASE A - copy the whole shaft in place, once per outer boundary.
    src = List[ElementId]()
    src.Add(opening.Id)
    copy_ids = []
    t1 = Transaction(doc, "DQT - Copy shaft x{}".format(n))
    t1.Start()
    fho = t1.GetFailureHandlingOptions()
    fho.SetFailuresPreprocessor(_SwallowFailures())
    t1.SetFailureHandlingOptions(fho)
    for i in range(n):
        res = ElementTransformUtils.CopyElements(doc, src, XYZ(0, 0, 0))
        oid = None
        for rid in res:
            if is_shaft_opening(doc.GetElement(rid)):
                oid = rid
                break
        if oid is None:
            for rid in res:
                oid = rid
                break
        copy_ids.append(oid)
    t1.Commit()

    # PHASE B - trim each copy to a single outer boundary (SketchEditScope,
    # no open transaction).
    created = 0
    failed = 0
    for i, cid in enumerate(copy_ids):
        copy = doc.GetElement(cid) if cid is not None else None
        if copy is None:
            failed += 1
            print("  Opening {}: copy missing".format(i + 1))
            continue
        try:
            ok, msg = trim_copy_to_outer_loop(copy, outer_loops[i])
        except Exception as ex:
            ok, msg = False, "exception: {}".format(ex)
        print("  Opening {}: {}".format(i + 1, msg))
        if ok:
            created += 1
        else:
            failed += 1
            # Remove the copy we could not trim so we do not leave a full
            # duplicate overlapping the others.
            td = Transaction(doc, "DQT - Remove failed copy")
            td.Start()
            try:
                doc.Delete(cid)
            except:
                pass
            td.Commit()

    # PHASE C - delete the original only if every opening was created; if any
    # failed, keep the original so nothing is lost (user can retry / undo).
    if created == n:
        t2 = Transaction(doc, "DQT - Delete original shaft")
        t2.Start()
        try:
            doc.Delete(opening.Id)
        except Exception as ex:
            print("  Could not delete original shaft: {}".format(ex))
        t2.Commit()
    else:
        print("  Kept the ORIGINAL shaft ({}/{} openings created) - review "
              "before deleting it manually.".format(created, n))

    return created, failed, n


def main():
    try:
        result = forms.alert(
            "Split shaft openings that have several disconnected boundaries "
            "into separate single-boundary openings.\n\n"
            "Each new opening is a COPY of the original trimmed to one "
            "boundary, so parameters, holes and symbolic lines are kept.\n\n"
            "Click OK, then pick the shaft opening(s) to split.\n"
            "Press ESC or Finish when done.",
            title="Split Shaft Opening Tool",
            ok=True, cancel=True)
        if not result:
            return

        selected_openings = []
        try:
            references = uidoc.Selection.PickObjects(
                ObjectType.Element,
                "Select shaft openings to split (ESC / Finish when done)")
            for ref in references:
                element = doc.GetElement(ref.ElementId)
                if is_shaft_opening(element):
                    selected_openings.append(element)
                else:
                    print("Skipping non-shaft-opening: {} (ID: {})".format(
                        element.Category.Name if element.Category else "Unknown",
                        _eid_int(element.Id)))
        except:
            return

        if not selected_openings:
            forms.alert("No shaft openings selected.", exitscript=True)

        print("\n" + "=" * 60)
        print("SPLIT SHAFT OPENING - processing {} opening(s)".format(
            len(selected_openings)))
        print("=" * 60)

        total_created = 0
        total_failed = 0
        successful_splits = 0
        skipped = 0

        for idx, opening in enumerate(selected_openings):
            print("\n" + "-" * 60)
            print("Shaft Opening {}/{} (ID: {})".format(
                idx + 1, len(selected_openings), _eid_int(opening.Id)))
            print("-" * 60)
            try:
                res = split_shaft(opening)
                if res is None:
                    skipped += 1
                    continue
                created, failed, n = res
                total_created += created
                total_failed += failed
                if created > 0:
                    successful_splits += 1
                print("Result: {} created, {} failed".format(created, failed))
            except Exception as e:
                total_failed += 1
                import traceback
                print("FAILED: {}".format(e))
                print(traceback.format_exc())
                continue

        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print("Shaft openings picked: {}".format(len(selected_openings)))
        print("Split successfully:    {}".format(successful_splits))
        print("Skipped (single loop): {}".format(skipped))
        print("New openings created:  {}".format(total_created))
        print("Openings failed:       {}".format(total_failed))
        print("=" * 60)

        msg = (
            "Split Shaft Opening complete.\n\n"
            "Picked: {} shaft opening(s)\n"
            "Split: {}\n"
            "New openings created: {}"
        ).format(len(selected_openings), successful_splits, total_created)
        if skipped:
            msg += "\nSkipped (only one boundary): {}".format(skipped)
        if total_failed:
            msg += ("\n\n{} opening(s) could not be created (handled safely - "
                    "no crash). The original shaft was kept where any opening "
                    "failed; see the output window for the exact reason."
                    ).format(total_failed)
        else:
            msg += ("\n\nParameters, holes and symbolic lines were kept "
                    "(each opening is a trimmed copy of the original).")
        forms.alert(msg, title="Split Shaft Opening Summary")

    except Exception as e:
        import traceback
        print("\n=== MAIN ERROR ===")
        print(traceback.format_exc())
        forms.alert("Error: {}".format(e), exitscript=True)


if __name__ == "__main__":
    main()
