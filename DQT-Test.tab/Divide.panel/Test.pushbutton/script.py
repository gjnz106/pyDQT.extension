# -*- coding: utf-8 -*-
__title__ = 'Split\nWall/Col\nby Level'
__doc__ = 'Split Walls and Columns that span multiple Levels into individual level-by-level elements'

from pyrevit import forms, revit, DB, script
import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
import Autodesk.Revit.UI.Selection as RvtSelection
clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')
from System.Windows.Forms import (
    Form, DataGridView, DataGridViewTextBoxColumn, DataGridViewCheckBoxColumn,
    DataGridViewColumnSortMode, DataGridViewContentAlignment,
    DataGridViewAutoSizeColumnsMode, DataGridViewAutoSizeColumnMode,
    FormBorderStyle, FormStartPosition, DataGridViewSelectionMode,
    DockStyle, AnchorStyles, MessageBox, MessageBoxButtons, MessageBoxIcon,
    SaveFileDialog, DialogResult,
    Application, BorderStyle, ComboBox, ComboBoxStyle, FlatStyle,
    Panel, Label, Button, CheckBox, TextBox, SplitContainer, Orientation,
    Padding, ScrollBars
)
from System.Drawing import Size, Point, Color, Font, FontStyle
import System
import datetime
import traceback

# ═══════════════════════════════════════════════════════════
#  THEME  — matching reference palette
# ═══════════════════════════════════════════════════════════
C_HEADER   = Color.FromArgb(245, 236, 210)
C_ACCENT   = Color.FromArgb(196, 152,  74)
C_OK       = Color.FromArgb( 39, 174,  96)
C_WARN     = Color.FromArgb(230, 160,  20)
C_ERR      = Color.FromArgb(192,  57,  43)
C_BG       = Color.FromArgb(245, 245, 248)
C_SURFACE  = Color.White
C_SURFACE2 = Color.FromArgb(235, 235, 240)
C_TEXT     = Color.FromArgb( 30,  30,  40)
C_SUBTEXT  = Color.FromArgb(110, 110, 130)
C_GRID_HDR = Color.FromArgb( 55,  65,  81)
C_GRID_ALT = Color.FromArgb(248, 249, 252)
C_SEL      = Color.FromArgb(196, 152,  74)
C_ROW_SKIP = Color.FromArgb(255, 243, 205)
C_ROW_ERR  = Color.FromArgb(255, 235, 235)
C_ROW_DONE = Color.FromArgb(220, 240, 255)
C_ROW_LVL  = Color.FromArgb(214, 248, 214)   # checked level row — green tint

FONT_NORM       = Font('Segoe UI', 9)
FONT_BOLD       = Font('Segoe UI', 9,  FontStyle.Bold)
FONT_SMALL      = Font('Segoe UI', 8)
FONT_SMALL_BOLD = Font('Segoe UI', 8,  FontStyle.Bold)
FONT_TITLE      = Font('Segoe UI', 16, FontStyle.Bold)

# ═══════════════════════════════════════════════════════════
#  CONSTANTS
# ═══════════════════════════════════════════════════════════
TOLERANCE = 0.001   # feet

# ═══════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════

def get_name(element):
    try:
        return str(DB.Element.Name.GetValue(element))
    except Exception:
        try:
            return str(element.Name)
        except Exception:
            return 'Unknown'


def feet_to_m(feet):
    return feet * 0.3048


def get_levels(doc):
    collector = DB.FilteredElementCollector(doc).OfClass(DB.Level).ToElements()
    levels = [(lvl.Elevation, lvl) for lvl in collector]
    levels.sort(key=lambda x: x[0])
    return levels


def get_element_base_top(doc, element):
    try:
        if isinstance(element, DB.Wall):
            base_offset = element.get_Parameter(DB.BuiltInParameter.WALL_BASE_OFFSET).AsDouble()
            top_offset  = element.get_Parameter(DB.BuiltInParameter.WALL_TOP_OFFSET).AsDouble()
            base_lvl_id = element.get_Parameter(DB.BuiltInParameter.WALL_BASE_CONSTRAINT).AsElementId()
            top_lvl_id  = element.get_Parameter(DB.BuiltInParameter.WALL_HEIGHT_TYPE).AsElementId()
            base_lvl    = doc.GetElement(base_lvl_id)
            base_elev   = base_lvl.Elevation + base_offset if base_lvl else 0.0
            if top_lvl_id == DB.ElementId.InvalidElementId or top_lvl_id.IntegerValue < 0:
                height   = element.get_Parameter(DB.BuiltInParameter.WALL_USER_HEIGHT_PARAM).AsDouble()
                top_elev = base_elev + height
            else:
                top_lvl  = doc.GetElement(top_lvl_id)
                top_elev = top_lvl.Elevation + top_offset if top_lvl else base_elev
            return base_elev, top_elev
        elif isinstance(element, DB.FamilyInstance):
            base_p = element.get_Parameter(DB.BuiltInParameter.FAMILY_BASE_LEVEL_PARAM)
            top_p  = element.get_Parameter(DB.BuiltInParameter.FAMILY_TOP_LEVEL_PARAM)
            boff_p = element.get_Parameter(DB.BuiltInParameter.FAMILY_BASE_LEVEL_OFFSET_PARAM)
            toff_p = element.get_Parameter(DB.BuiltInParameter.FAMILY_TOP_LEVEL_OFFSET_PARAM)
            if not base_p or not top_p:
                return None
            base_lvl = doc.GetElement(base_p.AsElementId())
            top_lvl  = doc.GetElement(top_p.AsElementId())
            if not base_lvl or not top_lvl:
                return None
            boff = boff_p.AsDouble() if boff_p else 0.0
            toff = toff_p.AsDouble()  if toff_p  else 0.0
            return base_lvl.Elevation + boff, top_lvl.Elevation + toff
    except Exception:
        pass
    return None


def get_intermediate_levels(base_elev, top_elev, sorted_levels):
    return [(e, lvl) for (e, lvl) in sorted_levels
            if base_elev + TOLERANCE < e < top_elev - TOLERANCE]


def get_element_display_name(doc, element):
    try:
        if isinstance(element, DB.Wall):
            wt = element.WallType
            return get_name(wt) if wt else 'Wall'
        elif isinstance(element, DB.FamilyInstance):
            sym = element.Symbol
            fam = sym.Family if sym else None
            if sym and fam:
                return u'{} : {}'.format(get_name(fam), get_name(sym))
            return get_name(element)
    except Exception:
        pass
    return 'Unknown'


def get_element_category(element):
    if isinstance(element, DB.Wall):
        return 'Wall'
    elif isinstance(element, DB.FamilyInstance):
        try:
            cat = element.Category
            if cat:
                return str(cat.Name)
        except Exception:
            pass
        return 'Column'
    return 'Unknown'


def _fmt_level_offset(lvl_name, elev_ft, lvl_elev_ft):
    """Format 'LevelName ±Xmm', omit offset if essentially zero."""
    off_mm = (elev_ft - lvl_elev_ft) * 304.8
    if abs(off_mm) < 0.5:
        return lvl_name
    sign = u'+' if off_mm > 0 else u''
    return u'{} {}{:.0f}mm'.format(lvl_name, sign, off_mm)


def get_base_level_name(base_elev, sorted_levels):
    """Level nearest to base_elev, with signed offset."""
    if not sorted_levels:
        return 'N/A'
    best_elev, best_lvl = min(sorted_levels, key=lambda x: abs(x[0] - base_elev))
    return _fmt_level_offset(get_name(best_lvl), base_elev, best_elev)


def get_top_level_name(top_elev, sorted_levels):
    """Level nearest to top_elev, with signed offset."""
    if not sorted_levels:
        return 'N/A'
    best_elev, best_lvl = min(sorted_levels, key=lambda x: abs(x[0] - top_elev))
    return _fmt_level_offset(get_name(best_lvl), top_elev, best_elev)


def collect_elements(doc):
    elements = []
    for w in (DB.FilteredElementCollector(doc)
              .OfClass(DB.Wall)
              .WhereElementIsNotElementType()
              .ToElements()):
        if w.WallType is not None:
            elements.append(w)
    col_filter = DB.LogicalOrFilter(
        DB.ElementCategoryFilter(DB.BuiltInCategory.OST_StructuralColumns),
        DB.ElementCategoryFilter(DB.BuiltInCategory.OST_Columns))
    for c in (DB.FilteredElementCollector(doc)
              .WherePasses(col_filter)
              .WhereElementIsNotElementType()
              .ToElements()):
        if isinstance(c, DB.FamilyInstance):
            elements.append(c)
    return elements


def analyze_elements(elements, doc, sorted_levels):
    """
    Build item dicts for each element.
    Items have _ready=True only if they span at least one intermediate level.
    """
    results = []
    for el in elements:
        try:
            el_id = el.Id.IntegerValue
            cat   = get_element_category(el)
            name  = get_element_display_name(doc, el)

            elevs = get_element_base_top(doc, el)
            if not elevs:
                results.append({
                    'el': el, 'id': el_id, 'name': name, 'category': cat,
                    'status': 'Skip', 'reason': 'Cannot determine base/top elevation',
                    'base_level': 'N/A', 'top_level': 'N/A',
                    'height_m': 'N/A', 'spans': 0, 'inter': [],
                    'base_elev': 0.0, 'top_elev': 0.0, '_ready': False,
                })
                continue

            base_elev, top_elev = elevs
            inter = get_intermediate_levels(base_elev, top_elev, sorted_levels)

            if not inter:
                results.append({
                    'el': el, 'id': el_id, 'name': name, 'category': cat,
                    'status': 'Skip', 'reason': 'Already within a single level',
                    'base_level': get_base_level_name(base_elev, sorted_levels),
                    'top_level':  get_top_level_name(top_elev,   sorted_levels),
                    'height_m': '{:.3f}'.format(feet_to_m(top_elev - base_elev)),
                    'spans': 0, 'inter': [],
                    'base_elev': base_elev, 'top_elev': top_elev, '_ready': False,
                })
                continue

            results.append({
                'el':         el,
                'id':         el_id,
                'name':       name,
                'category':   cat,
                'status':     'Ready',
                'reason':     '',
                'base_level': get_base_level_name(base_elev, sorted_levels),
                'top_level':  get_top_level_name(top_elev,   sorted_levels),
                'height_m':   '{:.3f}'.format(feet_to_m(top_elev - base_elev)),
                'spans':      len(inter),
                'inter':      inter,           # [(elev_ft, Level), ...]
                'base_elev':  base_elev,
                'top_elev':   top_elev,
                '_ready':     True,
            })

        except Exception as exc:
            results.append({
                'el': el, 'id': el.Id.IntegerValue if el else -1,
                'name': 'Unknown', 'category': 'Unknown',
                'status': 'Error', 'reason': str(exc),
                'base_level': 'N/A', 'top_level': 'N/A',
                'height_m': 'N/A', 'spans': 0, 'inter': [],
                'base_elev': 0.0, 'top_elev': 0.0, '_ready': False,
            })
    return results


# ═══════════════════════════════════════════════════════════
#  SPLIT LOGIC
# ═══════════════════════════════════════════════════════════

def _find_base_lvl(sb, sorted_levels):
    """
    Return the level whose elevation is closest at-or-below sb.
    Falls back to the lowest available level when sb is below all levels
    (handles negative base-offset elements).
    """
    base_lvl = None
    for (e, lvl) in sorted_levels:
        if e <= sb + TOLERANCE:
            base_lvl = lvl
    if base_lvl is None and sorted_levels:
        base_lvl = sorted_levels[0][1]   # lowest level — offset will be negative
    return base_lvl


def _find_top_lvl(st, sorted_levels):
    """
    Return the level whose elevation is closest at-or-above st.
    Falls back to the highest available level when st is above all levels.
    """
    for (e, lvl) in sorted_levels:
        if e >= st - TOLERANCE:
            return lvl
    if sorted_levels:
        return sorted_levels[-1][1]      # highest level — offset will be positive
    return None


def get_wall_hosted_elements(doc, wall):
    """
    Snapshot all FamilyInstances hosted on this wall before splitting.
    Must run BEFORE any wall geometry change.
    """
    hosted = []
    try:
        col = (DB.FilteredElementCollector(doc)
               .OfClass(DB.FamilyInstance)
               .WhereElementIsNotElementType())
        for fi in col:
            try:
                if fi.Host is None or fi.Host.Id != wall.Id:
                    continue
                loc = fi.Location
                if not isinstance(loc, DB.LocationPoint):
                    continue

                params = []
                for p in fi.Parameters:
                    try:
                        st = p.StorageType.ToString()
                        if st == 'None':
                            continue
                        entry = {'st': st, 'ro': p.IsReadOnly}
                        if p.IsShared:
                            entry['guid'] = str(p.GUID)
                        else:
                            try:
                                bip_int = int(p.Definition.BuiltInParameter)
                                if bip_int != -1:
                                    entry['bip'] = bip_int
                            except Exception:
                                pass
                            entry['name'] = p.Definition.Name
                        if st == 'Double':
                            entry['v'] = p.AsDouble()
                        elif st == 'Integer':
                            entry['v'] = p.AsInteger()
                        elif st == 'ElementId':
                            entry['v'] = p.AsElementId().IntegerValue
                        elif st == 'String':
                            val = p.AsString()
                            entry['v'] = val if val is not None else u''
                        else:
                            continue
                        params.append(entry)
                    except Exception:
                        pass

                hosted.append({
                    'elem_id':        fi.Id,
                    'type_id':        fi.GetTypeId(),
                    'point':          loc.Point,
                    'hand_flipped':   fi.HandFlipped,
                    'facing_flipped': fi.FacingFlipped,
                    'level_id':       fi.LevelId,        # THIS is the key for matching
                    'params':         params,
                })
            except Exception:
                pass
    except Exception:
        pass
    return hosted


def _apply_param(new_fi, entry):
    """Set one parameter: GUID → BIP int → name. Silent skip if read-only."""
    try:
        p = None
        if 'guid' in entry:
            try:
                import System
                p = new_fi.get_Parameter(System.Guid(entry['guid']))
            except Exception:
                pass
        if p is None and 'bip' in entry:
            try:
                p = new_fi.get_Parameter(entry['bip'])
            except Exception:
                pass
        if p is None and 'name' in entry:
            p = new_fi.LookupParameter(entry['name'])
        if p is None or p.IsReadOnly:
            return
        st = entry['st']
        v  = entry['v']
        if   st == 'Double':    p.Set(float(v))
        elif st == 'Integer':   p.Set(int(v))
        elif st == 'ElementId': p.Set(DB.ElementId(int(v)))
        elif st == 'String':    p.Set(v if v is not None else u'')
    except Exception:
        pass


def _recreate_hosted(doc, info, target_wall):
    """
    NewFamilyInstance on target_wall, restore all params + flips.
    Returns new ElementId on success, None on failure.
    Cleans up orphaned element on param-restore failure.
    """
    symbol = doc.GetElement(info['type_id'])
    level  = doc.GetElement(info['level_id'])
    if symbol is None or level is None:
        return None

    new_fi = doc.Create.NewFamilyInstance(
        info['point'], symbol, target_wall, level,
        DB.Structure.StructuralType.NonStructural)
    if new_fi is None:
        return None

    sub = DB.SubTransaction(doc)
    sub.Start()
    try:
        for entry in info['params']:
            _apply_param(new_fi, entry)
        try:
            if info['hand_flipped'] != new_fi.HandFlipped:
                new_fi.flipHand()
        except Exception:
            pass
        try:
            if info['facing_flipped'] != new_fi.FacingFlipped:
                new_fi.flipFacing()
        except Exception:
            pass
        sub.Commit()
        return new_fi.Id
    except Exception as ex:
        if sub.GetStatus() == DB.TransactionStatus.Started:
            sub.RollBack()
        try:
            doc.Delete(new_fi.Id)
        except Exception:
            pass
        print(u'_recreate_hosted param restore failed: {}'.format(ex))
        return None


def rehost_elements(doc, orig_wall_id, new_wall_ids, hosted_before, sorted_levels):
    """
    After splitting a wall, re-host every hosted element onto the correct segment.

    Matching rule (simple and reliable):
      Each wall segment has a base level (WALL_BASE_CONSTRAINT).
      Each hosted element has a level (LevelId).
      The correct segment = the one whose base level == element's level.

    If the element is already on orig_wall AND orig_wall's base level matches
    the element's level → leave it untouched.
    Otherwise → recreate on the matching segment, then delete original.

    Also handles elements auto-deleted by Revit during split (IsValidObject=False).
    """
    if not new_wall_ids or not hosted_before:
        return

    try:
        # Build {level_id_int: wall} map for every segment
        seg_by_level = {}   # level ElementId.IntegerValue → wall element
        for wid in [orig_wall_id] + list(new_wall_ids):
            try:
                w = doc.GetElement(wid)
                if w is None:
                    continue
                base_lvl_id = w.get_Parameter(
                    DB.BuiltInParameter.WALL_BASE_CONSTRAINT).AsElementId()
                seg_by_level[base_lvl_id.IntegerValue] = w
            except Exception:
                pass

        # Get orig wall base level for "leave it" check
        try:
            orig_wall = doc.GetElement(orig_wall_id)
            orig_base_lvl_int = orig_wall.get_Parameter(
                DB.BuiltInParameter.WALL_BASE_CONSTRAINT).AsElementId().IntegerValue
        except Exception:
            orig_base_lvl_int = -1

        to_delete = []

        for info in hosted_before:
            try:
                elem_lvl_int = info['level_id'].IntegerValue

                # Find the correct wall segment for this element's level
                target_wall = seg_by_level.get(elem_lvl_int)
                if target_wall is None:
                    # No exact level match — element stays on orig wall
                    continue

                # Check if element is already alive on the correct segment
                fi       = doc.GetElement(info['elem_id'])
                is_valid = (fi is not None and fi.IsValidObject)

                on_correct_wall = (
                    is_valid
                    and target_wall.Id.IntegerValue == orig_wall_id.IntegerValue
                )
                if on_correct_wall:
                    continue   # already in the right place, nothing to do

                # Recreate on correct segment
                new_id = _recreate_hosted(doc, info, target_wall)
                if new_id is not None and is_valid:
                    # Only delete original if it still exists and recreate succeeded
                    to_delete.append(info['elem_id'])
                # If element was auto-deleted (not is_valid), original is already gone

            except Exception as ex:
                print(u'rehost: skipped {} — {}'.format(
                    info['elem_id'].IntegerValue, ex))

        for eid in to_delete:
            try:
                doc.Delete(eid)
            except Exception:
                pass

    except Exception as ex:
        print(u'rehost_elements error: {}'.format(ex))



def snapshot_wall_params(wall):
    """
    Capture all writable instance parameters of wall that should be
    copied to split segments (everything except level/offset/height geometry).
    Returns list of param entry dicts compatible with _apply_param.
    """
    # BIP names to skip — geometry that each segment manages independently
    _SKIP_NAMES = set([
        'WALL_BASE_CONSTRAINT', 'WALL_BASE_OFFSET',
        'WALL_TOP_CONSTRAINT',  'WALL_TOP_OFFSET',
        'WALL_HEIGHT_TYPE',     'WALL_USER_HEIGHT_PARAM',
        'WALL_STRUCTURAL_SIGNIFICANT',
    ])

    entries = []
    for p in wall.Parameters:
        try:
            st = p.StorageType.ToString()
            if st == 'None':
                continue

            entry = {'st': st}

            if p.IsShared:
                entry['guid'] = str(p.GUID)
            else:
                bip_int  = -1
                bip_name = ''
                try:
                    bip_enum = p.Definition.BuiltInParameter
                    bip_name = bip_enum.ToString()
                    bip_int  = int(bip_enum)
                except Exception:
                    pass

                if bip_name in _SKIP_NAMES:
                    continue

                if bip_int != -1:
                    entry['bip'] = bip_int
                entry['name'] = p.Definition.Name

            # Value snapshot
            if st == 'Double':
                entry['v'] = p.AsDouble()
            elif st == 'Integer':
                entry['v'] = p.AsInteger()
            elif st == 'ElementId':
                entry['v'] = p.AsElementId().IntegerValue
            elif st == 'String':
                val = p.AsString()
                entry['v'] = val if val is not None else u''
            else:
                continue

            entries.append(entry)
        except Exception:
            pass
    return entries


def apply_wall_params(doc, wall, entries):
    """Apply param snapshot to a wall segment inside a SubTransaction."""
    if not entries:
        return
    sub = DB.SubTransaction(doc)
    sub.Start()
    try:
        for entry in entries:
            _apply_param(wall, entry)
        sub.Commit()
    except Exception as ex:
        if sub.GetStatus() == DB.TransactionStatus.Started:
            sub.RollBack()
        print(u'apply_wall_params error: {}'.format(ex))


def split_wall_at(doc, wall, sorted_levels, split_elevs, offsets=None,
                  elem_base_off=0.0, elem_top_off=0.0):
    """
    offsets: {elev_ft: (top_off_ft, base_off_ft)}  — per split point
    elem_base_off: offset (ft) applied to the BASE of segment 0
    elem_top_off:  offset (ft) applied to the TOP  of the last segment
    """
    if offsets is None:
        offsets = {}
    result = []
    elevs = get_element_base_top(doc, wall)
    if not elevs or not split_elevs:
        return result
    base_elev, top_elev = elevs
    split_elevs = sorted([e for e in split_elevs
                          if base_elev + TOLERANCE < e < top_elev - TOLERANCE])
    if not split_elevs:
        return result

    # Snapshot wall instance params BEFORE any geometry change
    wall_param_snapshot = snapshot_wall_params(wall)

    actual_bots = [base_elev + elem_base_off]
    actual_tops = []
    for i, se in enumerate(split_elevs):
        top_off, base_off = offsets.get(se, (0.0, 0.0))
        actual_tops.append(se + top_off)
        actual_bots.append(se + base_off)
    actual_tops.append(top_elev + elem_top_off)

    orig_base_lvl_id = wall.get_Parameter(
        DB.BuiltInParameter.WALL_BASE_CONSTRAINT).AsElementId()
    orig_base_lvl = doc.GetElement(orig_base_lvl_id)

    location = wall.Location
    if not isinstance(location, DB.LocationCurve):
        return result
    wall_curve   = location.Curve
    wall_type_id = wall.GetTypeId()
    structural   = wall.StructuralUsage != DB.Structure.StructuralWallUsage.NonBearing

    for i, (ab, at) in enumerate(zip(actual_bots, actual_tops)):
        height = at - ab
        if height <= 0:
            continue
        base_lvl = orig_base_lvl if i == 0 else _find_base_lvl(ab, sorted_levels)
        if base_lvl is None:
            continue
        base_offset = ab - base_lvl.Elevation
        if i == 0:
            t_in = DB.SubTransaction(doc)
            t_in.Start()
            try:
                p = wall.get_Parameter(DB.BuiltInParameter.WALL_HEIGHT_TYPE)
                if p and not p.IsReadOnly:
                    p.Set(DB.ElementId.InvalidElementId)
                p = wall.get_Parameter(DB.BuiltInParameter.WALL_USER_HEIGHT_PARAM)
                if p and not p.IsReadOnly:
                    p.Set(height)
                p = wall.get_Parameter(DB.BuiltInParameter.WALL_BASE_OFFSET)
                if p and not p.IsReadOnly:
                    p.Set(base_offset)
                t_in.Commit()
            except Exception:
                t_in.RollBack()
        else:
            try:
                nw = DB.Wall.Create(doc, wall_curve, wall_type_id,
                                    base_lvl.Id, height, base_offset,
                                    wall.Flipped, structural)
                if nw:
                    # Copy instance params from original wall to new segment
                    apply_wall_params(doc, nw, wall_param_snapshot)
                    result.append(nw.Id)
            except Exception as ex:
                print('Wall seg {} error: {}'.format(i, ex))
    return result



def split_column_at(doc, column, sorted_levels, split_elevs, offsets=None,
                    elem_base_off=0.0, elem_top_off=0.0):
    """offsets: {elev_ft: (top_off_ft, base_off_ft)}
    elem_base_off: offset (ft) applied to the BASE of segment 0
    elem_top_off:  offset (ft) applied to the TOP  of the last segment
    """
    if offsets is None:
        offsets = {}
    result = []
    elevs = get_element_base_top(doc, column)
    if not elevs or not split_elevs:
        return result
    base_elev, top_elev = elevs
    split_elevs = sorted([e for e in split_elevs
                          if base_elev + TOLERANCE < e < top_elev - TOLERANCE])
    if not split_elevs:
        return result

    actual_bots = [base_elev + elem_base_off]
    actual_tops = []
    for se in split_elevs:
        top_off, base_off = offsets.get(se, (0.0, 0.0))
        actual_tops.append(se + top_off)
        actual_bots.append(se + base_off)
    actual_tops.append(top_elev + elem_top_off)

    orig_base_lvl_id = column.get_Parameter(
        DB.BuiltInParameter.FAMILY_BASE_LEVEL_PARAM).AsElementId()
    orig_base_lvl = doc.GetElement(orig_base_lvl_id)

    location = column.Location
    if isinstance(location, DB.LocationPoint):
        col_point = location.Point
    else:
        return result
    try:
        col_rotation = column.Location.Rotation
    except Exception:
        col_rotation = 0.0
    symbol_id = column.GetTypeId()
    struct_p  = column.get_Parameter(DB.BuiltInParameter.COLUMN_STRUCTURAL_PARAM) if hasattr(DB.BuiltInParameter, 'COLUMN_STRUCTURAL_PARAM') else None
    is_struct = (struct_p.AsInteger() == 1) if struct_p else False

    for i, (ab, at) in enumerate(zip(actual_bots, actual_tops)):
        if at - ab <= 0:
            continue
        base_lvl = orig_base_lvl if i == 0 else _find_base_lvl(ab, sorted_levels)
        top_lvl  = _find_top_lvl(at, sorted_levels)
        if not base_lvl or not top_lvl:
            continue
        base_off = ab - base_lvl.Elevation
        top_off  = at - top_lvl.Elevation
        if i == 0:
            t_in = DB.SubTransaction(doc)
            t_in.Start()
            try:
                p = column.get_Parameter(DB.BuiltInParameter.FAMILY_TOP_LEVEL_PARAM)
                if p and not p.IsReadOnly:
                    p.Set(top_lvl.Id)
                p = column.get_Parameter(DB.BuiltInParameter.FAMILY_TOP_LEVEL_OFFSET_PARAM)
                if p and not p.IsReadOnly:
                    p.Set(top_off)
                p = column.get_Parameter(DB.BuiltInParameter.FAMILY_BASE_LEVEL_OFFSET_PARAM)
                if p and not p.IsReadOnly:
                    p.Set(base_off)
                t_in.Commit()
            except Exception:
                t_in.RollBack()
        else:
            try:
                st_type = (DB.Structure.StructuralType.Column if is_struct
                           else DB.Structure.StructuralType.NonStructural)
                nc = doc.Create.NewFamilyInstance(
                    col_point, doc.GetElement(symbol_id), base_lvl, st_type)
                if nc:
                    t_in = DB.SubTransaction(doc)
                    t_in.Start()
                    try:
                        p = nc.get_Parameter(DB.BuiltInParameter.FAMILY_TOP_LEVEL_PARAM)
                        if p and not p.IsReadOnly:
                            p.Set(top_lvl.Id)
                        p = nc.get_Parameter(DB.BuiltInParameter.FAMILY_TOP_LEVEL_OFFSET_PARAM)
                        if p and not p.IsReadOnly:
                            p.Set(top_off)
                        p = nc.get_Parameter(DB.BuiltInParameter.FAMILY_BASE_LEVEL_OFFSET_PARAM)
                        if p and not p.IsReadOnly:
                            p.Set(base_off)
                        if col_rotation != 0.0:
                            axis = DB.Line.CreateBound(
                                col_point,
                                DB.XYZ(col_point.X, col_point.Y, col_point.Z + 1))
                            DB.ElementTransformUtils.RotateElement(
                                doc, nc.Id, axis, col_rotation)
                        t_in.Commit()
                        result.append(nc.Id)
                    except Exception:
                        t_in.RollBack()
            except Exception as ex:
                print('Col seg {} error: {}'.format(i, ex))
    return result


# ═══════════════════════════════════════════════════════════
#  SHARED BUTTON FACTORY  (same as reference)
# ═══════════════════════════════════════════════════════════

def _btn(text, bg, x, y, w=110, h=28, fg=None):
    b           = Button()
    b.Text      = text
    b.Font      = Font('Segoe UI', 9, FontStyle.Bold)
    b.Size      = Size(w, h)
    b.Location  = Point(x, y)
    b.BackColor = bg
    b.ForeColor = fg if fg else Color.White
    b.FlatStyle = FlatStyle.Flat
    b.FlatAppearance.BorderSize = 0
    return b


# ═══════════════════════════════════════════════════════════
#  STEP 1 — SELECT ELEMENTS FORM
# ═══════════════════════════════════════════════════════════

class SelectElementsForm(Form):
    """
    Step 1: display all spanning walls/columns, user picks which ones to analyze.
    Supports Pick from Revit and Add to current list.
    _pending_action: None | 'pick' | 'add'
    """

    def __init__(self, items, sorted_levels, doc):
        self.doc             = doc
        self.items           = items            # list of dicts from analyze_elements
        self.sorted_levels   = sorted_levels
        self._pending_action = None
        self._filter_ready   = False
        self._cat_filter     = 'All'            # 'All' | 'Wall' | 'Column'
        self._n_selected     = 0
        self.selected_items  = []               # output: items user checked
        self._split_executed = False            # set True after Step 2 executes split
        self.InitializeComponent()

    # ────────────────────────────────────────────────────────
    def InitializeComponent(self):
        self.Text            = 'Split Wall / Column by Level'
        self.Size            = Size(1050, 680)
        self.MinimumSize     = Size(800, 500)
        self.StartPosition   = FormStartPosition.CenterScreen
        self.FormBorderStyle = FormBorderStyle.Sizable
        self.BackColor       = C_BG

        n_ready = sum(1 for i in self.items if i['_ready'])
        n_skip  = sum(1 for i in self.items if i['status'] == 'Skip')
        n_err   = sum(1 for i in self.items if i['status'] == 'Error')
        n_total = len(self.items)

        # ── HEADER  (deferred — added last) ─────────────────
        hdr           = Panel()
        hdr.Dock      = DockStyle.Top
        hdr.Height    = 130
        hdr.BackColor = C_HEADER

        lbl_title           = Label()
        lbl_title.Text      = u'Split Wall / Column by Level'
        lbl_title.Font      = FONT_TITLE
        lbl_title.ForeColor = C_TEXT
        lbl_title.AutoSize  = True
        lbl_title.Location  = Point(20, 14)
        hdr.Controls.Add(lbl_title)

        lbl_proj            = Label()
        lbl_proj.Text       = u'Project:  {}'.format(self.doc.Title or 'Unnamed')
        lbl_proj.Font       = FONT_SMALL
        lbl_proj.ForeColor  = C_SUBTEXT
        lbl_proj.AutoSize   = True
        lbl_proj.Location   = Point(hdr.Width - 360, 26)
        lbl_proj.Anchor     = AnchorStyles.Top | AnchorStyles.Right
        hdr.Controls.Add(lbl_proj)

        lbl_copy            = Label()
        lbl_copy.Text       = u'\u00a9 Nhat Vu — All Rights Reserved'
        lbl_copy.Font       = Font('Segoe UI', 8, FontStyle.Italic)
        lbl_copy.ForeColor  = C_SUBTEXT
        lbl_copy.AutoSize   = True
        lbl_copy.Location   = Point(22, 50)
        hdr.Controls.Add(lbl_copy)

        # Help button — small circle ?
        btn_help            = Button()
        btn_help.Text       = u'?'
        btn_help.Font       = Font('Segoe UI', 10, FontStyle.Bold)
        btn_help.Size       = Size(26, 26)
        btn_help.Location   = Point(hdr.Width - 42, 20)
        btn_help.Anchor     = AnchorStyles.Top | AnchorStyles.Right
        btn_help.FlatStyle  = FlatStyle.Flat
        btn_help.BackColor  = C_SURFACE
        btn_help.ForeColor  = C_TEXT
        btn_help.FlatAppearance.BorderSize  = 1
        btn_help.FlatAppearance.BorderColor = Color.FromArgb(160, 160, 160)
        btn_help.Click     += lambda s, e: MessageBox.Show(
            u'Step 1 — Select Elements\n\n'
            u'1. Use \u25b6 Pick to select elements in Revit\n'
            u'2. Use + Add to append more elements\n'
            u'3. Check/uncheck rows you want to split\n'
            u'4. Click Analyze Selected \u2192 to proceed\n\n'
            u'Row colours:\n'
            u'  White  = Ready to split\n'
            u'  Yellow = Skip (single-level element)\n'
            u'  Red    = Error reading element',
            u'Help', MessageBoxButtons.OK, MessageBoxIcon.Information)
        hdr.Controls.Add(btn_help)

        # ── Config row  y = 68 ───────────────────────────────
        cfg_y = 68
        CMB_X = 22    # combo left edge — label sits left of it, badges start here

        # Category filter label + combo
        lbl_cat           = Label()
        lbl_cat.Text      = u'Category :'
        lbl_cat.Font      = FONT_SMALL_BOLD
        lbl_cat.ForeColor = C_TEXT
        lbl_cat.AutoSize  = True
        lbl_cat.Location  = Point(CMB_X, cfg_y + 6)
        hdr.Controls.Add(lbl_cat)

        self.cmb_cat               = ComboBox()
        self.cmb_cat.DropDownStyle = ComboBoxStyle.DropDownList
        self.cmb_cat.Font          = FONT_NORM
        self.cmb_cat.Size          = Size(100, 26)
        self.cmb_cat.Location      = Point(CMB_X + 82, cfg_y + 2)   # right-align after label
        self.cmb_cat.BackColor     = C_SURFACE
        self.cmb_cat.ForeColor     = C_TEXT
        for opt in [u'All', u'Wall', u'Column']:
            self.cmb_cat.Items.Add(opt)
        self.cmb_cat.SelectedIndex = 0
        self.cmb_cat.SelectedIndexChanged += self._on_cat_changed
        hdr.Controls.Add(self.cmb_cat)

        # Stat badges — start with clear gap after combo right edge (CMB_X+82+100 = 204)
        BADGE_X0 = CMB_X + 82 + 100 + 36   # = 240, checkbox at 220
        self.chk_only_ready           = CheckBox()
        self.chk_only_ready.Text      = u''
        self.chk_only_ready.Size      = Size(16, 16)
        self.chk_only_ready.Location  = Point(BADGE_X0 - 20, cfg_y + 8)
        self.chk_only_ready.BackColor = C_HEADER
        self.chk_only_ready.CheckedChanged += self.OnToggleOnlyReady
        hdr.Controls.Add(self.chk_only_ready)

        self.stat_labels = {}
        for key, clr, xpos in [
            ('spanning', C_OK,    BADGE_X0),
            ('skip',     C_WARN,  BADGE_X0 + 88),
            ('error',    C_ERR,   BADGE_X0 + 168),
            ('total',    C_TEXT,  BADGE_X0 + 246),
            ('levels',   C_ACCENT, BADGE_X0 + 326),
        ]:
            lb           = Label()
            lb.Font      = FONT_SMALL_BOLD
            lb.ForeColor = clr
            lb.AutoSize  = True
            lb.Location  = Point(xpos, cfg_y + 6)
            self.stat_labels[key] = lb
            hdr.Controls.Add(lb)

        # ── Button row  y = cfg_y + 34 ───────────────────────
        BTN_Y = cfg_y + 34
        BTN_W, BTN_GAP = 120, 5

        self.btn_pick   = _btn(u'\u25b6 Pick',             C_ACCENT,                     20, BTN_Y, BTN_W)
        self.btn_add    = _btn(u'+ Add',                   Color.FromArgb(39, 100, 160), 20 + (BTN_W + BTN_GAP),     BTN_Y, BTN_W)
        btn_selall      = _btn(u'Select All',              C_GRID_HDR,                   20 + (BTN_W + BTN_GAP) * 2, BTN_Y, BTN_W)
        btn_clrall      = _btn(u'Clear All',               C_GRID_HDR,                   20 + (BTN_W + BTN_GAP) * 3, BTN_Y, BTN_W)
        self.btn_next   = _btn(u'Analyze Selected \u2192', C_OK,                         20 + (BTN_W + BTN_GAP) * 4, BTN_Y, BTN_W + 30)

        # OK — inline, immediately right of Analyze Selected
        _analyze_end = 20 + (BTN_W + BTN_GAP) * 4 + (BTN_W + 30)
        self.btn_ok = _btn(u'\u2714 OK', Color.FromArgb(140, 140, 140),
                           _analyze_end + BTN_GAP, BTN_Y, 70)

        self.btn_pick.Click  += self.OnPick
        self.btn_add.Click   += self.OnAdd
        btn_selall.Click     += lambda s, e: self._set_all_checks(True)
        btn_clrall.Click     += lambda s, e: self._set_all_checks(False)
        self.btn_next.Click  += self.OnNext
        self.btn_ok.Click    += self.OnOK

        for b in (self.btn_pick, self.btn_add, btn_selall, btn_clrall, self.btn_next, self.btn_ok):
            hdr.Controls.Add(b)

        # Status label
        self.lbl_status           = Label()
        self.lbl_status.Font      = FONT_BOLD
        self.lbl_status.ForeColor = C_SUBTEXT
        self.lbl_status.AutoSize  = True
        self.lbl_status.Location  = Point(22, BTN_Y + 32)
        hdr.Controls.Add(self.lbl_status)

        # Selected-row count (right-anchored)
        self.lbl_sel              = Label()
        self.lbl_sel.Text         = u''
        self.lbl_sel.Font         = FONT_BOLD
        self.lbl_sel.ForeColor    = C_ACCENT
        self.lbl_sel.AutoSize     = True
        self.lbl_sel.Anchor       = AnchorStyles.Top | AnchorStyles.Right
        self.lbl_sel.Location     = Point(hdr.Width - 180, BTN_Y + 5)
        hdr.Controls.Add(self.lbl_sel)

        self._deferred_header = hdr

        # ── GRID ────────────────────────────────────────────
        grid_wrap           = Panel()
        grid_wrap.Dock      = DockStyle.Fill
        grid_wrap.BackColor = C_BG
        grid_wrap.Padding   = Padding(4, 6, 4, 4)

        self.grid = DataGridView()
        self.grid.Dock                                  = DockStyle.Fill
        self.grid.AllowUserToAddRows                    = False
        self.grid.AllowUserToDeleteRows                 = False
        self.grid.ReadOnly                              = False
        self.grid.SelectionMode                         = DataGridViewSelectionMode.FullRowSelect
        self.grid.MultiSelect                           = True
        self.grid.RowHeadersVisible                     = False
        self.grid.BackgroundColor                       = C_SURFACE
        self.grid.GridColor                             = C_SURFACE2
        self.grid.BorderStyle                           = BorderStyle.FixedSingle
        self.grid.DefaultCellStyle.BackColor            = C_SURFACE
        self.grid.DefaultCellStyle.ForeColor            = C_TEXT
        self.grid.DefaultCellStyle.Font                 = FONT_NORM
        self.grid.DefaultCellStyle.SelectionBackColor   = C_SEL
        self.grid.DefaultCellStyle.SelectionForeColor   = Color.White
        self.grid.AlternatingRowsDefaultCellStyle.BackColor = C_GRID_ALT
        self.grid.ColumnHeadersDefaultCellStyle.BackColor   = C_GRID_HDR
        self.grid.ColumnHeadersDefaultCellStyle.ForeColor   = Color.White
        self.grid.ColumnHeadersDefaultCellStyle.Font        = FONT_BOLD
        self.grid.ColumnHeadersDefaultCellStyle.SelectionBackColor = C_GRID_HDR
        self.grid.EnableHeadersVisualStyles             = False
        self.grid.ColumnHeadersHeight                   = 34
        self.grid.RowTemplate.Height                    = 26
        self.grid.AutoSizeColumnsMode                   = DataGridViewAutoSizeColumnsMode.Fill
        self.grid.ScrollBars                            = ScrollBars.Both
        self.grid.CellClick      += self._on_cell_click
        self.grid.SelectionChanged += self._on_selection_changed

        for col_name, header, w, ro, fixed in [
            ('_chk',       '',                    36, False, True),
            ('Num',        '#',                   40, True,  True),
            ('ID',         'Element ID',          80, True,  True),
            ('Category',   'Category',           100, True,  False),
            ('Name',       'Type Name',          220, True,  False),
            ('BaseLevel',  'Base Level',         110, True,  False),
            ('TopLevel',   'Top Level',          110, True,  False),
            ('HeightM',    'Height (m)',          76, True,  True),
            ('Spans',      'Intermediate Lvls',   96, True,  True),
            ('Status',     'Status',              70, True,  True),
        ]:
            if col_name == '_chk':
                col = DataGridViewCheckBoxColumn()
            else:
                col = DataGridViewTextBoxColumn()
            col.HeaderText = header
            col.Name       = col_name
            col.MinimumWidth = 30
            col.ReadOnly   = ro
            col.Width      = w
            col.SortMode   = DataGridViewColumnSortMode.Automatic
            if fixed:
                col.AutoSizeMode = getattr(DataGridViewAutoSizeColumnMode, 'None')
            self.grid.Columns.Add(col)

        self.grid.Columns['Num'].DefaultCellStyle.Alignment = DataGridViewContentAlignment.MiddleCenter
        self.grid.Columns['Num'].Frozen = True

        grid_wrap.Controls.Add(self.grid)

        # WinForms dock order: Fill first, then Top header last
        self.Controls.Add(grid_wrap)
        self.Controls.Add(self._deferred_header)

        # X (close) = no transaction, no pending action
        self.FormClosing += self._on_form_closing

        self._populate_grid()
        self._update_status()

    # ── Population ──────────────────────────────────────────

    def _populate_grid(self):
        self.grid.Rows.Clear()
        cat = self._cat_filter
        for idx, item in enumerate(self.items):
            # Category filter
            if cat == 'Wall'   and item['category'] != 'Wall':
                continue
            if cat == 'Column' and item['category'] == 'Wall':
                continue
            ri = self.grid.Rows.Add()
            self._fill_row(self.grid.Rows[ri], idx, item)

    def _fill_row(self, row, idx, item):
        is_ready = item['_ready']
        row.Cells['_chk'].Value      = is_ready
        row.Cells['_chk'].ReadOnly   = not is_ready
        row.Cells['Num'].Value       = idx + 1
        row.Cells['ID'].Value        = item['id']
        row.Cells['Category'].Value  = item['category']
        row.Cells['Name'].Value      = item['name']
        row.Cells['BaseLevel'].Value = item['base_level']
        row.Cells['TopLevel'].Value  = item['top_level']
        row.Cells['HeightM'].Value   = item['height_m']
        row.Cells['Spans'].Value     = ('{} level(s)'.format(item['spans'])
                                        if item['spans'] > 0 else u'\u2014')
        row.Cells['Status'].Value    = item['status']
        row.Tag = idx

        status = item['status']
        if status == 'Skip':
            row.DefaultCellStyle.BackColor = C_ROW_SKIP
        elif status == 'Error':
            row.DefaultCellStyle.BackColor = C_ROW_ERR
        elif status == 'Done':
            row.DefaultCellStyle.BackColor = C_ROW_DONE

        clr_map = {'Ready': C_OK, 'Skip': C_WARN, 'Error': C_ERR,
                   'Done': Color.FromArgb(41, 128, 185)}
        row.Cells['Status'].Style.ForeColor = clr_map.get(status, C_TEXT)
        row.Cells['Status'].Style.Font      = FONT_BOLD

        # Extra highlight for elements spanning 3+ levels
        if is_ready and item['spans'] >= 3:
            row.Cells['Spans'].Style.ForeColor = C_ERR
            row.Cells['Spans'].Style.Font      = FONT_BOLD

    # ── Events ──────────────────────────────────────────────

    def _on_cell_click(self, sender, event):
        if event.RowIndex < 0 or event.ColumnIndex < 0:
            return
        if self.grid.Columns[event.ColumnIndex].Name != '_chk':
            return
        clicked_row = self.grid.Rows[event.RowIndex]
        idx = clicked_row.Tag
        if idx is None or idx >= len(self.items):
            return
        if not self.items[idx]['_ready']:
            return
        cur     = clicked_row.Cells['_chk'].Value
        new_val = not bool(cur)
        # Apply to all selected visible rows + clicked row
        selected_indices = set(r.Tag for r in self.grid.SelectedRows
                               if r.Tag is not None and r.Tag < len(self.items))
        selected_indices.add(idx)
        for row in self.grid.Rows:
            if row.Tag in selected_indices and self.items[row.Tag]['_ready']:
                row.Cells['_chk'].Value = new_val
        self._update_status()

    def _on_selection_changed(self, sender, event):
        try:
            indices = set()
            for cell in self.grid.SelectedCells:
                if cell.RowIndex >= 0:
                    indices.add(cell.RowIndex)
            n = len(indices)
        except Exception:
            n = 0
        self._n_selected = n
        if n > 0:
            self.lbl_sel.Text      = u'{} row{} selected'.format(n, u's' if n != 1 else u'')
            self.lbl_sel.ForeColor = C_ACCENT
        else:
            self.lbl_sel.Text = u''
        try:
            self.lbl_sel.Location = Point(
                self.lbl_sel.Parent.Width - self.lbl_sel.Width - 12,
                self.lbl_sel.Location.Y)
        except Exception:
            pass
        self._update_status()

    def OnToggleOnlyReady(self, sender, event):
        self._filter_ready = self.chk_only_ready.Checked
        self._apply_row_filter()

    def _apply_row_filter(self):
        """Apply both ready-only and category filters to visible rows."""
        cat = self._cat_filter
        for ri in range(self.grid.Rows.Count):
            row  = self.grid.Rows[ri]
            idx  = row.Tag
            if idx is None or idx >= len(self.items):
                continue
            item = self.items[idx]
            cat_ok   = (cat == 'All'
                        or (cat == 'Wall'   and item['category'] == 'Wall')
                        or (cat == 'Column' and item['category'] != 'Wall'))
            ready_ok = (not self._filter_ready) or item['_ready']
            row.Visible = cat_ok and ready_ok

    def _on_cat_changed(self, sender, event):
        sel = self.cmb_cat.SelectedItem
        self._cat_filter = str(sel) if sel else 'All'
        self._populate_grid()
        self._update_status()

    def _set_all_checks(self, state):
        for row in self.grid.Rows:
            if not row.Visible:
                continue
            idx = row.Tag
            if idx is not None and idx < len(self.items) and self.items[idx]['_ready']:
                row.Cells['_chk'].Value = state
        self.grid.Refresh()
        self._update_status()

    def _is_checked(self, ri):
        val = self.grid.Rows[ri].Cells['_chk'].Value
        return val is True or val == True

    def _update_status(self):
        n_ready = sum(1 for i in self.items if i['_ready'])
        n_skip  = sum(1 for i in self.items if i['status'] == 'Skip')
        n_err   = sum(1 for i in self.items if i['status'] == 'Error')
        n_total = len(self.items)
        checked = sum(1 for ri, item in enumerate(self.items)
                      if item['_ready'] and self._is_checked_by_id(item['id']))
        self.stat_labels['spanning'].Text = u'{} Ready'.format(n_ready)
        self.stat_labels['skip'].Text     = u'{} Skip'.format(n_skip)
        self.stat_labels['error'].Text    = u'{} Error'.format(n_err)
        self.stat_labels['total'].Text    = u'{} Total'.format(n_total)
        self.stat_labels['levels'].Text   = u'{} Levels'.format(len(self.sorted_levels))
        self.lbl_status.Text      = (u'{} / {} ready elements checked'.format(checked, n_ready)
                                     if n_total > 0
                                     else u'Use \u25b6 Pick to select elements in Revit')
        self.lbl_status.ForeColor = C_OK if checked > 0 else C_WARN

    def _is_checked_by_id(self, elem_id):
        """Check checkbox state by scanning grid rows (respects filtered view)."""
        for row in self.grid.Rows:
            if row.Tag is not None and row.Tag < len(self.items):
                if self.items[row.Tag]['id'] == elem_id:
                    val = row.Cells['_chk'].Value
                    return val is True or val == True
        return False

    # ── Actions ──────────────────────────────────────────────

    def _on_form_closing(self, sender, event):
        # If closed via X (no pending action set by a button), keep _pending_action = None.
        # This guarantees X = no transaction, no side effects.
        # Buttons that intend to act set _pending_action before calling self.Close().
        pass   # Nothing to do — _pending_action stays None unless a button set it

    def OnPick(self, sender, event):
        self._pending_action = 'pick'
        self.Close()

    def OnAdd(self, sender, event):
        self._pending_action = 'add'
        self.Close()

    def _is_checked(self, items_idx):
        """Lookup by items index via row.Tag."""
        for row in self.grid.Rows:
            if row.Tag == items_idx:
                val = row.Cells['_chk'].Value
                return val is True or val == True
        return False

    def OnNext(self, sender, event):
        selected = []
        seen = set()
        for row in self.grid.Rows:
            idx = row.Tag
            if idx is None or idx >= len(self.items) or idx in seen:
                continue
            val = row.Cells['_chk'].Value
            if (val is True or val == True) and self.items[idx]['_ready']:
                selected.append(self.items[idx])
                seen.add(idx)
        if not selected:
            MessageBox.Show(u'No elements checked.\nTick at least one Ready row.',
                            u'No Selection', MessageBoxButtons.OK, MessageBoxIcon.Warning)
            return
        self.selected_items  = selected
        self._pending_action = 'analyze'
        self.Close()

    def OnOK(self, sender, event):
        # If split was executed in Step 2, close and finish
        # If not yet executed, treat as X (close without action)
        if self._split_executed:
            self._pending_action = 'ok'
        else:
            self._pending_action = None
        self.Close()

    def MarkSplitExecuted(self):
        """Called from main() after Step 2 executes split. Lights up OK button."""
        self._split_executed = True
        self.btn_ok.BackColor = C_OK
        self.btn_ok.ForeColor = Color.White


# ═══════════════════════════════════════════════════════════
#  STEP 2 — ANALYZE & CHOOSE LEVELS FORM
# ═══════════════════════════════════════════════════════════

class AnalyzeLevelsForm(Form):
    """
    Step 2: for each selected element show intermediate levels.
    Left panel = element list, Right panel = level checklist.
    Same palette + header pattern as Step 1.
    _pending_action: None | 'back' | 'done'
    """

    def __init__(self, selected_items, sorted_levels, doc):
        self.doc            = doc
        self.items          = selected_items   # items from Step 1 (all _ready=True)
        self.sorted_levels  = sorted_levels
        # split_plan[elem_id] = {elev_ft: {'top_off_mm': 0.0, 'base_off_mm': 0.0}}
        # Special keys: '_elem_base_off_mm' (base of seg 0), '_elem_top_off_mm' (top of last seg)
        self.split_plan = {}
        for item in self.items:
            self.split_plan[item['id']] = {
                e: {'top_off_mm': 0.0, 'base_off_mm': 0.0}
                for (e, _) in item['inter']
            }
            self.split_plan[item['id']]['_elem_base_off_mm'] = 0.0
            self.split_plan[item['id']]['_elem_top_off_mm']  = 0.0
        self._active_idx  = 0
        self._building    = False
        self._pending_action = None
        self.auto_join       = False   # set from checkbox
        self.InitializeComponent()

    # ────────────────────────────────────────────────────────
    def InitializeComponent(self):
        self.Text            = u'Split Wall / Column by Level  \u2014  Choose Split Points'
        self.Size            = Size(1160, 700)
        self.MinimumSize     = Size(860, 540)
        self.StartPosition   = FormStartPosition.CenterScreen
        self.FormBorderStyle = FormBorderStyle.Sizable
        self.BackColor       = C_BG

        n_elem  = len(self.items)
        n_walls = sum(1 for i in self.items if i['category'] == 'Wall')
        n_cols  = n_elem - n_walls

        # ── HEADER (deferred) ────────────────────────────────
        hdr           = Panel()
        hdr.Dock      = DockStyle.Top
        hdr.Height    = 156
        hdr.BackColor = C_HEADER

        lbl_title           = Label()
        lbl_title.Text      = u'Choose Split Points per Element'
        lbl_title.Font      = FONT_TITLE
        lbl_title.ForeColor = C_TEXT
        lbl_title.AutoSize  = True
        lbl_title.Location  = Point(20, 14)
        hdr.Controls.Add(lbl_title)

        lbl_proj            = Label()
        lbl_proj.Text       = u'Project:  {}'.format(self.doc.Title or 'Unnamed')
        lbl_proj.Font       = FONT_SMALL
        lbl_proj.ForeColor  = C_SUBTEXT
        lbl_proj.AutoSize   = True
        lbl_proj.Location   = Point(hdr.Width - 360, 26)
        lbl_proj.Anchor     = AnchorStyles.Top | AnchorStyles.Right
        hdr.Controls.Add(lbl_proj)

        lbl_copy            = Label()
        lbl_copy.Text       = u'\u00a9 Nhat Vu — All Rights Reserved'
        lbl_copy.Font       = Font('Segoe UI', 8, FontStyle.Italic)
        lbl_copy.ForeColor  = C_SUBTEXT
        lbl_copy.AutoSize   = True
        lbl_copy.Location   = Point(22, 50)
        hdr.Controls.Add(lbl_copy)

        btn_help            = Button()
        btn_help.Text       = u'?'
        btn_help.Font       = Font('Segoe UI', 10, FontStyle.Bold)
        btn_help.Size       = Size(26, 26)
        btn_help.Location   = Point(hdr.Width - 42, 20)
        btn_help.Anchor     = AnchorStyles.Top | AnchorStyles.Right
        btn_help.FlatStyle  = FlatStyle.Flat
        btn_help.BackColor  = C_SURFACE
        btn_help.ForeColor  = C_TEXT
        btn_help.FlatAppearance.BorderSize  = 1
        btn_help.FlatAppearance.BorderColor = Color.FromArgb(160, 160, 160)
        btn_help.Click     += lambda s, e: MessageBox.Show(
            u'Step 2 — Choose Split Points\n\n'
            u'1. Click an element row on the LEFT panel\n'
            u'2. The RIGHT panel shows all intermediate levels\n'
            u'3. Check the levels you WANT to split at\n'
            u'   Uncheck levels you want to SKIP\n'
            u'4. Use Check All / Uncheck All for quick selection\n'
            u'5. Click \u26a1 Execute Split when ready\n\n'
            u'The Plan column shows: selected / total splits\n'
            u'Green rows = will split   Grey rows = will skip',
            u'Help', MessageBoxButtons.OK, MessageBoxIcon.Information)
        hdr.Controls.Add(btn_help)

        cfg_y = 68

        # Stat badges
        for text, clr, xpos in [
            (u'{} Elements'.format(n_elem),  C_OK,    22),
            (u'{} Walls'.format(n_walls),    C_ACCENT, 118),
            (u'{} Columns'.format(n_cols),   Color.FromArgb(41, 128, 185), 196),
            (u'{} Levels'.format(len(self.sorted_levels)), C_TEXT, 290),
        ]:
            lb           = Label()
            lb.Text      = text
            lb.Font      = FONT_SMALL_BOLD
            lb.ForeColor = clr
            lb.AutoSize  = True
            lb.Location  = Point(xpos, cfg_y + 6)
            hdr.Controls.Add(lb)

        # Button row — each button sized to fit its text
        BTN_Y   = cfg_y + 34
        BTN_GAP = 6

        btn_chkall     = _btn(u'Check All Segments',   C_GRID_HDR, 20,  BTN_Y, 148)
        btn_unchk      = _btn(u'Uncheck All Segments', C_GRID_HDR, 20 + 148 + BTN_GAP, BTN_Y, 158)
        self.btn_split = _btn(u'\u26a1 Execute Split', C_OK,  20 + 148 + BTN_GAP + 158 + BTN_GAP, BTN_Y, 124)
        btn_back       = _btn(u'\u2190 Back', Color.FromArgb(130, 130, 130),
                              20 + 148 + BTN_GAP + 158 + BTN_GAP + 124 + BTN_GAP, BTN_Y, 74)

        btn_chkall.Click     += self._on_check_all
        btn_unchk.Click      += self._on_uncheck_all
        self.btn_split.Click += self._on_execute_split
        btn_back.Click       += lambda s, e: self._go_back()

        for b in (btn_chkall, btn_unchk, self.btn_split, btn_back):
            hdr.Controls.Add(b)

        # ── Bulk offset inputs (right of Back) ───────────────
        bulk_x = 20 + 148 + BTN_GAP + 158 + BTN_GAP + 124 + BTN_GAP + 74 + 14

        lbl_base_off           = Label()
        lbl_base_off.Text      = u'Base Off:'
        lbl_base_off.Font      = FONT_SMALL_BOLD
        lbl_base_off.ForeColor = C_TEXT
        lbl_base_off.AutoSize  = True
        lbl_base_off.Location  = Point(bulk_x, BTN_Y + 7)
        hdr.Controls.Add(lbl_base_off)

        self.txt_base_off          = TextBox()
        self.txt_base_off.Text     = u'0'
        self.txt_base_off.Font     = FONT_NORM
        self.txt_base_off.Size     = Size(54, 24)
        self.txt_base_off.Location = Point(bulk_x + 54, BTN_Y + 4)
        self.txt_base_off.TextAlign = System.Windows.Forms.HorizontalAlignment.Center
        hdr.Controls.Add(self.txt_base_off)

        lbl_top_off           = Label()
        lbl_top_off.Text      = u'Top Off:'
        lbl_top_off.Font      = FONT_SMALL_BOLD
        lbl_top_off.ForeColor = C_TEXT
        lbl_top_off.AutoSize  = True
        lbl_top_off.Location  = Point(bulk_x + 116, BTN_Y + 7)
        hdr.Controls.Add(lbl_top_off)

        self.txt_top_off          = TextBox()
        self.txt_top_off.Text     = u'0'
        self.txt_top_off.Font     = FONT_NORM
        self.txt_top_off.Size     = Size(54, 24)
        self.txt_top_off.Location = Point(bulk_x + 176, BTN_Y + 4)
        self.txt_top_off.TextAlign = System.Windows.Forms.HorizontalAlignment.Center
        hdr.Controls.Add(self.txt_top_off)

        lbl_mm           = Label()
        lbl_mm.Text      = u'mm'
        lbl_mm.Font      = FONT_SMALL
        lbl_mm.ForeColor = C_SUBTEXT
        lbl_mm.AutoSize  = True
        lbl_mm.Location  = Point(bulk_x + 234, BTN_Y + 7)
        hdr.Controls.Add(lbl_mm)

        btn_apply_off      = _btn(u'\u21d3 Apply All', C_ACCENT,
                                  bulk_x + 260, BTN_Y, 90, 28)
        btn_apply_off.Click += self._on_apply_bulk_offsets
        hdr.Controls.Add(btn_apply_off)

        # ── Hint label ───────────────────────────────────────
        HINT_Y = BTN_Y + 34
        lbl_hint           = Label()
        lbl_hint.Text      = u'Shift+click left panel to apply to multiple elements at once'
        lbl_hint.Font      = Font('Segoe UI', 8, FontStyle.Italic)
        lbl_hint.ForeColor = C_SUBTEXT
        lbl_hint.AutoSize  = True
        lbl_hint.Location  = Point(20, HINT_Y)
        hdr.Controls.Add(lbl_hint)

        # ── Auto-join checkbox ────────────────────────────────
        self.chk_join           = CheckBox()
        self.chk_join.Text      = u'Auto-join segments after split'
        self.chk_join.Font      = Font('Segoe UI', 8, FontStyle.Bold)
        self.chk_join.ForeColor = C_ACCENT
        self.chk_join.AutoSize  = True
        self.chk_join.Checked   = False
        self.chk_join.Location  = Point(bulk_x, HINT_Y)
        hdr.Controls.Add(self.chk_join)

        self.lbl_status           = Label()
        self.lbl_status.Font      = FONT_BOLD
        self.lbl_status.ForeColor = C_SUBTEXT
        self.lbl_status.AutoSize  = True
        self.lbl_status.Location  = Point(22, HINT_Y + 18)
        hdr.Controls.Add(self.lbl_status)

        self.lbl_sel              = Label()
        self.lbl_sel.Text         = u''
        self.lbl_sel.Font         = FONT_BOLD
        self.lbl_sel.ForeColor    = C_ACCENT
        self.lbl_sel.AutoSize     = True
        self.lbl_sel.Anchor       = AnchorStyles.Top | AnchorStyles.Right
        self.lbl_sel.Location     = Point(hdr.Width - 200, HINT_Y + 18)
        hdr.Controls.Add(self.lbl_sel)

        self._deferred_header = hdr

        # ── SPLIT CONTAINER (Fill — docked before header) ────
        sc                    = SplitContainer()
        sc.Dock               = DockStyle.Fill
        sc.Orientation        = Orientation.Vertical
        sc.SplitterDistance   = 700          # will be corrected on Shown
        sc.BackColor          = C_BG
        sc.Panel1.Padding     = Padding(4, 6, 2, 4)
        sc.Panel2.Padding     = Padding(2, 6, 4, 4)
        self._sc              = sc           # keep ref for Shown handler

        # ── LEFT: element grid (no header bar) ───────────────
        self.elem_grid = self._make_elem_grid()
        sc.Panel1.Controls.Add(self.elem_grid)

        # ── RIGHT: level grid + bottom label ────────────
        self.lvl_grid = self._make_lvl_grid()

        self.lbl_top_seg           = Label()
        self.lbl_top_seg.Dock      = DockStyle.Bottom
        self.lbl_top_seg.Height    = 22
        self.lbl_top_seg.Font      = Font('Segoe UI', 8, FontStyle.Italic)
        self.lbl_top_seg.ForeColor = C_SUBTEXT
        self.lbl_top_seg.Text      = u''
        self.lbl_top_seg.TextAlign = System.Drawing.ContentAlignment.MiddleLeft
        self.lbl_top_seg.Padding   = Padding(4, 0, 0, 0)

        # WinForms dock order inside Panel2: Fill first, Bottom last
        sc.Panel2.Controls.Add(self.lvl_grid)
        sc.Panel2.Controls.Add(self.lbl_top_seg)

        # WinForms dock order: Fill first, then Top header last
        self.Controls.Add(sc)
        self.Controls.Add(self._deferred_header)
        self.Shown += self._on_shown

        self._populate_elem_grid()
        self._update_status()

        # Auto-select first row
        if self.elem_grid.Rows.Count > 0:
            self.elem_grid.Rows[0].Selected = True

    # ── Grid factories ───────────────────────────────────────

    def _make_elem_grid(self):
        g = DataGridView()
        g.Dock          = DockStyle.Fill
        g.AllowUserToAddRows    = False
        g.AllowUserToDeleteRows = False
        g.ReadOnly      = True
        g.MultiSelect   = True
        g.SelectionMode = DataGridViewSelectionMode.FullRowSelect
        g.RowHeadersVisible = False
        g.BackgroundColor   = C_SURFACE
        g.GridColor         = C_SURFACE2
        g.BorderStyle       = BorderStyle.FixedSingle
        g.DefaultCellStyle.Font                 = FONT_NORM
        g.DefaultCellStyle.ForeColor            = C_TEXT
        g.DefaultCellStyle.BackColor            = C_SURFACE
        g.DefaultCellStyle.SelectionBackColor   = C_SEL
        g.DefaultCellStyle.SelectionForeColor   = Color.White
        g.AlternatingRowsDefaultCellStyle.BackColor = C_GRID_ALT
        g.ColumnHeadersDefaultCellStyle.BackColor   = C_GRID_HDR
        g.ColumnHeadersDefaultCellStyle.ForeColor   = Color.White
        g.ColumnHeadersDefaultCellStyle.Font        = FONT_BOLD
        g.ColumnHeadersDefaultCellStyle.SelectionBackColor = C_GRID_HDR
        g.EnableHeadersVisualStyles = False
        g.ColumnHeadersHeight       = 30
        g.RowTemplate.Height        = 26
        g.AutoSizeColumnsMode       = DataGridViewAutoSizeColumnsMode.Fill
        g.SelectionChanged         += self._on_elem_selected

        for col_name, header, w, fixed in [
            ('Num',      '#',        36, True),
            ('Category', 'Category', 80, False),
            ('Name',     'Type',    200, False),
            ('Base',     'Base',    100, False),
            ('Top',      'Top',     100, False),
            ('Hm',       'H(m)',     60, True),
            ('Plan',     'Segs',     52, True),
        ]:
            c = DataGridViewTextBoxColumn()
            c.HeaderText = header
            c.Name       = col_name
            c.Width      = w
            c.ReadOnly   = True
            c.SortMode   = DataGridViewColumnSortMode.Automatic
            if fixed:
                c.AutoSizeMode = getattr(DataGridViewAutoSizeColumnMode, 'None')
            g.Columns.Add(c)
        g.Columns['Num'].DefaultCellStyle.Alignment = DataGridViewContentAlignment.MiddleCenter
        return g

    def _make_lvl_grid(self):
        g = DataGridView()
        g.Dock          = DockStyle.Fill
        g.AllowUserToAddRows    = False
        g.AllowUserToDeleteRows = False
        g.ReadOnly      = False
        g.MultiSelect   = True
        g.SelectionMode = DataGridViewSelectionMode.FullRowSelect
        g.RowHeadersVisible = False
        g.BackgroundColor   = C_SURFACE
        g.GridColor         = C_SURFACE2
        g.BorderStyle       = BorderStyle.FixedSingle
        g.DefaultCellStyle.Font                 = FONT_NORM
        g.DefaultCellStyle.ForeColor            = C_TEXT
        g.DefaultCellStyle.BackColor            = C_SURFACE
        g.DefaultCellStyle.SelectionBackColor   = C_SEL
        g.DefaultCellStyle.SelectionForeColor   = Color.White
        g.AlternatingRowsDefaultCellStyle.BackColor = C_GRID_ALT
        g.ColumnHeadersDefaultCellStyle.BackColor   = C_GRID_HDR
        g.ColumnHeadersDefaultCellStyle.ForeColor   = Color.White
        g.ColumnHeadersDefaultCellStyle.Font        = FONT_BOLD
        g.ColumnHeadersDefaultCellStyle.SelectionBackColor = C_GRID_HDR
        g.EnableHeadersVisualStyles = False
        g.ColumnHeadersHeight       = 30
        g.RowTemplate.Height        = 28
        g.AutoSizeColumnsMode       = DataGridViewAutoSizeColumnsMode.Fill
        g.CellValueChanged         += self._on_cell_changed
        g.CurrentCellDirtyStateChanged += self._on_dirty

        chk = DataGridViewCheckBoxColumn()
        chk.HeaderText   = u'\u2714'
        chk.Name         = 'split'
        chk.Width        = 36
        chk.FillWeight   = 1
        chk.AutoSizeMode = DataGridViewAutoSizeColumnMode.NotSet
        g.Columns.Add(chk)

        for col_name, header, fill_weight, ro in [
            ('SegLabel', 'Segment',        32,  True),
            ('Hm',       'H (m)',           9,  True),
            ('BaseAdj',  'Base Off (mm)',  16,  False),
            ('TopAdj',   'Top Off (mm)',   16,  False),
        ]:
            c = DataGridViewTextBoxColumn()
            c.HeaderText   = header
            c.Name         = col_name
            c.MinimumWidth = 40
            c.FillWeight   = fill_weight
            c.ReadOnly     = ro
            c.SortMode     = DataGridViewColumnSortMode.NotSortable
            c.AutoSizeMode = DataGridViewAutoSizeColumnMode.Fill
            g.Columns.Add(c)
        return g

    # ── Population ───────────────────────────────────────────

    def _populate_elem_grid(self):
        self.elem_grid.Rows.Clear()
        for i, item in enumerate(self.items):
            plan = self.split_plan.get(item['id'], {})
            idx  = self.elem_grid.Rows.Add()
            self._fill_elem_row(self.elem_grid.Rows[idx], i, item, plan)

    def _fill_elem_row(self, row, i, item, plan):
        row.Cells['Num'].Value      = i + 1
        row.Cells['Category'].Value = item['category']
        row.Cells['Name'].Value     = item['name']
        row.Cells['Base'].Value     = item['base_level']
        row.Cells['Top'].Value      = item['top_level']
        row.Cells['Hm'].Value       = item['height_m']
        # exclude pseudo-keys from count; show segments = split_points + 1
        n_plan = sum(1 for k in plan if isinstance(k, float))
        n_segs = n_plan + 1
        max_segs = item['spans'] + 1
        row.Cells['Plan'].Value     = u'{}/{}'.format(n_segs, max_segs)
        row.Tag = i
        row.DefaultCellStyle.ForeColor = (C_TEXT if n_plan > 0 else C_SUBTEXT)
        row.Cells['Plan'].Style.ForeColor = (C_OK if n_plan > 0 else C_WARN)
        row.Cells['Plan'].Style.Font      = FONT_BOLD

    def _refresh_lvl_grid(self, item):
        self._building = True
        plan      = self.split_plan.get(item['id'], {})
        inter     = item['inter']   # [(elev_ft, Level), ...]
        base_elev = item['base_elev']
        top_elev  = item['top_elev']
        N         = len(inter)       # number of intermediate levels = number of split points

        self.lvl_grid.Rows.Clear()

        # N+1 segments
        for i in range(N + 1):
            # Boundaries
            from_elev = base_elev        if i == 0 else inter[i - 1][0]
            from_name = item['base_level'] if i == 0 else get_name(inter[i - 1][1])
            to_elev   = inter[i][0]      if i < N  else top_elev
            to_name   = get_name(inter[i][1]) if i < N else item['top_level']
            seg_h     = feet_to_m(to_elev - from_elev)

            # Offsets: base of this seg = top_off of split below, top of this seg = base_off of split above
            base_adj  = plan.get('_elem_base_off_mm', 0.0) if i == 0 \
                        else plan.get(inter[i - 1][0], {}).get('base_off_mm', 0.0)
            top_adj   = plan.get('_elem_top_off_mm',  0.0) if i == N \
                        else plan.get(inter[i][0], {}).get('top_off_mm', 0.0)

            # Checkbox = "split at the top of this segment"
            is_last   = (i == N)
            checked   = (not is_last) and (inter[i][0] in plan)

            seg_lbl   = u'Seg {}/{} \u00b7 {} \u2192 {}'.format(i + 1, N + 1, from_name, to_name)

            ir = self.lvl_grid.Rows.Add()
            r  = self.lvl_grid.Rows[ir]
            r.Tag = i   # segment index

            r.Cells['split'].Value    = checked
            r.Cells['split'].ReadOnly = is_last   # last seg has no split above
            r.Cells['SegLabel'].Value = seg_lbl
            r.Cells['Hm'].Value       = u'{:.3f}'.format(seg_h)
            r.Cells['BaseAdj'].Value  = u'{:.0f}'.format(base_adj)
            r.Cells['TopAdj'].Value   = u'{:.0f}'.format(top_adj)

            # Offset cells always editable
            r.Cells['BaseAdj'].ReadOnly = False
            r.Cells['TopAdj'].ReadOnly  = False

            self._style_lvl_row(r, checked, is_last)

        self._update_status()
        self._building = False

        # Bottom summary label
        n_checked = sum(1 for k in plan if isinstance(k, float))
        self.lbl_top_seg.Text = u'  {}/{} split points active  \u2192  {} segment(s)'.format(
            n_checked, N, n_checked + 1)

    def _style_lvl_row(self, row, checked, is_last=False):
        C_SEG_ACTIVE = Color.FromArgb(214, 248, 214)  # green — will split
        C_SEG_LAST   = Color.FromArgb(235, 240, 255)  # blue tint — last segment
        C_SEG_SKIP   = Color.FromArgb(245, 245, 245)  # grey — no split at top

        if is_last:
            row.DefaultCellStyle.BackColor = C_SEG_LAST
            row.DefaultCellStyle.ForeColor = Color.FromArgb(41, 82, 163)
        elif checked:
            row.DefaultCellStyle.BackColor = C_SEG_ACTIVE
            row.DefaultCellStyle.ForeColor = Color.FromArgb(27, 94, 32)
        else:
            row.DefaultCellStyle.BackColor = C_SEG_SKIP
            row.DefaultCellStyle.ForeColor = C_SUBTEXT

        # Adj cells always white + editable
        for col in ('BaseAdj', 'TopAdj'):
            row.Cells[col].Style.BackColor = C_SURFACE
            row.Cells[col].Style.ForeColor = C_TEXT
            row.Cells[col].Style.Font      = FONT_BOLD

    # ── Events ───────────────────────────────────────────────

    def _on_elem_selected(self, sender, event):
        rows = self.elem_grid.SelectedRows
        if rows.Count > 0 and rows[0].Tag is not None:
            self._active_idx = rows[0].Tag
            self._refresh_lvl_grid(self.items[self._active_idx])

    def _on_dirty(self, sender, event):
        if self.lvl_grid.IsCurrentCellDirty:
            self.lvl_grid.CommitEdit(0)

    def _on_cell_changed(self, sender, event):
        if self._building:
            return
        if self._active_idx >= len(self.items):
            return
        item  = self.items[self._active_idx]
        row   = self.lvl_grid.Rows[event.RowIndex]
        seg_i = row.Tag   # int: segment index
        col   = self.lvl_grid.Columns[event.ColumnIndex].Name
        inter = item['inter']
        N     = len(inter)
        plan  = self.split_plan.setdefault(item['id'], {})

        if not isinstance(seg_i, int):
            return

        is_last = (seg_i == N)

        # ── Checkbox: toggle split at TOP of this segment ─────
        if col == 'split' and not is_last:
            # split elevation = top of this segment = inter[seg_i]
            elev    = inter[seg_i][0]
            checked = bool(row.Cells['split'].Value)
            if checked:
                if elev not in plan:
                    plan[elev] = {'top_off_mm': 0.0, 'base_off_mm': 0.0}
            else:
                plan.pop(elev, None)
            self._style_lvl_row(row, checked, is_last)
            self._sync_elem_row(self._active_idx)
            self._update_status()
            # Refresh bottom label
            n_checked = sum(1 for k in plan if isinstance(k, float))
            self.lbl_top_seg.Text = u'  {}/{} split points active  \u2192  {} segment(s)'.format(
                n_checked, N, n_checked + 1)

        # ── BaseAdj: base of this segment ─────────────────────
        elif col == 'BaseAdj':
            try:
                raw = row.Cells['BaseAdj'].Value
                val = float(str(raw).replace(',', '.')) if raw else 0.0
            except (ValueError, TypeError):
                val = 0.0
            if seg_i == 0:
                plan['_elem_base_off_mm'] = val
            else:
                elev = inter[seg_i - 1][0]
                if elev not in plan:
                    plan[elev] = {'top_off_mm': 0.0, 'base_off_mm': 0.0}
                plan[elev]['base_off_mm'] = val

        # ── TopAdj: top of this segment ───────────────────────
        elif col == 'TopAdj':
            try:
                raw = row.Cells['TopAdj'].Value
                val = float(str(raw).replace(',', '.')) if raw else 0.0
            except (ValueError, TypeError):
                val = 0.0
            if is_last:
                plan['_elem_top_off_mm'] = val
            else:
                elev = inter[seg_i][0]
                if elev not in plan:
                    plan[elev] = {'top_off_mm': 0.0, 'base_off_mm': 0.0}
                plan[elev]['top_off_mm'] = val

    def _sync_elem_row(self, idx):
        item = self.items[idx]
        plan = self.split_plan.get(item['id'], {})
        row  = self.elem_grid.Rows[idx]
        self._fill_elem_row(row, idx, item, plan)

    def _on_check_all(self, sender, event):
        if self._active_idx >= len(self.items):
            return
        item  = self.items[self._active_idx]
        inter = item['inter']
        N     = len(inter)
        plan  = self.split_plan.setdefault(item['id'], {})
        for r in self.lvl_grid.Rows:
            seg_i = r.Tag
            if not isinstance(seg_i, int):
                continue
            is_last = (seg_i == N)
            if not is_last:
                elev = inter[seg_i][0]
                r.Cells['split'].Value = True
                if elev not in plan:
                    plan[elev] = {'top_off_mm': 0.0, 'base_off_mm': 0.0}
            self._style_lvl_row(r, not is_last, is_last)
        self._sync_elem_row(self._active_idx)
        self._update_status()
        n_checked = sum(1 for k in plan if isinstance(k, float))
        self.lbl_top_seg.Text = u'  {}/{} split points active  \u2192  {} segment(s)'.format(
            n_checked, N, n_checked + 1)

    def _on_uncheck_all(self, sender, event):
        if self._active_idx >= len(self.items):
            return
        item  = self.items[self._active_idx]
        inter = item['inter']
        N     = len(inter)
        plan  = self.split_plan.get(item['id'], {})
        # Remove only float keys, keep pseudo-keys
        for k in [k for k in plan if isinstance(k, float)]:
            del plan[k]
        for r in self.lvl_grid.Rows:
            seg_i = r.Tag
            if not isinstance(seg_i, int):
                continue
            is_last = (seg_i == N)
            r.Cells['split'].Value = False
            self._style_lvl_row(r, False, is_last)
        self._sync_elem_row(self._active_idx)
        self._update_status()
        self.lbl_top_seg.Text = u'  0/{} split points active  \u2192  1 segment(s)'.format(N)

    def _update_status(self):
        total_pts = sum(
            sum(1 for k in v if isinstance(k, float))
            for v in self.split_plan.values())
        elems_with_plan = sum(1 for item in self.items
                              if any(isinstance(k, float)
                                     for k in self.split_plan.get(item['id'], {})))
        self.lbl_status.Text = (
            u'{} element(s) with split points   |   {} total split point(s)'.format(
                elems_with_plan, total_pts))
        self.lbl_status.ForeColor = C_OK if total_pts > 0 else C_WARN

        if self._active_idx < len(self.items):
            item = self.items[self._active_idx]
            plan = self.split_plan.get(item['id'], {})
            n_pts = sum(1 for k in plan if isinstance(k, float))
            self.lbl_sel.Text = u'{}/{} points selected'.format(n_pts, item['spans'])
            self.lbl_sel.ForeColor = C_OK if plan else C_WARN
        try:
            self.lbl_sel.Location = Point(
                self.lbl_sel.Parent.Width - self.lbl_sel.Width - 12,
                self.lbl_sel.Location.Y)
        except Exception:
            pass

    def _on_shown(self, sender, event):
        """Auto-size right panel — 40% of splitter width."""
        try:
            right_w  = int(self._sc.Width * 0.40)
            new_dist = self._sc.Width - right_w - self._sc.SplitterWidth
            if new_dist > 100:
                self._sc.SplitterDistance = new_dist
        except Exception:
            pass

    def _on_apply_bulk_offsets(self, sender, event):
        """Apply Base Off / Top Off to all checked levels of every element
        selected in the left panel. Falls back to the active element if none selected."""
        try:
            base_mm = float(str(self.txt_base_off.Text).replace(',', '.') or '0')
            top_mm  = float(str(self.txt_top_off.Text).replace(',', '.') or '0')
        except (ValueError, TypeError):
            MessageBox.Show(u'Please enter valid numbers (e.g. 0, -50, 100).',
                            u'Invalid Input', MessageBoxButtons.OK, MessageBoxIcon.Warning)
            return

        # Collect selected element indices from left panel
        selected_idxs = [row.Tag for row in self.elem_grid.SelectedRows
                         if row.Tag is not None]
        if not selected_idxs:
            selected_idxs = [self._active_idx]

        for idx in selected_idxs:
            if idx >= len(self.items):
                continue
            item = self.items[idx]
            plan = self.split_plan.get(item['id'], {})
            for elev in [k for k in plan if isinstance(k, float)]:
                plan[elev]['base_off_mm'] = base_mm
                plan[elev]['top_off_mm']  = top_mm
            plan['_elem_base_off_mm'] = base_mm
            plan['_elem_top_off_mm']  = top_mm

        # Refresh right panel if active element was in the batch
        if self._active_idx in selected_idxs:
            self._building = True
            item  = self.items[self._active_idx]
            inter = item['inter']
            N     = len(inter)
            plan  = self.split_plan.get(item['id'], {})
            for row in self.lvl_grid.Rows:
                seg_i = row.Tag
                if not isinstance(seg_i, int):
                    continue
                row.Cells['BaseAdj'].Value = u'{:.0f}'.format(base_mm)
                row.Cells['TopAdj'].Value  = u'{:.0f}'.format(top_mm)
            self._building = False

        self._update_status()

    def _go_back(self):
        self._pending_action = 'back'
        self.Close()

    # ── Execute split ─────────────────────────────────────────

    def _on_execute_split(self, sender, event):
        plan_map = {item['id']: self.split_plan.get(item['id'], {})
                    for item in self.items}
        to_do = [(item, plan_map[item['id']])
                 for item in self.items
                 if plan_map[item['id']]]

        if not to_do:
            MessageBox.Show(
                u'No split points selected.\n'
                u'Check at least one level in the right panel.',
                u'Nothing to Split', MessageBoxButtons.OK, MessageBoxIcon.Warning)
            return

        total_pts = sum(len([k for k in p if isinstance(k, float)]) for _, p in to_do)

        ok_n = err_n = 0
        failed_ids = []
        doc    = self.doc
        do_join = self.chk_join.Checked

        # NOTE: no Transaction here — the outer Transaction in main() is already open.
        # SubTransactions inside split_wall_at / split_column_at nest correctly inside it.
        try:
            split_results = []
            for item, plan_dict in to_do:
                try:
                    elem = doc.GetElement(DB.ElementId(item['id']))
                    if elem is None:
                        raise Exception('Element not found')
                    split_elevs = sorted(k for k in plan_dict if isinstance(k, float))
                    offsets = {
                        e: (plan_dict[e]['top_off_mm']  / 304.8,
                            plan_dict[e]['base_off_mm'] / 304.8)
                        for e in split_elevs
                    }
                    elem_base_off = plan_dict.get('_elem_base_off_mm', 0.0) / 304.8
                    elem_top_off  = plan_dict.get('_elem_top_off_mm',  0.0) / 304.8

                    # Collect hosted elements before split (walls only) — for warning only
                    hosted_before = []
                    if isinstance(elem, DB.Wall):
                        hosted_before = get_wall_hosted_elements(doc, elem)

                    if isinstance(elem, DB.Wall):
                        new_ids = split_wall_at(doc, elem, self.sorted_levels,
                                                split_elevs, offsets,
                                                elem_base_off, elem_top_off)
                    else:
                        new_ids = split_column_at(doc, elem, self.sorted_levels,
                                                  split_elevs, offsets,
                                                  elem_base_off, elem_top_off)

                    split_results.append((DB.ElementId(item['id']), new_ids, hosted_before))
                    item['status'] = 'Done'
                    ok_n += 1
                except Exception as ex:
                    item['status'] = 'Error'
                    failed_ids.append(item['id'])
                    err_n += 1
                    print(u'Error on ID {}: {}'.format(item['id'], ex))

            # Regenerate geometry, rehost misplaced elements, then join
            if split_results:
                doc.Regenerate()
                for orig_id, new_ids, hosted_before in split_results:
                    if new_ids and hosted_before:
                        rehost_elements(doc, orig_id, new_ids,
                                        hosted_before, self.sorted_levels)
                if do_join:
                    for orig_id, new_ids, _hosted in split_results:
                        if new_ids:
                            join_segments(doc, orig_id, new_ids)

        except Exception as tx_exc:
            MessageBox.Show(u'Split error:\n{}'.format(str(tx_exc)),
                            u'Error', MessageBoxButtons.OK, MessageBoxIcon.Error)
            return

        # Count hosted elements that may need manual rehosting
        hosted_total = sum(len(h) for _, _, h in split_results)

        self._update_status()
        msg = u'Split successfully!\n\nChanged : {}\nErrors  : {}\n\n' \
              u'Press OK in Step 1 to apply.\nPress X in Step 1 to cancel.'.format(ok_n, err_n)
        if hosted_total > 0:
            msg += (u'\n\n\u26a0  {} hosted element(s) (doors/windows) remain on their '
                    u'original wall segment.\nUse Revit\u2019s  Pick New Host  to manually '
                    u'rehost any that need to move.'.format(hosted_total))
        if failed_ids:
            msg += u'\n\nFailed IDs : {}'.format(u', '.join(str(x) for x in failed_ids[:10]))
        self.lbl_status.Text      = u'\u23f3 Staged — {} split, {} error(s)  |  OK in Step 1 to commit'.format(ok_n, err_n)
        self.lbl_status.ForeColor = C_OK if err_n == 0 else C_WARN
        MessageBox.Show(msg, u'Split Successfully', MessageBoxButtons.OK, MessageBoxIcon.Information)
        self._pending_action = 'done'
        self.Close()


# ═══════════════════════════════════════════════════════════
#  PICK FILTER
# ═══════════════════════════════════════════════════════════

class _WallColumnFilter(RvtSelection.ISelectionFilter):
    """Selection filter — cat: 'All' | 'Wall' | 'Column'"""
    def __init__(self, cat='All'):
        self._cat = cat

    def AllowElement(self, el):
        want_wall = self._cat in ('All', 'Wall')
        want_col  = self._cat in ('All', 'Column')
        if want_wall and isinstance(el, DB.Wall):
            return True
        if want_col and isinstance(el, DB.FamilyInstance):
            try:
                cat = el.Category
                if cat:
                    bic = cat.Id.IntegerValue
                    return bic in [
                        int(DB.BuiltInCategory.OST_StructuralColumns),
                        int(DB.BuiltInCategory.OST_Columns),
                    ]
            except Exception:
                pass
        return False

    def AllowReference(self, ref, pt):
        return False


# ═══════════════════════════════════════════════════════════
#  JOIN HELPER
# ═══════════════════════════════════════════════════════════

def join_segments(doc, original_id, new_ids):
    """Join only the segments produced by this split:
    original (seg 0) ↔ new_ids[0], new_ids[0] ↔ new_ids[1], ...
    Errors are swallowed silently to avoid noise from geometry edge cases.
    """
    all_ids = [original_id] + list(new_ids)
    for i in range(len(all_ids) - 1):
        try:
            a = doc.GetElement(all_ids[i])
            b = doc.GetElement(all_ids[i + 1])
            if a is None or b is None:
                continue
            if not DB.JoinGeometryUtils.AreElementsJoined(doc, a, b):
                DB.JoinGeometryUtils.JoinGeometry(doc, a, b)
        except Exception:
            pass   # geometry edge cases — skip silently


# ═══════════════════════════════════════════════════════════
#  ENTRY POINT  (intent + while True loop)
# ═══════════════════════════════════════════════════════════

def main():
    try:
        doc           = revit.doc
        sorted_levels = get_levels(doc)

        if len(sorted_levels) < 2:
            forms.alert(u'At least 2 levels required.', title=u'Split by Level')
            return

        # Pre-populate from current Revit selection (walls/columns only)
        items = []
        try:
            pre_sel_ids = revit.uidoc.Selection.GetElementIds()
            if pre_sel_ids and pre_sel_ids.Count > 0:
                pre_elems = [doc.GetElement(eid) for eid in pre_sel_ids]
                pre_elems = [e for e in pre_elems
                             if e is not None and isinstance(e, (DB.Wall, DB.FamilyInstance))]
                if pre_elems:
                    items = analyze_elements(pre_elems, doc, sorted_levels)
        except Exception:
            items = []

        # ── Step 1 loop ─────────────────────────────────────
        s1 = SelectElementsForm(items, sorted_levels, doc)
        pending_t = [None]   # mutable ref to the open Transaction (if any)

        def _rollback_pending():
            t = pending_t[0]
            if t is not None and t.GetStatus() == DB.TransactionStatus.Started:
                t.RollBack()
            pending_t[0] = None

        while True:
            s1.ShowDialog()
            action1  = s1._pending_action
            cat_pick = s1._cat_filter

            # ── X (close) — rollback any pending transaction ──
            if action1 is None:
                _rollback_pending()
                break

            # ── OK — commit the pending transaction ──────────
            if action1 == 'ok':
                t = pending_t[0]
                if t is not None and t.GetStatus() == DB.TransactionStatus.Started:
                    t.Commit()
                pending_t[0] = None
                break

            # ── Pick / Add — rollback first, then re-pick ────
            if action1 in ('pick', 'add'):
                _rollback_pending()
                hint = {
                    'All':    u'Select Walls / Columns — press Finish when done',
                    'Wall':   u'Select Walls — press Finish when done',
                    'Column': u'Select Columns — press Finish when done',
                }.get(cat_pick, u'Select elements — press Finish when done')
                try:
                    refs = revit.uidoc.Selection.PickObjects(
                        RvtSelection.ObjectType.Element,
                        _WallColumnFilter(cat_pick),
                        hint)
                    new_elems = [doc.GetElement(r.ElementId) for r in refs]
                except Exception:
                    new_elems = []

                if not new_elems:
                    continue

                new_items = analyze_elements(new_elems, doc, sorted_levels)
                if action1 == 'pick':
                    items = new_items
                else:
                    existing_ids = {i['id'] for i in items}
                    items = items + [i for i in new_items if i['id'] not in existing_ids]
                s1 = SelectElementsForm(items, sorted_levels, doc)
                continue

            # ── Analyze → Step 2 ─────────────────────────────
            if action1 == 'analyze':
                # Rollback any previous staged transaction before opening a new one
                _rollback_pending()

                # Open the Transaction that will stay open until OK or X in Step 1
                t = DB.Transaction(doc, u'Split Wall/Column by Level')
                t.Start()
                pending_t[0] = t

                while True:
                    s2 = AnalyzeLevelsForm(s1.selected_items, sorted_levels, doc)
                    s2.ShowDialog()
                    action2 = s2._pending_action

                    if action2 == 'back':
                        # Rollback staged work, rebuild Step 1 fresh
                        _rollback_pending()
                        s1 = SelectElementsForm(items, sorted_levels, doc)
                        break

                    if action2 == 'done':
                        # Transaction still open — propagate status, rebuild Step 1
                        done_map = {i['id']: i['status'] for i in s2.items}
                        for i in items:
                            if i['id'] in done_map:
                                i['status'] = done_map[i['id']]
                        s1 = SelectElementsForm(items, sorted_levels, doc)
                        s1.MarkSplitExecuted()
                        break

                    # X on Step 2 — rollback, rebuild Step 1 fresh
                    _rollback_pending()
                    s1 = SelectElementsForm(items, sorted_levels, doc)
                    break

    except Exception as ex:
        forms.alert(u'Error:\n{}\n\n{}'.format(str(ex), traceback.format_exc()),
                    title=u'Split by Level')


if __name__ == '__main__':
    main()
