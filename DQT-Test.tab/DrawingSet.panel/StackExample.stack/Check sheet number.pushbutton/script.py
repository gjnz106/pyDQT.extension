# Import necessary libraries
from pyrevit import revit, DB, forms

# Get the current document
doc = revit.doc

# Collect all ViewSheet elements
sheets = list(DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet).ToElements())

# Prepare a list to hold sheets using automatic numbering
auto_numbered_sheets = []

# Check each sheet
for sheet in sheets:
    if sheet.SheetNumber.startswith("S-") or not sheet.SheetNumber.isdigit():
        auto_numbered_sheets.append(sheet)

# Display the sheets with automatic numbering
if auto_numbered_sheets:
    sheet_names = []
    for sheet in auto_numbered_sheets:
        sheet_names.append("{} (Number: {})".format(sheet.Name, sheet.SheetNumber))
    forms.alert("The following sheets are using automatic numbering:\n\n" + "\n".join(sheet_names))
else:
    forms.alert("No sheets are using automatic numbering.")