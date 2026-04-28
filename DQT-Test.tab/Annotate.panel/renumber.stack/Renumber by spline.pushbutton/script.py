# coding=utf-8
import System
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import *
from pyrevit import revit, forms, script

# Định nghĩa Custom Selection Filter
class CustomISelectionFilter(ISelectionFilter):
    def __init__(self, category):
        self.category = category

    def AllowElement(self, element):
        # Cho phép chỉ các đối tượng trong category đã chỉ định
        return element.Category.Id.IntegerValue == self.category.Id.IntegerValue

    @staticmethod
    def AllowReference(reference, point):
        return False

# Set the active Revit application and document
app = __revit__.Application
doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

# Construct UI for Prefix
prefix = forms.ask_for_string("Prefix for Renumbering", default="A", prompt="Enter the prefix for renumbering:")
if prefix is None:
    script.exit()  # Exit if canceled

start_count = forms.ask_for_int("Starting Count", default=1, prompt="Enter the starting number:")
if start_count is None:
    script.exit()  # Exit if canceled

# Function to renumber elements
def renumber_elements(elements, prefix, start_count):
    counter = start_count
    with revit.Transaction("Renumber Elements", doc):
        for element in elements:
            new_name = "{}{}".format(prefix, counter)  # Tạo tên mới
            element.Name = new_name
            counter += 1

# Select and renumber doors
try:
    TaskDialog.Show("Select Doors", "Select all the doors you want to rename.")
    door_elements = uidoc.Selection.PickObjects(UI.Selection.ObjectType.Element, 
        CustomISelectionFilter(doc.GetElement(DB.BuiltInCategory.OST_Doors)), "Select Doors")
    doors = [doc.GetElement(e) for e in door_elements]
    renumber_elements(doors, prefix, start_count)
except Exception as e:
    forms.alert("Aborted or no doors selected. Error: {}".format(str(e)))

# Select and renumber rooms
try:
    TaskDialog.Show("Select Rooms", "Select all the rooms you want to rename.")
    room_elements = uidoc.Selection.PickObjects(UI.Selection.ObjectType.Element, 
        CustomISelectionFilter(doc.GetElement(DB.BuiltInCategory.OST_Rooms)), "Select Rooms")
    rooms = [doc.GetElement(e) for e in room_elements]
    renumber_elements(rooms, prefix, start_count)
except Exception as e:
    forms.alert("Aborted or no rooms selected. Error: {}".format(str(e)))

# Select and renumber gridlines
try:
    TaskDialog.Show("Select Gridlines", "Select all the gridlines you want to rename.")
    gridline_elements = uidoc.Selection.PickObjects(UI.Selection.ObjectType.Element, 
        CustomISelectionFilter(doc.GetElement(DB.BuiltInCategory.OST_Grid)), "Select Gridlines")
    gridlines = [doc.GetElement(e) for e in gridline_elements]
    renumber_elements(gridlines, prefix, start_count)
except Exception as e:
    forms.alert("Aborted or no gridlines selected. Error: {}".format(str(e)))

# Select and renumber levels
try:
    TaskDialog.Show("Select Levels", "Select all the levels you want to rename.")
    level_elements = uidoc.Selection.PickObjects(UI.Selection.ObjectType.Element, 
        CustomISelectionFilter(doc.GetElement(DB.BuiltInCategory.OST_Levels)), "Select Levels")
    levels = [doc.GetElement(e) for e in level_elements]
    renumber_elements(levels, prefix, start_count)
except Exception as e:
    forms.alert("Aborted or no levels selected. Error: {}".format(str(e)))

# Notify success
TaskDialog.Show("Success", "Renumbering complete.")