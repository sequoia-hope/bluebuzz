#!/usr/bin/env python3
"""Layout audit: the rules DRC cannot express, checked on every build.

  [hard] no copper of any kind inside the antenna keepout: no track, no
         via, no filled zone, no pad (route.py's rule area; design.yaml
         mcu.antenna_keepout_mm)
  [hard] no F.Cu track under the E73 body (module manual sec 5: solid
         ground under it; bike-tracker rule)
  [hard] no other-net copper within 0.45 mm of a J3 contact pad, on
         J3's layer (Tag-Connect TC2030-IDC-NL drawing, bike-tracker B2)
  [hard] JLC: PTH hole -> other copper >= 0.28, NPTH -> copper >= 0.2,
         via hole -> via hole >= 0.2, via hole -> track >= 0.2 (B12)
  [hard] motor path (VSYS to J4, MOTOR?_SW) carries only Power-class
         width (>= 0.4 mm) -- 1 A through a 0.15 track is a fuse
  metrics: decoupling distances, USB pair lengths, per-layer wire
           counts, GND via count
"""
import math
import sys
from collections import defaultdict
from pathlib import Path

import pcbnew

sys.path.insert(0, str(Path(__file__).resolve().parent))
from circuit import load_design  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PCB = ROOT / "out" / "bluebuzz.kicad_pcb"
CX, CY = 100.0, 100.0
to_mm = pcbnew.ToMM


def rel(p):
    return (to_mm(p.x) - CX, to_mm(p.y) - CY)


def pt_seg(p, a, b):
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def main():
    design = load_design()
    board = pcbnew.LoadBoard(str(PCB))
    fps = {f.GetReference(): f for f in board.GetFootprints()}
    tracks = [t for t in board.GetTracks() if not isinstance(t, pcbnew.PCB_VIA)]
    vias = [t for t in board.GetTracks() if isinstance(t, pcbnew.PCB_VIA)]
    fails = []

    def pad(ref, num):
        return next(p for p in fps[ref].Pads() if p.GetNumber() == str(num))

    def hard(ok, msg):
        print(("  ok    " if ok else "  FAIL  ") + msg)
        if not ok:
            fails.append(msg)

    print("audit:")
    # --- antenna keepout: nothing conductive --------------------------
    u1 = fps["U1"]
    ux, uy = rel(u1.GetPosition())
    ak = design["mcu"]["antenna_keepout_mm"]
    hh = design["board"]["height_mm"] / 2
    kx0, kx1 = ux - 6.5 - ak["margin"], ux + 6.5 + ak["margin"]
    ky0, ky1 = uy + 10.99 - ak["depth"], hh + 1.0

    def inside(x, y, m=0.0):
        return kx0 - m < x < kx1 + m and ky0 - m < y < ky1 + m
    bad = []
    for t in tracks:
        for pnt in (rel(t.GetStart()), rel(t.GetEnd())):
            if inside(*pnt, m=to_mm(t.GetWidth()) / 2):
                bad.append(f"track {t.GetNetname()}")
                break
    for v in vias:
        if inside(*rel(v.GetPosition()), m=to_mm(v.GetWidth(pcbnew.F_Cu)) / 2):
            bad.append(f"via {v.GetNetname()}")
    for f in board.GetFootprints():
        if f.GetReference() == "U1":
            continue
        for p in f.Pads():
            bb = p.GetBoundingBox()
            x, y = rel(bb.GetCenter())
            if inside(x, y, m=max(to_mm(bb.GetWidth()), to_mm(bb.GetHeight())) / 2):
                bad.append(f"pad {f.GetReference()}.{p.GetNumber()}")
    # filled copper: sample the keepout on a grid against every zone fill
    zones = [z for z in board.Zones() if not z.GetIsRuleArea()]
    hits = 0
    y = ky0 + 0.25
    while y < min(ky1, hh - 0.3):
        x = kx0 + 0.25
        while x < kx1:
            pt = pcbnew.VECTOR2I(pcbnew.FromMM(CX + x), pcbnew.FromMM(CY + y))
            for z in zones:
                for ly in z.GetLayerSet().Seq():
                    if z.IsFilled() and z.GetFilledPolysList(ly).Contains(pt):
                        hits += 1
                        break
            x += 0.5
        y += 0.5
    hard(not bad and hits == 0,
         f"antenna keepout x {kx0:.1f}..{kx1:.1f} y {ky0:.1f}..edge: "
         f"{len(bad)} items {sorted(set(bad))[:6]}, {hits} filled samples")

    # --- module: no F.Cu tracks under the body --------------------------
    # the same box as route.py's rule area: the bands holding the edge
    # pads' escape stubs and vias are left out on purpose
    under = sorted({t.GetNetname() for t in tracks if t.GetLayer() == pcbnew.F_Cu
                    and any(ux - 3.1 < p[0] < ux + 5.5 and uy - 3.6 < p[1] < uy + 10.0
                            for p in (rel(t.GetStart()), rel(t.GetEnd())))})
    hard(not under, f"F.Cu tracks under the E73 body: {under or 'none'}")

    # --- Tag-Connect: nothing else near the contact pads -----------------
    j3 = fps["J3"]
    j3_layer = j3.GetLayer()
    j3p = [(p, rel(p.GetPosition())) for p in j3.Pads() if p.GetNumber()]
    worst, what = 9.0, ""
    for t in board.GetTracks():
        for p, pp in j3p:
            if t.GetNetname() == p.GetNetname():
                continue
            if isinstance(t, pcbnew.PCB_VIA):
                qd = rel(t.GetPosition())
                d = math.hypot(qd[0] - pp[0], qd[1] - pp[1]) - 0.395 - to_mm(t.GetWidth(pcbnew.F_Cu)) / 2
            elif t.GetLayer() == j3_layer:
                d = pt_seg(pp, rel(t.GetStart()), rel(t.GetEnd())) - 0.395 - to_mm(t.GetWidth()) / 2
            else:
                continue
            if d < worst:
                worst, what = d, f"{t.GetNetname()} near pad {p.GetNumber()}"
    hard(worst >= 0.45, f"Tag-Connect ({pcbnew.LayerName(j3_layer)}): nearest other-net copper "
         f"to a contact pad {worst:.2f} mm ({what})")

    # --- motor path width -------------------------------------------------
    # (pad-to-pad bridges inside the charger's pin row are 0.25 and under
    #  1 mm long; they lie entirely inside the pads' own copper)
    thin = [(t.GetNetname(), round(to_mm(t.GetWidth()), 2)) for t in tracks
            if t.GetNetname() in ("MOTOR1_SW", "MOTOR2_SW", "VSYS") and to_mm(t.GetWidth()) < 0.39
            and to_mm(t.GetLength()) > 1.0]
    hard(not thin, f"motor path tracks under 0.4 mm: {sorted(set(thin)) or 'none'}")

    # --- JLCPCB hole rules (capability table, 2026-08) --------------------
    worst_pth, worst_npth, worst_vt = 9.0, 9.0, 9.0
    for f in board.GetFootprints():
        for p in f.Pads():
            if p.GetDrillSizeX() == 0:
                continue
            hole = p.GetEffectiveHoleShape()
            for t in tracks:
                if p.GetNetname() and t.GetNetname() == p.GetNetname():
                    continue
                seg = pcbnew.SHAPE_SEGMENT(t.GetStart(), t.GetEnd(), t.GetWidth())
                lo, hi = 0.0, 1.0
                for _ in range(12):
                    mid = (lo + hi) / 2
                    if hole.Collide(seg, pcbnew.FromMM(mid)):
                        hi = mid
                    else:
                        lo = mid
                if p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                    worst_npth = min(worst_npth, lo)
                else:
                    worst_pth = min(worst_pth, lo)
    hard(worst_pth >= 0.28, f"JLC PTH hole -> other-net track: {worst_pth:.2f} mm (>= 0.28)")
    hard(worst_npth >= 0.20, f"JLC NPTH hole -> track: {worst_npth:.2f} mm (>= 0.20)")
    holes = [(rel(v.GetPosition()), to_mm(v.GetDrillValue())) for v in vias]
    vv = min((math.hypot(a[0] - c[0], a[1] - c[1]) - da / 2 - dc / 2
              for i, (a, da) in enumerate(holes) for (c, dc) in holes[i + 1:]), default=9.0)
    hard(vv >= 0.20, f"JLC via hole -> via hole: {vv:.2f} mm (>= 0.20)")
    for v in vias:
        qd = rel(v.GetPosition())
        r = to_mm(v.GetDrillValue()) / 2
        for t in tracks:
            if t.GetNetname() == v.GetNetname():
                continue
            worst_vt = min(worst_vt, pt_seg(qd, rel(t.GetStart()), rel(t.GetEnd())) - r - to_mm(t.GetWidth()) / 2)
    hard(worst_vt >= 0.20, f"JLC via hole -> other-net track: {worst_vt:.2f} mm (>= 0.20)")

    # --- metrics ---------------------------------------------------------
    per = defaultdict(float)
    for t in tracks:
        per[(t.GetNetname(), pcbnew.LayerName(t.GetLayer()))] += to_mm(t.GetLength())
    usb = {n: {ly: round(v, 1) for (nn, ly), v in per.items() if nn == n} for n in ("USB_DP", "USB_DM")}
    print(f"  info  USB pair: {usb}")
    print(f"  info  GND vias: {sum(1 for v in vias if v.GetNetname() == 'GND')} of {len(vias)}; "
          f"wires per layer: { {ly: sum(1 for t in tracks if pcbnew.LayerName(t.GetLayer()) == ly) for ly in ('F.Cu', 'In1.Cu', 'In2.Cu', 'B.Cu')} }")
    pairs = {"C80": ("U1", 19), "C81": ("U1", 23), "C10": ("U2", 13), "C11": ("U2", 10),
             "C12": ("U2", 2), "C20": ("U3", 1), "C21": ("U3", 5), "C50": ("U5", 4),
             "C60": ("U4", 3), "C62": ("U4", 16), "C82": ("U1", 11), "C83": ("U1", 13),
             "C2": ("U10", 5), "C40": ("J4", 1), "C42": ("J4", 3), "C65": ("U1", 27)}
    far = []
    for c, (ic, pin) in pairs.items():
        a, qd = rel(pad(c, 1).GetPosition()), rel(pad(ic, pin).GetPosition())
        d = math.hypot(a[0] - qd[0], a[1] - qd[1])
        if d > 4.0:
            far.append(f"{c}->{ic}.{pin} {d:.1f}")
    print(f"  info  decoupling caps more than 4 mm from their pin: {far or 'none'}")
    if fails:
        print(f"audit: {len(fails)} hard rule(s) failed")
        return 1
    print("audit: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
