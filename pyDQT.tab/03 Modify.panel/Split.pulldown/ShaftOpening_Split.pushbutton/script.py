# -*- coding: utf-8 -*-
"""
Split Shaft Opening Tool

Splits a shaft opening that has several disconnected boundary loops into
separate individual shaft openings - one per boundary - while preserving
EVERYTHING the original held: all instance parameters, any holes, and the
user-drawn Symbolic Lines inside the boundaries.

Method (this mirrors the manual Revit workflow that reliably keeps
symbolic lines, requested by the user):

  For each outer boundary of the original shaft:
    1. COPY the whole shaft in place (Copy + Paste Aligned / Same Place).
       The copy already contains every boundary, every hole and every
       symbolic line as real sketch members - nothing is recreated.
    2. EDIT that copy's sketch and DELETE every loop / line that does NOT
       belong to the boundary we are keeping.
  Finally the original multi-boundary shaft is deleted.

Why this does not crash like the earlier version: we only ever DELETE
complete loops from an already-valid sketch. We never inject a new open
curve into a boundary sketch - injecting open curves is what made
SketchEditScope.Commit() validate an invalid profile and take Revit down.
Removing whole loops leaves a still-valid sketch (one closed outer loop,
its holes, and the symbolic lines that were always legal members).

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

# Endpoint-match tolerance in feet (~0.0003 mm). Copied curves are exact
# copies of the original profile curves, so this only needs to absorb
# floating-point noise.
TOL = 1e-6


def _eid_int(eid):
    """Integer value of an ElementId across Revit 2024-2027 (.IntegerValue is
    deprecated in 2024+ and removed in 2026+; use .Value)."""
    try:
        return eid.Value
    except:
        return eid.IntegerValue


class _SwallowFailures(IFailuresPreprocessor):
    """Silences the 'duplicate/overlapping elements' style warnings that appear
    while copies briefly overlap - they are expected and harmless here."""
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


def get_boundary_loops(sketch):
    """CurveLoop for each profile loop of the sketch (boundaries + holes)."""
    loops = []
    if sketch is None:
        return loops
    try:
        for curve_array in sketch.Profile:
            cl = CurveLoop()
            for c in curve_array:
                cl.Append(c)
            loops.append(cl)
    except Exception as ex:
        print("  Could not read sketch profile: {}".format(ex))
    return loops


def _midpoint(curve):
    try:
        return curve.Evaluate(0.5, True)
    except:
        try:
            return curve.GetEndPoint(0)
        except:
            return None


def point_in_loop(point, loop):
    """Even-odd horizontal ray-cast point-in-polygon test against a loop."""
    if point is None:
        return False
    ray_end = XYZ(point.X + 10000.0, point.Y, point.Z)
    try:
        ray = Line.CreateBound(point, ray_end)
    except:
        return False
    count = 0
    for curve in loop:
        try:
            if curve.Intersect(ray) == DB.SetComparisonResult.Overlap:
                count += 1
        except:
            pass
    return count % 2 == 1


def _loop_first_point(loop):
    for c in loop:
        return c.GetEndPoint(0)
    return None


def loop_is_inside(inner, outer):
    return point_in_loop(_loop_first_point(inner), outer)


def loop_bbox_area(loop):
    pts = []
    for c in loop:
        pts.append(c.GetEndPoint(0))
        pts.append(c.GetEndPoint(1))
    if not pts:
        return 0.0
    return (max(p.X for p in pts) - min(p.X for p in pts)) * \
           (max(p.Y for p in pts) - min(p.Y for p in pts))


def find_outer_loops(loops):
    """Subset of loops that are outer boundaries (not holes nested in a bigger
    loop). Each becomes one separate shaft opening."""
    data = [{'loop': l, 'area': loop_bbox_area(l)} for l in loops]
    data.sort(key=lambda d: d['area'], reverse=True)
    outers = []
    for i in range(len(data)):
        is_hole = False
        for j in range(len(data)):
            if i == j:
                continue
            if data[j]['area'] > data[i]['area'] and \
                    loop_is_inside(data[i]['loop'], data[j]['loop']):
                is_hole = True
                break
        if not is_hole:
            outers.append(data[i]['loop'])
    return outers


def _is_edge_of_loop(g, loop, tol):
    """True if curve g coincides with one of loop's edges (endpoints match in
    either direction, confirmed by midpoint to disambiguate arcs)."""
    a = g.GetEndPoint(0)
    b = g.GetEndPoint(1)
    mg = _midpoint(g)
    for lc in loop:
        la = lc.GetEndPoint(0)
        lb = lc.GetEndPoint(1)
        if (a.DistanceTo(la) < tol and b.DistanceTo(lb) < tol) or \
                (a.DistanceTo(lb) < tol and b.DistanceTo(la) < tol):
            ml = _midpoint(lc)
            if mg is None or ml is None or mg.DistanceTo(ml) < max(tol * 100, 1e-4):
                return True
    return False


def collect_sketch_curves(sketch):
    """Dependent elements of the sketch that expose a GeometryCurve (boundary
    edges + symbolic lines). Returns [(element, curve)]."""
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


def trim_copy_to_outer_loop(copy, outer_loop):
    """Edit the copy's sketch, deleting every curve that is NOT an edge of
    outer_loop and NOT inside it. Keeps outer_loop's edges, any holes inside
    it, and the symbolic lines that fall inside it.

    Runs its own SketchEditScope + transaction, so it must be called with NO
    transaction open. Returns (kept, deleted)."""
    sketch = get_sketch(copy)
    if sketch is None:
        print("  Copy has no sketch - cannot trim")
        return 0, 0

    curves = collect_sketch_curves(sketch)
    keep = 0
    del_ids = []
    for (e, g) in curves:
        if _is_edge_of_loop(g, outer_loop, TOL):
            keep += 1                                   # edge of kept loop
        elif point_in_loop(_midpoint(g), outer_loop):
            keep += 1                                   # hole edge / symbolic line inside
        else:
            del_ids.append(e.Id)                        # belongs to another opening

    if not del_ids:
        return keep, 0

    scope = SketchEditScope(doc, "DQT - Trim shaft copy")
    scope.Start(sketch.Id)
    t = Transaction(doc, "DQT - Remove other boundaries")
    t.Start()
    deleted = 0
    for cid in del_ids:
        try:
            doc.Delete(cid)
            deleted += 1
        except:
            pass
    t.Commit()
    scope.Commit(_SwallowFailures())
    return keep, deleted


def split_shaft(opening):
    """Split one multi-boundary shaft opening into N single-boundary openings
    by copy-in-place + trim. Returns (created, failed, n) or None if nothing
    to split."""
    sketch = get_sketch(opening)
    loops = get_boundary_loops(sketch)
    if len(loops) <= 1:
        print("  Shaft has only one boundary - skipping")
        return None

    outer_loops = find_outer_loops(loops)
    n = len(outer_loops)
    if n <= 1:
        print("  Only one outer boundary (rest are holes) - skipping")
        return None

    print("  {} loops in sketch -> {} separate openings".format(len(loops), n))

    # PHASE A - copy the whole shaft in place, once per outer boundary. Each
    # copy is a full duplicate (all boundaries, holes and symbolic lines).
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

    # PHASE B - trim each copy down to a single outer boundary. Uses
    # SketchEditScope, which must run with NO transaction open, so it lives
    # outside phase A's transaction.
    created = 0
    failed = 0
    for i, cid in enumerate(copy_ids):
        copy = doc.GetElement(cid) if cid is not None else None
        if copy is None:
            failed += 1
            print("  Opening {}: copy missing - skipped".format(i + 1))
            continue
        try:
            kept, deleted = trim_copy_to_outer_loop(copy, outer_loops[i])
            print("  Opening {}: kept {} curve(s), removed {}".format(
                i + 1, kept, deleted))
            created += 1
        except Exception as ex:
            failed += 1
            print("  Opening {}: trim FAILED ({}) - removing partial copy".format(
                i + 1, ex))
            # A copy we could not trim is a full duplicate overlapping the
            # others; remove it so we do not leave junk behind.
            td = Transaction(doc, "DQT - Remove failed copy")
            td.Start()
            try:
                doc.Delete(cid)
            except:
                pass
            td.Commit()

    # PHASE C - delete the original multi-boundary shaft.
    t2 = Transaction(doc, "DQT - Delete original shaft")
    t2.Start()
    try:
        doc.Delete(opening.Id)
    except Exception as ex:
        print("  Could not delete original shaft: {}".format(ex))
    t2.Commit()

    return created, failed, n


def main():
    try:
        result = forms.alert(
            "Split shaft openings that have several disconnected boundaries "
            "into separate single-boundary openings.\n\n"
            "Each new opening is a COPY of the original trimmed to one "
            "boundary, so parameters, holes and user-drawn symbolic lines are "
            "kept.\n\n"
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
                print("Result: {} new opening(s) created, {} failed".format(
                    created, failed))
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
            msg += "\n\n{} opening(s) could not be created - see the output " \
                   "window for details.".format(total_failed)
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
