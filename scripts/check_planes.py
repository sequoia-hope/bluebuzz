#!/usr/bin/env python3
"""Plane-integrity check for the routed board (routing gate, phase 7).

Stackup (design/stackup.md, JLC06161H-3313): F.Cu | 0.10 | In1 GND | 0.55 |
In2 signal | 0.11 | In3 VSYS | 0.55 | In4 GND | 0.10 | B.Cu. Each signal
layer's reference is the plane nearest it: F.Cu -> In1, B.Cu -> In4, and
In2 -> In3 (0.11 mm away, against 0.55 mm to In1: In2's return runs in the
VSYS plane, the phase-7 review's M9).

1. The planes (In1 and In4 GND, In3 VSYS): one piece each, voids bigger than
   a via's anti-pad listed, and no wire of any other net on them.
2. Every DIFF_HS / SE_HS / CLOCK track (design/nets.csv) over its reference
   plane. Points every 0.1 mm along each track; a run of more than 0.5 mm
   off the plane's copper is a crossing (a via anti-pad is ~0.5 mm, and
   the track's own vias' anti-pads are skipped).
3. Every signal via where the return changes plane:
   - In1 <-> In4 (an F.Cu track on one side, a B.Cu track on the other):
     the return jumps GND to GND, so a GND via should be within 1.0 mm.
     FAIL beyond 1.0 mm on a fast net, beyond 1.5 mm on any other.
   - GND <-> VSYS (In2 on one side, F.Cu or B.Cu on the other): the return
     crosses between planes through the nearest VSYS decoupling cap; the
     distance to it is listed, and a fast net with none within 3 mm is a
     WARN.
4. GND stitching (stackup.md: an edge fence at <= 3 mm pitch, stitching
   through the interior): every point of the edge line 1.2 mm inside the
   outline within 1.6 mm of a GND via (3 mm pitch), and every interior point
   within 3.0 mm of one. Points where no via could go are skipped: within
   0.6 mm of the outline (copper to edge), within a via's reach of a rule
   area that forbids vias (the RF keep-out, the sensors' boxes) or of the
   RP2350 block's and route.py's power zones (pwr_*), or within 0.33 mm of a
   pad of another net (a module's pad row along the edge). GND vias here
   are GND vias and GND through-hole pads.

Exits 1 on any FAIL.

    python3 scripts/check_planes.py [board.kicad_pcb]
"""
import csv
import math
import sys
from pathlib import Path

import numpy as np
import pcbnew

ROOT = Path(__file__).resolve().parent.parent
PCB = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "out" / "bluebuzz-rm2.kicad_pcb"
NETS = ROOT / "design" / "nets.csv"
T = pcbnew.ToMM
FAST = ("DIFF_HS", "SE_HS", "CLOCK")
PLANES = {"In1.Cu": "GND", "In3.Cu": "VSYS", "In4.Cu": "GND"}
REF = {"F.Cu": "In1.Cu", "In2.Cu": "In3.Cu", "B.Cu": "In4.Cu"}
VOID_MM2 = 0.8          # a 0.4 via's anti-pad is ~0.3 mm2; two merged ~0.6
RET_FAST, RET_SLOW = 1.0, 1.5      # GND via within this of an In1 <-> In4 change
CAP_FAST = 3.0                     # VSYS cap within this of a GND <-> VSYS change
EDGE_INSET, EDGE_GAP = 1.2, 1.6    # edge fence line, max distance to a GND via on it
INNER_GAP = 3.0                    # max distance from a GND via inside the board


def vec(x, y):
    return pcbnew.VECTOR2I(pcbnew.FromMM(float(x)), pcbnew.FromMM(float(y)))


def plane_fill(board, layer_name, net, holes=False):
    """The fill of `net` on a layer. KiCad stores fills fractured (each hole
    joined to the outline by a slit); `holes` undoes that so the voids show
    up as holes."""
    ly = board.GetLayerID(layer_name)
    out = pcbnew.SHAPE_POLY_SET()
    for z in board.Zones():
        if z.GetNetname() == net and not z.GetIsRuleArea() and z.IsOnLayer(ly):
            out.Append(z.GetFilledPolysList(ly))
    if holes:
        out.Unfracture()
    return out


def poly_area_mm2(chain):
    return abs(chain.Area()) / 1e12


def net_classes():
    with open(NETS) as f:
        return {row["net"]: row["class"] for row in csv.DictReader(f)}


def layer_change_vias(board, classes=None):
    """Every signal via, with the reference planes of the layers its net
    uses there: [(net, x, y, {plane layers})], board mm. Plane nets and
    POWER nets are left out (they are not signals with a return), and so
    are the SWITCH_HI motor nodes: their current loop closes through VSYS
    at the same pad row (J4.1's via array, 2 mm from J4.2 / J4.3), not
    through an image current in the GND planes."""
    classes = classes if classes is not None else net_classes()
    tracks = [t for t in board.GetTracks() if t.Type() != pcbnew.PCB_VIA_T]
    pads = [(fp, pd) for fp in board.GetFootprints() for pd in fp.Pads()]
    out = []
    for v in board.GetTracks():
        if v.Type() != pcbnew.PCB_VIA_T:
            continue
        net = v.GetNetname()
        if net in PLANES.values() or classes.get(net, "").startswith("POWER") \
                or classes.get(net) == "SWITCH_HI":
            continue
        x, y = T(v.GetPosition().x), T(v.GetPosition().y)
        refs = set()
        for t in tracks:
            if t.GetNetname() == net and t.GetLayerName() in REF:
                if any(math.hypot(T(e.x) - x, T(e.y) - y) < 0.25 for e in (t.GetStart(), t.GetEnd())):
                    refs.add(REF[t.GetLayerName()])
        for fp, pd in pads:
            if pd.GetNetname() == net and pd.HitTest(vec(x, y)):
                refs |= {REF[l] for l in ("F.Cu", "B.Cu") if pd.IsOnLayer(board.GetLayerID(l))}
        out.append((net, x, y, refs))
    return out


def main():
    board = pcbnew.LoadBoard(str(PCB))
    fails = 0
    classes = net_classes()
    fast = {n: c for n, c in classes.items() if c in FAST}
    tracks = [t for t in board.GetTracks() if t.Type() != pcbnew.PCB_VIA_T]
    vias = [v for v in board.GetTracks() if v.Type() == pcbnew.PCB_VIA_T]

    print("planes:")
    for ly, net in PLANES.items():
        fill = plane_fill(board, ly, net, holes=True)
        n = fill.OutlineCount()
        voids = []
        for k in range(n):
            for h in range(fill.HoleCount(k)):
                hole = fill.CHole(k, h)
                a = poly_area_mm2(hole)
                if a > VOID_MM2:
                    bb = hole.BBox()
                    voids.append((a, T(bb.GetLeft()), T(bb.GetTop()), T(bb.GetRight()), T(bb.GetBottom())))
        intruders = [t for t in tracks if t.GetLayerName() == ly and t.GetNetname() != net]
        bad = n != 1 or intruders
        fails += bool(bad)
        print(f"  {'FAIL' if bad else 'ok  '}  {ly} {net}: {n} piece(s), "
              f"{sum(fill.HoleCount(k) for k in range(n))} holes, {len(voids)} void(s) > {VOID_MM2} mm2, "
              f"{len(intruders)} wire(s) of other nets")
        if n > 1:
            for k in range(n):
                print(f"        piece {k}: {poly_area_mm2(fill.COutline(k)):.1f} mm2")
        for a, x0, y0, x1, y1 in sorted(voids, reverse=True):
            print(f"        void {a:5.2f} mm2  ({x0:.2f},{y0:.2f})-({x1:.2f},{y1:.2f})  "
                  f"{x1 - x0:.2f} x {y1 - y0:.2f} mm")
        by_net = {}
        for t in intruders:
            by_net[t.GetNetname()] = by_net.get(t.GetNetname(), 0) + T(t.GetLength())
        for nn, L in sorted(by_net.items(), key=lambda kv: -kv[1]):
            print(f"        wire  {nn} {L:.1f} mm")

    fills = {ly: plane_fill(board, ref, PLANES[ref]) for ly, ref in REF.items()}
    gnd = [(T(v.GetPosition().x), T(v.GetPosition().y)) for v in vias if v.GetNetname() == "GND"]
    gnd += [(T(p.GetPosition().x), T(p.GetPosition().y)) for fp in board.GetFootprints() for p in fp.Pads()
            if p.GetNetname() == "GND" and p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH]
    gnd_np = np.array(gnd)
    print(f"\nfast nets over their reference plane ({len(fast)} nets: {', '.join(sorted(fast))}):")
    crossings = 0
    for net in sorted(fast):
        own_vias = [(T(v.GetPosition().x), T(v.GetPosition().y)) for v in vias if v.GetNetname() == net]
        for t in tracks:
            if t.GetNetname() != net:
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
                print(f"  FAIL  {net} on {ly}: {worst:.2f} mm off {REF[ly]} {PLANES[REF[ly]]} "
                      f"near ({at[0]:.2f},{at[1]:.2f})")
    if not crossings:
        print("  ok    no fast track leaves its reference plane for more than 0.5 mm")
    fails += crossings

    # VSYS decoupling: the VSYS pad of every cap whose other pad is GND
    vcaps = []
    for fp in board.GetFootprints():
        if not fp.GetReference().startswith("C"):
            continue
        nets = {p.GetNetname(): p for p in fp.Pads()}
        if "VSYS" in nets and "GND" in nets:
            p = nets["VSYS"].GetPosition()
            vcaps.append((fp.GetReference(), T(p.x), T(p.y)))

    print("\nsignal vias where the return changes plane:")
    gg = {"fail": 0, "warn": 0, "ok": 0}
    gv = {"warn": 0, "ok": 0}
    lines = []
    for net, x, y, refs in layer_change_vias(board, classes):
        nets_ = {PLANES[r] for r in refs}
        is_fast = net in fast
        if refs >= {"In1.Cu", "In4.Cu"}:
            d = float(np.min(np.hypot(gnd_np[:, 0] - x, gnd_np[:, 1] - y)))
            lim = RET_FAST if is_fast else RET_SLOW
            d = round(d, 2)                   # (a via placed at exactly 1.0 mm read 1.0000x)
            if d > lim:
                gg["fail"] += 1
                lines.append(f"  FAIL  {net} via at ({x:.2f},{y:.2f}) In1<->In4: nearest GND via {d:.2f} mm (> {lim})")
            elif d > RET_FAST:
                gg["warn"] += 1
                lines.append(f"  WARN  {net} via at ({x:.2f},{y:.2f}) In1<->In4: nearest GND via {d:.2f} mm")
            else:
                gg["ok"] += 1
        if "GND" in nets_ and "VSYS" in nets_:
            d, ref = min((math.hypot(cx - x, cy - y), r) for r, cx, cy in vcaps) if vcaps else (99, "-")
            if is_fast and d > CAP_FAST:
                gv["warn"] += 1
                lines.append(f"  WARN  {net} via at ({x:.2f},{y:.2f}) GND<->VSYS: nearest VSYS cap {ref} {d:.2f} mm")
            else:
                gv["ok"] += 1
    for ln in lines:
        print(ln)
    print(f"  In1<->In4: {gg['ok']} with a GND via within {RET_FAST} mm, {gg['warn']} within "
          f"{RET_SLOW} mm (slow nets), {gg['fail']} FAIL")
    print(f"  GND<->VSYS: {gv['ok'] + gv['warn']} ({gv['warn']} fast without a VSYS cap within {CAP_FAST} mm)")
    fails += gg["fail"]

    # ---- stitching density ----
    print("\nGND stitching:")
    no_via = [z for z in board.Zones() if z.GetIsRuleArea() and z.GetDoNotAllowVias()]
    # the RP2350 block's planes and route.py's power zones take no GND via
    # (it would cut them; PGND has one return point)
    power_zones = [z for z in board.Zones() if not z.GetIsRuleArea()
                   and z.GetZoneName().startswith(("rp2350_", "pwr_"))]
    outline0 = pcbnew.SHAPE_POLY_SET()
    board.GetBoardPolygonOutlines(outline0)
    via_area = pcbnew.SHAPE_POLY_SET(outline0)
    via_area.Inflate(-pcbnew.FromMM(0.6), pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS, pcbnew.FromMM(0.01))
    other_pads = []
    for fp in board.GetFootprints():
        for pd in fp.Pads():
            if pd.GetNetname() != "GND":
                bb = pd.GetBoundingBox()
                other_pads.append((T(bb.GetLeft()), T(bb.GetTop()), T(bb.GetRight()), T(bb.GetBottom())))

    def via_allowed(x, y):
        p = vec(x, y)
        if not via_area.Contains(p):
            return False
        if any(z.Outline().Collide(p, pcbnew.FromMM(0.35)) for z in no_via):
            return False
        if any(z.Outline().Collide(p, pcbnew.FromMM(0.35)) for z in power_zones):
            return False
        # a via centre within 0.33 mm (its radius + clearance) of another
        # net's pad is impossible
        return not any(math.hypot(max(x0 - x, 0, x - x1), max(y0 - y, 0, y - y1)) < 0.33
                       for x0, y0, x1, y1 in other_pads)
    edge = board.GetBoardEdgesBoundingBox()
    ex0, ey0, ex1, ey1 = T(edge.GetLeft()), T(edge.GetTop()), T(edge.GetRight()), T(edge.GetBottom())
    outline = pcbnew.SHAPE_POLY_SET()
    board.GetBoardPolygonOutlines(outline)
    inner = pcbnew.SHAPE_POLY_SET(outline)
    inner.Inflate(-pcbnew.FromMM(EDGE_INSET), pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS, pcbnew.FromMM(0.01))
    ch = inner.COutline(0)
    pts = []
    for i in range(ch.PointCount()):
        a, b = ch.CPoint(i), ch.CPoint((i + 1) % ch.PointCount())
        ax, ay, bx, by = T(a.x), T(a.y), T(b.x), T(b.y)
        n = max(1, int(math.hypot(bx - ax, by - ay) / 0.1))
        pts += [(ax + (bx - ax) * k / n, ay + (by - ay) * k / n) for k in range(n)]
    worst, gaps, run_at = 0.0, [], None
    for x, y in pts:
        if not via_allowed(x, y):
            continue
        d = float(np.min(np.hypot(gnd_np[:, 0] - x, gnd_np[:, 1] - y)))
        if d > EDGE_GAP:
            gaps.append((d, x, y))
        worst = max(worst, d)
    # merge the over-limit points into stretches
    stretches = []
    for d, x, y in gaps:
        if stretches and math.hypot(x - stretches[-1][3], y - stretches[-1][4]) < 0.3:
            s = stretches[-1]
            stretches[-1] = (max(s[0], d), s[1], s[2], x, y)
        else:
            stretches.append((d, x, y, x, y))
    tag = "FAIL" if stretches else "ok  "
    fails += bool(stretches)
    print(f"  {tag}  edge line {EDGE_INSET} mm in: worst {worst:.2f} mm to a GND via (limit {EDGE_GAP}), "
          f"{len(stretches)} stretch(es) over")
    for d, x0, y0, x1, y1 in stretches:
        print(f"        ({x0:.2f},{y0:.2f})-({x1:.2f},{y1:.2f}): up to {d:.2f} mm")
    xs = np.arange(ex0 + 0.5, ex1 - 0.5, 0.25)
    ys = np.arange(ey0 + 0.5, ey1 - 0.5, 0.25)
    n_in, far, worst, worst_at = 0, 0, 0.0, None
    over = []
    for x in xs:
        for y in ys:
            if not outline.Contains(vec(x, y)) or not via_allowed(x, y):
                continue
            n_in += 1
            d = float(np.min(np.hypot(gnd_np[:, 0] - x, gnd_np[:, 1] - y)))
            if d > 2.0:
                far += 1
            if d > INNER_GAP:
                over.append((d, x, y))
            if d > worst:
                worst, worst_at = d, (x, y)
    tag = "FAIL" if over else "ok  "
    fails += bool(over)
    print(f"  {tag}  interior: {len(gnd)} GND vias / PTH pads; {100 * far / max(n_in, 1):.0f} % of the "
          f"via-allowed area > 2 mm from one; worst {worst:.2f} mm at ({worst_at[0]:.2f},{worst_at[1]:.2f}); "
          f"{len(over)} points > {INNER_GAP} mm")
    for d, x, y in sorted(over, reverse=True)[:10]:
        print(f"        ({x:.2f},{y:.2f}) {d:.2f} mm")

    print(f"\nplane check: {fails} FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
