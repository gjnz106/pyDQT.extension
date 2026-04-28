# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                        QUICK SELECT MANAGER v1.0                              ║
║                              pyDQT Tool Suite                                 ║
║                                                                               ║
║  Quickly find, select, and navigate to any element in your Revit model       ║
║  Displays hierarchical view: Category → Family → Type → Instance             ║
║  Search by Category, Family, Type name - Zoom to any element                 ║
║                                                                               ║
║  Copyright (c) 2025 Dang Quoc Truong - DQT                                   ║
║  All rights reserved.                                                         ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

__title__ = "Quick\nSelect"
__author__ = "Dang Quoc Truong (DQT)"
__doc__ = "Quickly find, select, and zoom to any element in your Revit model. "\
          "Hierarchical browser with search and filtering capabilities."

# =============================================================================
# IMPORTS
# =============================================================================
import clr
clr.AddReference('System')
clr.AddReference('System.Core')
clr.AddReference('System.Drawing')
clr.AddReference('System.Windows.Forms')
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')

import System
from System import EventHandler, Object, Uri
from System.Collections.Generic import List
from System.Collections.ObjectModel import ObservableCollection
from System.ComponentModel import INotifyPropertyChanged, PropertyChangedEventArgs
from System.Windows import (
    Window, WindowStyle, WindowStartupLocation, ResizeMode,
    Thickness, HorizontalAlignment, VerticalAlignment, TextAlignment,
    Visibility, FontWeight, FontWeights, FontStyles, RoutedEventArgs,
    GridLength, GridUnitType, CornerRadius as WCornerRadius, MessageBox
)
from System.Windows.Controls import (
    Grid, RowDefinition, ColumnDefinition, Border, StackPanel,
    TextBlock, TextBox, Button, ComboBox, ComboBoxItem, CheckBox,
    ScrollViewer, TreeView, TreeViewItem, ContextMenu, MenuItem,
    Orientation, ScrollBarVisibility, SelectionMode, Separator
)
from System.Windows.Media import (
    SolidColorBrush, Color, Colors, Brushes,
    FontFamily
)
from System.Windows.Input import Cursors

from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, ElementId, Element,
    ViewType, View, ViewPlan, View3D, ViewSection, ViewSheet,
    Category, FamilyInstance, FamilySymbol, Family,
    Wall, Floor, Ceiling, Level,
    BuiltInParameter, Transaction, XYZ, BoundingBoxXYZ,
    ElementCategoryFilter, LogicalOrFilter, ElementFilter
)
from Autodesk.Revit.UI import UIApplication, TaskDialog, TaskDialogCommonButtons

from pyrevit import revit, script, forms

import traceback
from collections import defaultdict

# =============================================================================
# DQT BRAND COLORS
# =============================================================================
class C:
    """DQT Brand Color Palette"""
    PRI = Color.FromRgb(240, 204, 136)      # #F0CC88 - Primary Gold
    PRI_DARK = Color.FromRgb(200, 160, 100) # Darker gold for borders
    BG = Color.FromRgb(254, 248, 231)       # #FEF8E7 - Warm cream background
    BG_WHITE = Color.FromRgb(255, 255, 255) # White
    BG_CARD = Color.FromRgb(255, 250, 240)  # Light cream for cards
    BG_HOVER = Color.FromRgb(255, 245, 220) # Hover state
    TEXT = Color.FromRgb(51, 51, 51)        # #333333 - Dark text
    TEXT_SEC = Color.FromRgb(102, 102, 102) # #666666 - Secondary text
    TEXT_LIGHT = Color.FromRgb(150, 150, 150)
    BORDER = Color.FromRgb(220, 200, 160)   # Warm border
    ACCENT = Color.FromRgb(70, 130, 180)    # Steel blue for actions
    SUCCESS = Color.FromRgb(76, 175, 80)    # Green
    WARNING = Color.FromRgb(255, 152, 0)    # Orange
    ERROR = Color.FromRgb(244, 67, 54)      # Red
    INFO = Color.FromRgb(33, 150, 243)      # Blue

def SB(color):
    """Create SolidColorBrush from Color"""
    return SolidColorBrush(color)

# =============================================================================
# ELEMENT ITEM DATA CLASS
# =============================================================================
class ElementItem:
    """Represents a single Revit element in the tree"""
    
    def __init__(self, element, doc):
        self.element = element
        self.id = element.Id
        self.id_int = element.Id.IntegerValue
        self.doc = doc
        
        # Basic info
        self.name = self._get_name()
        self.category_name = self._get_category_name()
        self.family_name = self._get_family_name()
        self.type_name = self._get_type_name()
        
        # For display
        self.display_name = self._get_display_name()
        self.is_selected = False
    
    def _get_name(self):
        """Get element name"""
        try:
            name = self.element.Name
            if name:
                return name
        except:
            pass
        
        # Try getting Mark or other parameters
        try:
            mark_param = self.element.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
            if mark_param and mark_param.AsString():
                return mark_param.AsString()
        except:
            pass
        
        return "Element {}".format(self.id_int)
    
    def _get_category_name(self):
        """Get category name"""
        try:
            cat = self.element.Category
            if cat:
                return cat.Name
        except:
            pass
        return "Unknown Category"
    
    def _get_family_name(self):
        """Get family name"""
        try:
            # For FamilyInstance
            if isinstance(self.element, FamilyInstance):
                symbol = self.element.Symbol
                if symbol and symbol.Family:
                    return symbol.Family.Name
            
            # For other elements, try to get from type
            type_id = self.element.GetTypeId()
            if type_id and type_id != ElementId.InvalidElementId:
                elem_type = self.doc.GetElement(type_id)
                if elem_type:
                    # Try FamilyName parameter
                    param = elem_type.get_Parameter(BuiltInParameter.ALL_MODEL_FAMILY_NAME)
                    if param and param.AsString():
                        return param.AsString()
                    # Try to get family name from type name
                    type_name = elem_type.Name if hasattr(elem_type, 'Name') else ""
                    if hasattr(elem_type, 'FamilyName'):
                        return elem_type.FamilyName
        except:
            pass
        
        return "System Family"
    
    def _get_type_name(self):
        """Get type name"""
        try:
            type_id = self.element.GetTypeId()
            if type_id and type_id != ElementId.InvalidElementId:
                elem_type = self.doc.GetElement(type_id)
                if elem_type and hasattr(elem_type, 'Name'):
                    return elem_type.Name
        except:
            pass
        
        # For some elements, Name is the type name
        try:
            return self.element.Name
        except:
            pass
        
        return "Unknown Type"
    
    def _get_display_name(self):
        """Get display name for tree (Instance level)"""
        parts = []
        
        # Add Mark if available
        try:
            mark = self.element.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
            if mark and mark.AsString():
                parts.append(mark.AsString())
        except:
            pass
        
        # Add Level info if available
        try:
            level_param = self.element.get_Parameter(BuiltInParameter.FAMILY_LEVEL_PARAM)
            if not level_param:
                level_param = self.element.get_Parameter(BuiltInParameter.SCHEDULE_LEVEL_PARAM)
            if level_param:
                level_id = level_param.AsElementId()
                if level_id and level_id != ElementId.InvalidElementId:
                    level = self.doc.GetElement(level_id)
                    if level:
                        parts.append("Level: " + level.Name)
        except:
            pass
        
        # Add Room info if available
        try:
            if isinstance(self.element, FamilyInstance):
                room = self.element.Room
                if room:
                    parts.append("Room: " + room.Name)
        except:
            pass
        
        # Build display name
        if parts:
            return "ID {} - {}".format(self.id_int, " | ".join(parts))
        else:
            return "ID {}".format(self.id_int)


# =============================================================================
# TREE NODE CLASSES
# =============================================================================
class TreeNode:
    """Base class for tree nodes"""
    
    def __init__(self, name, parent=None):
        self.name = name
        self.parent = parent
        self.children = []
        self.is_expanded = False
        self.is_selected = False
        self.count = 0
    
    def add_child(self, child):
        self.children.append(child)
        child.parent = self
    
    def get_all_elements(self):
        """Get all ElementItems under this node"""
        elements = []
        for child in self.children:
            elements.extend(child.get_all_elements())
        return elements


class CategoryNode(TreeNode):
    """Node representing a Category"""
    
    def __init__(self, name):
        TreeNode.__init__(self, name)
        self.families = {}  # family_name -> FamilyNode
    
    def get_or_create_family(self, family_name):
        if family_name not in self.families:
            family_node = FamilyNode(family_name)
            self.families[family_name] = family_node
            self.add_child(family_node)
        return self.families[family_name]


class FamilyNode(TreeNode):
    """Node representing a Family"""
    
    def __init__(self, name):
        TreeNode.__init__(self, name)
        self.types = {}  # type_name -> TypeNode
    
    def get_or_create_type(self, type_name):
        if type_name not in self.types:
            type_node = TypeNode(type_name)
            self.types[type_name] = type_node
            self.add_child(type_node)
        return self.types[type_name]


class TypeNode(TreeNode):
    """Node representing a Type"""
    
    def __init__(self, name):
        TreeNode.__init__(self, name)
        self.elements = []  # List of ElementItem
    
    def add_element(self, element_item):
        self.elements.append(element_item)
        self.count = len(self.elements)
    
    def get_all_elements(self):
        return self.elements


class InstanceNode(TreeNode):
    """Node representing a single Element Instance"""
    
    def __init__(self, element_item):
        TreeNode.__init__(self, element_item.display_name)
        self.element_item = element_item
    
    def get_all_elements(self):
        return [self.element_item]


# =============================================================================
# DATA COLLECTOR
# =============================================================================
class ElementDataCollector:
    """Collects and organizes elements from Revit"""
    
    # Categories to collect
    CATEGORIES = [
        BuiltInCategory.OST_Walls,
        BuiltInCategory.OST_Floors,
        BuiltInCategory.OST_Ceilings,
        BuiltInCategory.OST_Roofs,
        BuiltInCategory.OST_Doors,
        BuiltInCategory.OST_Windows,
        BuiltInCategory.OST_Furniture,
        BuiltInCategory.OST_FurnitureSystems,
        BuiltInCategory.OST_Casework,
        BuiltInCategory.OST_Columns,
        BuiltInCategory.OST_StructuralColumns,
        BuiltInCategory.OST_StructuralFraming,
        BuiltInCategory.OST_StructuralFoundation,
        BuiltInCategory.OST_Stairs,
        BuiltInCategory.OST_StairsRailing,
        BuiltInCategory.OST_Ramps,
        BuiltInCategory.OST_GenericModel,
        BuiltInCategory.OST_SpecialityEquipment,
        BuiltInCategory.OST_MechanicalEquipment,
        BuiltInCategory.OST_ElectricalEquipment,
        BuiltInCategory.OST_ElectricalFixtures,
        BuiltInCategory.OST_LightingFixtures,
        BuiltInCategory.OST_PlumbingFixtures,
        BuiltInCategory.OST_Rooms,
        BuiltInCategory.OST_Areas,
        BuiltInCategory.OST_Parking,
        BuiltInCategory.OST_Planting,
        BuiltInCategory.OST_Entourage,
        BuiltInCategory.OST_Site,
        BuiltInCategory.OST_Topography,
        BuiltInCategory.OST_CurtainWallPanels,
        BuiltInCategory.OST_CurtainWallMullions,
        # Annotations
        BuiltInCategory.OST_TextNotes,
        BuiltInCategory.OST_Dimensions,
        BuiltInCategory.OST_DetailComponents,
        BuiltInCategory.OST_GenericAnnotation,
        BuiltInCategory.OST_RevisionClouds,
        BuiltInCategory.OST_Grids,
        BuiltInCategory.OST_Levels,
        # MEP
        BuiltInCategory.OST_PipeCurves,
        BuiltInCategory.OST_PipeFitting,
        BuiltInCategory.OST_PipeAccessory,
        BuiltInCategory.OST_DuctCurves,
        BuiltInCategory.OST_DuctFitting,
        BuiltInCategory.OST_DuctAccessory,
        BuiltInCategory.OST_DuctTerminal,
        BuiltInCategory.OST_FlexDuctCurves,
        BuiltInCategory.OST_FlexPipeCurves,
        BuiltInCategory.OST_Conduit,
        BuiltInCategory.OST_ConduitFitting,
        BuiltInCategory.OST_CableTray,
        BuiltInCategory.OST_CableTrayFitting,
        BuiltInCategory.OST_Sprinklers,
        # Links
        BuiltInCategory.OST_RvtLinks,
    ]
    
    def __init__(self, doc, uidoc):
        self.doc = doc
        self.uidoc = uidoc
    
    def collect_entire_project(self):
        """Collect all elements from entire project"""
        all_elements = []
        
        for bic in self.CATEGORIES:
            try:
                collector = FilteredElementCollector(self.doc)
                collector = collector.OfCategory(bic)
                collector = collector.WhereElementIsNotElementType()
                
                for elem in collector:
                    if elem and elem.Id:
                        try:
                            item = ElementItem(elem, self.doc)
                            all_elements.append(item)
                        except:
                            pass
            except:
                pass
        
        return all_elements
    
    def collect_active_view(self):
        """Collect elements visible in active view"""
        active_view = self.doc.ActiveView
        if not active_view:
            return []
        
        all_elements = []
        
        for bic in self.CATEGORIES:
            try:
                collector = FilteredElementCollector(self.doc, active_view.Id)
                collector = collector.OfCategory(bic)
                collector = collector.WhereElementIsNotElementType()
                
                for elem in collector:
                    if elem and elem.Id:
                        try:
                            item = ElementItem(elem, self.doc)
                            all_elements.append(item)
                        except:
                            pass
            except:
                pass
        
        return all_elements
    
    def collect_current_selection(self):
        """Collect currently selected elements"""
        selection = self.uidoc.Selection.GetElementIds()
        all_elements = []
        
        for elem_id in selection:
            try:
                elem = self.doc.GetElement(elem_id)
                if elem:
                    item = ElementItem(elem, self.doc)
                    all_elements.append(item)
            except:
                pass
        
        return all_elements
    
    def build_tree_structure(self, elements):
        """Build hierarchical tree structure from elements"""
        categories = {}  # category_name -> CategoryNode
        
        for item in elements:
            # Get or create category node
            cat_name = item.category_name
            if cat_name not in categories:
                categories[cat_name] = CategoryNode(cat_name)
            cat_node = categories[cat_name]
            
            # Get or create family node
            family_node = cat_node.get_or_create_family(item.family_name)
            
            # Get or create type node
            type_node = family_node.get_or_create_type(item.type_name)
            
            # Add element to type
            type_node.add_element(item)
        
        # Update counts
        for cat_node in categories.values():
            cat_count = 0
            for family_node in cat_node.children:
                family_count = 0
                for type_node in family_node.children:
                    family_count += type_node.count
                family_node.count = family_count
                cat_count += family_count
            cat_node.count = cat_count
        
        # Sort and return
        sorted_categories = sorted(categories.values(), key=lambda x: x.name)
        return sorted_categories


# =============================================================================
# VIEW NAVIGATOR
# =============================================================================
class ViewNavigator:
    """Helps navigate to elements and find suitable views"""
    
    def __init__(self, doc, uidoc):
        self.doc = doc
        self.uidoc = uidoc
    
    def zoom_to_element(self, element_id):
        """Zoom to element in current view"""
        try:
            elem = self.doc.GetElement(element_id)
            if not elem:
                return False
            
            # Get bounding box
            bbox = elem.get_BoundingBox(self.doc.ActiveView)
            if bbox:
                # Expand bbox slightly
                min_pt = bbox.Min
                max_pt = bbox.Max
                offset = 3.0  # feet
                
                new_min = XYZ(min_pt.X - offset, min_pt.Y - offset, min_pt.Z - offset)
                new_max = XYZ(max_pt.X + offset, max_pt.Y + offset, max_pt.Z + offset)
                
                new_bbox = BoundingBoxXYZ()
                new_bbox.Min = new_min
                new_bbox.Max = new_max
                
                # Zoom
                self.uidoc.GetOpenUIViews()[0].ZoomAndCenterRectangle(new_min, new_max)
                return True
            
            return False
        except Exception as e:
            print("Zoom error: {}".format(str(e)))
            return False
    
    def find_view_for_element(self, element_id):
        """Find a suitable view where the element is visible"""
        try:
            elem = self.doc.GetElement(element_id)
            if not elem:
                return None
            
            # Get element's level if available
            level_id = None
            try:
                level_param = elem.get_Parameter(BuiltInParameter.FAMILY_LEVEL_PARAM)
                if not level_param:
                    level_param = elem.get_Parameter(BuiltInParameter.SCHEDULE_LEVEL_PARAM)
                if level_param:
                    level_id = level_param.AsElementId()
            except:
                pass
            
            # Collect floor plan views
            views = FilteredElementCollector(self.doc)\
                .OfClass(ViewPlan)\
                .WhereElementIsNotElementType()\
                .ToElements()
            
            # Find matching view
            for view in views:
                if view.IsTemplate:
                    continue
                
                # Check if element is visible in this view
                try:
                    if level_id and view.GenLevel:
                        if view.GenLevel.Id == level_id:
                            return view
                except:
                    pass
            
            # If no matching level, return first non-template floor plan
            for view in views:
                if not view.IsTemplate:
                    return view
            
            return None
        except:
            return None
    
    def show_element(self, element_id):
        """Navigate to element - find view and zoom"""
        try:
            elem = self.doc.GetElement(element_id)
            if not elem:
                return False
            
            # Check if element is in current view
            current_view = self.doc.ActiveView
            bbox = elem.get_BoundingBox(current_view)
            
            if bbox:
                # Element visible in current view, just zoom
                return self.zoom_to_element(element_id)
            else:
                # Find another view
                view = self.find_view_for_element(element_id)
                if view:
                    self.uidoc.ActiveView = view
                    # Wait a bit for view to activate, then zoom
                    return self.zoom_to_element(element_id)
            
            return False
        except Exception as e:
            print("Show element error: {}".format(str(e)))
            return False
    
    def select_elements(self, element_ids):
        """Select elements in Revit"""
        try:
            id_list = List[ElementId]()
            for eid in element_ids:
                if isinstance(eid, ElementId):
                    id_list.Add(eid)
                else:
                    id_list.Add(ElementId(int(eid)))
            
            self.uidoc.Selection.SetElementIds(id_list)
            return True
        except Exception as e:
            print("Selection error: {}".format(str(e)))
            return False


# =============================================================================
# QUICK SELECT WINDOW
# =============================================================================
class QuickSelectWindow(Window):
    """
    Quick Select Manager - Hierarchical element browser
    Similar to Ideate QuickSelect functionality
    """
    
    def __init__(self):
        self.doc = revit.doc
        self.uidoc = revit.uidoc
        
        # Data
        self.collector = ElementDataCollector(self.doc, self.uidoc)
        self.navigator = ViewNavigator(self.doc, self.uidoc)
        self.all_elements = []
        self.tree_data = []
        self.selected_elements = []
        self.current_display_mode = "Active View"
        
        # UI References
        self.tree_view = None
        self.txt_search = None
        self.cmb_display = None
        self.txt_total = None
        self.txt_selected = None
        self.txt_categories = None
        
        # Window properties
        self.Title = "Quick Select Manager v1.0 - DQT"
        self.Width = 750
        self.Height = 700
        self.MinWidth = 600
        self.MinHeight = 500
        self.WindowStartupLocation = WindowStartupLocation.CenterScreen
        self.Background = SB(C.BG)
        
        # Build UI
        self._build_ui()
        
        # Load initial data
        self._load_data()
    
    # =========================================================================
    # UI BUILDING
    # =========================================================================
    
    def _build_ui(self):
        """Build the main UI"""
        root = Grid()
        root.Margin = Thickness(15)
        
        # Define rows
        row_heights = [
            GridLength.Auto,                    # 0: Header
            GridLength.Auto,                    # 1: Summary cards
            GridLength.Auto,                    # 2: Display options & Search
            GridLength(1, GridUnitType.Star),   # 3: TreeView
            GridLength.Auto,                    # 4: Action buttons
            GridLength.Auto,                    # 5: Footer
        ]
        
        for h in row_heights:
            rd = RowDefinition()
            rd.Height = h
            root.RowDefinitions.Add(rd)
        
        # Row 0: Header
        header = self._build_header()
        Grid.SetRow(header, 0)
        root.Children.Add(header)
        
        # Row 1: Summary cards
        cards = self._build_summary_cards()
        Grid.SetRow(cards, 1)
        root.Children.Add(cards)
        
        # Row 2: Display options & Search
        options = self._build_options_bar()
        Grid.SetRow(options, 2)
        root.Children.Add(options)
        
        # Row 3: TreeView
        tree = self._build_tree_section()
        Grid.SetRow(tree, 3)
        root.Children.Add(tree)
        
        # Row 4: Actions
        actions = self._build_action_buttons()
        Grid.SetRow(actions, 4)
        root.Children.Add(actions)
        
        # Row 5: Footer
        footer = self._build_footer()
        Grid.SetRow(footer, 5)
        root.Children.Add(footer)
        
        self.Content = root
    
    def _build_header(self):
        """Build header with title"""
        border = Border()
        border.Background = SB(C.PRI)
        border.CornerRadius = WCornerRadius(6)
        border.Padding = Thickness(15, 12, 15, 12)
        border.Margin = Thickness(0, 0, 0, 12)
        
        grid = Grid()
        
        # Title column
        col1 = ColumnDefinition()
        col1.Width = GridLength(1, GridUnitType.Star)
        grid.ColumnDefinitions.Add(col1)
        
        # Info column
        col2 = ColumnDefinition()
        col2.Width = GridLength.Auto
        grid.ColumnDefinitions.Add(col2)
        
        # Title
        title = TextBlock()
        title.Text = "🔍 Quick Select Manager"
        title.FontSize = 20
        title.FontWeight = FontWeights.Bold
        title.Foreground = SB(C.TEXT)
        Grid.SetColumn(title, 0)
        grid.Children.Add(title)
        
        # Subtitle
        subtitle = TextBlock()
        subtitle.Text = "pyDQT Tool Suite"
        subtitle.FontSize = 11
        subtitle.Foreground = SB(C.TEXT_SEC)
        subtitle.VerticalAlignment = VerticalAlignment.Center
        subtitle.HorizontalAlignment = HorizontalAlignment.Right
        Grid.SetColumn(subtitle, 1)
        grid.Children.Add(subtitle)
        
        border.Child = grid
        return border
    
    def _build_summary_cards(self):
        """Build summary statistic cards"""
        panel = StackPanel()
        panel.Orientation = Orientation.Horizontal
        panel.Margin = Thickness(0, 0, 0, 12)
        
        # Total Elements
        card1, self.txt_total = self._create_stat_card("Total Elements", "0", "📊")
        panel.Children.Add(card1)
        
        # Selected
        card2, self.txt_selected = self._create_stat_card("Selected", "0", "✓")
        panel.Children.Add(card2)
        
        # Categories
        card3, self.txt_categories = self._create_stat_card("Categories", "0", "📁")
        panel.Children.Add(card3)
        
        return panel
    
    def _create_stat_card(self, label, value, icon):
        """Create a single statistics card"""
        border = Border()
        border.Background = SB(C.BG_WHITE)
        border.BorderBrush = SB(C.BORDER)
        border.BorderThickness = Thickness(1)
        border.CornerRadius = WCornerRadius(5)
        border.Padding = Thickness(15, 10, 15, 10)
        border.Margin = Thickness(0, 0, 10, 0)
        border.MinWidth = 140
        
        stack = StackPanel()
        
        # Icon and Label row
        header = StackPanel()
        header.Orientation = Orientation.Horizontal
        
        icon_tb = TextBlock()
        icon_tb.Text = icon
        icon_tb.FontSize = 14
        icon_tb.Margin = Thickness(0, 0, 6, 0)
        header.Children.Add(icon_tb)
        
        label_tb = TextBlock()
        label_tb.Text = label
        label_tb.FontSize = 11
        label_tb.Foreground = SB(C.TEXT_SEC)
        header.Children.Add(label_tb)
        
        stack.Children.Add(header)
        
        # Value
        value_tb = TextBlock()
        value_tb.Text = value
        value_tb.FontSize = 22
        value_tb.FontWeight = FontWeights.Bold
        value_tb.Foreground = SB(C.TEXT)
        value_tb.Margin = Thickness(0, 4, 0, 0)
        stack.Children.Add(value_tb)
        
        border.Child = stack
        return border, value_tb
    
    def _build_options_bar(self):
        """Build display options and search bar"""
        border = Border()
        border.Background = SB(C.BG_WHITE)
        border.BorderBrush = SB(C.BORDER)
        border.BorderThickness = Thickness(1)
        border.CornerRadius = WCornerRadius(5)
        border.Padding = Thickness(12)
        border.Margin = Thickness(0, 0, 0, 12)
        
        grid = Grid()
        
        # Columns
        col1 = ColumnDefinition()
        col1.Width = GridLength.Auto
        grid.ColumnDefinitions.Add(col1)
        
        col2 = ColumnDefinition()
        col2.Width = GridLength(1, GridUnitType.Star)
        grid.ColumnDefinitions.Add(col2)
        
        col3 = ColumnDefinition()
        col3.Width = GridLength.Auto
        grid.ColumnDefinitions.Add(col3)
        
        # Display dropdown
        display_panel = StackPanel()
        display_panel.Orientation = Orientation.Horizontal
        display_panel.Margin = Thickness(0, 0, 20, 0)
        
        display_label = TextBlock()
        display_label.Text = "Display:"
        display_label.FontSize = 12
        display_label.Foreground = SB(C.TEXT)
        display_label.VerticalAlignment = VerticalAlignment.Center
        display_label.Margin = Thickness(0, 0, 8, 0)
        display_panel.Children.Add(display_label)
        
        self.cmb_display = ComboBox()
        self.cmb_display.Width = 150
        self.cmb_display.FontSize = 12
        
        for option in ["Active View", "Entire Project", "Current Selection"]:
            item = ComboBoxItem()
            item.Content = option
            self.cmb_display.Items.Add(item)
        
        self.cmb_display.SelectedIndex = 0
        self.cmb_display.SelectionChanged += self._on_display_changed
        display_panel.Children.Add(self.cmb_display)
        
        Grid.SetColumn(display_panel, 0)
        grid.Children.Add(display_panel)
        
        # Search box
        search_panel = StackPanel()
        search_panel.Orientation = Orientation.Horizontal
        
        search_icon = TextBlock()
        search_icon.Text = "🔎"
        search_icon.FontSize = 14
        search_icon.VerticalAlignment = VerticalAlignment.Center
        search_icon.Margin = Thickness(0, 0, 8, 0)
        search_panel.Children.Add(search_icon)
        
        self.txt_search = TextBox()
        self.txt_search.Width = 250
        self.txt_search.FontSize = 12
        self.txt_search.Padding = Thickness(8, 6, 8, 6)
        self.txt_search.VerticalContentAlignment = VerticalAlignment.Center
        # Placeholder simulation
        self.txt_search.Text = ""
        self.txt_search.Tag = "Search Category, Family, or Type..."
        self.txt_search.Foreground = SB(C.TEXT_LIGHT)
        self.txt_search.GotFocus += self._on_search_focus
        self.txt_search.LostFocus += self._on_search_blur
        self.txt_search.TextChanged += self._on_search_changed
        search_panel.Children.Add(self.txt_search)
        
        Grid.SetColumn(search_panel, 1)
        grid.Children.Add(search_panel)
        
        # Refresh button
        btn_refresh = self._create_button("🔄 Refresh", self._on_refresh_click)
        btn_refresh.Width = 90
        Grid.SetColumn(btn_refresh, 2)
        grid.Children.Add(btn_refresh)
        
        border.Child = grid
        return border
    
    def _build_tree_section(self):
        """Build the TreeView section"""
        border = Border()
        border.Background = SB(C.BG_WHITE)
        border.BorderBrush = SB(C.BORDER)
        border.BorderThickness = Thickness(1)
        border.CornerRadius = WCornerRadius(5)
        border.Margin = Thickness(0, 0, 0, 12)
        
        # ScrollViewer for TreeView
        scroll = ScrollViewer()
        scroll.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
        scroll.HorizontalScrollBarVisibility = ScrollBarVisibility.Auto
        scroll.Padding = Thickness(8)
        
        self.tree_view = TreeView()
        self.tree_view.Background = SB(Colors.Transparent)
        self.tree_view.BorderThickness = Thickness(0)
        self.tree_view.FontSize = 12
        
        # Context menu
        context_menu = ContextMenu()
        
        mi_show = MenuItem()
        mi_show.Header = "Show Elements"
        mi_show.Click += self._on_show_elements
        context_menu.Items.Add(mi_show)
        
        mi_select = MenuItem()
        mi_select.Header = "Select in Model"
        mi_select.Click += self._on_select_in_model
        context_menu.Items.Add(mi_select)
        
        context_menu.Items.Add(Separator())
        
        mi_expand = MenuItem()
        mi_expand.Header = "Expand All"
        mi_expand.Click += self._on_expand_all
        context_menu.Items.Add(mi_expand)
        
        mi_collapse = MenuItem()
        mi_collapse.Header = "Collapse All"
        mi_collapse.Click += self._on_collapse_all
        context_menu.Items.Add(mi_collapse)
        
        self.tree_view.ContextMenu = context_menu
        self.tree_view.MouseDoubleClick += self._on_tree_double_click
        
        scroll.Content = self.tree_view
        border.Child = scroll
        return border
    
    def _build_action_buttons(self):
        """Build action buttons"""
        border = Border()
        border.Background = SB(C.BG_CARD)
        border.BorderBrush = SB(C.BORDER)
        border.BorderThickness = Thickness(1)
        border.CornerRadius = WCornerRadius(5)
        border.Padding = Thickness(12)
        border.Margin = Thickness(0, 0, 0, 12)
        
        grid = Grid()
        
        # Left buttons
        col1 = ColumnDefinition()
        col1.Width = GridLength(1, GridUnitType.Star)
        grid.ColumnDefinitions.Add(col1)
        
        # Right buttons
        col2 = ColumnDefinition()
        col2.Width = GridLength.Auto
        grid.ColumnDefinitions.Add(col2)
        
        # Left panel - Selection actions
        left_panel = StackPanel()
        left_panel.Orientation = Orientation.Horizontal
        
        btn_select_all = self._create_button("Select All", self._on_select_all)
        btn_select_all.Margin = Thickness(0, 0, 8, 0)
        left_panel.Children.Add(btn_select_all)
        
        btn_select_none = self._create_button("Select None", self._on_select_none)
        btn_select_none.Margin = Thickness(0, 0, 8, 0)
        left_panel.Children.Add(btn_select_none)
        
        left_panel.Children.Add(self._create_separator())
        
        btn_expand = self._create_button("Expand All", self._on_expand_all)
        btn_expand.Margin = Thickness(8, 0, 8, 0)
        left_panel.Children.Add(btn_expand)
        
        btn_collapse = self._create_button("Collapse All", self._on_collapse_all)
        left_panel.Children.Add(btn_collapse)
        
        Grid.SetColumn(left_panel, 0)
        grid.Children.Add(left_panel)
        
        # Right panel - Main actions
        right_panel = StackPanel()
        right_panel.Orientation = Orientation.Horizontal
        
        btn_show = self._create_button("👁 Show Elements", self._on_show_elements, is_primary=True)
        btn_show.Margin = Thickness(0, 0, 8, 0)
        right_panel.Children.Add(btn_show)
        
        btn_select = self._create_button("✓ Select in Model", self._on_select_in_model, is_primary=True)
        right_panel.Children.Add(btn_select)
        
        Grid.SetColumn(right_panel, 1)
        grid.Children.Add(right_panel)
        
        border.Child = grid
        return border
    
    def _build_footer(self):
        """Build footer with copyright"""
        grid = Grid()
        
        col1 = ColumnDefinition()
        col1.Width = GridLength(1, GridUnitType.Star)
        grid.ColumnDefinitions.Add(col1)
        
        col2 = ColumnDefinition()
        col2.Width = GridLength.Auto
        grid.ColumnDefinitions.Add(col2)
        
        # Tip text
        tip = TextBlock()
        tip.Text = "💡 Double-click to zoom to element | Right-click for options"
        tip.FontSize = 11
        tip.Foreground = SB(C.TEXT_SEC)
        tip.VerticalAlignment = VerticalAlignment.Center
        Grid.SetColumn(tip, 0)
        grid.Children.Add(tip)
        
        # Copyright
        copyright_text = TextBlock()
        copyright_text.Text = "© 2025 Dang Quoc Truong - DQT"
        copyright_text.FontSize = 10
        copyright_text.Foreground = SB(C.TEXT_LIGHT)
        copyright_text.VerticalAlignment = VerticalAlignment.Center
        Grid.SetColumn(copyright_text, 1)
        grid.Children.Add(copyright_text)
        
        return grid
    
    def _create_button(self, text, click_handler, is_primary=False):
        """Create a styled button"""
        btn = Button()
        btn.Content = text
        btn.FontSize = 12
        btn.Padding = Thickness(12, 6, 12, 6)
        btn.Cursor = Cursors.Hand
        
        if is_primary:
            btn.Background = SB(C.ACCENT)
            btn.Foreground = SB(C.BG_WHITE)
        else:
            btn.Background = SB(C.BG_WHITE)
            btn.Foreground = SB(C.TEXT)
        
        btn.BorderBrush = SB(C.BORDER)
        btn.BorderThickness = Thickness(1)
        btn.Click += click_handler
        
        return btn
    
    def _create_separator(self):
        """Create a vertical separator"""
        border = Border()
        border.Width = 1
        border.Background = SB(C.BORDER)
        border.Margin = Thickness(0, 2, 0, 2)
        return border
    
    # =========================================================================
    # DATA LOADING
    # =========================================================================
    
    def _load_data(self):
        """Load data based on current display mode"""
        try:
            # Collect elements
            if self.current_display_mode == "Entire Project":
                self.all_elements = self.collector.collect_entire_project()
            elif self.current_display_mode == "Active View":
                self.all_elements = self.collector.collect_active_view()
            else:  # Current Selection
                self.all_elements = self.collector.collect_current_selection()
            
            # Build tree
            self.tree_data = self.collector.build_tree_structure(self.all_elements)
            
            # Update UI
            self._populate_tree()
            self._update_stats()
            
        except Exception as e:
            print("Error loading data: {}".format(str(e)))
            traceback.print_exc()
    
    def _populate_tree(self, filter_text=""):
        """Populate the TreeView with data"""
        self.tree_view.Items.Clear()
        
        filter_lower = filter_text.lower() if filter_text else ""
        
        for cat_node in self.tree_data:
            # Filter check at category level
            if filter_lower and filter_lower not in cat_node.name.lower():
                # Check if any child matches
                has_match = False
                for fam_node in cat_node.children:
                    if filter_lower in fam_node.name.lower():
                        has_match = True
                        break
                    for type_node in fam_node.children:
                        if filter_lower in type_node.name.lower():
                            has_match = True
                            break
                    if has_match:
                        break
                
                if not has_match:
                    continue
            
            # Create category item
            cat_item = self._create_tree_item(
                "📁 {} ({})".format(cat_node.name, cat_node.count),
                cat_node,
                is_category=True
            )
            
            # Add families
            for fam_node in sorted(cat_node.children, key=lambda x: x.name):
                if filter_lower and filter_lower not in fam_node.name.lower() and filter_lower not in cat_node.name.lower():
                    # Check if any type matches
                    has_type_match = False
                    for type_node in fam_node.children:
                        if filter_lower in type_node.name.lower():
                            has_type_match = True
                            break
                    if not has_type_match:
                        continue
                
                fam_item = self._create_tree_item(
                    "📦 {} ({})".format(fam_node.name, fam_node.count),
                    fam_node
                )
                
                # Add types
                for type_node in sorted(fam_node.children, key=lambda x: x.name):
                    if filter_lower and filter_lower not in type_node.name.lower() and \
                       filter_lower not in fam_node.name.lower() and \
                       filter_lower not in cat_node.name.lower():
                        continue
                    
                    type_item = self._create_tree_item(
                        "📄 {} ({})".format(type_node.name, type_node.count),
                        type_node
                    )
                    
                    # Add instances
                    for elem_item in type_node.elements:
                        instance_item = self._create_tree_item(
                            "• {}".format(elem_item.display_name),
                            InstanceNode(elem_item),
                            is_instance=True
                        )
                        type_item.Items.Add(instance_item)
                    
                    fam_item.Items.Add(type_item)
                
                if fam_item.Items.Count > 0:
                    cat_item.Items.Add(fam_item)
            
            if cat_item.Items.Count > 0:
                self.tree_view.Items.Add(cat_item)
    
    def _create_tree_item(self, text, node, is_category=False, is_instance=False):
        """Create a TreeViewItem"""
        item = TreeViewItem()
        item.Header = text
        item.Tag = node
        item.IsExpanded = is_category  # Expand categories by default
        
        if is_category:
            item.FontWeight = FontWeights.SemiBold
        elif is_instance:
            item.Foreground = SB(C.TEXT_SEC)
        
        return item
    
    def _update_stats(self):
        """Update statistics display"""
        total = len(self.all_elements)
        categories = len(self.tree_data)
        selected = len(self.selected_elements)
        
        if self.txt_total:
            self.txt_total.Text = "{:,}".format(total)
        if self.txt_categories:
            self.txt_categories.Text = str(categories)
        if self.txt_selected:
            self.txt_selected.Text = str(selected)
    
    # =========================================================================
    # EVENT HANDLERS
    # =========================================================================
    
    def _on_display_changed(self, sender, args):
        """Handle display mode change"""
        if self.cmb_display.SelectedItem:
            self.current_display_mode = self.cmb_display.SelectedItem.Content
            self._load_data()
    
    def _on_search_focus(self, sender, args):
        """Handle search box focus"""
        if self.txt_search.Foreground.Color == C.TEXT_LIGHT:
            self.txt_search.Text = ""
            self.txt_search.Foreground = SB(C.TEXT)
    
    def _on_search_blur(self, sender, args):
        """Handle search box blur"""
        if not self.txt_search.Text:
            self.txt_search.Foreground = SB(C.TEXT_LIGHT)
            self.txt_search.Text = ""
    
    def _on_search_changed(self, sender, args):
        """Handle search text change"""
        search_text = self.txt_search.Text if self.txt_search.Foreground.Color != C.TEXT_LIGHT else ""
        self._populate_tree(search_text)
    
    def _on_refresh_click(self, sender, args):
        """Refresh data"""
        self._load_data()
        self._show_message("Data refreshed!", "Quick Select")
    
    def _on_tree_double_click(self, sender, args):
        """Handle double-click on tree item"""
        selected_item = self.tree_view.SelectedItem
        if selected_item and selected_item.Tag:
            node = selected_item.Tag
            
            if isinstance(node, InstanceNode):
                # Zoom to single element
                elem_item = node.element_item
                self.navigator.show_element(elem_item.id)
    
    def _on_show_elements(self, sender, args):
        """Show/zoom to selected elements"""
        elements = self._get_selected_elements()
        
        if not elements:
            self._show_message("Please select elements from the tree first.", "No Selection")
            return
        
        if len(elements) == 1:
            # Single element - zoom to it
            self.navigator.show_element(elements[0].id)
        else:
            # Multiple elements - select and zoom to first
            self.navigator.select_elements([e.id for e in elements])
            self.navigator.show_element(elements[0].id)
    
    def _on_select_in_model(self, sender, args):
        """Select elements in Revit model"""
        elements = self._get_selected_elements()
        
        if not elements:
            self._show_message("Please select elements from the tree first.", "No Selection")
            return
        
        self.navigator.select_elements([e.id for e in elements])
        self.selected_elements = elements
        self._update_stats()
        
        self._show_message("{} element(s) selected in model.".format(len(elements)), "Selection")
    
    def _on_select_all(self, sender, args):
        """Select all elements at selected tree level"""
        # Select all visible in current filter
        all_ids = [e.id for e in self.all_elements]
        self.navigator.select_elements(all_ids)
        self.selected_elements = self.all_elements[:]
        self._update_stats()
    
    def _on_select_none(self, sender, args):
        """Clear selection"""
        self.navigator.select_elements([])
        self.selected_elements = []
        self._update_stats()
    
    def _on_expand_all(self, sender, args):
        """Expand all tree nodes"""
        self._set_all_expanded(self.tree_view, True)
    
    def _on_collapse_all(self, sender, args):
        """Collapse all tree nodes"""
        self._set_all_expanded(self.tree_view, False)
    
    def _set_all_expanded(self, parent, expanded):
        """Recursively set expanded state"""
        for item in parent.Items:
            if isinstance(item, TreeViewItem):
                item.IsExpanded = expanded
                self._set_all_expanded(item, expanded)
    
    def _get_selected_elements(self):
        """Get elements from selected tree item"""
        selected_item = self.tree_view.SelectedItem
        if not selected_item or not selected_item.Tag:
            return []
        
        node = selected_item.Tag
        return node.get_all_elements()
    
    def _show_message(self, message, title="Quick Select"):
        """Show message dialog"""
        MessageBox.Show(message, title)


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================
def main():
    """Main entry point"""
    try:
        window = QuickSelectWindow()
        window.ShowDialog()
    except Exception as e:
        print("Error: {}".format(str(e)))
        traceback.print_exc()
        forms.alert("Error launching Quick Select:\n{}".format(str(e)), title="Error")

if __name__ == "__main__":
    main()