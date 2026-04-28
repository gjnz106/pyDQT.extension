# -*- coding: utf-8 -*-
"""Snap to Grid v10 - Round wall/column/beam distances to nearest gridline.

Line-based (wall/beam): checks ALL parallel grids, reports each with
fractional offset. Apply sums move vectors per element.
Point-based (column): checks nearest grid per direction group.

Copyright (c) 2026 by Dang Quoc Truong (DQT)
"""

__title__ = "Snap to\nGrid"
__author__ = "DQT"
__doc__ = "Round wall/column/beam offset from grid to whole millimeters"

import clr
import math

clr.AddReference("System")
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")
clr.AddReference("System.Xml")
clr.AddReference("System.Data")

from System.IO import MemoryStream
from System.Text import Encoding
from System.Windows.Markup import XamlReader
from System.Data import DataTable
from System.Collections.Generic import List
from collections import OrderedDict

import Autodesk.Revit.DB as DB
from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, Transaction,
    XYZ, ElementId, Grid, Wall, FamilyInstance,
    LocationCurve, LocationPoint, ElementTransformUtils,
)
from Autodesk.Revit.UI import TaskDialog

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

FEET_TO_MM = 304.8
SNAP_TOL = 0.0001


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


def get_line_elem_half_width(elem):
    """Get half-width for walls or beams."""
    if isinstance(elem, Wall):
        try:
            return doc.GetElement(elem.GetTypeId()).Width / 2.0
        except:
            return 0.0
    # Beam: try type parameters
    try:
        etype = doc.GetElement(elem.GetTypeId())
        if etype:
            for bip in [DB.BuiltInParameter.STRUCTURAL_SECTION_COMMON_WIDTH,
                        DB.BuiltInParameter.FAMILY_WIDTH_PARAM]:
                try:
                    p = etype.get_Parameter(bip)
                    if p and p.HasValue and p.AsDouble() > 0:
                        return p.AsDouble() / 2.0
                except:
                    pass
            # Try instance parameters on element itself
            for bip in [DB.BuiltInParameter.STRUCTURAL_SECTION_COMMON_WIDTH]:
                try:
                    p = elem.get_Parameter(bip)
                    if p and p.HasValue and p.AsDouble() > 0:
                        return p.AsDouble() / 2.0
                except:
                    pass
            # Try named parameters
            for name in ["b", "B", "Width", "W", "bf", "Bf", "d", "D"]:
                try:
                    p = etype.LookupParameter(name)
                    if p and p.HasValue and p.AsDouble() > 0:
                        return p.AsDouble() / 2.0
                except:
                    pass
    except:
        pass
    return 0.0


# ==============================================================================
# Single grid snap calculation (reusable)
# ==============================================================================
def calc_snap_for_grid(sc, half_w, grid_dir, precision):
    """
    Given signed center distance (sc, feet) and half_width (feet),
    compute snap result for one grid.

    Returns (shown_mm, snapped_mm, delta_mm, move_vec) or None.
    """
    perp = XYZ(grid_dir.Y, -grid_dir.X, 0)
    s = 1.0 if sc >= 0 else -1.0
    center_mm = abs(sc) * FEET_TO_MM

    if half_w > 0:
        nf_signed = sc - s * half_w
        ff_signed = sc + s * half_w
        nf_mm = abs(nf_signed) * FEET_TO_MM
        ff_mm = abs(ff_signed) * FEET_TO_MM

        candidates = []
        for label, ref_signed, ref_mm in [("NF", nf_signed, nf_mm),
                                            ("FF", ff_signed, ff_mm),
                                            ("C", sc, center_mm)]:
            target_mm = round_to(ref_mm, precision)
            delta = target_mm - ref_mm
            if abs(delta) >= SNAP_TOL:
                candidates.append((ref_mm, target_mm, delta, ref_signed))

        if not candidates:
            return None

        candidates.sort(key=lambda c: abs(c[2]))
        shown_mm, snapped_mm, delta_mm, ref_signed = candidates[0]

        s_ref = 1.0 if ref_signed >= 0 else -1.0
        target_ref_signed = s_ref * (snapped_mm / FEET_TO_MM)
        offset = ref_signed - sc
        target_sc = target_ref_signed - offset
        move_ft = target_sc - sc
    else:
        target_mm = round_to(center_mm, precision)
        delta_mm = target_mm - center_mm
        if abs(delta_mm) < SNAP_TOL:
            return None
        shown_mm = center_mm
        snapped_mm = target_mm
        s_c = 1.0 if sc >= 0 else -1.0
        target_sc = s_c * (target_mm / FEET_TO_MM)
        move_ft = target_sc - sc

    move_vec = XYZ(perp.X * move_ft, perp.Y * move_ft, 0)
    return (shown_mm, snapped_mm, delta_mm, move_vec)


# ==============================================================================
# ANALYSIS
# ==============================================================================
def analyze_line_elem(elem, grids_info, precision):
    """For walls/beams: check nearest parallel grid ONLY (one result).
    Move only towards nearest grid to avoid conflicts."""
    loc = elem.Location
    if not isinstance(loc, LocationCurve):
        return []

    curve = loc.Curve
    mid = curve.Evaluate(0.5, True)
    elem_dir = line_dir_2d(curve.GetEndPoint(0), curve.GetEndPoint(1))
    if elem_dir is None:
        return []

    half_w = get_line_elem_half_width(elem)

    # Find nearest parallel grid
    best_sd = None
    best_gdir = None
    best_gname = ""
    best_abs = float("inf")

    for g, go, gd in grids_info:
        if gd is None:
            continue
        if not is_parallel(elem_dir, gd):
            continue
        sd = signed_perp(go, gd, mid)
        if abs(sd) < best_abs:
            best_abs = abs(sd)
            best_sd = sd
            best_gdir = gd
            try:
                best_gname = DB.Element.Name.GetValue(g)
            except:
                best_gname = "?"

    if best_gdir is None or best_sd is None:
        return []

    result = calc_snap_for_grid(best_sd, half_w, best_gdir, precision)
    if result is None:
        return []

    shown_mm, snapped_mm, delta_mm, move_vec = result
    return [(best_gname, shown_mm, snapped_mm, delta_mm, move_vec)]


def analyze_column(elem, grid_groups, precision):
    """For columns: check nearest grid in each direction group."""
    loc = elem.Location
    if isinstance(loc, LocationPoint):
        pt = loc.Point
    elif isinstance(loc, LocationCurve):
        pt = loc.Curve.Evaluate(0.5, True)
    else:
        return []

    results = []
    for group in grid_groups:
        best_sd = None
        best_gdir = None
        best_gname = ""
        best_abs = float("inf")

        for g, go, gd in group:
            sd = signed_perp(go, gd, pt)
            if abs(sd) < best_abs:
                best_abs = abs(sd)
                best_sd = sd
                best_gdir = gd
                try:
                    best_gname = DB.Element.Name.GetValue(g)
                except:
                    best_gname = "?"

        if best_gdir is None or best_sd is None:
            continue

        result = calc_snap_for_grid(best_sd, 0.0, best_gdir, precision)
        if result is None:
            continue

        shown_mm, snapped_mm, delta_mm, move_vec = result
        results.append((best_gname, shown_mm, snapped_mm, delta_mm, move_vec))

    return results


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
        <Border Grid.Row="0" Background="%%HD%%" Padding="16,10">
            <StackPanel>
                <TextBlock Text="Snap to Grid" FontSize="18" FontWeight="Bold" Foreground="%%DK%%"/>
                <TextBlock Text="Round element distances to gridlines (Walls, Columns, Beams)" FontSize="11" Foreground="%%DK%%" Opacity="0.7"/>
            </StackPanel>
        </Border>
        <Border Grid.Row="1" Background="White" Padding="16,10" BorderBrush="%%AC%%" BorderThickness="0,0,0,1">
            <Grid>
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="Auto"/><ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="Auto"/><ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="Auto"/><ColumnDefinition Width="Auto"/>
                </Grid.ColumnDefinitions>
                <TextBlock Grid.Column="0" Text="Category:" VerticalAlignment="Center" Margin="0,0,8,0" Foreground="%%DK%%"/>
                <ComboBox x:Name="cmbCat" Grid.Column="1" Width="180" Margin="0,0,16,0" SelectedIndex="0">
                    <ComboBoxItem Content="All (Walls+Columns+Beams)"/>
                    <ComboBoxItem Content="Walls Only"/>
                    <ComboBoxItem Content="Columns Only"/>
                    <ComboBoxItem Content="Beams Only"/>
                    <ComboBoxItem Content="Walls + Columns"/>
                    <ComboBoxItem Content="Walls + Beams"/>
                    <ComboBoxItem Content="Columns + Beams"/>
                </ComboBox>
                <TextBlock Grid.Column="2" Text="Round to:" VerticalAlignment="Center" Margin="0,0,8,0" Foreground="%%DK%%"/>
                <ComboBox x:Name="cmbPrec" Grid.Column="3" Width="100" Margin="0,0,16,0" SelectedIndex="0">
                    <ComboBoxItem Content="1 mm"/>
                    <ComboBoxItem Content="0.5 mm"/>
                    <ComboBoxItem Content="5 mm"/>
                    <ComboBoxItem Content="10 mm"/>
                </ComboBox>
                <TextBlock Grid.Column="5" Text="Max move:" VerticalAlignment="Center" Margin="0,0,8,0" Foreground="%%DK%%"/>
                <ComboBox x:Name="cmbMax" Grid.Column="6" Width="100" SelectedIndex="2">
                    <ComboBoxItem Content="0.1 mm"/>
                    <ComboBoxItem Content="0.5 mm"/>
                    <ComboBoxItem Content="1 mm"/>
                    <ComboBoxItem Content="2 mm"/>
                    <ComboBoxItem Content="5 mm"/>
                    <ComboBoxItem Content="No limit"/>
                </ComboBox>
            </Grid>
        </Border>
        <DataGrid x:Name="dg" Grid.Row="2" Margin="10,8,10,4"
            AutoGenerateColumns="True" IsReadOnly="True" CanUserSortColumns="True"
            SelectionMode="Extended" GridLinesVisibility="Horizontal"
            HeadersVisibility="Column" BorderBrush="%%AC%%" BorderThickness="1"
            RowHeight="26" FontSize="12" AlternatingRowBackground="#FFF8F0"/>
        <Border Grid.Row="3" Padding="12,4" Background="White">
            <Grid>
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/><ColumnDefinition Width="Auto"/>
                </Grid.ColumnDefinitions>
                <TextBlock x:Name="txtSt" Grid.Column="0" Text="Click Scan." FontSize="11" Foreground="%%DK%%" VerticalAlignment="Center"/>
                <CheckBox x:Name="chkAll" Grid.Column="1" Content="Select All" VerticalAlignment="Center" Margin="0,0,16,0" IsChecked="True"/>
            </Grid>
        </Border>
        <Border Grid.Row="4" Background="White" Padding="12,8" BorderBrush="%%AC%%" BorderThickness="0,1,0,0">
            <Grid>
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="Auto"/><ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="Auto"/><ColumnDefinition Width="Auto"/>
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
    def __init__(self, eid, cat, ft, gn, dist, snap, delta, lv, mv):
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
        self.cmbCat = self.w.FindName("cmbCat")
        self.cmbPrec = self.w.FindName("cmbPrec")
        self.cmbMax = self.w.FindName("cmbMax")
        self.dg = self.w.FindName("dg")
        self.txtSt = self.w.FindName("txtSt")
        self.w.FindName("btnScan").Click += self._scan
        self.w.FindName("btnHL").Click += self._hl
        self.w.FindName("btnApply").Click += self._apply
        self.w.FindName("btnClose").Click += lambda s, e: self.w.Close()
        self.w.FindName("chkAll").Checked += lambda s, e: self._tog(True)
        self.w.FindName("chkAll").Unchecked += lambda s, e: self._tog(False)

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

    def _collect(self, bic):
        return list(FilteredElementCollector(doc)
                    .OfCategory(bic)
                    .WhereElementIsNotElementType()
                    .ToElements())

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

        grid_groups = group_grids_by_direction(grids_info)

        line_elems = []
        point_elems = []

        if cats["walls"]:
            for e in self._collect(BuiltInCategory.OST_Walls):
                if e.Location:
                    line_elems.append(e)

        if cats["beams"]:
            for e in self._collect(BuiltInCategory.OST_StructuralFraming):
                if e.Location:
                    line_elems.append(e)

        if cats["columns"]:
            for bic in [BuiltInCategory.OST_Columns,
                        BuiltInCategory.OST_StructuralColumns]:
                for e in self._collect(bic):
                    if e.Location:
                        point_elems.append(e)

        ns = len(line_elems) + len(point_elems)
        ni = 0

        for e in line_elems:
            results = analyze_line_elem(e, grids_info, pr)
            for gn, dist, snap, delta, mv in results:
                if abs(delta) > mx:
                    continue
                ni += 1
                cn = "Wall"
                try:
                    cn = e.Category.Name
                except:
                    pass
                self.items.append(SI(get_id_value(e.Id), cn, self._ft(e),
                                     gn, dist, snap, delta, self._lv(e), mv))

        for e in point_elems:
            results = analyze_column(e, grid_groups, pr)
            for gn, dist, snap, delta, mv in results:
                if abs(delta) > mx:
                    continue
                ni += 1
                cn = "Column"
                try:
                    cn = e.Category.Name
                except:
                    pass
                self.items.append(SI(get_id_value(e.Id), cn, self._ft(e),
                                     gn, dist, snap, delta, self._lv(e), mv))

        self._ref()
        self.txtSt.Text = "Scanned {}. Found {} fractional.".format(ns, ni)

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

    def _apply(self, s, a):
        todo = [i for i in self.items if i.sel]
        if not todo:
            self.txtSt.Text = "Nothing selected."
            return

        moves = OrderedDict()
        for i in todo:
            if i.eid not in moves:
                moves[i.eid] = XYZ(0, 0, 0)
            moves[i.eid] = XYZ(
                moves[i.eid].X + i.mv.X,
                moves[i.eid].Y + i.mv.Y,
                moves[i.eid].Z + i.mv.Z,
            )

        ok = fail = 0
        t = Transaction(doc, "DQT - Snap to Grid")
        try:
            t.Start()
            for eid_int, mv in moves.items():
                try:
                    eid = ElementId(eid_int)
                    if doc.GetElement(eid):
                        ElementTransformUtils.MoveElement(doc, eid, mv)
                        ok += 1
                    else:
                        fail += 1
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
        self.txtSt.Text = "Snapped {}.".format(ok) + (" {} failed.".format(fail) if fail else "")

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