# -*- coding: utf-8 -*-
"""
Tag Leader Straightener v1.1 - DQT
Straightens tag leaders (Room Tags, Area Tags, Space Tags, etc.)
to orthogonal (90-degree) angles, eliminating diagonal/acute angle leaders.

Copyright (c) 2025 Dang Quoc Truong (DQT)
All rights reserved.
"""

__title__ = "Leader\nStraightener"
__author__ = "Dang Quoc Truong (DQT)"
__doc__ = "Straighten tag leaders to orthogonal angles. Fix diagonal/acute leaders."

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('System')
clr.AddReference('System.Xml')
clr.AddReference('PresentationCore')
clr.AddReference('PresentationFramework')
clr.AddReference('WindowsBase')

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *

from System.Collections.ObjectModel import ObservableCollection
from System.Windows import Window, MessageBox, MessageBoxButton, MessageBoxResult, MessageBoxImage
from System.Windows.Markup import XamlReader
from System.IO import StringReader
from System.Xml import XmlReader as SysXmlReader
from System import Object
import System

import math

# =====================================================
# REVIT CONTEXT
# =====================================================
uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document
active_view = doc.ActiveView

# =====================================================
# COLORS
# =====================================================
PRIMARY = "#F0CC88"
BG = "#FEF8E7"
BORDER = "#D4A574"
FOOTER = "#2C2C2C"
GREEN = "#4CAF50"
RED = "#F44336"
BLUE = "#2196F3"
ORANGE = "#FF9800"

# =====================================================
# HELPER: Check Revit version for API differences
# =====================================================
def get_revit_version():
    try:
        return int(doc.Application.VersionNumber)
    except:
        return 2022

REVIT_VERSION = get_revit_version()

# =====================================================
# TAG ANALYSIS FUNCTIONS
# =====================================================

def safe_get_head_position(tag):
    """Get tag head position safely"""
    try:
        return tag.TagHeadPosition
    except:
        pass
    try:
        if tag.Location and hasattr(tag.Location, 'Point'):
            return tag.Location.Point
    except:
        pass
    return None


def safe_get_leader_end(tag):
    """Get leader end point - the point where leader touches the element"""
    # Method 1: SpatialElementTag.LeaderEnd (Room/Area/Space tags)
    try:
        return tag.LeaderEnd
    except:
        pass
    
    # Method 2: Revit 2022+ GetTaggedReferences API (IndependentTag)
    try:
        if hasattr(tag, 'GetTaggedReferences'):
            refs = tag.GetTaggedReferences()
            if refs.Count > 0:
                return tag.GetLeaderEnd(refs[0])
    except:
        pass
    
    # Method 3: Get tagged element location as fallback
    try:
        tagged_elem = get_tagged_element(tag)
        if tagged_elem and tagged_elem.Location:
            if hasattr(tagged_elem.Location, 'Point'):
                return tagged_elem.Location.Point
    except:
        pass
    
    return None


def safe_get_elbow(tag):
    """Get current elbow point if exists"""
    # Method 1: Revit 2022+ API
    try:
        if hasattr(tag, 'GetTaggedReferences'):
            refs = tag.GetTaggedReferences()
            if refs.Count > 0:
                return tag.GetLeaderElbow(refs[0])
    except:
        pass
    
    # Method 2: Direct property
    try:
        return tag.LeaderElbow
    except:
        pass
    
    return None


def is_spatial_tag(tag):
    """Check if tag is a SpatialElementTag (Room/Area/Space)"""
    try:
        # SpatialElementTag has LeaderEnd property, IndependentTag does not
        cat_name = tag.Category.Name if tag.Category else ""
        if any(k in cat_name for k in ["Room", "Area", "Space"]):
            return True
        # Also check by class
        if hasattr(tag, 'LeaderEnd') and not hasattr(tag, 'GetTaggedReferences'):
            return True
    except:
        pass
    return False


def safe_set_elbow(tag, elbow_point):
    """Set the elbow point on a tag leader - returns (True/False, message)"""
    
    # === SPATIAL ELEMENT TAGS (Room/Area/Space) ===
    if is_spatial_tag(tag):
        try:
            # Read current elbow before
            old_elbow = None
            try:
                old_elbow = tag.LeaderElbow
            except:
                pass
            
            # Set new elbow
            tag.LeaderElbow = elbow_point
            
            # Verify it changed
            try:
                new_elbow = tag.LeaderElbow
                dx = abs(new_elbow.X - elbow_point.X)
                dy = abs(new_elbow.Y - elbow_point.Y)
                if dx < 0.01 and dy < 0.01:
                    # Check if it was already the same
                    if old_elbow:
                        odx = abs(old_elbow.X - elbow_point.X)
                        ody = abs(old_elbow.Y - elbow_point.Y)
                        if odx < 0.01 and ody < 0.01:
                            return True, "Elbow already at target position"
                    return True, "OK"
                else:
                    return False, "Set succeeded but value did not change"
            except:
                return True, "OK (unverified)"
        except Exception as e:
            return False, "SpatialTag error: {}".format(str(e))
    
    # === INDEPENDENT TAGS ===
    try:
        if hasattr(tag, 'GetTaggedReferences'):
            refs = tag.GetTaggedReferences()
            if refs.Count > 0:
                ref = refs[0]
                if hasattr(tag, 'HasLeader') and not tag.HasLeader:
                    tag.HasLeader = True
                if hasattr(tag, 'LeaderEndCondition'):
                    tag.LeaderEndCondition = LeaderEndCondition.Free
                tag.SetLeaderElbow(ref, elbow_point)
                return True, "OK"
    except Exception as e:
        pass
    
    try:
        if hasattr(tag, 'LeaderEndCondition'):
            tag.LeaderEndCondition = LeaderEndCondition.Free
        tag.LeaderElbow = elbow_point
        return True, "OK"
    except Exception as e:
        pass
    
    return False, "No API method worked"


def get_tagged_element(tag):
    """Get the element being tagged"""
    # Method 1: GetTaggedReferences (Revit 2022+)
    try:
        if hasattr(tag, 'GetTaggedReferences'):
            refs = tag.GetTaggedReferences()
            if refs.Count > 0:
                ref = refs[0]
                if hasattr(ref, 'ElementId'):
                    return doc.GetElement(ref.ElementId)
    except:
        pass
    
    # Method 2: TaggedLocalElementId
    try:
        eid = tag.TaggedLocalElementId
        if eid and eid != ElementId.InvalidElementId:
            return doc.GetElement(eid)
    except:
        pass
    
    # Method 3: Category-specific properties
    try:
        cat_name = tag.Category.Name if tag.Category else ""
        if "Room" in cat_name:
            if hasattr(tag, 'Room'):
                return tag.Room
            if hasattr(tag, 'TaggedLocalRoom'):
                return tag.TaggedLocalRoom
        elif "Area" in cat_name:
            if hasattr(tag, 'Area'):
                return tag.Area
        elif "Space" in cat_name:
            if hasattr(tag, 'Space'):
                return tag.Space
    except:
        pass
    
    return None


def get_element_display_name(tag):
    """Get a display name for the tagged element"""
    elem = get_tagged_element(tag)
    if not elem:
        return "Element {}".format(tag.Id.IntegerValue)
    
    try:
        if hasattr(elem, 'Number'):
            num = elem.Number or ""
            name_param = elem.LookupParameter("Name")
            name = name_param.AsString() if name_param else ""
            result = "{} {}".format(num, name).strip()
            if result:
                return result
    except:
        pass
    
    try:
        if hasattr(elem, 'Name') and elem.Name:
            return elem.Name
    except:
        pass
    
    try:
        return "ID {}".format(elem.Id.IntegerValue)
    except:
        return "Unknown"


def needs_straightening(p1, p2, tol_ft=0.1):
    """
    Check if the line between two points needs straightening.
    A leader needs straightening when it's NOT aligned to a single axis,
    meaning both dx and dy are significant (the leader is diagonal).
    
    tol_ft: tolerance in feet (~1.2 inches / ~30mm)
    """
    dx = abs(p2.X - p1.X)
    dy = abs(p2.Y - p1.Y)
    # Diagonal = both dx and dy are larger than tolerance
    return dx > tol_ft and dy > tol_ft


def calc_deviation_angle(p1, p2):
    """
    Calculate how far the line deviates from the nearest axis (0 or 90).
    Returns angle from 0 to 45 degrees.
    0 = perfectly aligned to an axis
    45 = maximum diagonal (45 degrees)
    """
    dx = abs(p2.X - p1.X)
    dy = abs(p2.Y - p1.Y)
    if dx < 1e-10 and dy < 1e-10:
        return 0.0
    angle = math.degrees(math.atan2(dy, dx))  # 0-90
    # Deviation from nearest axis (0 or 90)
    if angle > 45:
        return 90.0 - angle
    return angle


def analyze_tag(tag):
    """Analyze a tag and return (is_diagonal, deviation_angle)"""
    head = safe_get_head_position(tag)
    end = safe_get_leader_end(tag)
    
    if not head or not end:
        return False, 0.0
    
    # First: does head-to-end need straightening at all?
    if not needs_straightening(head, end):
        return False, 0.0
    
    elbow = safe_get_elbow(tag)
    
    if elbow:
        # Has elbow - but is it creating a real visible L-shape?
        seg1_diag = needs_straightening(head, elbow)
        seg2_diag = needs_straightening(elbow, end)
        
        if seg1_diag or seg2_diag:
            # At least one segment is diagonal - needs fix
            dev1 = calc_deviation_angle(head, elbow)
            dev2 = calc_deviation_angle(elbow, end)
            return True, max(dev1, dev2)
        
        # Both segments are axis-aligned = elbow works correctly
        # But check: is the elbow the RIGHT L-shape (horizontal-first)?
        # If elbow.X == head.X → vertical-first (may look wrong)
        # We still mark as OK since it IS orthogonal
        return False, 0.0
    else:
        # No elbow - straight diagonal leader
        dev = calc_deviation_angle(head, end)
        return True, dev


def compute_elbow(head, end, mode="auto"):
    """Compute orthogonal elbow point between head and leader end.
    
    For Area/Room tags, leader goes: Head -> Elbow -> End
    horizontal_first: Head --horizontal--> Elbow --vertical--> End (L-shape)
    vertical_first:   Head --vertical--> Elbow --horizontal--> End (reversed L)
    auto: Always horizontal-first (natural reading direction from tag)
    """
    # Horizontal first: elbow at (end.X, head.Y) - go right/left then down/up
    elbow_hf = XYZ(end.X, head.Y, head.Z)
    # Vertical first: elbow at (head.X, end.Y) - go down/up then right/left
    elbow_vf = XYZ(head.X, end.Y, head.Z)
    
    if mode == "horizontal_first":
        return elbow_hf
    elif mode == "vertical_first":
        return elbow_vf
    else:
        # Auto: prefer horizontal-first (most natural L-shape for tags)
        # Tag text is typically offset from element, so going horizontal 
        # first then vertical creates a cleaner visual
        return elbow_hf


def straighten_one_tag(tag, mode="auto"):
    """Straighten one tag leader. Returns (success, error_msg)"""
    head = safe_get_head_position(tag)
    end = safe_get_leader_end(tag)
    
    if not head:
        return False, "Cannot get tag head position"
    if not end:
        return False, "Cannot get leader end point"
    
    # If head and end are on same axis, no elbow needed
    if not needs_straightening(head, end):
        return True, "Already axis-aligned"
    
    # Compute desired elbow position
    elbow_point = compute_elbow(head, end, mode)
    
    # Check if existing elbow is already at target
    existing_elbow = safe_get_elbow(tag)
    if existing_elbow:
        dx = abs(existing_elbow.X - elbow_point.X)
        dy = abs(existing_elbow.Y - elbow_point.Y)
        if dx < 0.05 and dy < 0.05:
            return True, "Already has correct L-shape"
    
    # Apply new elbow
    try:
        ok, msg = safe_set_elbow(tag, elbow_point)
        return ok, msg
    except Exception as ex:
        return False, str(ex)


# =====================================================
# COLLECT TAGS
# =====================================================

def collect_leader_tags(view):
    """Collect all tags with leaders in the given view"""
    tags = []
    seen_ids = set()
    
    tag_categories = [
        BuiltInCategory.OST_RoomTags,
        BuiltInCategory.OST_AreaTags,
        BuiltInCategory.OST_MEPSpaceTags,
        BuiltInCategory.OST_StructuralFramingTags,
        BuiltInCategory.OST_DoorTags,
        BuiltInCategory.OST_WindowTags,
        BuiltInCategory.OST_WallTags,
        BuiltInCategory.OST_FloorTags,
        BuiltInCategory.OST_CeilingTags,
        BuiltInCategory.OST_ColumnTags,
        BuiltInCategory.OST_StructuralColumnTags,
        BuiltInCategory.OST_FurnitureTags,
        BuiltInCategory.OST_PlumbingFixtureTags,
        BuiltInCategory.OST_MechanicalEquipmentTags,
        BuiltInCategory.OST_ElectricalEquipmentTags,
        BuiltInCategory.OST_ElectricalFixtureTags,
        BuiltInCategory.OST_LightingFixtureTags,
        BuiltInCategory.OST_GenericModelTags,
        BuiltInCategory.OST_SpecialityEquipmentTags,
        BuiltInCategory.OST_ParkingTags,
    ]
    
    for bic in tag_categories:
        try:
            collector = FilteredElementCollector(doc, view.Id)\
                .OfCategory(bic)\
                .WhereElementIsNotElementType()
            for tag in collector:
                if tag.Id.IntegerValue not in seen_ids:
                    try:
                        if hasattr(tag, 'HasLeader') and tag.HasLeader:
                            tags.append(tag)
                            seen_ids.add(tag.Id.IntegerValue)
                    except:
                        pass
        except:
            pass
    
    # Also collect generic IndependentTag that might be missed
    try:
        collector = FilteredElementCollector(doc, view.Id)\
            .OfClass(IndependentTag)\
            .WhereElementIsNotElementType()
        for tag in collector:
            if tag.Id.IntegerValue not in seen_ids:
                try:
                    if hasattr(tag, 'HasLeader') and tag.HasLeader:
                        tags.append(tag)
                        seen_ids.add(tag.Id.IntegerValue)
                except:
                    pass
    except:
        pass
    
    return tags


# =====================================================
# DATA ITEM
# =====================================================

class TagItem(Object):
    def __init__(self, tag):
        super(TagItem, self).__init__()
        self.Tag = tag
        self.TagId = tag.Id.IntegerValue
        
        cat = tag.Category
        self.CategoryName = cat.Name if cat else "Unknown"
        self.ElementName = get_element_display_name(tag)
        
        is_diag, angle = analyze_tag(tag)
        self.IsDiagonal = is_diag
        self.Angle = round(angle, 1)
        self.Status = "Diagonal" if is_diag else "OK"
        self.AngleDisplay = "{:.1f} deg".format(self.Angle)
        self._is_selected = is_diag
    
    @property
    def IsSelected(self):
        return self._is_selected
    
    @IsSelected.setter
    def IsSelected(self, value):
        self._is_selected = value


# =====================================================
# ZOOM TO ELEMENT
# =====================================================

def zoom_to_element(elem_id):
    """Zoom the active view to focus on a specific element"""
    try:
        elem = doc.GetElement(ElementId(elem_id))
        if not elem:
            return
        
        bb = elem.get_BoundingBox(active_view)
        if not bb:
            bb = elem.get_BoundingBox(None)
        
        if bb:
            pad = 3.0
            min_pt = XYZ(bb.Min.X - pad, bb.Min.Y - pad, bb.Min.Z)
            max_pt = XYZ(bb.Max.X + pad, bb.Max.Y + pad, bb.Max.Z)
            
            ui_views = uidoc.GetOpenUIViews()
            for uv in ui_views:
                if uv.ViewId == active_view.Id:
                    uv.ZoomAndCenterRectangle(min_pt, max_pt)
                    break
        
        ids = System.Collections.Generic.List[ElementId]()
        ids.Add(ElementId(elem_id))
        uidoc.Selection.SetElementIds(ids)
    except:
        pass


# =====================================================
# WPF XAML
# =====================================================

XAML_STR = '''
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Tag Leader Straightener - By DQT" 
        Height="720" Width="1020"
        WindowStartupLocation="CenterScreen" 
        Background="''' + BG + '''">
    <Grid Margin="0">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>
        
        <!-- HEADER -->
        <Border Grid.Row="0" Background="''' + PRIMARY + '''" 
                Padding="15" BorderBrush="''' + BORDER + '''" BorderThickness="0,0,0,2">
            <StackPanel>
                <TextBlock Text="TAG LEADER STRAIGHTENER" 
                           FontSize="20" FontWeight="Bold" 
                           HorizontalAlignment="Center" Foreground="#333333"/>
                <TextBlock Text="Fix diagonal tag leaders to orthogonal (90-degree) angles" 
                           FontSize="12" HorizontalAlignment="Center"
                           Foreground="#555555" Margin="0,3,0,0"/>
            </StackPanel>
        </Border>
        
        <!-- SUMMARY CARDS -->
        <Border Grid.Row="1" Margin="15,10,15,5" Padding="10" 
                Background="White" CornerRadius="5"
                BorderBrush="#E0E0E0" BorderThickness="1">
            <Grid>
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="*"/>
                </Grid.ColumnDefinitions>
                
                <Border Grid.Column="0" Margin="5" Padding="10" CornerRadius="5" Background="#E3F2FD">
                    <StackPanel HorizontalAlignment="Center">
                        <TextBlock x:Name="txtTotal" Text="0" FontSize="24" FontWeight="Bold" 
                                   HorizontalAlignment="Center" Foreground="''' + BLUE + '''"/>
                        <TextBlock Text="Total Tags" FontSize="11" 
                                   HorizontalAlignment="Center" Foreground="#666"/>
                    </StackPanel>
                </Border>
                
                <Border Grid.Column="1" Margin="5" Padding="10" CornerRadius="5" Background="#FBE9E7">
                    <StackPanel HorizontalAlignment="Center">
                        <TextBlock x:Name="txtDiag" Text="0" FontSize="24" FontWeight="Bold" 
                                   HorizontalAlignment="Center" Foreground="''' + RED + '''"/>
                        <TextBlock Text="Diagonal" FontSize="11" 
                                   HorizontalAlignment="Center" Foreground="#666"/>
                    </StackPanel>
                </Border>
                
                <Border Grid.Column="2" Margin="5" Padding="10" CornerRadius="5" Background="#E8F5E9">
                    <StackPanel HorizontalAlignment="Center">
                        <TextBlock x:Name="txtOrtho" Text="0" FontSize="24" FontWeight="Bold" 
                                   HorizontalAlignment="Center" Foreground="''' + GREEN + '''"/>
                        <TextBlock Text="Orthogonal" FontSize="11" 
                                   HorizontalAlignment="Center" Foreground="#666"/>
                    </StackPanel>
                </Border>
                
                <Border Grid.Column="3" Margin="5" Padding="10" CornerRadius="5" Background="#FFF3E0">
                    <StackPanel HorizontalAlignment="Center">
                        <TextBlock x:Name="txtSelected" Text="0" FontSize="24" FontWeight="Bold" 
                                   HorizontalAlignment="Center" Foreground="''' + ORANGE + '''"/>
                        <TextBlock Text="Selected" FontSize="11" 
                                   HorizontalAlignment="Center" Foreground="#666"/>
                    </StackPanel>
                </Border>
            </Grid>
        </Border>
        
        <!-- TOOLBAR -->
        <Border Grid.Row="2" Margin="15,5,15,5" Padding="8" 
                Background="White" CornerRadius="5"
                BorderBrush="#E0E0E0" BorderThickness="1">
            <Grid>
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="Auto"/>
                </Grid.ColumnDefinitions>
                
                <TextBlock Grid.Column="0" Text="Search:" 
                           VerticalAlignment="Center" Margin="5,0,8,0" 
                           FontWeight="SemiBold" Foreground="#555"/>
                <TextBox x:Name="txtSearch" Grid.Column="1" 
                         Height="28" VerticalContentAlignment="Center"
                         Margin="0,0,10,0"/>
                
                <TextBlock Grid.Column="2" Text="Mode:" 
                           VerticalAlignment="Center" Margin="5,0,8,0" 
                           FontWeight="SemiBold" Foreground="#555"/>
                <ComboBox x:Name="cboMode" Grid.Column="3" 
                          Width="150" Height="28" 
                          VerticalContentAlignment="Center" Margin="0,0,10,0"
                          SelectedIndex="0">
                    <ComboBoxItem Content="Auto (Smart)"/>
                    <ComboBoxItem Content="Horizontal First"/>
                    <ComboBoxItem Content="Vertical First"/>
                </ComboBox>
                
                <Button x:Name="btnSelectAll" Grid.Column="4" 
                        Content="Select All" Width="80" Height="28" 
                        Margin="0,0,5,0" Background="''' + PRIMARY + '''"
                        Foreground="#333" FontWeight="SemiBold" 
                        BorderBrush="''' + BORDER + '''" Cursor="Hand"/>
                <Button x:Name="btnSelectDiag" Grid.Column="5" 
                        Content="Select Diagonal" Width="110" Height="28" 
                        Margin="0,0,5,0" Background="#FFCDD2"
                        Foreground="#C62828" FontWeight="SemiBold" 
                        BorderBrush="#E57373" Cursor="Hand"/>
                <Button x:Name="btnSelectNone" Grid.Column="6" 
                        Content="Select None" Width="85" Height="28" 
                        Margin="0,0,5,0" Background="#E0E0E0" Foreground="#555" 
                        FontWeight="SemiBold" BorderBrush="#BDBDBD" Cursor="Hand"/>
                <Button x:Name="btnFilter" Grid.Column="7" 
                        Content="Diagonal Only" Width="100" Height="28" 
                        Background="#FFF3E0" Foreground="#E65100" 
                        FontWeight="SemiBold" BorderBrush="#FFB74D" Cursor="Hand"/>
            </Grid>
        </Border>
        
        <!-- DATA GRID -->
        <Border Grid.Row="3" Margin="15,5,15,5" 
                BorderBrush="#E0E0E0" BorderThickness="1" CornerRadius="3">
            <DataGrid x:Name="dgTags" 
                      AutoGenerateColumns="False"
                      CanUserAddRows="False"
                      CanUserDeleteRows="False"
                      CanUserReorderColumns="False"
                      SelectionMode="Single"
                      GridLinesVisibility="Horizontal"
                      HeadersVisibility="Column"
                      HorizontalGridLinesBrush="#EEE"
                      RowHeight="32"
                      IsReadOnly="False"
                      Background="White"
                      BorderThickness="0">
                <DataGrid.ColumnHeaderStyle>
                    <Style TargetType="DataGridColumnHeader">
                        <Setter Property="Background" Value="''' + PRIMARY + '''"/>
                        <Setter Property="Foreground" Value="#333"/>
                        <Setter Property="FontWeight" Value="Bold"/>
                        <Setter Property="FontSize" Value="12"/>
                        <Setter Property="Padding" Value="8,6"/>
                        <Setter Property="BorderBrush" Value="''' + BORDER + '''"/>
                        <Setter Property="BorderThickness" Value="0,0,1,1"/>
                    </Style>
                </DataGrid.ColumnHeaderStyle>
                <DataGrid.Columns>
                    <DataGridCheckBoxColumn Binding="{Binding IsSelected, Mode=TwoWay, UpdateSourceTrigger=PropertyChanged}" 
                                            Header="" Width="40"/>
                    <DataGridTextColumn Binding="{Binding TagId}" Header="Tag ID" Width="80" IsReadOnly="True"/>
                    <DataGridTextColumn Binding="{Binding CategoryName}" Header="Category" Width="130" IsReadOnly="True"/>
                    <DataGridTextColumn Binding="{Binding ElementName}" Header="Tagged Element" Width="*" IsReadOnly="True"/>
                    <DataGridTextColumn Binding="{Binding Status}" Header="Status" Width="85" IsReadOnly="True"/>
                    <DataGridTextColumn Binding="{Binding AngleDisplay}" Header="Max Angle" Width="85" IsReadOnly="True"/>
                </DataGrid.Columns>
            </DataGrid>
        </Border>
        
        <!-- ACTION BUTTONS -->
        <Border Grid.Row="4" Margin="15,5,15,5" Padding="8" 
                Background="White" CornerRadius="5"
                BorderBrush="#E0E0E0" BorderThickness="1">
            <Grid>
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="Auto"/>
                </Grid.ColumnDefinitions>
                
                <TextBlock x:Name="txtStatus" Grid.Column="0" 
                           Text="Ready" VerticalAlignment="Center"
                           Foreground="#777" FontStyle="Italic" Margin="5,0"/>
                
                <Button x:Name="btnZoom" Grid.Column="1" 
                        Content="Zoom to Tag" Width="100" Height="32" 
                        Margin="0,0,8,0" Background="#E8EAF6"
                        Foreground="#283593" FontWeight="Bold" 
                        BorderBrush="#9FA8DA" Cursor="Hand"/>
                <Button x:Name="btnHighlight" Grid.Column="2" 
                        Content="Highlight Selected" Width="125" Height="32" 
                        Margin="0,0,8,0" Background="#E3F2FD"
                        Foreground="''' + BLUE + '''" FontWeight="Bold" 
                        BorderBrush="#90CAF9" Cursor="Hand"/>
                <Button x:Name="btnRefresh" Grid.Column="3" 
                        Content="Refresh" Width="80" Height="32" 
                        Margin="0,0,8,0" Background="''' + PRIMARY + '''"
                        Foreground="#333" FontWeight="Bold" 
                        BorderBrush="''' + BORDER + '''" Cursor="Hand"/>
                <Button x:Name="btnApply" Grid.Column="4" 
                        Content="Straighten Selected" Width="145" Height="32" 
                        Margin="0,0,8,0" Background="''' + GREEN + '''"
                        Foreground="White" FontWeight="Bold" 
                        BorderBrush="#388E3C" Cursor="Hand"/>
                <Button x:Name="btnClose" Grid.Column="5" 
                        Content="Close" Width="70" Height="32" 
                        Background="#E0E0E0" Foreground="#555" 
                        FontWeight="Bold" BorderBrush="#BDBDBD" Cursor="Hand"/>
            </Grid>
        </Border>
        
        <!-- FOOTER -->
        <Border Grid.Row="5" Background="''' + FOOTER + '''" Padding="8">
            <TextBlock Text="Tag Leader Straightener v1.1 | Copyright 2025 Dang Quoc Truong (DQT) | All Rights Reserved" 
                       FontSize="10" FontWeight="Bold"
                       Foreground="White" HorizontalAlignment="Center"/>
        </Border>
    </Grid>
</Window>
'''


# =====================================================
# MAIN WINDOW
# =====================================================

class TagLeaderWindow:
    
    def __init__(self):
        self.window = XamlReader.Load(SysXmlReader.Create(StringReader(XAML_STR)))
        
        # Controls
        self.txtTotal = self.window.FindName("txtTotal")
        self.txtDiag = self.window.FindName("txtDiag")
        self.txtOrtho = self.window.FindName("txtOrtho")
        self.txtSelected = self.window.FindName("txtSelected")
        self.txtSearch = self.window.FindName("txtSearch")
        self.cboMode = self.window.FindName("cboMode")
        self.dgTags = self.window.FindName("dgTags")
        self.txtStatus = self.window.FindName("txtStatus")
        
        self.btnSelectAll = self.window.FindName("btnSelectAll")
        self.btnSelectDiag = self.window.FindName("btnSelectDiag")
        self.btnSelectNone = self.window.FindName("btnSelectNone")
        self.btnFilter = self.window.FindName("btnFilter")
        self.btnZoom = self.window.FindName("btnZoom")
        self.btnHighlight = self.window.FindName("btnHighlight")
        self.btnRefresh = self.window.FindName("btnRefresh")
        self.btnApply = self.window.FindName("btnApply")
        self.btnClose = self.window.FindName("btnClose")
        
        # Data
        self.all_items = []
        self.show_diagonal_only = False
        
        # Events - direct assignment (IronPython auto-wraps)
        self.btnSelectAll.Click += self.on_select_all
        self.btnSelectDiag.Click += self.on_select_diagonal
        self.btnSelectNone.Click += self.on_select_none
        self.btnFilter.Click += self.on_toggle_filter
        self.btnZoom.Click += self.on_zoom
        self.btnHighlight.Click += self.on_highlight
        self.btnRefresh.Click += self.on_refresh
        self.btnApply.Click += self.on_apply
        self.btnClose.Click += self.on_close
        self.txtSearch.TextChanged += self.on_search
        self.dgTags.MouseDoubleClick += self.on_row_double_click
        
        self.load_data()
    
    def load_data(self):
        self.all_items = []
        tags = collect_leader_tags(active_view)
        for tag in tags:
            try:
                self.all_items.append(TagItem(tag))
            except:
                continue
        self.refresh_grid()
        self.update_summary()
        self.txtStatus.Text = "Loaded {} tags with leaders".format(len(self.all_items))
    
    def get_filtered_items(self):
        items = self.all_items
        if self.show_diagonal_only:
            items = [i for i in items if i.IsDiagonal]
        
        search = self.txtSearch.Text.strip().lower() if self.txtSearch.Text else ""
        if search:
            items = [i for i in items
                     if search in i.CategoryName.lower()
                     or search in i.ElementName.lower()
                     or search in str(i.TagId)
                     or search in i.Status.lower()]
        return items
    
    def refresh_grid(self):
        filtered = self.get_filtered_items()
        col = ObservableCollection[Object]()
        for item in filtered:
            col.Add(item)
        self.dgTags.ItemsSource = col
    
    def update_summary(self):
        total = len(self.all_items)
        diag = sum(1 for i in self.all_items if i.IsDiagonal)
        self.txtTotal.Text = str(total)
        self.txtDiag.Text = str(diag)
        self.txtOrtho.Text = str(total - diag)
        self.txtSelected.Text = str(sum(1 for i in self.all_items if i.IsSelected))
    
    def get_mode(self):
        idx = self.cboMode.SelectedIndex
        if idx == 1: return "horizontal_first"
        if idx == 2: return "vertical_first"
        return "auto"
    
    # === EVENTS ===
    
    def on_search(self, sender, args):
        self.refresh_grid()
    
    def on_select_all(self, sender, args):
        for item in self.get_filtered_items():
            item._is_selected = True
        self.refresh_grid()
        self.update_summary()
    
    def on_select_diagonal(self, sender, args):
        for item in self.get_filtered_items():
            item._is_selected = item.IsDiagonal
        self.refresh_grid()
        self.update_summary()
    
    def on_select_none(self, sender, args):
        for item in self.get_filtered_items():
            item._is_selected = False
        self.refresh_grid()
        self.update_summary()
    
    def on_toggle_filter(self, sender, args):
        self.show_diagonal_only = not self.show_diagonal_only
        bc = System.Windows.Media.BrushConverter()
        if self.show_diagonal_only:
            self.btnFilter.Content = "Show All"
            self.btnFilter.Background = bc.ConvertFromString("#FFCDD2")
            self.btnFilter.Foreground = bc.ConvertFromString("#C62828")
        else:
            self.btnFilter.Content = "Diagonal Only"
            self.btnFilter.Background = bc.ConvertFromString("#FFF3E0")
            self.btnFilter.Foreground = bc.ConvertFromString("#E65100")
        self.refresh_grid()
    
    def on_zoom(self, sender, args):
        item = self.dgTags.SelectedItem
        if not item:
            MessageBox.Show("Select a tag row first, or double-click a row to zoom.",
                            "Zoom to Tag", MessageBoxButton.OK, MessageBoxImage.Information)
            return
        zoom_to_element(item.TagId)
        self.txtStatus.Text = "Zoomed to Tag ID {}".format(item.TagId)
    
    def on_row_double_click(self, sender, args):
        item = self.dgTags.SelectedItem
        if item:
            zoom_to_element(item.TagId)
            self.txtStatus.Text = "Zoomed to Tag ID {}".format(item.TagId)
    
    def on_highlight(self, sender, args):
        selected = [i for i in self.all_items if i.IsSelected]
        if not selected:
            MessageBox.Show("No tags selected.", "Highlight",
                            MessageBoxButton.OK, MessageBoxImage.Information)
            return
        ids = System.Collections.Generic.List[ElementId]()
        for item in selected:
            ids.Add(ElementId(item.TagId))
        uidoc.Selection.SetElementIds(ids)
        self.txtStatus.Text = "Highlighted {} tags".format(len(selected))
    
    def on_refresh(self, sender, args):
        self.load_data()
    
    def on_apply(self, sender, args):
        selected = [i for i in self.all_items if i.IsSelected]
        if not selected:
            MessageBox.Show("No tags selected to straighten.",
                            "Tag Leader Straightener",
                            MessageBoxButton.OK, MessageBoxImage.Information)
            return
        
        mode_names = ["Auto (Smart)", "Horizontal First", "Vertical First"]
        result = MessageBox.Show(
            "Straighten leaders for {} tag(s)?\n\nMode: {}\n\nCtrl+Z to undo.".format(
                len(selected), mode_names[self.cboMode.SelectedIndex]),
            "Confirm", MessageBoxButton.YesNo, MessageBoxImage.Question)
        
        if result != MessageBoxResult.Yes:
            return
        
        mode = self.get_mode()
        ok_count = 0
        skip_count = 0
        fail_count = 0
        fail_msgs = []
        detail_lines = []
        
        t = Transaction(doc, "DQT - Straighten Tag Leaders")
        t.Start()
        
        try:
            for item in selected:
                try:
                    tag = doc.GetElement(ElementId(item.TagId))
                    if not tag:
                        fail_count += 1
                        continue
                    success, msg = straighten_one_tag(tag, mode)
                    if success:
                        if "Already" in msg:
                            skip_count += 1
                            detail_lines.append("ID {}: {}".format(item.TagId, msg))
                        else:
                            ok_count += 1
                    else:
                        fail_count += 1
                        detail_lines.append("ID {}: FAIL - {}".format(item.TagId, msg))
                        if msg not in fail_msgs:
                            fail_msgs.append(msg)
                except Exception as ex:
                    fail_count += 1
                    err = str(ex)
                    if err not in fail_msgs:
                        fail_msgs.append(err)
            
            t.Commit()
        except Exception as ex:
            t.RollBack()
            MessageBox.Show("Transaction error: {}\n\nRolled back.".format(str(ex)),
                            "Error", MessageBoxButton.OK, MessageBoxImage.Error)
            return
        
        self.load_data()
        
        msg = "Changed: {}\nAlready OK: {}\nFailed: {}".format(ok_count, skip_count, fail_count)
        if detail_lines:
            msg += "\n\nDetails:\n" + "\n".join(detail_lines[:15])
        
        self.txtStatus.Text = "Done: {} changed, {} skipped, {} failed".format(ok_count, skip_count, fail_count)
        MessageBox.Show(msg, "Result", MessageBoxButton.OK, MessageBoxImage.Information)
    
    def on_close(self, sender, args):
        self.window.Close()
    
    def show(self):
        self.window.ShowDialog()


# =====================================================
# ENTRY POINT
# =====================================================

try:
    valid_types = [
        ViewType.FloorPlan, ViewType.CeilingPlan, ViewType.AreaPlan,
        ViewType.EngineeringPlan, ViewType.Section, ViewType.Elevation,
        ViewType.Detail
    ]
    
    if active_view.ViewType not in valid_types:
        MessageBox.Show(
            "Please open a Plan, Section, or Elevation view.\n\nCurrent: {}".format(active_view.ViewType),
            "Tag Leader Straightener - DQT",
            MessageBoxButton.OK, MessageBoxImage.Warning)
    else:
        window = TagLeaderWindow()
        window.show()

except Exception as e:
    import traceback
    MessageBox.Show(
        "Error:\n{}\n\n{}".format(str(e), traceback.format_exc()),
        "Tag Leader Straightener - DQT",
        MessageBoxButton.OK, MessageBoxImage.Error)