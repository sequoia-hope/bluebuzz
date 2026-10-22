#!/usr/bin/env python3
"""Parametric generator and board-overlay renderer for design/squish_pcb.dxf.

The DXF in `design/squish_pcb.dxf` is an Onshape export (inward 10 mm offset of
a 50 x 60 mm ellipse centered at (0, 90) with a top dome and concave lower neck):
  - Top dome (Entity 3): ARC centered at (0, 114.9), r = 10.0 mm, reaching
    y_dxf = 124.9 mm, tangent at (+/-9.7758, 117.0055) to:
  - Straight taper lines (Entities 2, 4): to (+/-14.4289, 95.4014), tangent to:
  - Belly splines (Entities 1, 5): cubic B-splines (10 mm inward offset of an
    ellipse A=25, B=30 at (0, 90)), widest at (+/-15.0019, 90.0), ending at
    (+/-12.9505, 80.0111), tangent to:
  - Concave neck arcs (Entities 0, 6): centered at (+/-99.168217, 42.030381),
    R = 94.212670 mm, tangent near the bottom to:
  - Lower tip arc (Entity 7): in the DXF, centered at (0, 45.0) with radius
    r_tip = 5.0 mm (diameter 10.0 mm), reaching y_dxf = 40.0 mm.

Making `r_tip` larger moves the lower tip circle's center (0, y_c) up along the
symmetry axis so that it stays externally tangent to both R = 94.212670 mm
concave neck arcs:
    y_c(r_tip) = C_y + sqrt((R_concave + r_tip)^2 - C_x^2)
    y_bottom_dxf(r_tip) = y_c(r_tip) - r_tip

When aligned with the top of the bulbous head (y_dxf = 124.9) flush with the
top (RM2 antenna) edge of the current 28 x 44 mm board (y_pcb = -22.0 mm, +y down):
    x_pcb = x_dxf
    y_pcb = -22.0 + (124.9 - y_dxf) = 102.9 - y_dxf
"""
import argparse
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DXF_PATH = ROOT / "design" / "squish_pcb.dxf"

# Exact CAD constants from design/squish_pcb.dxf
TOP_ARC_CENTER_DXF = (0.0, 114.9)
TOP_ARC_RADIUS = 10.0
TOP_Y_DXF = TOP_ARC_CENTER_DXF[1] + TOP_ARC_RADIUS  # 124.9 mm

LINE_TOP_PT = (9.775835696593326, 117.0054777209013)
LINE_BOT_PT = (14.42883317048328, 95.40138362393799)

CONCAVE_CX = 99.16821745287605
CONCAVE_CY = 42.03038149933658
CONCAVE_R = 94.21267049535906
CONCAVE_TOP_ANGLE_DEG = 156.2255256859636  # at (12.9504838, 80.0110594)


def _de_boor(k, u, knots, ctrl, p=3):
    """Evaluate degree-p B-spline at parameter u in knot span k."""
    d = [ctrl[j + k - p] for j in range(p + 1)]
    for r in range(1, p + 1):
        for j in range(p, r - 1, -1):
            denom = knots[j + 1 + k - r] - knots[j + k - p]
            alpha = (u - knots[j + k - p]) / denom if denom != 0 else 0.0
            d[j] = (1.0 - alpha) * d[j - 1] + alpha * d[j]
    return d[p]


def load_dxf_spline(dxf_path=DXF_PATH):
    """Extract the right-hand belly spline (Entity 1) knots and control points."""
    lines = [l.strip() for l in dxf_path.read_text().splitlines()]
    pairs = [(int(lines[i]), lines[i + 1]) for i in range(0, len(lines) - 1, 2)]
    in_ent = False
    ent = None
    ents = []
    for code, val in pairs:
        if code == 2 and val == "ENTITIES":
            in_ent = True
            continue
        if in_ent:
            if code == 0 and val == "ENDSEC":
                break
            if code == 0:
                if ent:
                    ents.append(ent)
                ent = {"type": val, "props": []}
            elif ent is not None:
                ent["props"].append((code, val))
    if ent:
        ents.append(ent)
    # First SPLINE is the right-hand side (x > 0), from y=95.4014 down to y=80.0111
    sp = next(e for e in ents if e["type"] == "SPLINE")
    knots = [float(v) for c, v in sp["props"] if c == 40]
    xs = [float(v) for c, v in sp["props"] if c == 10]
    ys = [float(v) for c, v in sp["props"] if c == 20]
    return knots, xs, ys


def sample_right_spline(n_samples=120, dxf_path=DXF_PATH, offset_mm=0.0):
    """Sample the right-side belly B-spline from (14.4289, 95.4014) to (12.9505, 80.0111),
    optionally offset inward by `offset_mm` along the local normal."""
    knots, xs, ys = load_dxf_spline(dxf_path)
    p = 3
    u0, u1 = knots[p], knots[-p - 1]
    pts = []
    for i in range(n_samples):
        u = u0 + (u1 - u0) * i / (n_samples - 1)
        k = p
        for j in range(p, len(knots) - p - 1):
            if knots[j] <= u <= knots[j + 1]:
                k = j
        pts.append((_de_boor(k, u, knots, xs, p), _de_boor(k, u, knots, ys, p)))
    if abs(offset_mm) < 1e-9:
        return pts
    a_top = math.radians(12.15445501118053)
    a_bot = math.radians(CONCAVE_TOP_ANGLE_DEG)
    out = []
    for i, (x, y) in enumerate(pts):
        if i == 0:
            nx, ny = math.cos(a_top), math.sin(a_top)
        elif i == len(pts) - 1:
            nx, ny = -math.cos(a_bot), -math.sin(a_bot)
        else:
            dx = pts[i + 1][0] - pts[i - 1][0]
            dy = pts[i + 1][1] - pts[i - 1][1]
            L = math.hypot(dx, dy)
            nx, ny = -dy / L, dx / L
        out.append((x - offset_mm * nx, y - offset_mm * ny))
    return out


def solve_lower_tip(r_tip, offset_mm=0.0):
    """Compute center, bottom y, and tangent points for a lower tip arc of radius `r_tip`
    tangent to the two R=94.2127 mm concave neck arcs in DXF coordinates (+y up),
    optionally offset inward by `offset_mm`."""
    dist = CONCAVE_R + r_tip
    if dist < CONCAVE_CX:
        raise ValueError(f"r_tip={r_tip} too small to bridge concave arcs")
    yc_dxf = CONCAVE_CY + math.sqrt(dist * dist - CONCAVE_CX * CONCAVE_CX)
    alpha_rad = math.atan2(yc_dxf - CONCAVE_CY, CONCAVE_CX)
    alpha_deg = math.degrees(alpha_rad)

    r_tip_eff = r_tip - offset_mm
    concave_r_eff = CONCAVE_R + offset_mm
    top_r_eff = TOP_ARC_RADIUS - offset_mm
    top_y_eff = TOP_ARC_CENTER_DXF[1] + top_r_eff

    # Tangent point on the right side (x > 0)
    tx = r_tip_eff * math.cos(alpha_rad)
    ty_dxf = yc_dxf - r_tip_eff * math.sin(alpha_rad)
    y_bot_dxf = yc_dxf - r_tip_eff

    return {
        "r_tip": r_tip,
        "r_tip_eff": r_tip_eff,
        "offset_mm": offset_mm,
        "concave_r_eff": concave_r_eff,
        "top_r_eff": top_r_eff,
        "top_y_eff": top_y_eff,
        "diam_tip": 2.0 * r_tip_eff,
        "yc_dxf": yc_dxf,
        "y_bot_dxf": y_bot_dxf,
        "alpha_deg": alpha_deg,
        "tangent_right_dxf": (tx, ty_dxf),
        "tangent_left_dxf": (-tx, ty_dxf),
        "right_concave_angles_deg": (CONCAVE_TOP_ANGLE_DEG, 180.0 - alpha_deg),
        "left_concave_angles_deg": (alpha_deg, 180.0 - CONCAVE_TOP_ANGLE_DEG),
        "tip_arc_angles_deg": (180.0 + alpha_deg, 360.0 - alpha_deg),
        "total_height_mm": top_y_eff - y_bot_dxf,
        "shift_up_from_r5_mm": y_bot_dxf - 40.0,
    }


def dxf_to_pcb(x_dxf, y_dxf, top_y_pcb=-22.0):
    """Map DXF (x, y) (+y up) to KiCad centre-relative (x, y) (+y down),
    with the top of the un-offset bulbous head (y_dxf = 124.9) at `top_y_pcb` (-22.0 mm)."""
    return (x_dxf, top_y_pcb + (TOP_Y_DXF - y_dxf))


def generate_outline_points_pcb(r_tip=5.0, top_y_pcb=-22.0, n_arc=90, n_spline=100, offset_mm=0.0):
    """Return a closed polyline [(x_pcb, y_pcb), ...] for the squish outline with
    lower tip radius `r_tip` mm (inward offset `offset_mm`), plus metadata dictionary."""
    info = solve_lower_tip(r_tip, offset_mm=offset_mm)
    spline_right = sample_right_spline(n_spline, offset_mm=offset_mm)
    top_r = info["top_r_eff"]
    concave_r = info["concave_r_eff"]
    r_tip_eff = info["r_tip_eff"]

    a_line = math.radians(12.15445501118053)
    nx_line, ny_line = math.cos(a_line), math.sin(a_line)
    l_top = (LINE_TOP_PT[0] - offset_mm * nx_line, LINE_TOP_PT[1] - offset_mm * ny_line)
    l_bot = (LINE_BOT_PT[0] - offset_mm * nx_line, LINE_BOT_PT[1] - offset_mm * ny_line)

    pts_dxf = []

    # 1. Top dome arc (from left tangent 167.8455 deg to right tangent 12.1545 deg)
    a_top_start = math.radians(180.0 - 12.15445501118053)
    a_top_end = math.radians(12.15445501118053)
    for a in np.linspace(a_top_start, a_top_end, n_arc):
        pts_dxf.append((
            TOP_ARC_CENTER_DXF[0] + top_r * math.cos(a),
            TOP_ARC_CENTER_DXF[1] + top_r * math.sin(a),
        ))

    # 2. Right straight taper line: l_top -> l_bot
    pts_dxf.append(l_top)
    pts_dxf.append(l_bot)

    # 3. Right belly spline
    pts_dxf.extend(spline_right[1:])

    # 4. Right concave neck arc: from 156.2255 deg to (180 - alpha) deg
    a0, a1 = info["right_concave_angles_deg"]
    for a in np.linspace(math.radians(a0), math.radians(a1), n_arc)[1:]:
        pts_dxf.append((
            CONCAVE_CX + concave_r * math.cos(a),
            CONCAVE_CY + concave_r * math.sin(a),
        ))

    # 5. Lower tip arc: centered at (0, yc_dxf), radius r_tip_eff, from (360 - alpha) down through 270 to (180 + alpha)
    ta0, ta1 = info["tip_arc_angles_deg"]
    for a in np.linspace(math.radians(ta1), math.radians(ta0), n_arc)[1:]:
        pts_dxf.append((
            r_tip_eff * math.cos(a),
            info["yc_dxf"] + r_tip_eff * math.sin(a),
        ))

    # 6. Left concave neck arc: centered at (-CONCAVE_CX, CONCAVE_CY), from alpha to (180 - 156.2255) deg
    la0, la1 = info["left_concave_angles_deg"]
    for a in np.linspace(math.radians(la0), math.radians(la1), n_arc)[1:]:
        pts_dxf.append((
            -CONCAVE_CX + concave_r * math.cos(a),
            CONCAVE_CY + concave_r * math.sin(a),
        ))

    # 7. Left belly spline
    for sx, sy in reversed(spline_right[:-1]):
        pts_dxf.append((-sx, sy))

    # 8. Left straight taper line: (-l_bot) -> (-l_top)
    pts_dxf.append((-l_bot[0], l_bot[1]))
    pts_dxf.append((-l_top[0], l_top[1]))
    pts_dxf.append(pts_dxf[0])

    pts_pcb = [dxf_to_pcb(x, y, top_y_pcb=top_y_pcb) for x, y in pts_dxf]
    info["y_top_pcb"] = dxf_to_pcb(0, info["top_y_eff"], top_y_pcb=top_y_pcb)[1]
    info["y_bot_pcb"] = dxf_to_pcb(0, info["y_bot_dxf"], top_y_pcb=top_y_pcb)[1]
    info["yc_pcb"] = dxf_to_pcb(0, info["yc_dxf"], top_y_pcb=top_y_pcb)[1]
    info["tangent_right_pcb"] = dxf_to_pcb(*info["tangent_right_dxf"], top_y_pcb=top_y_pcb)
    info["tangent_left_pcb"] = dxf_to_pcb(*info["tangent_left_dxf"], top_y_pcb=top_y_pcb)
    return pts_pcb, info


def add_squish_outline_to_board(board, r_tip=5.0, top_y_pcb=-22.0, layer=None, width_mm=0.1, center=(100.0, 100.0), offset_mm=0.0):
    """Add the parametric squish outline to a pcbnew.BOARD (default Edge.Cuts)."""
    import pcbnew
    if layer is None:
        layer = pcbnew.Edge_Cuts

    def vec(x, y):
        return pcbnew.VECTOR2I(pcbnew.FromMM(center[0] + x), pcbnew.FromMM(center[1] + y))

    def add_seg(p0, p1):
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(vec(*p0))
        s.SetEnd(vec(*p1))
        s.SetLayer(layer)
        s.SetWidth(pcbnew.FromMM(width_mm))
        board.Add(s)

    def add_arc_dxf(cx_dxf, cy_dxf, r, a0_deg, a1_deg):
        am_deg = 0.5 * (a0_deg + a1_deg)
        p0 = dxf_to_pcb(cx_dxf + r * math.cos(math.radians(a0_deg)),
                        cy_dxf + r * math.sin(math.radians(a0_deg)), top_y_pcb)
        pm = dxf_to_pcb(cx_dxf + r * math.cos(math.radians(am_deg)),
                        cy_dxf + r * math.sin(math.radians(am_deg)), top_y_pcb)
        p1 = dxf_to_pcb(cx_dxf + r * math.cos(math.radians(a1_deg)),
                        cy_dxf + r * math.sin(math.radians(a1_deg)), top_y_pcb)
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_ARC)
        s.SetArcGeometry(vec(*p0), vec(*pm), vec(*p1))
        s.SetLayer(layer)
        s.SetWidth(pcbnew.FromMM(width_mm))
        board.Add(s)

    info = solve_lower_tip(r_tip, offset_mm=offset_mm)
    top_r = info["top_r_eff"]
    concave_r = info["concave_r_eff"]
    r_tip_eff = info["r_tip_eff"]
    a_line = math.radians(12.15445501118053)
    nx_line, ny_line = math.cos(a_line), math.sin(a_line)
    l_top = (LINE_TOP_PT[0] - offset_mm * nx_line, LINE_TOP_PT[1] - offset_mm * ny_line)
    l_bot = (LINE_BOT_PT[0] - offset_mm * nx_line, LINE_BOT_PT[1] - offset_mm * ny_line)

    # Top dome arc
    add_arc_dxf(0.0, 114.9, top_r, 12.15445501118053, 167.845544988819)
    # Right and left straight taper lines
    add_seg(dxf_to_pcb(*l_top, top_y_pcb), dxf_to_pcb(*l_bot, top_y_pcb))
    add_seg(dxf_to_pcb(-l_top[0], l_top[1], top_y_pcb),
            dxf_to_pcb(-l_bot[0], l_bot[1], top_y_pcb))
    # Right and left belly splines (dense polyline segments)
    sp = sample_right_spline(80, offset_mm=offset_mm)
    for i in range(len(sp) - 1):
        add_seg(dxf_to_pcb(*sp[i], top_y_pcb), dxf_to_pcb(*sp[i + 1], top_y_pcb))
        add_seg(dxf_to_pcb(-sp[i][0], sp[i][1], top_y_pcb),
                dxf_to_pcb(-sp[i + 1][0], sp[i + 1][1], top_y_pcb))
    # Right and left concave neck arcs
    add_arc_dxf(CONCAVE_CX, CONCAVE_CY, concave_r, *info["right_concave_angles_deg"])
    add_arc_dxf(-CONCAVE_CX, CONCAVE_CY, concave_r, *info["left_concave_angles_deg"])
    # Lower tip arc
    add_arc_dxf(0.0, info["yc_dxf"], r_tip_eff, *info["tip_arc_angles_deg"])
    return info


def export_layout_crop_png(out_png, xlim=(-20.0, 20.0), ylim=(-25.0, 66.0)):
    """Export an exact millimetre-registered 2D layout PNG from out/bluebuzz-rm2.kicad_pcb
    covering the requested centre-relative mm box `xlim` x `ylim`."""
    import subprocess
    import tempfile
    import xml.etree.ElementTree as ET

    pcb_path = ROOT / "out" / "bluebuzz-rm2.kicad_pcb"
    layers = "B.Cu,In4.Cu,In3.Cu,In2.Cu,In1.Cu,F.Cu,F.Silkscreen,F.Fab,Edge.Cuts"
    with tempfile.TemporaryDirectory() as tmp:
        svg_path = Path(tmp) / "board_sheet.svg"
        subprocess.run(
            ["kicad-cli", "pcb", "export", "svg", "--mode-single",
             "--layers", layers, "--page-size-mode", "0",
             "--exclude-drawing-sheet", "-o", str(svg_path), str(pcb_path)],
            check=True, capture_output=True, text=True,
        )
        tree = ET.parse(svg_path)
        root = tree.getroot()
        vx0 = 100.0 + xlim[0]
        vy0 = 100.0 + ylim[0]
        vw = xlim[1] - xlim[0]
        vh = ylim[1] - ylim[0]
        root.set("viewBox", f"{vx0:.4f} {vy0:.4f} {vw:.4f} {vh:.4f}")
        root.set("width", f"{vw:.4f}mm")
        root.set("height", f"{vh:.4f}mm")
        tree.write(svg_path)
        subprocess.run(
            ["magick", "-density", "450", "-background", "#14171c",
             str(svg_path), str(out_png)],
            check=True, capture_output=True, text=True,
        )


def render_superimposed(out_path=None):
    """Render a 3-panel comparison (Front 3D, 2D Layout + Fab, Back 3D) with the
    current 28x44mm board outline and the parametric squish_pcb.dxf outlines
    superimposed."""
    import tempfile
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch
    from PIL import Image

    if out_path is None:
        out_path = ROOT / "out" / "squish_outline_overlay.png"

    xlim = (-21.5, 36.5)
    ylim = (-25.5, 66.5)  # +y is DOWN in PCB coords

    # Calibrated pixel-to-mm mapping of out/render_top.png & render_bottom.png:
    rtop_img = Image.open(ROOT / "out" / "render_top.png").convert("RGBA")
    rbot_img = Image.open(ROOT / "out" / "render_bottom.png").convert("RGBA")
    rw, rh = rtop_img.size
    rgb = np.array(rtop_img, dtype=np.float32)[:, :, :3]
    gmask = (rgb[:, :, 1] > rgb[:, :, 0] + 12) & (rgb[:, :, 1] > rgb[:, :, 2] + 8) & (rgb[:, :, 1] < 140)
    g_ys, g_xs = np.where(gmask)
    px_x = float(g_xs.max() - g_xs.min()) / 26.0
    px_y = px_x
    cx_px = 0.5 * float(g_xs.min() + g_xs.max())
    cy_px = float(g_ys.min()) - (-18.0) * px_y

    pts_off2, info_off2 = generate_outline_points_pcb(r_tip=10.0, top_y_pcb=-20.0, offset_mm=2.0, n_arc=360, n_spline=300)
    right_off2 = sorted([(p[1], p[0]) for p in pts_off2 if p[0] >= -1e-6])
    off2_ys = np.array([p[0] for p in right_off2])
    off2_xs = np.array([p[1] for p in right_off2])

    # Make studio background outside the board transparent while keeping all on-board pixels 100% intact
    def _clean_3d_bg(im):
        arr = np.array(im, dtype=np.float32)
        h_px, w_px = arr.shape[:2]
        xs_px = np.arange(w_px)[None, :]
        ys_px = np.arange(h_px)[:, None]
        x_mm = (xs_px - cx_px) / px_x
        y_mm = (ys_px - cy_px) / px_y
        hw_mm = np.interp(y_mm, off2_ys, off2_xs, left=0.0, right=0.0)
        in_board = (y_mm >= info_off2["y_top_pcb"] - 0.15) & (y_mm <= info_off2["y_bot_pcb"] + 0.15) & (np.abs(x_mm) <= hw_mm + 0.15)
        in_usbc = (np.abs(x_mm) <= 4.8) & (y_mm >= 31.0) & (y_mm <= 38.3)
        in_sw1 = (np.abs(x_mm) <= 14.2) & (y_mm >= 19.0) & (y_mm <= 27.5)
        keep = in_board | in_usbc | in_sw1
        arr[~keep, 3] = 0.0
        return arr.astype(np.uint8)

    rtop_arr = _clean_3d_bg(rtop_img)
    rbot_arr = _clean_3d_bg(rbot_img)
    render_extent = [
        (0 - cx_px) / px_x,
        (rw - cx_px) / px_x,
        (rh - cy_px) / px_y,
        (0 - cy_px) / px_y,
    ]

    with tempfile.TemporaryDirectory() as tmp:
        lay_png = Path(tmp) / "lay.png"
        export_layout_crop_png(lay_png, xlim=xlim, ylim=ylim)
        lay_img = Image.open(lay_png).convert("RGBA")

    # Radii to plot:
    # Primary set (solid lines): r = 5, 6, 7 mm (diam = 10, 12, 14 mm)
    # Secondary set (dashed lines): r = 10, 12, 14 mm (diam = 20, 24, 28 mm)
    variants = [
        (5.0,  "#00e5ff", "-",  2.4, "r=5 mm (⌀10 mm, current DXF)"),
        (6.0,  "#22c55e", "-",  2.2, "r=6 mm (⌀12 mm)"),
        (7.0,  "#f59e0b", "-",  2.2, "r=7 mm (⌀14 mm)"),
        (10.0, "#ec4899", "--", 1.8, "r=10 mm (⌀20 mm)"),
        (12.0, "#a855f7", "--", 1.8, "r=12 mm (⌀24 mm)"),
        (14.0, "#ef4444", "--", 1.8, "r=14 mm (⌀28 mm)"),
    ]

    fig, axes = plt.subplots(1, 3, figsize=(21, 12.5), dpi=180, facecolor="#111318")
    fig.subplots_adjust(left=0.04, right=0.98, top=0.90, bottom=0.06, wspace=0.14)

    titles = [
        "Front (3D Render + Squish Outlines)",
        "2D Layout & Fab (Component Fit Check)",
        "Back (3D Render + Squish Outlines)",
    ]

    for idx, ax in enumerate(axes):
        ax.set_facecolor("#181b22")
        if idx == 0:
            ax.imshow(rtop_arr, extent=render_extent, zorder=1)
        elif idx == 1:
            ax.imshow(lay_img, extent=[xlim[0], xlim[1], ylim[1], ylim[0]], zorder=1)
        else:
            ax.imshow(rbot_arr, extent=render_extent, zorder=1)

        # Draw current 28x44 mm board outline (rounded rect r=2mm)
        rect_patch = FancyBboxPatch(
            (-12.0, -20.0), 24.0, 40.0,
            boxstyle="round,pad=2.0,rounding_size=2.0",
            fill=False, edgecolor="#ffffff", linestyle=":", linewidth=1.6,
            alpha=0.85, zorder=4, label="Current board (28 × 44 mm)"
        )
        ax.add_patch(rect_patch)

        # Draw RF keep-out line at y = -12.75 mm (for 2mm offset)
        ax.plot([-14, 14], [-12.75, -12.75], color="#fbbf24", linestyle=":", linewidth=1.0, alpha=0.7, zorder=3)
        ax.text(-13.5, -13.3, "RM2 RF keep-out (y < -12.75 mm)", color="#fbbf24", fontsize=7.5, alpha=0.85, zorder=6)

        # Draw active 2.0 mm inward-offset r=10 mm outline (26.0 x 56.84 mm)
        xs_off2 = [p[0] for p in pts_off2]
        ys_off2 = [p[1] for p in pts_off2]
        ax.plot(xs_off2, ys_off2, color="#10b981", linestyle="-", linewidth=2.6, zorder=6,
                label="r=10 mm, −2 mm offset (26.0 × 56.84 mm, active)")

        # Draw each squish_pcb variant
        for r_tip, color, ls, lw, label in variants:
            pts, info = generate_outline_points_pcb(r_tip=r_tip, top_y_pcb=-20.0)
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            ax.plot(xs, ys, color=color, linestyle=ls, linewidth=lw, zorder=5,
                    label=f"{label} → H={info['total_height_mm']:.1f} mm (↑{info['shift_up_from_r5_mm']:.1f} mm)")

            # Mark left & right tangent points where tip arc meets R=94.21mm concave arcs
            tx_r, ty_r = info["tangent_right_pcb"]
            tx_l, ty_l = info["tangent_left_pcb"]
            ax.scatter([tx_l, tx_r], [ty_r, ty_r], color=color, s=22, zorder=7, edgecolors="#111318", linewidths=0.6)

            # Mark bottom tip elevation callout on the right side
            y_bot = info["y_bot_pcb"]
            ax.plot([0, 15.2], [y_bot, y_bot], color=color, linestyle=":", linewidth=0.9, alpha=0.75, zorder=4)
            tag = (f"r={r_tip:g} (⌀{2*r_tip:g}): y={y_bot:+.1f} "
                   f"[H={info['total_height_mm']:.1f}mm, ↑{info['shift_up_from_r5_mm']:.1f}mm]")
            ax.text(15.5, y_bot, tag, color=color, fontsize=7.5, fontweight="bold",
                    va="center", ha="left", zorder=8,
                    bbox=dict(boxstyle="round,pad=0.15", facecolor="#111318", edgecolor="none", alpha=0.75))

        # Annotate key geometric transitions of squish_pcb.dxf
        # 1. Top dome tangent to straight lines at y_pcb = -14.11 mm (width 19.55 mm)
        ax.plot([-9.78, 9.78], [-14.11, -14.11], color="#94a3b8", linestyle="--", linewidth=0.7, alpha=0.5, zorder=3)
        # 2. Straight lines tangent to belly spline at y_pcb = +7.50 mm (width 28.86 mm)
        ax.plot([-14.43, 14.43], [7.50, 7.50], color="#94a3b8", linestyle="--", linewidth=0.7, alpha=0.5, zorder=3)
        # 3. Widest point of belly at y_pcb = +12.90 mm (width 30.00 mm)
        ax.plot([-15.0, 15.0], [12.90, 12.90], color="#38bdf8", linestyle=":", linewidth=0.9, alpha=0.6, zorder=3)
        ax.text(-20.2, 12.90, "max W\n30.0mm\n(y=+12.9)", color="#38bdf8", fontsize=6.8, va="center", ha="left", zorder=7)
        # 4. Spline tangent to concave R=94.2mm arcs at y_pcb = +22.89 mm (width 25.90 mm)
        ax.plot([-12.95, 12.95], [22.89, 22.89], color="#94a3b8", linestyle="--", linewidth=0.8, alpha=0.6, zorder=3)
        ax.text(-20.2, 22.89, "spline→arc\nW=25.9mm\n(y=+22.9)", color="#cbd5e1", fontsize=6.8, va="center", ha="left", zorder=7)

        # Callout current board bottom at y = +22.0 mm
        ax.plot([12.0, 15.2], [22.0, 22.0], color="#ffffff", linestyle=":", linewidth=0.9, alpha=0.7, zorder=4)
        ax.text(15.5, 21.3, "Current bottom: y=+22.0 [H=44.0mm]", color="#ffffff", fontsize=7.5,
                va="center", ha="left", zorder=8,
                bbox=dict(boxstyle="round,pad=0.15", facecolor="#111318", edgecolor="none", alpha=0.75))

        ax.set_xlim(xlim)
        ax.set_ylim(ylim[1], ylim[0])  # +y down
        ax.set_aspect("equal")
        ax.grid(True, color="#334155", linestyle=":", linewidth=0.5, alpha=0.45)
        ax.set_title(titles[idx], color="#f8fafc", fontsize=11.5, fontweight="bold", pad=10)
        ax.set_xlabel("x (mm from board centre)", color="#94a3b8", fontsize=9)
        if idx == 0:
            ax.set_ylabel("y (mm from board centre, +y down)", color="#94a3b8", fontsize=9)
        ax.tick_params(colors="#94a3b8", labelsize=8)
        for spine in ax.spines.values():
            spine.set_edgecolor("#334155")

    # Shared legend at top
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 0.965),
               ncol=4, frameon=True, facecolor="#1e222d", edgecolor="#334155",
               fontsize=8.5, labelcolor="#f1f5f9")
    fig.suptitle(
        "bluebuzz-rm2 — design/squish_pcb.dxf Superimposed on Current 28 × 44 mm Board (Top Edge Flush at y = −22 mm)",
        color="#ffffff", fontsize=13.5, fontweight="bold", y=0.99
    )

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=180, facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"wrote {out_path}")
    return out_path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--radius", type=float, default=5.0,
                    help="lower tip radius in mm (default: 5.0 = ⌀10 mm in DXF)")
    ap.add_argument("--render", action="store_true",
                    help="render superimposed comparison PNG to out/squish_outline_overlay.png")
    ap.add_argument("-o", "--output", type=Path,
                    help="output path for rendered image")
    args = ap.parse_args()

    for r in [5.0, 6.0, 7.0, 10.0, 12.0, 14.0]:
        info = solve_lower_tip(r)
        tx, ty_pcb = dxf_to_pcb(*info["tangent_right_dxf"])
        _, y_bot_pcb = dxf_to_pcb(0, info["y_bot_dxf"])
        print(f"r_tip={r:5.1f} mm (⌀{2*r:4.1f} mm): "
              f"total_H={info['total_height_mm']:6.2f} mm, "
              f"y_bot_pcb={y_bot_pcb:+6.2f} mm (moves up {info['shift_up_from_r5_mm']:+6.2f} mm), "
              f"tangent=({tx:.2f}, {ty_pcb:+.2f}) mm")

    if args.render or args.output:
        render_superimposed(args.output)


if __name__ == "__main__":
    main()

