#!/usr/bin/env python3
"""The RP2350's power copper, transplanted from Raspberry Pi's own layout.

The RP2350 datasheet (s6.3.8) says the core regulator layout "should be
placed first on any board design and these guidelines must be strictly
followed", and points at the minimal-board and Pico 2 designs. This module
reads that layout from the vendor's KiCad file (design/reference/, the
RP2350A minimal board, RP-006440-DD) and returns its power block relative
to U1's centre, so place.py and route.py lay exactly that copper and lock
it before freerouting sees the board:

  - under the chip, F.Cu: a 1V1 ring around the GND pad (prio 3) inside a
    3V3 band that reaches every IOVDD pad's inner end (prio 1);
  - four 1V1 vias in the ring, with 0.6 mm spokes on the far layer to the
    DVDD pins (6, 23, 39) and to the regulator output;
  - the regulator above pins 46-50 (L1, COUT, CIN, CFILT, RFILT) and its
    small high-current zones (LX, 1V1, 3V3 to CIN, PGND with its pair of
    GND vias to the plane at one point);
  - the USB 27R pair and the shared 53/54 100n at the top edge.

Notes on the chip and why: ~/.claude/skills/pcb-design/chips/rp2350.md.
Only power-block items are taken: the reference's IOVDD caps sit on the
chip's sides where this board has its own (each at its pin), so their
tracks are left out.

Where this board differs from the minimal board, the spoke topology is
kept and only the ends move (ADAPT below):
  - spokes run on In2, not the back: the back holds the debug connector
    J6 over the N spoke and passives under the chip; In2 is the signal
    layer between the In1 GND plane and the In3 VSYS pour;
  - W: the flash sits where the reference runs pin 6 out to its spoke
    via, so pin 6 joins the ring through the 3V3 band (the band's only
    cut, so it stays one connected ring), and C98 on the back hangs off
    the ring's W via;
  - S: the crystal is closer to the chip than on the minimal board, so the
    spoke via sits 1.4 mm below the pin row (XOUT passes under it) and the
    second VOUT 4.7u (C81) is on the back under that via;
  - E: the ADC_AVDD filter (R85/C85) is where the reference's spoke via and
    C11 are, so the via comes in to 1 mm past the pin row and C82 keeps
    its place beside it.
"""
from pathlib import Path

import pcbnew

ROOT = Path(__file__).resolve().parent.parent
REF_PCB = ROOT / "design" / "reference" / "RP2350_60QFN_minimal.kicad_pcb"

# reference ref -> this board's ref (pad 1 carries the same net in both,
# checked in block(), so the reference rotation carries over as is)
PARTS = {
    "L1": "L1",     # 3.3u, polarity-marked, LX pad right
    "C7": "C80",    # COUT 4.7u
    "C6": "C83",    # CIN 4.7u
    "C9": "C84",    # CFILT 4.7u (VREG_AVDD)
    "R5": "R84",    # RFILT 33R
    "R7": "R3",     # USB D+ 27R
    "R8": "R4",     # USB D- 27R
    "C12": "C93",   # 100n shared by IOVDD 53/54
}

NETS = {"+1V1": "1V1", "+3V3": "3V3_SYS", "GND": "GND", "/VREG_LX": "VREG_LX",
        "/VREG_AVDD": "VREG_AVDD", "Net-(U1-USB_DP)": "USB_DP_C",
        "Net-(U1-USB_DM)": "USB_DM_C", "/USB_D+": "USB_DP", "/USB_D-": "USB_DM"}

# the block, relative to U1's centre: a copied item must lie wholly inside
# these boxes (x0, y0, x1, y1). The chip body; the top edge (regulator, USB
# resistors, 53/54 cap); and each transplanted DVDD cap with its spoke end.
BOXES = [(-3.5, -3.5, 3.5, 3.5),
         (-2.6, -8.7, 4.8, -2.6)]
# reference copper this board cannot take: the 53/54 cap's GND via sits
# where the RM2's pad row is (the module is 1.2 mm closer to the chip than
# anything on the minimal board); that pad gets route.py's GND via-in-pad
# and the N spoke's two vias at COUT sit on the back debug connector J6's
# mounting pad here: they move 0.43 mm right (still in the 1V1 zone, on
# VREG_FB's end) and the spoke jogs to them (ADAPT)
SKIP = [(-2.1, -8.6), (0.5, -5.2), (0.5, -5.8)]
# the reference's far-side spokes go on this layer (see the docstring)
LAYER_MAP = {"F.Cu": "F.Cu", "B.Cu": "In2.Cu"}
RING_VIA = {"W": (-2.15, -0.8), "S": (0.2, 2.15), "E": (2.15, -0.4)}
# this board's spoke ends (relative to U1): tracks (layer, a, b, width), vias
ADAPT_TRACKS = [
    ("F.Cu", (-3.438, -0.8), (-2.15, -0.8), 0.2),     # W: pin 6 into the ring
    ("In2.Cu", (0.2, 2.15), (0.2, 4.8), 0.6),         # S spoke
    ("F.Cu", (0.0, 3.438), (0.0, 4.6), 0.2),          # pin 23 down to it
    ("F.Cu", (0.0, 4.6), (0.2, 4.8), 0.2),
    ("In2.Cu", (2.15, -0.4), (4.5, -0.4), 0.6),       # E spoke
    ("F.Cu", (3.438, -0.4), (4.5, -0.4), 0.2),        # pin 39 out to it
    # N spoke to its vias at COUT (moved off J6's pad, see SKIP)
    ("In2.Cu", (0.5, -2.162), (0.5, -4.77), 0.6),
    ("In2.Cu", (0.5, -4.77), (0.93, -5.2), 0.6),
    ("In2.Cu", (0.93, -5.2), (0.93, -5.8), 0.6),
    # the reference reaches COUT from those vias only through the 1V1 zone;
    # before zones fill, KiCad's net propagation re-nets a via cluster that
    # touches no pad of its net (it became GND). A link inside that zone to
    # COUT's 1V1 pad ties them to a pad.
    ("F.Cu", (0.93, -5.2), (1.28, -5.55), 0.2),
    ("F.Cu", (1.28, -5.55), (1.485, -5.55), 0.2),
]
ADAPT_VIAS = [(0.2, 4.8), (4.5, -0.4), (0.93, -5.2), (0.93, -5.8)]
# pin 11 (IOVDD) into the 3V3 band: the reference's stub is one track from
# the band out through the pad to its edge cap, which the box filter drops
# pin 1 the same way (the reference feeds it from its board-wide 3V3 pour;
# a via beside it here took the left pins' only way north, 2026-10-18)
ADAPT_3V3 = [("F.Cu", (-3.438, 1.2), (-2.6, 1.2), 0.2),
             ("F.Cu", (-3.438, -2.8), (-2.6, -2.8), 0.2)]
# PGND: pin 47 and the CIN/COUT grounds reach the main GND only through the
# PGND zone's two adjacent vias (s6.3.8.1, "only connect to main GND at one
# point"). They get no via-in-pad, and the board's F.Cu GND pour has a hole
# over the regulator (the pin row closes it at the bottom), so no pour copper
# reaches them. (A moat of no-pour strips was tried first: the pour filled
# the inside as an island, kept alive by CFILT's own GND via, and touched
# PGND.) The reference has its 3V3 pour there, another net.
PGND_PADS = [("C80", "2"), ("C83", "2"), ("U1", "47")]
POUR_HOLE = [(-0.12, -8.6), (5.0, -8.6), (5.0, -2.95), (3.85, -2.95), (3.85, -3.0), (-0.12, -3.0)]
# caps that hang off a spoke end: (ref, the via they join, layer of the link)
CAP_LINKS = [("C98", RING_VIA["W"], "B.Cu"), ("C81", (0.2, 4.8), "B.Cu"),
             ("C82", (4.5, -0.4), "F.Cu")]
# the reference's board-wide 3V3 pour, its VBUS and crystal-GND zones are
# not part of the block
ZONE_MAX_HALF = 9.0
SKIP_ZONE_NETS = {"VBUS"}


def T(v):
    return pcbnew.ToMM(v)


def _inside(p):
    return any(x0 - 1e-6 <= p[0] <= x1 + 1e-6 and y0 - 1e-6 <= p[1] <= y1 + 1e-6
               for x0, y0, x1, y1 in BOXES)


def block():
    """The reference power block relative to U1: parts, zones, vias, tracks,
    and the layer-2 cut-out under LX."""
    b = pcbnew.LoadBoard(str(REF_PCB))
    u = b.FindFootprintByReference("U1")
    assert abs(u.GetOrientationDegrees()) < 0.01
    cx, cy = T(u.GetPosition().x), T(u.GetPosition().y)

    def rel(p):
        return (round(T(p.x) - cx, 4), round(T(p.y) - cy, 4))

    parts = {}
    for rr, ours in PARTS.items():
        fp = b.FindFootprintByReference(rr)
        assert not fp.IsFlipped(), f"{rr} is on the back in the reference"
        parts[ours] = {"at": rel(fp.GetPosition()), "rot": fp.GetOrientationDegrees(),
                       "pad1": NETS.get(next(p for p in fp.Pads() if p.GetNumber() == "1").GetNetname())}

    zones = []
    for z in b.Zones():
        if z.GetIsRuleArea() or z.GetNetname() in SKIP_ZONE_NETS:
            continue
        o = z.Outline()
        pts = [rel(o.CVertex(i)) for i in range(o.TotalVertices())]
        if not pts or max(max(abs(x), abs(y)) for x, y in pts) > ZONE_MAX_HALF:
            continue
        if not all(_inside(p) for p in pts):
            continue                     # the crystal's GND island
        net = NETS[z.GetNetname()]
        zones.append({"net": net, "layer": b.GetLayerName(z.GetLayer()), "poly": pts,
                      "priority": z.GetAssignedPriority(),
                      "full": z.GetPadConnection() == pcbnew.ZONE_CONNECTION_FULL,
                      # the reference's own: pin 48's neighbours are 0.2 mm off,
                      # so a wider LX clearance cut the zone off pin 48
                      "clearance": T(z.GetLocalClearance() or 0),
                      "min_width": T(z.GetMinThickness()),
                      "thermal_gap": T(z.GetThermalReliefGap()),
                      "spoke": T(z.GetThermalReliefSpokeWidth())})

    def skipped(p):
        return any(abs(p[0] - q[0]) < 1e-3 and abs(p[1] - q[1]) < 1e-3 for q in SKIP)

    vias, tracks = [], []
    for t in b.GetTracks():
        n = NETS.get(t.GetNetname())
        if n is None:
            continue
        if t.Type() == pcbnew.PCB_VIA_T:
            p = rel(t.GetPosition())
            if _inside(p) and not skipped(p):
                vias.append({"net": n, "at": p, "size": T(t.GetWidth(pcbnew.F_Cu)),
                             "drill": T(t.GetDrillValue())})
            continue
        a, e = rel(t.GetStart()), rel(t.GetEnd())
        if _inside(a) and _inside(e) and not (skipped(a) or skipped(e)):
            tracks.append({"net": n, "layer": LAYER_MAP[b.GetLayerName(t.GetLayer())],
                           "a": a, "b": e, "width": T(t.GetWidth())})
    ring = next(v for v in vias if v["net"] == "1V1")
    for ly, a, e, w in ADAPT_TRACKS:
        tracks.append({"net": "1V1", "layer": ly, "a": a, "b": e, "width": w})
    for ly, a, e, w in ADAPT_3V3:
        tracks.append({"net": "3V3_SYS", "layer": ly, "a": a, "b": e, "width": w})
    for p in ADAPT_VIAS:
        vias.append({"net": "1V1", "at": p, "size": ring["size"], "drill": ring["drill"]})

    # layer-2 cut-out (s6.3.8.1, figure 27): under the VREG_LX zone and the
    # inductor's LX pad, grown by a margin -- their own outline, not the box
    # round both (that box was 1.7 x 5.4 mm, the LX zone's thin leg plus the
    # pad, and opened In1 over In2 wiring the switch node then coupled
    # into: phase-7 review, M6)
    l1 = b.FindFootprintByReference("L1")
    lx_pad = next(p for p in l1.Pads() if p.GetNetname() == "/VREG_LX")
    bb = lx_pad.GetBoundingBox()
    x0, y0 = rel(pcbnew.VECTOR2I(bb.GetLeft(), bb.GetTop()))
    x1, y1 = rel(pcbnew.VECTOR2I(bb.GetRight(), bb.GetBottom()))
    lx_zone = next(z["poly"] for z in zones if z["net"] == "VREG_LX")
    m = 0.25
    shape = pcbnew.SHAPE_POLY_SET()
    for poly in (lx_zone, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]):
        shape.NewOutline()
        for x, y in poly:
            shape.Append(pcbnew.FromMM(x), pcbnew.FromMM(y))
    shape.Simplify()
    shape.Inflate(pcbnew.FromMM(m), pcbnew.CORNER_STRATEGY_CHAMFER_ALL_CORNERS, pcbnew.FromMM(0.02))
    shape.Simplify()
    assert shape.OutlineCount() == 1, "LX cut-out: the zone and the pad do not meet"
    ch = shape.COutline(0)
    cutout = [(T(ch.CPoint(i).x), T(ch.CPoint(i).y)) for i in range(ch.PointCount())]
    # top layer: nothing but the inductor's own copper between its pads
    a_pad = next(p for p in l1.Pads() if p.GetNetname() == "+1V1").GetBoundingBox()
    gap = [(T(a_pad.GetRight()) - cx, T(a_pad.GetTop()) - cy), (x0, T(a_pad.GetTop()) - cy),
           (x0, T(a_pad.GetBottom()) - cy), (T(a_pad.GetRight()) - cx, T(a_pad.GetBottom()) - cy)]
    return {"parts": parts, "zones": zones, "vias": vias, "tracks": tracks,
            "cap_links": CAP_LINKS, "cutout_l2": cutout, "l1_gap": gap,
            "pgnd_pads": PGND_PADS, "pour_hole": POUR_HOLE}


if __name__ == "__main__":
    blk = block()
    for k in ("parts", "zones", "vias", "tracks"):
        print(f"{k}: {len(blk[k])}")
    for r, p in blk["parts"].items():
        print(f"  {r:4} at ({p['at'][0]:.2f},{p['at'][1]:.2f}) rot {p['rot']:.0f}, pad 1 {p['pad1']}")
    for z in blk["zones"]:
        print(f"  zone {z['net']:9} {z['layer']} prio {z['priority']} {'full' if z['full'] else 'thermal'} "
              f"clr {z['clearance']} {len(z['poly'])} pts")
    print("  layer-2 cut-out", blk["cutout_l2"])
