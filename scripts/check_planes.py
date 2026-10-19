#!/usr/bin/env python3
"""Plane-integrity check for the routed board (routing gate, phase 7).

1. The GND planes (In1, In4): islands, and voids bigger than a via's
   anti-pad -- a slot a return current would have to go round.
2. Every DIFF_HS / SE_HS / CLOCK track (design/nets.csv) over its
   reference plane: F.Cu and In2 over In1, In3 and B.Cu over In4. Points
   every 0.1 mm along each track; a run of more than 0.5 mm off the plane's
   copper is a crossing (a via anti-pad is ~0.5 mm, and the track's own
   vias' anti-pads are skipped).
3. Every via on those nets where the signal moves between the two
   references (an F.Cu / In2 track on one side, In3 / B.Cu on the other):
   the return has to jump from In1 to In4 there, so a GND via should be
   within 1.0 mm. (F.Cu <-> In2 keeps In1 under it: no jump.)

Exits 1 on a crossing, a plane island, or a layer change with no GND via
within 1.5 mm.

    python3 scripts/check_planes.py
"""
import csv
import math
import sys
from pathlib import Path

import pcbnew

ROOT = Path(__file__).resolve().parent.parent
PCB = ROOT / "out" / "bluebuzz-rm2.kicad_pcb"
NETS = ROOT / "design" / "nets.csv"
T = pcbnew.ToMM
FAST = ("DIFF_HS", "SE_HS", "CLOCK")
REF = {"F.Cu": "In1.Cu", "In2.Cu": "In1.Cu", "In3.Cu": "In4.Cu", "B.Cu": "In4.Cu"}
VOID_MM2 = 0.8          # a 0.4 via's anti-pad is ~0.3 mm2; two merged ~0.6


def vec(x, y):
    return pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))


def gnd_fill(board, layer_name, holes=False):
    """The GND fill on a layer. KiCad stores fills fractured (each hole
    joined to the outline by a slit); `holes` undoes that so the voids
    show up as holes."""
    ly = board.GetLayerID(layer_name)
    out = pcbnew.SHAPE_POLY_SET()
    for z in board.Zones():
        if z.GetNetname() == "GND" and not z.GetIsRuleArea() and z.IsOnLayer(ly):
            out.Append(z.GetFilledPolysList(ly))
    if holes:
        out.Unfracture()
    return out


def poly_area_mm2(chain):
    return abs(chain.Area()) / 1e12


def main():
    board = pcbnew.LoadBoard(str(PCB))
    fails = 0
    fast = {}
    with open(NETS) as f:
        for row in csv.DictReader(f):
            if row["class"] in FAST:
                fast[row["net"]] = row["class"]

    print("GND planes:")
    for ly in ("In1.Cu", "In4.Cu"):
        fill = gnd_fill(board, ly, holes=True)
        n = fill.OutlineCount()
        voids = []
        for k in range(n):
            for h in range(fill.HoleCount(k)):
                hole = fill.CHole(k, h)
                a = poly_area_mm2(hole)
                if a > VOID_MM2:
                    bb = hole.BBox()
                    voids.append((a, T(bb.GetLeft()), T(bb.GetTop()), T(bb.GetRight()), T(bb.GetBottom())))
        tag = "ok  " if n == 1 else "FAIL"
        fails += n != 1
        print(f"  {tag}  {ly}: {n} piece(s), {sum(fill.HoleCount(k) for k in range(n))} holes, "
              f"{len(voids)} void(s) > {VOID_MM2} mm2")
        for a, x0, y0, x1, y1 in sorted(voids, reverse=True):
            print(f"        void {a:5.2f} mm2  ({x0:.2f},{y0:.2f})-({x1:.2f},{y1:.2f})  "
                  f"{x1 - x0:.2f} x {y1 - y0:.2f} mm")

    fills = {ly: gnd_fill(board, ref) for ly, ref in REF.items()}
    gnd_vias = [(T(v.GetPosition().x), T(v.GetPosition().y)) for v in board.GetTracks()
                if v.Type() == pcbnew.PCB_VIA_T and v.GetNetname() == "GND"]
    print(f"\nfast nets over their reference plane ({len(fast)} nets: {', '.join(sorted(fast))}):")
    crossings = 0
    for net in sorted(fast):
        own_vias = [(T(v.GetPosition().x), T(v.GetPosition().y)) for v in board.GetTracks()
                    if v.Type() == pcbnew.PCB_VIA_T and v.GetNetname() == net]
        for t in board.GetTracks():
            if t.GetNetname() != net or t.Type() == pcbnew.PCB_VIA_T:
                continue
            ly = t.GetLayerName()
            if ly not in REF:
                continue
            a, b = t.GetStart(), t.GetEnd()
            ax, ay, bx, by = T(a.x), T(a.y), T(b.x), T(b.y)
            L = math.hypot(bx - ax, by - ay)
            steps = max(1, int(L / 0.1))
            run, worst, at = 0.0, 0.0, None
            for k in range(steps + 1):
                x, y = ax + (bx - ax) * k / steps, ay + (by - ay) * k / steps
                if any(math.hypot(x - vx, y - vy) < 0.45 for vx, vy in own_vias):
                    run = 0.0
                    continue
                if fills[ly].Contains(vec(x, y)):
                    run = 0.0
                else:
                    run += L / steps
                    if run > worst:
                        worst, at = run, (x, y)
            if worst > 0.5:
                crossings += 1
                print(f"  FAIL  {net} on {ly}: {worst:.2f} mm off {REF[ly]} near ({at[0]:.2f},{at[1]:.2f})")
    if not crossings:
        print("  ok    no fast track leaves its reference plane for more than 0.5 mm")
    fails += crossings

    print("\nfast-net vias that move the return between In1 and In4 (GND via for it):")
    worst_far = 0
    for net in sorted(fast):
        for v in board.GetTracks():
            if v.Type() != pcbnew.PCB_VIA_T or v.GetNetname() != net:
                continue
            x, y = T(v.GetPosition().x), T(v.GetPosition().y)
            refs = set()
            for t in board.GetTracks():
                if t.GetNetname() == net and t.Type() != pcbnew.PCB_VIA_T and t.GetLayerName() in REF:
                    if any(math.hypot(T(e.x) - x, T(e.y) - y) < 0.25 for e in (t.GetStart(), t.GetEnd())):
                        refs.add(REF[t.GetLayerName()])
            for fp in board.GetFootprints():
                for pd in fp.Pads():
                    if pd.GetNetname() == net and pd.HitTest(vec(x, y)):
                        refs |= {REF[l] for l in ("F.Cu", "B.Cu") if pd.IsOnLayer(board.GetLayerID(l))}
            if len(refs) < 2:
                continue                      # stays over one plane
            d = min(math.hypot(x - gx, y - gy) for gx, gy in gnd_vias)
            tag = "ok  " if d <= 1.0 else ("WARN" if d <= 1.5 else "FAIL")
            worst_far += tag == "FAIL"
            if tag != "ok  ":
                print(f"  {tag}  {net} via at ({x:.2f},{y:.2f}): nearest GND via {d:.2f} mm")
    if not worst_far:
        print("  ok    every one has a GND via within 1.5 mm")
    fails += worst_far
    print(f"\nplane check: {fails} FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
