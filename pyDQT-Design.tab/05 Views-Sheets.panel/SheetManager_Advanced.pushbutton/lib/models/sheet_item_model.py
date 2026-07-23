# -*- coding: utf-8 -*-
"""
Sheet Manager - Sheet Item Model
Row model for the sheet list DataGrid, with change tracking used by the
Rename / Apply flow.

Copyright (c) Dang Quoc Truong (DQT)
"""


class SheetItemModel(object):
    """Sheet row model with change tracking."""

    def __init__(self, element):
        self.element = element
        self.id = element.Id if element else None
        self.is_selected = False
        self.status = ""
        self.sheet_number = element.SheetNumber if element else ""
        self.sheet_name = element.Name if element else ""

        # Original values for change tracking
        self._original_sheet_number = self.sheet_number
        self._original_sheet_name = self.sheet_name
        self.is_modified = False

        # Views placed on sheet
        try:
            view_ids = element.GetAllPlacedViews()
            if view_ids and view_ids.Count > 0:
                view_names = []
                for view_id in view_ids:
                    view = element.Document.GetElement(view_id)
                    if view and hasattr(view, 'Name'):
                        view_names.append(view.Name)
                self.views_on_sheet = ", ".join(view_names) if view_names else ""
            else:
                self.views_on_sheet = ""
        except:
            self.views_on_sheet = ""

        # Current revision
        try:
            from Autodesk.Revit.DB import BuiltInParameter
            rev_param = element.get_Parameter(BuiltInParameter.SHEET_CURRENT_REVISION)
            if rev_param and rev_param.HasValue:
                self.current_revision = rev_param.AsString() or ""
            else:
                self.current_revision = ""
        except:
            self.current_revision = ""

    def check_if_modified(self):
        """Recompute modified state from current vs original values."""
        if (self.sheet_number != self._original_sheet_number or
                self.sheet_name != self._original_sheet_name):
            self.is_modified = True
            self.status = u"●"  # filled dot
        else:
            self.is_modified = False
            self.status = u"✓"  # check mark
        return self.is_modified

    def commit_changes(self):
        """Mark current values as the new baseline after a successful apply."""
        self._original_sheet_number = self.sheet_number
        self._original_sheet_name = self.sheet_name
        self.is_modified = False
        self.status = u"✓"  # check mark
