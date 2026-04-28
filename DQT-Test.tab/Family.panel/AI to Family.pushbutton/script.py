# -*- coding: utf-8 -*-
"""
DQT Family Creator from JSON - v7
Arc.Create causes 'internal error code 1' in Revit 2026.
Fix: use polyline segments to approximate rounded corners.

Revit 2026 + pyRevit 6.1 (IronPython)
"""

__title__ = "AI to\nFamily"
__author__ = "DQT"

import clr
import json
import os
import time
import math

clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')

from Autodesk.Revit.DB import (
    XYZ, Line, Plane,
    CurveArray, CurveArrArray,
    Transaction, SaveAsOptions,
    FilteredElementCollector, ReferencePlane, SketchPlane,
    ForgeTypeId, BuiltInParameter
)

from pyrevit import forms, script

logger = script.get_logger()
uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document
app = __revit__.Application

SPEC_LENGTH = ForgeTypeId("autodesk.spec.aec:length-2.0.0")
GROUP_GEOMETRY = ForgeTypeId("autodesk.grouptype:geometry-2.0.0")
MIN_SEG = 0.001  # minimum segment length in feet


def mm2ft(v):
    return float(v) / 304.8


# ============================================================
# PROFILE LOOPS (all polyline-based, no Arc)
# ============================================================
def _rect_loop(w, d, ox=0, oy=0):
    hw, hd = mm2ft(w)/2, mm2ft(d)/2
    cx, cy = mm2ft(ox), mm2ft(oy)
    pts = [XYZ(cx-hw,cy-hd,0), XYZ(cx+hw,cy-hd,0),
           XYZ(cx+hw,cy+hd,0), XYZ(cx-hw,cy+hd,0)]
    lp = CurveArray()
    for i in range(4):
        lp.Append(Line.CreateBound(pts[i], pts[(i+1)%4]))
    return lp


def _oct_loop(dia, ox=0, oy=0):
    r = mm2ft(dia)/2
    cx, cy = mm2ft(ox), mm2ft(oy)
    pts = [XYZ(cx + r*math.cos(2*math.pi*i/8),
               cy + r*math.sin(2*math.pi*i/8), 0) for i in range(8)]
    lp = CurveArray()
    for i in range(8):
        lp.Append(Line.CreateBound(pts[i], pts[(i+1)%8]))
    return lp


def _rrect_loop(w, d, rad, ox=0, oy=0):
    """
    Rounded rectangle using POLYLINE segments (no Arc).
    Each corner is approximated with N_SEG straight segments.
    """
    rad = min(float(rad), min(w, d) / 2.0 - 1)
    if rad < 2:
        return _rect_loop(w, d, ox, oy)

    hw = mm2ft(w) / 2.0
    hd = mm2ft(d) / 2.0
    r = mm2ft(rad)
    cx = mm2ft(ox)
    cy = mm2ft(oy)

    N_SEG = 5  # segments per corner (5 = smooth enough)

    # Corner centers: BR, TR, TL, BL
    corners = [
        (cx + hw - r, cy - hd + r, -math.pi/2, 0),          # BR: -90 to 0
        (cx + hw - r, cy + hd - r, 0, math.pi/2),            # TR: 0 to 90
        (cx - hw + r, cy + hd - r, math.pi/2, math.pi),      # TL: 90 to 180
        (cx - hw + r, cy - hd + r, math.pi, 3*math.pi/2),    # BL: 180 to 270
    ]

    all_pts = []
    for (ccx, ccy, a_start, a_end) in corners:
        for i in range(N_SEG + 1):
            t = float(i) / N_SEG
            a = a_start + t * (a_end - a_start)
            px = ccx + r * math.cos(a)
            py = ccy + r * math.sin(a)
            all_pts.append(XYZ(px, py, 0))

    # Remove near-duplicate points
    clean = [all_pts[0]]
    for i in range(1, len(all_pts)):
        if all_pts[i].DistanceTo(clean[-1]) > MIN_SEG:
            clean.append(all_pts[i])
    # Remove last if same as first
    if len(clean) > 2 and clean[-1].DistanceTo(clean[0]) < MIN_SEG:
        clean.pop()

    lp = CurveArray()
    for i in range(len(clean)):
        p1 = clean[i]
        p2 = clean[(i + 1) % len(clean)]
        if p1.DistanceTo(p2) > MIN_SEG:
            lp.Append(Line.CreateBound(p1, p2))
    return lp


def build_loop(pd, ox=0, oy=0):
    t = pd.get("type", "rectangle")
    if t == "octagon":
        return _oct_loop(pd.get("diameter", 50), ox, oy)
    if t == "rounded_rect":
        return _rrect_loop(pd["width"], pd["depth"], pd.get("radius", 20), ox, oy)
    r = pd.get("corner_radius", pd.get("radius", 0))
    if r > 0:
        return _rrect_loop(pd.get("width", 100), pd.get("depth", 100), r, ox, oy)
    return _rect_loop(pd.get("width", 100), pd.get("depth", 100), ox, oy)


def build_caa(pd, ox=0, oy=0):
    arr = CurveArrArray()
    arr.Append(build_loop(pd, ox, oy))
    return arr


# ============================================================
# FAMILY UTILITIES
# ============================================================
def ensure_rp(fd, name, org, d):
    for rp in FilteredElementCollector(fd).OfClass(ReferencePlane).ToElements():
        if rp.Name == name:
            return rp
    L = mm2ft(2000)
    rp = fd.FamilyCreate.NewReferencePlane(org+d*L, org-d*L, XYZ.BasisZ, None)
    rp.Name = name
    return rp


def add_param(fd, name, inst, val):
    fm = fd.FamilyManager
    try:
        fp = fm.AddParameter(name, GROUP_GEOMETRY, SPEC_LENGTH, inst)
        if fp and val > 0:
            if fm.CurrentType is None:
                fm.NewType("Default")
            fm.Set(fp, mm2ft(val))
        return fp
    except Exception as ex:
        logger.warning("Param '{}': {}".format(name, str(ex)))
        return None


def get_subcat(fd, name, cache):
    if name in cache:
        return cache[name]
    try:
        fc = fd.OwnerFamily.FamilyCategory
        for sc in fc.SubCategories:
            if sc.Name == name:
                cache[name] = sc
                return sc
        sc = fd.Settings.Categories.NewSubcategory(fc, name)
        cache[name] = sc
        return sc
    except:
        return None


# ============================================================
# GEOMETRY
# ============================================================
def make_extrusion(fd, g, void=False):
    pr = g.get("profile", {})
    ox, oy = g.get("offset_x", 0), g.get("offset_y", 0)
    z0, z1 = g.get("extrusion_start", 0), g.get("extrusion_end", 100)
    profile = build_caa(pr, ox, oy)
    pl = Plane.CreateByNormalAndOrigin(XYZ.BasisZ, XYZ(0, 0, mm2ft(z0)))
    sp = SketchPlane.Create(fd, pl)
    return fd.FamilyCreate.NewExtrusion(not void, profile, sp, mm2ft(z1 - z0))


def make_blend(fd, g):
    bp = g.get("bottom_profile", g.get("profile", {}))
    tp = g.get("top_profile", bp)
    ox, oy = g.get("offset_x", 0), g.get("offset_y", 0)
    z0 = g.get("blend_start", g.get("extrusion_start", 0))
    z1 = g.get("blend_end", g.get("extrusion_end", 100))
    height = mm2ft(z1 - z0)

    bottom = build_caa(bp, ox, oy)
    top = build_caa(tp, ox, oy)

    pl = Plane.CreateByNormalAndOrigin(XYZ.BasisZ, XYZ(0, 0, mm2ft(z0)))
    sp = SketchPlane.Create(fd, pl)

    try:
        blend = fd.FamilyCreate.NewBlend(True, top, bottom, sp)
        if blend:
            # Try set height
            try:
                blend.TopOffset = height
            except:
                pass
            try:
                p = blend.get_Parameter(BuiltInParameter.BLEND_END_PARAM)
                if p and not p.IsReadOnly:
                    p.Set(height)
            except:
                pass
            try:
                for p in blend.Parameters:
                    nm = str(p.Definition.Name)
                    if ("End" in nm or "Top" in nm or "Second" in nm):
                        if not p.IsReadOnly:
                            p.Set(height)
                            break
            except:
                pass
        return blend
    except Exception as ex:
        logger.info("Blend fallback->extrusion for '{}'".format(g.get("id", "?")))
        avg = {
            "type": bp.get("type", "rectangle"),
            "width": (bp.get("width", 100) + tp.get("width", 100)) / 2.0,
            "depth": (bp.get("depth", 100) + tp.get("depth", 100)) / 2.0,
            "radius": (bp.get("radius", 0) + tp.get("radius", 0)) / 2.0,
        }
        fg = dict(g)
        fg["profile"] = avg
        fg["extrusion_start"] = z0
        fg["extrusion_end"] = z1
        return make_extrusion(fd, fg, False)


# ============================================================
# MAIN
# ============================================================
def run(json_path):
    with open(json_path, 'r') as f:
        data = json.load(f)

    info = data.get("family_info", {})
    dims = data.get("overall_dimensions", {})
    params = data.get("parameters", [])
    geoms = data.get("geometry", [])
    fname = info.get("name", "DQT_Family")

    ver = app.VersionNumber
    tmpl = None
    for p in [
        r"C:\ProgramData\Autodesk\RVT {}\Family Templates\English\Metric Furniture.rft",
        r"C:\ProgramData\Autodesk\RVT {}\Family Templates\English\Metric Generic Model.rft",
        r"C:\ProgramData\Autodesk\RVT {}\Family Templates\English_I\Metric Furniture.rft",
        r"C:\ProgramData\Autodesk\RVT {}\Family Templates\English_I\Metric Generic Model.rft",
    ]:
        pp = p.format(ver)
        if os.path.exists(pp):
            tmpl = pp
            break
    if not tmpl:
        tmpl = forms.pick_file(file_ext='rft', title='Select .rft')
        if not tmpl:
            return

    global fd
    fd = app.NewFamilyDocument(tmpl)
    if not fd:
        forms.alert("Cannot create family doc.")
        return

    t = Transaction(fd, "DQT AI to Family v7")
    t.Start()

    ct = {"solid": 0, "blend": 0, "void": 0, "param": 0}
    solids = []
    sc_cache = {}

    try:
        hw = mm2ft(dims.get("width", 1990)) / 2
        hd = mm2ft(dims.get("depth", 930)) / 2
        ensure_rp(fd, "Left", XYZ(-hw,0,0), XYZ.BasisY)
        ensure_rp(fd, "Right", XYZ(hw,0,0), XYZ.BasisY)
        ensure_rp(fd, "Front", XYZ(0,-hd,0), XYZ.BasisX)
        ensure_rp(fd, "Back", XYZ(0,hd,0), XYZ.BasisX)

        for p in params:
            fp = add_param(fd, p["name"], p.get("instance", True), p.get("value", 0))
            if fp:
                ct["param"] += 1

        # Solids
        for g in geoms:
            gt = g.get("type", "")
            gid = g.get("id", "?")
            if gt not in ("extrusion", "blend"):
                continue
            try:
                el = None
                if gt == "extrusion":
                    el = make_extrusion(fd, g)
                    ct["solid"] += 1
                else:
                    el = make_blend(fd, g)
                    ct["blend"] += 1
                if el:
                    solids.append(el)
                    hint = g.get("material_hint", "")
                    if hint:
                        sc = get_subcat(fd, hint, sc_cache)
                        if sc:
                            try:
                                el.Subcategory = sc
                            except:
                                pass
                    logger.info("OK: {} [{}]".format(gid, gt))
            except Exception as ex:
                logger.error("FAIL '{}': {}".format(gid, str(ex)))

        # Voids
        for g in geoms:
            if g.get("type") != "void_extrusion":
                continue
            gid = g.get("id", "?")
            try:
                ve = make_extrusion(fd, g, True)
                if ve:
                    for s in solids:
                        try:
                            fd.CombineElements(s, ve)
                        except:
                            pass
                    ct["void"] += 1
                    logger.info("VOID: {}".format(gid))
            except Exception as ex:
                logger.error("FAIL void '{}': {}".format(gid, str(ex)))

        t.Commit()

    except Exception as ex:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        forms.alert("Error:\n{}".format(str(ex)))
        fd.Close(False)
        return

    od = r"C:\Temp\DQT_FamilyCreator"
    if not os.path.exists(od):
        os.makedirs(od)
    ts = time.strftime("%H%M%S")
    sp = os.path.join(od, "{}_{}.rfa".format(fname, ts))
    try:
        opt = SaveAsOptions()
        opt.OverwriteExistingFile = True
        fd.SaveAs(sp, opt)
    except:
        sp = os.path.join(os.environ.get("TEMP", r"C:\Temp"), "{}_{}.rfa".format(fname, ts))
        try:
            fd.SaveAs(sp, opt)
        except Exception as ex:
            forms.alert("Save failed:\n{}".format(str(ex)))
            fd.Close(False)
            return

    try:
        uidoc.Application.OpenAndActivateDocument(sp)
    except:
        pass

    forms.alert(
        "LOD 300 Family!\n\n"
        "Extrusions: {}\nBlends: {}\nVoids: {}\nParams: {}\n\n"
        "File: {}".format(ct["solid"], ct["blend"], ct["void"], ct["param"], sp),
        title="DQT AI to Family v7"
    )


if __name__ == "__main__":
    jp = forms.pick_file(file_ext='json', title='Select Family JSON')
    if jp:
        run(jp)