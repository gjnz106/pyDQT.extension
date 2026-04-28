# -*- coding: utf-8 -*-
"""
Schedule Link Pro - Export/Import Schedule to Excel
Copyright (c) 2025 by Dang Quoc Truong (DQT)

DiRoots-style: Read data directly from elements, not from schedule cells
"""

__title__ = "Schedule\nLink Pro"
__doc__ = "Export Schedule to Excel, edit and import back"
__author__ = "Dang Quoc Truong (DQT)"

import os
import traceback

import clr
clr.AddReference('System.Windows.Forms')
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')
clr.AddReference('Microsoft.Office.Interop.Excel')

from System.Windows.Forms import (
    OpenFileDialog, SaveFileDialog, DialogResult, MessageBox,
    MessageBoxButtons, MessageBoxIcon
)
from System.Windows import (
    Window, Thickness, TextWrapping, HorizontalAlignment, 
    VerticalAlignment, GridLength, Visibility, FontWeights
)
from System.Windows.Controls import (
    StackPanel, DockPanel, Grid, RowDefinition, ColumnDefinition,
    Button, TextBlock, ComboBox, ComboBoxItem, Border, ScrollViewer,
    ProgressBar, CheckBox, ListBox, ListBoxItem, SelectionMode
)
from System.Windows.Media import SolidColorBrush
from System.Windows.Media import Color as WpfColor

import Microsoft.Office.Interop.Excel as Excel

from Autodesk.Revit.DB import (
    FilteredElementCollector, ViewSchedule, ScheduleFieldType,
    Transaction, ElementId, BuiltInParameter, StorageType, Element
)

from pyrevit import revit

import System

doc = revit.doc

# =============================================================================
# CONSTANTS
# =============================================================================
PRIMARY = "#FFE6A800"
BACKGROUND = "#FFFEF8E7"  
WHITE = "#FFFFFFFF"
GRAY = "#FF808080"
RED = "#FFFF0000"
GREEN = "#FF008000"
COPYRIGHT = "Copyright (c) 2025 by Dang Quoc Truong (DQT)"

DEBUG_LOG = []
UPDATE_LOG = []

def log_debug(msg):
    global DEBUG_LOG
    DEBUG_LOG.append(str(msg))

def log_update(msg):
    global UPDATE_LOG
    UPDATE_LOG.append(str(msg))

def brush(hex_color):
    h = hex_color.lstrip('#')
    if len(h) == 8:
        a, r, g, b = [int(h[i:i+2], 16) for i in range(0, 8, 2)]
    else:
        a = 255
        r, g, b = [int(h[i:i+2], 16) for i in range(0, 6, 2)]
    return SolidColorBrush(WpfColor.FromArgb(a, r, g, b))

def get_cell_value(cell):
    try:
        val = cell.Value2
        return val if val is not None else None
    except:
        try:
            return cell.Value
        except:
            return None

def safe_str(val):
    if val is None:
        return ""
    try:
        # Handle float that is actually an integer (1.0 -> "1")
        if isinstance(val, float):
            if val == int(val):
                return str(int(val))
            else:
                return str(val)
        return str(val).strip()
    except:
        return ""

def safe_int(val):
    if val is None:
        return None
    try:
        if isinstance(val, (int, float)):
            return int(val)
        s = str(val).strip()
        return int(float(s)) if s else None
    except:
        return None


# =============================================================================
# SCHEDULE EXTRACTOR - DiRoots Style
# =============================================================================
class ScheduleExtractor:
    
    @staticmethod
    def get_all_schedules():
        result = {}
        for sch in FilteredElementCollector(doc).OfClass(ViewSchedule):
            if not sch.IsTitleblockRevisionSchedule and not sch.IsInternalKeynoteSchedule:
                result[sch.Name] = sch
        return result
    
    @staticmethod
    def extract_from_cells(schedule):
        """Extract data directly from schedule cells - keeps formatting, gets all data including calculated fields"""
        global DEBUG_LOG
        DEBUG_LOG = []
        
        if not schedule:
            return None
        
        try:
            from Autodesk.Revit.DB import SectionType
            
            definition = schedule.Definition
            table = schedule.GetTableData()
            body = table.GetSectionData(SectionType.Body)
            
            num_rows = body.NumberOfRows
            num_cols = body.NumberOfColumns
            
            log_debug("Schedule cells: {} rows x {} cols".format(num_rows, num_cols))
            
            # Get headers from first row or from field definitions
            headers = []
            fields = []
            
            for i in range(definition.GetFieldCount()):
                f = definition.GetField(i)
                if not f.IsHidden:
                    field_name = f.GetName()
                    headers.append(field_name)
                    fields.append({
                        'name': field_name,
                        'param_id': None,
                        'can_edit': False,  # Read-only for cell export
                        'field_type': f.FieldType,
                        'field_type_str': str(f.FieldType)
                    })
            
            log_debug("Headers: {}".format(headers))
            
            # Find where data rows start (skip header rows)
            data_start_row = 0
            field_names_lower = set(h.lower() for h in headers)
            
            for r in range(num_rows):
                first_cell = ""
                try:
                    first_cell = schedule.GetCellText(SectionType.Body, r, 0) or ""
                except:
                    pass
                
                # If first cell is not a header name, this is data row
                if first_cell.lower() not in field_names_lower and first_cell.strip():
                    # Check if it looks like data (not a sub-header)
                    non_empty = 0
                    for c in range(min(3, num_cols)):
                        try:
                            cell = schedule.GetCellText(SectionType.Body, r, c) or ""
                            if cell.strip():
                                non_empty += 1
                        except:
                            pass
                    if non_empty >= 2:
                        data_start_row = r
                        break
            
            log_debug("Data starts at row: {}".format(data_start_row))
            
            # Read all data rows
            rows = []
            for r in range(data_start_row, num_rows):
                row_data = []
                for c in range(num_cols):
                    try:
                        cell_text = schedule.GetCellText(SectionType.Body, r, c) or ""
                        row_data.append(cell_text)
                    except:
                        row_data.append("")
                
                # Skip if row is empty or looks like a header
                if row_data and any(v.strip() for v in row_data):
                    first_val = row_data[0].lower() if row_data else ""
                    if first_val not in field_names_lower:
                        rows.append(row_data)
            
            log_debug("Data rows: {}".format(len(rows)))
            
            # Debug first few rows
            for i in range(min(3, len(rows))):
                log_debug("Row {}: {}".format(i, rows[i][:5] if len(rows[i]) > 5 else rows[i]))
            
            return {
                'headers': headers,
                'fields': fields,
                'rows': rows,
                'element_ids': [],  # No element IDs in cell mode
                'schedule_name': schedule.Name,
                'num_cols': len(headers),
                'valid_element_count': len(rows),
                'total_rows': len(rows),
                'from_cells': True  # Flag to indicate cell extraction
            }
            
        except Exception as e:
            log_debug("Extract from cells error: " + str(e))
            log_debug(traceback.format_exc())
            return None
    
    @staticmethod
    def extract(schedule):
        global DEBUG_LOG
        DEBUG_LOG = []
        
        if not schedule:
            return None
        
        try:
            definition = schedule.Definition
            
            # Get fields info from schedule definition
            fields = []
            for i in range(definition.GetFieldCount()):
                f = definition.GetField(i)
                if not f.IsHidden:
                    param_id = None
                    try:
                        if f.ParameterId and f.ParameterId.IntegerValue != -1:
                            param_id = f.ParameterId.IntegerValue
                    except:
                        pass
                    
                    field_type = f.FieldType
                    field_name = f.GetName()
                    
                    is_editable = field_type not in [
                        ScheduleFieldType.Formula, 
                        ScheduleFieldType.Count,
                        ScheduleFieldType.ElementType
                    ]
                    
                    fields.append({
                        'name': field_name,
                        'param_id': param_id,
                        'can_edit': is_editable,
                        'field_type': field_type,
                        'field_type_str': str(field_type)
                    })
            
            headers = [f['name'] for f in fields]
            log_debug("Fields: {}".format(headers))
            log_debug("Field count: {}".format(len(fields)))
            
            for f in fields:
                log_debug("  {} -> param_id={}, field_type={}".format(
                    f['name'], f['param_id'], f['field_type_str']))
            
            # Get elements from schedule view
            collector = FilteredElementCollector(doc, schedule.Id)
            elements = list(collector.ToElements())
            log_debug("Elements in schedule: {}".format(len(elements)))
            
            # Build data rows directly from elements
            rows = []
            element_ids = []
            
            for elem in elements:
                eid = elem.Id.IntegerValue
                element_ids.append(eid)
                
                row_data = []
                for field in fields:
                    value = ScheduleExtractor._get_field_value(elem, field)
                    row_data.append(value)
                
                rows.append(row_data)
            
            log_debug("Rows built: {}".format(len(rows)))
            
            for i in range(min(3, len(rows))):
                eid = element_ids[i]
                log_debug("Row {}: ID={}, Data={}".format(i, eid, rows[i]))
            
            return {
                'headers': headers,
                'fields': fields,
                'rows': rows,
                'element_ids': element_ids,
                'schedule_name': schedule.Name,
                'num_cols': len(fields),
                'valid_element_count': len(elements),
                'total_rows': len(rows)
            }
            
        except Exception as e:
            log_debug("Extract error: " + str(e))
            log_debug(traceback.format_exc())
            return None
    
    @staticmethod
    def _get_element_name(elem):
        """Get element name - works in IronPython"""
        try:
            # Method 1: Direct property access
            if hasattr(elem, 'Name'):
                name = elem.Name
                if name:
                    return name
        except:
            pass
        
        try:
            # Method 2: Use Element.Name.GetValue() for IronPython
            name = Element.Name.GetValue(elem)
            if name:
                return name
        except:
            pass
        
        return ""
    
    @staticmethod
    def _get_field_value(elem, field):
        """Get field value from element"""
        try:
            field_name = field['name']
            param_id = field['param_id']
            field_type = field['field_type']
            field_name_lower = field_name.lower().strip()
            
            # Handle Count field type
            if field_type == ScheduleFieldType.Count:
                return "1"
            
            # Get element type
            type_id = elem.GetTypeId()
            elem_type = doc.GetElement(type_id) if type_id and type_id.IntegerValue != -1 else None
            
            # Handle Family field (param_id -1002051)
            if param_id == -1002051 or field_name_lower == 'family':
                if elem_type:
                    # Try FamilyName property
                    if hasattr(elem_type, 'FamilyName'):
                        fname = elem_type.FamilyName
                        if fname:
                            return fname
                    # Try Family.Name
                    if hasattr(elem_type, 'Family') and elem_type.Family:
                        fname = ScheduleExtractor._get_element_name(elem_type.Family)
                        if fname:
                            return fname
                return ""
            
            # Handle Type field (param_id -1002050)
            if param_id == -1002050 or field_name_lower == 'type':
                if elem_type:
                    # Get Type name using _get_element_name helper
                    type_name = ScheduleExtractor._get_element_name(elem_type)
                    if type_name:
                        return type_name
                return ""
            
            # Handle ElementType field type (parameters from Type)
            if field_type == ScheduleFieldType.ElementType:
                if elem_type:
                    param = None
                    if param_id and param_id < 0:
                        try:
                            bip = BuiltInParameter(param_id)
                            param = elem_type.get_Parameter(bip)
                        except:
                            pass
                    if not param:
                        param = elem_type.LookupParameter(field_name)
                    
                    if param:
                        return ScheduleExtractor._get_param_value(param)
                return ""
            
            # Regular parameter - try instance first
            param = None
            
            if param_id and param_id < 0:
                try:
                    bip = BuiltInParameter(param_id)
                    param = elem.get_Parameter(bip)
                except:
                    pass
            
            if not param:
                param = elem.LookupParameter(field_name)
            
            # If not found on instance, try type
            if not param and elem_type:
                if param_id and param_id < 0:
                    try:
                        bip = BuiltInParameter(param_id)
                        param = elem_type.get_Parameter(bip)
                    except:
                        pass
                if not param:
                    param = elem_type.LookupParameter(field_name)
            
            if not param:
                return ""
            
            return ScheduleExtractor._get_param_value(param)
            
        except Exception as e:
            return ""
    
    @staticmethod
    def _get_param_value(param):
        """Extract value from parameter"""
        try:
            storage = param.StorageType
            
            if storage == StorageType.String:
                return param.AsString() or ""
            elif storage == StorageType.Integer:
                v = param.AsInteger()
                return str(v) if v is not None else ""
            elif storage == StorageType.Double:
                v = param.AsDouble()
                if v is not None:
                    return str(v)
                return ""
            elif storage == StorageType.ElementId:
                eid = param.AsElementId()
                if eid and eid.IntegerValue != -1:
                    ref_elem = doc.GetElement(eid)
                    if ref_elem:
                        return ScheduleExtractor._get_element_name(ref_elem)
                return ""
            return ""
        except:
            return ""


# =============================================================================
# EXCEL MANAGER
# =============================================================================
class ExcelManager:
    
    @staticmethod
    def export_multiple_to_excel(filepath, schedules_data, from_cells=False):
        """Export multiple schedules to single Excel file - each schedule as a sheet"""
        excel_app = None
        wb = None
        
        try:
            excel_app = Excel.ApplicationClass()
            excel_app.Visible = False
            excel_app.DisplayAlerts = False
            
            wb = excel_app.Workbooks.Add()
            
            # Remove default sheets except first one
            while wb.Sheets.Count > 1:
                wb.Sheets[wb.Sheets.Count].Delete()
            
            first_sheet = True
            
            for data in schedules_data:
                schedule_name = data['schedule_name']
                headers = data['headers']
                fields = data['fields']
                rows = data['rows']
                element_ids = data.get('element_ids', [])
                is_from_cells = data.get('from_cells', False) or from_cells
                
                # Create or use sheet
                if first_sheet:
                    ws = wb.Sheets[1]
                    first_sheet = False
                else:
                    ws = wb.Sheets.Add(After=wb.Sheets[wb.Sheets.Count])
                
                # Sheet name (max 31 chars, no special chars)
                safe_name = schedule_name[:31].replace("/", "_").replace("\\", "_").replace("*", "_")
                safe_name = safe_name.replace("?", "_").replace("[", "_").replace("]", "_")
                ws.Name = safe_name
                
                if is_from_cells:
                    # No Element ID column - just headers and data
                    for col, header in enumerate(headers):
                        cell = ws.Cells[1, col + 1]
                        cell.Value2 = header
                        cell.Font.Bold = True
                        cell.Interior.Color = 0xE0E0E0  # Gray - read only
                    
                    for row_idx, row_data in enumerate(rows):
                        excel_row = row_idx + 2
                        for col_idx, value in enumerate(row_data):
                            ws.Cells[excel_row, col_idx + 1].Value2 = value
                else:
                    # With Element ID column
                    ws.Cells[1, 1].Value2 = "Element ID"
                    ws.Cells[1, 1].Font.Bold = True
                    ws.Cells[1, 1].Interior.Color = 0xA5E6D4
                    
                    for col, header in enumerate(headers):
                        cell = ws.Cells[1, col + 2]
                        cell.Value2 = header
                        cell.Font.Bold = True
                        is_editable = col < len(fields) and fields[col].get('can_edit', True)
                        cell.Interior.Color = 0xCDFF97 if is_editable else 0xE0E0E0
                    
                    for row_idx, row_data in enumerate(rows):
                        excel_row = row_idx + 2
                        eid = element_ids[row_idx] if row_idx < len(element_ids) else None
                        ws.Cells[excel_row, 1].Value2 = eid if eid else ""
                        
                        for col_idx, value in enumerate(row_data):
                            ws.Cells[excel_row, col_idx + 2].Value2 = value
                
                ws.Columns.AutoFit()
            
            # Only add meta sheet if not from_cells mode
            if not from_cells:
                meta = wb.Sheets.Add(After=wb.Sheets[wb.Sheets.Count])
                meta.Name = "_Meta"
                
                meta.Cells[1, 1].Value2 = "ScheduleCount"
                meta.Cells[1, 2].Value2 = len(schedules_data)
                
                row = 3
                for idx, data in enumerate(schedules_data):
                    meta.Cells[row, 1].Value2 = "Schedule_{}".format(idx)
                    meta.Cells[row, 2].Value2 = data['schedule_name']
                    meta.Cells[row, 3].Value2 = len(data['fields'])
                    row += 1
                    
                    for f in data['fields']:
                        meta.Cells[row, 1].Value2 = f['name']
                        meta.Cells[row, 2].Value2 = f['param_id'] if f['param_id'] else ""
                        meta.Cells[row, 3].Value2 = 1 if f['can_edit'] else 0
                        row += 1
                    
                    row += 1
                
                meta.Visible = Excel.XlSheetVisibility.xlSheetHidden
            
            wb.Sheets[1].Activate()
            
            wb.SaveAs(filepath)
            wb.Close()
            excel_app.Quit()
            
            return True, None
            
        except Exception as e:
            if wb:
                try: wb.Close(False)
                except: pass
            if excel_app:
                try: excel_app.Quit()
                except: pass
            return False, str(e)
    
    @staticmethod
    def export_to_excel(filepath, data):
        excel_app = None
        wb = None
        
        try:
            excel_app = Excel.ApplicationClass()
            excel_app.Visible = False
            excel_app.DisplayAlerts = False
            
            wb = excel_app.Workbooks.Add()
            ws = wb.Sheets[1]
            
            schedule_name = data['schedule_name']
            headers = data['headers']
            fields = data['fields']
            rows = data['rows']
            element_ids = data.get('element_ids', [])
            is_from_cells = data.get('from_cells', False)
            
            # Clean sheet name
            safe_name = schedule_name[:31].replace("/", "_").replace("\\", "_").replace("*", "_")
            safe_name = safe_name.replace("?", "_").replace("[", "_").replace("]", "_")
            ws.Name = safe_name
            
            if is_from_cells:
                # No Element ID column - export as displayed in schedule
                for col, header in enumerate(headers):
                    cell = ws.Cells[1, col + 1]
                    cell.Value2 = header
                    cell.Font.Bold = True
                    cell.Interior.Color = 0xE0E0E0  # Gray - read only
                
                for row_idx, row_data in enumerate(rows):
                    excel_row = row_idx + 2
                    for col_idx, value in enumerate(row_data):
                        ws.Cells[excel_row, col_idx + 1].Value2 = value
                
                ws.Columns.AutoFit()
                
                # No meta sheet needed for cell export
                wb.SaveAs(filepath)
                wb.Close()
                excel_app.Quit()
                
                return True, None
            
            # Normal export with Element ID
            ws.Cells[1, 1].Value2 = "Element ID"
            ws.Cells[1, 1].Font.Bold = True
            ws.Cells[1, 1].Interior.Color = 0xA5E6D4
            
            for col, header in enumerate(headers):
                cell = ws.Cells[1, col + 2]
                cell.Value2 = header
                cell.Font.Bold = True
                is_editable = col < len(fields) and fields[col].get('can_edit', True)
                cell.Interior.Color = 0xCDFF97 if is_editable else 0xE0E0E0
            
            # Data rows
            for row_idx, row_data in enumerate(rows):
                excel_row = row_idx + 2
                eid = element_ids[row_idx] if row_idx < len(element_ids) else None
                ws.Cells[excel_row, 1].Value2 = eid if eid else ""
                
                for col_idx, value in enumerate(row_data):
                    ws.Cells[excel_row, col_idx + 2].Value2 = value
            
            ws.Columns.AutoFit()
            
            # Meta sheet
            meta = wb.Sheets.Add()
            meta.Name = "_Meta"
            meta.Cells[1, 1].Value2 = "ScheduleName"
            meta.Cells[1, 2].Value2 = schedule_name
            meta.Cells[2, 1].Value2 = "FieldCount"
            meta.Cells[2, 2].Value2 = len(fields)
            
            for i, f in enumerate(fields):
                meta.Cells[i + 4, 1].Value2 = f['name']
                meta.Cells[i + 4, 2].Value2 = f['param_id'] if f['param_id'] else ""
                meta.Cells[i + 4, 3].Value2 = 1 if f['can_edit'] else 0
            
            meta.Visible = Excel.XlSheetVisibility.xlSheetHidden
            ws.Activate()
            
            wb.SaveAs(filepath)
            wb.Close()
            excel_app.Quit()
            
            return True, None
            
        except Exception as e:
            if wb:
                try: wb.Close(False)
                except: pass
            if excel_app:
                try: excel_app.Quit()
                except: pass
            return False, str(e)
    
    @staticmethod
    def import_from_excel(filepath):
        excel_app = None
        wb = None
        
        try:
            excel_app = Excel.ApplicationClass()
            excel_app.Visible = False
            excel_app.DisplayAlerts = False
            
            wb = excel_app.Workbooks.Open(filepath)
            
            meta_sheet = None
            data_sheet = None
            
            for i in range(1, wb.Sheets.Count + 1):
                sheet = wb.Sheets[i]
                if sheet.Name == "_Meta":
                    meta_sheet = sheet
                elif not sheet.Name.startswith("_"):
                    data_sheet = sheet
            
            if not meta_sheet or not data_sheet:
                wb.Close()
                excel_app.Quit()
                return None, "Invalid file format"
            
            schedule_name = safe_str(get_cell_value(meta_sheet.Cells[1, 2]))
            field_count = safe_int(get_cell_value(meta_sheet.Cells[2, 2])) or 0
            
            fields = []
            for i in range(field_count):
                name = safe_str(get_cell_value(meta_sheet.Cells[i + 4, 1]))
                param_id = safe_int(get_cell_value(meta_sheet.Cells[i + 4, 2]))
                can_edit = safe_int(get_cell_value(meta_sheet.Cells[i + 4, 3])) == 1
                if name:
                    fields.append({'name': name, 'param_id': param_id, 'can_edit': can_edit})
            
            h1 = safe_str(get_cell_value(data_sheet.Cells[1, 1]))
            
            if h1.lower() in ['element id', 'elementid', 'id']:
                eid_col = 1
                data_start = 2
            else:
                eid_col = None
                data_start = 1
            
            headers = []
            col = data_start
            while True:
                h = safe_str(get_cell_value(data_sheet.Cells[1, col]))
                if not h:
                    break
                headers.append(h)
                col += 1
                if col > 100:
                    break
            
            rows, element_ids = [], []
            row, empty = 2, 0
            
            while empty < 5:
                has_data = False
                
                eid_val = get_cell_value(data_sheet.Cells[row, eid_col]) if eid_col else None
                if eid_val is not None and safe_str(eid_val):
                    has_data = True
                
                for c in range(data_start, data_start + len(headers)):
                    if get_cell_value(data_sheet.Cells[row, c]) is not None:
                        has_data = True
                        break
                
                if not has_data:
                    empty += 1
                    row += 1
                    continue
                
                empty = 0
                element_ids.append(safe_int(eid_val) if eid_val else None)
                
                row_data = []
                for c in range(data_start, data_start + len(headers)):
                    row_data.append(safe_str(get_cell_value(data_sheet.Cells[row, c])))
                rows.append(row_data)
                
                row += 1
                if row > 50000:
                    break
            
            wb.Close()
            excel_app.Quit()
            
            return {
                'schedule_name': schedule_name,
                'fields': fields,
                'headers': headers,
                'rows': rows,
                'element_ids': element_ids
            }, None
            
        except Exception as e:
            if wb:
                try: wb.Close(False)
                except: pass
            if excel_app:
                try: excel_app.Quit()
                except: pass
            return None, str(e)


# =============================================================================
# CHANGE DETECTOR
# =============================================================================
class ChangeDetector:
    @staticmethod
    def find_changes(current_data, imported_data):
        changes = []
        if not current_data or not imported_data:
            return changes
        
        cur_headers = current_data['headers']
        imp_headers = imported_data.get('headers', [])
        imp_fields = imported_data.get('fields', [])
        cur_col_map = {h: idx for idx, h in enumerate(cur_headers)}
        
        cur_by_eid = {}
        for row_idx, eid in enumerate(current_data['element_ids']):
            if eid:
                cur_by_eid[eid] = {
                    'row_idx': row_idx,
                    'row_data': current_data['rows'][row_idx]
                }
        
        for imp_idx, imp_row in enumerate(imported_data['rows']):
            imp_eid = imported_data['element_ids'][imp_idx] if imp_idx < len(imported_data['element_ids']) else None
            
            if not imp_eid:
                continue
            
            cur_info = cur_by_eid.get(imp_eid)
            if not cur_info:
                continue
            
            cur_row = cur_info['row_data']
            
            for col_idx, header in enumerate(imp_headers):
                is_editable = col_idx < len(imp_fields) and imp_fields[col_idx].get('can_edit', True)
                param_id = imp_fields[col_idx].get('param_id') if col_idx < len(imp_fields) else None
                
                if not is_editable:
                    continue
                
                imp_val = safe_str(imp_row[col_idx] if col_idx < len(imp_row) else "")
                cur_col = cur_col_map.get(header)
                if cur_col is None:
                    continue
                cur_val = safe_str(cur_row[cur_col] if cur_col < len(cur_row) else "")
                
                if imp_val != cur_val:
                    changes.append({
                        'imp_row_index': imp_idx,
                        'field_name': header,
                        'param_id': param_id,
                        'element_id': imp_eid,
                        'old_value': cur_val,
                        'new_value': imp_val,
                        'excel_row': imp_idx + 2
                    })
        
        return changes


# =============================================================================
# MODEL UPDATER
# =============================================================================
class ModelUpdater:
    
    @staticmethod
    def apply_changes(schedule, changes, progress_cb=None):
        global UPDATE_LOG
        UPDATE_LOG = []
        
        if not changes:
            return 0, [], 0
        
        success, errors, skipped = 0, [], 0
        t = Transaction(doc, "Schedule Link Pro - Update")
        t.Start()
        
        try:
            for idx, ch in enumerate(changes):
                if progress_cb:
                    progress_cb(idx + 1, len(changes))
                
                elem = None
                elem_id = ch.get('element_id')
                if elem_id:
                    try:
                        elem = doc.GetElement(ElementId(elem_id))
                    except:
                        pass
                
                if not elem:
                    skipped += 1
                    continue
                
                ok, err = ModelUpdater._set_param(elem, ch)
                if ok:
                    success += 1
                    log_update("OK: ID {} - {} = '{}'".format(
                        elem_id, ch['field_name'], 
                        ch['new_value'][:30] if ch['new_value'] else ''))
                else:
                    errors.append("ID {}: {}".format(elem_id, err))
            
            t.Commit()
            
        except Exception as e:
            t.RollBack()
            return 0, [str(e)], 0
        
        return success, errors, skipped
    
    @staticmethod
    def _set_param(elem, change):
        try:
            param = None
            field_name = change['field_name']
            param_id = change['param_id']
            value = change['new_value']
            
            if param_id and param_id < 0:
                try:
                    bip = BuiltInParameter(param_id)
                    param = elem.get_Parameter(bip)
                except:
                    pass
            
            if not param:
                param = elem.LookupParameter(field_name)
            
            if not param:
                for p in elem.Parameters:
                    try:
                        if p.Definition and p.Definition.Name == field_name:
                            param = p
                            break
                    except:
                        pass
            
            if not param:
                elem_type = doc.GetElement(elem.GetTypeId())
                if elem_type:
                    if param_id and param_id < 0:
                        try:
                            bip = BuiltInParameter(param_id)
                            param = elem_type.get_Parameter(bip)
                        except:
                            pass
                    if not param:
                        param = elem_type.LookupParameter(field_name)
            
            if not param:
                return False, "'{}' not found".format(field_name)
            
            if param.IsReadOnly:
                return False, "'{}' read-only".format(field_name)
            
            storage = param.StorageType
            
            if storage == StorageType.String:
                param.Set(str(value) if value else "")
            elif storage == StorageType.Integer:
                if value:
                    param.Set(int(float(value)))
                else:
                    param.Set(0)
            elif storage == StorageType.Double:
                if value:
                    param.Set(float(value))
                else:
                    param.Set(0.0)
            else:
                return False, "Unsupported type"
            
            return True, ""
            
        except Exception as e:
            return False, str(e)


# =============================================================================
# MAIN WINDOW
# =============================================================================
class MainWindow(Window):
    
    def __init__(self):
        self.Title = "Schedule Link Pro - DQT"
        self.Width = 1100
        self.Height = 750
        self.WindowStartupLocation = System.Windows.WindowStartupLocation.CenterScreen
        self.Background = brush(BACKGROUND)
        
        self.schedules = ScheduleExtractor.get_all_schedules()
        self.current_schedule = None
        self.current_data = None
        self.imported_data = None
        self.changes = []
        
        self._build_ui()
        self._load_schedules()
    
    def _build_ui(self):
        main = Grid()
        main.Margin = Thickness(10)
        
        for _ in range(4):
            main.RowDefinitions.Add(RowDefinition())
        main.RowDefinitions[0].Height = GridLength.Auto
        main.RowDefinitions[1].Height = GridLength.Auto
        main.RowDefinitions[3].Height = GridLength.Auto
        
        copyright_top = TextBlock()
        copyright_top.Text = COPYRIGHT
        copyright_top.FontSize = 10
        copyright_top.Foreground = brush(GRAY)
        copyright_top.HorizontalAlignment = HorizontalAlignment.Center
        copyright_top.Margin = Thickness(0, 0, 0, 5)
        Grid.SetRow(copyright_top, 0)
        main.Children.Add(copyright_top)
        
        top = self._build_top_bar()
        Grid.SetRow(top, 1)
        main.Children.Add(top)
        
        scroll = ScrollViewer()
        scroll.HorizontalScrollBarVisibility = System.Windows.Controls.ScrollBarVisibility.Auto
        scroll.VerticalScrollBarVisibility = System.Windows.Controls.ScrollBarVisibility.Auto
        scroll.Margin = Thickness(0, 10, 0, 10)
        
        self.grid_container = StackPanel()
        scroll.Content = self.grid_container
        
        Grid.SetRow(scroll, 2)
        main.Children.Add(scroll)
        
        bottom = self._build_bottom_bar()
        Grid.SetRow(bottom, 3)
        main.Children.Add(bottom)
        
        self.Content = main
    
    def _build_top_bar(self):
        panel = StackPanel()
        
        title = TextBlock()
        title.Text = "Schedule Link Pro"
        title.FontSize = 20
        title.FontWeight = FontWeights.Bold
        title.Margin = Thickness(0, 0, 0, 10)
        panel.Children.Add(title)
        
        # Mode selection
        mode_row = DockPanel()
        mode_row.Margin = Thickness(0, 0, 0, 5)
        
        self.single_mode_cb = CheckBox()
        self.single_mode_cb.Content = "Single Schedule"
        self.single_mode_cb.IsChecked = True
        self.single_mode_cb.Margin = Thickness(0, 0, 20, 0)
        self.single_mode_cb.Checked += self._on_mode_change
        mode_row.Children.Add(self.single_mode_cb)
        
        self.multi_mode_cb = CheckBox()
        self.multi_mode_cb.Content = "Multi-Schedule Export"
        self.multi_mode_cb.IsChecked = False
        self.multi_mode_cb.Checked += self._on_mode_change
        mode_row.Children.Add(self.multi_mode_cb)
        
        panel.Children.Add(mode_row)
        
        # Single schedule row
        self.single_row = DockPanel()
        self.single_row.Margin = Thickness(0, 0, 0, 10)
        
        lbl = TextBlock()
        lbl.Text = "Schedule: "
        lbl.Width = 70
        lbl.VerticalAlignment = VerticalAlignment.Center
        DockPanel.SetDock(lbl, System.Windows.Controls.Dock.Left)
        self.single_row.Children.Add(lbl)
        
        self.preview_btn = self._btn("Preview", self._on_preview)
        self.preview_btn.Width = 100
        DockPanel.SetDock(self.preview_btn, System.Windows.Controls.Dock.Right)
        self.single_row.Children.Add(self.preview_btn)
        
        self.sch_combo = ComboBox()
        self.sch_combo.Height = 28
        self.sch_combo.Margin = Thickness(0, 0, 10, 0)
        self.single_row.Children.Add(self.sch_combo)
        
        panel.Children.Add(self.single_row)
        
        # Multi schedule panel (hidden by default)
        self.multi_panel = StackPanel()
        self.multi_panel.Visibility = Visibility.Collapsed
        
        multi_lbl = TextBlock()
        multi_lbl.Text = "Select schedules to export:"
        multi_lbl.Margin = Thickness(0, 0, 0, 5)
        self.multi_panel.Children.Add(multi_lbl)
        
        # Select All / None buttons
        select_row = StackPanel()
        select_row.Orientation = System.Windows.Controls.Orientation.Horizontal
        select_row.Margin = Thickness(0, 0, 0, 5)
        
        self.select_all_btn = Button()
        self.select_all_btn.Content = "Select All"
        self.select_all_btn.Width = 80
        self.select_all_btn.Height = 24
        self.select_all_btn.Margin = Thickness(0, 0, 10, 0)
        self.select_all_btn.Click += self._on_select_all
        select_row.Children.Add(self.select_all_btn)
        
        self.select_none_btn = Button()
        self.select_none_btn.Content = "Select None"
        self.select_none_btn.Width = 80
        self.select_none_btn.Height = 24
        self.select_none_btn.Click += self._on_select_none
        select_row.Children.Add(self.select_none_btn)
        
        self.multi_panel.Children.Add(select_row)
        
        # Schedule checkboxes in scrollable list
        self.schedule_list_scroll = ScrollViewer()
        self.schedule_list_scroll.MaxHeight = 150
        self.schedule_list_scroll.VerticalScrollBarVisibility = System.Windows.Controls.ScrollBarVisibility.Auto
        
        self.schedule_list = StackPanel()
        self.schedule_list_scroll.Content = self.schedule_list
        self.multi_panel.Children.Add(self.schedule_list_scroll)
        
        self.selected_count_text = TextBlock()
        self.selected_count_text.Text = "0 schedules selected"
        self.selected_count_text.Margin = Thickness(0, 5, 0, 0)
        self.selected_count_text.Foreground = brush(GRAY)
        self.multi_panel.Children.Add(self.selected_count_text)
        
        panel.Children.Add(self.multi_panel)
        
        self.info_text = TextBlock()
        self.info_text.Text = "Select a schedule and click Preview"
        self.info_text.Foreground = brush(GRAY)
        self.info_text.TextWrapping = TextWrapping.Wrap
        panel.Children.Add(self.info_text)
        
        return panel
    
    def _on_mode_change(self, sender, e):
        if sender == self.single_mode_cb and self.single_mode_cb.IsChecked:
            self.multi_mode_cb.IsChecked = False
            self.single_row.Visibility = Visibility.Visible
            self.multi_panel.Visibility = Visibility.Collapsed
            self.export_btn.Content = "Export to Excel"
        elif sender == self.multi_mode_cb and self.multi_mode_cb.IsChecked:
            self.single_mode_cb.IsChecked = False
            self.single_row.Visibility = Visibility.Collapsed
            self.multi_panel.Visibility = Visibility.Visible
            self.export_btn.Content = "Export All Selected"
            self.export_btn.IsEnabled = True
            self._update_selected_count()
    
    def _on_select_all(self, s, e):
        for child in self.schedule_list.Children:
            if isinstance(child, CheckBox):
                child.IsChecked = True
        self._update_selected_count()
    
    def _on_select_none(self, s, e):
        for child in self.schedule_list.Children:
            if isinstance(child, CheckBox):
                child.IsChecked = False
        self._update_selected_count()
    
    def _update_selected_count(self):
        count = sum(1 for child in self.schedule_list.Children 
                   if isinstance(child, CheckBox) and child.IsChecked)
        self.selected_count_text.Text = "{} schedules selected".format(count)
        if count > 0:
            self.selected_count_text.Foreground = brush(GREEN)
        else:
            self.selected_count_text.Foreground = brush(GRAY)
    
    def _on_schedule_check_changed(self, s, e):
        self._update_selected_count()
    
    def _build_bottom_bar(self):
        panel = StackPanel()
        
        self.progress = ProgressBar()
        self.progress.Height = 20
        self.progress.Margin = Thickness(0, 0, 0, 10)
        self.progress.Visibility = Visibility.Collapsed
        panel.Children.Add(self.progress)
        
        # Export options row
        options_row = StackPanel()
        options_row.Orientation = System.Windows.Controls.Orientation.Horizontal
        options_row.Margin = Thickness(0, 0, 0, 10)
        
        self.keep_formatting_cb = CheckBox()
        self.keep_formatting_cb.Content = "Keep Formatting of Schedule (read-only export, includes calculated fields)"
        self.keep_formatting_cb.IsChecked = False
        self.keep_formatting_cb.Margin = Thickness(0, 0, 20, 0)
        options_row.Children.Add(self.keep_formatting_cb)
        
        panel.Children.Add(options_row)
        
        btn_row = DockPanel()
        
        right_panel = StackPanel()
        right_panel.Orientation = System.Windows.Controls.Orientation.Horizontal
        DockPanel.SetDock(right_panel, System.Windows.Controls.Dock.Right)
        
        self.import_btn = self._btn("Import Excel", self._on_import)
        self.import_btn.Width = 120
        self.import_btn.Margin = Thickness(5, 0, 0, 0)
        right_panel.Children.Add(self.import_btn)
        
        self.update_btn = self._btn("Update Model", self._on_update)
        self.update_btn.Width = 120
        self.update_btn.Margin = Thickness(5, 0, 0, 0)
        self.update_btn.IsEnabled = False
        self.update_btn.Background = brush(GREEN)
        right_panel.Children.Add(self.update_btn)
        
        btn_row.Children.Add(right_panel)
        
        left_panel = StackPanel()
        left_panel.Orientation = System.Windows.Controls.Orientation.Horizontal
        
        self.export_btn = self._btn("Export to Excel", self._on_export)
        self.export_btn.Width = 130
        self.export_btn.IsEnabled = False
        left_panel.Children.Add(self.export_btn)
        
        self.debug_btn = self._btn("Debug Info", self._on_debug)
        self.debug_btn.Width = 100
        self.debug_btn.Margin = Thickness(10, 0, 0, 0)
        left_panel.Children.Add(self.debug_btn)
        
        btn_row.Children.Add(left_panel)
        panel.Children.Add(btn_row)
        
        self.status_text = TextBlock()
        self.status_text.Text = ""
        self.status_text.Margin = Thickness(0, 10, 0, 5)
        self.status_text.TextWrapping = TextWrapping.Wrap
        panel.Children.Add(self.status_text)
        
        copyright_bottom = TextBlock()
        copyright_bottom.Text = COPYRIGHT
        copyright_bottom.FontSize = 10
        copyright_bottom.Foreground = brush(GRAY)
        copyright_bottom.HorizontalAlignment = HorizontalAlignment.Center
        copyright_bottom.Margin = Thickness(0, 10, 0, 0)
        panel.Children.Add(copyright_bottom)
        
        return panel
    
    def _btn(self, text, handler):
        b = Button()
        b.Content = text
        b.Height = 32
        b.MinWidth = 80
        b.Background = brush(PRIMARY)
        b.Padding = Thickness(10, 5, 10, 5)
        b.Click += handler
        return b
    
    def _load_schedules(self):
        self.sch_combo.Items.Clear()
        self.schedule_list.Children.Clear()
        self.schedule_checkboxes = {}
        
        for name in sorted(self.schedules.keys()):
            # For combo box
            item = ComboBoxItem()
            item.Content = name
            self.sch_combo.Items.Add(item)
            
            # For multi-select list
            cb = CheckBox()
            cb.Content = name
            cb.Margin = Thickness(0, 2, 0, 2)
            cb.Checked += self._on_schedule_check_changed
            cb.Unchecked += self._on_schedule_check_changed
            self.schedule_list.Children.Add(cb)
            self.schedule_checkboxes[name] = cb
        
        if self.sch_combo.Items.Count > 0:
            self.sch_combo.SelectedIndex = 0
    
    def _build_grid(self, data, change_lookup=None):
        self.grid_container.Children.Clear()
        
        headers = data.get('headers', [])
        rows = data.get('rows', [])
        element_ids = data.get('element_ids', [])
        fields = data.get('fields', [])
        
        grid = Grid()
        grid.Background = brush(WHITE)
        
        num_cols = len(headers) + 1
        for i in range(num_cols):
            col_def = ColumnDefinition()
            col_def.Width = GridLength.Auto
            grid.ColumnDefinitions.Add(col_def)
        
        num_rows = len(rows) + 1
        for i in range(num_rows):
            row_def = RowDefinition()
            row_def.Height = GridLength.Auto
            grid.RowDefinitions.Add(row_def)
        
        self._add_cell(grid, 0, 0, "Element ID", True, False, False)
        for col_idx, header in enumerate(headers):
            is_editable = col_idx < len(fields) and fields[col_idx].get('can_edit', True)
            self._add_cell(grid, 0, col_idx + 1, header, True, is_editable, False)
        
        for row_idx, row_data in enumerate(rows):
            eid = element_ids[row_idx] if row_idx < len(element_ids) else None
            self._add_cell(grid, row_idx + 1, 0, str(eid) if eid else "", False, False, False)
            
            for col_idx in range(len(headers)):
                val = row_data[col_idx] if col_idx < len(row_data) else ""
                is_changed = False
                old_val = None
                if change_lookup:
                    key = (row_idx, headers[col_idx])
                    if key in change_lookup:
                        is_changed = True
                        old_val = change_lookup[key]['old_value']
                
                is_editable = col_idx < len(fields) and fields[col_idx].get('can_edit', True)
                self._add_cell(grid, row_idx + 1, col_idx + 1, val, False, is_editable, is_changed, old_val)
        
        self.grid_container.Children.Add(grid)
    
    def _add_cell(self, grid, row, col, text, is_header, is_editable, is_changed, old_value=None):
        border = Border()
        border.BorderBrush = brush("#FFD0D0D0")
        border.BorderThickness = Thickness(1)
        border.Padding = Thickness(6, 3, 6, 3)
        
        if is_header:
            if col == 0:
                border.Background = brush("#FFA5E6D4")
            elif is_editable:
                border.Background = brush("#FFCDFF97")
            else:
                border.Background = brush("#FFE0E0E0")
        elif is_changed:
            border.Background = brush("#FFFFF3CD")
        elif row % 2 == 0:
            border.Background = brush("#FFF8F8F8")
        else:
            border.Background = brush(WHITE)
        
        tb = TextBlock()
        tb.Text = text
        tb.TextWrapping = TextWrapping.NoWrap
        
        if is_header:
            tb.FontWeight = FontWeights.Bold
        elif is_changed:
            tb.Foreground = brush(RED)
            tb.FontWeight = FontWeights.Bold
            if old_value:
                tb.ToolTip = "Was: " + str(old_value)
        
        border.Child = tb
        Grid.SetRow(border, row)
        Grid.SetColumn(border, col)
        grid.Children.Add(border)
    
    def _on_debug(self, s, e):
        global DEBUG_LOG, UPDATE_LOG
        
        msg = "=== DEBUG LOG ===\n"
        msg += "\n".join(DEBUG_LOG[-50:]) if DEBUG_LOG else "(empty)"
        msg += "\n\n=== UPDATE LOG ===\n"
        msg += "\n".join(UPDATE_LOG[-25:]) if UPDATE_LOG else "(none)"
        
        MessageBox.Show(msg, "Debug Info", MessageBoxButtons.OK, MessageBoxIcon.Information)
    
    def _on_preview(self, s, e):
        global DEBUG_LOG
        DEBUG_LOG = []
        
        if not self.sch_combo.SelectedItem:
            return
        
        name = self.sch_combo.SelectedItem.Content
        schedule = self.schedules.get(name)
        
        if not schedule:
            return
        
        self.current_schedule = schedule
        self.current_data = ScheduleExtractor.extract(schedule)
        
        if not self.current_data:
            self.info_text.Text = "Error extracting schedule"
            self.info_text.Foreground = brush(RED)
            return
        
        self._build_grid(self.current_data)
        
        editable = sum(1 for f in self.current_data.get('fields', []) if f.get('can_edit', True))
        total = self.current_data.get('valid_element_count', 0)
        
        self.info_text.Text = "{} cols ({} editable) | {} elements".format(
            len(self.current_data['headers']), editable, total)
        self.info_text.Foreground = brush("#FF000000")
        self.status_text.Text = ""
        
        self.export_btn.IsEnabled = True
        self.changes = []
        self.update_btn.IsEnabled = False
    
    def _on_export(self, s, e):
        # Check if multi-mode
        if self.multi_mode_cb.IsChecked:
            self._on_export_multi()
            return
        
        # Single schedule export
        if not self.sch_combo.SelectedItem:
            return
        
        name = self.sch_combo.SelectedItem.Content
        schedule = self.schedules.get(name)
        
        if not schedule:
            return
        
        # Check if Keep Formatting is enabled
        keep_formatting = self.keep_formatting_cb.IsChecked
        
        if keep_formatting:
            # Extract from cells for full data including calculated fields
            export_data = ScheduleExtractor.extract_from_cells(schedule)
        else:
            # Use current_data if available, otherwise extract
            if self.current_data and self.current_data.get('schedule_name') == name:
                export_data = self.current_data
            else:
                export_data = ScheduleExtractor.extract(schedule)
        
        if not export_data:
            self.status_text.Text = "Error extracting schedule"
            self.status_text.Foreground = brush(RED)
            return
        
        dlg = SaveFileDialog()
        dlg.Filter = "Excel (*.xlsx)|*.xlsx"
        safe_name = name.replace(" ", "_").replace("/", "_")
        dlg.FileName = "{}.xlsx".format(safe_name)
        
        if dlg.ShowDialog() != DialogResult.OK:
            return
        
        ok, err = ExcelManager.export_to_excel(dlg.FileName, export_data)
        
        if ok:
            count = export_data.get('valid_element_count', 0)
            mode_text = "(formatted)" if keep_formatting else ""
            self.status_text.Text = "Exported {} rows {}!".format(count, mode_text)
            self.status_text.Foreground = brush(GREEN)
            MessageBox.Show("Exported {} rows {}!".format(count, mode_text), "Success", 
                          MessageBoxButtons.OK, MessageBoxIcon.Information)
            os.startfile(dlg.FileName)
        else:
            self.status_text.Text = "Export failed: " + str(err)
            self.status_text.Foreground = brush(RED)
    
    def _on_export_multi(self):
        """Export multiple selected schedules to single Excel file"""
        # Get selected schedules
        selected_names = []
        for name, cb in self.schedule_checkboxes.items():
            if cb.IsChecked:
                selected_names.append(name)
        
        if not selected_names:
            MessageBox.Show("Please select at least one schedule!", "No Selection", 
                          MessageBoxButtons.OK, MessageBoxIcon.Warning)
            return
        
        dlg = SaveFileDialog()
        dlg.Filter = "Excel (*.xlsx)|*.xlsx"
        dlg.FileName = "Combined_Schedules.xlsx"
        
        if dlg.ShowDialog() != DialogResult.OK:
            return
        
        # Check if Keep Formatting is enabled
        keep_formatting = self.keep_formatting_cb.IsChecked
        
        # Show progress
        self.progress.Visibility = Visibility.Visible
        self.progress.Maximum = len(selected_names)
        self.progress.Value = 0
        
        # Extract data from all selected schedules
        schedules_data = []
        total_rows = 0
        
        for idx, name in enumerate(selected_names):
            schedule = self.schedules.get(name)
            if schedule:
                if keep_formatting:
                    data = ScheduleExtractor.extract_from_cells(schedule)
                else:
                    data = ScheduleExtractor.extract(schedule)
                    
                if data:
                    schedules_data.append(data)
                    total_rows += data.get('valid_element_count', 0)
            self.progress.Value = idx + 1
        
        self.progress.Visibility = Visibility.Collapsed
        
        if not schedules_data:
            MessageBox.Show("No data extracted from selected schedules!", "Error", 
                          MessageBoxButtons.OK, MessageBoxIcon.Error)
            return
        
        # Export to Excel
        ok, err = ExcelManager.export_multiple_to_excel(dlg.FileName, schedules_data, keep_formatting)
        
        if ok:
            mode_text = "(formatted)" if keep_formatting else ""
            self.status_text.Text = "Exported {} schedules ({} rows) {}!".format(
                len(schedules_data), total_rows, mode_text)
            self.status_text.Foreground = brush(GREEN)
            MessageBox.Show(
                "Exported {} schedules with {} total rows {}!\n\nEach schedule is in a separate sheet.".format(
                    len(schedules_data), total_rows, mode_text), 
                "Success", MessageBoxButtons.OK, MessageBoxIcon.Information)
            os.startfile(dlg.FileName)
        else:
            self.status_text.Text = "Export failed: " + str(err)
            self.status_text.Foreground = brush(RED)
    
    def _on_import(self, s, e):
        dlg = OpenFileDialog()
        dlg.Filter = "Excel (*.xlsx)|*.xlsx"
        
        if dlg.ShowDialog() != DialogResult.OK:
            return
        
        data, err = ExcelManager.import_from_excel(dlg.FileName)
        
        if err:
            self.status_text.Text = "Import failed: " + str(err)
            self.status_text.Foreground = brush(RED)
            return
        
        self.imported_data = data
        schedule = self.schedules.get(data['schedule_name'])
        if not schedule:
            self.status_text.Text = "Schedule '{}' not found!".format(data['schedule_name'])
            self.status_text.Foreground = brush(RED)
            return
        
        self.current_schedule = schedule
        self.current_data = ScheduleExtractor.extract(schedule)
        
        self.changes = ChangeDetector.find_changes(self.current_data, data)
        
        change_lookup = {(ch['imp_row_index'], ch['field_name']): ch for ch in self.changes}
        self._build_grid(data, change_lookup)
        
        if self.changes:
            self.status_text.Text = "{} changes detected".format(len(self.changes))
            self.status_text.Foreground = brush("#FF0000FF")
            self.update_btn.IsEnabled = True
            self.info_text.Text = "IMPORTED: {} | {} rows".format(
                data['schedule_name'], len(data['rows']))
            self.info_text.Foreground = brush(RED)
        else:
            self.status_text.Text = "No changes detected"
            self.status_text.Foreground = brush(GRAY)
            self.update_btn.IsEnabled = False
    
    def _on_update(self, s, e):
        global UPDATE_LOG
        UPDATE_LOG = []
        
        if not self.changes or not self.current_schedule:
            return
        
        r = MessageBox.Show(
            "Apply {} changes to model?".format(len(self.changes)), 
            "Confirm Update", 
            MessageBoxButtons.YesNo, 
            MessageBoxIcon.Question)
        
        if r != DialogResult.Yes:
            return
        
        self.progress.Visibility = Visibility.Visible
        self.progress.Maximum = len(self.changes)
        
        success, errors, skipped = ModelUpdater.apply_changes(
            self.current_schedule, 
            self.changes,
            lambda cur, total: setattr(self.progress, 'Value', cur))
        
        self.progress.Visibility = Visibility.Collapsed
        
        msg = "Updated: {}\nSkipped: {}\nErrors: {}".format(success, skipped, len(errors))
        
        if success > 0:
            self.status_text.Text = "Updated {} elements!".format(success)
            self.status_text.Foreground = brush(GREEN)
            MessageBox.Show(msg, "Update Complete", MessageBoxButtons.OK, MessageBoxIcon.Information)
        else:
            self.status_text.Text = "No elements updated"
            self.status_text.Foreground = brush(RED)
            MessageBox.Show(msg, "Update Result", MessageBoxButtons.OK, MessageBoxIcon.Warning)
        
        self.changes = []
        self.update_btn.IsEnabled = False
        self._on_preview(None, None)


if __name__ == "__main__":
    try:
        MainWindow().ShowDialog()
    except Exception as e:
        MessageBox.Show(str(e) + "\n\n" + traceback.format_exc(), "Error", 
                       MessageBoxButtons.OK, MessageBoxIcon.Error)