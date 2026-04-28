# -*- coding: utf-8 -*-
"""
DQT BCF Reader (v2 - pyRevit WPFWindow modeless)
Read BCF/BCFzip files exported from IFC Delta Viewer and navigate issues in Revit.

This version uses pyRevit's forms.WPFWindow + show() modeless pattern,
which has been tested stable in Revit 2024/2025/2026 including the
.NET 8 CoreCLR cross-runtime scenario that causes crashes with raw
IronPython modeless windows.

Dang Quoc Truong - DQT (c) 2025
"""
__title__ = "BCF\nReader"
__author__ = "Dang Quoc Truong"

# CRITICAL for modeless forms in pyRevit IronPython:
# Without this flag, pyRevit tears down the IronPython engine after the
# script returns, destroying the modeless window and causing crashes on
# any subsequent interaction. This flag keeps the engine alive for the
# lifetime of the window.
__persistentengine__ = True

import os
import re
import clr
import traceback

# ---------------------------------------------------------------------------
# .NET / WPF imports (MUST come BEFORE any Revit DB wildcard import)
# ---------------------------------------------------------------------------
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")
clr.AddReference("System")
clr.AddReference("System.Xml")
clr.AddReference("System.IO.Compression")
clr.AddReference("System.IO.Compression.FileSystem")

import System
from System.IO import MemoryStream, File, Path as IOPath, StreamReader
from System.IO.Compression import ZipFile
from System.Text import Encoding
from System.Windows import (
    Thickness, HorizontalAlignment, VerticalAlignment,
    TextWrapping, FontStyles, FontWeights, CornerRadius,
    GridLength, GridUnitType
)
from System.Windows.Media import BrushConverter, Stretch
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption
from System.Windows.Controls import (
    Button, TextBlock, StackPanel, Border, ScrollViewer,
    Image, Orientation, ColumnDefinition, RowDefinition
)
from System.Windows.Controls import Grid as WPFGrid
from System.Windows.Input import Cursors
from System.Collections.Generic import List
from System.Xml import XmlDocument
from Microsoft.Win32 import OpenFileDialog, SaveFileDialog

# ---------------------------------------------------------------------------
# Revit API
# ---------------------------------------------------------------------------
import Autodesk.Revit.DB as DB
from Autodesk.Revit.DB import (
    ElementId, Transaction, FilteredElementCollector,
    RevitLinkInstance, IFailuresPreprocessor, FailureProcessingResult,
    XYZ, BoundingBoxXYZ
)
from Autodesk.Revit.UI import TaskDialog, IExternalEventHandler, ExternalEvent

# ---------------------------------------------------------------------------
# pyRevit
# ---------------------------------------------------------------------------
from pyrevit import revit, script
from pyrevit.forms import WPFWindow

doc = revit.doc
uidoc = revit.uidoc

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
OUTPUT_DIR = r"C:\Temp\DQT_Purge"

COLOR_HEADER_BG   = "#5D4E37"
COLOR_HEADER_FG   = "#F0CC88"
COLOR_BG          = "#FEF8E7"
COLOR_FOOTER_BG   = "#F5F0E0"
COLOR_CARD_BORDER = "#D4B87A"
COLOR_CARD_SEL    = "#5D4E37"
COLOR_REMOVED     = "#E74C3C"
COLOR_ADDED       = "#27AE60"
COLOR_MODIFIED    = "#F39C12"
COLOR_OTHER       = "#95A5A6"
COLOR_TEXT        = "#333333"
COLOR_TEXT_MUTED  = "#7B6F5A"

LABEL_COLORS = {
    "REMOVED": COLOR_REMOVED,
    "ADDED": COLOR_ADDED,
    "MODIFIED": COLOR_MODIFIED,
}

# BCF stores coordinates in meters; Revit internal units are feet.
METERS_TO_FEET = 3.2808398950131233


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _eid_int(eid):
    """Revit 2026+ compatibility."""
    if eid is None:
        return -1
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue


def _make_eid(int_value):
    try:
        return ElementId(System.Int64(int_value))
    except Exception:
        return ElementId(int(int_value))


def _ensure_output_dir():
    if not os.path.exists(OUTPUT_DIR):
        try:
            os.makedirs(OUTPUT_DIR)
        except Exception:
            pass


def _brush(hex_color):
    return BrushConverter().ConvertFromString(hex_color)


def _truncate(text, n):
    if text is None:
        return ""
    t = text.strip()
    if len(t) <= n:
        return t
    return t[:n-3] + "..."


def _csv_esc(s):
    if s is None:
        return ""
    s = str(s).replace('"', '""')
    if "," in s or '"' in s or "\n" in s or "\r" in s:
        return '"' + s + '"'
    return s


class WarningSwallower(IFailuresPreprocessor):
    def PreprocessFailures(self, failuresAccessor):
        failuresAccessor.DeleteAllWarnings()
        return FailureProcessingResult.Continue


class ActionHandler(IExternalEventHandler):
    """Queues a callable to run on Revit API thread. Required for modeless
    WPF windows since WPF event handlers are outside Revit API context."""
    def __init__(self):
        self._action = None

    def set_action(self, action):
        self._action = action

    def Execute(self, uiapp):
        try:
            if self._action is not None:
                self._action()
        except Exception as ex:
            try:
                TaskDialog.Show("DQT BCF Reader",
                    "Action error:\n" + str(ex) + "\n\n" + traceback.format_exc())
            except Exception:
                pass
        finally:
            self._action = None

    def GetName(self):
        return "DQT BCF Action"


# ---------------------------------------------------------------------------
# BCF data model
# ---------------------------------------------------------------------------
class BCFIssue(object):
    """Holds parsed data for a single BCF topic."""
    def __init__(self):
        self.guid = ""
        self.title = ""
        self.description = ""
        self.creation_date = ""
        self.label = "OTHER"
        self.resolved = False     # User mark - will be written to exported BCF
        self.element_id = None    # Primary element ID (first one)
        self.element_ids = []     # ALL element IDs (for clashes: 2+ elements)
        self.ifc_guid = ""
        self.position = None
        self.snapshot_bytes = None
        self.snapshot_image = None   # cached frozen BitmapImage
        self.camera_type = ""
        self.cam_viewpoint = None
        self.cam_direction = None
        self.cam_up = None
        self.clipping_planes = []
        self.components = []
        self.index = 0

    def build_snapshot_image(self):
        """Build frozen BitmapImage once. Call ms.Dispose() after EndInit()
        because CacheOption.OnLoad has already copied pixels into memory."""
        if self.snapshot_image is not None:
            return self.snapshot_image
        if self.snapshot_bytes is None:
            return None
        try:
            ms = MemoryStream(self.snapshot_bytes)
            try:
                bi = BitmapImage()
                bi.BeginInit()
                bi.CacheOption = BitmapCacheOption.OnLoad
                bi.StreamSource = ms
                bi.EndInit()
                bi.Freeze()
            finally:
                try:
                    ms.Close()
                    ms.Dispose()
                except Exception:
                    pass
            self.snapshot_image = bi
            return bi
        except Exception:
            self.snapshot_image = None
            return None


class BCFReader(object):
    """Parses a .bcf / .bcfzip archive."""

    def __init__(self, filepath):
        self.filepath = filepath
        self.project_name = ""
        self.project_guid = ""
        self.issues = []

    def parse(self):
        if not File.Exists(self.filepath):
            raise IOError("BCF file not found: " + self.filepath)

        archive = ZipFile.OpenRead(self.filepath)
        try:
            # Project info
            for entry in archive.Entries:
                name_lower = entry.FullName.lower()
                if name_lower.endswith("project.bcfp"):
                    try:
                        self._parse_project(self._read_entry_text(entry))
                    except Exception:
                        pass

            # Group entries by topic folder
            folder_map = {}
            for entry in archive.Entries:
                full = entry.FullName.replace("\\", "/")
                parts = full.split("/")
                if len(parts) < 2:
                    continue
                folder = parts[0]
                filename = parts[-1].lower()
                if not folder:
                    continue
                d = folder_map.setdefault(folder, {})
                if filename == "markup.bcf":
                    d["markup"] = entry
                elif filename == "viewpoint.bcfv":
                    d["viewpoint"] = entry
                elif filename == "snapshot.png":
                    d["snapshot"] = entry

            idx = 0
            for folder in sorted(folder_map.keys()):
                parts = folder_map[folder]
                if "markup" not in parts:
                    continue
                idx += 1
                issue = BCFIssue()
                issue.guid = folder
                issue.index = idx

                try:
                    self._parse_markup(self._read_entry_text(parts["markup"]), issue)
                except Exception as ex:
                    issue.title = "[parse error] " + folder
                    issue.description = "Failed: " + str(ex)

                if "viewpoint" in parts:
                    try:
                        self._parse_viewpoint(self._read_entry_text(parts["viewpoint"]), issue)
                    except Exception:
                        pass

                if "snapshot" in parts:
                    try:
                        issue.snapshot_bytes = self._read_entry_bytes(parts["snapshot"])
                        issue.build_snapshot_image()
                    except Exception:
                        pass

                self._extract_from_description(issue)

                # Collect ALL element ids from components (clashes have 2+ elements)
                all_ids = []
                for c in issue.components:
                    aid = c.get("AuthoringToolId") or c.get("ElementId")
                    if aid:
                        try:
                            eid = int(aid)
                            if eid not in all_ids:
                                all_ids.append(eid)
                        except Exception:
                            pass
                    if not issue.ifc_guid and c.get("IfcGuid"):
                        issue.ifc_guid = c.get("IfcGuid")

                # Also extract additional IDs from description (e.g. "Source: ... :1372474 ... Target: ... :792679")
                if issue.description:
                    found_in_desc = re.findall(r":(\d{4,})", issue.description)
                    for s in found_in_desc:
                        try:
                            eid = int(s)
                            if eid not in all_ids and eid > 0:
                                all_ids.append(eid)
                        except Exception:
                            pass

                # If we still have nothing, try the regex-extracted single ID
                if not all_ids and issue.element_id is not None:
                    all_ids.append(issue.element_id)

                issue.element_ids = all_ids
                if issue.element_id is None and all_ids:
                    issue.element_id = all_ids[0]

                self.issues.append(issue)
        finally:
            archive.Dispose()

    def _read_entry_text(self, entry):
        stream = entry.Open()
        try:
            reader = StreamReader(stream, Encoding.UTF8)
            try:
                return reader.ReadToEnd()
            finally:
                reader.Dispose()
        finally:
            stream.Dispose()

    def _read_entry_bytes(self, entry):
        stream = entry.Open()
        try:
            ms = MemoryStream()
            try:
                stream.CopyTo(ms)
                return ms.ToArray()
            finally:
                ms.Dispose()
        finally:
            stream.Dispose()

    def _xml_doc(self, xml_text):
        xd = XmlDocument()
        xd.LoadXml(xml_text)
        return xd

    def _first_child_text(self, node, names):
        if node is None:
            return ""
        names_lower = [n.lower() for n in names]
        for child in node.ChildNodes:
            if child.NodeType != System.Xml.XmlNodeType.Element:
                continue
            if child.LocalName.lower() in names_lower:
                return child.InnerText or ""
        return ""

    def _find_element_recursive(self, node, local_name):
        if node is None:
            return None
        target = local_name.lower()
        for child in node.ChildNodes:
            if child.NodeType != System.Xml.XmlNodeType.Element:
                continue
            if child.LocalName.lower() == target:
                return child
            found = self._find_element_recursive(child, local_name)
            if found is not None:
                return found
        return None

    def _find_all_recursive(self, node, local_name, out_list):
        if node is None:
            return
        target = local_name.lower()
        for child in node.ChildNodes:
            if child.NodeType != System.Xml.XmlNodeType.Element:
                continue
            if child.LocalName.lower() == target:
                out_list.append(child)
            self._find_all_recursive(child, local_name, out_list)

    def _parse_xyz(self, node):
        if node is None:
            return None
        try:
            xs = self._first_child_text(node, ["X"])
            ys = self._first_child_text(node, ["Y"])
            zs = self._first_child_text(node, ["Z"])
            if xs == "" or ys == "" or zs == "":
                return None
            return (float(xs), float(ys), float(zs))
        except Exception:
            return None

    def _parse_project(self, xml_text):
        try:
            xd = self._xml_doc(xml_text)
            proj = self._find_element_recursive(xd, "Project")
            if proj is not None:
                self.project_guid = proj.GetAttribute("ProjectId") or ""
                self.project_name = self._first_child_text(proj, ["Name"])
        except Exception:
            pass

    def _parse_markup(self, xml_text, issue):
        xd = self._xml_doc(xml_text)
        topic = self._find_element_recursive(xd, "Topic")
        if topic is None:
            return
        issue.guid = topic.GetAttribute("Guid") or issue.guid
        issue.title = self._first_child_text(topic, ["Title"])
        issue.description = self._first_child_text(topic, ["Description"])
        issue.creation_date = self._first_child_text(topic, ["CreationDate"])

        labels_nodes = []
        self._find_all_recursive(topic, "Labels", labels_nodes)
        label_texts = []
        for ln in labels_nodes:
            t = (ln.InnerText or "").strip()
            if t:
                label_texts.append(t.upper())
        joined = ",".join(label_texts)
        detected = "OTHER"
        for key in ("REMOVED", "ADDED", "MODIFIED"):
            if key in joined:
                detected = key
                break
        # Resolved flag (user-marked via DQT)
        if "RESOLVED" in joined or "DQT_RESOLVED" in joined:
            issue.resolved = True

        if detected == "OTHER":
            desc_up = (issue.description or "").upper()
            title_up = (issue.title or "").upper()
            for key in ("REMOVED", "ADDED", "MODIFIED"):
                if desc_up.startswith(key) or ("| " + key in desc_up) or \
                   key in desc_up[:50] or key in title_up[:50]:
                    detected = key
                    break

        if detected == "OTHER":
            ttype = (topic.GetAttribute("TopicType") or "").upper()
            for key in ("REMOVED", "ADDED", "MODIFIED"):
                if key in ttype:
                    detected = key
                    break

        issue.label = detected

    def _parse_viewpoint(self, xml_text, issue):
        xd = self._xml_doc(xml_text)
        vis = self._find_element_recursive(xd, "VisualizationInfo")
        if vis is None:
            vis = xd.DocumentElement

        comps = []
        self._find_all_recursive(vis, "Component", comps)
        for c in comps:
            d = {
                "IfcGuid": c.GetAttribute("IfcGuid") or "",
                "ElementId": "",
                "AuthoringToolId": c.GetAttribute("AuthoringToolId") or "",
            }
            ati_child = self._find_element_recursive(c, "AuthoringToolId")
            if ati_child is not None and not d["AuthoringToolId"]:
                d["AuthoringToolId"] = (ati_child.InnerText or "").strip()
            eid_child = self._find_element_recursive(c, "ElementId")
            if eid_child is not None:
                d["ElementId"] = (eid_child.InnerText or "").strip()
            if not d["ElementId"]:
                d["ElementId"] = c.GetAttribute("ElementId") or ""
            issue.components.append(d)

        ortho = self._find_element_recursive(vis, "OrthogonalCamera")
        persp = self._find_element_recursive(vis, "PerspectiveCamera")
        cam = ortho if ortho is not None else persp
        if ortho is not None:
            issue.camera_type = "Orthogonal"
        elif persp is not None:
            issue.camera_type = "Perspective"
        if cam is not None:
            issue.cam_viewpoint = self._parse_xyz(self._find_element_recursive(cam, "CameraViewPoint"))
            issue.cam_direction = self._parse_xyz(self._find_element_recursive(cam, "CameraDirection"))
            issue.cam_up = self._parse_xyz(self._find_element_recursive(cam, "CameraUpVector"))

        planes_container = self._find_element_recursive(vis, "ClippingPlanes")
        if planes_container is not None:
            plane_nodes = []
            self._find_all_recursive(planes_container, "ClippingPlane", plane_nodes)
            for pn in plane_nodes:
                loc = self._parse_xyz(self._find_element_recursive(pn, "Location"))
                dir_ = self._parse_xyz(self._find_element_recursive(pn, "Direction"))
                if loc is not None and dir_ is not None:
                    issue.clipping_planes.append((loc, dir_))

    def _extract_from_description(self, issue):
        desc = issue.description or ""
        if issue.element_id is None:
            m = re.search(r"Element\s*ID\s*:\s*(\d+)", desc, re.IGNORECASE)
            if m is None:
                m = re.search(r"ElementId[^0-9]*(\d+)", desc, re.IGNORECASE)
            if m:
                try:
                    issue.element_id = int(m.group(1))
                except Exception:
                    pass
        if issue.position is None:
            m = re.search(
                r"Position\s*:\s*\(\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)\s*\)",
                desc, re.IGNORECASE)
            if m:
                try:
                    issue.position = (float(m.group(1)), float(m.group(2)), float(m.group(3)))
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# Main WPF window (pyRevit forms.WPFWindow)
# ---------------------------------------------------------------------------
class BCFManagerWindow(WPFWindow):
    """Inherits pyRevit's WPFWindow which handles modeless + cross-runtime
    safely in Revit 2024/2025/2026."""

    def __init__(self, xaml_file):
        WPFWindow.__init__(self, xaml_file)

        # Bind helpers as instance attributes so WPF event closures
        # don't lose them via IronPython 2.7 module-globals lookup
        # (this is the root cause of the "_brush is not defined" error
        #  observed in Revit 2024 + pyRevit IronPython engine).
        self._brush = _brush
        self._truncate = _truncate
        self._csv_esc = _csv_esc
        self._make_eid = _make_eid
        self._ensure_output_dir = _ensure_output_dir
        # Color/constant references too (closures lose them on Revit 2024)
        self._LABEL_COLORS = LABEL_COLORS
        self._COLOR_ADDED = COLOR_ADDED
        self._COLOR_OTHER = COLOR_OTHER
        self._COLOR_TEXT = COLOR_TEXT
        self._COLOR_CARD_BORDER = COLOR_CARD_BORDER

        # State
        self.reader = None
        self.issues = []
        self.selected_issue = None
        self.card_borders = {}
        self.active_filter = "ALL"

        # ExternalEvent for Revit API calls from modeless WPF handlers
        self._action_handler = ActionHandler()
        self._action_event = ExternalEvent.Create(self._action_handler)

        # Wire events (control names are exposed as attributes by WPFWindow)
        self.btnOpen.Click += self.on_open_click
        self.btnZoom.Click += self.on_zoom_click
        self.btnExport.Click += self.on_export_click
        self.btnAll.Click += lambda s, e: self.set_filter("ALL")
        self.btnRemoved.Click += lambda s, e: self.set_filter("REMOVED")
        self.btnAdded.Click += lambda s, e: self.set_filter("ADDED")
        self.btnModified.Click += lambda s, e: self.set_filter("MODIFIED")
        # Optional buttons (added later in XAML)
        try:
            self.btnExportBCF.Click += self.on_export_bcf_click
        except AttributeError:
            pass
        try:
            self.btnExportPDF.Click += self.on_export_pdf_click
        except AttributeError:
            pass
        try:
            self.btnResolved.Click += lambda s, e: self.set_filter("RESOLVED")
        except AttributeError:
            pass
        try:
            self.btnUnresolved.Click += lambda s, e: self.set_filter("UNRESOLVED")
        except AttributeError:
            pass

    # ------------------------------------------------------------------
    # File loading
    # ------------------------------------------------------------------
    def prompt_open(self):
        dlg = OpenFileDialog()
        dlg.Title = "Select BCF file"
        dlg.Filter = "BCF files (*.bcf;*.bcfzip)|*.bcf;*.bcfzip|All files (*.*)|*.*"
        if dlg.ShowDialog() == True:
            self.load_bcf(dlg.FileName)
            return True
        return False

    def load_bcf(self, filepath):
        self.set_status("Loading BCF: " + filepath)
        try:
            reader = BCFReader(filepath)
            reader.parse()
            self.reader = reader
            self.issues = reader.issues
            fname = IOPath.GetFileName(filepath)
            subtitle = "{} - {} issues".format(fname, len(self.issues))
            if reader.project_name:
                subtitle = "{} | {}".format(reader.project_name, subtitle)
            self.lblSubtitle.Text = subtitle

            n_added = sum(1 for i in self.issues if i.label == "ADDED")
            n_removed = sum(1 for i in self.issues if i.label == "REMOVED")
            n_modified = sum(1 for i in self.issues if i.label == "MODIFIED")
            n_other = sum(1 for i in self.issues if i.label == "OTHER")
            self.txtTotal.Text = str(len(self.issues))
            self.txtAdded.Text = str(n_added)
            self.txtRemoved.Text = str(n_removed)
            self.txtModified.Text = str(n_modified)

            self.set_filter("ALL", repopulate=False)
            self.populate_cards()

            msg = "Loaded {} issues (Added: {}, Removed: {}, Modified: {}".format(
                len(self.issues), n_added, n_removed, n_modified)
            if n_other > 0:
                msg += ", Unclassified: {}".format(n_other)
            msg += ")"
            self.set_status(msg)
        except Exception as ex:
            TaskDialog.Show("DQT BCF Reader",
                "Failed to load BCF file:\n\n" + str(ex) + "\n\n" + traceback.format_exc())
            self.set_status("Error loading BCF")

    # ------------------------------------------------------------------
    # Cards
    # ------------------------------------------------------------------
    def populate_cards(self):
        self.panelCards.Children.Clear()
        self.card_borders = {}
        visible_count = 0
        for issue in self.issues:
            if self.active_filter == "RESOLVED":
                if not issue.resolved:
                    continue
            elif self.active_filter == "UNRESOLVED":
                if issue.resolved:
                    continue
            elif self.active_filter != "ALL" and issue.label != self.active_filter:
                continue
            card = self._build_card(issue)
            self.panelCards.Children.Add(card)
            visible_count += 1
        if visible_count == 0:
            msg = TextBlock()
            msg.Text = "No issues to display."
            msg.Foreground = self._brush(COLOR_TEXT_MUTED)
            msg.Margin = Thickness(20)
            msg.FontStyle = FontStyles.Italic
            self.panelCards.Children.Add(msg)
        self._clear_detail()
        self._update_resolved_count()

    def _update_resolved_count(self):
        try:
            n_resolved = sum(1 for i in self.issues if i.resolved)
            n_total = len(self.issues)
            base = self.lblSubtitle.Text.split(" | Resolved:")[0]
            if n_total > 0:
                self.lblSubtitle.Text = "{} | Resolved: {}/{}".format(
                    base, n_resolved, n_total)
            else:
                self.lblSubtitle.Text = base
        except Exception:
            pass

    def _build_card(self, issue):
        outer = Border()
        outer.Width = 240
        outer.Height = 260
        outer.Margin = Thickness(6)
        outer.BorderBrush = self._brush(COLOR_CARD_BORDER)
        outer.BorderThickness = Thickness(1)
        outer.CornerRadius = CornerRadius(5)
        outer.Background = self._brush("#FFFFFF")
        outer.Cursor = Cursors.Hand
        outer.Tag = issue

        outer_grid = WPFGrid()
        col_accent = ColumnDefinition(); col_accent.Width = GridLength(5)
        col_body = ColumnDefinition(); col_body.Width = GridLength(1, GridUnitType.Star)
        outer_grid.ColumnDefinitions.Add(col_accent)
        outer_grid.ColumnDefinitions.Add(col_body)

        accent = Border()
        accent_color = COLOR_ADDED if issue.resolved else LABEL_COLORS.get(issue.label, COLOR_OTHER)
        accent.Background = self._brush(accent_color)
        accent.CornerRadius = CornerRadius(4, 0, 0, 4)
        WPFGrid.SetColumn(accent, 0)
        outer_grid.Children.Add(accent)

        body_border = Border()
        body_border.Background = self._brush("#FFFFFF")
        body_border.BorderThickness = Thickness(0)
        WPFGrid.SetColumn(body_border, 1)

        grid = WPFGrid()
        row1 = RowDefinition(); row1.Height = GridLength(140)
        row2 = RowDefinition(); row2.Height = GridLength(1, GridUnitType.Star)
        grid.RowDefinitions.Add(row1)
        grid.RowDefinitions.Add(row2)

        thumb_border = Border()
        thumb_border.Background = self._brush(COLOR_BG)
        thumb_border.BorderThickness = Thickness(0, 0, 0, 1)
        thumb_border.BorderBrush = self._brush(COLOR_CARD_BORDER)
        WPFGrid.SetRow(thumb_border, 0)

        thumb_grid = WPFGrid()
        if issue.snapshot_image is not None:
            try:
                img = Image()
                img.Source = issue.snapshot_image
                img.Stretch = Stretch.UniformToFill
                thumb_grid.Children.Add(img)
            except Exception:
                thumb_grid.Children.Add(self._placeholder_thumb())
        else:
            thumb_grid.Children.Add(self._placeholder_thumb())

        # Badge: ● Label
        badge = Border()
        badge.Background = self._brush("#FFFFFF")
        badge.BorderBrush = self._brush(COLOR_CARD_BORDER)
        badge.BorderThickness = Thickness(1)
        badge.CornerRadius = CornerRadius(10)
        badge.Padding = Thickness(7, 2, 8, 2)
        badge.Margin = Thickness(6)
        badge.HorizontalAlignment = HorizontalAlignment.Left
        badge.VerticalAlignment = VerticalAlignment.Top
        badge_sp = StackPanel()
        badge_sp.Orientation = Orientation.Horizontal
        dot = TextBlock()
        dot.Text = u"\u25CF"
        dot.Foreground = self._brush(LABEL_COLORS.get(issue.label, COLOR_OTHER))
        dot.FontSize = 12
        dot.Margin = Thickness(0, 0, 4, 0)
        dot.VerticalAlignment = VerticalAlignment.Center
        badge_sp.Children.Add(dot)
        badge_tb = TextBlock()
        badge_tb.Text = issue.label.title() if issue.label != "OTHER" else "Other"
        badge_tb.Foreground = self._brush(COLOR_TEXT)
        badge_tb.FontSize = 10
        badge_tb.FontWeight = FontWeights.SemiBold
        badge_tb.VerticalAlignment = VerticalAlignment.Center
        badge_sp.Children.Add(badge_tb)
        badge.Child = badge_sp
        thumb_grid.Children.Add(badge)

        # Issue number
        num = Border()
        num.Background = self._brush(COLOR_HEADER_BG)
        num.CornerRadius = CornerRadius(2)
        num.Padding = Thickness(6, 2, 6, 2)
        num.Margin = Thickness(6)
        num.HorizontalAlignment = HorizontalAlignment.Right
        num.VerticalAlignment = VerticalAlignment.Top
        num_tb = TextBlock()
        num_tb.Text = "#" + str(issue.index)
        num_tb.Foreground = self._brush(COLOR_HEADER_FG)
        num_tb.FontSize = 10
        num_tb.FontWeight = FontWeights.Bold
        num.Child = num_tb
        thumb_grid.Children.Add(num)

        thumb_border.Child = thumb_grid
        grid.Children.Add(thumb_border)

        text_sp = StackPanel()
        text_sp.Margin = Thickness(8)
        WPFGrid.SetRow(text_sp, 1)

        title_tb = TextBlock()
        title_tb.Text = self._truncate(issue.title, 80)
        title_tb.FontWeight = FontWeights.SemiBold
        title_tb.Foreground = self._brush(COLOR_TEXT)
        title_tb.FontSize = 12
        title_tb.TextWrapping = TextWrapping.Wrap
        title_tb.MaxHeight = 54
        text_sp.Children.Add(title_tb)

        if issue.element_id is not None:
            eid_tb = TextBlock()
            eid_tb.Text = "Element ID: " + str(issue.element_id)
            eid_tb.Foreground = self._brush(COLOR_TEXT_MUTED)
            eid_tb.FontSize = 10
            eid_tb.Margin = Thickness(0, 4, 0, 0)
            text_sp.Children.Add(eid_tb)

        if issue.position is not None:
            px = str(round(issue.position[0], 2))
            py = str(round(issue.position[1], 2))
            pz = str(round(issue.position[2], 2))
            pos_tb = TextBlock()
            pos_tb.Text = "Pos: ({}, {}, {})".format(px, py, pz)
            pos_tb.Foreground = self._brush(COLOR_TEXT_MUTED)
            pos_tb.FontSize = 10
            text_sp.Children.Add(pos_tb)

        grid.Children.Add(text_sp)
        body_border.Child = grid
        outer_grid.Children.Add(body_border)
        outer.Child = outer_grid

        outer.MouseLeftButtonDown += self._make_card_click_handler(issue, outer)
        self.card_borders[issue.guid] = outer
        return outer

    def _placeholder_thumb(self):
        tb = TextBlock()
        tb.Text = "[ no image ]"
        tb.FontSize = 12
        tb.Foreground = self._brush(COLOR_TEXT_MUTED)
        tb.HorizontalAlignment = HorizontalAlignment.Center
        tb.VerticalAlignment = VerticalAlignment.Center
        tb.Opacity = 0.6
        return tb

    def _make_card_click_handler(self, issue, border):
        def handler(sender, e):
            try:
                e.Handled = True
                self._select_issue(issue, border)
                if e.ClickCount >= 2:
                    self.zoom_to_issue(issue)
            except Exception as ex:
                try:
                    self.set_status("Card click error: " + str(ex))
                except Exception:
                    pass
        return handler

    def _select_issue(self, issue, border):
        try:
            for b in self.card_borders.values():
                try:
                    b.BorderBrush = self._brush(self._COLOR_CARD_BORDER)
                    b.BorderThickness = Thickness(1)
                except Exception:
                    pass
            border.BorderBrush = self._brush(COLOR_CARD_SEL)
            border.BorderThickness = Thickness(2)
            self.selected_issue = issue
            self._populate_detail(issue)
        except Exception as ex:
            try:
                self.set_status("Select error: " + str(ex))
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Detail panel
    # ------------------------------------------------------------------
    def _clear_detail(self):
        self.panelDetailHeader.Children.Clear()
        self.panelDetailBody.Children.Clear()
        tb = TextBlock()
        tb.Text = "Select an issue to view details."
        tb.Foreground = self._brush(COLOR_TEXT_MUTED)
        tb.FontStyle = FontStyles.Italic
        tb.Margin = Thickness(14, 20, 14, 0)
        self.panelDetailBody.Children.Add(tb)
        self.selected_issue = None

    def _populate_detail(self, issue):
        self.panelDetailHeader.Children.Clear()
        self.panelDetailBody.Children.Clear()

        header_sp = StackPanel()
        header_sp.Orientation = Orientation.Horizontal
        header_sp.Margin = Thickness(0, 0, 0, 8)

        badge = Border()
        badge.Background = self._brush(LABEL_COLORS.get(issue.label, COLOR_OTHER))
        badge.CornerRadius = CornerRadius(2)
        badge.Padding = Thickness(8, 3, 8, 3)
        badge.Margin = Thickness(0, 0, 8, 0)
        btb = TextBlock()
        btb.Text = issue.label
        btb.Foreground = self._brush("#FFFFFF")
        btb.FontSize = 11
        btb.FontWeight = FontWeights.Bold
        badge.Child = btb
        header_sp.Children.Add(badge)

        idx_tb = TextBlock()
        idx_tb.Text = "Issue #" + str(issue.index)
        idx_tb.FontWeight = FontWeights.Bold
        idx_tb.FontSize = 13
        idx_tb.Foreground = self._brush(COLOR_HEADER_BG)
        idx_tb.VerticalAlignment = VerticalAlignment.Center
        header_sp.Children.Add(idx_tb)
        self.panelDetailHeader.Children.Add(header_sp)

        title_tb = TextBlock()
        title_tb.Text = issue.title or "(no title)"
        title_tb.TextWrapping = TextWrapping.Wrap
        title_tb.FontWeight = FontWeights.SemiBold
        title_tb.FontSize = 14
        title_tb.Foreground = self._brush(COLOR_TEXT)
        self.panelDetailHeader.Children.Add(title_tb)

        body = self.panelDetailBody

        if issue.snapshot_image is not None:
            try:
                img = Image()
                img.Source = issue.snapshot_image
                img.Stretch = Stretch.Uniform
                img.MaxHeight = 220
                img.Margin = Thickness(0, 4, 0, 10)
                body.Children.Add(img)
            except Exception:
                pass

        self._add_detail_row(body, "Element ID",
            str(issue.element_id) if issue.element_id is not None else "(not specified)")
        if issue.ifc_guid:
            self._add_detail_row(body, "IFC GUID", issue.ifc_guid)
        if issue.position is not None:
            px = str(round(issue.position[0], 3))
            py = str(round(issue.position[1], 3))
            pz = str(round(issue.position[2], 3))
            self._add_detail_row(body, "Position", "({}, {}, {})".format(px, py, pz))
        if issue.creation_date:
            self._add_detail_row(body, "Created", issue.creation_date)
        if issue.camera_type:
            self._add_detail_row(body, "Camera", issue.camera_type)
        if issue.clipping_planes:
            self._add_detail_row(body, "Clipping Planes", str(len(issue.clipping_planes)))
        if issue.components:
            self._add_detail_row(body, "Components", str(len(issue.components)))

        desc_label = TextBlock()
        desc_label.Text = "Description"
        desc_label.FontWeight = FontWeights.Bold
        desc_label.Foreground = self._brush(COLOR_HEADER_BG)
        desc_label.Margin = Thickness(0, 12, 0, 4)
        body.Children.Add(desc_label)

        desc_border = Border()
        desc_border.Background = self._brush(COLOR_BG)
        desc_border.BorderBrush = self._brush(COLOR_CARD_BORDER)
        desc_border.BorderThickness = Thickness(1)
        desc_border.CornerRadius = CornerRadius(3)
        desc_border.Padding = Thickness(10)
        desc_tb = TextBlock()
        desc_tb.Text = issue.description or "(no description)"
        desc_tb.TextWrapping = TextWrapping.Wrap
        desc_tb.Foreground = self._brush(COLOR_TEXT)
        desc_tb.FontSize = 12
        desc_border.Child = desc_tb
        body.Children.Add(desc_border)

        # Action buttons
        actions_sp = StackPanel()
        actions_sp.Orientation = Orientation.Horizontal
        actions_sp.Margin = Thickness(0, 12, 0, 0)

        def _make_action_btn(text, handler, primary=False):
            btn = Button()
            btn.Content = text
            btn.Padding = Thickness(10, 5, 10, 5)
            btn.Margin = Thickness(0, 0, 6, 0)
            if primary:
                btn.Background = self._brush(COLOR_HEADER_FG)
                btn.Foreground = self._brush(COLOR_HEADER_BG)
                btn.FontWeight = FontWeights.SemiBold
            else:
                btn.Background = self._brush("#FFFFFF")
                btn.Foreground = self._brush(COLOR_TEXT)
            btn.BorderBrush = self._brush(COLOR_CARD_BORDER)
            btn.BorderThickness = Thickness(1)
            btn.Cursor = Cursors.Hand
            btn.FontSize = 11
            btn.Click += handler
            return btn

        actions_sp.Children.Add(_make_action_btn("Zoom to Element",
            lambda s, e: self.zoom_to_issue(issue), primary=True))

        if issue.element_id is not None:
            actions_sp.Children.Add(_make_action_btn("Select",
                lambda s, e: self.select_only(issue)))

        if issue.clipping_planes or issue.element_id is not None:
            actions_sp.Children.Add(_make_action_btn("Section Box",
                lambda s, e: self.apply_section_box(issue)))

        if issue.element_id is not None:
            actions_sp.Children.Add(_make_action_btn("Isolate",
                lambda s, e: self.isolate_element(issue)))

        body.Children.Add(actions_sp)

        # Resolved checkbox row
        from System.Windows.Controls import CheckBox
        resolved_sp = StackPanel()
        resolved_sp.Orientation = Orientation.Horizontal
        resolved_sp.Margin = Thickness(0, 12, 0, 0)
        chk = CheckBox()
        chk.Content = "Mark as Resolved"
        chk.FontSize = 12
        chk.FontWeight = FontWeights.SemiBold
        chk.Foreground = self._brush(self._COLOR_ADDED if issue.resolved else self._COLOR_TEXT)
        chk.IsChecked = System.Nullable[System.Boolean](bool(issue.resolved))
        chk.VerticalAlignment = VerticalAlignment.Center
        def _on_resolved_toggle(s, e):
            try:
                issue.resolved = bool(chk.IsChecked)
                chk.Foreground = self._brush(self._COLOR_ADDED if issue.resolved else self._COLOR_TEXT)
                # Update card accent (show green stripe when resolved)
                card = self.card_borders.get(issue.guid)
                if card is not None:
                    try:
                        grid = card.Child
                        if grid is not None and grid.Children.Count > 0:
                            accent = grid.Children[0]
                            if issue.resolved:
                                accent.Background = self._brush(self._COLOR_ADDED)
                            else:
                                accent.Background = self._brush(
                                    self._LABEL_COLORS.get(issue.label, self._COLOR_OTHER))
                    except Exception:
                        pass
                self._update_resolved_count()
            except Exception:
                pass
        chk.Checked += _on_resolved_toggle
        chk.Unchecked += _on_resolved_toggle
        resolved_sp.Children.Add(chk)
        body.Children.Add(resolved_sp)

    def _add_detail_row(self, parent, label, value):
        sp = StackPanel()
        sp.Orientation = Orientation.Horizontal
        sp.Margin = Thickness(0, 2, 0, 2)
        l = TextBlock()
        l.Text = label + ": "
        l.FontWeight = FontWeights.SemiBold
        l.Foreground = self._brush(COLOR_HEADER_BG)
        l.Width = 110
        l.FontSize = 12
        sp.Children.Add(l)
        v = TextBlock()
        v.Text = value
        v.Foreground = self._brush(COLOR_TEXT)
        v.FontSize = 12
        v.TextWrapping = TextWrapping.Wrap
        sp.Children.Add(v)
        parent.Children.Add(sp)

    # ------------------------------------------------------------------
    # Filter
    # ------------------------------------------------------------------
    def set_filter(self, flt, repopulate=True):
        self.active_filter = flt
        buttons = {
            "ALL": self.btnAll,
            "REMOVED": self.btnRemoved,
            "ADDED": self.btnAdded,
            "MODIFIED": self.btnModified,
        }
        # Optional buttons
        for attr, key in [("btnResolved", "RESOLVED"), ("btnUnresolved", "UNRESOLVED")]:
            try:
                buttons[key] = getattr(self, attr)
            except AttributeError:
                pass
        for key, btn in buttons.items():
            if key == flt:
                btn.Background = self._brush(COLOR_HEADER_FG)
                btn.Foreground = self._brush(COLOR_HEADER_BG)
                btn.FontWeight = FontWeights.SemiBold
            else:
                btn.Background = self._brush("#FFFFFF")
                btn.Foreground = self._brush(COLOR_TEXT)
                btn.FontWeight = FontWeights.Normal
        if repopulate and self.issues:
            self.populate_cards()

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------
    def on_open_click(self, sender, e):
        try:
            self.prompt_open()
        except Exception as ex:
            TaskDialog.Show("DQT BCF Reader", "Open failed:\n" + str(ex))

    def on_zoom_click(self, sender, e):
        if self.selected_issue is None:
            TaskDialog.Show("DQT BCF Reader", "Please select an issue first.")
            return
        self.zoom_to_issue(self.selected_issue)
    def on_export_click(self, sender, e):
        if not self.issues:
            TaskDialog.Show("DQT BCF Reader", "No issues to export.")
            return
        try:
            self.export_summary_csv()
        except Exception as ex:
            TaskDialog.Show("DQT BCF Reader", "Export failed:\n" + str(ex))

    # ------------------------------------------------------------------
    # Dispatch helper
    # ------------------------------------------------------------------
    def _dispatch(self, action):
        """Queue a callable for Revit API thread via ExternalEvent."""
        try:
            self._action_handler.set_action(action)
            self._action_event.Raise()
        except Exception as ex:
            TaskDialog.Show("DQT BCF Reader", "Dispatch failed:\n" + str(ex))

    # ------------------------------------------------------------------
    # Revit operations (via ExternalEvent)
    # ------------------------------------------------------------------
    def zoom_to_issue(self, issue):
        self._dispatch(lambda: self._zoom_to_issue_impl(issue))

    def select_only(self, issue):
        """Select element without zooming."""
        self._dispatch(lambda: self._select_only_impl(issue))

    def apply_section_box(self, issue):
        self._dispatch(lambda: self._apply_section_box_impl(issue))

    def isolate_element(self, issue):
        self._dispatch(lambda: self._isolate_element_impl(issue))

    def _select_only_impl(self, issue):
        ids_to_select = self._collect_element_ids(issue)
        if not ids_to_select:
            TaskDialog.Show("DQT BCF Reader", "No Element ID for this issue.")
            return

        host_ids = []
        link_refs = []   # list of (link_inst, link_elem)
        not_found = []
        for eid_int in ids_to_select:
            ok, elem = self._find_in_host(eid_int)
            if ok:
                host_ids.append(elem.Id)
                continue
            link_inst, link_elem = self._find_in_links(eid_int)
            if link_elem is not None:
                link_refs.append((link_inst, link_elem))
            else:
                not_found.append(eid_int)

        # Strategy: if all in host -> SetElementIds; if mixed -> SetReferences (host + link refs)
        try:
            if link_refs and not host_ids:
                refs = List[DB.Reference]()
                for li, le in link_refs:
                    try:
                        refs.Add(DB.Reference(le).CreateLinkReference(li))
                    except Exception:
                        pass
                if refs.Count > 0:
                    uidoc.Selection.SetReferences(refs)
            elif link_refs and host_ids:
                # Mixed: try References API which supports both
                refs = List[DB.Reference]()
                for hid in host_ids:
                    try:
                        el = doc.GetElement(hid)
                        if el is not None:
                            refs.Add(DB.Reference(el))
                    except Exception:
                        pass
                for li, le in link_refs:
                    try:
                        refs.Add(DB.Reference(le).CreateLinkReference(li))
                    except Exception:
                        pass
                try:
                    uidoc.Selection.SetReferences(refs)
                except Exception:
                    # Fallback: just select host ids
                    eids = List[ElementId]()
                    for h in host_ids:
                        eids.Add(h)
                    uidoc.Selection.SetElementIds(eids)
            else:
                # Pure host
                eids = List[ElementId]()
                for h in host_ids:
                    eids.Add(h)
                uidoc.Selection.SetElementIds(eids)
        except Exception as ex:
            TaskDialog.Show("DQT BCF Reader", "Selection failed:\n" + str(ex))
            return

        msg = "Selected {} element(s)".format(len(host_ids) + len(link_refs))
        if not_found:
            msg += " ({} not found: {})".format(
                len(not_found), ", ".join(str(x) for x in not_found[:5]))
        self.set_status(msg)

    def _collect_element_ids(self, issue):
        """Return list of integer element IDs to operate on (clash = 2+)."""
        if issue.element_ids:
            return list(issue.element_ids)
        if issue.element_id is not None:
            return [int(issue.element_id)]
        return []

    def _zoom_to_issue_impl(self, issue):
        if issue.element_id is None and issue.cam_viewpoint is None and issue.position is None:
            TaskDialog.Show("DQT BCF Reader",
                "This issue has no Element ID, position, or camera viewpoint.")
            return

        eid_int = int(issue.element_id) if issue.element_id is not None else None

        found_host_elem = None
        found_link_inst = None
        found_linked_elem = None
        if eid_int is not None:
            ok_host, host_elem = self._find_in_host(eid_int)
            if ok_host:
                found_host_elem = host_elem
            else:
                link_inst, link_elem = self._find_in_links(eid_int)
                if link_elem is not None:
                    found_link_inst = link_inst
                    found_linked_elem = link_elem

        if found_host_elem is not None:
            self._select_in_host(found_host_elem)
            self.set_status("Selected element {} in active model.".format(eid_int))
        elif found_linked_elem is not None:
            self._select_link_element(found_link_inst, found_linked_elem)
            self.set_status("Element {} found in linked model '{}'.".format(
                eid_int, found_link_inst.Name if found_link_inst else "?"))
        else:
            if eid_int is not None:
                self.set_status("Element {} not found - using BCF viewpoint.".format(eid_int))
            if issue.position is None and issue.cam_viewpoint is None:
                TaskDialog.Show("DQT BCF Reader",
                    "Element ID {} not found and no viewpoint stored.".format(eid_int))
                return

        self._apply_zoom_from_issue(issue, found_host_elem, found_link_inst, found_linked_elem)

    def _apply_zoom_from_issue(self, issue, host_elem, link_inst, linked_elem):
        """Zoom active view. For REMOVED issues, host_elem and linked_elem will
        be None - we must use issue.position with smart unit detection."""
        try:
            uiview = None
            for v in uidoc.GetOpenUIViews():
                if v.ViewId == doc.ActiveView.Id:
                    uiview = v
                    break
            if uiview is None:
                return

            bbox = None
            # Case 1: element found -> use its bbox (most accurate)
            if host_elem is not None:
                try:
                    bb = host_elem.get_BoundingBox(doc.ActiveView)
                    if bb is None:
                        bb = host_elem.get_BoundingBox(None)
                    if bb is not None:
                        bbox = (bb.Min, bb.Max)
                except Exception:
                    pass
            elif linked_elem is not None and link_inst is not None:
                try:
                    bb = linked_elem.get_BoundingBox(None)
                    if bb is not None:
                        xform = link_inst.GetTotalTransform()
                        tmin = xform.OfPoint(bb.Min)
                        tmax = xform.OfPoint(bb.Max)
                        mn = XYZ(min(tmin.X, tmax.X), min(tmin.Y, tmax.Y), min(tmin.Z, tmax.Z))
                        mx = XYZ(max(tmin.X, tmax.X), max(tmin.Y, tmax.Y), max(tmin.Z, tmax.Z))
                        bbox = (mn, mx)
                except Exception:
                    pass

            # Case 2: no element (e.g. REMOVED) -> use position from BCF
            # Smart unit detection: try both meters and feet, pick one inside model extent
            if bbox is None:
                pos = issue.position or issue.cam_viewpoint
                if pos is not None:
                    best_pos = self._detect_position_unit(pos)
                    pad = 10.0
                    bbox = (XYZ(best_pos[0] - pad, best_pos[1] - pad, best_pos[2] - pad),
                            XYZ(best_pos[0] + pad, best_pos[1] + pad, best_pos[2] + pad))

            if bbox is not None:
                uiview.ZoomAndCenterRectangle(bbox[0], bbox[1])
        except Exception:
            pass

    def _detect_position_unit(self, pos):
        """Returns (x,y,z) in feet. Auto-detects whether BCF position is in
        meters or feet by comparing with project extent."""
        # Get project extent from any element (cheap sample)
        try:
            coll = FilteredElementCollector(doc).WhereElementIsNotElementType()
            xs = []; ys = []; zs = []
            count = 0
            for el in coll:
                if count > 50:
                    break
                try:
                    bb = el.get_BoundingBox(None)
                    if bb is not None:
                        xs.append(bb.Min.X); xs.append(bb.Max.X)
                        ys.append(bb.Min.Y); ys.append(bb.Max.Y)
                        zs.append(bb.Min.Z); zs.append(bb.Max.Z)
                        count += 1
                except Exception:
                    pass
            if len(xs) > 1:
                proj_min = (min(xs), min(ys), min(zs))
                proj_max = (max(xs), max(ys), max(zs))
                # Try meters
                pm = (pos[0]*METERS_TO_FEET, pos[1]*METERS_TO_FEET, pos[2]*METERS_TO_FEET)
                # Try feet
                pf = (pos[0], pos[1], pos[2])
                # Pick whichever is closer to project center
                cx = (proj_min[0]+proj_max[0])*0.5
                cy = (proj_min[1]+proj_max[1])*0.5
                cz = (proj_min[2]+proj_max[2])*0.5
                dm = (pm[0]-cx)**2 + (pm[1]-cy)**2 + (pm[2]-cz)**2
                df = (pf[0]-cx)**2 + (pf[1]-cy)**2 + (pf[2]-cz)**2
                if dm < df:
                    return pm
                return pf
        except Exception:
            pass
        # Default: assume meters per BCF spec
        return (pos[0]*METERS_TO_FEET, pos[1]*METERS_TO_FEET, pos[2]*METERS_TO_FEET)

    def _find_in_host(self, eid_int):
        try:
            el = doc.GetElement(self._make_eid(eid_int))
            if el is not None:
                return True, el
        except Exception:
            pass
        return False, None

    def _find_in_links(self, eid_int):
        collector = FilteredElementCollector(doc).OfClass(RevitLinkInstance)
        for link_inst in collector:
            try:
                link_doc = link_inst.GetLinkDocument()
            except Exception:
                link_doc = None
            if link_doc is None:
                continue
            try:
                elem = link_doc.GetElement(self._make_eid(eid_int))
                if elem is not None:
                    return link_inst, elem
            except Exception:
                continue
        return None, None

    def _select_in_host(self, element):
        tx = Transaction(doc, "DQT - BCF Select Element")
        try:
            tx.Start()
            opts = tx.GetFailureHandlingOptions()
            opts.SetFailuresPreprocessor(WarningSwallower())
            tx.SetFailureHandlingOptions(opts)
            ids = List[ElementId]()
            ids.Add(element.Id)
            uidoc.Selection.SetElementIds(ids)
            tx.Commit()
        except Exception:
            if tx.HasStarted() and not tx.HasEnded():
                tx.RollBack()
        try:
            uidoc.ShowElements(element.Id)
        except Exception:
            pass

    def _select_link_element(self, link_inst, linked_elem):
        try:
            ref = DB.Reference(linked_elem).CreateLinkReference(link_inst)
            ids = List[DB.Reference]()
            ids.Add(ref)
            try:
                uidoc.Selection.SetReferences(ids)
            except Exception:
                host_ids = List[ElementId]()
                host_ids.Add(link_inst.Id)
                uidoc.Selection.SetElementIds(host_ids)
        except Exception:
            host_ids = List[ElementId]()
            host_ids.Add(link_inst.Id)
            uidoc.Selection.SetElementIds(host_ids)

    def _get_element_world_bbox(self, eid_int):
        """Return ((minX, minY, minZ), (maxX, maxY, maxZ)) in world coords,
        handling both host and linked elements. None if not found."""
        # Try host
        try:
            el = doc.GetElement(self._make_eid(eid_int))
            if el is not None:
                bb = el.get_BoundingBox(None)
                if bb is not None:
                    return ((bb.Min.X, bb.Min.Y, bb.Min.Z),
                            (bb.Max.X, bb.Max.Y, bb.Max.Z))
        except Exception:
            pass
        # Try linked
        try:
            collector = FilteredElementCollector(doc).OfClass(RevitLinkInstance)
            for link_inst in collector:
                ldoc = link_inst.GetLinkDocument()
                if ldoc is None:
                    continue
                el = ldoc.GetElement(self._make_eid(eid_int))
                if el is None:
                    continue
                bb = el.get_BoundingBox(None)
                if bb is None:
                    continue
                xform = link_inst.GetTotalTransform()
                # 8 corners of source bbox transformed
                corners = [
                    XYZ(bb.Min.X, bb.Min.Y, bb.Min.Z),
                    XYZ(bb.Max.X, bb.Min.Y, bb.Min.Z),
                    XYZ(bb.Min.X, bb.Max.Y, bb.Min.Z),
                    XYZ(bb.Max.X, bb.Max.Y, bb.Min.Z),
                    XYZ(bb.Min.X, bb.Min.Y, bb.Max.Z),
                    XYZ(bb.Max.X, bb.Min.Y, bb.Max.Z),
                    XYZ(bb.Min.X, bb.Max.Y, bb.Max.Z),
                    XYZ(bb.Max.X, bb.Max.Y, bb.Max.Z),
                ]
                xs = []; ys = []; zs = []
                for c in corners:
                    p = xform.OfPoint(c)
                    xs.append(p.X); ys.append(p.Y); zs.append(p.Z)
                return ((min(xs), min(ys), min(zs)),
                        (max(xs), max(ys), max(zs)))
        except Exception:
            pass
        return None

    def _intersect_bboxes(self, bbox_list):
        """Compute axis-aligned intersection of multiple bboxes.
        Returns ((minX,minY,minZ),(maxX,maxY,maxZ)) or None if no overlap."""
        if not bbox_list:
            return None
        mn_x = max(b[0][0] for b in bbox_list)
        mn_y = max(b[0][1] for b in bbox_list)
        mn_z = max(b[0][2] for b in bbox_list)
        mx_x = min(b[1][0] for b in bbox_list)
        mx_y = min(b[1][1] for b in bbox_list)
        mx_z = min(b[1][2] for b in bbox_list)
        # Check if intersection is valid (all maxes >= mins)
        if mx_x < mn_x or mx_y < mn_y or mx_z < mn_z:
            return None
        return ((mn_x, mn_y, mn_z), (mx_x, mx_y, mx_z))

    def _union_bboxes(self, bbox_list):
        if not bbox_list:
            return None
        mn_x = min(b[0][0] for b in bbox_list)
        mn_y = min(b[0][1] for b in bbox_list)
        mn_z = min(b[0][2] for b in bbox_list)
        mx_x = max(b[1][0] for b in bbox_list)
        mx_y = max(b[1][1] for b in bbox_list)
        mx_z = max(b[1][2] for b in bbox_list)
        return ((mn_x, mn_y, mn_z), (mx_x, mx_y, mx_z))

    def _apply_section_box_impl(self, issue):
        if not isinstance(doc.ActiveView, DB.View3D):
            TaskDialog.Show("DQT BCF Reader",
                "Section Box requires an active 3D view.")
            return

        bbox = None
        source = ""

        # Priority 1: collect bboxes of ALL clash elements, then INTERSECT them
        # (clash region = where elements overlap)
        ids_to_use = self._collect_element_ids(issue)
        if ids_to_use:
            element_bboxes = []  # list of (min_xyz_tuple, max_xyz_tuple)
            for eid_int in ids_to_use:
                bb = self._get_element_world_bbox(eid_int)
                if bb is not None:
                    element_bboxes.append(bb)

            if len(element_bboxes) >= 2:
                # INTERSECTION of multiple bboxes (clash zone)
                inter = self._intersect_bboxes(element_bboxes)
                if inter is not None:
                    pad = 2.0  # small padding around clash zone
                    bbox = BoundingBoxXYZ()
                    bbox.Min = XYZ(inter[0][0] - pad, inter[0][1] - pad, inter[0][2] - pad)
                    bbox.Max = XYZ(inter[1][0] + pad, inter[1][1] + pad, inter[1][2] + pad)
                    source = "clash intersection ({} elements)".format(len(element_bboxes))
                else:
                    # No overlap -> union with smaller padding
                    union = self._union_bboxes(element_bboxes)
                    pad = 3.0
                    bbox = BoundingBoxXYZ()
                    bbox.Min = XYZ(union[0][0] - pad, union[0][1] - pad, union[0][2] - pad)
                    bbox.Max = XYZ(union[1][0] + pad, union[1][1] + pad, union[1][2] + pad)
                    source = "elements union (no overlap)"
            elif len(element_bboxes) == 1:
                pad = 5.0
                bb = element_bboxes[0]
                bbox = BoundingBoxXYZ()
                bbox.Min = XYZ(bb[0][0] - pad, bb[0][1] - pad, bb[0][2] - pad)
                bbox.Max = XYZ(bb[1][0] + pad, bb[1][1] + pad, bb[1][2] + pad)
                source = "single element bbox"

        # Priority 2: clipping planes
        if bbox is None:
            bbox = self._build_bbox_from_clipping_planes(issue)
            if bbox is not None:
                source = "clipping planes"

        # Priority 3: position cube
        if bbox is None:
            pos = issue.position or issue.cam_viewpoint
            if pos is None:
                TaskDialog.Show("DQT BCF Reader",
                    "Cannot build section box: no element, clipping planes, or position.")
                return
            cx = pos[0] * METERS_TO_FEET
            cy = pos[1] * METERS_TO_FEET
            cz = pos[2] * METERS_TO_FEET
            pad = 15.0
            bbox = BoundingBoxXYZ()
            bbox.Min = XYZ(cx - pad, cy - pad, cz - pad)
            bbox.Max = XYZ(cx + pad, cy + pad, cz + pad)
            source = "position cube"

        tx = Transaction(doc, "DQT - BCF Apply Section Box")
        try:
            tx.Start()
            opts = tx.GetFailureHandlingOptions()
            opts.SetFailuresPreprocessor(WarningSwallower())
            tx.SetFailureHandlingOptions(opts)
            view3d = doc.ActiveView
            view3d.SetSectionBox(bbox)
            view3d.IsSectionBoxActive = True
            tx.Commit()
            try:
                uiview = None
                for v in uidoc.GetOpenUIViews():
                    if v.ViewId == doc.ActiveView.Id:
                        uiview = v
                        break
                if uiview is not None:
                    uiview.ZoomAndCenterRectangle(bbox.Min, bbox.Max)
            except Exception:
                pass
            self.set_status("Applied section box for #{} ({}).".format(issue.index, source))
        except Exception as ex:
            if tx.HasStarted() and not tx.HasEnded():
                tx.RollBack()
            TaskDialog.Show("DQT BCF Reader", "Failed to apply section box:\n" + str(ex))

    def _build_bbox_from_clipping_planes(self, issue):
        if not issue.clipping_planes:
            return None
        xs_raw = []; ys_raw = []; zs_raw = []
        for (loc, _) in issue.clipping_planes:
            xs_raw.append(loc[0]); ys_raw.append(loc[1]); zs_raw.append(loc[2])
        if len(xs_raw) < 2:
            return None

        raw_min = (min(xs_raw), min(ys_raw), min(zs_raw))
        raw_max = (max(xs_raw), max(ys_raw), max(zs_raw))

        # Get view extent
        view_bbox = None
        try:
            av = doc.ActiveView
            if isinstance(av, DB.View3D) and av.IsSectionBoxActive:
                view_bbox = av.GetSectionBox()
            else:
                coll = FilteredElementCollector(doc, av.Id).WhereElementIsNotElementType()
                xs_e = []; ys_e = []; zs_e = []
                count = 0
                for el in coll:
                    if count > 200:
                        break
                    try:
                        bb = el.get_BoundingBox(av)
                        if bb is not None:
                            xs_e.append(bb.Min.X); xs_e.append(bb.Max.X)
                            ys_e.append(bb.Min.Y); ys_e.append(bb.Max.Y)
                            zs_e.append(bb.Min.Z); zs_e.append(bb.Max.Z)
                            count += 1
                    except Exception:
                        pass
                if len(xs_e) > 1:
                    view_bbox = BoundingBoxXYZ()
                    view_bbox.Min = XYZ(min(xs_e), min(ys_e), min(zs_e))
                    view_bbox.Max = XYZ(max(xs_e), max(ys_e), max(zs_e))
        except Exception:
            pass

        candidates = [("meters", METERS_TO_FEET), ("feet", 1.0)]
        best = None
        for name, scale in candidates:
            mn = (raw_min[0]*scale, raw_min[1]*scale, raw_min[2]*scale)
            mx = (raw_max[0]*scale, raw_max[1]*scale, raw_max[2]*scale)
            cx = (mn[0]+mx[0])*0.5
            cy = (mn[1]+mx[1])*0.5
            cz = (mn[2]+mx[2])*0.5
            size = max(mx[0]-mn[0], mx[1]-mn[1], mx[2]-mn[2])
            score = 0
            if view_bbox is not None:
                vmn = view_bbox.Min; vmx = view_bbox.Max
                pad_x = (vmx.X-vmn.X)*0.5
                pad_y = (vmx.Y-vmn.Y)*0.5
                pad_z = (vmx.Z-vmn.Z)*0.5
                if (vmn.X-pad_x) <= cx <= (vmx.X+pad_x) and \
                   (vmn.Y-pad_y) <= cy <= (vmx.Y+pad_y) and \
                   (vmn.Z-pad_z) <= cz <= (vmx.Z+pad_z):
                    score += 10
            if 1.0 <= size <= 2000.0:
                score += 5
            elif size < 1.0:
                score -= 5
            if best is None or score > best[0]:
                best = (score, name, scale, mn, mx)

        if best is None:
            return None
        _, _, _, mn, mx = best

        pad = 1.0
        mn_x, mn_y, mn_z = mn
        mx_x, mx_y, mx_z = mx
        if abs(mx_x - mn_x) < 0.1: mn_x -= pad; mx_x += pad
        if abs(mx_y - mn_y) < 0.1: mn_y -= pad; mx_y += pad
        if abs(mx_z - mn_z) < 0.1: mn_z -= pad; mx_z += pad

        bbox = BoundingBoxXYZ()
        bbox.Min = XYZ(mn_x, mn_y, mn_z)
        bbox.Max = XYZ(mx_x, mx_y, mx_z)
        return bbox

    def _isolate_element_impl(self, issue):
        if issue.element_id is None:
            TaskDialog.Show("DQT BCF Reader", "No Element ID for this issue.")
            return
        eid_int = int(issue.element_id)
        ok, elem = self._find_in_host(eid_int)
        target_id = None
        if ok:
            target_id = elem.Id
        else:
            link_inst, link_elem = self._find_in_links(eid_int)
            if link_inst is not None:
                target_id = link_inst.Id
        if target_id is None:
            TaskDialog.Show("DQT BCF Reader",
                "Element ID {} not found.".format(eid_int))
            return

        tx = Transaction(doc, "DQT - BCF Isolate Element")
        try:
            tx.Start()
            opts = tx.GetFailureHandlingOptions()
            opts.SetFailuresPreprocessor(WarningSwallower())
            tx.SetFailureHandlingOptions(opts)
            ids = List[ElementId]()
            ids.Add(target_id)
            doc.ActiveView.IsolateElementsTemporary(ids)
            tx.Commit()
            self.set_status("Isolated element {} (temporary).".format(eid_int))
        except Exception as ex:
            if tx.HasStarted() and not tx.HasEnded():
                tx.RollBack()
            TaskDialog.Show("DQT BCF Reader", "Failed to isolate:\n" + str(ex))

    # ------------------------------------------------------------------
    # Export PDF (via HTML + Word interop, fallback browser)
    # ------------------------------------------------------------------
    def on_export_pdf_click(self, sender, e):
        if not self.issues:
            TaskDialog.Show("DQT BCF Reader", "No issues to export.")
            return
        try:
            self.export_pdf()
        except Exception as ex:
            TaskDialog.Show("DQT BCF Reader",
                "PDF export failed:\n" + str(ex) + "\n\n" + traceback.format_exc())

    def export_pdf(self):
        # Suggest filename
        suggested = "BCF_Report.pdf"
        if self.reader and self.reader.filepath:
            suggested = "BCF_Report_" + IOPath.GetFileNameWithoutExtension(
                self.reader.filepath) + ".pdf"

        # Let user choose location
        dlg = SaveFileDialog()
        dlg.Title = "Save PDF Report"
        dlg.Filter = "PDF files (*.pdf)|*.pdf|All files (*.*)|*.*"
        dlg.FileName = suggested
        dlg.DefaultExt = ".pdf"
        if os.path.exists(OUTPUT_DIR):
            dlg.InitialDirectory = OUTPUT_DIR
        if dlg.ShowDialog() != True:
            self.set_status("PDF export cancelled.")
            return

        pdf_path = dlg.FileName
        # Derive companion paths in same folder as user-chosen pdf
        out_folder = IOPath.GetDirectoryName(pdf_path)
        base = IOPath.GetFileNameWithoutExtension(pdf_path)
        if not out_folder:
            out_folder = OUTPUT_DIR
            self._ensure_output_dir()

        html_path = os.path.join(out_folder, base + ".html")
        img_dir = os.path.join(out_folder, base + "_images")
        if not os.path.exists(img_dir):
            try:
                os.makedirs(img_dir)
            except Exception:
                pass

        # Save snapshot bytes to disk so HTML <img> can reference them
        for issue in self.issues:
            if issue.snapshot_bytes is not None:
                img_path = os.path.join(img_dir, issue.guid + ".png")
                if not os.path.exists(img_path):
                    try:
                        File.WriteAllBytes(img_path, issue.snapshot_bytes)
                    except Exception:
                        pass

        html = self._build_html_report(img_dir)
        from System.IO import File as IOFile
        IOFile.WriteAllText(html_path, html, Encoding.UTF8)

        # Try multiple PDF conversion methods in order of reliability
        pdf_ok = False
        method_used = ""

        # Method 1: Microsoft Edge headless (built-in on Windows 10/11)
        if not pdf_ok:
            if self._try_html_to_pdf_edge(html_path, pdf_path):
                pdf_ok = True
                method_used = "Microsoft Edge"

        # Method 2: Word interop (if Office installed)
        if not pdf_ok:
            if self._try_html_to_pdf_word(html_path, pdf_path):
                pdf_ok = True
                method_used = "Microsoft Word"

        if pdf_ok:
            self.set_status("Exported PDF via {}: {}".format(method_used, pdf_path))
            TaskDialog.Show("DQT BCF Reader",
                "PDF exported via {}:\n{}".format(method_used, pdf_path))
            try:
                System.Diagnostics.Process.Start(pdf_path)
            except Exception:
                pass
        else:
            # Fallback: open HTML in default browser; user prints to PDF
            self.set_status("Saved HTML report (open and print to PDF): " + html_path)
            td = TaskDialog("DQT BCF Reader")
            td.MainInstruction = "PDF conversion unavailable"
            td.MainContent = ("Microsoft Word interop not found.\n\n"
                "HTML report saved to:\n" + html_path + "\n\n"
                "Opening in browser - press Ctrl+P then 'Save as PDF'.")
            td.Show()
            try:
                System.Diagnostics.Process.Start(html_path)
            except Exception:
                pass

    def _try_html_to_pdf_edge(self, html_path, pdf_path):
        """Convert HTML to PDF using Microsoft Edge headless mode.
        Edge is built into Windows 10/11 - no installation needed.
        Returns True on success."""
        # Common Edge executable paths
        edge_paths = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
        ]
        edge_exe = None
        for p in edge_paths:
            if p and os.path.exists(p):
                edge_exe = p
                break
        if edge_exe is None:
            # Try Chrome as alternative
            chrome_paths = [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            ]
            for p in chrome_paths:
                if os.path.exists(p):
                    edge_exe = p
                    break
        if edge_exe is None:
            return False

        # Delete existing pdf so we can verify creation
        if File.Exists(pdf_path):
            try:
                File.Delete(pdf_path)
            except Exception:
                pass

        try:
            from System.Diagnostics import Process, ProcessStartInfo
            psi = ProcessStartInfo()
            psi.FileName = edge_exe
            # File URL for HTML input
            html_uri = "file:///" + html_path.replace("\\", "/")
            psi.Arguments = (
                '--headless=new --disable-gpu --no-pdf-header-footer '
                '--print-to-pdf="{}" "{}"'.format(pdf_path, html_uri))
            psi.UseShellExecute = False
            psi.CreateNoWindow = True
            psi.RedirectStandardOutput = True
            psi.RedirectStandardError = True
            proc = Process.Start(psi)
            # Wait up to 30 seconds
            if not proc.WaitForExit(30000):
                try:
                    proc.Kill()
                except Exception:
                    pass
                return False
            return File.Exists(pdf_path)
        except Exception:
            return False

    def _try_html_to_pdf_word(self, html_path, pdf_path):
        """Convert HTML to PDF using late-bound COM to Word.Application.
        This avoids needing Microsoft.Office.Interop.Word PIA - works on any
        machine that has Word installed (including Office 365 click-to-run).
        Returns True on success."""
        word_app = None
        doc_obj = None
        try:
            # Late binding via COM ProgID - no PIA needed
            from System import Type, Activator
            word_type = Type.GetTypeFromProgID("Word.Application")
            if word_type is None:
                return False
            word_app = Activator.CreateInstance(word_type)

            # Word Application properties via COM late binding
            # Visible = False
            try:
                word_type.InvokeMember(
                    "Visible",
                    System.Reflection.BindingFlags.SetProperty,
                    None, word_app, System.Array[System.Object]([False]))
            except Exception:
                pass

            # Get Documents collection
            documents = word_type.InvokeMember(
                "Documents",
                System.Reflection.BindingFlags.GetProperty,
                None, word_app, None)

            # Documents.Open(html_path, False, True) -> ConfirmConversions=False, ReadOnly=True
            doc_obj = documents.GetType().InvokeMember(
                "Open",
                System.Reflection.BindingFlags.InvokeMethod,
                None, documents,
                System.Array[System.Object]([html_path, False, True]))

            # ExportAsFixedFormat: pdf format=17, range=0 (all), item=0 (content), bookmarks=0
            # Signature: ExportAsFixedFormat(OutputFileName, ExportFormat, OpenAfterExport,
            #   OptimizeFor, Range, From, To, Item, IncludeDocProps, KeepIRM,
            #   CreateBookmarks, DocStructureTags, BitmapMissingFonts, UseISO19005_1)
            args = System.Array[System.Object]([
                pdf_path,    # OutputFileName
                17,          # ExportFormat = wdExportFormatPDF
                False,       # OpenAfterExport
                0,           # OptimizeFor = wdExportOptimizeForPrint
                0,           # Range = wdExportAllDocument
                0, 0,        # From, To
                0,           # Item = wdExportDocumentContent
                True,        # IncludeDocProps
                True,        # KeepIRM
                0,           # CreateBookmarks = wdExportCreateNoBookmarks
                True, True, False  # DocStructureTags, BitmapMissingFonts, UseISO19005_1
            ])
            doc_obj.GetType().InvokeMember(
                "ExportAsFixedFormat",
                System.Reflection.BindingFlags.InvokeMethod,
                None, doc_obj, args)

            return File.Exists(pdf_path)
        except Exception:
            return False
        finally:
            try:
                if doc_obj is not None:
                    doc_obj.GetType().InvokeMember(
                        "Close",
                        System.Reflection.BindingFlags.InvokeMethod,
                        None, doc_obj,
                        System.Array[System.Object]([False]))
            except Exception:
                pass
            try:
                if word_app is not None:
                    word_app.GetType().InvokeMember(
                        "Quit",
                        System.Reflection.BindingFlags.InvokeMethod,
                        None, word_app,
                        System.Array[System.Object]([False]))
            except Exception:
                pass

    def _build_html_report(self, img_dir):
        """Generate a self-contained HTML report from issues."""
        n_total = len(self.issues)
        n_added = sum(1 for i in self.issues if i.label == "ADDED")
        n_removed = sum(1 for i in self.issues if i.label == "REMOVED")
        n_modified = sum(1 for i in self.issues if i.label == "MODIFIED")
        n_resolved = sum(1 for i in self.issues if i.resolved)

        proj_name = ""
        file_name = ""
        if self.reader:
            proj_name = self.reader.project_name or ""
            if self.reader.filepath:
                file_name = IOPath.GetFileName(self.reader.filepath)

        from datetime import datetime
        gen_time = datetime.now().strftime("%Y-%m-%d %H:%M")

        css = """
        body{font-family:'Segoe UI',Arial,sans-serif;margin:24px;color:#333;background:#fff;}
        h1{color:#5D4E37;border-bottom:3px solid #F0CC88;padding-bottom:8px;}
        .meta{color:#7B6F5A;font-size:12px;margin-bottom:24px;}
        .stats{display:flex;gap:12px;margin-bottom:24px;flex-wrap:wrap;}
        .stat{flex:1;min-width:120px;padding:12px;border:1px solid #D4B87A;border-radius:5px;text-align:center;background:#FEF8E7;}
        .stat .num{font-size:28px;font-weight:bold;color:#5D4E37;}
        .stat .lbl{font-size:11px;color:#7B6F5A;text-transform:uppercase;}
        .stat.added{background:#E8F5E9;}.stat.added .num{color:#27AE60;}
        .stat.removed{background:#FDEDEC;}.stat.removed .num{color:#E74C3C;}
        .stat.modified{background:#FEF5E7;}.stat.modified .num{color:#F39C12;}
        .stat.resolved{background:#E8F5E9;}.stat.resolved .num{color:#27AE60;}
        .issue{border:1px solid #D4B87A;border-radius:5px;margin-bottom:16px;overflow:hidden;page-break-inside:avoid;}
        .issue-header{background:#F0CC88;color:#5D4E37;padding:10px 14px;font-weight:bold;display:flex;justify-content:space-between;align-items:center;}
        .badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:bold;color:#fff;margin-right:8px;}
        .badge.ADDED{background:#27AE60;}.badge.REMOVED{background:#E74C3C;}.badge.MODIFIED{background:#F39C12;}.badge.OTHER{background:#95A5A6;}
        .badge.RESOLVED{background:#27AE60;border:1px solid #1e7e34;}
        .issue-body{padding:14px;display:flex;gap:16px;}
        .issue-img{flex-shrink:0;width:280px;}
        .issue-img img{max-width:100%;border:1px solid #ddd;border-radius:3px;}
        .issue-info{flex:1;font-size:12px;}
        .issue-info table{border-collapse:collapse;width:100%;}
        .issue-info td{padding:4px 8px;border-bottom:1px solid #f0e8d8;vertical-align:top;}
        .issue-info td.k{font-weight:bold;color:#5D4E37;width:120px;}
        .desc{margin-top:10px;padding:10px;background:#FEF8E7;border-left:3px solid #F0CC88;border-radius:3px;font-size:11px;line-height:1.5;}
        .footer{margin-top:32px;padding-top:12px;border-top:1px solid #D4B87A;color:#7B6F5A;font-size:10px;text-align:center;}
        """
        out = []
        out.append("<!DOCTYPE html><html><head><meta charset='utf-8'>")
        out.append("<title>BCF Report - " + self._html_esc(file_name) + "</title>")
        out.append("<style>" + css + "</style></head><body>")
        out.append("<h1>DQT BCF Reader - Issue Report</h1>")
        out.append("<div class='meta'>")
        if proj_name:
            out.append("<b>Project:</b> " + self._html_esc(proj_name) + " &nbsp;|&nbsp; ")
        out.append("<b>File:</b> " + self._html_esc(file_name))
        out.append(" &nbsp;|&nbsp; <b>Generated:</b> " + gen_time)
        out.append("</div>")

        # Stats
        out.append("<div class='stats'>")
        out.append("<div class='stat'><div class='num'>{}</div><div class='lbl'>Total</div></div>".format(n_total))
        out.append("<div class='stat added'><div class='num'>{}</div><div class='lbl'>Added</div></div>".format(n_added))
        out.append("<div class='stat removed'><div class='num'>{}</div><div class='lbl'>Removed</div></div>".format(n_removed))
        out.append("<div class='stat modified'><div class='num'>{}</div><div class='lbl'>Modified</div></div>".format(n_modified))
        out.append("<div class='stat resolved'><div class='num'>{}/{}</div><div class='lbl'>Resolved</div></div>".format(n_resolved, n_total))
        out.append("</div>")

        # Issues
        for issue in self.issues:
            out.append("<div class='issue'>")
            badge_html = "<span class='badge {}'>{}</span>".format(
                issue.label, issue.label)
            if issue.resolved:
                badge_html += "<span class='badge RESOLVED'>RESOLVED</span>"
            out.append("<div class='issue-header'>" + badge_html
                       + "Issue #" + str(issue.index) + " - "
                       + self._html_esc(self._truncate(issue.title, 100))
                       + "</div>")
            out.append("<div class='issue-body'>")
            if issue.snapshot_bytes is not None:
                # Reference image by relative path (same dir as html)
                img_rel = os.path.basename(img_dir) + "/" + issue.guid + ".png"
                out.append("<div class='issue-img'><img src='" + img_rel + "' /></div>")
            out.append("<div class='issue-info'><table>")
            if issue.element_ids:
                ids_str = ", ".join(str(x) for x in issue.element_ids)
                out.append("<tr><td class='k'>Element IDs</td><td>" + ids_str + "</td></tr>")
            elif issue.element_id is not None:
                out.append("<tr><td class='k'>Element ID</td><td>" + str(issue.element_id) + "</td></tr>")
            if issue.position:
                out.append("<tr><td class='k'>Position</td><td>({}, {}, {})</td></tr>".format(
                    str(round(issue.position[0], 3)),
                    str(round(issue.position[1], 3)),
                    str(round(issue.position[2], 3))))
            if issue.creation_date:
                out.append("<tr><td class='k'>Created</td><td>" + self._html_esc(issue.creation_date) + "</td></tr>")
            if issue.camera_type:
                out.append("<tr><td class='k'>Camera</td><td>" + self._html_esc(issue.camera_type) + "</td></tr>")
            if issue.components:
                out.append("<tr><td class='k'>Components</td><td>" + str(len(issue.components)) + "</td></tr>")
            if issue.ifc_guid:
                out.append("<tr><td class='k'>IFC GUID</td><td style='font-family:monospace;font-size:10px;'>" + self._html_esc(issue.ifc_guid) + "</td></tr>")
            out.append("</table>")
            if issue.description:
                out.append("<div class='desc'>" + self._html_esc(issue.description) + "</div>")
            out.append("</div></div></div>")

        out.append("<div class='footer'>DQT BCF Reader - Dang Quoc Truong &copy; 2025</div>")
        out.append("</body></html>")
        return "\n".join(out)

    def _html_esc(self, s):
        if s is None:
            return ""
        return (str(s)
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;"))

    # ------------------------------------------------------------------
    # Export BCF (with resolved flags embedded as Labels)
    # ------------------------------------------------------------------
    def on_export_bcf_click(self, sender, e):
        if not self.issues:
            TaskDialog.Show("DQT BCF Reader", "No issues loaded.")
            return
        if self.reader is None or not self.reader.filepath:
            TaskDialog.Show("DQT BCF Reader", "Original BCF file path unknown.")
            return

        # Suggest filename based on source
        orig = self.reader.filepath
        base = IOPath.GetFileNameWithoutExtension(orig)
        ext = IOPath.GetExtension(orig) or ".bcfzip"
        suggested = base + "_resolved" + ext

        # Let user choose location
        dlg = SaveFileDialog()
        dlg.Title = "Save BCF (with Resolved flags)"
        dlg.Filter = "BCF files (*.bcfzip;*.bcf)|*.bcfzip;*.bcf|All files (*.*)|*.*"
        dlg.FileName = suggested
        dlg.DefaultExt = ext
        # Default folder: same as original BCF if exists, else OUTPUT_DIR
        try:
            orig_dir = IOPath.GetDirectoryName(orig)
            if orig_dir and os.path.exists(orig_dir):
                dlg.InitialDirectory = orig_dir
            elif os.path.exists(OUTPUT_DIR):
                dlg.InitialDirectory = OUTPUT_DIR
        except Exception:
            pass
        if dlg.ShowDialog() != True:
            self.set_status("BCF export cancelled.")
            return
        out_path = dlg.FileName

        try:
            self.export_bcf(out_path)
            n_resolved = sum(1 for i in self.issues if i.resolved)
            TaskDialog.Show("DQT BCF Reader",
                "Exported BCF with {} resolved / {} total issues.\n\nSaved to:\n{}".format(
                    n_resolved, len(self.issues), out_path))
            self.set_status("Exported BCF: " + out_path)
        except Exception as ex:
            TaskDialog.Show("DQT BCF Reader",
                "Export BCF failed:\n" + str(ex) + "\n\n" + traceback.format_exc())

    def export_bcf(self, out_path):
        """Re-zip the original BCF but rewrite markup.bcf of each issue to
        add/remove 'RESOLVED' label according to issue.resolved flag."""
        from System.IO.Compression import ZipArchiveMode
        from System.IO import FileMode, FileStream, FileAccess, FileShare

        self._ensure_output_dir()
        if File.Exists(out_path):
            File.Delete(out_path)

        # Map guid -> resolved
        resolved_map = {}
        for it in self.issues:
            resolved_map[it.guid] = it.resolved

        src_archive = ZipFile.OpenRead(self.reader.filepath)
        try:
            # FileShare.None clashes with Python keyword - use getattr
            fs_none = getattr(FileShare, "None")
            out_stream = FileStream(out_path, FileMode.Create, FileAccess.ReadWrite, fs_none)
            try:
                out_archive = System.IO.Compression.ZipArchive(
                    out_stream, ZipArchiveMode.Create)
                try:
                    for entry in src_archive.Entries:
                        full = entry.FullName.replace("\\", "/")
                        parts = full.split("/")
                        filename = parts[-1].lower() if parts else ""
                        folder = parts[0] if len(parts) >= 2 else ""

                        new_entry = out_archive.CreateEntry(entry.FullName)
                        entry_stream = new_entry.Open()
                        try:
                            if filename == "markup.bcf" and folder in resolved_map:
                                xml_text = self._read_entry_text_src(entry)
                                new_xml = self._rewrite_markup_labels(
                                    xml_text, resolved_map[folder])
                                data = Encoding.UTF8.GetBytes(new_xml)
                                entry_stream.Write(data, 0, data.Length)
                            else:
                                src_stream = entry.Open()
                                try:
                                    src_stream.CopyTo(entry_stream)
                                finally:
                                    src_stream.Dispose()
                        finally:
                            entry_stream.Dispose()
                finally:
                    out_archive.Dispose()
            finally:
                out_stream.Dispose()
        finally:
            src_archive.Dispose()

    def _read_entry_text_src(self, entry):
        stream = entry.Open()
        try:
            reader = StreamReader(stream, Encoding.UTF8)
            try:
                return reader.ReadToEnd()
            finally:
                reader.Dispose()
        finally:
            stream.Dispose()

    def _rewrite_markup_labels(self, xml_text, resolved):
        """Add or remove <Labels>DQT_RESOLVED</Labels> in markup.bcf XML."""
        # Remove any existing DQT_RESOLVED labels
        xml_text = re.sub(
            r'\s*<Labels>\s*DQT_RESOLVED\s*</Labels>', '', xml_text,
            flags=re.IGNORECASE)
        xml_text = re.sub(
            r'\s*<Labels>\s*RESOLVED\s*</Labels>', '', xml_text,
            flags=re.IGNORECASE)

        if resolved:
            # Insert <Labels>DQT_RESOLVED</Labels> just before </Topic>
            m = re.search(r'</Topic>', xml_text)
            if m:
                insert_pos = m.start()
                xml_text = (xml_text[:insert_pos]
                    + "  <Labels>DQT_RESOLVED</Labels>\n"
                    + xml_text[insert_pos:])
        return xml_text

    # ------------------------------------------------------------------
    # Export CSV
    # ------------------------------------------------------------------
    def export_summary_csv(self):
        # Suggest filename based on source BCF
        suggested = "BCF_Summary.csv"
        if self.reader and self.reader.filepath:
            base = IOPath.GetFileNameWithoutExtension(self.reader.filepath)
            suggested = "BCF_Summary_" + base + ".csv"

        # Let user choose location
        dlg = SaveFileDialog()
        dlg.Title = "Save CSV Summary"
        dlg.Filter = "CSV files (*.csv)|*.csv|All files (*.*)|*.*"
        dlg.FileName = suggested
        dlg.DefaultExt = ".csv"
        # Default folder: OUTPUT_DIR if exists, else Documents
        if os.path.exists(OUTPUT_DIR):
            dlg.InitialDirectory = OUTPUT_DIR
        if dlg.ShowDialog() != True:
            self.set_status("CSV export cancelled.")
            return
        out_path = dlg.FileName

        lines = []
        lines.append(",".join([
            "Index", "GUID", "Label", "Resolved", "Title", "ElementId",
            "IfcGuid", "X", "Y", "Z", "CameraType", "CreationDate"
        ]))
        for it in self.issues:
            pos = ("", "", "")
            if it.position is not None:
                pos = (str(round(it.position[0], 4)),
                       str(round(it.position[1], 4)),
                       str(round(it.position[2], 4)))
            row = [
                str(it.index),
                self._csv_esc(it.guid),
                self._csv_esc(it.label),
                "Yes" if it.resolved else "No",
                self._csv_esc(it.title),
                str(it.element_id) if it.element_id is not None else "",
                self._csv_esc(it.ifc_guid),
                pos[0], pos[1], pos[2],
                self._csv_esc(it.camera_type),
                self._csv_esc(it.creation_date),
            ]
            lines.append(",".join(row))

        from System.IO import File as IOFile
        IOFile.WriteAllText(out_path, "\n".join(lines), Encoding.UTF8)
        self.set_status("Exported {} issues to {}".format(len(self.issues), out_path))
        TaskDialog.Show("DQT BCF Reader",
            "Exported {} issues to:\n{}".format(len(self.issues), out_path))

    # ------------------------------------------------------------------
    def set_status(self, text):
        try:
            self.lblStatus.Text = text
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------
def main():
    _ensure_output_dir()
    try:
        xaml_file = script.get_bundle_file('BCFReaderWindow.xaml')
        if xaml_file is None or not os.path.exists(xaml_file):
            TaskDialog.Show("DQT BCF Reader",
                "BCFReaderWindow.xaml not found in bundle folder.\n"
                "Expected: same folder as script.py")
            return

        win = BCFManagerWindow(xaml_file)

        # Prompt for BCF before showing window
        win.prompt_open()

        # MODELESS via pyRevit.
        # WPFWindow.show() is modeless (non-blocking) by default - it calls
        # self.Show() on the underlying WPF Window. This is stable in
        # Revit 2024/2025/2026 because pyRevit's WPFWindow sets the Owner
        # to Revit's main window via WindowInteropHelper during __init__,
        # keeping the IronPython/CoreCLR boundary safe.
        # (Use show_dialog() if modal is needed.)
        win.show()
    except Exception as ex:
        TaskDialog.Show("DQT BCF Reader",
            "Unexpected error:\n\n" + str(ex) + "\n\n" + traceback.format_exc())


main()