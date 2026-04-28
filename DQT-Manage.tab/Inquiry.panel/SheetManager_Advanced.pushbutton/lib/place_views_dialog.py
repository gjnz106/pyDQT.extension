# -*- coding: utf-8 -*-
"""
Sheet Manager - Place Views Dialog (WITH EXCEL MAPPING)

Copyright (c) Dang Quoc Truong (DQT)
"""

from System.Windows import Window, MessageBox, MessageBoxButton, MessageBoxImage, Thickness, GridLength
from System.Windows.Controls import (Grid, Label, Button, TextBox, ListBox, RadioButton, 
                                      ComboBox, StackPanel, RowDefinition, ColumnDefinition, GroupBox, CheckBox)
import System


class PlaceViewsDialog(Window):
    """Dialog for placing views on sheets"""
    
    def __init__(self, place_views_service, doc, selected_sheets):
        self.place_views_service = place_views_service
        self.doc = doc
        self.selected_sheets = selected_sheets
        self.all_views = []
        self.selected_views = []
        self.excel_file_path = None
        
        self._build_ui()
        self._load_views()
    
    def _build_ui(self):
        """Build dialog UI"""
        self.Title = "Place Views on Sheets"
        self.Width = 900
        self.Height = 700
        self.WindowStartupLocation = System.Windows.WindowStartupLocation.CenterScreen
        
        # Main grid
        main_grid = Grid()
        main_grid.Margin = Thickness(20)
        main_grid.RowDefinitions.Add(RowDefinition(Height=GridLength(40)))  # Info
        main_grid.RowDefinitions.Add(RowDefinition(Height=GridLength(1, System.Windows.GridUnitType.Star)))  # Content
        main_grid.RowDefinitions.Add(RowDefinition(Height=GridLength(50)))  # Buttons
        
        # Info label
        self.info_label = Label()
        self.info_label.Content = "Select views to place on {} sheet(s)".format(len(self.selected_sheets))
        self.info_label.FontSize = 14
        self.info_label.FontWeight = System.Windows.FontWeights.Bold
        Grid.SetRow(self.info_label, 0)
        main_grid.Children.Add(self.info_label)
        
        # Content grid
        content_grid = Grid()
        content_grid.ColumnDefinitions.Add(ColumnDefinition(Width=GridLength(400)))
        content_grid.ColumnDefinitions.Add(ColumnDefinition(Width=GridLength(20)))
        content_grid.ColumnDefinitions.Add(ColumnDefinition(Width=GridLength(1, System.Windows.GridUnitType.Star)))
        Grid.SetRow(content_grid, 1)
        
        # Left - Views list
        left_panel = Grid()
        left_panel.RowDefinitions.Add(RowDefinition(Height=GridLength(40)))
        left_panel.RowDefinitions.Add(RowDefinition(Height=GridLength(40)))
        left_panel.RowDefinitions.Add(RowDefinition(Height=GridLength(1, System.Windows.GridUnitType.Star)))
        left_panel.RowDefinitions.Add(RowDefinition(Height=GridLength(50)))
        Grid.SetColumn(left_panel, 0)
        
        views_label = Label()
        views_label.Content = "Available Views:"
        views_label.FontWeight = System.Windows.FontWeights.Bold
        Grid.SetRow(views_label, 0)
        left_panel.Children.Add(views_label)
        
        # Filter
        filter_panel = StackPanel()
        filter_panel.Orientation = System.Windows.Controls.Orientation.Horizontal
        Grid.SetRow(filter_panel, 1)
        
        filter_label = Label()
        filter_label.Content = "Filter:"
        filter_label.Width = 50
        filter_panel.Children.Add(filter_label)
        
        self.filter_combo = ComboBox()
        self.filter_combo.Width = 150
        self.filter_combo.Items.Add("All Views")
        self.filter_combo.Items.Add("Not on Sheets")
        self.filter_combo.Items.Add("Floor Plans")
        self.filter_combo.Items.Add("Sections")
        self.filter_combo.Items.Add("Elevations")
        self.filter_combo.SelectedIndex = 1  # Default: Not on sheets
        self.filter_combo.SelectionChanged += self.on_filter_changed
        filter_panel.Children.Add(self.filter_combo)
        
        left_panel.Children.Add(filter_panel)
        
        # Views listbox
        from System.Windows.Controls import ScrollViewer
        scroll = ScrollViewer()
        scroll.VerticalScrollBarVisibility = System.Windows.Controls.ScrollBarVisibility.Auto
        Grid.SetRow(scroll, 2)
        
        self.views_panel = StackPanel()
        scroll.Content = self.views_panel
        left_panel.Children.Add(scroll)
        
        # Select buttons
        select_panel = StackPanel()
        select_panel.Orientation = System.Windows.Controls.Orientation.Horizontal
        select_panel.HorizontalAlignment = System.Windows.HorizontalAlignment.Center
        Grid.SetRow(select_panel, 3)
        
        select_all_btn = Button()
        select_all_btn.Content = "Select All"
        select_all_btn.Width = 90
        select_all_btn.Height = 30
        select_all_btn.Margin = Thickness(5, 0, 5, 0)
        select_all_btn.Click += self.on_select_all_views
        select_panel.Children.Add(select_all_btn)
        
        select_none_btn = Button()
        select_none_btn.Content = "Select None"
        select_none_btn.Width = 90
        select_none_btn.Height = 30
        select_none_btn.Margin = Thickness(5, 0, 5, 0)
        select_none_btn.Click += self.on_select_none_views
        select_panel.Children.Add(select_none_btn)
        
        left_panel.Children.Add(select_panel)
        content_grid.Children.Add(left_panel)
        
        # Right - Options
        right_panel = Grid()
        right_panel.RowDefinitions.Add(RowDefinition(Height=GridLength.Auto))  # Mode selection
        right_panel.RowDefinitions.Add(RowDefinition(Height=GridLength(1, System.Windows.GridUnitType.Star)))  # Manual options
        right_panel.RowDefinitions.Add(RowDefinition(Height=GridLength(1, System.Windows.GridUnitType.Star)))  # Arrangement / Excel panel
        Grid.SetColumn(right_panel, 2)
        
        # Mode Selection Group (Manual vs Excel)
        mode_selection_group = GroupBox()
        mode_selection_group.Header = "Placement Method"
        mode_selection_group.Margin = Thickness(0, 0, 0, 10)
        Grid.SetRow(mode_selection_group, 0)
        
        mode_selection_panel = StackPanel()
        mode_selection_panel.Margin = Thickness(10)
        
        self.method_manual = RadioButton()
        self.method_manual.Content = "Manual Selection"
        self.method_manual.IsChecked = True
        self.method_manual.Margin = Thickness(0, 5, 0, 5)
        self.method_manual.Checked += self.on_method_changed
        mode_selection_panel.Children.Add(self.method_manual)
        
        manual_desc = Label()
        manual_desc.Content = "  Select views and placement mode below"
        manual_desc.Foreground = System.Windows.Media.Brushes.Gray
        manual_desc.Margin = Thickness(20, 0, 0, 10)
        mode_selection_panel.Children.Add(manual_desc)
        
        self.method_excel = RadioButton()
        self.method_excel.Content = "From Excel File"
        self.method_excel.Margin = Thickness(0, 5, 0, 5)
        self.method_excel.Checked += self.on_method_changed
        mode_selection_panel.Children.Add(self.method_excel)
        
        excel_desc = Label()
        excel_desc.Content = "  Load Sheet → View mapping from Excel"
        excel_desc.Foreground = System.Windows.Media.Brushes.Gray
        excel_desc.Margin = Thickness(20, 0, 0, 10)
        mode_selection_panel.Children.Add(excel_desc)
        
        mode_selection_group.Content = mode_selection_panel
        right_panel.Children.Add(mode_selection_group)
        
        # Manual Placement Mode Panel
        self.manual_mode_group = GroupBox()
        self.manual_mode_group.Header = "Placement Mode"
        self.manual_mode_group.Margin = Thickness(0, 0, 0, 10)
        Grid.SetRow(self.manual_mode_group, 1)
        
        mode_panel = StackPanel()
        mode_panel.Margin = Thickness(10)
        
        self.mode_one_per_sheet = RadioButton()
        self.mode_one_per_sheet.Content = "One view per sheet"
        self.mode_one_per_sheet.IsChecked = True
        self.mode_one_per_sheet.Margin = Thickness(0, 5, 0, 5)
        mode_panel.Children.Add(self.mode_one_per_sheet)
        
        desc1 = Label()
        desc1.Content = "  Place one view on each sheet"
        desc1.Foreground = System.Windows.Media.Brushes.Gray
        desc1.Margin = Thickness(20, 0, 0, 10)
        mode_panel.Children.Add(desc1)
        
        self.mode_all_on_each = RadioButton()
        self.mode_all_on_each.Content = "All views on each sheet"
        self.mode_all_on_each.Margin = Thickness(0, 5, 0, 5)
        mode_panel.Children.Add(self.mode_all_on_each)
        
        desc2 = Label()
        desc2.Content = "  Place all views on every sheet"
        desc2.Foreground = System.Windows.Media.Brushes.Gray
        desc2.Margin = Thickness(20, 0, 0, 10)
        mode_panel.Children.Add(desc2)
        
        self.mode_distribute = RadioButton()
        self.mode_distribute.Content = "Distribute evenly"
        self.mode_distribute.Margin = Thickness(0, 5, 0, 5)
        mode_panel.Children.Add(self.mode_distribute)
        
        desc3 = Label()
        desc3.Content = "  Distribute views across sheets"
        desc3.Foreground = System.Windows.Media.Brushes.Gray
        desc3.Margin = Thickness(20, 0, 0, 10)
        mode_panel.Children.Add(desc3)
        
        self.manual_mode_group.Content = mode_panel
        right_panel.Children.Add(self.manual_mode_group)
        
        # Manual Arrangement / Excel Panel (switches based on mode)
        self.arrangement_excel_container = Grid()
        Grid.SetRow(self.arrangement_excel_container, 2)
        
        # Manual Arrangement Panel
        self.arrange_group = GroupBox()
        self.arrange_group.Header = "Auto-Arrange"
        
        arrange_panel = StackPanel()
        arrange_panel.Margin = Thickness(10)
        
        grid_label = Label()
        grid_label.Content = "Grid Layout:"
        grid_label.FontWeight = System.Windows.FontWeights.Bold
        arrange_panel.Children.Add(grid_label)
        
        grid_options = StackPanel()
        grid_options.Orientation = System.Windows.Controls.Orientation.Horizontal
        grid_options.Margin = Thickness(0, 10, 0, 10)
        
        rows_label = Label()
        rows_label.Content = "Rows:"
        rows_label.Width = 50
        grid_options.Children.Add(rows_label)
        
        self.rows_combo = ComboBox()
        self.rows_combo.Width = 60
        for i in range(1, 5):
            self.rows_combo.Items.Add(i)
        self.rows_combo.SelectedIndex = 1  # Default: 2 rows
        grid_options.Children.Add(self.rows_combo)
        
        cols_label = Label()
        cols_label.Content = "  Columns:"
        cols_label.Width = 80
        grid_options.Children.Add(cols_label)
        
        self.cols_combo = ComboBox()
        self.cols_combo.Width = 60
        for i in range(1, 5):
            self.cols_combo.Items.Add(i)
        self.cols_combo.SelectedIndex = 1  # Default: 2 cols
        grid_options.Children.Add(self.cols_combo)
        
        arrange_panel.Children.Add(grid_options)
        
        preview_label = Label()
        preview_label.Content = "Views will be arranged in a 2x2 grid\non each sheet"
        preview_label.Foreground = System.Windows.Media.Brushes.Gray
        arrange_panel.Children.Add(preview_label)
        
        self.arrange_group.Content = arrange_panel
        self.arrangement_excel_container.Children.Add(self.arrange_group)
        
        # Excel Panel
        self.excel_group = GroupBox()
        self.excel_group.Header = "Excel File Mapping"
        self.excel_group.Visibility = System.Windows.Visibility.Collapsed
        
        excel_panel = StackPanel()
        excel_panel.Margin = Thickness(10)
        
        excel_info = Label()
        excel_info.Content = "Excel file format:"
        excel_info.FontWeight = System.Windows.FontWeights.Bold
        excel_panel.Children.Add(excel_info)
        
        excel_format = Label()
        excel_format.Content = """Column A: Sheet Name
Column B: View Name

Example:
LPL_3500 | DRAWING LIST
LPL_3510 | UPS BATTERY ROOM 2"""
        excel_format.Foreground = System.Windows.Media.Brushes.Gray
        excel_format.Margin = Thickness(0, 5, 0, 15)
        excel_panel.Children.Add(excel_format)
        
        # File picker
        file_picker_panel = StackPanel()
        file_picker_panel.Orientation = System.Windows.Controls.Orientation.Horizontal
        file_picker_panel.Margin = Thickness(0, 10, 0, 10)
        
        file_label = Label()
        file_label.Content = "File:"
        file_label.Width = 50
        file_picker_panel.Children.Add(file_label)
        
        self.file_path_box = TextBox()
        self.file_path_box.Width = 250
        self.file_path_box.IsReadOnly = True
        self.file_path_box.Background = System.Windows.Media.Brushes.LightGray
        file_picker_panel.Children.Add(self.file_path_box)
        
        browse_btn = Button()
        browse_btn.Content = "Browse..."
        browse_btn.Width = 80
        browse_btn.Margin = Thickness(10, 0, 0, 0)
        browse_btn.Click += self.on_browse_excel
        file_picker_panel.Children.Add(browse_btn)
        
        excel_panel.Children.Add(file_picker_panel)
        
        # Status
        self.excel_status_label = Label()
        self.excel_status_label.Content = "No file selected"
        self.excel_status_label.Foreground = System.Windows.Media.Brushes.Gray
        excel_panel.Children.Add(self.excel_status_label)
        
        self.excel_group.Content = excel_panel
        self.arrangement_excel_container.Children.Add(self.excel_group)
        
        right_panel.Children.Add(self.arrangement_excel_container)
        
        content_grid.Children.Add(right_panel)
        main_grid.Children.Add(content_grid)
        
        # Buttons
        btn_panel = StackPanel()
        btn_panel.Orientation = System.Windows.Controls.Orientation.Horizontal
        btn_panel.HorizontalAlignment = System.Windows.HorizontalAlignment.Right
        Grid.SetRow(btn_panel, 2)
        
        self.place_btn = Button()
        self.place_btn.Content = "Place Views"
        self.place_btn.Width = 120
        self.place_btn.Height = 35
        self.place_btn.Margin = Thickness(0, 0, 10, 0)
        self.place_btn.Click += self.on_place_click
        btn_panel.Children.Add(self.place_btn)
        
        cancel_btn = Button()
        cancel_btn.Content = "Cancel"
        cancel_btn.Width = 100
        cancel_btn.Height = 35
        cancel_btn.Click += self.on_cancel_click
        btn_panel.Children.Add(cancel_btn)
        
        main_grid.Children.Add(btn_panel)
        self.Content = main_grid
    
    def on_method_changed(self, sender, args):
        """Toggle between manual and Excel mode"""
        if self.method_manual.IsChecked:
            # Show manual controls
            self.manual_mode_group.Visibility = System.Windows.Visibility.Visible
            self.arrange_group.Visibility = System.Windows.Visibility.Visible
            self.excel_group.Visibility = System.Windows.Visibility.Collapsed
            self.info_label.Content = "Select views to place on {} sheet(s)".format(len(self.selected_sheets))
        else:
            # Show Excel controls
            self.manual_mode_group.Visibility = System.Windows.Visibility.Collapsed
            self.arrange_group.Visibility = System.Windows.Visibility.Collapsed
            self.excel_group.Visibility = System.Windows.Visibility.Visible
            self.info_label.Content = "Load Excel file with Sheet → View mapping"
    
    def on_browse_excel(self, sender, args):
        """Browse for Excel file"""
        from System.Windows.Forms import OpenFileDialog, DialogResult
        
        dialog = OpenFileDialog()
        dialog.Filter = "Excel Files (*.xlsx;*.xls)|*.xlsx;*.xls|All Files (*.*)|*.*"
        dialog.Title = "Select Excel File with Sheet-View Mapping"
        
        if dialog.ShowDialog() == DialogResult.OK:
            self.excel_file_path = dialog.FileName
            self.file_path_box.Text = self.excel_file_path
            
            # Try to read and validate
            try:
                mapping = self._read_excel_mapping(self.excel_file_path)
                count = len(mapping)
                self.excel_status_label.Content = "{} mappings loaded successfully".format(count)
                self.excel_status_label.Foreground = System.Windows.Media.Brushes.Green
            except Exception as e:
                self.excel_status_label.Content = "Error: {}".format(str(e))
                self.excel_status_label.Foreground = System.Windows.Media.Brushes.Red
                self.excel_file_path = None
    
    def _read_excel_mapping(self, file_path):
        """Read Excel file and return sheet → view mapping"""
        import zipfile
        import xml.etree.ElementTree as ET
        
        # Read Excel as ZIP
        mapping = {}
        
        with zipfile.ZipFile(file_path, 'r') as zip_file:
            # Read shared strings
            shared_strings = []
            try:
                with zip_file.open('xl/sharedStrings.xml') as f:
                    tree = ET.parse(f)
                    root = tree.getroot()
                    ns = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
                    for si in root.findall('x:si', ns):
                        t = si.find('x:t', ns)
                        if t is not None:
                            shared_strings.append(t.text)
            except:
                pass  # No shared strings
            
            # Read first sheet
            with zip_file.open('xl/worksheets/sheet1.xml') as f:
                tree = ET.parse(f)
                root = tree.getroot()
                ns = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
                
                for row in root.findall('.//x:row', ns):
                    cells = list(row.findall('x:c', ns))
                    if len(cells) >= 2:
                        # Get column A (sheet name)
                        cell_a = cells[0]
                        sheet_name = None
                        
                        if cell_a.get('t') == 's':  # Shared string
                            v = cell_a.find('x:v', ns)
                            if v is not None:
                                idx = int(v.text)
                                if idx < len(shared_strings):
                                    sheet_name = shared_strings[idx]
                        else:  # Inline string
                            v = cell_a.find('x:v', ns)
                            if v is not None:
                                sheet_name = v.text
                        
                        # Get column B (view name)
                        cell_b = cells[1]
                        view_name = None
                        
                        if cell_b.get('t') == 's':  # Shared string
                            v = cell_b.find('x:v', ns)
                            if v is not None:
                                idx = int(v.text)
                                if idx < len(shared_strings):
                                    view_name = shared_strings[idx]
                        else:  # Inline string
                            v = cell_b.find('x:v', ns)
                            if v is not None:
                                view_name = v.text
                        
                        if sheet_name and view_name:
                            mapping[sheet_name.strip()] = view_name.strip()
        
        if not mapping:
            raise Exception("No valid mappings found in Excel file")
        
        return mapping
    
    def _load_views(self):
        """Load available views"""
        from Autodesk.Revit.DB import FilteredElementCollector, View, ViewType
        
        collector = FilteredElementCollector(self.doc).OfClass(View)
        
        for view in collector:
            if view.IsTemplate:
                continue
            
            # Skip system views
            view_type = view.ViewType
            if view_type in [ViewType.DrawingSheet, ViewType.ProjectBrowser, 
                           ViewType.SystemBrowser, ViewType.Internal]:
                continue
            
            self.all_views.append(view)
        
        self._update_views_display()
    
    def _update_views_display(self):
        """Update views display based on filter"""
        self.views_panel.Children.Clear()
        
        filter_text = str(self.filter_combo.SelectedItem) if self.filter_combo.SelectedIndex >= 0 else "All Views"
        
        for view in self.all_views:
            # Apply filter
            if filter_text == "Not on Sheets":
                # Check if view is on any sheet
                from Autodesk.Revit.DB import FilteredElementCollector, ViewSheet
                is_on_sheet = False
                for sheet in FilteredElementCollector(self.doc).OfClass(ViewSheet):
                    view_ids = sheet.GetAllPlacedViews()
                    if view.Id in view_ids:
                        is_on_sheet = True
                        break
                if is_on_sheet:
                    continue
            elif filter_text == "Floor Plans":
                if str(view.ViewType) != "FloorPlan":
                    continue
            elif filter_text == "Sections":
                if str(view.ViewType) != "Section":
                    continue
            elif filter_text == "Elevations":
                if str(view.ViewType) != "Elevation":
                    continue
            
            # Create checkbox for view
            cb = CheckBox()
            cb.Content = "{} [{}]".format(view.Name, str(view.ViewType))
            cb.Tag = view
            cb.Margin = Thickness(5, 2, 5, 2)
            self.views_panel.Children.Add(cb)
    
    def on_filter_changed(self, sender, args):
        """Handle filter change"""
        self._update_views_display()
    
    def on_select_all_views(self, sender, args):
        """Select all views"""
        for child in self.views_panel.Children:
            if isinstance(child, CheckBox):
                child.IsChecked = True
    
    def on_select_none_views(self, sender, args):
        """Deselect all views"""
        for child in self.views_panel.Children:
            if isinstance(child, CheckBox):
                child.IsChecked = False
    
    def on_place_click(self, sender, args):
        """Place views on sheets"""
        try:
            if self.method_excel.IsChecked:
                # Excel mode
                if not self.excel_file_path:
                    MessageBox.Show("Please select an Excel file first.", "No File Selected",
                                  MessageBoxButton.OK, MessageBoxImage.Warning)
                    return
                
                self._place_from_excel()
            else:
                # Manual mode
                self._place_manual()
            
        except Exception as e:
            MessageBox.Show("Error: {}".format(str(e)), "Error",
                          MessageBoxButton.OK, MessageBoxImage.Error)
            import traceback
            traceback.print_exc()
    
    def _place_from_excel(self):
        """Place views based on Excel mapping"""
        from Autodesk.Revit.DB import Transaction, FilteredElementCollector, ViewSheet, View
        
        # Read mapping
        try:
            mapping = self._read_excel_mapping(self.excel_file_path)
        except Exception as e:
            MessageBox.Show("Failed to read Excel file:\n{}".format(str(e)), "Error",
                          MessageBoxButton.OK, MessageBoxImage.Error)
            return
        
        # Get all sheets and views as dictionaries
        all_sheets = {}
        for sheet in FilteredElementCollector(self.doc).OfClass(ViewSheet):
            if not sheet.IsTemplate:
                all_sheets[sheet.Name] = sheet  # Use Sheet Name instead of SheetNumber
        
        all_views = {}
        for view in FilteredElementCollector(self.doc).OfClass(View):
            if not view.IsTemplate:
                all_views[view.Name] = view
        
        # Match and place
        success_count = 0
        error_count = 0
        errors = []
        
        t = Transaction(self.doc, "DQT - Place Views from Excel")
        t.Start()
        
        try:
            for sheet_name, view_name in mapping.items():
                # Find sheet
                sheet = all_sheets.get(sheet_name)
                if not sheet:
                    errors.append("Sheet not found: {}".format(sheet_name))
                    error_count += 1
                    continue
                
                # Find view
                view = all_views.get(view_name)
                if not view:
                    errors.append("View not found: {}".format(view_name))
                    error_count += 1
                    continue
                
                # Check if view can be placed
                from Autodesk.Revit.DB import ViewType
                if view.ViewType in [ViewType.DrawingSheet, ViewType.ProjectBrowser,
                                   ViewType.SystemBrowser, ViewType.Internal]:
                    errors.append("Cannot place system view: {}".format(view_name))
                    error_count += 1
                    continue
                
                # Place view
                try:
                    from Autodesk.Revit.DB import XYZ, Viewport, UV
                    
                    # Simple center placement
                    center = XYZ(0, 0, 0)
                    viewport = Viewport.Create(self.doc, sheet.Id, view.Id, center)
                    
                    if viewport:
                        success_count += 1
                    else:
                        errors.append("Failed to place {} on {}".format(view_name, sheet_name))
                        error_count += 1
                except Exception as e:
                    errors.append("{} → {}: {}".format(sheet_name, view_name, str(e)))
                    error_count += 1
            
            t.Commit()
            
            # Show results
            result_msg = "Placement complete!\n\n"
            result_msg += "Success: {} views placed\n".format(success_count)
            result_msg += "Errors: {}\n".format(error_count)
            
            if errors and len(errors) <= 10:
                result_msg += "\nErrors:\n" + "\n".join(errors)
            elif errors:
                result_msg += "\nFirst 10 errors:\n" + "\n".join(errors[:10])
                result_msg += "\n... and {} more".format(len(errors) - 10)
            
            MessageBox.Show(result_msg, "Placement Results",
                          MessageBoxButton.OK, MessageBoxImage.Information)
            
            if success_count > 0:
                self.Close()
                
        except Exception as e:
            t.RollBack()
            raise
    
    def _place_manual(self):
        """Place views manually (original logic)"""
        # Get selected views
        selected_views = []
        for child in self.views_panel.Children:
            if isinstance(child, CheckBox) and child.IsChecked:
                selected_views.append(child.Tag)
        
        if not selected_views:
            MessageBox.Show("Please select at least one view to place.", "No Views Selected",
                          MessageBoxButton.OK, MessageBoxImage.Information)
            return
        
        # Get placement mode
        if self.mode_one_per_sheet.IsChecked:
            mode = "one_per_sheet"
        elif self.mode_all_on_each.IsChecked:
            mode = "all_on_each"
        else:
            mode = "distribute"
        
        # Get grid layout
        rows = self.rows_combo.SelectedItem if self.rows_combo.SelectedIndex >= 0 else 2
        cols = self.cols_combo.SelectedItem if self.cols_combo.SelectedIndex >= 0 else 2
        
        # Place views using service
        try:
            from Autodesk.Revit.DB import Transaction
            
            t = Transaction(self.doc, "DQT - Place Views")
            t.Start()
            
            success_count = self.place_views_service.place_views(
                self.selected_sheets,
                selected_views,
                mode,
                rows,
                cols
            )
            
            t.Commit()
            
            MessageBox.Show("Successfully placed {} views".format(success_count), "Success",
                          MessageBoxButton.OK, MessageBoxImage.Information)
            
            self.Close()
            
        except Exception as e:
            t.RollBack()
            raise
    
    def on_cancel_click(self, sender, args):
        """Cancel dialog"""
        self.Close()