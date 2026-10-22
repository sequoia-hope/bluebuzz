#!/usr/bin/env python3
"""Layout audit: the rules DRC cannot express, checked on every build.

  [hard] no copper of any kind inside the RM2's RF keep-out: no track, no
         via, no filled zone, no pad (route.py's rule area; design.yaml
         radio.keepout_mm; RM2 datasheet fig. 6)
  [hard] no F.Cu track under the RM2 body inside its pad ring
  [hard] JLC: PTH hole -> other copper >= 0.28, NPTH -> copper >= 0.2,
         via hole -> via hole >= 0.2, via hole -> track >= 0.2 (B12)
  [hard] motor path (VSYS to J4, MOTOR?_SW) carries only Power-class
         width (>= 0.4 mm) -- 1 A through a 0.15 track is a fuse
  [hard] the RP2350's power block is Raspberry Pi's (rp2350_block.py,
         datasheet s6.3.8; ~/.claude/skills/pcb-design/chips/rp2350.md):
         every block zone present and filled, no other net's copper in the
         1V1 ring / 3V3 band, PGND joined to GND only by its via pair, the
         layer-2 cut-out under LX, L1 at the reference rotation
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
PCB = ROOT / "out" / "bluebuzz-rm2.kicad_pcb"
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
    # --- RF keep-out: nothing conductive --------------------------------
    u7 = fps["U7"]
    ux, uy = rel(u7.GetPosition())
    k = design["radio"]["keepout_mm"]
    hw, hh = design["board"]["width_mm"] / 2, design["board"]["height_mm"] / 2
    kx0, kx1 = max(-hw - 1, ux - 7.25 - k["side"]), min(hw + 1, ux + 7.25 + k["side"])
    ky0, ky1 = -hh - 1, uy - 8.25 + k["depth"]

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
        if f.GetReference() == "U7":
            continue
        for p in f.Pads():
            bb = p.GetBoundingBox()
            x, y = rel(bb.GetCenter())
            if inside(x, y, m=max(to_mm(bb.GetWidth()), to_mm(bb.GetHeight())) / 2):
                bad.append(f"pad {f.GetReference()}.{p.GetNumber()}")
    zones = [z for z in board.Zones() if not z.GetIsRuleArea()]
    hits = 0
    y = -hh + 0.3
    while y < ky1:
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
         f"RF keep-out (y < {ky1:.1f}, full width): {len(bad)} items {sorted(set(bad))[:6]}, {hits} filled samples")

    # --- RM2: no F.Cu tracks under the body inside the pad ring ----------
    under = sorted({t.GetNetname() for t in tracks if t.GetLayer() == pcbnew.F_Cu
                    and any(ux - 5.5 < p[0] < ux + 5.5 and ky1 < p[1] < uy + 6.5
                            for p in (rel(t.GetStart()), rel(t.GetEnd())))})
    hard(not under, f"F.Cu tracks under the RM2 body: {under or 'none'}")

    # --- motor path width -------------------------------------------------
    # (pad-to-pad bridges inside the charger's pin row are 0.25 and under
    #  1 mm long; they lie entirely inside the pads' own copper. A wire that
    #  lies inside a same-net pour -- route.py's pwr_* zones, which carry
    #  the current; their 0.25 mm wires only tie the vias to copper before
    #  the zone is filled -- is not on its own either; check_current.py
    #  rates the fill.)
    pours = [z for z in board.Zones() if not z.GetIsRuleArea() and z.GetZoneName().startswith("pwr_")]

    def in_pour(t):
        return any(z.GetNetCode() == t.GetNetCode() and z.IsOnLayer(t.GetLayer())
                   and z.Outline().Contains(t.GetStart()) and z.Outline().Contains(t.GetEnd())
                   for z in pours)
    thin = [(t.GetNetname(), round(to_mm(t.GetWidth()), 2)) for t in tracks
            if t.GetNetname() in ("MOTOR1_SW", "MOTOR2_SW", "VSYS") and to_mm(t.GetWidth()) < 0.39
            and to_mm(t.GetLength()) > 1.0 and not in_pour(t)]
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
                for _ in range(22):          # 1 mm / 2^22, under 1 nm (12 steps, 0.24 um, read 0.2800 as 0.2798)
                    mid = (lo + hi) / 2
                    if hole.Collide(seg, pcbnew.FromMM(mid)):
                        hi = mid
                    else:
                        lo = mid
                lo = hi                      # the clearance lies in [lo, hi); report hi, within 1 nm
                if p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                    worst_npth = min(worst_npth, lo)
                elif to_mm(p.GetDrillSizeX()) <= 0.3:
                    # a 0.2 mm plated hole in a footprint (the RP2350 EP's
                    # thermal vias) is a via to the fab: the via rule applies
                    worst_vt = min(worst_vt, lo)
                else:
                    worst_pth = min(worst_pth, lo)
    hard(worst_pth >= 0.28, f"JLC PTH hole -> other-net track: {worst_pth:.3f} mm (>= 0.28)")
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

    # --- the RP2350 power block ----------------------------------------
    from rp2350_block import block, PGND_PADS
    blk = block()
    zs = {z.GetZoneName(): z for z in board.Zones() if z.GetZoneName().startswith("rp2350_")}
    want = [f"rp2350_{z['net'].lower()}_{z['priority']}" for z in blk["zones"]]
    missing = [n for n in want if n not in zs]
    hard(not missing, f"RP2350 block zones present ({len(want) - len(missing)}/{len(want)})"
         + (f": missing {missing}" if missing else ""))
    empty = [n for n in want if n in zs and zs[n].GetFilledPolysList(zs[n].GetLayer()).OutlineCount() == 0]
    hard(not empty, f"RP2350 block zones filled" + (f": empty {empty}" if empty else ""))
    band = zs.get("rp2350_3v3_sys_1")
    intruders = []
    if band is not None:
        ol = band.Outline()
        for t in board.GetTracks():
            if t.GetNetname() in ("1V1", "3V3_SYS") or not t.IsOnLayer(pcbnew.F_Cu):
                continue
            pts = [t.GetPosition()] if isinstance(t, pcbnew.PCB_VIA) else \
                [t.GetStart(), t.GetEnd(), (t.GetStart() + t.GetEnd()) / 2]
            if any(ol.Collide(q) for q in pts):
                intruders.append(f"{t.GetNetname()}@({rel(pts[0])[0]:.2f},{rel(pts[0])[1]:.2f})")
    hard(band is not None and not intruders,
         f"nothing but 1V1/3V3 inside the RP2350 ring and band" + (f": {intruders[:5]}" if intruders else ""))
    pieces = {n: zs[n].GetFilledPolysList(zs[n].GetLayer()).OutlineCount()
              for n in ("rp2350_1v1_3", "rp2350_3v3_sys_1") if n in zs}
    hard(all(v == 1 for v in pieces.values()) and len(pieces) == 2,
         f"RP2350 1V1 ring and 3V3 band each one piece: {pieces}")
    pg = zs.get("rp2350_gnd_4")
    pg_vias, pour_touch = [], False
    if pg is not None:
        fill = pg.GetFilledPolysList(pcbnew.F_Cu)
        pg_vias = [v for v in vias if v.GetNetname() == "GND" and fill.Collide(v.GetPosition(), pcbnew.FromMM(0.01))]
        for z in board.Zones():
            if z.m_Uuid.AsString() == pg.m_Uuid.AsString() or z.GetNetname() != "GND" or z.GetIsRuleArea() or not z.IsOnLayer(pcbnew.F_Cu):
                continue
            other = z.GetFilledPolysList(pcbnew.F_Cu)
            for i in range(fill.OutlineCount()):
                o = fill.Outline(i)
                if any(other.Collide(o.CPoint(k), pcbnew.FromMM(0.01)) for k in range(o.PointCount())):
                    pour_touch = True
    in_pad = [f"{r}.{n}" for r, n in PGND_PADS if r in fps
              for v in vias if v.GetNetname() == "GND" and pad(r, n).HitTest(v.GetPosition())]
    hard(pg is not None and len(pg_vias) == 2 and not pour_touch and not in_pad,
         f"RP2350 PGND returns to GND at one point: {len(pg_vias)} vias in the PGND zone (2)"
         + (", the F.Cu GND pour touches it" if pour_touch else "")
         + (f", vias in {in_pad}" if in_pad else ""))
    cut = [z for z in board.Zones() if z.GetZoneName() == "rp2350_lx_cutout"]
    lx = next(p for p in fps["L1"].Pads() if p.GetNetname() == "VREG_LX")
    l2 = cut[0].GetLayer() if cut else None
    l2_fill = any(z.GetFilledPolysList(l2).Collide(lx.GetPosition()) for z in board.Zones()
                  if cut and not z.GetIsRuleArea() and z.IsOnLayer(l2))
    hard(bool(cut) and not l2_fill, "layer-2 copper cut away under the RP2350's LX node")
    l1_rot = blk["parts"]["L1"]["rot"]
    hard(abs((fps["L1"].GetOrientationDegrees() - l1_rot) % 360) < 0.01,
         f"L1 at the reference rotation ({l1_rot:.0f}): the polarity-marked inductor's field direction")

    # --- metrics ---------------------------------------------------------
    per = defaultdict(float)
    for t in tracks:
        per[(t.GetNetname(), pcbnew.LayerName(t.GetLayer()))] += to_mm(t.GetLength())
    usb = {n: {ly: round(v, 1) for (nn, ly), v in per.items() if nn == n} for n in ("USB_DP", "USB_DM")}
    print(f"  info  USB pair: {usb}")
    print(f"  info  GND vias: {sum(1 for v in vias if v.GetNetname() == 'GND')} of {len(vias)}; "
          f"wires per layer: { {ly: sum(1 for t in tracks if pcbnew.LayerName(t.GetLayer()) == ly) for ly in ['F.Cu'] + [f'In{i}.Cu' for i in range(1, design['board']['layers'] - 1)] + ['B.Cu']} }")
    pairs = {"C83": ("U1", 49), "C80": ("L1", 1), "C81": ("U1", 23), "C82": ("U1", 39),
             "C84": ("U1", 46), "C85": ("U1", 44), "C86": ("Y1", 1), "C87": ("Y1", 3),
             "C88": ("U6", 8), "C10": ("U2", 13), "C11": ("U2", 10), "C12": ("U2", 2),
             "C20": ("U3", 1), "C21": ("U3", 5), "C50": ("U5", 4),
             "C120": ("U20", 8), "C121": ("U21", 8), "C122": ("U22", 8),
             "C123": ("U23", 8), "C140": ("U40", 1), "C133": ("D2", 2), "C130": ("U30", 8), "C132": ("U30", 5), "C2": ("U10", 5), "C100": ("U7", 16), "C102": ("U7", 14),
             "C40": ("J4", 1), "C42": ("J4", 1)}
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
