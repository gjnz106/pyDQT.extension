# -*- coding: utf-8 -*-
"""
Split Shaft Opening Tool
Splits a shaft opening with multiple disconnected boundaries into separate
individual shaft openings.

Note: a shaft Opening (unlike Floor/Ceiling) can only hold ONE boundary loop
per element (Document.Create.NewOpening takes a single CurveArray), so holes
inside a boundary cannot be preserved on the new openings - they are dropped
with a warning if found.

User-drawn "Symbolic Line" marks inside the original sketch (extra lines added
with the Symbolic Line tool while editing the shaft's boundary) ARE captured
and restored on the matching new opening.

Dang Quoc Truong - DQT (c) 2026
"""

__title__ = "Split\nShaft"
__author__ = "DQT"

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import ObjectType
from pyrevit import revit, DB, UI, forms
import math
import clr
clr.AddReference('System.Core')


def _eid_int(eid):
    """Get integer value of an ElementId across Revit 2024-2027.
    .IntegerValue is deprecated in 2024+ and removed in 2026+; use .Value."""
    try:
        return eid.Value
    except:
        return eid.IntegerValue


doc = revit.doc
uidoc = revit.uidoc


def is_shaft_opening(elem):
    if not isinstance(elem, Opening):
        return False
    try:
        cat = elem.Category
        return cat is not None and cat.Id == Category.GetCategory(
            doc, DB.BuiltInCategory.OST_ShaftOpening).Id
    except:
        return False


def get_curve_loops_from_opening(opening):
    """Extract all curve loops from a shaft opening's sketch"""
    curve_loops = []

    sketch_filter = DB.ElementClassFilter(DB.Sketch)
    dependent_elements = opening.GetDependentElements(sketch_filter)

    if dependent_elements.Count > 0:
        sketch_id = dependent_elements[0]
        sketch_obj = doc.GetElement(sketch_id)

        if sketch_obj:
            profile = sketch_obj.Profile

            for curve_array in profile:
                curve_loop = CurveLoop()
                for curve in curve_array:
                    curve_loop.Append(curve)
                curve_loops.append(curve_loop)

    return curve_loops


def _curve_midpoint(curve):
    try:
        return curve.Evaluate(0.5, True)
    except:
        try:
            return curve.GetEndPoint(0)
        except:
            return None


def get_symbolic_lines(elem, curve_loops):
    """User-drawn extra lines inside the shaft's sketch (e.g. a Symbolic Line
    drawn while editing the boundary). These are NOT part of Sketch.Profile
    (which only holds the closed boundary loops), so they must be located
    separately or they are lost when the original opening is deleted.

    Detection is done WITHOUT relying on a specific BuiltInCategory name (there
    is no OST_SymbolicLines - referencing it is what crashed the earlier
    version). Instead every element that DEPENDS on the opening (and on its
    sketch) is walked; any of them that exposes a GeometryCurve whose midpoint
    lands strictly inside one of this shaft's boundary loops is treated as a
    line to preserve. Boundary edges are excluded because their midpoints lie
    ON a loop, not inside it. Wrapped so it can never raise - a detection
    failure must not abort the split itself."""
    found = {}   # id(int) -> (curve, style_id)

    def _collect(e):
        if e is None:
            return
        try:
            curve = e.GeometryCurve
        except:
            return
        if curve is None:
            return
        mid = _curve_midpoint(curve)
        if mid is None:
            return
        if not any(point_in_loop(mid, loop) for loop in curve_loops):
            return
        key = _eid_int(e.Id)
        if key in found:
            return
        style_id = None
        try:
            style_id = e.LineStyle.Id
        except:
            pass
        found[key] = (curve, style_id)

    # Hosts to walk: the opening plus its sketch(es).
    hosts = [("Opening", elem)]
    try:
        for did in elem.GetDependentElements(DB.ElementClassFilter(DB.Sketch)):
            sk = doc.GetElement(did)
            if sk is not None:
                hosts.append(("Sketch", sk))
    except Exception as ex:
        print("  (could not enumerate sketches: {})".format(ex))

    for host_name, host in hosts:
        before = len(found)
        try:
            for did in host.GetDependentElements(None):
                _collect(doc.GetElement(did))
        except Exception as ex:
            print("  GetDependentElements({}) failed: {}".format(host_name, ex))
            continue
        print("  {} dependents -> {} line(s) inside boundary".format(
            host_name, len(found) - before))

    # Fallback: geometric search over concrete curve classes across the whole
    # document (class names resolved defensively via getattr).
    if not found:
        print("  Nothing via dependents - trying a global geometry search...")
        for cls_name in ("SymbolicCurve", "ModelLine", "ModelCurve",
                         "ModelArc", "DetailLine", "DetailCurve"):
            cls = getattr(DB, cls_name, None)
            if cls is None:
                continue
            try:
                coll = list(FilteredElementCollector(doc).OfClass(cls)
                            .WhereElementIsNotElementType())
            except Exception:
                continue
            before = len(found)
            for e in coll:
                _collect(e)
            if coll:
                print("  {}: {} in doc, {} matched inside boundary".format(
                    cls_name, len(coll), len(found) - before))

    print("  Total lines to preserve: {}".format(len(found)))
    return list(found.values())


def point_in_loop(point, loop):
    """Even-odd ray-cast point-in-polygon test against a curve loop (same
    method as check_if_loop_is_inside, but against a raw point)."""
    ray_end = XYZ(point.X + 10000, point.Y, point.Z)
    ray = Line.CreateBound(point, ray_end)
    intersection_count = 0
    for curve in loop:
        try:
            result = curve.Intersect(ray)
            if result == DB.SetComparisonResult.Overlap:
                intersection_count += 1
        except:
            pass
    return intersection_count % 2 == 1


def symbolic_lines_for_loop(symbolic_lines, loop):
    """Which of the captured symbolic lines belong inside this boundary loop
    (tested by the line's midpoint) - so each split piece only gets back the
    marks that were drawn inside its own footprint."""
    result = []
    for curve, style_id in symbolic_lines:
        try:
            mid = curve.Evaluate(0.5, True)
        except:
            mid = curve.GetEndPoint(0)
        if point_in_loop(mid, loop):
            result.append((curve, style_id))
    return result


def _make_sketch_plane_at(curve):
    try:
        p0 = curve.GetEndPoint(0)
        plane = Plane.CreateByNormalAndOrigin(XYZ.BasisZ, XYZ(0, 0, p0.Z))
        return SketchPlane.Create(doc, plane)
    except:
        return None


def recreate_symbolic_lines(symbolic_lines):
    """Best-effort: recreate each captured symbolic line. Tries
    Document.Create.NewSymbolicCurve first (the exact match for the original
    element type, but its availability/signature isn't confirmed against a
    live Revit API); falls back to a plain Model Line at the same location so
    the mark is visually restored either way. Returns (created, dropped)."""
    created = 0
    dropped = 0
    for curve, style_id in symbolic_lines:
        sketch_plane = _make_sketch_plane_at(curve)
        if sketch_plane is None:
            dropped += 1
            continue
        c = curve.Clone()
        new_elem = None
        for args in ((c, sketch_plane), (sketch_plane, c)):
            try:
                new_elem = doc.Create.NewSymbolicCurve(*args)
                if new_elem is not None:
                    break
            except:
                new_elem = None
        if new_elem is None:
            try:
                new_elem = doc.Create.NewModelCurve(c, sketch_plane)
            except:
                new_elem = None
        if new_elem is None:
            dropped += 1
            continue
        if style_id is not None:
            try:
                new_elem.LineStyle = doc.GetElement(style_id)
            except:
                pass
        created += 1
    return created, dropped


def check_if_loop_is_inside(inner_loop, outer_loop):
    """Check if inner_loop is inside outer_loop"""
    test_point = None
    for curve in inner_loop:
        test_point = curve.GetEndPoint(0)
        break

    if not test_point:
        return False

    ray_end = XYZ(test_point.X + 10000, test_point.Y, test_point.Z)
    ray = Line.CreateBound(test_point, ray_end)

    intersection_count = 0
    for curve in outer_loop:
        try:
            result = curve.Intersect(ray)
            if result == DB.SetComparisonResult.Overlap:
                intersection_count += 1
        except:
            pass

    return intersection_count % 2 == 1


def get_opening_levels(opening):
    """(base_level, top_level_or_None, top_connected) read from the shaft's
    Base Constraint / Top Constraint instance parameters."""
    base_level = None
    top_level = None
    top_connected = False

    p_base = opening.LookupParameter("Base Constraint")
    if p_base:
        bid = p_base.AsElementId()
        if bid and bid != ElementId.InvalidElementId:
            base_level = doc.GetElement(bid)

    p_top = opening.LookupParameter("Top Constraint")
    if p_top:
        tid = p_top.AsElementId()
        if tid and tid != ElementId.InvalidElementId:
            tl = doc.GetElement(tid)
            if isinstance(tl, Level):
                top_level = tl
                top_connected = True

    return base_level, top_level, top_connected


def _copy_named_double(src, dst, name):
    try:
        sp = src.LookupParameter(name)
        dp = dst.LookupParameter(name)
        if sp and dp and not dp.IsReadOnly:
            dp.Set(sp.AsDouble())
    except:
        pass


def copy_shaft_params(src, dst, top_connected):
    """Best-effort copy of the offset/height parameters (by display name -
    the exact BuiltInParameter enum for shaft openings isn't confirmed, so
    LookupParameter by the UI name is used instead).

    Base Offset always applies. For Top: if the original was connected to a
    level, only Top Offset needs copying (NewOpening already set Top
    Constraint to the right level). If the original was UNCONNECTED, Top
    Constraint must be set to InvalidElementId FIRST - Unconnected Height stays
    read-only/inapplicable while Top Constraint still points at a level, so
    setting it beforehand silently does nothing and the new opening ends up
    with the wrong (near-zero) vertical extent, which is why Revit stops
    drawing the shaft's symbolic (not-cut-by-view) cross line."""
    _copy_named_double(src, dst, "Base Offset")

    if top_connected:
        _copy_named_double(src, dst, "Top Offset")
        return

    try:
        dp_top = dst.LookupParameter("Top Constraint")
        if dp_top and not dp_top.IsReadOnly:
            dp_top.Set(ElementId.InvalidElementId)
    except:
        pass
    doc.Regenerate()   # let "Unconnected Height" become editable
    _copy_named_double(src, dst, "Unconnected Height")


def create_opening_from_curve_loop(base_level, top_level, curve_loop):
    """Create a new shaft opening from a single curve loop (no holes)."""
    curve_array = CurveArray()
    for curve in curve_loop:
        curve_array.Append(curve)

    print("  Base level: {}".format(base_level.Name if base_level else "?"))
    print("  Top level: {}".format(top_level.Name if top_level else "?"))
    print("  Calling NewOpening...")

    new_opening = doc.Create.NewOpening(base_level, top_level, curve_array)
    print("  Shaft opening created successfully: {}".format(_eid_int(new_opening.Id)))

    return new_opening


def split_shaft(opening):
    """Split a shaft opening with multiple boundaries into separate openings"""
    base_level, top_level, top_connected = get_opening_levels(opening)
    if base_level is None:
        print("  ERROR: could not read Base Constraint level - skipping")
        return None
    if top_level is None:
        # NewOpening requires two Level objects; use the base level as a
        # stand-in and restore "unconnected" afterwards via copy_shaft_params.
        top_level = base_level

    curve_loops = get_curve_loops_from_opening(opening)

    if len(curve_loops) <= 1:
        print("  Shaft opening has only one boundary - skipping")
        return None

    try:
        all_symbolic_lines = get_symbolic_lines(opening, curve_loops)
    except Exception as ex:
        # Preserving symbolic lines is a bonus - never let it stop the split.
        print("  (symbolic-line detection error, continuing split: {})".format(ex))
        all_symbolic_lines = []
    print("\nFound {} curve loops in shaft opening".format(len(curve_loops)))
    if all_symbolic_lines:
        print("Found {} symbolic line(s) drawn in the sketch".format(
            len(all_symbolic_lines)))

    loop_data = []
    for i, loop in enumerate(curve_loops):
        curve_count = sum(1 for _ in loop)

        points = []
        for curve in loop:
            points.append(curve.GetEndPoint(0))
            points.append(curve.GetEndPoint(1))

        if points:
            min_x = min(p.X for p in points)
            max_x = max(p.X for p in points)
            min_y = min(p.Y for p in points)
            max_y = max(p.Y for p in points)
            bbox_area = (max_x - min_x) * (max_y - min_y)
        else:
            bbox_area = 0

        loop_data.append({
            'index': i,
            'loop': loop,
            'curve_count': curve_count,
            'area': bbox_area,
        })

        print("Loop {}: {} curves, area = {:.2f}".format(i, curve_count, bbox_area))

    loop_data.sort(key=lambda x: x['area'], reverse=True)

    print("\nChecking for inside/outside relationships...")

    is_hole = [False] * len(loop_data)
    parent_of = [-1] * len(loop_data)

    for i in range(len(loop_data)):
        for j in range(len(loop_data)):
            if i == j:
                continue
            if check_if_loop_is_inside(loop_data[i]['loop'], loop_data[j]['loop']):
                if loop_data[j]['area'] > loop_data[i]['area']:
                    is_hole[i] = True
                    parent_of[i] = j
                    print("  Loop {} is inside Loop {} (hole - will be DROPPED, "
                          "shaft openings support only one boundary)".format(
                              loop_data[i]['index'], loop_data[j]['index']))
                    break

    main_boundaries = []
    for i, data in enumerate(loop_data):
        if not is_hole[i]:
            hole_count = sum(1 for j in range(len(loop_data)) if parent_of[j] == i)
            main_boundaries.append({
                'loop': data['loop'],
                'index': data['index'],
                'area': data['area'],
                'curve_count': data['curve_count'],
                'dropped_holes': hole_count,
            })

    print("\nAnalysis:")
    print("  Total loops: {}".format(len(loop_data)))
    print("  Main boundaries: {}".format(len(main_boundaries)))
    print("  Holes: {}".format(sum(is_hole)))

    if len(main_boundaries) <= 1:
        print("\nOnly one main boundary found - skipping split")
        return None

    print("\nCreating {} separate shaft openings".format(len(main_boundaries)))

    t = Transaction(doc, "DQT - Split Shaft {} into {} Openings".format(
        _eid_int(opening.Id), len(main_boundaries)))
    t.Start()

    try:
        new_openings = []
        dropped_holes_total = 0
        symbolic_created_total = 0
        symbolic_dropped_total = 0

        for idx, data in enumerate(main_boundaries):
            print("\nCreating shaft opening {} (area: {:.2f}, {} curves, "
                  "{} hole(s) dropped)".format(
                      idx + 1, data['area'], data['curve_count'],
                      data['dropped_holes']))
            dropped_holes_total += data['dropped_holes']
            try:
                new_opening = create_opening_from_curve_loop(
                    base_level, top_level, data['loop'])
                copy_shaft_params(opening, new_opening, top_connected)
                new_openings.append(new_opening)

                my_symbolic = symbolic_lines_for_loop(
                    all_symbolic_lines, data['loop'])
                if my_symbolic:
                    s_created, s_dropped = recreate_symbolic_lines(my_symbolic)
                    symbolic_created_total += s_created
                    symbolic_dropped_total += s_dropped
                    print("  Restored {} symbolic line(s), {} dropped".format(
                        s_created, s_dropped))
            except Exception as e:
                print("  WARNING: Failed to create shaft opening {}: {}".format(
                    idx + 1, str(e)))

        doc.Delete(opening.Id)

        t.Commit()

        return (new_openings, dropped_holes_total,
                symbolic_created_total, symbolic_dropped_total)

    except Exception as e:
        t.RollBack()
        import traceback
        print("\n=== ERROR IN SPLIT_SHAFT ===")
        print(traceback.format_exc())
        raise e


def main():
    """Main function"""
    try:
        result = forms.alert(
            "Select multiple shaft openings with disconnected boundaries to split.\n\n"
            "Note: shaft openings can only hold one boundary each, so any hole\n"
            "inside a boundary will be dropped on the new openings.\n\n"
            "Click OK to start selecting shaft openings.\n"
            "Press ESC or Finish when done.",
            title="Split Shaft Opening Tool",
            ok=True,
            cancel=True
        )

        if not result:
            return

        selected_openings = []
        try:
            references = uidoc.Selection.PickObjects(
                ObjectType.Element,
                "Select shaft openings to split (Press ESC or Finish when done)"
            )

            for ref in references:
                element = doc.GetElement(ref.ElementId)
                if is_shaft_opening(element):
                    selected_openings.append(element)
                else:
                    print("Skipping non-shaft-opening element: {} (ID: {})".format(
                        element.Category.Name if element.Category else "Unknown",
                        element.Id
                    ))
        except:
            return

        if not selected_openings:
            forms.alert("No shaft openings selected.", exitscript=True)

        print("\n" + "=" * 60)
        print("SPLIT SHAFT OPENING TOOL - Processing {} opening(s)".format(
            len(selected_openings)))
        print("=" * 60)

        total_created = 0
        total_dropped_holes = 0
        total_symbolic_created = 0
        total_symbolic_dropped = 0
        successful_splits = 0
        failed_splits = 0

        for idx, opening in enumerate(selected_openings):
            print("\n" + "-" * 60)
            print("Processing Shaft Opening {}/{} (ID: {})".format(
                idx + 1, len(selected_openings), _eid_int(opening.Id)))
            print("-" * 60)

            try:
                result = split_shaft(opening)
                if result:
                    new_openings, dropped_holes, sym_created, sym_dropped = result
                    total_created += len(new_openings)
                    total_dropped_holes += dropped_holes
                    total_symbolic_created += sym_created
                    total_symbolic_dropped += sym_dropped
                    successful_splits += 1
                    print("SUCCESS: Created {} shaft openings from this split".format(
                        len(new_openings)))
            except Exception as e:
                failed_splits += 1
                print("FAILED: {}".format(str(e)))
                continue

        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print("Shaft openings processed: {}".format(len(selected_openings)))
        print("Successful splits: {}".format(successful_splits))
        print("Failed splits: {}".format(failed_splits))
        print("Total new shaft openings created: {}".format(total_created))
        print("Total holes dropped: {}".format(total_dropped_holes))
        print("Symbolic lines restored: {}".format(total_symbolic_created))
        print("Symbolic lines dropped: {}".format(total_symbolic_dropped))
        print("=" * 60)

        summary_message = (
            "Split Shaft Opening Complete!\n\n"
            "Processed: {} shaft opening(s)\n"
            "Successful: {}\n"
            "Failed: {}\n"
            "Total new shaft openings created: {}"
        ).format(len(selected_openings), successful_splits, failed_splits, total_created)
        if total_symbolic_created:
            summary_message += "\n\nRestored {} symbolic line(s) drawn in the original " \
                "sketch(es).".format(total_symbolic_created)
        if total_dropped_holes:
            summary_message += "\n\n{} hole(s) could not be preserved (shaft openings " \
                "support only one boundary each) and were dropped.".format(
                    total_dropped_holes)
        if total_symbolic_dropped:
            summary_message += "\n\n{} symbolic line(s) could not be restored.".format(
                total_symbolic_dropped)

        forms.alert(summary_message, title="Split Shaft Opening Summary")

    except Exception as e:
        import traceback
        print("\n=== MAIN ERROR ===")
        print(traceback.format_exc())
        forms.alert("Error: {}".format(str(e)), exitscript=True)


if __name__ == "__main__":
    main()
