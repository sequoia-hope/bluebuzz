#!/usr/bin/env python3
"""GND stitching after routing: return vias, the edge fence, interior stitching.

Runs after `finish`, when every signal via is where it will stay, and
places 0.4/0.2 GND vias in three passes. The targets are check_planes.py's,
which judges the result:

1. Return vias. Every signal via whose net goes from an In1-referenced
   layer (F.Cu) to an In4-referenced one (B.Cu) moves its return current
   between the two GND planes there, so it takes a GND via within
   RET_FAST mm (phase-7 review, M7). Spots on rings 0.55-1.0 mm round the
   via, nearest first.
2. The edge fence. Along the line EDGE_INSET mm inside the outline, every
   point gets a GND via within EDGE_GAP mm (3 mm pitch: stackup.md).
3. Interior. Points more than INNER_GAP mm from any GND via, farthest
   first, until none is left that can take one (M10).

First, though (plane_pads), a via in any GND or VSYS pad the routing
left cut off from its plane, where one fits.

A via goes only where it clears every copper item on every layer by the
board's rules (exact pad boxes, tracks and vias, not bounding circles),
stays out of the rule areas that forbid vias and out of the RP2350 block's
and route.py's power zones (pwr_*), and keeps 0.4 mm hole to hole from
other GND vias. Spots that do not fit are skipped, never forced; what is
left is check_planes.py's to report. Zones are refilled at the end.

    python3 scripts/stitch.py
"""
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pcbnew

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_planes import (EDGE_GAP, EDGE_INSET, FAST, INNER_GAP, RET_FAST,  # noqa: E402
                          RET_SLOW, layer_change_vias, net_classes)
from circuit import load_design  # noqa: E402
from route import CX, CY, Router, rel, seg_dist, to_mm  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PCB = ROOT / "out" / "bluebuzz-rm2.kicad_pcb"
VIA_R = 0.2                 # 0.4/0.2
CLR = 0.127 + 0.02          # copper clearance, and a hair
EDGE_MIN = 0.6              # via centre to the outline


class Space:
    """Where a through-via of plane net `net` (GND, or VSYS) may go: every
    pad of another net as its exact box, every other-net track and via,
    the forbidden areas, and this net's vias so far (`gnd`, for spacing)."""

    def __init__(self, board, net="GND"):
        self.board, self.net = board, net
        self.pads, self.segs, self.vias, self.gnd, self.holes = [], [], [], [], []
        for fp in board.GetFootprints():
            for pd in fp.Pads():
                if pd.HasHole():
                    # hole to copper 0.2 mm (an NPTH's pad box can be
                    # smaller than its hole)
                    d = pd.GetDrillSize()
                    self.holes.append((rel(pd.GetPosition()), max(to_mm(d.x), to_mm(d.y)) / 2))
                if pd.GetNetname() == net and pd.GetAttribute() != pcbnew.PAD_ATTRIB_PTH:
                    continue                 # a via may land in a pad of its own net
                bb = pd.GetBoundingBox()
                self.pads.append((to_mm(bb.GetLeft()) - CX, to_mm(bb.GetTop()) - CY,
                                  to_mm(bb.GetRight()) - CX, to_mm(bb.GetBottom()) - CY,
                                  to_mm(int(pd.GetLocalClearance() or 0))))
                if pd.GetNetname() == net:
                    self.gnd.append(rel(pd.GetPosition()))
        for t in board.GetTracks():
            if t.Type() == pcbnew.PCB_VIA_T:
                p = rel(t.GetPosition())
                if t.GetNetname() == net:
                    self.gnd.append(p)
                else:
                    self.vias.append((p, to_mm(t.GetWidth(pcbnew.F_Cu)) / 2))
            elif t.GetNetname() != net:
                self.segs.append((rel(t.GetStart()), rel(t.GetEnd()), to_mm(t.GetWidth()) / 2))
        self.areas = [z for z in board.Zones()
                      if (z.GetIsRuleArea() and z.GetDoNotAllowVias())
                      or (not z.GetIsRuleArea() and z.GetZoneName().startswith(("rp2350_", "pwr_"))
                          and z.GetNetname() != net)]
        self.outline = pcbnew.SHAPE_POLY_SET()
        board.GetBoardPolygonOutlines(self.outline)
        self.inner = pcbnew.SHAPE_POLY_SET(self.outline)
        self.inner.Inflate(-pcbnew.FromMM(EDGE_MIN), pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS,
                           pcbnew.FromMM(0.01))

    @staticmethod
    def vec(x, y):
        return pcbnew.VECTOR2I(pcbnew.FromMM(float(CX + x)), pcbnew.FromMM(float(CY + y)))

    def nearest_gnd(self, x, y):
        if not self.gnd:
            return 1e9
        g = np.array(self.gnd)
        return float(np.min(np.hypot(g[:, 0] - x, g[:, 1] - y)))

    def free(self, x, y):
        if not self.inner.Contains(self.vec(x, y)):
            return False
        for x0, y0, x1, y1, lc in self.pads:
            if math.hypot(max(x0 - x, 0, x - x1), max(y0 - y, 0, y - y1)) < VIA_R + max(CLR, lc):
                return False
        for (hx, hy), r in self.holes:
            # hole to the via's COPPER 0.2 mm (KiCad's hole_clearance)
            if math.hypot(hx - x, hy - y) < r + VIA_R + 0.2 + 0.02:
                return False
        for (vx, vy), r in self.vias:
            if math.hypot(vx - x, vy - y) < VIA_R + r + CLR:
                return False
        for a, b, hw in self.segs:
            if seg_dist(a, b, (x, y), (x, y)) < VIA_R + hw + CLR:
                return False
        if self.nearest_gnd(x, y) < 0.45:     # hole to hole 0.2 (0.2 drills)
            return False
        p = self.vec(x, y)
        for z in self.areas:
            if z.Outline().Collide(p, pcbnew.FromMM(VIA_R + CLR)):
                return False
        return True

    def place(self, rt, x, y):
        rt.via((x, y), self.net)
        self.gnd.append((x, y))


def ring(x, y, radii, step=15):
    for r in radii:
        for k in range(0, 360, step):
            a = math.radians(k)
            yield x + r * math.cos(a), y + r * math.sin(a)


def return_vias(board, rt, sp=None, quiet=False, ahead=False, fast_only=False):
    """A GND via within RET_FAST mm of every signal via that moves the
    return between In1 and In4 (fast nets first; a slow net may take one
    out to RET_SLOW if nothing nearer fits). Also run by route.py on the
    pre-routes, before freerouting, so their spots are kept free; with
    `ahead` a fast net's pin-escape via that so far has copper on one
    outer layer only counts too, since freerouting gives it the other side.
    (Slow nets' escapes are left to stitch.py: reserved ahead, their GND
    vias walled in the next pin's escape -- SWCLK, RUN, SDA, SCL and
    TAC_CS3 went open in every ordering; `fast_only` keeps route.py's
    pass to fast nets altogether -- a slow pre-route's return via took
    the spot under the next pin.)
    Returns (placed, without room)."""
    sp = sp or Space(board)
    classes = net_classes()
    outer = {"In1.Cu", "In4.Cu"}
    todo = [(classes.get(net) not in FAST, net, x - CX, y - CY)
            for net, x, y, refs in layer_change_vias(board, classes)
            if (refs >= outer or (ahead and refs and refs <= outer and classes.get(net) in FAST))
            and (not fast_only or classes.get(net) in FAST)]
    done = miss = 0
    for slow, net, x, y in sorted(todo):
        if sp.nearest_gnd(x, y) <= RET_FAST:
            continue
        radii = [0.55 + 0.05 * k for k in range(int((RET_FAST - 0.55) / 0.05) + 1)]
        if slow:
            radii += [RET_FAST + 0.05 * k for k in range(1, int((RET_SLOW - RET_FAST) / 0.05))]
        spot = next(((qx, qy) for qx, qy in ring(x, y, radii, 10) if sp.free(qx, qy)), None)
        if spot:
            sp.place(rt, *spot)
            done += 1
        else:
            miss += 1
            if not quiet:
                print(f"  no room for a return via by {net} at ({x + CX:.2f},{y + CY:.2f})")
    return done, miss


def plane_pads(board, rt):
    """A via inside every GND / VSYS pad that KiCad's DRC reports as
    unconnected. route.py gives every such pad a via before routing where
    one fits; a pad that then had no room, or whose neighbours moved, can
    find a spot once the routing is done (J5's VSYS test pad). Spots on a
    0.1 mm lattice in the pad, nearest its centre first. Returns (placed,
    without room)."""
    from close_gaps import drc_unconnected
    pcbnew.SaveBoard(str(PCB), board)
    open_pads = set()
    for u in drc_unconnected():
        for it in u["items"]:
            d = it["description"]
            if d.startswith("Pad ") and ("[GND]" in d or "[VSYS]" in d):
                open_pads.add(it["uuid"])
    placed = miss = 0
    for net in ("GND", "VSYS"):
        sp = None
        for fp in board.GetFootprints():
            for pd in fp.Pads():
                if pd.m_Uuid.AsString() not in open_pads or pd.GetNetname() != net:
                    continue
                sp = sp or Space(board, net)
                px, py = rel(pd.GetPosition())
                bb = pd.GetBoundingBox()
                hx, hy = to_mm(bb.GetWidth()) / 2 - 0.1, to_mm(bb.GetHeight()) / 2 - 0.1
                spots = sorted(((px + i * 0.1, py + k * 0.1)
                                for i in range(-int(hx / 0.1), int(hx / 0.1) + 1)
                                for k in range(-int(hy / 0.1), int(hy / 0.1) + 1)),
                               key=lambda q: math.hypot(q[0] - px, q[1] - py))
                spot = next((q for q in spots if sp.free(*q)), None)
                if spot:
                    sp.place(rt, *spot)
                    placed += 1
                    print(f"  {fp.GetReference()}.{pd.GetNumber()} ({net}): via at ({spot[0]:.2f},{spot[1]:.2f})")
                else:
                    miss += 1
                    print(f"  {fp.GetReference()}.{pd.GetNumber()} ({net}): open, no room for a via in it")
    return placed, miss


def drop_flat_signal_vias(board):
    """Last of all, the vias KiCad's DRC calls dangling (connected on one
    layer only) are dead copper: route.py keeps every locked via while
    routing, and an escape's via can end up with its net leaving on the
    same layer it arrived (or relayer can move a locked run off a
    pre-route's layer). The wires it sat between still meet end to end.
    DRC is the judge, not a geometric guess: matching wire ends to via
    centres exactly removed 9 vias that were in use."""
    import json
    rep = PCB.with_name("drc_dangling.json")
    pcbnew.SaveBoard(str(PCB), board)
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--severity-all",
                    "-o", str(rep), str(PCB)], capture_output=True, text=True)
    try:
        viol = json.loads(rep.read_text()).get("violations", [])
    finally:
        rep.unlink(missing_ok=True)
    spots = {(round(i["pos"]["x"], 4), round(i["pos"]["y"], 4))
             for v in viol if v["type"] == "via_dangling" for i in v["items"]}
    gone = 0
    for v in list(board.GetTracks()):
        if v.Type() == pcbnew.PCB_VIA_T and v.GetNetname() not in ("GND", "VSYS") and \
                (round(to_mm(v.GetPosition().x), 4), round(to_mm(v.GetPosition().y), 4)) in spots:
            board.Delete(v)
            gone += 1
    return gone


def main():
    design = load_design()
    board = pcbnew.LoadBoard(str(PCB))
    rt = Router(board, design)
    # 0. plane-net pads still cut off from their plane
    print("plane pads: %d vias placed, %d without room" % plane_pads(board, rt))
    sp = Space(board)
    n0 = len(sp.gnd)

    # 1. return vias
    done, miss = return_vias(board, rt, sp)
    print(f"return vias: {done} placed, {miss} without room")

    # 2. the edge fence
    fence = pcbnew.SHAPE_POLY_SET(sp.outline)
    fence.Inflate(-pcbnew.FromMM(EDGE_INSET), pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS, pcbnew.FromMM(0.01))
    ch = fence.COutline(0)
    pts = []
    for i in range(ch.PointCount()):
        a, b = rel(ch.CPoint(i)), rel(ch.CPoint((i + 1) % ch.PointCount()))
        n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / 0.1))
        pts += [(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) for k in range(n)]
    fence_n = 0
    for x, y in pts:
        if sp.nearest_gnd(x, y) <= EDGE_GAP - 0.2:
            continue
        # on the line, then a little inboard or along it
        spot = next(((qx, qy) for qx, qy in [(x, y)] + list(ring(x, y, (0.2, 0.4, 0.6), 30))
                     if sp.free(qx, qy)), None)
        if spot:
            sp.place(rt, *spot)
            fence_n += 1
    print(f"edge fence: {fence_n} vias")

    # 3. interior, farthest point first
    hw, hh = design["board"]["width_mm"] / 2, design["board"]["height_mm"] / 2
    grid = [(float(x), float(y)) for x in np.arange(-hw + 0.5, hw - 0.5, 0.25) for y in np.arange(-hh + 0.5, hh - 0.5, 0.25)
            if sp.inner.Contains(sp.vec(x, y))
            and not any(z.GetIsRuleArea() and z.Outline().Contains(sp.vec(x, y)) for z in sp.areas)]
    tried, inner_n = set(), 0
    while True:
        g = np.array(sp.gnd)
        far = [(float(np.min(np.hypot(g[:, 0] - x, g[:, 1] - y))), x, y) for x, y in grid
               if (round(x, 2), round(y, 2)) not in tried]
        far = [f for f in far if f[0] > INNER_GAP - 0.3]
        if not far:
            break
        d, x, y = max(far)
        tried.add((round(x, 2), round(y, 2)))
        spot = next(((qx, qy) for qx, qy in [(x, y)] + list(ring(x, y, (0.3, 0.6, 0.9, 1.2), 30))
                     if sp.free(qx, qy)), None)
        if spot:
            sp.place(rt, *spot)
            inner_n += 1
    print(f"interior: {inner_n} vias")

    print(f"flat signal vias removed: {drop_flat_signal_vias(board)}")
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(str(PCB), board)
    print(f"stitch: {len(sp.gnd) - n0} GND vias added ({done} return, {fence_n} fence, {inner_n} interior)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
