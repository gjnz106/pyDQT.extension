# -*- coding: utf-8 -*-
"""Snap to Grid v19 - Round wall/column/beam distances to nearest gridline.

Apply ALIGNS the element onto the rounded grid line by setting its Location to
the exact computed position - not a relative move, so no residual accumulates.
A column is aligned by its CENTRE-LINE reference - the family's Center
(Left/Right) and Center (Front/Back) reference planes, which is exactly what a
centre-line dimension snaps to (not the insertion point, nor the solid
centroid). A wall's centerline is projected onto its rounded line. Beams fall
back to a measure / move / regenerate loop.

Apply can also draw a 2D detail line at the rounded distance (parallel to the
grid) and align the element exactly onto it, giving a visible reference to
verify the snap. Toggle with the "Draw rounded line" checkbox.

Distances are measured and rounded to the element CENTERLINE (the way the
dimensions are taken), so snapping a wall/column never leaves the centerline
dimension fractional by rounding a face instead.

When an element is snapped to two grids at once (e.g. a column at a grid
intersection) the combined move is solved as a 2x2 system, so both dimensions
land on a whole number even when the grids are not exactly perpendicular -
instead of the two independent moves being summed and leaving a small residual.

Scope option - scan all elements or only current selection.

Copyright (c) 2026 by Dang Quoc Truong (DQT)
"""

__title__ = "Snap to\nGrid"
__author__ = "DQT"
__doc__ = "Round wall/column/beam centerline offset from grid to whole mm"

import clr
import math

clr.AddReference("System")
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")
for _asm in ("System.Data", "System.Data.Common"):
    try:
        clr.AddReference(_asm)
    except Exception:
        pass

from System.IO import MemoryStream
from System.Text import Encoding
from System.Windows.Markup import XamlReader
from System.Data import DataTable
from System.Collections.Generic import List
from collections import OrderedDict

import Autodesk.Revit.DB as DB
from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, Transaction,
    XYZ, ElementId, Grid, Wall, FamilyInstance, Line,
    LocationCurve, LocationPoint, ElementTransformUtils,
    Options, Solid, GeometryInstance, ViewDetailLevel,
    FamilyInstanceReferenceType, PlanarFace,
)
from Autodesk.Revit.UI import TaskDialog

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

FEET_TO_MM = 304.8
SNAP_TOL = 0.0001
CONV_TOL = 1.0e-7   # ft (~3e-5 mm) - convergence target when aligning
MAX_ITER = 8        # re-measure / move passes per element


def get_id_value(eid):
    try:
        return eid.IntegerValue
    except:
        return eid.Value


def round_to(v, p):
    if p <= 0:
        return v
    return round(v / p) * p


def line_dir_2d(p0, p1):
    dx, dy = p1.X - p0.X, p1.Y - p0.Y
    ln = math.sqrt(dx * dx + dy * dy)
    if ln < 1e-12:
        return None
    return XYZ(dx / ln, dy / ln, 0)


def is_parallel(d1, d2):
    if d1 is None or d2 is None:
        return False
    return abs(d1.X * d2.X + d1.Y * d2.Y) >= math.cos(math.radians(5.0))


def is_perpendicular(d1, d2):
    if d1 is None or d2 is None:
        return False
    return abs(d1.X * d2.X + d1.Y * d2.Y) <= math.sin(math.radians(5.0))


def signed_perp(origin, direction, point):
    vx = point.X - origin.X
    vy = point.Y - origin.Y
    return vx * direction.Y - vy * direction.X


def group_grids_by_direction(grids_info):
    groups = []
    for g, go, gd in grids_info:
        placed = False
        for group in groups:
            if is_parallel(group[0][2], gd):
                group.append((g, go, gd))
                placed = True
                break
        if not placed:
            groups.append([(g, go, gd)])
    return groups


def calc_snap(sc, half_w, grid_dir, precision):
    perp = XYZ(grid_dir.Y, -grid_dir.X, 0)
    s = 1.0 if sc >= 0 else -1.0
    center_mm = abs(sc) * FEET_TO_MM

    if half_w > 0:
        nf_signed = sc - s * half_w
        ff_signed = sc + s * half_w
        nf_mm = abs(nf_signed) * FEET_TO_MM
        ff_mm = abs(ff_signed) * FEET_TO_MM

        candidates = []
        for ref_signed, ref_mm in [(nf_signed, nf_mm),
                                    (ff_signed, ff_mm),
                                    (sc, center_mm)]:
            target_mm = round_to(ref_mm, precision)
            delta = target_mm - ref_mm
            if abs(delta) >= SNAP_TOL:
                candidates.append((ref_mm, target_mm, delta, ref_signed))

        if not candidates:
            return None

        candidates.sort(key=lambda c: abs(c[2]))
        shown_mm, snapped_mm, delta_mm, ref_signed = candidates[0]

        s_ref = 1.0 if ref_signed >= 0 else -1.0
        target_ref = s_ref * (snapped_mm / FEET_TO_MM)
        offset = ref_signed - sc
        target_sc = target_ref - offset
        move_ft = target_sc - sc
    else:
        target_mm = round_to(center_mm, precision)
        delta_mm = target_mm - center_mm
        if abs(delta_mm) < SNAP_TOL:
            return None
        shown_mm = center_mm
        snapped_mm = target_mm
        target_sc = s * (target_mm / FEET_TO_MM)
        move_ft = target_sc - sc

    move_vec = XYZ(perp.X * move_ft, perp.Y * move_ft, 0)
    return (shown_mm, snapped_mm, delta_mm, move_vec)


def calc_snap_endpoint(endpoint, grid_origin, grid_dir, precision):
    sd = signed_perp(grid_origin, grid_dir, endpoint)
    dist_mm = abs(sd) * FEET_TO_MM
    target_mm = round_to(dist_mm, precision)
    delta_mm = target_mm - dist_mm

    if abs(delta_mm) < SNAP_TOL:
        return None

    perp = XYZ(grid_dir.Y, -grid_dir.X, 0)
    s = 1.0 if sd >= 0 else -1.0
    target_sd = s * (target_mm / FEET_TO_MM)
    move_ft = target_sd - sd
    move_vec = XYZ(perp.X * move_ft, perp.Y * move_ft, 0)
    return (dist_mm, target_mm, delta_mm, move_vec)


# ==============================================================================
# ANALYSIS
# ==============================================================================
def analyze_wall(elem, grids_info, precision):
    loc = elem.Location
    if not isinstance(loc, LocationCurve):
        return []
    curve = loc.Curve
    mid = curve.Evaluate(0.5, True)
    elem_dir = line_dir_2d(curve.GetEndPoint(0), curve.GetEndPoint(1))
    if elem_dir is None:
        return []

    best_sd = None
    best_gdir = None
    best_go = None
    best_gname = ""
    best_abs = float("inf")
    for g, go, gd in grids_info:
        if not is_parallel(elem_dir, gd):
            continue
        sd = signed_perp(go, gd, mid)
        if abs(sd) < best_abs:
            best_abs = abs(sd)
            best_sd = sd
            best_gdir = gd
            best_go = go
            try:
                best_gname = DB.Element.Name.GetValue(g)
            except:
                best_gname = "?"
    if best_gdir is None:
        return []
    # Snap the wall CENTERLINE distance to the grid (dimensions are taken to
    # the centerline). half_w = 0 so a face is never rounded instead.
    r = calc_snap(best_sd, 0.0, best_gdir, precision)
    if not r:
        return []
    shown, snapped, delta, mv = r
    return [(best_gname, shown, snapped, delta, mv, best_go, best_gdir)]


def analyze_beam(elem, grids_info, precision):
    loc = elem.Location
    if not isinstance(loc, LocationCurve):
        return []
    curve = loc.Curve
    mid = curve.Evaluate(0.5, True)
    p0 = curve.GetEndPoint(0)
    p1 = curve.GetEndPoint(1)
    elem_dir = line_dir_2d(p0, p1)
    if elem_dir is None:
        return []
    results = []

    # 1) Nearest parallel grid - snap the beam CENTERLINE (half_w = 0).
    best_sd = None
    best_gdir = None
    best_go = None
    best_gname = ""
    best_abs = float("inf")
    for g, go, gd in grids_info:
        if not is_parallel(elem_dir, gd):
            continue
        sd = signed_perp(go, gd, mid)
        if abs(sd) < best_abs:
            best_abs = abs(sd)
            best_sd = sd
            best_gdir = gd
            best_go = go
            try:
                best_gname = DB.Element.Name.GetValue(g)
            except:
                best_gname = "?"
    if best_gdir is not None and best_sd is not None:
        r = calc_snap(best_sd, 0.0, best_gdir, precision)
        if r:
            shown, snapped, delta, mv = r
            results.append((best_gname, shown, snapped, delta, mv,
                            best_go, best_gdir))

    # 2) Perpendicular grids - nearest endpoint
    perp_grids = [(g, go, gd) for g, go, gd in grids_info
                  if is_perpendicular(elem_dir, gd)]
    if perp_grids:
        perp_groups = group_grids_by_direction(perp_grids)
        for group in perp_groups:
            best_ep = None
            best_ep_gdir = None
            best_ep_gname = ""
            best_ep_go = None
            best_ep_abs = float("inf")
            for g, go, gd in group:
                for ep in [p0, p1]:
                    sd = signed_perp(go, gd, ep)
                    if abs(sd) < best_ep_abs:
                        best_ep_abs = abs(sd)
                        best_ep = ep
                        best_ep_gdir = gd
                        best_ep_go = go
                        try:
                            best_ep_gname = DB.Element.Name.GetValue(g)
                        except:
                            best_ep_gname = "?"
            if best_ep is not None and best_ep_gdir is not None:
                r = calc_snap_endpoint(best_ep, best_ep_go,
                                       best_ep_gdir, precision)
                if r:
                    shown, snapped, delta, mv = r
                    results.append((best_ep_gname, shown, snapped, delta, mv,
                                    best_ep_go, best_ep_gdir))
    return results


def analyze_column(elem, grids_info, precision):
    loc = elem.Location
    if isinstance(loc, LocationPoint):
        pt = loc.Point
    elif isinstance(loc, LocationCurve):
        pt = loc.Curve.Evaluate(0.5, True)
    else:
        return []

    # A column sits at a grid intersection, so it only makes sense to snap it
    # to the NEAREST grid in each of the (up to two) principal directions - not
    # to every grid in the project. Otherwise one column produces dozens of
    # rows (incl. grids tens of metres away) and the per-element move-summing in
    # Apply would push the column off its position.
    dists = []
    for g, go, gd in grids_info:
        sd = signed_perp(go, gd, pt)
        try:
            gname = DB.Element.Name.GetValue(g)
        except:
            gname = "?"
        dists.append((abs(sd), sd, go, gd, gname))
    if not dists:
        return []
    dists.sort(key=lambda d: d[0])

    chosen = []          # (sd, go, gd, gname) - nearest grid per direction
    chosen_dirs = []
    for _, sd, go, gd, gname in dists:
        if any(is_parallel(gd, cg) for cg in chosen_dirs):
            continue
        chosen.append((sd, go, gd, gname))
        chosen_dirs.append(gd)
        if len(chosen) >= 2:
            break

    results = []
    for sd, go, gd, gname in chosen:
        r = calc_snap(sd, 0.0, gd, precision)
        if r:
            shown, snapped, delta, mv = r
            results.append((gname, shown, snapped, delta, mv, go, gd))
    return results


# ==============================================================================
# CATEGORY BIC SETS
# ==============================================================================
WALL_BICS = [BuiltInCategory.OST_Walls]
BEAM_BICS = [BuiltInCategory.OST_StructuralFraming]
COL_BICS = [BuiltInCategory.OST_Columns, BuiltInCategory.OST_StructuralColumns]

ALL_BICS = WALL_BICS + BEAM_BICS + COL_BICS


# ==============================================================================
# XAML
# ==============================================================================
XAML_STR = """
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="DQT - Snap to Grid"
    Width="880" Height="580"
    WindowStartupLocation="CenterScreen"
    ResizeMode="CanResizeWithGrip"
    Background="%%BG%%">
    <Window.Resources>
        <Style x:Key="BtnP" TargetType="Button">
            <Setter Property="Background" Value="%%HD%%"/>
            <Setter Property="Foreground" Value="%%DK%%"/>
            <Setter Property="FontWeight" Value="Bold"/>
            <Setter Property="FontSize" Value="13"/>
            <Setter Property="Padding" Value="16,8"/>
            <Setter Property="BorderBrush" Value="%%AC%%"/>
            <Setter Property="BorderThickness" Value="1"/>
            <Setter Property="Cursor" Value="Hand"/>
        </Style>
        <Style x:Key="BtnS" TargetType="Button">
            <Setter Property="Background" Value="White"/>
            <Setter Property="Foreground" Value="%%DK%%"/>
            <Setter Property="FontSize" Value="12"/>
            <Setter Property="Padding" Value="12,6"/>
            <Setter Property="BorderBrush" Value="%%AC%%"/>
            <Setter Property="BorderThickness" Value="1"/>
            <Setter Property="Cursor" Value="Hand"/>
        </Style>
    </Window.Resources>
    <Grid>
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <!-- HEADER -->
        <Border Grid.Row="0" Background="%%HD%%" Padding="16,10">
            <StackPanel>
                <TextBlock Text="Snap to Grid" FontSize="18" FontWeight="Bold" Foreground="%%DK%%"/>
                <TextBlock Text="Round element distances to gridlines (Walls, Columns, Beams)" FontSize="11" Foreground="%%DK%%" Opacity="0.7"/>
            </StackPanel>
        </Border>

        <!-- OPTIONS -->
        <Border Grid.Row="1" Background="White" Padding="16,8" BorderBrush="%%AC%%" BorderThickness="0,0,0,1">
            <Grid>
                <Grid.RowDefinitions>
                    <RowDefinition Height="Auto"/>
                </Grid.RowDefinitions>
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="Auto"/>
                </Grid.ColumnDefinitions>

                <TextBlock Grid.Column="0" Text="Scope:" VerticalAlignment="Center" Margin="0,0,6,0" Foreground="%%DK%%"/>
                <ComboBox x:Name="cmbScope" Grid.Column="1" Width="140" Margin="0,0,12,0" SelectedIndex="0">
                    <ComboBoxItem Content="Entire Project"/>
                    <ComboBoxItem Content="Current Selection"/>
                </ComboBox>

                <TextBlock Grid.Column="2" Text="Category:" VerticalAlignment="Center" Margin="0,0,6,0" Foreground="%%DK%%"/>
                <ComboBox x:Name="cmbCat" Grid.Column="3" Width="175" Margin="0,0,12,0" SelectedIndex="0">
                    <ComboBoxItem Content="All (Walls+Columns+Beams)"/>
                    <ComboBoxItem Content="Walls Only"/>
                    <ComboBoxItem Content="Columns Only"/>
                    <ComboBoxItem Content="Beams Only"/>
                    <ComboBoxItem Content="Walls + Columns"/>
                    <ComboBoxItem Content="Walls + Beams"/>
                    <ComboBoxItem Content="Columns + Beams"/>
                </ComboBox>

                <TextBlock Grid.Column="4" Text="Round:" VerticalAlignment="Center" Margin="0,0,6,0" Foreground="%%DK%%"/>
                <ComboBox x:Name="cmbPrec" Grid.Column="5" Width="80" Margin="0,0,12,0" SelectedIndex="0">
                    <ComboBoxItem Content="1 mm"/>
                    <ComboBoxItem Content="0.5 mm"/>
                    <ComboBoxItem Content="5 mm"/>
                    <ComboBoxItem Content="10 mm"/>
                </ComboBox>

                <TextBlock Grid.Column="7" Text="Max:" VerticalAlignment="Center" Margin="0,0,6,0" Foreground="%%DK%%"/>
                <ComboBox x:Name="cmbMax" Grid.Column="8" Width="80" SelectedIndex="2">
                    <ComboBoxItem Content="0.1 mm"/>
                    <ComboBoxItem Content="0.5 mm"/>
                    <ComboBoxItem Content="1 mm"/>
                    <ComboBoxItem Content="2 mm"/>
                    <ComboBoxItem Content="5 mm"/>
                    <ComboBoxItem Content="No limit"/>
                </ComboBox>
            </Grid>
        </Border>

        <!-- DATAGRID -->
        <DataGrid x:Name="dg" Grid.Row="2" Margin="10,8,10,4"
            AutoGenerateColumns="True" IsReadOnly="True" CanUserSortColumns="True"
            SelectionMode="Extended" GridLinesVisibility="Horizontal"
            HeadersVisibility="Column" BorderBrush="%%AC%%" BorderThickness="1"
            RowHeight="26" FontSize="12" AlternatingRowBackground="#FFF8F0"/>

        <!-- STATUS -->
        <Border Grid.Row="3" Padding="12,4" Background="White">
            <Grid>
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="Auto"/>
                </Grid.ColumnDefinitions>
                <TextBlock x:Name="txtSt" Grid.Column="0" Text="Click Scan." FontSize="11" Foreground="%%DK%%" VerticalAlignment="Center"/>
                <StackPanel Grid.Column="1" Orientation="Horizontal">
                    <CheckBox x:Name="chkLine" Content="Draw rounded line" VerticalAlignment="Center" Margin="0,0,16,0" IsChecked="True"/>
                    <CheckBox x:Name="chkAll" Content="Select All" VerticalAlignment="Center" Margin="0,0,16,0" IsChecked="True"/>
                </StackPanel>
            </Grid>
        </Border>

        <!-- BUTTONS -->
        <Border Grid.Row="4" Background="White" Padding="12,8" BorderBrush="%%AC%%" BorderThickness="0,1,0,0">
            <Grid>
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="Auto"/>
                </Grid.ColumnDefinitions>
                <Button x:Name="btnScan" Grid.Column="0" Content="Scan" Style="{StaticResource BtnS}" Margin="0,0,8,0"/>
                <Button x:Name="btnHL" Grid.Column="1" Content="Highlight Selected" Style="{StaticResource BtnS}"/>
                <Button x:Name="btnApply" Grid.Column="3" Content="Apply Snap" Style="{StaticResource BtnP}" Margin="0,0,8,0"/>
                <Button x:Name="btnClose" Grid.Column="4" Content="Close" Style="{StaticResource BtnS}"/>
            </Grid>
        </Border>
    </Grid>
</Window>
"""


class SI(object):
    def __init__(self, eid, cat, ft, gn, dist, snap, delta, lv, mv,
                 go=None, gd=None):
        self.sel = True
        self.eid = eid
        self.cat = cat
        self.ft = ft
        self.gn = gn
        self.dist = dist
        self.snap = snap
        self.delta = delta
        self.lv = lv
        self.mv = mv
        self.go = go    # a point on the grid this row snaps to
        self.gd = gd    # the grid's unit direction


class MainWin(object):
    CAT_MAP = {
        0: {"walls": True,  "columns": True,  "beams": True},
        1: {"walls": True,  "columns": False, "beams": False},
        2: {"walls": False, "columns": True,  "beams": False},
        3: {"walls": False, "columns": False, "beams": True},
        4: {"walls": True,  "columns": True,  "beams": False},
        5: {"walls": True,  "columns": False, "beams": True},
        6: {"walls": False, "columns": True,  "beams": True},
    }

    def __init__(self):
        self.items = []
        x = XAML_STR.replace("%%HD%%", "#F0CC88").replace("%%BG%%", "#FEF8E7")
        x = x.replace("%%AC%%", "#D4B87A").replace("%%DK%%", "#5D4E37")
        self.w = XamlReader.Load(MemoryStream(Encoding.UTF8.GetBytes(x)))
        self.cmbScope = self.w.FindName("cmbScope")
        self.cmbCat = self.w.FindName("cmbCat")
        self.cmbPrec = self.w.FindName("cmbPrec")
        self.cmbMax = self.w.FindName("cmbMax")
        self.dg = self.w.FindName("dg")
        self.txtSt = self.w.FindName("txtSt")
        self.chkLine = self.w.FindName("chkLine")
        self.w.FindName("btnScan").Click += self._scan
        self.w.FindName("btnHL").Click += self._hl
        self.w.FindName("btnApply").Click += self._apply
        self.w.FindName("btnClose").Click += lambda s, e: self.w.Close()
        self.w.FindName("chkAll").Checked += lambda s, e: self._tog(True)
        self.w.FindName("chkAll").Unchecked += lambda s, e: self._tog(False)

        # Auto-detect: if elements are pre-selected, switch to Current Selection
        sel_ids = uidoc.Selection.GetElementIds()
        if sel_ids.Count > 0:
            self.cmbScope.SelectedIndex = 1

    def _prec(self):
        return [1.0, 0.5, 5.0, 10.0][self.cmbPrec.SelectedIndex]

    def _mm(self):
        return [0.1, 0.5, 1.0, 2.0, 5.0, 999999.0][self.cmbMax.SelectedIndex]

    def _get_cats(self):
        return self.CAT_MAP.get(self.cmbCat.SelectedIndex,
                                 {"walls": True, "columns": True, "beams": True})

    def _lv(self, e):
        for b in [DB.BuiltInParameter.WALL_BASE_CONSTRAINT,
                   DB.BuiltInParameter.FAMILY_LEVEL_PARAM,
                   DB.BuiltInParameter.SCHEDULE_LEVEL_PARAM,
                   DB.BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM]:
            try:
                p = e.get_Parameter(b)
                if p and p.HasValue:
                    l = doc.GetElement(p.AsElementId())
                    if l:
                        return DB.Element.Name.GetValue(l)
            except:
                pass
        return "-"

    def _ft(self, e):
        try:
            t = doc.GetElement(e.GetTypeId())
            if t:
                fn = ""
                try:
                    fn = t.FamilyName
                except:
                    pass
                tn = DB.Element.Name.GetValue(t)
                return (fn + " : " + tn) if fn else tn
        except:
            pass
        return "-"

    def _collect_all(self, bic):
        return list(FilteredElementCollector(doc)
                    .OfCategory(bic)
                    .WhereElementIsNotElementType()
                    .ToElements())

    def _is_wall_bic(self, elem):
        try:
            cat_id = get_id_value(elem.Category.Id)
            return cat_id == get_id_value(
                DB.Category.GetCategory(doc, BuiltInCategory.OST_Walls).Id)
        except:
            return isinstance(elem, Wall)

    def _is_beam_bic(self, elem):
        try:
            cat_id = get_id_value(elem.Category.Id)
            return cat_id == get_id_value(
                DB.Category.GetCategory(doc, BuiltInCategory.OST_StructuralFraming).Id)
        except:
            return False

    def _is_column_bic(self, elem):
        try:
            cat_id = get_id_value(elem.Category.Id)
            col_id = get_id_value(
                DB.Category.GetCategory(doc, BuiltInCategory.OST_Columns).Id)
            scol_id = get_id_value(
                DB.Category.GetCategory(doc, BuiltInCategory.OST_StructuralColumns).Id)
            return cat_id == col_id or cat_id == scol_id
        except:
            return False

    def _get_elements(self, cats):
        """Get elements based on scope and category filter."""
        use_selection = (self.cmbScope.SelectedIndex == 1)

        walls = []
        beams = []
        columns = []

        if use_selection:
            sel_ids = uidoc.Selection.GetElementIds()
            if sel_ids.Count == 0:
                return walls, beams, columns

            for eid in sel_ids:
                elem = doc.GetElement(eid)
                if elem is None or elem.Location is None:
                    continue
                if cats["walls"] and self._is_wall_bic(elem):
                    walls.append(elem)
                elif cats["beams"] and self._is_beam_bic(elem):
                    beams.append(elem)
                elif cats["columns"] and self._is_column_bic(elem):
                    columns.append(elem)
        else:
            if cats["walls"]:
                walls = [e for e in self._collect_all(BuiltInCategory.OST_Walls)
                         if e.Location]
            if cats["beams"]:
                beams = [e for e in self._collect_all(BuiltInCategory.OST_StructuralFraming)
                         if e.Location]
            if cats["columns"]:
                for bic in [BuiltInCategory.OST_Columns,
                            BuiltInCategory.OST_StructuralColumns]:
                    columns.extend([e for e in self._collect_all(bic) if e.Location])

        return walls, beams, columns

    def _scan(self, s, a):
        self.items = []
        pr = self._prec()
        mx = self._mm()
        cats = self._get_cats()

        grids_info = []
        for g in FilteredElementCollector(doc).OfClass(Grid).WhereElementIsNotElementType().ToElements():
            try:
                c = g.Curve
                d = line_dir_2d(c.GetEndPoint(0), c.GetEndPoint(1))
                if d:
                    grids_info.append((g, c.GetEndPoint(0), d))
            except:
                pass

        if not grids_info:
            self.txtSt.Text = "No grids found."
            return

        walls, beams, columns = self._get_elements(cats)
        ns = len(walls) + len(beams) + len(columns)

        if ns == 0:
            scope_name = "selection" if self.cmbScope.SelectedIndex == 1 else "project"
            self.txtSt.Text = "No matching elements in {}.".format(scope_name)
            return

        ni = 0

        for e in walls:
            for gn, dist, snap, delta, mv, go, gd in analyze_wall(
                    e, grids_info, pr):
                if abs(delta) > mx:
                    continue
                ni += 1
                cn = "Walls"
                try:
                    cn = e.Category.Name
                except:
                    pass
                self.items.append(SI(get_id_value(e.Id), cn, self._ft(e),
                                     gn, dist, snap, delta, self._lv(e), mv,
                                     go, gd))

        for e in beams:
            for gn, dist, snap, delta, mv, go, gd in analyze_beam(
                    e, grids_info, pr):
                if abs(delta) > mx:
                    continue
                ni += 1
                cn = "Structural Framing"
                try:
                    cn = e.Category.Name
                except:
                    pass
                self.items.append(SI(get_id_value(e.Id), cn, self._ft(e),
                                     gn, dist, snap, delta, self._lv(e), mv,
                                     go, gd))

        for e in columns:
            for gn, dist, snap, delta, mv, go, gd in analyze_column(
                    e, grids_info, pr):
                if abs(delta) > mx:
                    continue
                ni += 1
                cn = "Columns"
                try:
                    cn = e.Category.Name
                except:
                    pass
                self.items.append(SI(get_id_value(e.Id), cn, self._ft(e),
                                     gn, dist, snap, delta, self._lv(e), mv,
                                     go, gd))

        self._ref()
        scope_name = "selected" if self.cmbScope.SelectedIndex == 1 else "total"
        self.txtSt.Text = ("Scanned {} element(s) ({}). "
                           "Found {} grid distance(s) to round.").format(
            ns, scope_name, ni)

    def _ref(self):
        dt = DataTable()
        for c in ["Sel", "ID", "Category", "Family : Type", "Grid",
                   "Dist (mm)", "Snap (mm)", "Move (mm)", "Level"]:
            dt.Columns.Add(c)
        for i in self.items:
            r = dt.NewRow()
            r["Sel"] = "V" if i.sel else ""
            r["ID"] = str(i.eid)
            r["Category"] = i.cat
            r["Family : Type"] = i.ft
            r["Grid"] = i.gn
            r["Dist (mm)"] = str(round(i.dist, 3))
            r["Snap (mm)"] = str(round(i.snap, 3))
            r["Move (mm)"] = str(round(i.delta, 4))
            r["Level"] = i.lv
            dt.Rows.Add(r)
        self.dg.ItemsSource = dt.DefaultView

    def _hl(self, s, a):
        ids = List[ElementId]()
        for i in self.items:
            if i.sel:
                try:
                    ids.Add(ElementId(i.eid))
                except:
                    pass
        if ids.Count > 0:
            uidoc.Selection.SetElementIds(ids)
            self.txtSt.Text = "Highlighted {}.".format(ids.Count)

    def _solve_move(self, cons):
        """Find the single translation that satisfies every snap constraint
        for one element. Each constraint is (n, L): move . n = L, with n a unit
        direction. Two independent per-grid moves cannot just be added when the
        grids are not exactly perpendicular - that leaves a residual on each
        dimension (e.g. 2425.042 instead of 2425). With exactly two
        non-parallel constraints we solve the 2x2 system so both dimensions
        land on a whole number; otherwise we fall back to summation."""
        if len(cons) == 1:
            n, L = cons[0]
            return XYZ(n.X * L, n.Y * L, 0)
        if len(cons) >= 2:
            (n1, L1), (n2, L2) = cons[0], cons[1]
            a, b, c, d = n1.X, n1.Y, n2.X, n2.Y
            det = a * d - b * c
            if abs(det) > 1e-9:
                mx = (L1 * d - b * L2) / det
                my = (a * L2 - L1 * c) / det
                mv = XYZ(mx, my, 0)
                for n, L in cons[2:]:   # rare: 3+ constraints (some beams)
                    mv = XYZ(mv.X + n.X * L, mv.Y + n.Y * L, mv.Z)
                return mv
        mv = XYZ(0, 0, 0)
        for n, L in cons:
            mv = XYZ(mv.X + n.X * L, mv.Y + n.Y * L, mv.Z)
        return mv

    def _elem_point(self, e):
        loc = e.Location
        if isinstance(loc, LocationPoint):
            return loc.Point
        if isinstance(loc, LocationCurve):
            return loc.Curve.Evaluate(0.5, True)
        return None

    def _draw_ref_line(self, view, p, gdir):
        """Draw a 2D detail line through p, parallel to a grid (direction gdir),
        i.e. exactly on the rounded distance the element was aligned to. Guarded
        so it never breaks the snap (some view types reject detail curves)."""
        try:
            half = 6.0   # ft (~1.8 m each side)
            a = XYZ(p.X - gdir.X * half, p.Y - gdir.Y * half, p.Z)
            b = XYZ(p.X + gdir.X * half, p.Y + gdir.Y * half, p.Z)
            if a.DistanceTo(b) < 1e-6:
                return
            doc.Create.NewDetailCurve(view, Line.CreateBound(a, b))
        except:
            pass

    def _line_const(self, go, gd, p, tmm):
        """The rounded grid line as perp . X = c (perp unit), placed on the
        element's current side of the grid. Returns (perp, c)."""
        sd = signed_perp(go, gd, p)
        s = 1.0 if sd >= 0 else -1.0
        tgt = s * (tmm / FEET_TO_MM)
        perp = XYZ(gd.Y, -gd.X, 0)
        c = tgt + (perp.X * go.X + perp.Y * go.Y)
        return perp, c

    def _project_onto(self, pt, perp, c):
        """Perpendicular foot of pt on the line perp . X = c (perp unit)."""
        k = c - (perp.X * pt.X + perp.Y * pt.Y)
        return XYZ(pt.X + perp.X * k, pt.Y + perp.Y * k, pt.Z)

    def _iter_solids(self, geo):
        if geo is None:
            return
        for g in geo:
            if isinstance(g, Solid):
                if g.Volume > 1e-9:
                    yield g
            elif isinstance(g, GeometryInstance):
                for s in self._iter_solids(g.GetInstanceGeometry()):
                    yield s

    def _column_center(self, e):
        """Fallback centre when the family references can't be read: the NOMINAL
        geometric centre (mid-way between the extreme faces, from the solid's
        bounding box), not the volume-weighted centroid. The midplane between the
        faces is what the centre-line reference follows; the volume centroid is
        pulled off it by any asymmetric geometry."""
        try:
            opt = Options()
            opt.DetailLevel = ViewDetailLevel.Fine
            opt.ComputeReferences = False
            best = None
            bestv = 0.0
            for sol in self._iter_solids(e.get_Geometry(opt)):
                if sol.Volume > bestv:
                    bestv = sol.Volume
                    best = sol
            if best is not None:
                bb = best.GetBoundingBox()
                mid = XYZ((bb.Min.X + bb.Max.X) / 2.0,
                          (bb.Min.Y + bb.Max.Y) / 2.0,
                          (bb.Min.Z + bb.Max.Z) / 2.0)
                w = bb.Transform.OfPoint(mid)
                return XYZ(w.X, w.Y, 0.0)
        except:
            pass
        return None

    def _ref_point_dir(self, e, ref):
        """A point on, and the in-plan direction of, a family reference - or
        (None, None) if its geometry cannot be read."""
        try:
            obj = e.GetGeometryObjectFromReference(ref)
        except:
            obj = None
        if obj is None:
            return None, None
        if isinstance(obj, PlanarFace):
            o = obj.Origin
            n = obj.FaceNormal
            d = XYZ(-n.Y, n.X, 0)           # in-plan line dir = normal x Z
            return XYZ(o.X, o.Y, 0), d
        try:                                # Curve / Line reference
            a = obj.GetEndPoint(0)
            b = obj.GetEndPoint(1)
            return XYZ(a.X, a.Y, 0), XYZ(b.X - a.X, b.Y - a.Y, 0)
        except:
            return None, None

    def _column_ref_lines(self, e):
        """In-plan lines (point, unit dir) of the column's centre-line
        references: Center (Left/Right) and Center (Front/Back). These are the
        planes a centre-line dimension actually snaps to."""
        out = []
        for rt in (FamilyInstanceReferenceType.CenterLeftRight,
                   FamilyInstanceReferenceType.CenterFrontBack):
            try:
                refs = e.GetReferences(rt)
            except:
                refs = None
            if not refs:
                continue
            for r in refs:
                p, d = self._ref_point_dir(e, r)
                if p is None or d is None:
                    continue
                ln = (d.X * d.X + d.Y * d.Y) ** 0.5
                if ln < 1e-9:
                    continue
                out.append((p, XYZ(d.X / ln, d.Y / ln, 0)))
                break                        # one line per reference type
        return out

    def _column_ref_center(self, e):
        """The point where the two centre-line reference planes cross (it lies
        on both planes, so it carries the exact centre-line distance to any
        grid). Falls back to a single reference point, else None."""
        lines = self._column_ref_lines(e)
        if len(lines) >= 2:
            (p1, d1), (p2, d2) = lines[0], lines[1]
            a, b = d1.X, -d2.X
            c, dd = d1.Y, -d2.Y
            det = a * dd - b * c
            if abs(det) > 1e-9:
                ex = p2.X - p1.X
                ey = p2.Y - p1.Y
                t = (ex * dd - b * ey) / det
                return XYZ(p1.X + d1.X * t, p1.Y + d1.Y * t, 0)
        if len(lines) == 1:
            return lines[0][0]
        return None

    def _align_element(self, eid, glist):
        """Align an element ONTO its rounded grid line(s) by setting its
        Location to the exact computed position - not a relative move, so no
        residual accumulates. A column is placed at the exact intersection of
        its two rounded lines; a wall's centerline is projected onto its rounded
        line. Beams / other curve-driven elements fall back to a measure-move-
        regenerate loop. Returns the element's final point."""
        e = doc.GetElement(eid)
        if e is None:
            return None
        loc = e.Location

        # Column (and any point-located element): align the family's CENTRE-LINE
        # REFERENCE (Center Left/Right + Front/Back), which is what a dimension
        # snaps to - not the insertion point and not the solid centroid, either
        # of which can sit slightly off the reference. Place that reference on
        # the rounded line(s), then shift the insertion point by the same vector.
        if isinstance(loc, LocationPoint):
            p = loc.Point
            ref = self._column_ref_center(e)
            if ref is None:
                ref = self._column_center(e)
            if ref is None:
                ref = p
            try:
                target = None
                if len(glist) >= 2:
                    p1, c1 = self._line_const(glist[0][0], glist[0][1], ref,
                                              glist[0][2])
                    p2, c2 = self._line_const(glist[1][0], glist[1][1], ref,
                                              glist[1][2])
                    det = p1.X * p2.Y - p1.Y * p2.X
                    if abs(det) > 1e-9:
                        x = (c1 * p2.Y - p1.Y * c2) / det
                        y = (p1.X * c2 - c1 * p2.X) / det
                        target = XYZ(x, y, 0)
                else:
                    perp, c = self._line_const(glist[0][0], glist[0][1], ref,
                                               glist[0][2])
                    target = self._project_onto(ref, perp, c)
                if target is not None:
                    loc.Point = XYZ(p.X + (target.X - ref.X),
                                    p.Y + (target.Y - ref.Y), p.Z)
                    doc.Regenerate()
                    ne = doc.GetElement(eid)
                    newc = self._column_ref_center(ne)
                    if newc is None:
                        newc = self._column_center(ne)
                    if newc is not None:
                        return newc
                return self._elem_point(doc.GetElement(eid))
            except:
                pass   # fall back to the move loop below

        # Wall: project its centerline endpoints onto the rounded line.
        elif isinstance(e, Wall) and isinstance(loc, LocationCurve):
            try:
                cur = loc.Curve
                a = cur.GetEndPoint(0)
                b = cur.GetEndPoint(1)
                mid = cur.Evaluate(0.5, True)
                for go, gd, tmm in glist:
                    perp, c = self._line_const(go, gd, mid, tmm)
                    a = self._project_onto(a, perp, c)
                    b = self._project_onto(b, perp, c)
                    mid = self._project_onto(mid, perp, c)
                loc.Curve = Line.CreateBound(a, b)
                doc.Regenerate()
                return self._elem_point(doc.GetElement(eid))
            except:
                pass   # fall back to the move loop below

        # Fallback (beams, odd cases): closed-loop measure / move / regenerate.
        for _ in range(MAX_ITER):
            p = self._elem_point(e)
            if p is None:
                return None
            cons = []
            maxd = 0.0
            for go, gd, tmm in glist:
                sd = signed_perp(go, gd, p)
                s = 1.0 if sd >= 0 else -1.0
                tgt = s * (tmm / FEET_TO_MM)
                d = tgt - sd
                perp = XYZ(gd.Y, -gd.X, 0)
                cons.append((perp, d))
                if abs(d) > maxd:
                    maxd = abs(d)
            if maxd <= CONV_TOL:
                break
            ElementTransformUtils.MoveElement(doc, eid, self._solve_move(cons))
            doc.Regenerate()
        return self._elem_point(doc.GetElement(eid))

    def _apply(self, s, a):
        todo = [i for i in self.items if i.sel]
        if not todo:
            self.txtSt.Text = "Nothing selected."
            return

        # Group the grid constraints (origin, direction, rounded mm) per element.
        glist_by_id = OrderedDict()
        for i in todo:
            if i.go is None or i.gd is None:
                continue
            glist_by_id.setdefault(i.eid, []).append((i.go, i.gd, i.snap))

        view = doc.ActiveView
        draw = bool(self.chkLine.IsChecked)

        ok = fail = lines = 0
        t = Transaction(doc, "DQT - Snap to Grid")
        try:
            t.Start()
            for eid_int, glist in glist_by_id.items():
                try:
                    eid = ElementId(eid_int)
                    pf = self._align_element(eid, glist)
                    if pf is None:
                        fail += 1
                        continue
                    ok += 1
                    # Draw the rounded grid line(s) through the final position.
                    if draw:
                        for go, gd, tmm in glist:
                            self._draw_ref_line(view, pf, gd)
                            lines += 1
                except:
                    fail += 1
            t.Commit()
        except Exception as ex:
            if t.HasStarted():
                t.RollBack()
            self.txtSt.Text = "Err: " + str(ex)
            return

        self.items = [i for i in self.items if not i.sel]
        self._ref()
        msg = "Snapped {}.".format(ok)
        if draw and lines:
            msg += " Drew {} rounded line(s).".format(lines)
        if fail:
            msg += " {} failed.".format(fail)
        self.txtSt.Text = msg

    def _tog(self, v):
        for i in self.items:
            i.sel = v
        self._ref()

    def show(self):
        self.w.ShowDialog()


if __name__ == "__main__":
    try:
        MainWin().show()
    except Exception as e:
        TaskDialog.Show("DQT - Snap to Grid", str(e))