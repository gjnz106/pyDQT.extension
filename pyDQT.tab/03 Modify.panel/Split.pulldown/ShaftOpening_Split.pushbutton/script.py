# -*- coding: utf-8 -*-
"""
Split Shaft Opening Tool
Splits a shaft opening with multiple disconnected boundaries into separate
individual shaft openings.

Note: a shaft Opening (unlike Floor/Ceiling) can only hold ONE boundary loop
per element (Document.Create.NewOpening takes a single CurveArray), so holes
inside a boundary cannot be preserved on the new openings - they are dropped
with a warning if found.

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

    print("\nFound {} curve loops in shaft opening".format(len(curve_loops)))

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
            except Exception as e:
                print("  WARNING: Failed to create shaft opening {}: {}".format(
                    idx + 1, str(e)))

        doc.Delete(opening.Id)

        t.Commit()

        return new_openings, dropped_holes_total

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
                    new_openings, dropped_holes = result
                    total_created += len(new_openings)
                    total_dropped_holes += dropped_holes
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
        print("=" * 60)

        summary_message = (
            "Split Shaft Opening Complete!\n\n"
            "Processed: {} shaft opening(s)\n"
            "Successful: {}\n"
            "Failed: {}\n"
            "Total new shaft openings created: {}"
        ).format(len(selected_openings), successful_splits, failed_splits, total_created)
        if total_dropped_holes:
            summary_message += "\n\n{} hole(s) could not be preserved (shaft openings " \
                "support only one boundary each) and were dropped.".format(
                    total_dropped_holes)

        forms.alert(summary_message, title="Split Shaft Opening Summary")

    except Exception as e:
        import traceback
        print("\n=== MAIN ERROR ===")
        print(traceback.format_exc())
        forms.alert("Error: {}".format(str(e)), exitscript=True)


if __name__ == "__main__":
    main()
