# -*- coding: utf-8 -*-
"""
Auto Opening - Create wall openings from MEP Linked model intersections
Copyright (c) 2025 Dang Quoc Truong (DQT)
"""

__title__ = "Auto\nOpening"
__author__ = "Dang Quoc Truong (DQT)"
__doc__ = "Automatically create rectangular openings in walls based on MEP elements from Revit linked models. Supports update when MEP link changes."

import clr
import sys
import math

clr.AddReference('System')
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')

from System.Collections.Generic import List
from System.Windows import (
    Window, WindowStartupLocation, Thickness, CornerRadius,
    HorizontalAlignment, VerticalAlignment, ResizeMode, FontWeights, FontStyles,
    Visibility, TextWrapping, GridLength, GridUnitType
)
from System.Windows.Controls import (
    StackPanel, DockPanel, Border, TextBlock, TextBox,
    Button, ListBox, ComboBox, CheckBox, RadioButton,
    Orientation, Dock, ScrollViewer, ScrollBarVisibility,
    SelectionMode, ProgressBar, Grid as WpfGrid,
    ColumnDefinition, RowDefinition
)
from System.Windows.Media import BrushConverter
from System.Windows.Input import Cursors, Keyboard, ModifierKeys, MouseButtonState
import System.Windows

import Autodesk.Revit.DB as DB
from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, BuiltInParameter,
    Transaction, TransactionGroup, XYZ, Line, Plane,
    ElementId, BoundingBoxXYZ, Transform, Options, Solid, GeometryInstance,
    FamilyInstance, Wall, RevitLinkInstance, RevitLinkType,
    Opening, ElementCategoryFilter, StorageType,
    FailureProcessingResult, IFailuresPreprocessor
)
from Autodesk.Revit.UI import TaskDialog, TaskDialogCommonButtons, TaskDialogResult


# =====================================================================
# REVIT VERSION COMPATIBILITY - ElementId.IntegerValue vs .Value
# =====================================================================
def _eid_int(eid):
    """Get integer value from ElementId - compatible with Revit 2024 (.IntegerValue) and 2026 (.Value)"""
    if eid is None:
        return 0
    try:
        return eid.Value
    except:
        try:
            return eid.IntegerValue
        except:
            return 0


# =====================================================================
# WARNING SUPPRESSOR - Auto dismiss warnings during opening creation
# =====================================================================
class WarningSwallower(IFailuresPreprocessor):
    """Automatically dismiss all warnings (not errors) during transactions"""
    def PreprocessFailures(self, failuresAccessor):
        try:
            failures = failuresAccessor.GetFailureMessages()
            for f in failures:
                try:
                    severity = f.GetSeverity()
                    # Delete warnings, leave errors
                    if severity == DB.FailureSeverity.Warning:
                        failuresAccessor.DeleteWarning(f)
                except:
                    pass
        except:
            pass
        return FailureProcessingResult.Continue


def project_point_on_wall(pt, wall):
    """
    Project a 3D point precisely onto the wall's centerline curve.
    Clamps the point to wall extents if slightly outside.
    Returns the projected XYZ or None only if far outside wall.
    """
    try:
        wc = wall.Location.Curve
        ws = wc.GetEndPoint(0)
        we = wc.GetEndPoint(1)
        wd = (we - ws).Normalize()

        # Parameter along wall curve
        param_along = (pt - ws).DotProduct(wd)
        wall_len = wc.Length

        # Reject only if very far outside wall (> 1 foot beyond ends)
        if param_along < -1.0 or param_along > wall_len + 1.0:
            return None

        # Clamp to wall extents (keep opening within wall bounds)
        param_along = max(0.0, min(wall_len, param_along))

        # Project onto wall centerline (remove normal component)
        projected = ws + wd.Multiply(param_along) + XYZ(0, 0, pt.Z - ws.Z)

        # Clamp Z within wall bbox (don't reject, clamp)
        wbb = wall.get_BoundingBox(None)
        if wbb:
            z = projected.Z
            if z < wbb.Min.Z:
                z = wbb.Min.Z + 0.05
            if z > wbb.Max.Z:
                z = wbb.Max.Z - 0.05
            projected = XYZ(projected.X, projected.Y, z)

        return projected
    except:
        return None


def create_opening_safe(wall, center_pt, half_w, half_h):
    """
    Create opening with points projected precisely on wall centerline.
    Returns (opening, error_msg) tuple.
    """
    try:
        wc = wall.Location.Curve
        ws = wc.GetEndPoint(0)
        we = wc.GetEndPoint(1)
        wd = (we - ws).Normalize()

        # Project center onto wall centerline
        projected = project_point_on_wall(center_pt, wall)
        if projected is None:
            return None, "Point outside wall"

        # Compute corners along wall direction + Z
        p1 = projected + wd.Multiply(-half_w) + XYZ(0, 0, -half_h)
        p2 = projected + wd.Multiply(half_w) + XYZ(0, 0, half_h)

        # Validate opening fits within wall extents
        wbb = wall.get_BoundingBox(None)
        if wbb:
            # Check opening doesn't exceed wall height
            if p1.Z < wbb.Min.Z - 0.05:
                p1 = XYZ(p1.X, p1.Y, wbb.Min.Z + 0.05)
            if p2.Z > wbb.Max.Z + 0.05:
                p2 = XYZ(p2.X, p2.Y, wbb.Max.Z - 0.05)
            # Ensure minimum opening size
            if p2.Z - p1.Z < 0.05:
                return None, "Opening too small after clamping"

        opening = doc.Create.NewOpening(wall, p1, p2)
        return opening, None
    except Exception as ex:
        return None, str(ex)[:80]

uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document

# =====================================================================
# BRANDING & COLORS
# =====================================================================
_conv = BrushConverter()
def brush(c):
    return _conv.ConvertFromString(c)

PRIMARY = "#F0CC88"
SECONDARY = "#FEF8E7"
ACCENT = "#C89650"
WHITE = "#FFFFFF"
BORDER_COLOR = "#E0E0E0"
TEXT_DARK = "#333333"
TEXT_GRAY = "#666666"
TEXT_MUTED = "#999999"
SUCCESS = "#4CAF50"
ERROR = "#F44336"
WARNING = "#FF9800"
INFO = "#2196F3"
HIGHLIGHT = "#C8E6C9"
LIGHT_GRAY = "#F5F5F5"
ORPHAN_BG = "#FFF3E0"
UPDATE_BG = "#E3F2FD"

# =====================================================================
# CONSTANTS
# =====================================================================
FEET_TO_MM = 304.8
MM_TO_FEET = 1.0 / 304.8

DQT_TAG_PREFIX = "DQT_AUTO_OPENING"

MEP_CATEGORY_NAMES = {
    BuiltInCategory.OST_PipeCurves: "Pipes",
    BuiltInCategory.OST_DuctCurves: "Ducts",
    BuiltInCategory.OST_CableTray: "Cable Trays",
    BuiltInCategory.OST_Conduit: "Conduits",
    BuiltInCategory.OST_FlexDuctCurves: "Flex Ducts",
    BuiltInCategory.OST_FlexPipeCurves: "Flex Pipes",
    BuiltInCategory.OST_PipeFitting: "Pipe Fittings",
    BuiltInCategory.OST_DuctFitting: "Duct Fittings",
    BuiltInCategory.OST_CableTrayFitting: "Cable Tray Fittings",
    BuiltInCategory.OST_ConduitFitting: "Conduit Fittings",
}

# Column definitions: (key, header_text, width, sort_attr)
COLUMNS = [
    ("select",   "",         30,  None),
    ("status",   "Status",   75,  "status"),
    ("wall",     "Wall",     115, "wall_name"),
    ("level",    "Level",    75,  "wall_level"),
    ("category", "Category", 90,  "mep_category"),
    ("size",     "Size",     80,  "mep_size"),
    ("link",     "Link",     115, "link_name"),
    ("w_mm",     "W(mm)",    70,  "_sort_w"),
    ("h_mm",     "H(mm)",    70,  "_sort_h"),
    ("result",   "Result",   100, None),
]


# =====================================================================
# DATA CLASS
# =====================================================================
class IntersectionResult:
    def __init__(self):
        self.wall_id = None
        self.wall_name = ""
        self.wall_level = ""
        self.mep_id = None
        self.mep_name = ""
        self.mep_category = ""
        self.mep_size = ""
        self.link_name = ""
        self.link_instance = None
        self.intersection_point = None
        self.opening_width = 0
        self.opening_height = 0
        self.is_selected = True
        self.status = "New"
        self.existing_opening_id = None
        self.tracking_key = ""

    @property
    def _sort_w(self):
        return self.opening_width

    @property
    def _sort_h(self):
        return self.opening_height

    def build_tracking_key(self):
        mep_int = _eid_int(self.mep_id)
        wall_int = _eid_int(self.wall_id)
        self.tracking_key = str(self.link_name) + "::" + str(mep_int) + "::" + str(wall_int)
        return self.tracking_key

    def build_tag_string(self):
        w_str = str(round(self.opening_width, 6))
        h_str = str(round(self.opening_height, 6))
        pt_str = ""
        if self.intersection_point:
            pt_str = str(round(self.intersection_point.X, 6)) + "," + str(round(self.intersection_point.Y, 6)) + "," + str(round(self.intersection_point.Z, 6))
        return DQT_TAG_PREFIX + "::" + self.tracking_key + "::" + w_str + "::" + h_str + "::" + pt_str


# =====================================================================
# TRACKING
# =====================================================================
def find_existing_dqt_openings():
    existing = {}
    for cat in [BuiltInCategory.OST_SWallRectOpening, BuiltInCategory.OST_GenericModel]:
        try:
            openings = FilteredElementCollector(doc)\
                .OfCategory(cat)\
                .WhereElementIsNotElementType()\
                .ToElements()
            for op in openings:
                try:
                    comment_param = op.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
                    if comment_param is None or not comment_param.HasValue:
                        continue
                    tag = comment_param.AsString()
                    if tag and tag.startswith(DQT_TAG_PREFIX + "::"):
                        parts = tag.split("::")
                        if len(parts) >= 4:
                            key = parts[1] + "::" + parts[2] + "::" + parts[3]
                            existing[key] = (op, tag)
                except:
                    continue
        except:
            continue

    try:
        all_walls = FilteredElementCollector(doc)\
            .OfCategory(BuiltInCategory.OST_Walls)\
            .WhereElementIsNotElementType()\
            .ToElements()
        for wall in all_walls:
            try:
                dep_ids = wall.GetDependentElements(None)
                if dep_ids:
                    for did in dep_ids:
                        dep_el = doc.GetElement(did)
                        if dep_el is None:
                            continue
                        try:
                            cp = dep_el.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
                            if cp and cp.HasValue:
                                tag = cp.AsString()
                                if tag and tag.startswith(DQT_TAG_PREFIX + "::"):
                                    parts = tag.split("::")
                                    if len(parts) >= 4:
                                        key = parts[1] + "::" + parts[2] + "::" + parts[3]
                                        if key not in existing:
                                            existing[key] = (dep_el, tag)
                        except:
                            continue
            except:
                continue
    except:
        pass

    return existing


def write_opening_tag(opening_element, tag_string):
    try:
        cp = opening_element.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        if cp and not cp.IsReadOnly:
            cp.Set(tag_string)
            return True
    except:
        pass
    return False


# =====================================================================
# GEOMETRY HELPERS
# =====================================================================
def get_mep_diameter_or_size(element):
    w = 0
    h = 0
    d = 0
    for pname in ["Diameter", "Outside Diameter"]:
        try:
            p = element.LookupParameter(pname)
            if p and p.HasValue:
                d = p.AsDouble() * FEET_TO_MM
                if d > 0:
                    return d, 0, 0
        except:
            pass
    for bip in [BuiltInParameter.RBS_PIPE_DIAMETER_PARAM,
                BuiltInParameter.RBS_CURVE_DIAMETER_PARAM]:
        try:
            p = element.get_Parameter(bip)
            if p and p.HasValue:
                d = p.AsDouble() * FEET_TO_MM
                if d > 0:
                    return d, 0, 0
        except:
            pass
    try:
        p = element.LookupParameter("Width")
        if p and p.HasValue:
            w = p.AsDouble() * FEET_TO_MM
    except:
        pass
    try:
        p = element.LookupParameter("Height")
        if p and p.HasValue:
            h = p.AsDouble() * FEET_TO_MM
    except:
        pass
    if w == 0:
        try:
            p = element.get_Parameter(BuiltInParameter.RBS_CURVE_WIDTH_PARAM)
            if p and p.HasValue:
                w = p.AsDouble() * FEET_TO_MM
        except:
            pass
    if h == 0:
        try:
            p = element.get_Parameter(BuiltInParameter.RBS_CURVE_HEIGHT_PARAM)
            if p and p.HasValue:
                h = p.AsDouble() * FEET_TO_MM
        except:
            pass
    return d, w, h


def get_mep_location_curve(element):
    try:
        loc = element.Location
        if hasattr(loc, 'Curve'):
            return loc.Curve
    except:
        pass
    return None


def line_wall_intersection(line_start, line_end, wall):
    try:
        wall_loc = wall.Location
        if not hasattr(wall_loc, 'Curve'):
            return None
        wall_curve = wall_loc.Curve
        wall_start = wall_curve.GetEndPoint(0)
        wall_end = wall_curve.GetEndPoint(1)
        wall_dir = (wall_end - wall_start).Normalize()
        wall_normal = XYZ(-wall_dir.Y, wall_dir.X, 0).Normalize()

        denom = (line_end - line_start).DotProduct(wall_normal)
        if abs(denom) < 1e-10:
            return None
        t = (wall_start - line_start).DotProduct(wall_normal) / denom
        if t < -0.01 or t > 1.01:
            return None

        pt = line_start + (line_end - line_start).Multiply(t)

        wall_param = (pt - wall_start).DotProduct(wall_dir) / wall_curve.Length
        if wall_param < -0.01 or wall_param > 1.01:
            return None

        wall_bb = wall.get_BoundingBox(None)
        if wall_bb:
            if pt.Z < wall_bb.Min.Z - 0.5 or pt.Z > wall_bb.Max.Z + 0.5:
                return None

        return pt
    except:
        return None


# =====================================================================
# CORE LOGIC - Find Intersections
# =====================================================================
def find_mep_wall_intersections(link_instances, selected_categories,
                                 clearance_mm, min_size_mm, merge_distance_mm,
                                 scope_view_id=None, progress_callback=None):
    """
    scope_view_id: if not None, only collect walls visible in that view.
                   if None, collect all walls in project.
    """
    results = []
    clearance_ft = clearance_mm * MM_TO_FEET
    min_size_ft = min_size_mm * MM_TO_FEET
    merge_dist_ft = merge_distance_mm * MM_TO_FEET

    existing_openings = find_existing_dqt_openings()
    matched_keys = set()

    # Collect walls based on scope
    if scope_view_id:
        walls = FilteredElementCollector(doc, scope_view_id)\
            .OfCategory(BuiltInCategory.OST_Walls)\
            .WhereElementIsNotElementType()\
            .ToElements()
    else:
        walls = FilteredElementCollector(doc)\
            .OfCategory(BuiltInCategory.OST_Walls)\
            .WhereElementIsNotElementType()\
            .ToElements()
    walls = [w for w in walls if w.Location and hasattr(w.Location, 'Curve')]

    total_links = len(link_instances)

    for li_idx, link_inst in enumerate(link_instances):
        try:
            link_doc = link_inst.GetLinkDocument()
            if link_doc is None:
                continue
            link_transform = link_inst.GetTotalTransform()
            link_name = ""
            try:
                link_type = doc.GetElement(link_inst.GetTypeId())
                link_name = link_type.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME).AsString()
            except:
                link_name = str(_eid_int(link_inst.Id))

            for bic in selected_categories:
                try:
                    mep_elements = FilteredElementCollector(link_doc)\
                        .OfCategory(bic)\
                        .WhereElementIsNotElementType()\
                        .ToElements()
                except:
                    continue

                for mep_el in mep_elements:
                    try:
                        mep_bb = mep_el.get_BoundingBox(None)
                        if mep_bb is None:
                            continue

                        mep_min = link_transform.OfPoint(mep_bb.Min)
                        mep_max = link_transform.OfPoint(mep_bb.Max)
                        actual_min = XYZ(min(mep_min.X, mep_max.X), min(mep_min.Y, mep_max.Y), min(mep_min.Z, mep_max.Z))
                        actual_max = XYZ(max(mep_min.X, mep_max.X), max(mep_min.Y, mep_max.Y), max(mep_min.Z, mep_max.Z))

                        diameter, width, height = get_mep_diameter_or_size(mep_el)

                        if diameter > 0:
                            op_w = diameter * MM_TO_FEET + 2 * clearance_ft
                            op_h = diameter * MM_TO_FEET + 2 * clearance_ft
                            size_str = str(int(round(diameter))) + "mm dia"
                        elif width > 0 and height > 0:
                            op_w = width * MM_TO_FEET + 2 * clearance_ft
                            op_h = height * MM_TO_FEET + 2 * clearance_ft
                            size_str = str(int(round(width))) + "x" + str(int(round(height))) + "mm"
                        else:
                            est_w = (actual_max.X - actual_min.X + actual_max.Y - actual_min.Y) / 2.0
                            est_h = actual_max.Z - actual_min.Z
                            if est_w < min_size_ft and est_h < min_size_ft:
                                continue
                            op_w = est_w + 2 * clearance_ft
                            op_h = est_h + 2 * clearance_ft
                            size_str = str(int(round(est_w * FEET_TO_MM))) + "x" + str(int(round(est_h * FEET_TO_MM))) + "mm (est)"

                        if op_w < min_size_ft or op_h < min_size_ft:
                            continue

                        mep_curve = get_mep_location_curve(mep_el)
                        mep_line_start = None
                        mep_line_end = None
                        if mep_curve:
                            mep_line_start = link_transform.OfPoint(mep_curve.GetEndPoint(0))
                            mep_line_end = link_transform.OfPoint(mep_curve.GetEndPoint(1))

                        for wall in walls:
                            try:
                                wall_bb = wall.get_BoundingBox(None)
                                if wall_bb is None:
                                    continue

                                # STEP 0: Skip walls with very small height (soffit/beam wraps)
                                # These are typically horizontal elements, not suitable for MEP openings
                                wall_height = wall_bb.Max.Z - wall_bb.Min.Z
                                if wall_height < 0.5:  # < ~150mm height = likely soffit/beam
                                    continue

                                # STEP 1: Quick bbox pre-filter (tight tolerance)
                                tol = 0.3
                                if (actual_max.X < wall_bb.Min.X - tol or actual_min.X > wall_bb.Max.X + tol or
                                    actual_max.Y < wall_bb.Min.Y - tol or actual_min.Y > wall_bb.Max.Y + tol or
                                    actual_max.Z < wall_bb.Min.Z - tol or actual_min.Z > wall_bb.Max.Z + tol):
                                    continue

                                wc = wall.Location.Curve
                                ws = wc.GetEndPoint(0)
                                we = wc.GetEndPoint(1)
                                wd = (we - ws).Normalize()
                                wn = XYZ(-wd.Y, wd.X, 0).Normalize()

                                # Get wall half-thickness
                                wall_thickness = 0.5
                                wwp = wall.get_Parameter(BuiltInParameter.WALL_ATTR_WIDTH_PARAM)
                                if wwp and wwp.HasValue:
                                    wall_thickness = wwp.AsDouble()
                                wall_half_t = wall_thickness / 2.0

                                int_pt = None
                                passes_through = False

                                # STEP 2: For linear MEP
                                if mep_line_start and mep_line_end:
                                    mep_dir = (mep_line_end - mep_line_start).Normalize()
                                    cross_angle = abs(mep_dir.DotProduct(wn))

                                    dist_start = (mep_line_start - ws).DotProduct(wn)
                                    dist_end = (mep_line_end - ws).DotProduct(wn)

                                    # Must cross at >25 degrees AND endpoints on opposite sides
                                    angle_ok = cross_angle > 0.42
                                    opposite_sides = (dist_start * dist_end) < 0
                                    extends_beyond = (abs(dist_start) > wall_half_t * 0.8 and
                                                      abs(dist_end) > wall_half_t * 0.8)

                                    if angle_ok and opposite_sides and extends_beyond:
                                        int_pt = line_wall_intersection(mep_line_start, mep_line_end, wall)
                                        if int_pt:
                                            # CRITICAL: Verify the MEP physically passes near this point
                                            # Find closest point on MEP line to the intersection point
                                            mep_vec = mep_line_end - mep_line_start
                                            mep_len = mep_vec.GetLength()
                                            if mep_len > 0.001:
                                                t_param = (int_pt - mep_line_start).DotProduct(mep_vec) / (mep_len * mep_len)
                                                t_param = max(0.0, min(1.0, t_param))
                                                closest_on_mep = mep_line_start + mep_vec.Multiply(t_param)
                                                # Distance from closest point on MEP to intersection
                                                verify_dist = closest_on_mep.DistanceTo(int_pt)
                                                # Must be very close (within MEP radius + small tolerance)
                                                mep_radius = max(op_w, op_h) / 2.0
                                                if verify_dist < mep_radius + wall_half_t + 0.1:
                                                    passes_through = True
                                                else:
                                                    int_pt = None  # MEP line is far from wall at this point

                                # STEP 3: No fallback for fittings
                                # Fittings without location curve are unreliable for intersection detection.
                                # If a fitting truly passes through a wall, the connected pipe/duct
                                # will be detected in STEP 2 instead.

                                # Skip if no valid intersection found
                                if int_pt is None or not passes_through:
                                    continue

                                r = IntersectionResult()
                                r.wall_id = wall.Id
                                try:
                                    wtype = doc.GetElement(wall.GetTypeId())
                                    r.wall_name = wtype.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME).AsString()
                                except:
                                    r.wall_name = "Wall #" + str(_eid_int(wall.Id))
                                try:
                                    lvl = doc.GetElement(wall.LevelId)
                                    r.wall_level = lvl.Name if lvl else ""
                                except:
                                    r.wall_level = ""
                                r.mep_id = mep_el.Id
                                try:
                                    r.mep_name = mep_el.Name or ""
                                except:
                                    r.mep_name = ""
                                r.mep_category = MEP_CATEGORY_NAMES.get(bic, str(bic))
                                r.mep_size = size_str
                                r.link_name = link_name
                                r.link_instance = link_inst
                                r.intersection_point = int_pt
                                r.opening_width = op_w
                                r.opening_height = op_h
                                r.is_selected = True

                                key = r.build_tracking_key()
                                if key in existing_openings:
                                    matched_keys.add(key)
                                    old_op, old_tag = existing_openings[key]
                                    old_parts = old_tag.split("::")
                                    needs_update = False
                                    if len(old_parts) >= 7:
                                        try:
                                            old_w = float(old_parts[4])
                                            old_h = float(old_parts[5])
                                            oc = old_parts[6].split(",")
                                            old_pt = XYZ(float(oc[0]), float(oc[1]), float(oc[2]))
                                            if (abs(op_w - old_w) > 0.005 or abs(op_h - old_h) > 0.005 or int_pt.DistanceTo(old_pt) > 0.01):
                                                needs_update = True
                                        except:
                                            needs_update = True
                                    else:
                                        needs_update = True
                                    if needs_update:
                                        r.status = "Update"
                                        r.existing_opening_id = old_op.Id
                                    else:
                                        r.status = "Up-to-date"
                                        r.existing_opening_id = old_op.Id
                                        r.is_selected = False
                                else:
                                    r.status = "New"

                                results.append(r)
                            except Exception:
                                continue
                    except Exception:
                        continue

            if progress_callback:
                pct = int((li_idx + 1) * 100.0 / total_links)
                progress_callback(pct, "Scanning: " + link_name)
        except Exception:
            continue

    if merge_dist_ft > 0:
        results = merge_nearby_openings(results, merge_dist_ft)

    orphan_results = []
    for key, (op_el, tag) in existing_openings.items():
        if key not in matched_keys:
            r = IntersectionResult()
            r.existing_opening_id = op_el.Id
            r.status = "Orphan"
            r.is_selected = True
            r.wall_name = "---"
            r.mep_category = "---"
            r.mep_size = "---"
            parts = tag.split("::")
            r.link_name = parts[1] if len(parts) > 1 else "?"
            r.tracking_key = key
            try:
                bb = op_el.get_BoundingBox(None)
                if bb:
                    r.opening_width = bb.Max.X - bb.Min.X
                    r.opening_height = bb.Max.Z - bb.Min.Z
            except:
                pass
            orphan_results.append(r)

    return results, orphan_results


def merge_nearby_openings(results, merge_dist):
    if not results:
        return results
    merged = []
    used = set()
    for i in range(len(results)):
        if i in used:
            continue
        group = [results[i]]
        used.add(i)
        for j in range(i + 1, len(results)):
            if j in used:
                continue
            if results[i].wall_id != results[j].wall_id:
                continue
            if results[i].intersection_point and results[j].intersection_point:
                if results[i].intersection_point.DistanceTo(results[j].intersection_point) < merge_dist:
                    group.append(results[j])
                    used.add(j)
        if len(group) == 1:
            merged.append(group[0])
        else:
            pts = [r.intersection_point for r in group if r.intersection_point]
            if not pts:
                merged.extend(group)
                continue
            min_z = min(r.intersection_point.Z - r.opening_height / 2.0 for r in group if r.intersection_point)
            max_z = max(r.intersection_point.Z + r.opening_height / 2.0 for r in group if r.intersection_point)
            m = IntersectionResult()
            m.wall_id = group[0].wall_id
            m.wall_name = group[0].wall_name
            m.wall_level = group[0].wall_level
            m.mep_id = group[0].mep_id
            m.mep_name = str(len(group)) + " merged"
            m.mep_category = "Mixed" if len(set(r.mep_category for r in group)) > 1 else group[0].mep_category
            m.mep_size = "Merged"
            m.link_name = group[0].link_name
            m.link_instance = group[0].link_instance
            m.intersection_point = XYZ(sum(p.X for p in pts) / len(pts), sum(p.Y for p in pts) / len(pts), (min_z + max_z) / 2.0)
            m.opening_width = max(r.opening_width for r in group) * 1.2
            m.opening_height = max_z - min_z + max(r.opening_height for r in group) * 0.1
            m.is_selected = True
            m.status = "New"
            m.tracking_key = group[0].tracking_key
            merged.append(m)
    return merged


# =====================================================================
# CORE LOGIC - Execute
# =====================================================================
def execute_openings(results, orphan_results, delete_orphans, progress_callback=None):
    selected_new = [r for r in results if r.is_selected and r.status == "New"]
    selected_update = [r for r in results if r.is_selected and r.status == "Update"]
    selected_orphan = [r for r in orphan_results if r.is_selected] if delete_orphans else []

    total = len(selected_new) + len(selected_update) + len(selected_orphan)
    if total == 0:
        return 0, 0, 0, 0

    created = 0
    updated = 0
    deleted = 0
    errors = 0
    step = 0
    warning_swallower = WarningSwallower()

    tg = TransactionGroup(doc, "DQT - Auto Opening Sync")
    tg.Start()

    # --- DELETE ORPHANS ---
    for r in selected_orphan:
        step += 1
        try:
            t = Transaction(doc, "Delete Orphan Opening")
            opts = t.GetFailureHandlingOptions()
            opts.SetFailuresPreprocessor(warning_swallower)
            t.SetFailureHandlingOptions(opts)
            t.Start()
            try:
                doc.Delete(r.existing_opening_id)
                r.status = "Deleted"
                deleted += 1
                t.Commit()
            except Exception as ex:
                r.status = "Error: " + str(ex)[:60]
                errors += 1
                if t.HasStarted() and not t.HasEnded():
                    t.RollBack()
        except Exception as ex:
            r.status = "Error: " + str(ex)[:60]
            errors += 1
        if progress_callback:
            progress_callback(int(step * 100.0 / total), "Deleting " + str(step))

    # --- UPDATE EXISTING ---
    for r in selected_update:
        step += 1
        try:
            wall = doc.GetElement(r.wall_id)
            if wall is None:
                r.status = "Error: Wall not found"
                errors += 1
                continue

            t = Transaction(doc, "Update Opening")
            opts = t.GetFailureHandlingOptions()
            opts.SetFailuresPreprocessor(warning_swallower)
            t.SetFailureHandlingOptions(opts)
            t.Start()
            try:
                if r.existing_opening_id:
                    doc.Delete(r.existing_opening_id)
                hw = r.opening_width / 2.0
                hh = r.opening_height / 2.0
                opening, err_msg = create_opening_safe(wall, r.intersection_point, hw, hh)
                if opening:
                    write_opening_tag(opening, r.build_tag_string())
                    r.status = "Updated (ID:" + str(_eid_int(opening.Id)) + ")"
                    r.existing_opening_id = opening.Id
                    updated += 1
                    t.Commit()
                else:
                    r.status = "Error: " + (err_msg or "null")
                    errors += 1
                    if t.HasStarted() and not t.HasEnded():
                        t.RollBack()
            except Exception as ex:
                r.status = "Error: " + str(ex)[:60]
                errors += 1
                if t.HasStarted() and not t.HasEnded():
                    t.RollBack()
        except Exception as ex:
            r.status = "Error: " + str(ex)[:60]
            errors += 1
        if progress_callback:
            progress_callback(int(step * 100.0 / total), "Updating " + str(step))

    # --- CREATE NEW ---
    for r in selected_new:
        step += 1
        try:
            wall = doc.GetElement(r.wall_id)
            if wall is None:
                r.status = "Error: Wall not found"
                errors += 1
                continue

            t = Transaction(doc, "Create Opening")
            opts = t.GetFailureHandlingOptions()
            opts.SetFailuresPreprocessor(warning_swallower)
            t.SetFailureHandlingOptions(opts)
            t.Start()
            try:
                hw = r.opening_width / 2.0
                hh = r.opening_height / 2.0
                opening, err_msg = create_opening_safe(wall, r.intersection_point, hw, hh)
                if opening:
                    write_opening_tag(opening, r.build_tag_string())
                    r.status = "Created (ID:" + str(_eid_int(opening.Id)) + ")"
                    r.existing_opening_id = opening.Id
                    created += 1
                    t.Commit()
                else:
                    r.status = "Error: " + (err_msg or "null")
                    errors += 1
                    if t.HasStarted() and not t.HasEnded():
                        t.RollBack()
            except Exception as ex:
                r.status = "Error: " + str(ex)[:60]
                errors += 1
                if t.HasStarted() and not t.HasEnded():
                    t.RollBack()
        except Exception as ex:
            r.status = "Error: " + str(ex)[:60]
            errors += 1
        if progress_callback:
            progress_callback(int(step * 100.0 / total), "Creating " + str(step))

    tg.Assimilate()
    return created, updated, deleted, errors


# =====================================================================
# UI
# =====================================================================
class AutoOpeningWindow(Window):
    def __init__(self):
        self.Title = "DQT - Auto Opening from MEP Link"
        self.Width = 1180
        self.Height = 800
        self.MinWidth = 960
        self.MinHeight = 600
        self.WindowStartupLocation = WindowStartupLocation.CenterScreen
        self.ResizeMode = ResizeMode.CanResize
        self.Background = brush(WHITE)

        self.results = []
        self.orphan_results = []
        self._last_clicked_idx = -1
        self._highlighted_indices = set()  # rows highlighted for zoom (blue)
        self._sort_key = None
        self._sort_reverse = False
        self._build_ui()
        self._load_links()

    def _build_ui(self):
        root = DockPanel()

        # HEADER
        hdr = Border()
        hdr.Background = brush(PRIMARY)
        hdr.Padding = Thickness(20, 14, 20, 14)
        DockPanel.SetDock(hdr, Dock.Top)
        hs = StackPanel()
        hs.Orientation = Orientation.Horizontal
        t = TextBlock()
        t.Text = "Auto Opening from MEP Link"
        t.FontSize = 18
        t.FontWeight = FontWeights.Bold
        t.Foreground = brush(TEXT_DARK)
        hs.Children.Add(t)
        st = TextBlock()
        st.Text = "   |   Create + Update + Delete orphan openings"
        st.FontSize = 12
        st.Foreground = brush(TEXT_GRAY)
        st.VerticalAlignment = VerticalAlignment.Center
        hs.Children.Add(st)
        hdr.Child = hs
        root.Children.Add(hdr)

        # FOOTER
        ftr = Border()
        ftr.Background = brush(LIGHT_GRAY)
        ftr.Padding = Thickness(20, 8, 20, 8)
        ftr.BorderBrush = brush(BORDER_COLOR)
        ftr.BorderThickness = Thickness(0, 1, 0, 0)
        DockPanel.SetDock(ftr, Dock.Bottom)
        fs = StackPanel()
        fs.Orientation = Orientation.Horizontal
        fs.HorizontalAlignment = HorizontalAlignment.Right

        self.status_text = TextBlock()
        self.status_text.Text = "Ready"
        self.status_text.Foreground = brush(TEXT_MUTED)
        self.status_text.VerticalAlignment = VerticalAlignment.Center
        self.status_text.Margin = Thickness(0, 0, 20, 0)
        fs.Children.Add(self.status_text)

        self.cb_delete_orphans = CheckBox()
        self.cb_delete_orphans.Content = "Delete Orphans"
        self.cb_delete_orphans.IsChecked = True
        self.cb_delete_orphans.VerticalAlignment = VerticalAlignment.Center
        self.cb_delete_orphans.Margin = Thickness(0, 0, 16, 0)
        self.cb_delete_orphans.Foreground = brush(TEXT_DARK)
        fs.Children.Add(self.cb_delete_orphans)

        be = Button()
        be.Content = "Execute (Create / Update / Delete)"
        be.Width = 240
        be.Height = 34
        be.FontWeight = FontWeights.Bold
        be.Background = brush(SUCCESS)
        be.Foreground = brush(WHITE)
        be.BorderThickness = Thickness(0)
        be.Margin = Thickness(0, 0, 8, 0)
        be.Cursor = Cursors.Hand
        be.Click += self._on_execute
        fs.Children.Add(be)

        bc = Button()
        bc.Content = "Close"
        bc.Width = 80
        bc.Height = 34
        bc.Click += self._on_close
        fs.Children.Add(bc)

        ftr.Child = fs
        root.Children.Add(ftr)

        # MAIN
        mg = WpfGrid()
        mg.Margin = Thickness(12)
        cl = ColumnDefinition()
        cl.Width = GridLength(285)
        mg.ColumnDefinitions.Add(cl)
        cr = ColumnDefinition()
        cr.Width = GridLength(1, GridUnitType.Star)
        mg.ColumnDefinitions.Add(cr)

        # LEFT PANEL
        ls = ScrollViewer()
        ls.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
        ls.Margin = Thickness(0, 0, 8, 0)
        WpfGrid.SetColumn(ls, 0)
        left = StackPanel()

        # -- Scope --
        self._add_section_header(left, "Scope")
        scope_row = StackPanel()
        scope_row.Orientation = Orientation.Horizontal
        scope_row.Margin = Thickness(0, 2, 0, 8)
        self.rb_project = RadioButton()
        self.rb_project.Content = "Entire Project"
        self.rb_project.IsChecked = True
        self.rb_project.Foreground = brush(TEXT_DARK)
        self.rb_project.Margin = Thickness(0, 0, 16, 0)
        self.rb_project.GroupName = "scope"
        scope_row.Children.Add(self.rb_project)
        self.rb_view = RadioButton()
        self.rb_view.Content = "Active View"
        self.rb_view.Foreground = brush(TEXT_DARK)
        self.rb_view.GroupName = "scope"
        scope_row.Children.Add(self.rb_view)
        left.Children.Add(scope_row)

        # -- Links --
        self._add_section_header(left, "Revit Links (MEP)")
        lbr = StackPanel()
        lbr.Orientation = Orientation.Horizontal
        lbr.Margin = Thickness(0, 2, 0, 2)
        for txt, hdl in [("All", self._on_link_all), ("None", self._on_link_none)]:
            b = Button()
            b.Content = txt
            b.Width = 50
            b.Height = 22
            b.FontSize = 10
            b.Margin = Thickness(0, 0, 4, 0)
            b.Click += hdl
            lbr.Children.Add(b)
        left.Children.Add(lbr)

        lscr = ScrollViewer()
        lscr.MaxHeight = 90
        lscr.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
        lscr.Margin = Thickness(0, 2, 0, 8)
        lbdr = Border()
        lbdr.BorderBrush = brush(BORDER_COLOR)
        lbdr.BorderThickness = Thickness(1)
        lbdr.CornerRadius = CornerRadius(4)
        lbdr.Padding = Thickness(6, 4, 6, 4)
        self.link_cb_panel = StackPanel()
        lbdr.Child = self.link_cb_panel
        lscr.Content = lbdr
        left.Children.Add(lscr)
        self.link_checkboxes = []

        # -- Categories --
        self._add_section_header(left, "MEP Categories")
        self.cat_checkboxes = {}
        cbdr = Border()
        cbdr.BorderBrush = brush(BORDER_COLOR)
        cbdr.BorderThickness = Thickness(1)
        cbdr.CornerRadius = CornerRadius(4)
        cbdr.Padding = Thickness(8, 4, 8, 4)
        cbdr.Margin = Thickness(0, 4, 0, 8)
        cstk = StackPanel()
        for name, bic, chk in [
            ("Pipes", BuiltInCategory.OST_PipeCurves, True),
            ("Ducts", BuiltInCategory.OST_DuctCurves, True),
            ("Cable Trays", BuiltInCategory.OST_CableTray, True),
            ("Conduits", BuiltInCategory.OST_Conduit, True),
            ("Flex Ducts", BuiltInCategory.OST_FlexDuctCurves, False),
            ("Flex Pipes", BuiltInCategory.OST_FlexPipeCurves, False),
            ("Pipe Fittings *", BuiltInCategory.OST_PipeFitting, False),
            ("Duct Fittings *", BuiltInCategory.OST_DuctFitting, False),
            ("Cable Tray Fittings *", BuiltInCategory.OST_CableTrayFitting, False),
            ("Conduit Fittings *", BuiltInCategory.OST_ConduitFitting, False),
        ]:
            cb = CheckBox()
            cb.Content = name
            cb.Tag = bic
            cb.IsChecked = chk
            cb.Margin = Thickness(0, 2, 0, 2)
            cb.Foreground = brush(TEXT_DARK)
            cstk.Children.Add(cb)
            self.cat_checkboxes[bic] = cb

        # Note about fittings
        fit_note = TextBlock()
        fit_note.Text = "* Fittings: detected via connected pipes/ducts"
        fit_note.FontSize = 9
        fit_note.FontStyle = FontStyles.Italic
        fit_note.Foreground = brush(TEXT_MUTED)
        fit_note.Margin = Thickness(0, 4, 0, 0)
        fit_note.TextWrapping = TextWrapping.Wrap
        cstk.Children.Add(fit_note)

        cbdr.Child = cstk
        left.Children.Add(cbdr)

        # -- Settings --
        self._add_section_header(left, "Opening Settings")
        sbdr = Border()
        sbdr.BorderBrush = brush(BORDER_COLOR)
        sbdr.BorderThickness = Thickness(1)
        sbdr.CornerRadius = CornerRadius(4)
        sbdr.Padding = Thickness(8)
        sbdr.Margin = Thickness(0, 4, 0, 8)
        sstk = StackPanel()
        self._add_setting_row(sstk, "Clearance (mm):", "50")
        self.txt_clearance = sstk.Children[sstk.Children.Count - 1].Children[1]
        self._add_setting_row(sstk, "Min Size (mm):", "25")
        self.txt_min_size = sstk.Children[sstk.Children.Count - 1].Children[1]
        self._add_setting_row(sstk, "Merge Dist (mm):", "100")
        self.txt_merge_dist = sstk.Children[sstk.Children.Count - 1].Children[1]
        sbdr.Child = sstk
        left.Children.Add(sbdr)

        # Scan button
        bscan = Button()
        bscan.Content = "Scan Intersections"
        bscan.Height = 36
        bscan.FontWeight = FontWeights.Bold
        bscan.Background = brush(ACCENT)
        bscan.Foreground = brush(WHITE)
        bscan.BorderThickness = Thickness(0)
        bscan.Cursor = Cursors.Hand
        bscan.Margin = Thickness(0, 4, 0, 8)
        bscan.Click += self._on_scan
        left.Children.Add(bscan)

        self.progress_bar = ProgressBar()
        self.progress_bar.Height = 6
        self.progress_bar.Margin = Thickness(0, 0, 0, 4)
        self.progress_bar.Visibility = Visibility.Collapsed
        left.Children.Add(self.progress_bar)
        self.progress_text = TextBlock()
        self.progress_text.FontSize = 10
        self.progress_text.Foreground = brush(TEXT_MUTED)
        self.progress_text.Visibility = Visibility.Collapsed
        left.Children.Add(self.progress_text)

        self.summary_border = Border()
        self.summary_border.Background = brush(SECONDARY)
        self.summary_border.CornerRadius = CornerRadius(6)
        self.summary_border.Padding = Thickness(12)
        self.summary_border.Margin = Thickness(0, 4, 0, 0)
        self.summary_border.Visibility = Visibility.Collapsed
        self.summary_stack = StackPanel()
        self.summary_border.Child = self.summary_stack
        left.Children.Add(self.summary_border)

        ls.Content = left
        mg.Children.Add(ls)

        # RIGHT PANEL
        rbdr = Border()
        rbdr.BorderBrush = brush(BORDER_COLOR)
        rbdr.BorderThickness = Thickness(1)
        rbdr.CornerRadius = CornerRadius(4)
        WpfGrid.SetColumn(rbdr, 1)
        rstk = StackPanel()

        # Toolbar
        tb = StackPanel()
        tb.Orientation = Orientation.Horizontal
        tb.Margin = Thickness(8, 6, 8, 6)
        for lbl, hdl in [("Select All", self._on_select_all), ("Select None", self._on_select_none),
                          ("Highlight", self._on_highlight), ("Zoom To", self._on_zoom)]:
            b = Button()
            b.Content = lbl
            b.Width = 80
            b.Height = 26
            b.Margin = Thickness(0, 0, 4, 0)
            b.Click += hdl
            tb.Children.Add(b)

        for color, label in [(SUCCESS, "New"), (INFO, "Update"), (WARNING, "Orphan"), (TEXT_MUTED, "OK")]:
            dp = StackPanel()
            dp.Orientation = Orientation.Horizontal
            dp.Margin = Thickness(5, 0, 0, 0)
            dp.VerticalAlignment = VerticalAlignment.Center
            d = Border()
            d.Width = 10
            d.Height = 10
            d.CornerRadius = CornerRadius(5)
            d.Background = brush(color)
            d.Margin = Thickness(0, 0, 2, 0)
            dp.Children.Add(d)
            lt = TextBlock()
            lt.Text = label
            lt.FontSize = 10
            lt.Foreground = brush(TEXT_GRAY)
            lt.VerticalAlignment = VerticalAlignment.Center
            dp.Children.Add(lt)
            tb.Children.Add(dp)

        self.lbl_count = TextBlock()
        self.lbl_count.Text = "No results"
        self.lbl_count.VerticalAlignment = VerticalAlignment.Center
        self.lbl_count.Foreground = brush(TEXT_MUTED)
        self.lbl_count.Margin = Thickness(8, 0, 0, 0)
        tb.Children.Add(self.lbl_count)
        rstk.Children.Add(tb)

        # Sortable Header
        self.header_panel = StackPanel()
        rstk.Children.Add(self.header_panel)

        # Results
        self.results_scroll = ScrollViewer()
        self.results_scroll.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
        self.results_scroll.MaxHeight = 530
        self.results_panel = StackPanel()
        self.results_scroll.Content = self.results_panel
        rstk.Children.Add(self.results_scroll)

        rbdr.Child = rstk
        mg.Children.Add(rbdr)
        root.Children.Add(mg)
        self.Content = root

    # ---- Helpers ----
    def _add_section_header(self, parent, text):
        tb = TextBlock()
        tb.Text = text
        tb.FontSize = 12
        tb.FontWeight = FontWeights.Bold
        tb.Foreground = brush(TEXT_DARK)
        tb.Margin = Thickness(0, 8, 0, 2)
        parent.Children.Add(tb)

    def _add_setting_row(self, parent, label, default_val):
        row = StackPanel()
        row.Orientation = Orientation.Horizontal
        row.Margin = Thickness(0, 4, 0, 4)
        lbl = TextBlock()
        lbl.Text = label
        lbl.Width = 140
        lbl.VerticalAlignment = VerticalAlignment.Center
        lbl.Foreground = brush(TEXT_DARK)
        row.Children.Add(lbl)
        txt = TextBox()
        txt.Text = default_val
        txt.Width = 80
        txt.Height = 24
        txt.VerticalContentAlignment = VerticalAlignment.Center
        row.Children.Add(txt)
        parent.Children.Add(row)

    # ---- Links ----
    def _load_links(self):
        self.link_data = []
        links = FilteredElementCollector(doc).OfClass(RevitLinkInstance).ToElements()
        for lnk in links:
            try:
                ld = lnk.GetLinkDocument()
                if ld is None:
                    continue
                lt = doc.GetElement(lnk.GetTypeId())
                name = ""
                try:
                    name = lt.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME).AsString()
                except:
                    name = "Link #" + str(_eid_int(lnk.Id))
                self.link_data.append((name, lnk))
                cb = CheckBox()
                cb.Content = name
                cb.IsChecked = True
                cb.Margin = Thickness(0, 2, 0, 2)
                cb.Foreground = brush(TEXT_DARK)
                cb.FontSize = 11
                self.link_cb_panel.Children.Add(cb)
                self.link_checkboxes.append((cb, lnk))
            except:
                continue
        if not self.link_data:
            self.status_text.Text = "No loaded Revit links found"
            self.status_text.Foreground = brush(WARNING)

    def _on_link_all(self, s, e):
        for cb, _ in self.link_checkboxes:
            cb.IsChecked = True

    def _on_link_none(self, s, e):
        for cb, _ in self.link_checkboxes:
            cb.IsChecked = False

    def _get_selected_links(self):
        return [lnk for cb, lnk in self.link_checkboxes if cb.IsChecked]

    def _get_selected_categories(self):
        return [bic for bic, cb in self.cat_checkboxes.items() if cb.IsChecked]

    def _get_float(self, textbox, default=50):
        try:
            return float(textbox.Text)
        except:
            return default

    def _update_progress(self, pct, msg):
        self.progress_bar.Value = pct
        self.progress_text.Text = msg

    def _force_ui(self):
        import System.Windows.Threading as thr
        self.Dispatcher.Invoke(thr.DispatcherPriority.Render, System.Action(lambda: None))

    # ---- Scan ----
    def _on_scan(self, s, e):
        links = self._get_selected_links()
        if not links:
            TaskDialog.Show("Auto Opening", "Select at least one Revit link.")
            return
        cats = self._get_selected_categories()
        if not cats:
            TaskDialog.Show("Auto Opening", "Select at least one MEP category.")
            return

        # Determine scope
        scope_vid = None
        if self.rb_view.IsChecked:
            scope_vid = doc.ActiveView.Id

        self.progress_bar.Visibility = Visibility.Visible
        self.progress_text.Visibility = Visibility.Visible
        self.progress_bar.Value = 0
        self.status_text.Text = "Scanning..."
        self.status_text.Foreground = brush(INFO)
        self._force_ui()

        self.results, self.orphan_results = find_mep_wall_intersections(
            links, cats,
            self._get_float(self.txt_clearance, 50),
            self._get_float(self.txt_min_size, 25),
            self._get_float(self.txt_merge_dist, 100),
            scope_view_id=scope_vid,
            progress_callback=self._update_progress
        )

        self.progress_bar.Visibility = Visibility.Collapsed
        self.progress_text.Visibility = Visibility.Collapsed
        self._sort_key = None
        self._sort_reverse = False
        self._refresh_table()
        self._update_summary()

        nc = sum(1 for r in self.results if r.status == "New")
        uc = sum(1 for r in self.results if r.status == "Update")
        oc_ = sum(1 for r in self.results if r.status == "Up-to-date")
        orc = len(self.orphan_results)
        scope_label = "Active View" if self.rb_view.IsChecked else "Project"
        parts = []
        if nc: parts.append(str(nc) + " new")
        if uc: parts.append(str(uc) + " update")
        if oc_: parts.append(str(oc_) + " ok")
        if orc: parts.append(str(orc) + " orphan")
        self.status_text.Text = "[" + scope_label + "] " + (", ".join(parts) if parts else "No intersections")
        self.status_text.Foreground = brush(SUCCESS)

    # ---- Sorting ----
    def _on_sort_click(self, sender, args):
        """Sort results by column when header is clicked"""
        col_key = sender.Tag
        if col_key is None:
            return
        # Toggle direction if same column
        if self._sort_key == col_key:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_key = col_key
            self._sort_reverse = False
        self._apply_sort()
        self._refresh_table()

    def _apply_sort(self):
        if not self._sort_key:
            return
        # Find column def
        sort_attr = None
        for cdef in COLUMNS:
            if cdef[0] == self._sort_key:
                sort_attr = cdef[3]
                break
        if not sort_attr:
            return

        def get_val(r):
            try:
                v = getattr(r, sort_attr, "")
                if isinstance(v, (int, float)):
                    return v
                return str(v).lower()
            except:
                return ""

        self.results.sort(key=get_val, reverse=self._sort_reverse)
        self.orphan_results.sort(key=get_val, reverse=self._sort_reverse)

    # ---- Table ----
    def _refresh_table(self):
        self.header_panel.Children.Clear()
        self.results_panel.Children.Clear()

        # Build sortable header
        hdr_border = Border()
        hdr_border.Background = brush(PRIMARY)
        hdr_border.Padding = Thickness(0, 6, 0, 6)
        hdr_grid = WpfGrid()
        for cdef in COLUMNS:
            cd = ColumnDefinition()
            cd.Width = GridLength(cdef[2])
            hdr_grid.ColumnDefinitions.Add(cd)

        for ci, cdef in enumerate(COLUMNS):
            col_key, col_text, col_w, col_sort = cdef
            if ci == 0:
                # Empty checkbox column header
                tb = TextBlock()
                tb.Text = ""
                WpfGrid.SetColumn(tb, ci)
                hdr_grid.Children.Add(tb)
                continue

            # Sortable header button-like text
            hdr_btn = Border()
            hdr_btn.Cursor = Cursors.Hand if col_sort else Cursors.Arrow
            hdr_btn.Padding = Thickness(4, 0, 4, 0)
            hdr_btn.Background = brush(PRIMARY)

            arrow = ""
            if col_sort and self._sort_key == col_key:
                arrow = " v" if self._sort_reverse else " ^"

            htb = TextBlock()
            htb.Text = col_text + arrow
            htb.FontWeight = FontWeights.Bold
            htb.FontSize = 11
            htb.Foreground = brush(TEXT_DARK)
            htb.VerticalAlignment = VerticalAlignment.Center
            hdr_btn.Child = htb

            if col_sort:
                hdr_btn.Tag = col_key
                hdr_btn.MouseLeftButtonDown += self._on_sort_click

            WpfGrid.SetColumn(hdr_btn, ci)
            hdr_grid.Children.Add(hdr_btn)

        hdr_border.Child = hdr_grid
        self.header_panel.Children.Add(hdr_border)

        # Data rows
        idx = 0
        for r in self.results:
            self.results_panel.Children.Add(self._build_row(idx, r, False))
            idx += 1

        if self.orphan_results:
            sep = Border()
            sep.Background = brush(WARNING)
            sep.Height = 2
            sep.Margin = Thickness(0, 4, 0, 4)
            self.results_panel.Children.Add(sep)
            ol = TextBlock()
            ol.Text = "  Orphans (MEP removed/moved away):"
            ol.FontWeight = FontWeights.Bold
            ol.FontSize = 11
            ol.Foreground = brush(WARNING)
            ol.Margin = Thickness(0, 2, 0, 4)
            self.results_panel.Children.Add(ol)
            for r in self.orphan_results:
                self.results_panel.Children.Add(self._build_row(idx, r, True))
                idx += 1

        all_items = self.results + self.orphan_results
        sel = sum(1 for r in all_items if r.is_selected)
        self.lbl_count.Text = str(sel) + " / " + str(len(all_items)) + " selected"

    def _build_row(self, idx, r, is_orphan):
        s = r.status
        # Background: highlighted row gets distinct color
        is_highlighted = (idx in self._highlighted_indices)
        if is_highlighted:
            bg = "#BBDEFB"  # bright blue highlight
        elif "Created" in s or "Updated" in s:
            bg = HIGHLIGHT
        elif "Deleted" in s:
            bg = LIGHT_GRAY
        elif "Error" in s:
            bg = "#FFEBEE"
        elif s == "Update":
            bg = UPDATE_BG
        elif s == "Orphan":
            bg = ORPHAN_BG
        elif s == "Up-to-date":
            bg = LIGHT_GRAY
        else:
            bg = WHITE if idx % 2 == 0 else LIGHT_GRAY

        border = Border()
        border.Background = brush(bg)
        border.Padding = Thickness(0, 4, 0, 4)
        border.BorderBrush = brush("#90CAF9" if is_highlighted else BORDER_COLOR)
        border.BorderThickness = Thickness(0, 0, 0, 2 if is_highlighted else 1)
        border.Tag = (idx, is_orphan)
        border.Cursor = Cursors.Hand
        # Click row = highlight only (NOT toggle checkbox)
        border.MouseLeftButtonDown += self._on_row_click

        grid = WpfGrid()
        for cdef in COLUMNS:
            cd = ColumnDefinition()
            cd.Width = GridLength(cdef[2])
            grid.ColumnDefinitions.Add(cd)

        # Col 0: CheckBox - independent from row click
        cb = CheckBox()
        cb.IsChecked = r.is_selected
        cb.Tag = (idx, is_orphan)
        cb.Margin = Thickness(8, 0, 0, 0)
        cb.Checked += self._on_cb_changed
        cb.Unchecked += self._on_cb_changed
        WpfGrid.SetColumn(cb, 0)
        grid.Children.Add(cb)

        # Col 1: Status
        stb = TextBlock()
        stb.Text = s[:12]
        stb.FontSize = 10
        stb.FontWeight = FontWeights.Bold
        stb.VerticalAlignment = VerticalAlignment.Center
        stb.Margin = Thickness(4, 0, 0, 0)
        cmap = {"New": SUCCESS, "Update": INFO, "Orphan": WARNING, "Up-to-date": TEXT_MUTED}
        stb.Foreground = brush(cmap.get(s, ERROR if "Error" in s else SUCCESS if "Created" in s or "Updated" in s else TEXT_MUTED))
        stb.IsHitTestVisible = False
        WpfGrid.SetColumn(stb, 1)
        grid.Children.Add(stb)

        # Cols 2-9
        w_mm = str(int(round(r.opening_width * FEET_TO_MM))) if r.opening_width > 0 else "---"
        h_mm = str(int(round(r.opening_height * FEET_TO_MM))) if r.opening_height > 0 else "---"
        texts = [r.wall_name, r.wall_level, r.mep_category, r.mep_size, r.link_name, w_mm, h_mm,
                 s if ("ID:" in s or "Error" in s or "Deleted" in s) else ""]
        for i, t in enumerate(texts):
            tb = TextBlock()
            tb.Text = t[:22] if len(t) > 22 else t
            tb.FontSize = 11
            tb.Foreground = brush(ERROR if "Error" in t else SUCCESS if "Created" in t or "Updated" in t else TEXT_DARK)
            tb.VerticalAlignment = VerticalAlignment.Center
            tb.TextWrapping = TextWrapping.NoWrap
            tb.Margin = Thickness(4, 0, 0, 0)
            tb.IsHitTestVisible = False
            WpfGrid.SetColumn(tb, i + 2)
            grid.Children.Add(tb)

        border.Child = grid
        return border

    # ---- Row interaction ----
    def _on_cb_changed(self, sender, args):
        """Checkbox toggle - also handles Shift+click for range select"""
        tag = sender.Tag
        if tag is None:
            return
        idx, is_orphan = tag
        checked = bool(sender.IsChecked)

        # Shift+click on checkbox = range select
        shift = (Keyboard.Modifiers & ModifierKeys.Shift) == ModifierKeys.Shift
        if shift and self._last_clicked_idx >= 0 and self._last_clicked_idx != idx:
            all_items = self.results + self.orphan_results
            start = min(self._last_clicked_idx, idx)
            end = max(self._last_clicked_idx, idx)
            for i in range(start, end + 1):
                if 0 <= i < len(all_items):
                    all_items[i].is_selected = checked
            self._last_clicked_idx = idx
            self._refresh_table()
            return

        self._set_item_selected(idx, is_orphan, checked)
        self._last_clicked_idx = idx
        self._update_count_label()

    def _on_row_click(self, sender, args):
        """Click row = highlight for Zoom/Highlight. Shift=range, Ctrl=add/remove."""
        tag = sender.Tag
        if tag is None:
            return
        idx, is_orphan = tag
        all_items = self.results + self.orphan_results

        shift = (Keyboard.Modifiers & ModifierKeys.Shift) == ModifierKeys.Shift
        ctrl = (Keyboard.Modifiers & ModifierKeys.Control) == ModifierKeys.Control

        if shift and self._last_clicked_idx >= 0 and self._last_clicked_idx != idx:
            # Shift+Click: range highlight from last to current
            start = min(self._last_clicked_idx, idx)
            end = max(self._last_clicked_idx, idx)
            for i in range(start, end + 1):
                self._highlighted_indices.add(i)
        elif ctrl:
            # Ctrl+Click: toggle single row in/out of highlight set
            if idx in self._highlighted_indices:
                self._highlighted_indices.discard(idx)
            else:
                self._highlighted_indices.add(idx)
        else:
            # Normal click: highlight only this row
            self._highlighted_indices = set([idx])

        self._last_clicked_idx = idx
        self._refresh_table()

        # Select highlighted walls in Revit
        id_list = List[ElementId]()
        for hi in self._highlighted_indices:
            if 0 <= hi < len(all_items):
                r = all_items[hi]
                if r.wall_id and r.wall_id not in [id_list[j] for j in range(id_list.Count)]:
                    id_list.Add(r.wall_id)
        if id_list.Count > 0:
            try:
                uidoc.Selection.SetElementIds(id_list)
            except:
                pass

        # Status bar info
        count = len(self._highlighted_indices)
        if count == 1:
            hi = list(self._highlighted_indices)[0]
            if 0 <= hi < len(all_items):
                r = all_items[hi]
                self.status_text.Text = r.wall_name + " | " + r.mep_category + " " + r.mep_size
        elif count > 1:
            self.status_text.Text = str(count) + " rows highlighted"

    def _set_item_selected(self, idx, is_orphan, checked):
        if is_orphan:
            oi = idx - len(self.results)
            if 0 <= oi < len(self.orphan_results):
                self.orphan_results[oi].is_selected = checked
        else:
            if 0 <= idx < len(self.results):
                self.results[idx].is_selected = checked

    def _update_count_label(self):
        all_items = self.results + self.orphan_results
        sel = sum(1 for r in all_items if r.is_selected)
        self.lbl_count.Text = str(sel) + " / " + str(len(all_items)) + " selected"

    # ---- Summary ----
    def _update_summary(self):
        self.summary_stack.Children.Clear()
        self.summary_border.Visibility = Visibility.Visible
        t = TextBlock()
        t.Text = "Summary"
        t.FontWeight = FontWeights.Bold
        t.FontSize = 12
        t.Foreground = brush(TEXT_DARK)
        t.Margin = Thickness(0, 0, 0, 6)
        self.summary_stack.Children.Add(t)
        for label, color in [
            ("New: " + str(sum(1 for r in self.results if r.status == "New")), SUCCESS),
            ("Update: " + str(sum(1 for r in self.results if r.status == "Update")), INFO),
            ("Up-to-date: " + str(sum(1 for r in self.results if r.status == "Up-to-date")), TEXT_MUTED),
            ("Orphans: " + str(len(self.orphan_results)), WARNING),
        ]:
            tb = TextBlock()
            tb.Text = label
            tb.FontSize = 11
            tb.FontWeight = FontWeights.Bold
            tb.Foreground = brush(color)
            tb.Margin = Thickness(0, 1, 0, 1)
            self.summary_stack.Children.Add(tb)

    # ---- Toolbar actions ----
    def _on_select_all(self, s, e):
        for r in self.results + self.orphan_results:
            r.is_selected = True
        self._refresh_table()

    def _on_select_none(self, s, e):
        for r in self.results + self.orphan_results:
            r.is_selected = False
        self._refresh_table()

    def _on_highlight(self, s, e):
        """Select walls in Revit from highlighted rows, fallback to checked."""
        results = self._get_target_results()
        if not results:
            TaskDialog.Show("Auto Opening", "No items highlighted or checked.\nClick rows or check items first.")
            return
        ids = list(set(r.wall_id for r in results if r.wall_id))
        id_list = List[ElementId]()
        for wid in ids:
            id_list.Add(wid)
        uidoc.Selection.SetElementIds(id_list)
        self.status_text.Text = "Selected " + str(len(ids)) + " walls"

    def _on_zoom(self, s, e):
        """Zoom tightly to intersection points + apply section box."""
        target = self._get_target_results()
        if not target:
            TaskDialog.Show("Auto Opening", "No items highlighted or checked.\nClick rows or check items first.")
            return

        # Collect intersection points and wall IDs
        points = [r.intersection_point for r in target if r.intersection_point]
        wall_ids = list(set(r.wall_id for r in target if r.wall_id))

        if not points and not wall_ids:
            TaskDialog.Show("Auto Opening", "No geometry data for selected items.")
            return

        # Build tight bbox around intersection points
        if points:
            mn_x = min(p.X for p in points)
            mn_y = min(p.Y for p in points)
            mn_z = min(p.Z for p in points)
            mx_x = max(p.X for p in points)
            mx_y = max(p.Y for p in points)
            mx_z = max(p.Z for p in points)
            # Tight padding: ~1m around intersection area
            pad = 3.0  # ~900mm
        else:
            # Fallback to wall bbox
            mn_x = mn_y = mn_z = float('inf')
            mx_x = mx_y = mx_z = float('-inf')
            for wid in wall_ids:
                w = doc.GetElement(wid)
                if not w:
                    continue
                bb = w.get_BoundingBox(None)
                if not bb:
                    continue
                if bb.Min.X < mn_x: mn_x = bb.Min.X
                if bb.Min.Y < mn_y: mn_y = bb.Min.Y
                if bb.Min.Z < mn_z: mn_z = bb.Min.Z
                if bb.Max.X > mx_x: mx_x = bb.Max.X
                if bb.Max.Y > mx_y: mx_y = bb.Max.Y
                if bb.Max.Z > mx_z: mx_z = bb.Max.Z
            pad = 2.0

        if mn_x == float('inf'):
            self.status_text.Text = "No geometry found"
            return

        # Select walls in Revit
        id_list = List[ElementId]()
        for wid in wall_ids:
            id_list.Add(wid)
        if id_list.Count > 0:
            uidoc.Selection.SetElementIds(id_list)

        # Apply section box to 3D view (if active view is 3D)
        view = doc.ActiveView
        section_applied = False
        try:
            if hasattr(view, 'IsSectionBoxActive'):
                sbox = BoundingBoxXYZ()
                sbox.Min = XYZ(mn_x - pad, mn_y - pad, mn_z - pad)
                sbox.Max = XYZ(mx_x + pad, mx_y + pad, mx_z + pad)
                t = Transaction(doc, "DQT - Section Box at Opening")
                t.Start()
                try:
                    view.IsSectionBoxActive = True
                    view.SetSectionBox(sbox)
                    t.Commit()
                    section_applied = True
                except:
                    if t.HasStarted() and not t.HasEnded():
                        t.RollBack()
        except:
            pass

        # Zoom to the area
        try:
            uiview = None
            for uv in uidoc.GetOpenUIViews():
                if uv.ViewId == view.Id:
                    uiview = uv
                    break
            if uiview:
                uiview.ZoomAndCenterRectangle(
                    XYZ(mn_x - pad, mn_y - pad, mn_z - pad),
                    XYZ(mx_x + pad, mx_y + pad, mx_z + pad)
                )
        except:
            try:
                if id_list.Count > 0:
                    uidoc.ShowElements(id_list)
            except:
                pass

        n = len(target)
        msg = "Zoomed to " + str(n) + " intersection" + ("s" if n > 1 else "")
        if section_applied:
            msg += " + Section Box"
        self.status_text.Text = msg

    def _get_target_results(self):
        """Get target IntersectionResult items: highlighted rows first, fallback to checked"""
        all_items = self.results + self.orphan_results

        # First: highlighted rows
        if self._highlighted_indices:
            highlighted = []
            for hi in self._highlighted_indices:
                if 0 <= hi < len(all_items):
                    highlighted.append(all_items[hi])
            if highlighted:
                return highlighted

        # Fallback: checked items
        checked = [r for r in self.results if r.is_selected and r.wall_id]
        return checked

    # ---- Execute ----
    def _on_execute(self, s, e):
        nc = sum(1 for r in self.results if r.is_selected and r.status == "New")
        uc = sum(1 for r in self.results if r.is_selected and r.status == "Update")
        do = bool(self.cb_delete_orphans.IsChecked)
        oc = sum(1 for r in self.orphan_results if r.is_selected) if do else 0
        total = nc + uc + oc
        if total == 0:
            TaskDialog.Show("Auto Opening", "Nothing to do. Scan first.")
            return
        msg = ""
        if nc: msg += "Create: " + str(nc) + " new\n"
        if uc: msg += "Update: " + str(uc) + " existing\n"
        if oc: msg += "Delete: " + str(oc) + " orphans\n"
        msg += "\nSupports Undo (Ctrl+Z)."
        td = TaskDialog("Confirm")
        td.MainContent = msg
        td.CommonButtons = TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No
        if td.Show() != TaskDialogResult.Yes:
            return
        self.progress_bar.Visibility = Visibility.Visible
        self.progress_text.Visibility = Visibility.Visible
        self.status_text.Text = "Executing..."
        self._force_ui()
        cr, up, dl, er = execute_openings(self.results, self.orphan_results, do, self._update_progress)
        self.progress_bar.Visibility = Visibility.Collapsed
        self.progress_text.Visibility = Visibility.Collapsed
        self._refresh_table()
        parts = []
        if cr: parts.append(str(cr) + " created")
        if up: parts.append(str(up) + " updated")
        if dl: parts.append(str(dl) + " deleted")
        if er: parts.append(str(er) + " errors")
        msg = ", ".join(parts) if parts else "No changes"
        self.status_text.Text = msg
        self.status_text.Foreground = brush(SUCCESS if er == 0 else WARNING)
        TaskDialog.Show("Auto Opening - Done", msg)

    def _on_close(self, s, e):
        self.Close()


# =====================================================================
# ENTRY POINT
# =====================================================================
if __name__ == '__main__' or True:
    try:
        window = AutoOpeningWindow()
        window.ShowDialog()
    except Exception as ex:
        TaskDialog.Show("Auto Opening - Error", str(ex))