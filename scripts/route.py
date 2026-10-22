#!/usr/bin/env python3
"""Routing pipeline.

1. Wipe existing tracks / vias / zones (idempotent).
2. Pre-route: the inner planes (stackup(): GND on In1 and In4, the VSYS
   plane on In3), the power copper (the charger's OUT and BAT zones and
   via arrays, the motor pads' via arrays, a via in every GND and VSYS
   pad), the thermal
   vias under the charger's PowerPad, the charger's EN2 via, the ESD
   array's middle-pin stubs and vias. Plus the rule areas: no F.Cu tracks
   under the RM2 body, NO COPPER AT ALL in the RM2's RF keep-out (the top
   5 mm strip of the board, permanent), and an edge ring exported for
   freerouting and deleted after.
3. Freerouting (Specctra DSN -> SES) for everything else, with the
   netclass widths from the project (Power 0.4, USB 0.25). The DSN is
   canonicalised first (reorder_placement) so the result is
   reproducible; retries permute it with a seed.
4. Post-route: drop unused vias, re-layer wires off the In1 plane
   (relayer -- aware of the back-side pads this board has), QFN pin
   bridges and ESD stubs, outer GND pours (F/B), GND stitching vias
   where they fit, zone fill, save; report unconnected.

Run with --no-freeroute to skip step 3 (fast placement iteration).
"""
import math
import shutil
import subprocess
import os
import sys
from pathlib import Path

import pcbnew

sys.path.insert(0, str(Path(__file__).resolve().parent))
from circuit import load_design  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PCB = ROOT / "out" / "bluebuzz-rm2.kicad_pcb"
# FR_JAR picks the freerouting build (a file in tools/). 2.2.4 loops forever
# inside a pass on this board; 2.3.0 added a cap on repeated trace
# normalisation (#741), which is that loop.
JAR = ROOT / "tools" / os.environ.get("FR_JAR", "freerouting-2.4.1.jar")
FR_JOB_TIMEOUT = os.environ.get("FR_JOB_TIMEOUT", "00:13:00")   # HH:MM:SS, < the 900 s kill

FR_RESUME_ROUNDS = int(os.environ.get("FR_RESUME_ROUNDS", "0"))   # resuming from a routed state never improved on 2.4.1


def freeroute_once(dsn, ses):
    """One freerouting run with the stall watchdog. freerouting 2.2.4 can
    loop forever inside a pass (thread dump: PolylineTrace.normalize ->
    split -> remove_if_cycle, 15+ min at 100 % CPU). It is deterministic
    for a given DSN, so a stalled run is replayed capped at its last
    completed pass, which reproduces that state and writes the SES.
    Returns (stalled, unrouted) with the SES at `ses`, or (stalled, None)
    and no SES."""
    ses.unlink(missing_ok=True)
    passes, ok, unrouted = run_freerouting(dsn, ses, 120)
    if ok:
        return False, unrouted
    if not passes:
        return True, None
    print(f"freerouting stalled after pass {passes}; replaying {passes} passes")
    ses.unlink(missing_ok=True)
    _, ok, unrouted = run_freerouting(dsn, ses, passes)
    return True, (unrouted if ses.exists() else None)


def route_with_resume(dsn, ses, attempt, design):
    """Route `dsn`; when freerouting stalls, resume from the replayed
    result: import its SES, export a DSN that carries those wires as
    ordinary (rip-up-able) routes, and run again. The router's state is
    different on each round, so it can get past the spot it looped on.
    Keeps the round with the fewest unrouted connections."""
    stalled, unrouted = freeroute_once(dsn, ses)
    best = ses.with_suffix(".best.ses")
    if ses.exists():
        shutil.copy(ses, best)
    rnd = 0
    # resume whenever anything is left: a fresh run from the routed state
    # rips up and retries in a new order (the finish stage cannot rip up)
    while unrouted and rnd < FR_RESUME_ROUNDS and ses.exists():
        rnd += 1
        b = pcbnew.LoadBoard(str(PCB))
        if not pcbnew.ImportSpecctraSES(b, str(ses)):
            break
        dsn2 = dsn.with_name(f"{dsn.stem}.r{rnd}.dsn")
        if not pcbnew.ExportSpecctraDSN(b, str(dsn2)):
            break
        reorder_placement(dsn2, attempt)
        tame_dsn(dsn2, design)
        print(f"resume round {rnd}: {unrouted} unrouted going in")
        ses2 = ses.with_name(f"{ses.stem}.r{rnd}.ses")
        stalled, u2 = freeroute_once(dsn2, ses2)
        if u2 is None:
            break
        shutil.copy(ses2, ses)
        if u2 < unrouted:
            shutil.copy(ses2, best)
            unrouted = u2
        else:
            break                            # no better: stop
    if best.exists():
        shutil.copy(best, ses)
    print(f"freerouting result: {unrouted} unrouted (resume rounds: {rnd})")
    return ses


FR_STALL_S = int(os.environ.get("FR_STALL_S", "180"))   # no pass finished for this long: stalled


def run_freerouting(dsn, ses, max_passes):
    """Run freerouting on `dsn`, watching its log. Returns (passes completed,
    finished cleanly, unrouted after the last completed pass). Kills it when no pass completes for FR_STALL_S
    seconds or the whole run exceeds 900 s."""
    import re
    import threading
    import time
    # without a cap the JVM may take a quarter of RAM; 16 orderings side by
    # side ran the machine out of memory (2026-10-18)
    cmd = ["java", f"-Xmx{os.environ.get('FR_HEAP', '3g')}", "-jar", str(JAR),
           "-de", str(dsn), "-do", str(ses),
           "-mp", str(max_passes), "--gui.enabled=false",
           f"--router.job_timeout={FR_JOB_TIMEOUT}",
           # its optimiser took a 4-unrouted result back to 7 (2.4.1); the
           # finish stage and close_gaps tidy up instead
           "--router.optimizer.enabled=false",
           # 2.4.1's fanout stage lays its escape wires 0.1124 mm wide, under
           # the 0.127 mm minimum (13-22 track_width errors a run; A/B on one
           # DSN: 10 such wires with fanout, 0 without). automatic_neckdown
           # is not it (no change with it off).
           "--router.fanout.enabled=false",
           # 2.4.1 laid a via 0.1 mm from a rounded corner (route.py's own
           # edge keepout band is straight-sided); 0.3 mm as in routing rules
           "--router.copper_to_edge_clearance_um=300"]
    print(f"running freerouting (max {max_passes} passes)…")
    # no DISPLAY: with --gui.enabled=false it still asks Swing for a look
    # and feel, and a stale X cookie in the environment kills it there
    # ("Can't connect to X11 window server", 2026-10-19)
    env = {k: v for k, v in os.environ.items() if k != "DISPLAY"}
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1, env=env)
    state = {"passes": 0, "last": time.time(), "tail": [], "unrouted": None}

    def reader():
        for ln in proc.stdout:
            if re.search(r"pass #\d+", ln):     # any pass (fanout, routing, optimiser) is progress
                state["last"] = time.time()
            # 2.2.4: "Auto-router pass #N ... (K unrouted)";
            # 2.4.1: "Auto-routing pass #N ... (K unrouted and V violations)"
            m = re.search(r"Auto-rout\w+ pass #(\d+) .*?\((\d+) unrouted", ln)
            if m:
                state["passes"] = int(m.group(1))
                state["unrouted"] = int(m.group(2))
                state["last"] = time.time()
                print(f"  pass {m.group(1)}: {m.group(2)} unrouted", flush=True)
            if ln.strip():
                state["tail"] = (state["tail"] + [ln.strip()[:120]])[-4:]
    th = threading.Thread(target=reader, daemon=True)
    th.start()
    t0 = time.time()
    while proc.poll() is None:
        time.sleep(2)
        now = time.time()
        if now - state["last"] > FR_STALL_S or now - t0 > 900:
            why = "stalled" if now - state["last"] > FR_STALL_S else "timed out"
            print(f"freerouting {why} in pass {state['passes'] + 1}; killing it")
            proc.kill()
            proc.wait()
            th.join(5)
            return state["passes"], False, state["unrouted"]
    th.join(5)
    print("freerouting said: " + " | ".join(state["tail"][-2:]))
    return state["passes"], proc.returncode == 0 and ses.exists(), state["unrouted"]

CX, CY = 100.0, 100.0


def mm(v):
    return pcbnew.FromMM(v)


def to_mm(v):
    return pcbnew.ToMM(v)


def vec(x, y):
    return pcbnew.VECTOR2I(mm(CX + x), mm(CY + y))


def rel(p):
    return (to_mm(p.x) - CX, to_mm(p.y) - CY)


def smd_layer(pd):
    """The copper layer an SMD pad is actually on. pd.GetLayer() answers
    F.Cu even for pads of flipped footprints in this pcbnew; IsOnLayer()
    tells the truth."""
    return pcbnew.B_Cu if pd.IsOnLayer(pcbnew.B_Cu) else pcbnew.F_Cu



def inside_board_poly(board, inset=0.6):
    """Return a SHAPE_POLY_SET of the board outline shrunk by `inset` mm."""
    polys = pcbnew.SHAPE_POLY_SET()
    board.GetBoardPolygonOutlines(polys)
    polys.Inflate(-mm(inset), pcbnew.CORNER_STRATEGY_ALLOW_ACUTE_CORNERS, mm(0.05))
    return polys


def free_for_gnd(board, via_at, legs, clr=0.15, via_r=0.2, leg_w=0.25):
    """True when a GND through-via at `via_at` and B.Cu wires `legs` (board-
    centre mm; `via_at` None to check wires only) clear every non-GND pad (any layer for the via, B.Cu for the
    legs), every non-GND track and via, every rule area, and the edge.
    Conservative: pads and tracks are taken as their bounding boxes."""
    def seg_box_dist(a, b, box):
        x0, y0, x1, y1 = box
        best = 1e9
        for k in range(21):
            px = a[0] + (b[0] - a[0]) * k / 20
            py = a[1] + (b[1] - a[1]) * k / 20
            dx = max(x0 - px, 0, px - x1)
            dy = max(y0 - py, 0, py - y1)
            best = min(best, math.hypot(dx, dy))
        return best

    def box(item):
        bb = item.GetBoundingBox()
        return (to_mm(bb.GetLeft()) - CX, to_mm(bb.GetTop()) - CY,
                to_mm(bb.GetRight()) - CX, to_mm(bb.GetBottom()) - CY)

    if via_at is None:                          # wires only: check the legs
        via_at, via_r = legs[0][0], -1.0
    in_poly = inside_board_poly(board, 0.6)
    if not in_poly.Contains(vec(*via_at)):
        return False
    for z in board.Zones():
        if z.GetIsRuleArea() and z.GetDoNotAllowVias():
            if seg_box_dist(via_at, via_at, box(z)) < via_r + 0.05:
                return False
        if z.GetIsRuleArea() and z.GetDoNotAllowTracks() and z.IsOnLayer(pcbnew.B_Cu):
            for a, b in legs:
                if seg_box_dist(a, b, box(z)) < leg_w / 2 + 0.05:
                    return False
    for fp in board.GetFootprints():
        for pd in fp.Pads():
            if pd.GetNetname() == "GND":
                continue
            bx = box(pd)
            if seg_box_dist(via_at, via_at, bx) < via_r + clr:
                return False
            if pd.IsOnLayer(pcbnew.B_Cu):
                for a, b in legs:
                    if seg_box_dist(a, b, bx) < leg_w / 2 + clr:
                        return False
    for tr in board.GetTracks():
        if tr.GetNetname() == "GND":
            continue
        bx = box(tr)
        if seg_box_dist(via_at, via_at, bx) < via_r + clr:
            return False
        if isinstance(tr, pcbnew.PCB_VIA) or tr.GetLayer() == pcbnew.B_Cu:
            for a, b in legs:
                if seg_box_dist(a, b, bx) < leg_w / 2 + clr:
                    return False
    return True



# DRC errors no later stage repairs: close/finish only add copper, so a
# short or a clearance breach in freerouting's output survives to the gate
COPPER_DEFECTS = {"shorting_items", "tracks_crossing", "clearance", "hole_clearance",
                  "copper_edge_clearance", "track_width"}


def attempt_score(pcb_path):
    """(copper defects, open signal pairs) by kicad-cli DRC. Opens on nets
    other than GND only: the GND ones (pads to pours, pour islands) are
    what the finish stage closes (it knows the pours; the Python
    connectivity API cannot list ratsnest edges). Defects rank first: an
    attempt with a short once beat clean ones on opens alone (attempt 4
    shorted IMU_INT2 to 3V3_SYS, 2026-10-18)."""
    import json
    rep = Path(pcb_path).with_suffix(".drc.json")
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--severity-all",
                    "-o", str(rep), str(pcb_path)], capture_output=True, text=True)
    try:
        d = json.loads(rep.read_text())
    except (OSError, ValueError):
        return 999, 999
    bad = sum(1 for v in d.get("violations", [])
              if v.get("severity") == "error" and v.get("type") in COPPER_DEFECTS)
    sig = sum(1 for u in d.get("unconnected_items", [])
              if not all("[GND]" in i.get("description", "") for i in u.get("items", [])))
    return bad, sig

class Router:
    def __init__(self, board, design):
        self.board = board
        self.design = design
        self.j = design["jlcpcb"]
        self.nets = {}

    def net(self, name):
        if name not in self.nets:
            ni = self.board.FindNet(name)
            assert ni is not None, f"net {name} not found"
            self.nets[name] = ni
        return self.nets[name]

    def via(self, pos, netname, locked=True, drill=None, size=None):
        v = pcbnew.PCB_VIA(self.board)
        v.SetPosition(pos if isinstance(pos, pcbnew.VECTOR2I) else vec(*pos))
        v.SetDrill(mm(drill or self.j["via_drill_mm"]))
        v.SetWidth(mm(size or self.j["via_diameter_mm"]))
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetNet(self.net(netname))
        v.SetLocked(locked)
        v.SetFrontTentingMode(pcbnew.TENTING_MODE_TENTED)
        v.SetBackTentingMode(pcbnew.TENTING_MODE_TENTED)
        self.board.Add(v)
        return v

    def track(self, a, b, netname, layer=pcbnew.F_Cu, width=None, locked=True):
        t = pcbnew.PCB_TRACK(self.board)
        t.SetStart(vec(*a))
        t.SetEnd(vec(*b))
        t.SetLayer(layer)
        t.SetWidth(mm(width or self.j["default_track_mm"]))
        t.SetNet(self.net(netname))
        t.SetLocked(locked)
        self.board.Add(t)
        return t

    def path(self, pts, netname, layer=pcbnew.F_Cu, width=None, locked=True, chamfer=0.4):
        """A polyline of tracks with every right-angle corner cut to two
        45-degree bends: each 90-degree vertex becomes a mitre of up to
        `chamfer` mm per side (less where a leg is short). Corners that are
        already at 45 degrees, and legs that are not axis-aligned, are
        drawn as given."""
        out = [pts[0]]
        for k in range(1, len(pts) - 1):
            a, b, c = pts[k - 1], pts[k], pts[k + 1]
            d1 = (b[0] - a[0], b[1] - a[1])
            d2 = (c[0] - b[0], c[1] - b[1])
            l1, l2 = math.hypot(*d1), math.hypot(*d2)
            axis1 = abs(d1[0]) < 1e-6 or abs(d1[1]) < 1e-6
            axis2 = abs(d2[0]) < 1e-6 or abs(d2[1]) < 1e-6
            right = axis1 and axis2 and abs(d1[0] * d2[0] + d1[1] * d2[1]) < 1e-6
            if not right or l1 < 1e-6 or l2 < 1e-6:
                out.append(b)
                continue
            m = min(chamfer, l1 / 2, l2 / 2)
            out.append((b[0] - d1[0] / l1 * m, b[1] - d1[1] / l1 * m))
            out.append((b[0] + d2[0] / l2 * m, b[1] + d2[1] / l2 * m))
        out.append(pts[-1])
        segs = []
        for a, b in zip(out, out[1:]):
            if math.hypot(b[0] - a[0], b[1] - a[1]) > 1e-6:
                segs.append(self.track(a, b, netname, layer=layer, width=width, locked=locked))
        return segs

    def zone(self, layer, netname, poly, priority=0, name="", full=False):
        z = pcbnew.ZONE(self.board)
        z.SetLayer(layer)
        z.SetNet(self.net(netname))
        z.SetAssignedPriority(priority)
        z.SetMinThickness(mm(0.15))
        z.SetLocalClearance(mm(self.j["min_clearance_mm"]))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL if full
                           else pcbnew.ZONE_CONNECTION_THERMAL)
        z.SetThermalReliefGap(mm(0.25))
        z.SetThermalReliefSpokeWidth(mm(0.3))
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
        if name:
            z.SetZoneName(name)
        ol = z.Outline()
        ol.NewOutline()
        for x, y in poly:
            ol.Append(mm(CX + x), mm(CY + y))
        self.board.Add(z)
        return z


from rp2350_block import PGND_PADS  # noqa: E402


def lay_rp2350_block(board, rt, design, fps):
    """Lay the RP2350's power block from Raspberry Pi's layout (see
    rp2350_block.py), locked, relative to U1: zones with the reference's
    own settings, vias, tracks, the caps hung off the spoke ends, and the
    two copper cut-outs the datasheet asks for. Any copied copper that
    would touch a pad of another net on this board is refused loudly."""
    from rp2350_block import block
    blk = block()
    u1 = fps["U1"]
    assert abs(u1.GetOrientationDegrees()) < 0.01, "the RP2350 block is laid for U1 at rot 0"
    ux, uy = rel(u1.GetPosition())

    def at(p):
        return (ux + p[0], uy + p[1])

    def foreign_pad(pt, layer, net):
        v = vec(*pt)
        for fp in board.GetFootprints():
            for pd in fp.Pads():
                if pd.GetNetname() != net and pd.IsOnLayer(layer) and pd.HitTest(v):
                    return f"{fp.GetReference()}.{pd.GetNumber()} {pd.GetNetname()}"
        return None

    for z in blk["zones"]:
        zz = rt.zone(board.GetLayerID(z["layer"]), z["net"], [at(p) for p in z["poly"]],
                     priority=z["priority"], name=f"rp2350_{z['net'].lower()}_{z['priority']}",
                     full=z["full"])
        zz.SetLocalClearance(mm(max(z["clearance"], rt.j["min_clearance_mm"])))
        zz.SetMinThickness(mm(z["min_width"]))
        zz.SetThermalReliefGap(mm(z["thermal_gap"]))
        zz.SetThermalReliefSpokeWidth(mm(z["spoke"]))
        zz.SetLocked(True)
    for v in blk["vias"]:
        pt = at(v["at"])
        bad = foreign_pad(pt, pcbnew.F_Cu, v["net"]) or foreign_pad(pt, pcbnew.B_Cu, v["net"])
        assert not bad, f"RP2350 block: {v['net']} via at {pt} lands on {bad}"
        rt.via(pt, v["net"], size=v["size"], drill=v["drill"])
    for t in blk["tracks"]:
        ly = board.GetLayerID(t["layer"])
        a, b = at(t["a"]), at(t["b"])
        bad = foreign_pad(a, ly, t["net"]) or foreign_pad(b, ly, t["net"])
        assert not bad, f"RP2350 block: {t['net']} track {a}->{b} touches {bad}"
        rt.track(a, b, t["net"], layer=ly, width=t["width"])
    # caps on this board's own spots, hung off a spoke end (45-degree dog-leg)
    for ref, v, ly in blk["cap_links"]:
        pad = pad_net(fps[ref], "1V1")
        pp, vv = rel(pad.GetPosition()), at(v)
        dx, dy = pp[0] - vv[0], pp[1] - vv[1]
        if abs(dx) > 1e-3 and abs(dy) > 1e-3 and abs(abs(dx) - abs(dy)) > 1e-3:
            k = min(abs(dx), abs(dy))
            mid = (pp[0] - math.copysign(k, dx), vv[1]) if abs(dx) > abs(dy) else (vv[0], pp[1] - math.copysign(k, dy))
            pts = [vv, mid, pp]
        else:
            pts = [vv, pp]
        for a, b in zip(pts, pts[1:]):
            rt.track(a, b, "1V1", layer=board.GetLayerID(ly), width=0.3)

    def keepout(name, layers, poly, tracks=False):
        z = pcbnew.ZONE(board)
        z.SetIsRuleArea(True)
        z.SetDoNotAllowCopperPour(True)
        z.SetDoNotAllowTracks(tracks)
        z.SetDoNotAllowVias(False)
        z.SetDoNotAllowPads(False)
        z.SetDoNotAllowFootprints(False)
        ls = pcbnew.LSET()
        for ly in layers:
            ls.addLayer(ly)
        z.SetLayerSet(ls)
        z.SetZoneName(name)
        ol = z.Outline()
        ol.NewOutline()
        for p in poly:
            x, y = at(p)
            ol.Append(mm(CX + x), mm(CY + y))
        board.Add(z)
    # s6.3.8.1: no plane copper beneath the LX node on layer 2 (fig. 27),
    # and nothing on the top layer under the inductor but its own pads
    keepout("rp2350_lx_cutout", [stackup(design)["gnd"][0]], blk["cutout_l2"])
    # ...and nothing on the inner signal layer under that opening: In2 sees
    # the switch node through it (VBAT_SENSE, a 500 k source, ran 0.65 mm
    # under LX there: phase-7 review, M6)
    if stackup(design)["signal"]:
        keepout("rp2350_lx_in2_clear", stackup(design)["signal"][:1], blk["cutout_l2"], tracks=True)
    keepout("rp2350_l1_gap", [pcbnew.F_Cu], blk["l1_gap"])
    return blk


def board_poly(design, inset, n_arc=8):
    """The board outline shrunk by `inset` mm."""
    b = design["board"]
    if b.get("outline") == "squish":
        from squish_outline import generate_outline_points_pcb
        pts, _ = generate_outline_points_pcb(
            r_tip=float(b.get("r_tip_mm", 10.0)),
            top_y_pcb=float(b.get("top_y_mm", -22.0)),
            n_arc=36,
            n_spline=40,
            offset_mm=float(b.get("offset_mm", 0.0)) + inset,
        )
        return pts[:-1]
    hw, hh = b["width_mm"] / 2 - inset, b["height_mm"] / 2 - inset
    r = max(b["corner_radius_mm"] - inset, 0.01)
    pts = []
    for cx, cy, a0 in ((hw - r, -hh + r, -90), (hw - r, hh - r, 0),
                       (-hw + r, hh - r, 90), (-hw + r, -hh + r, 180)):
        for i in range(n_arc + 1):
            a = math.radians(a0 + 90 * i / n_arc)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def seg_dist(a, b, c, d):
    """Min distance between segments ab and cd (mm tuples)."""
    def pt_seg(p, a, b):
        ax, ay = a
        bx, by = b
        px, py = p
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
        return math.hypot(px - (ax + t * dx), py - (ay + t * dy))

    def cross(o, p, q):
        return (p[0] - o[0]) * (q[1] - o[1]) - (p[1] - o[1]) * (q[0] - o[0])
    if (cross(a, b, c) * cross(a, b, d) < 0) and (cross(c, d, a) * cross(c, d, b) < 0):
        return 0.0
    return min(pt_seg(a, c, d), pt_seg(b, c, d), pt_seg(c, a, b), pt_seg(d, a, b))


class WireGroups:
    """Freerouting's wires, clustered into runs (same net, same layer,
    touching end-to-end). A run keeps its endpoints on any layer -- they
    are through vias or nothing -- so it can be moved between layers as a
    unit whenever the target layer has room for all of it."""

    def __init__(self, board, design):
        self.board = board
        self.clr = design["jlcpcb"]["min_clearance_mm"]
        segs = [t for t in board.GetTracks() if not isinstance(t, pcbnew.PCB_VIA)]
        parent = list(range(len(segs)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        ends = {}
        for i, t in enumerate(segs):
            for p in (t.GetStart(), t.GetEnd()):
                key = (p.x, p.y, t.GetNetCode(), t.GetLayer())
                if key in ends:
                    parent[find(i)] = find(ends[key])
                else:
                    ends[key] = i
        by_root = {}
        for i, t in enumerate(segs):
            by_root.setdefault(find(i), []).append(t)
        self.groups = []      # [tracks, geo, layer, netcode]
        for trks in by_root.values():
            geo = [(rel(t.GetStart()), rel(t.GetEnd()), to_mm(t.GetWidth()) / 2)
                   for t in trks]
            self.groups.append([trks, geo, trks[0].GetLayer(), trks[0].GetNetCode()])
        # Static copper per layer that is NOT the same on every layer: the
        # SMD pads of the parts on the back. (The bike-tracker had none;
        # this board has its passives and the Tag-Connect there.) Each is
        # a zero-length segment with the pad's bounding radius, so the
        # same seg_dist test keeps a re-layered run off it.
        self.static = {}
        for fp in board.GetFootprints():
            for pad in fp.Pads():
                if pad.GetAttribute() != pcbnew.PAD_ATTRIB_SMD:
                    continue
                bb = pad.GetBoundingBox()
                x, y = rel(bb.GetCenter())
                # half the DIAGONAL: max(w, h)/2 misses a rectangle's corners;
                # the fragment stitcher put a GND via 0.04 mm from J4's
                # MOTOR1_SW pad corner that way (2026-10-18)
                r = math.hypot(to_mm(bb.GetWidth()), to_mm(bb.GetHeight())) / 2
                r += to_mm(int(pad.GetLocalClearance() or 0))
                # PAD::GetLayer() answers F.Cu for a pad on a flipped
                # footprint; only the layer set knows (servodrive README)
                for ly in (pcbnew.F_Cu, pcbnew.B_Cu):
                    if pad.IsOnLayer(ly):
                        self.static.setdefault(ly, []).append(
                            ((x, y), (x, y), r, pad.GetNetCode()))

    def blocked(self, g, layer):
        """Would g collide with a back-side (or front) pad of another net
        if it were put on `layer`?"""
        for (c, d, hw2, nc) in self.static.get(layer, []):
            if nc == g[3]:
                continue
            if any(seg_dist(a, b, c, d) < hw + hw2 + self.clr
                   for (a, b, hw) in g[1]):
                return True
        return False

    def conflicts(self, g, layer):
        """Groups on `layer` (other nets) that g would collide with."""
        out = []
        for h in self.groups:
            if h is g or h[2] != layer or h[3] == g[3]:
                continue
            if any(seg_dist(a, b, c, d) < hw + hw2 + self.clr
                   for (a, b, hw) in g[1] for (c, d, hw2) in h[1]):
                out.append(h)
        return out

    def move(self, g, layer):
        for t in g[0]:
            t.SetLayer(layer)
        g[2] = layer

    def on(self, layer):
        return [g for g in self.groups if g[2] == layer]


def stackup(design):
    """Which inner layer is which. 4 layers: In1 = GND plane, In2 = the
    VSYS pour (wires allowed at a cost). 6 layers: In1 and In4 = GND
    planes, In2 = the one inner signal layer, In3 = the VSYS PLANE.

    On six layers In3 carries no wire at all: with signals allowed there
    the VSYS pour came out in two pieces joined by 0.24-0.32 mm necks,
    under 312 mm of wiring (phase-7 review, B1), and In2 -- 0.11 mm above
    it -- had no solid reference. VSYS is then a plane net like GND
    (`plane_nets`): it leaves freerouting's netlist, every VSYS pad takes
    vias into In3, and no stage routes it."""
    n = design["board"]["layers"]
    if n == 6:
        return {"gnd": [pcbnew.In1_Cu, pcbnew.In4_Cu], "signal": [pcbnew.In2_Cu],
                "pour": pcbnew.In3_Cu, "planes": [pcbnew.In1_Cu, pcbnew.In3_Cu, pcbnew.In4_Cu],
                "plane_nets": ["GND", "VSYS"]}
    return {"gnd": [pcbnew.In1_Cu], "signal": [], "pour": pcbnew.In2_Cu,
            "planes": [pcbnew.In1_Cu], "plane_nets": ["GND"]}


def relayer(board, design, node_budget=300000):
    """Empty the In1 GND plane of wires and thin out In2 (the 3V3 pour).

    Freerouting v2 ignores per-layer costs from the DSN, and its defaults
    make the inner layers the cheapest, so it slots both planes freely.
    A wire keepout on In1 kills its plane fanout (3 -> 45 unrouted), so
    the wires are re-layered afterwards instead. Every run that is not
    on F.Cu ends only in through vias, and In1 / In2 / B.Cu carry the
    same static copper (through-hole pads and nothing else), so runs may
    be assigned to any of the three freely as long as no two runs of
    different nets get too close on one layer. That is a 3-colouring of
    the runs' conflict graph, solved per connected component by
    branch-and-bound minimising (wire on In1, then wire on In2).
    Returns (wires left on In1, wires on In2)."""
    wg = WireGroups(board, design)
    st = stackup(design)
    B = pcbnew.B_Cu
    # preference order: the back, then free inner signal layers, then the
    # pour layer, and a GND plane only when nothing else fits (it is
    # removed afterwards and left to the finish stage)
    # (on six layers the pour is the VSYS plane: no wire may go there)
    pour = [] if st["pour"] in st["planes"] else [st["pour"]]
    LAYERS = tuple([B] + st["signal"] + pour + st["planes"])
    COST = {B: 0.0, st["pour"]: 1.0}
    for ly in st["signal"]:
        COST[ly] = 0.5
    for ly in st["planes"]:
        COST[ly] = 1000.0
    mov = [g for g in wg.groups if g[2] in LAYERS]
    n = len(mov)
    adj = [set() for _ in mov]
    for a in range(n):
        for b in range(a + 1, n):
            ga, gb = mov[a], mov[b]
            if ga[3] == gb[3]:
                continue
            if any(seg_dist(p, q, r, t) < hw + hw2 + wg.clr
                   for (p, q, hw) in ga[1] for (r, t, hw2) in gb[1]):
                adj[a].add(b)
                adj[b].add(a)
    length = [sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b, _ in g[1])
              for g in mov]
    blocked = [{ly for ly in LAYERS if wg.blocked(g, ly)} for g in mov]
    # A run that lands on an SMD pad of its own net is pinned to that pad's
    # layer: moved, it ends in mid-air over the pad. J6's GND hop on the
    # back was moved to In2 this way and left a dangling locked wire across
    # the In2 corridor by the USB resistors (2026-10-18).
    smd = {}
    for fp in board.GetFootprints():
        for pd in fp.Pads():
            if pd.GetAttribute() == pcbnew.PAD_ATTRIB_SMD:
                smd.setdefault(pd.GetNetCode(), []).append(pd)
    for k, g in enumerate(mov):
        if any(pd.IsOnLayer(g[2])
               and (pd.HitTest(t.GetStart()) or pd.HitTest(t.GetEnd()))
               for t in g[0] for pd in smd.get(g[3], [])):
            blocked[k] = set(LAYERS) - {g[2]}

    seen = [False] * n
    for s0 in range(n):
        if seen[s0]:
            continue
        comp, queue = [s0], [s0]
        seen[s0] = True
        while queue:
            u = queue.pop()
            for v in adj[u]:
                if not seen[v]:
                    seen[v] = True
                    comp.append(v)
                    queue.append(v)
        # most-constrained first
        comp.sort(key=lambda k: -len(adj[k]))
        best = {"cost": sum(COST[mov[k][2]] * length[k] for k in comp),
                "assign": {k: mov[k][2] for k in comp}, "nodes": 0}
        assign = {}

        def dfs(pos, cost):
            best["nodes"] += 1
            if cost >= best["cost"] or best["nodes"] > node_budget:
                return
            if pos == len(comp):
                best["cost"] = cost
                best["assign"] = dict(assign)
                return
            k = comp[pos]
            for ly in LAYERS:
                if any(assign.get(v) == ly for v in adj[k]):
                    continue
                if ly in blocked[k]:
                    continue
                assign[k] = ly
                dfs(pos + 1, cost + COST[ly] * length[k])
                del assign[k]

        dfs(0, 0.0)
        for k, ly in best["assign"].items():
            if mov[k][2] != ly:
                wg.move(mov[k], ly)
    return (sum(len(g[0]) for ly in st["planes"] for g in wg.on(ly)),
            sum(len(g[0]) for ly in st["signal"] + pour for g in wg.on(ly)))


def drop_flat_vias(board):
    """Delete vias that change no layer, and peel back what fed them.

    Two kinds: pre-placed escape vias freerouting did not use, and the
    ones it drops on a corner mid-run and then leaves on a single layer.
    Either way the wires still meet end-to-end without them, and what is
    left is what KiCad reports as a dangling via.

    A via on a poured net is NOT one of these even with no wire on it at
    all: that is how a track reaches the plane it belongs to (3V3_SYS off
    the In2 pour, every GND stitch). Those are left alone -- deleting one
    would silently cut the connection. Locked vias are pre-routes and are
    never touched. Returns (vias dropped, wires peeled).
    """
    poured = {z.GetNetname() for z in board.Zones()
              if z.IsOnCopperLayer() and not z.GetIsRuleArea()}
    dropped = 0
    for v in list(board.GetTracks()):
        if not isinstance(v, pcbnew.PCB_VIA) or v.IsLocked():
            continue
        if v.GetNetname() in poured:
            continue
        hits = [t for t in board.GetTracks()
                if not isinstance(t, pcbnew.PCB_VIA)
                and (t.GetStart() == v.GetPosition() or t.GetEnd() == v.GetPosition())]
        if len({t.GetLayer() for t in hits}) < 2:
            board.Delete(v)
            dropped += 1
    return dropped, (prune_dangling(board) if dropped else 0)


def prune_dangling(board):
    """Delete unlocked wires with a free end, repeatedly. An end is held
    by a via at it, a pad under it (same layer or through-hole), or
    another wire of the same net on the same layer that ends there or
    passes through it."""
    removed = 0
    while True:
        tracks = [t for t in board.GetTracks() if not isinstance(t, pcbnew.PCB_VIA)]
        vias = [v for v in board.GetTracks() if isinstance(v, pcbnew.PCB_VIA)]
        pads = [p for fp in board.GetFootprints() for p in fp.Pads()]

        def held(t, e):
            ex, ey = to_mm(e.x), to_mm(e.y)
            for v in vias:
                if v.GetNetCode() == t.GetNetCode() and \
                        math.hypot(to_mm(v.GetPosition().x) - ex,
                                   to_mm(v.GetPosition().y) - ey) < 0.01:
                    return True
            for p in pads:
                if p.GetNetCode() != t.GetNetCode():
                    continue
                if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD and not p.IsOnLayer(t.GetLayer()):
                    continue          # (IsOnLayer: GetLayer() lies for flipped pads)
                if p.GetBoundingBox().Contains(e):
                    return True
            for u in tracks:
                if u is t or u.GetLayer() != t.GetLayer() or u.GetNetCode() != t.GetNetCode():
                    continue
                if u.GetLength() < 1000:
                    continue          # a zero-length stub holds nothing
                a, b = u.GetStart(), u.GetEnd()
                if seg_dist((to_mm(a.x), to_mm(a.y)), (to_mm(b.x), to_mm(b.y)),
                            (ex, ey), (ex, ey)) < 0.01:
                    return True
            return False

        victims = [t for t in tracks if not t.IsLocked()
                   and not (held(t, t.GetStart()) and held(t, t.GetEnd()))]
        if not victims:
            return removed
        for t in victims:
            board.Delete(t)
        removed += len(victims)


def reorder_placement(dsn_path, seed):
    """Make the DSN deterministic, then permute its component order by
    `seed`. KiCad's exporter lists the (placement ...) components, the
    (library ...) images and the pins inside each (net ...) in hash order,
    which differs from process to process, and freerouting's outcome
    follows that order: the same board routed to 0 unconnected in one
    process and stranded the same 3V3_SYS hop, three tries running, in
    the next (2026-08-19). So: sort every level-2 block of those three
    sections and the entries inside them (seed 0 = canonical), and for the
    retries shuffle the placement with a seeded RNG, so each attempt is a
    genuinely different, reproducible ordering instead of three copies of
    one. Freerouting itself is deterministic for a given DSN."""
    import random
    lines = Path(dsn_path).read_text().splitlines()

    def section(name):
        try:
            i0 = lines.index(f"  ({name}")
        except ValueError:
            return None
        i1 = next(k for k in range(i0 + 1, len(lines)) if lines[k] == "  )")
        return i0, i1

    def blocks(i0, i1):
        """level-2 children: multi-line '    (' .. '    )' or one-liners"""
        out, k = [], i0 + 1
        while k < i1:
            ln = lines[k]
            if ln.startswith("    (") and not ln.rstrip().endswith(")"):
                j = next(m for m in range(k + 1, i1 + 1) if lines[m] == "    )")
                out.append(lines[k:j + 1])
                k = j + 1
            else:
                out.append([ln])
                k += 1
        return out

    # The exporter also emits one (image ...) per footprint VARIANT it
    # meets (a part placed at another rotation gets "name::1", "::2" ...)
    # and numbers the variants in the order it meets them -- hash order
    # again. Rename them canonically: variants of one base name sorted by
    # their body, then re-numbered, in both the library and the placement.
    sec = section("library")
    if sec is not None:
        i0, i1 = sec
        groups = {}
        for b in blocks(i0, i1):
            hd = b[0]
            if not hd.startswith("    (image "):
                continue
            nm = hd[len("    (image "):].strip()
            # names with special characters come quoted ("Lib:SOT-23::1"):
            # split the bare name and quote the results again, or the base
            # keeps its opening quote and loses the closing one -- which
            # unbalanced every quote after it and left freerouting with no
            # nets (2026-10-18)
            q = '"' if nm.startswith('"') else ""
            base = q + nm.strip('"').split("::")[0] + q
            groups.setdefault(base, []).append((nm, "\n".join(b[1:])))
        rename = {}
        for base, var in groups.items():
            if len(var) < 2:
                continue
            var.sort(key=lambda v: v[1])
            for n, (nm, _) in enumerate(var):
                q = '"' if base.startswith('"') else ""
                rename[nm] = base if n == 0 else f"{q}{base.strip(chr(34))}::{n}{q}"
        if rename:
            for k, ln in enumerate(lines):
                for pre in ("    (image ", "    (component "):
                    if ln.startswith(pre) and ln[len(pre):].strip() in rename:
                        lines[k] = pre + rename[ln[len(pre):].strip()]

    rng = random.Random(seed)
    for name in ("library", "network", "placement"):
        sec = section(name)
        if sec is None:
            continue
        i0, i1 = sec
        bl = blocks(i0, i1)
        for b in bl:
            if name == "placement" and len(b) > 2:
                body = b[1:-1]
                body.sort()
                if seed:
                    rng.shuffle(body)
                b[1:-1] = body
            if name == "network" and len(b) > 2 and b[1].lstrip().startswith("(pins"):
                toks = " ".join(x.strip() for x in b[1:-1]).strip()
                assert toks.startswith("(pins") and toks.endswith(")"), toks
                pins = sorted(toks[len("(pins"):-1].split())
                b[1:-1] = ["      (pins " + " ".join(pins) + ")"]
        bl.sort(key=lambda b: b[0])
        if name == "placement" and seed:
            rng.shuffle(bl)
        lines[i0 + 1:i1] = [ln for b in bl for ln in b]
    for ln in lines:
        if ln.startswith(("    (image ", "    (component ")):
            assert ln.count('"') % 2 == 0, f"unbalanced quote in DSN: {ln}"
    Path(dsn_path).write_text("\n".join(lines) + "\n")


def tame_dsn(dsn_path, design):
    """Edit the exported DSN before freerouting sees it (servodrive's lessons):

    * the GND plane layers become `(type power)`: Specctra's way of saying
      "not for routing". Freerouting ignores per-layer costs and otherwise
      slots the planes freely; on this board it put 50-70 wires on them
      per attempt, all of which had to be torn out again.
    * GND leaves the network entirely: its net block goes, its name goes
      from the class list, and its pads stay as obstacles with no net.
      Freerouting does not treat a Specctra plane as connecting anything,
      so it was drawing ~180 GND wires per attempt that the pours make
      redundant and route.py deleted -- effort and space wasted, and the
      ripped-up fragments it left behind shorted other nets.
    * the fixed GND copper (the pre-routed vias and stubs) comes out of
      the wiring section -- a wire on a net that no longer exists is fatal
      -- and each piece leaves a keepout the size of its copper plus the
      clearance, on every layer, so nothing is routed into it.
    * on six layers all of that holds for VSYS and its In3 plane as well
      (stackup()'s plane_nets): its pads carry pre-placed vias into In3.
    * the classes in gen_project.LAYER_RULES get their `use_layer` limit:
      the motor switch nodes on F.Cu only, VBUS on the outer layers.
    """
    import re
    from gen_project import LAYER_RULES
    s = dsn_path.read_text()
    st = stackup(design)
    for ly in st["planes"]:
        name = pcbnew.LayerName(ly)
        s = s.replace(f"(layer {name}\n      (type signal)", f"(layer {name}\n      (type power)")
    n_net = 0
    for pn in st["plane_nets"]:
        # the net block, and the net's planes (a plane on a net that no
        # longer exists is as fatal as a class naming one; the layers are
        # `power` now)
        s, k = re.subn(rf"\n    \(net {pn}\n      \(pins[^)]*\)\n    \)", "", s)
        n_net += k
        s = re.sub(rf"\n    \(plane {pn} \(polygon [^\n]*(?:\n(?!    \().*)*", "", s)
        # out of its class list (the token, with its surrounding space)
        s = re.sub(rf"(\(class [A-Za-z_]+[^\n]*?) {pn}(?=[ \n])", r"\1", s)
    # a class left with no nets is fatal too (Power held only GND and VSYS)
    s = re.sub(r"\n    \(class [A-Za-z_]+\n      \(circuit\n(?:        [^\n]*\n)*      \)\n"
               r"      \(rule\n(?:        [^\n]*\n)*      \)\n    \)", "", s)
    # per-class layer limits: (circuit (use_layer ...)) -- freerouting
    # reads them (NetClass.useLayer)
    for cls, lys in LAYER_RULES.items():
        s, k = re.subn(rf"(\n    \(class {cls} [^\n]*\n      \(circuit\n)",
                       rf"\1        (use_layer {' '.join(lys)})\n", s)
        assert k == 1, f"tame_dsn: class {cls} not in the DSN"
    # fixed GND copper -> keepouts
    layers = ["F.Cu"] + [f"In{i}.Cu" for i in range(1, design["board"]["layers"] - 1)] + ["B.Cu"]
    # the DSN is `(unit um)`: coordinates and sizes in micrometres. (This
    # once scaled by 10000, i.e. 0.1 um units, which turned each 0.4 mm via
    # into a 6.5 mm keepout on all six layers; five of them walled off the
    # board and freerouting's second pass never finished.)
    m_unit = re.search(r"\(unit (\w+)\)", s)
    assert m_unit and m_unit.group(1) == "um", "tame_dsn expects a DSN in um"
    clr = int(design["jlcpcb"]["min_clearance_mm"] * 1000)
    keep = []
    def via_sub(m):
        x, y = m.group(2), m.group(3)
        d = int(re.search(r"_(\d+):", m.group(1)).group(1))   # via diameter, um
        for ly in layers:
            keep.append(f'    (keepout "" (circle {ly} {d + 2 * clr} {x} {y}))')
        return ""
    pn_re = "|".join(st["plane_nets"])
    s, n_via = re.subn(r'\n    \(via "(Via\[[^"]*\]_[0-9]+:[0-9]+_um)"  (-?[\d.]+) (-?[\d.]+) \(net (?:' + pn_re + r')\)\(type fix\)\)', via_sub, s)
    def wire_sub(m):
        # each fixed GND wire leaves a keepout the shape of its copper on its
        # own layer (freerouting adds its clearance around a keepout). They
        # were simply dropped while they were pad-to-via stubs; the tactile
        # sensors' GND diagonals run under the package between signal pads,
        # and freerouting -- not seeing them -- routed straight across
        # (8 tracks_crossing errors, 2026-10-18). (An older attempt at path
        # keepouts here "left freerouting routing 160 wires instead of
        # 600"; that was with the 10x unit error above.)
        ly, w = m.group(1), int(m.group(2))
        xy = [int(float(v)) for v in m.group(3).split()]
        pts = list(zip(xy[0::2], xy[1::2]))
        h = w / 2 + 10
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            L = math.hypot(x2 - x1, y2 - y1)
            if L < 1:
                continue
            ux, uy = (x2 - x1) / L, (y2 - y1) / L
            nx, ny = -uy * h, ux * h
            ex, ey = ux * h, uy * h            # square ends, half a width past each end
            c = [(x1 - ex + nx, y1 - ey + ny), (x2 + ex + nx, y2 + ey + ny),
                 (x2 + ex - nx, y2 + ey - ny), (x1 - ex - nx, y1 - ey - ny)]
            c.append(c[0])
            keep.append(f'    (keepout "" (polygon {ly} 0  ' +
                        "  ".join(f"{x:.0f} {y:.0f}" for x, y in c) + "))")
        return ""
    s, n_wire = re.subn(r"\n    \(wire \(path ([A-Za-z0-9.]+) (\d+) ([-\d. ]+?)\)\(net (?:" + pn_re + r")\)\(type fix\)\)", wire_sub, s)
    for pn in st["plane_nets"]:
        assert f"(net {pn})" not in s, f"tame_dsn: {pn} copper left in the DSN"
    if keep:
        i = s.index("    (wire_keepout") if "    (wire_keepout" in s else s.index("  )\n  (placement")
        s = s[:i] + "\n".join(keep) + "\n" + s[i:]
    dsn_path.write_text(s)
    print(f"tame_dsn: {len(st['planes'])} plane layers set to power, {'/'.join(st['plane_nets'])} "
          f"removed ({n_net}), {n_via} fixed plane-net vias and {n_wire} wires turned into keepouts, "
          f"layer rules {LAYER_RULES}")


def drop_debris(board):
    """Delete unlocked wires that end inside a pad of ANOTHER net on their
    layer: freerouting's ripped-up leftovers. Left in place, the finish
    stage routes to their free end and shorts the pad."""
    pads = [p for fp in board.GetFootprints() for p in fp.Pads() if p.GetNetCode()]
    gone = 0
    for t in list(board.GetTracks()):
        if isinstance(t, pcbnew.PCB_VIA) or t.IsLocked():
            continue
        hit = False
        for e in (t.GetStart(), t.GetEnd()):
            for p in pads:
                if p.GetNetCode() == t.GetNetCode():
                    continue
                if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD and not p.IsOnLayer(t.GetLayer()):
                    continue
                if p.GetBoundingBox().Contains(e):
                    hit = True
                    break
            if hit:
                break
        if hit:
            board.Delete(t)
            gone += 1
    return gone


def wipe(board):
    # Delete (not Remove): Remove leaves ownership dangling on the python
    # proxy side -> heap corruption / segfaults later in the run
    for t in list(board.GetTracks()):
        board.Delete(t)
    for z in list(board.Zones()):
        board.Delete(z)


def pad_net(fp, net):
    """The pad of `fp` on net `net` (the parts are turned by place.py's
    FACING check, so pad numbers do not say which end is which)."""
    for p in fp.Pads():
        if p.GetNetname() == net:
            return p
    raise KeyError(f"{fp.GetReference()} has no pad on {net}")


def pad_of(fp, num):
    for p in fp.Pads():
        if p.GetNumber() == str(num):
            return p
    raise KeyError(f"{fp.GetReference()} pad {num}")


class Obstacles:
    """Coarse copper obstacle model for placing stitching vias after
    routing: every pad (any layer), track and via, as bounding circles."""

    def __init__(self, board):
        self.board = board
        self.items = []   # (x, y, r, netcode, layer-or-None(all), what)
        for fp in board.GetFootprints():
            for p in fp.Pads():
                bb = p.GetBoundingBox()
                x, y = rel(bb.GetCenter())
                # half the DIAGONAL: max(w, h)/2 misses a rectangle's corners;
                # the fragment stitcher put a GND via 0.04 mm from J4's
                # MOTOR1_SW pad corner that way (2026-10-18)
                r = math.hypot(to_mm(bb.GetWidth()), to_mm(bb.GetHeight())) / 2
                # a pad's own clearance (the Tag-Connect pads carry 0.5 mm)
                lc = p.GetLocalClearance()
                if lc:
                    r += to_mm(int(lc)) - 0.127
                if p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                    r += 0.08
                ly = None
                if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD:
                    ly = pcbnew.B_Cu if p.IsOnLayer(pcbnew.B_Cu) else pcbnew.F_Cu
                self.items.append((x, y, r, p.GetNetCode(), ly,
                                   f"{fp.GetReference()}.{p.GetNumber()}"))
        for t in board.GetTracks():
            if isinstance(t, pcbnew.PCB_VIA):
                x, y = rel(t.GetPosition())
                self.items.append((x, y, to_mm(t.GetWidth(pcbnew.F_Cu)) / 2,
                                   t.GetNetCode(), None, f"via {t.GetNetname()}"))
            else:
                a, b = rel(t.GetStart()), rel(t.GetEnd())
                w = to_mm(t.GetWidth()) / 2
                L = math.hypot(b[0] - a[0], b[1] - a[1])
                n = max(1, int(L / 0.3))
                for i in range(n + 1):
                    self.items.append((a[0] + (b[0] - a[0]) * i / n,
                                       a[1] + (b[1] - a[1]) * i / n, w + 0.15,
                                       t.GetNetCode(), t.GetLayer(),
                                       f"track {t.GetNetname()} {pcbnew.LayerName(t.GetLayer())}"))

        # the RP2350's power-block zones (rp2350_block.py) are planes nothing
        # may cut: no stitching or fragment via in the 1V1 ring, the 3V3
        # band or the PGND zone (one return point), and no hop through them.
        # The model has no zones otherwise; their boxes go in as a 0.2 mm
        # lattice of discs on their layer.
        for z in board.Zones():
            if z.GetIsRuleArea() or not z.GetZoneName().startswith(("rp2350_", "pwr_")):
                continue
            bb = z.GetBoundingBox()
            x0, y0 = to_mm(bb.GetLeft()) - CX, to_mm(bb.GetTop()) - CY
            x1, y1 = to_mm(bb.GetRight()) - CX, to_mm(bb.GetBottom()) - CY
            nx, ny = int((x1 - x0) / 0.2) + 1, int((y1 - y0) / 0.2) + 1
            for i in range(nx + 1):
                for k in range(ny + 1):
                    self.items.append((x0 + (x1 - x0) * i / nx, y0 + (y1 - y0) * k / ny, 0.15,
                                       z.GetNetCode(), z.GetLayer(), f"zone {z.GetZoneName()}"))

    def clear(self, x, y, r, gap):
        """A through via at (x,y) clear of everything on every layer?"""
        for ix, iy, ir, _, _ly, _w in self.items:
            if math.hypot(ix - x, iy - y) < r + ir + gap:
                return False
        return True

    def blocker(self, a, b, halfw, netname, layer, gap=0.127):
        """First other-net item on `layer` within `gap` of segment a-b
        (width 2*halfw), or None. Same-net items are what it is meant to
        touch."""
        nc = self.board.FindNet(netname).GetNetCode()
        for ix, iy, ir, inc, ly, what in self.items:
            if inc == nc or (ly is not None and ly != layer):
                continue
            if seg_dist(a, b, (ix, iy), (ix, iy)) < halfw + ir + gap:
                return what
        return None

    def clear_seg(self, a, b, halfw, netname, layer, gap=0.127):
        return self.blocker(a, b, halfw, netname, layer, gap) is None


def add_stitching(board, rt, design, obs, pitch=4.0, inset=1.2):
    """GND vias along the perimeter and on a coarse interior grid, only
    where nothing else is: they tie the outer pours to the In1 plane and
    fence the board edge. Skipped, never forced."""
    bb_edge = board.GetBoardEdgesBoundingBox()
    x_min, y_min = to_mm(bb_edge.GetLeft()) - CX, to_mm(bb_edge.GetTop()) - CY
    x_max, y_max = to_mm(bb_edge.GetRight()) - CX, to_mm(bb_edge.GetBottom()) - CY
    r_via = design["jlcpcb"]["via_diameter_mm"] / 2
    cands = []
    # perimeter walk along the inset outline
    perim = board_poly(design, inset)
    acc = 0.0
    for a, b_pt in zip(perim, perim[1:] + perim[:1]):
        seg_l = math.hypot(b_pt[0] - a[0], b_pt[1] - a[1])
        if acc == 0.0:
            cands.append(a)
        acc += seg_l
        if acc >= pitch:
            cands.append(b_pt)
            acc = 0.0
    # interior grid
    yy = y_min + inset
    while yy < y_max - inset:
        xx = x_min + inset
        while xx < x_max - inset:
            cands.append((xx, yy))
            xx += pitch
        yy += pitch
    no_via = [z for z in board.Zones() if z.GetIsRuleArea() and z.GetDoNotAllowVias()]
    in_poly = inside_board_poly(board, 0.6)

    def in_keepout(x, y):
        pt = pcbnew.VECTOR2I(mm(CX + x), mm(CY + y))
        return not in_poly.Contains(pt) or any(z.Outline().Collide(pt, mm(r_via + 0.1)) for z in no_via)
    placed = 0
    for x, y in cands:
        if in_keepout(x, y):
            continue
        if obs.clear(x, y, r_via, 0.25):
            rt.via((x, y), "GND", locked=False)
            obs.items.append((x, y, r_via, rt.net("GND").GetNetCode(), None, "stitch"))
            placed += 1
    return placed


def plane_pad_vias(board, rt, design, in_pad_only, net="GND", only=None, counts=None):
    """A via IN every pad of plane net `net` (GND, VSYS) that takes one. JLCPCB fills and caps
    via-in-pad for free on six layers (servodrive's finding), so every GND
    pad on either side gets a 0.4/0.2 via at its centre, straight down to
    the planes -- where nothing of another net is within clearance of the
    via's rim or hole. Run BEFORE freerouting (in_pad_only: the vias are
    then DSN keepouts it routes around, and the decoupling pads are never
    walled off by wires) and again after it, when pads that had no room
    get a via just beside them with a stub.

    `counts` asks for more than one via in a pad, {(ref, pad): n}: the
    current-carrying pads (design/stackup.md's via counts) get an array
    of 0.4/0.2 vias at 0.6 mm pitch inside the pad."""
    counts = counts or {}
    hw, hh = design["board"]["width_mm"] / 2, design["board"]["height_mm"] / 2
    have = [rel(v.GetPosition()) for v in board.GetTracks()
            if v.Type() == pcbnew.PCB_VIA_T and v.GetNetname() == net]
    gnd_track_ends = {}
    for tr in board.GetTracks():
        if tr.Type() == pcbnew.PCB_TRACE_T and tr.GetNetname() == net and tr.IsLocked():
            for q in (tr.GetStart(), tr.GetEnd()):
                gnd_track_ends.setdefault(tr.GetLayer(), []).append(rel(q))

    def smd_side(pad):
        return pcbnew.B_Cu if pad.IsOnLayer(pcbnew.B_Cu) and not pad.IsOnLayer(pcbnew.F_Cu) else pcbnew.F_Cu
    # ---- post-route: a via IN every GND pad that takes one ----
    # JLCPCB fills and caps via-in-pad for free on six layers (servodrive's
    # finding), so every GND pad on either side simply gets a 0.4/0.2 via at
    # its centre, straight down to the planes -- where nothing of another
    # net is within clearance of the via's rim or hole. The pours still
    # spoke to the rest; the finish stage handles any pad left over.
    obs0 = Obstacles(board)
    gnd_nc = rt.net(net).GetNetCode()
    no_via_zones = [z for z in board.Zones() if z.GetIsRuleArea() and z.GetDoNotAllowVias()]

    # no GND via inside the RP2350 block's zones either: in the 1V1 ring or
    # the 3V3 band it cuts the plane (C97/C98's GND pads sit under them on
    # the back, and their vias split the band), and in the PGND zone it is
    # a second return point
    block_zones = [z for z in board.Zones()
                   if not z.GetIsRuleArea() and (z.GetZoneName().startswith("rp2350_")
                                                 or (z.GetZoneName().startswith("pwr_") and z.GetNetname() != net))]

    # (a via IN a pad may sit inside another net's pwr_* zone: the pad is a
    # hole in that zone already -- C14's GND pad in the charger's OUT zone)
    pwr_zones = [z for z in block_zones if z.GetZoneName().startswith("pwr_")]
    rp_zones = [z for z in block_zones if not z.GetZoneName().startswith("pwr_")]

    in_poly = inside_board_poly(board, 0.6)

    def via_allowed(x, y, in_pad=False):
        pt = pcbnew.VECTOR2I(mm(CX + x), mm(CY + y))
        if not in_pad and not in_poly.Contains(pt):
            return False
        zs = no_via_zones + rp_zones + ([] if in_pad else pwr_zones)
        return not any(z.Outline().Collide(pt, mm(0.3)) for z in zs)

    def rect_gap(x, y, bb):
        """Distance from (x,y) to an axis-aligned box (left, top, right, bottom)."""
        dx = max(bb[0] - x, 0.0, x - bb[2])
        dy = max(bb[1] - y, 0.0, y - bb[3])
        return math.hypot(dx, dy)
    other_pads = []
    for fp_ in board.GetFootprints():
        for q in fp_.Pads():
            if q.GetNetCode() == gnd_nc:
                continue
            bb = q.GetBoundingBox()
            m = 0.08 if q.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH else 0.0
            other_pads.append((to_mm(bb.GetLeft()) - CX - m, to_mm(bb.GetTop()) - CY - m,
                               to_mm(bb.GetRight()) - CX + m, to_mm(bb.GetBottom()) - CY + m))

    def blockers_at(x, y, r, gap):
        """(hard, tracks): other-net pads/vias within `gap` of a via of radius
        r at (x,y) -- exact boxes and circles, not the coarse obstacle
        circles -- and the unlocked other-net wires that are."""
        hard, tracks = False, []
        for bb in other_pads:
            if rect_gap(x, y, bb) < r + gap:
                hard = True
                break
        if not hard:
            for tr in board.GetTracks():
                if tr.GetNetCode() == gnd_nc:
                    continue
                if tr.Type() == pcbnew.PCB_VIA_T:
                    if math.hypot(rel(tr.GetPosition())[0] - x, rel(tr.GetPosition())[1] - y) < r + to_mm(tr.GetWidth()) / 2 + gap:
                        hard = True
                        break
                    continue
                a, b_ = rel(tr.GetStart()), rel(tr.GetEnd())
                if seg_dist(a, b_, (x, y), (x, y)) < r + to_mm(tr.GetWidth()) / 2 + gap:
                    if tr.IsLocked():
                        hard = True
                        break
                    tracks.append(tr)
        return hard, tracks

    def clear_of_others(x, y, r, gap):
        hard, tracks = blockers_at(x, y, r, gap)
        return not hard and not tracks
    gnd_vias = 0
    for fp in board.GetFootprints():
        if only is not None and not only(fp):
            continue
        for pad in fp.Pads():
            if pad.GetNetname() != net or pad.GetAttribute() != pcbnew.PAD_ATTRIB_SMD:
                continue
            if net == "GND" and (fp.GetReference(), pad.GetNumber()) in PGND_PADS:
                continue                     # the RP2350 regulator's PGND: one return point only
            sz = pad.GetSize()
            if min(to_mm(sz.x), to_mm(sz.y)) < 0.45:
                continue                     # too small to hold a 0.4 via
            if min(to_mm(sz.x), to_mm(sz.y)) > 1.6 and (fp.GetReference(), pad.GetNumber()) not in counts:
                continue                     # an exposed pad: it has its own thermal vias
            px, py = rel(pad.GetPosition())
            bb = pad.GetBoundingBox()
            bx0, by0 = to_mm(bb.GetLeft()) - CX, to_mm(bb.GetTop()) - CY
            bx1, by1 = to_mm(bb.GetRight()) - CX, to_mm(bb.GetBottom()) - CY
            want = counts.get((fp.GetReference(), pad.GetNumber()), 1)
            if sum(1 for vx0, vy0 in have if bx0 <= vx0 <= bx1 and by0 <= vy0 <= by1) >= want:
                continue                     # a via already lands in this pad (its own, or
                                             # another pad's through it: J6's back MP under C80)
            if any(bx0 <= q[0] <= bx1 and by0 <= q[1] <= by1 for q in gnd_track_ends.get(smd_side(pad), ())):
                continue                     # a locked GND wire already serves it (the tactile
                                             # sensors' pre-routed pads 1 and 7)

            def far_from_gnd_vias(x, y):
                # same-net copper is invisible to the clearance checks, so
                # two pads' vias could land 0.34 mm apart (hole-to-hole)
                return all(math.hypot(vx0 - x, vy0 - y) >= 0.5 for vx0, vy0 in have)
            if not in_pad_only and via_allowed(px, py):
                # blocked only by unlocked wires (freerouting's, on other
                # layers under the pad)? cut them; the finish stage re-closes
                hard, tracks = blockers_at(px, py, 0.2, 0.13)
                if not hard and tracks:
                    for tr in tracks:
                        board.Delete(tr)
                    obs0.items = Obstacles(board).items
            # in the pad: its centre first, then along a long pad's axis
            # (the RM2's 1 x 2 mm GND pad 11 sits over the debug connector's
            # SWCLK pin on the back at its centre, but not at its inner end)
            sx, sy = to_mm(bb.GetWidth()), to_mm(bb.GetHeight())
            spots = [(px, py)]
            if max(sx, sy) >= 1.2:
                reach = max(sx, sy) / 2 - 0.25
                ax = (1, 0) if sx > sy else (0, 1)
                for f in (1.0, -1.0, 0.5, -0.5):
                    spots.append((px + ax[0] * reach * f, py + ax[1] * reach * f))
            if want > 1:
                # an array: a 0.6 mm lattice inside the pad (0.25 in from its
                # edge), nearest the centre first
                nxs, nys = max(1, int((sx - 0.5) / 0.6) + 1), max(1, int((sy - 0.5) / 0.6) + 1)
                spots = sorted(((px + (i - (nxs - 1) / 2) * 0.6, py + (k - (nys - 1) / 2) * 0.6)
                                for i in range(nxs) for k in range(nys)),
                               key=lambda q: math.hypot(q[0] - px, q[1] - py))
            placed = 0
            for qx, qy in spots:
                if clear_of_others(qx, qy, 0.2, 0.13) and via_allowed(qx, qy, in_pad=True) and far_from_gnd_vias(qx, qy):
                    rt.via((qx, qy), net)
                    have.append((qx, qy))        # paired pins share one pad (USB-C A1/B12): one via
                    obs0.items.append((qx, qy, 0.2, gnd_nc, None, f"{net} via-in-pad"))
                    gnd_vias += 1
                    placed += 1
                    if placed >= want:
                        break
            if placed and want > 1 and placed < want:
                print(f"  {fp.GetReference()}.{pad.GetNumber()} ({net}): room for {placed} of {want} vias")
            if placed:
                continue
            if in_pad_only:
                continue
            # no room in the pad: a via just outside it, away from the
            # footprint's centre, with a stub on the pad's own layer
            fx, fy = rel(fp.GetPosition())
            dx, dy = px - fx, py - fy
            L = math.hypot(dx, dy)
            if L < 0.05:
                continue
            ly = pcbnew.B_Cu if pad.IsOnLayer(pcbnew.B_Cu) else pcbnew.F_Cu
            # outward first, then every other direction, nearest first
            a0 = math.atan2(dy, dx)
            done = False
            for dist in (0.8, 1.0, 1.2, 1.5):
                for k in (0, 1, -1, 2, -2, 3, -3, 4):
                    a = a0 + k * math.pi / 4
                    vx, vy = px + math.cos(a) * dist, py + math.sin(a) * dist
                    if not via_allowed(vx, vy):
                        continue                     # off the board, in its edge clearance, or in the RF keep-out
                    if (obs0.clear(vx, vy, 0.2, 0.2) and obs0.clear_seg((px, py), (vx, vy), 0.1, "GND", ly)
                            and far_from_gnd_vias(vx, vy)):
                        rt.via((vx, vy), net)
                        have.append((vx, vy))
                        rt.track((px, py), (vx, vy), net, layer=ly, width=0.2)
                        obs0.items.append((vx, vy, 0.2, gnd_nc, None, f"{net} pad via"))
                        gnd_vias += 1
                        done = True
                        break
                if done:
                    break
    print(f"{net} via-in-pad / beside ({'pre' if in_pad_only else 'post'}): {gnd_vias}")


def main(attempt=0):
    no_freeroute = "--no-freeroute" in sys.argv
    design = load_design()
    board = pcbnew.LoadBoard(str(PCB))
    wipe(board)
    rt = Router(board, design)
    fps = {fp.GetReference(): fp for fp in board.GetFootprints()}
    st = stackup(design)

    # ---- pre-route: charger PowerPad thermal vias (via-in-pad, 4x) ----
    ep = pad_of(fps["U2"], 17)
    ex, ey = rel(ep.GetPosition())
    for dx, dy in ((-0.1, -0.4), (0.4, -0.4), (-0.1, 0.4), (0.4, 0.4)):
        rt.via((ex + dx, ey + dy), "GND")

    # ---- pre-route: the charger's power pins ----
    # The pin pairs first (VBAT 2+3, VSYS 10+11: 0.25 wide at 0.5 pitch, a
    # bridge inside the row touches nothing else).
    u2 = fps["U2"]
    assert abs(u2.GetOrientationDegrees() - 90) < 0.01, "route.py lays the charger's power copper for U2 at rot 90"
    P2 = {n: rel(pad_of(u2, n).GetPosition()) for n in (1, 2, 3, 5, 9, 10, 11)}
    for a, b in ((2, 3), (10, 11)):
        rt.track(P2[a], P2[b], pad_of(u2, a).GetNetname(), width=0.25)

    # EN2 (pin 5, VSYS): a lone plane-net pad in a 0.5 mm QFN row --
    # freerouting left it with a 0.7 mm stub and no via, twice. Stub
    # outward from the pad, a via into the In3 plane at the end, locked.
    u2x, u2y = rel(u2.GetPosition())
    p5 = P2[5]
    dx, dy = p5[0] - u2x, p5[1] - u2y
    if abs(dx) > abs(dy):
        out = (p5[0] + (0.65 if dx > 0 else -0.65), p5[1])
    else:
        out = (p5[0], p5[1] + (0.65 if dy > 0 else -0.65))
    rt.track(p5, out, "VSYS", width=0.15)
    rt.via(out, "VSYS")

    # OUT (pins 10+11 -> the In3 VSYS plane), 2 A when both motors run at
    # their 1 A rating (check_current.py): an F.Cu VSYS zone over the pin
    # row's outer end, taking in C14's VSYS pad and reaching east to the
    # OUT cap C11 (which cannot take a via: the cell pad is under it on the
    # back), with four 0.6/0.3 vias (0.8 A each, stackup.md): two in C14's
    # pad, two east of pin 9 (CHG_N keeps its exit below them, toward pin
    # 8). Nothing can go straight above the pins: C120, the top-left
    # sensor's cap, is under them on the back. It replaces one 0.2 via
    # (0.53 A, the phase-7 review's B2).
    top = P2[10][1] - 0.44                       # the pins' outer end (0.88 long)
    c14 = rel(pad_net(fps["C14"], "VSYS").GetPosition())
    vc, vd = (P2[9][0] + 0.55, top - 0.05), (P2[9][0] + 1.15, top - 0.05)
    for v in ((c14[0] - 0.15, c14[1] - 0.25), (c14[0] - 0.15, c14[1] + 0.25), vc, vd):
        rt.via(v, "VSYS", drill=0.3, size=0.6)
    # (each via on copper of its own: a via that touches no pad of its net
    # is re-netted by KiCad before the zone is ever filled)
    rt.track(c14, vc, "VSYS", width=0.25)
    rt.track(vc, vd, "VSYS", width=0.25)
    c11 = pad_net(fps["C11"], "VSYS").GetBoundingBox()
    cx1, cy0 = to_mm(c11.GetRight()) - CX, to_mm(c11.GetTop()) - CY
    z = rt.zone(pcbnew.F_Cu, "VSYS", [(P2[11][0] - 0.15, top - 1.55), (cx1, top - 1.55), (cx1, cy0 + 0.1),
                                       (P2[9][0] + 1.35, cy0 + 0.1), (P2[9][0] + 1.35, top + 0.16),
                                       (P2[11][0] - 0.15, top + 0.16)],
                priority=2, name="pwr_vsys_out", full=True)
    z.SetLocked(True)

    # CHG_N (pin 9) sits between the OUT pins and the OUT copper's vias:
    # out of the pad's inner end, east to a via between the vias and pin 8
    # (freerouting left it open in 5 of 8 orderings without it).
    p9in = (P2[9][0], P2[9][1] + 0.19)
    v9c = (P2[9][0] + 0.55, p9in[1])
    rt.track(p9in, v9c, "CHG_N", width=0.15)
    rt.via(v9c, "CHG_N")

    # BAT (pins 2+3 -> the cell pad J2.1 on the back), 2 A on battery with
    # both motors at their rating: an F.Cu VBAT zone under the pin row and
    # across to the cell pad, and four 0.5/0.25 vias into J2.1 (2.7 A).
    # TS (pin 1 -> R13) is laid first, down the zone's west side, so the
    # zone fills round it.
    r13 = rel(pad_net(fps["R13"], "TS").GetPosition())
    v_ts = (P2[1][0], 5.85)
    rt.path([P2[1], (P2[1][0], r13[1]), r13], "TS", width=0.15, chamfer=0.2)
    rt.via(v_ts, "TS")
    j2 = pad_of(fps["J2"], 1).GetBoundingBox()
    jx0, jy0 = to_mm(j2.GetLeft()) - CX, to_mm(j2.GetTop()) - CY
    jx1, jy1 = to_mm(j2.GetRight()) - CX, to_mm(j2.GetBottom()) - CY
    y_hi = jy0 + 0.25                              # inside J2.1 on the back (y=[4.25, 5.85]), well above C91 (y>=5.49)
    for vy in (y_hi, y_hi + 0.50):
        for vx in (jx0 + 0.50, jx0 + 1.10):
            rt.via((vx, vy), "VBAT", drill=0.25, size=0.5)
    rt.path([P2[3], (P2[3][0], 5.98), (-4.40, 5.98), (-3.50, 5.05), (jx0 + 0.50, y_hi + 0.50)],
            "VBAT", width=0.25, chamfer=0.0)
    c15 = pad_net(fps["C15"], "VBAT").GetBoundingBox()
    c12 = pad_net(fps["C12"], "VBAT").GetBoundingBox()
    bx0 = jx0 - 0.05                               # east of U2's right pins (-4.12), EN2 (-3.91), PG_N (-4.06)
    bx1 = max(jx0 + 1.40, to_mm(c15.GetRight()) - CX + 0.15, to_mm(c12.GetRight()) - CX + 0.15)
    by0 = min(y_hi - 0.3, to_mm(c15.GetTop()) - CY - 0.15)
    by1_e = y_hi + 0.65                            # 5.15: clears C91 (y>=5.49)
    by1_w = 6.12                                   # passes below U2.4 GND (y<=5.67) and above R13.2 GND (y>=6.28)
    yb = P2[3][1] - 0.15                           # 5.09: steps into J2.1
    z = rt.zone(pcbnew.F_Cu, "VBAT", [(P2[2][0] - 0.15, yb), (bx0, yb), (bx0, by0),
                                       (bx1, by0), (bx1, by1_e), (-3.40, by1_e),
                                       (-4.25, by1_w), (-6.15, by1_w), (P2[2][0] - 0.15, 5.50)],
                priority=2, name="pwr_vbat", full=True)
    z.SetLocked(True)

    # IN (pin 13, VBUS): pin 13 and its 10 uF C10 sit on the upper-left,
    # and TMR / ISET wall the strip below them, so VBUS enters via a
    # 0.7/0.4 via overlapping C10's VBUS pad.
    c10 = pad_net(fps["C10"], "VBUS").GetBoundingBox()
    vin = (to_mm(c10.GetLeft()) - CX - 0.07, to_mm(c10.GetCenter().y) - CY)
    rt.via(vin, "VBUS", drill=0.4, size=0.7)
    c10v = rel(pad_net(fps["C10"], "VBUS").GetPosition())
    p13_u2 = rel(pad_of(fps["U2"], 13).GetPosition())
    rt.path([c10v, (p13_u2[0] - 0.3, c10v[1]), p13_u2], "VBUS", width=0.4, chamfer=0.0)

    # ---- pre-route: the motor pad row's via arrays (J4, on the back) ----
    # J4, Q1, D3, C40, C41, Q2, D4, C42, C43 are all on B.Cu outside the
    # tactile sensors' no-via boxes. J4.1 takes 4x VSYS vias into In3 (2 A),
    # and D3/D4/C40/C42 take their VSYS vias in plane_pad_vias.
    j4 = fps["J4"]
    assert abs(j4.GetOrientationDegrees() % 180) < 0.01, "route.py lays J4's arrays for rot 0/180"
    q4 = {n: rel(pad_of(j4, n).GetPosition()) for n in (1, 2, 3)}
    for vx in (-0.3, 0.3):
        for vy in (-0.6, 0.0):
            rt.via((q4[1][0] + vx, q4[1][1] + vy), "VSYS")
    for n, net in ((2, "MOTOR1_SW"), (3, "MOTOR2_SW")):
        x, y = q4[n]
        rt.track((x, y - 0.6), (x, y + 0.6), net, layer=pcbnew.B_Cu, width=0.6)

    # ---- pre-route: the six QSPI lines ----
    # 0.4 mm pins, six of them in a row, and a flash 4 mm away: freerouting
    # closed four every run and the grid router never the last two. Laid
    # by hand, locked, relative to U1 (since U6 sits at the exact same
    # offset (-7.6, -1.5) from U1 as on the reference placement).
    u1, u6 = fps["U1"], fps["U6"]
    ux1_q, uy1_q = rel(u1.GetPosition())
    qdx, qdy = ux1_q - 4.8, uy1_q - 3.5

    def pin(fp, net):
        for p in fp.Pads():
            if p.GetNetname() == net:
                return rel(p.GetPosition())
        raise KeyError(net)
    inner = st["signal"][0]
    # net, x - y of its 45-degree run (in old U1=(4.8,3.5) frame), the lane it turns west on
    ribbon = (("QSPI_SD3", 4.6, -3.0), ("QSPI_SCLK", 4.0, -2.4), ("QSPI_SD0", 3.6, -1.8),
              ("QSPI_SD2", 3.2, -1.5), ("QSPI_SD1", 2.8, -1.2), ("QSPI_SS", 2.1, -0.9))
    out = {}
    for net, c0, lane0 in ribbon:
        c = c0 + (qdx - qdy)
        lane = lane0 + qdy
        m = pin(u1, net)
        out[net] = [m, (m[0], m[0] - c), (lane + c, lane)]
    # SS/SD1/SD2: west, down a column beside the flash, into the near pad
    for net, col0 in (("QSPI_SS", -0.1), ("QSPI_SD1", -0.4), ("QSPI_SD2", -0.7)):
        col = col0 + qdx
        f = pin(u6, net)
        lane = out[net][-1][1]
        rt.path(out[net] + [(col, lane), (col, f[1]), f], net, width=0.15, chamfer=0.2)
    f_cu = {"QSPI_SD3": [], "QSPI_SCLK": [],
            "QSPI_SD0": [(1.1 + qdx, -1.8 + qdy), (0.8 + qdx, -2.1 + qdy)]}
    in2 = {"QSPI_SD3": [], "QSPI_SCLK": [(1.3 + qdx, -2.7 + qdy)], "QSPI_SD0": []}
    for net, col0 in (("QSPI_SD0", -5.0), ("QSPI_SCLK", -5.45), ("QSPI_SD3", -5.9)):
        col = col0 + qdx
        f = pin(u6, net)
        pts = out[net] + f_cu[net]
        rt.path(pts, net, width=0.15, chamfer=0.2)
        v = pts[-1]
        rt.via(v, net)
        lane_pts = [v] + in2[net]
        y = lane_pts[-1][1]
        if net == "QSPI_SD0":            # the top far pad: via up-left of it, in at 45
            fv = (col, f[1] - 0.35)
            rt.path(lane_pts + [(col, y), fv], net, layer=inner, width=0.15)
            rt.via(fv, net)
            rt.path([fv, (col + 0.35, f[1]), f], net, width=0.15, chamfer=0.0)
        elif net == "QSPI_SD3":          # the bottom one: via comes in east
            fv = (col + 0.5, f[1])
            rt.path(lane_pts + [(col, y), (col, f[1] - 0.5), fv], net, layer=inner, width=0.15)
            rt.via(fv, net)
            rt.track(fv, f, net, width=0.15)
        else:
            fv = (col, f[1])
            rt.path(lane_pts + [(col, y), fv], net, layer=inner, width=0.15)
            rt.via(fv, net)
            rt.track(fv, f, net, width=0.15)

    # ---- pre-route: IOVDD pin 11's 100n, under the chip on the back ----
    # C97 sits between the left pin column and the exposed pad (place.py);
    # a via in its 3V3 pad goes up into the RP2350 block's 3V3 band, which
    # pin 11's inner end touches.
    rt.via(rel(pad_net(fps["C97"], "3V3_SYS").GetPosition()), "3V3_SYS")
    # their GND pads take no via (it would land in the band, gnd_pad_vias):
    # a B.Cu stub to the exposed pad's back-side copper instead
    ep_b = [q for q in fps["U1"].Pads() if q.GetNetname() == "GND" and q.IsOnLayer(pcbnew.B_Cu)
            and to_mm(q.GetSize().x) > 1.0]
    eb = ep_b[0].GetBoundingBox()
    ex0, ey0 = to_mm(eb.GetLeft()) - CX + 0.2, to_mm(eb.GetTop()) - CY + 0.2
    ex1, ey1 = to_mm(eb.GetRight()) - CX - 0.2, to_mm(eb.GetBottom()) - CY - 0.2
    for ref in ("C98", "C97"):
        g = rel(pad_net(fps[ref], "GND").GetPosition())
        tgt = (min(max(g[0], ex0), ex1), min(max(g[1], ey0), ey1))
        dx, dy = tgt[0] - g[0], tgt[1] - g[1]
        k = min(abs(dx), abs(dy))
        mid = (g[0] + math.copysign(k, dx), g[1] + math.copysign(k, dy)) if k > 1e-3 else g
        for a, b in ((g, mid), (mid, tgt)):
            if math.hypot(b[0] - a[0], b[1] - a[1]) > 1e-3:
                rt.track(a, b, "GND", layer=pcbnew.B_Cu, width=0.3)

    # ---- pre-route: USB-C pad-pair joins (the bike-tracker's, any orientation) ----
    # The receptacle's D+ pads (A6, B6) and D- pads (A7, B7) alternate at
    # 0.5 mm pitch with 0.2 mm gaps: the two halves of each signal can only
    # meet through another layer. Three bare vias inboard of the row give
    # freerouting the layer change. The VBUS pads get a straight 0.4 mm
    # stub out of the row; freerouting takes it from there with the Vbus
    # class (0.65 mm, 0.7/0.4 vias). They had a 0.4/0.2 via each, which was
    # the 0.53 A neck of every VBUS path once VBUS left In3 (2026-10-19).
    j1 = fps["J1"]
    P = {n: rel(pad_of(j1, n).GetPosition()) for n in ("A1", "A12", "A6", "B6", "A7", "B7", "A4", "A9")}
    rx, ry = P["A12"][0] - P["A1"][0], P["A12"][1] - P["A1"][1]
    Lr = math.hypot(rx, ry)
    rx, ry = rx / Lr, ry / Lr                       # along the pad row
    cxr, cyr = (P["A1"][0] + P["A12"][0]) / 2, (P["A1"][1] + P["A12"][1]) / 2
    u10x, u10y = rel(fps["U10"].GetPosition())
    sgn = 1.0 if ((u10x - cxr) * -ry + (u10y - cyr) * rx) > 0 else -1.0
    nx, ny = -ry * sgn, rx * sgn                     # inboard, toward the ESD array

    def inb(pt, d):
        return (pt[0] + nx * d, pt[1] + ny * d)
    rt.via(inb(P["A7"], 1.46), "USB_DM")
    rt.via(inb(P["B7"], 1.46), "USB_DM")
    v6 = inb(P["A6"], 2.11)
    rt.via(v6, "USB_DP")
    rt.track(P["A6"], v6, "USB_DP", width=0.15)                     # straight along the pad's line
    rt.path([P["B6"], inb(P["B6"], 2.11), v6], "USB_DP", width=0.15)   # out, then along the row (mitred)
    for n in ("A4", "A9"):
        rt.track(P[n], inb(P[n], 0.8), "VBUS", width=0.4)   # straight out of the row

    # ---- pre-route: the ESD array's middle pins ----
    # SOT-666, 0.5 mm pitch: pins 2 (GND) and 5 (VBUS) sit between their
    # neighbours and can only be entered from their outer ends. A via 0.55
    # past each pad centre along the row's axis and a locked stub from the
    # pad centre to it; freerouting then routes VBUS to the via. (The stub
    # is drawn now, not after routing: a via that touches no pad of its
    # net is re-netted by KiCad's net propagation before the DSN export.)
    u10 = fps["U10"]
    u10c = rel(u10.GetPosition())
    esd_vias = {}
    for n in (2,):                 # pin 5 (VBUS): C2 sits in line with it on the front
        pad = pad_of(u10, n)
        px, py = rel(pad.GetPosition())
        dx, dy = px - u10c[0], py - u10c[1]
        L = math.hypot(dx, dy)
        ox, oy = dx / L, dy / L
        v = (px + ox * 0.55, py + oy * 0.55)
        esd_vias[n] = v
        rt.via(v, pad.GetNetname())
        rt.track((px, py), v, pad.GetNetname(), width=0.2)


    # ---- pre-route: PG_N, charger pin 7 -> GPIO9 (pin 13) ----
    pg = rel(pad_of(fps["U2"], 7).GetPosition())
    g13 = rel(pad_of(fps["U1"], 13).GetPosition())
    v1_pg = (pg[0] + 0.50, pg[1] + 0.05)
    rt.track(pg, v1_pg, "PG_N", width=0.15)
    rt.via(v1_pg, "PG_N")
    v2_pg = (g13[0] - 0.8, g13[1] + 0.1)
    rt.via(v2_pg, "PG_N")
    rt.track(v2_pg, g13, "PG_N", width=0.15)

    # ---- pre-route: BTN (pin 12) out of the channel ----
    p12 = rel(pad_of(fps["U1"], 12).GetPosition())
    v12 = (p12[0] - 1.45, p12[1] + 0.4)
    rt.path([p12, (p12[0] - 1.05, p12[1]), v12], "BTN", width=0.15)
    rt.via(v12, "BTN")

    # ---- pre-route: the RP2350's power block, Raspberry Pi's layout ----
    # The 1V1 ring and 3V3 band under the chip, the four 1V1 spokes, the
    # regulator's zones and vias and the USB / 53-54 pin stubs, copied from
    # the RP2350A minimal board relative to U1 (rp2350_block.py; datasheet
    # s6.3.8: "must be strictly followed"). Replaces the hand-made pin 47
    # bridge, the pin 46/49/50 vias, the LX stub and the USB climb.
    u1 = fps["U1"]
    lay_rp2350_block(board, rt, design, fps)
    # USB: the reference sends D+/D- straight up from the 27R pair to a
    # connector above it. This board's USB-C is at the bottom, so each
    # takes a via in its connector-side pad (filled and capped).
    for rref, net in (("R3", "USB_DP"), ("R4", "USB_DM")):
        rt.via(rel(pad_net(fps[rref], net).GetPosition()), net)

    # ---- pre-route: escapes for WL_CS (pin 37), WL_CLK (pin 5), SENS_EN, IMU_INT1 (pins 7, 8), SWCLK, SWDIO (24, 25) ----
    p37 = rel(pad_of(fps["U1"], 37).GetPosition())
    v37 = (p37[0] + 0.75, p37[1])
    rt.via(v37, "WL_CS")
    rt.track(v37, p37, "WL_CS", width=0.15)

    p5 = rel(pad_of(fps["U1"], 5).GetPosition())
    vb_clk = (p5[0] - 0.9, p5[1])
    rt.via(vb_clk, "WL_CLK")
    rt.track(vb_clk, p5, "WL_CLK", width=0.15)

    p7 = rel(pad_of(fps["U1"], 7).GetPosition())
    p8 = rel(pad_of(fps["U1"], 8).GetPosition())
    v7 = (p7[0] - 0.65, p7[1] - 0.08)         # in the lane, clear of C80/C83 GND pads and v8
    rt.path([p7, (p7[0] - 0.08, v7[1]), v7], "SENS_EN", width=0.15, chamfer=0.0)
    rt.via(v7, "SENS_EN")
    v8 = (p8[0] - 1.06, p8[1] + 0.02)         # west of v7, >0.60 apart
    rt.path([p8, (p8[0] - 0.02, v8[1]), v8], "IMU_INT1", width=0.15, chamfer=0.0)
    rt.via(v8, "IMU_INT1")
    p24 = rel(pad_of(fps["U1"], 24).GetPosition())
    p25 = rel(pad_of(fps["U1"], 25).GetPosition())
    v24 = (p24[0] + 0.44, p24[1] + 1.17)     # east of the 1V1 spoke via below pin 23
    rt.path([p24, (p24[0], p24[1] + 0.73), v24], "SWCLK", width=0.15, chamfer=0.0)
    rt.via(v24, "SWCLK")
    # TAC_CS1 (pin 2): west to a via in the lane.
    p2u = rel(pad_of(fps["U1"], 2).GetPosition())
    v2u = (p2u[0] - 0.85, p2u[1])
    rt.track(p2u, v2u, "TAC_CS1", width=0.15)
    rt.via(v2u, "TAC_CS1")
    # TAC_CS2 (pin 18) and TAC_CS3 (pin 19): south escape vias so they leave on In2/B.Cu without crossing XIN/XOUT
    p18u = rel(pad_of(fps["U1"], 18).GetPosition())
    v18u = (p18u[0], p18u[1] + 0.70)
    rt.track(p18u, v18u, "TAC_CS2", width=0.15)
    rt.via(v18u, "TAC_CS2")
    p19u = rel(pad_of(fps["U1"], 19).GetPosition())
    v19u = (p19u[0] + 0.05, p19u[1] + 1.25)
    rt.path([p19u, (p19u[0], p19u[1] + 0.65), (v19u[0], p19u[1] + 0.70), v19u], "TAC_CS3", width=0.15, chamfer=0.0)
    rt.via(v19u, "TAC_CS3")
    # XIN (pin 21 -> Y1.1 -> C86) and XOUT (pin 22 -> R86.1) on F.Cu
    p21u = rel(pad_of(fps["U1"], 21).GetPosition())
    y1_xin = rel(pad_net(fps["Y1"], "XIN").GetPosition())
    c86_xin = rel(pad_net(fps["C86"], "XIN").GetPosition())
    rt.path([p21u, (p21u[0], p21u[1] + 1.25), (y1_xin[0], p21u[1] + 1.25 + abs(p21u[0] - y1_xin[0])), y1_xin], "XIN", width=0.15, chamfer=0.0)
    rt.path([c86_xin, (y1_xin[0] - abs(c86_xin[1] - y1_xin[1]), y1_xin[1]), y1_xin], "XIN", width=0.15, chamfer=0.0)
    p22u = rel(pad_of(fps["U1"], 22).GetPosition())
    r86_xout = rel(pad_net(fps["R86"], "XOUT").GetPosition())
    rt.path([p22u, (p22u[0], 17.65), (r86_xout[0], 17.65), r86_xout], "XOUT", width=0.15, chamfer=0.2)
    # CT_SENS (C50.1 -> U5.4) on B.Cu before USB_DP/DM route
    c50_ct = rel(pad_net(fps["C50"], "CT_SENS").GetPosition())
    u5_ct = rel(pad_net(fps["U5"], "CT_SENS").GetPosition())
    rt.path([c50_ct, (c50_ct[0] + abs(u5_ct[1] - c50_ct[1]), u5_ct[1]), u5_ct], "CT_SENS", layer=pcbnew.B_Cu, width=0.15, chamfer=0.0)
    # pins 25-29 (SWDIO, RUN, TAC_CS4, MOTOR2_PWM, IMU_INT2) as one staircase:
    fan = ((25, "SWDIO", 0.53, 0.69, (0.0, 0.08)), (26, "RUN", 0.41, 0.87, (0.0, 0.13)),
           (27, "TAC_CS4", 0.37, 1.11, (0.0, 0.43)), (28, "MOTOR2_PWM", 0.37, 1.17, (0.0, 0.79)),
           (29, "IMU_INT2", 0.37, 0.75, (0.18, 0.0)))
    fan_vias = {}
    for num, net, dy, run, (vx, vy) in fan:
        p = rel(pad_of(fps["U1"], num).GetPosition())
        a = (p[0], p[1] + dy)
        b = (a[0] + run, a[1] + run)
        v = (b[0] + vx, b[1] + vy)
        rt.path([p, a, b, v], net, width=0.15, chamfer=0.0)
        rt.via(v, net)
        fan_vias[net] = v
    # 3V3A (pin 44 -> R85.2 -> C85.1) locked on F.Cu before PDM_CLK/PDM_DATA route
    p44u = rel(pad_of(fps["U1"], 44).GetPosition())
    r85_a = rel(pad_net(fps["R85"], "3V3A").GetPosition())
    c85_a = rel(pad_net(fps["C85"], "3V3A").GetPosition())
    rt.path([p44u, (r85_a[0] - abs(r85_a[1] - p44u[1]), p44u[1]), r85_a], "3V3A", width=0.15, chamfer=0.0)
    rt.path([r85_a, (c85_a[0] - abs(c85_a[1] - r85_a[1]), r85_a[1]), c85_a], "3V3A", width=0.15, chamfer=0.0)

    # ---- pre-route: the USB pair, receptacle joins -> R3/R4, on B.Cu ----
    dpv = v6
    dma, dmb = inb(P["A7"], 1.46), inb(P["B7"], 1.46)
    for a, b in ((P["A7"], dma), (P["B7"], dmb)):
        rt.track(a, b, "USB_DM", width=0.15)        # straight inboard to the bare vias
    rt.track(dmb, dma, "USB_DM", layer=pcbnew.B_Cu, width=0.15)

    # ---- inner planes ----
    inner = board_poly(design, 0.5)
    st = stackup(design)  # (also set at the top of main)
    for ly in st["gnd"]:
        rt.zone(ly, "GND", inner, name=f"gnd_{pcbnew.LayerName(ly).lower().split('.')[0]}", full=True)
    # The pour is VSYS, not 3V3_SYS: VSYS carries the two motors (up to 2 A
    # together), the RM2's 271 mA bursts and the charger's output, and a
    # 0.4 mm track for it could not leave the charger's 0.5 mm-pitch pins
    # (freerouting's last four open connections, three runs out of three).
    # On a plane every VSYS pad is one via. The 3.3 V rail draws ~100 mA
    # and goes as 0.2 mm wires (the Supply class).
    rt.zone(st["pour"], "VSYS", inner, name="vsys_pour", full=True)

    def rule_area(name, layers, poly, tracks=True, vias=False, pour=False):
        z = pcbnew.ZONE(board)
        z.SetIsRuleArea(True)
        z.SetDoNotAllowTracks(tracks)
        z.SetDoNotAllowVias(vias)
        z.SetDoNotAllowCopperPour(pour)
        z.SetDoNotAllowPads(False)
        z.SetDoNotAllowFootprints(False)
        ls = pcbnew.LSET()
        for ly in layers:
            ls.addLayer(ly)
        z.SetLayerSet(ls)
        z.SetZoneName(name)
        ol = z.Outline()
        ol.NewOutline()
        for x, y in poly:
            ol.Append(mm(CX + x), mm(CY + y))
        board.Add(z)
        return z

    u7 = fps["U7"]
    ux, uy = rel(u7.GetPosition())
    assert abs(u7.GetOrientationDegrees()) < 0.01, "route.py assumes the RM2 at rot 0"
    k = design["radio"]["keepout_mm"]
    hw, hh = design["board"]["width_mm"] / 2, design["board"]["height_mm"] / 2
    # ---- permanent rule area: no F.Cu tracks under the RM2 body ----
    # Inside the pad ring (the pads reach 1.5 mm under the body), from the
    # keep-out line down to the bottom row: the module's underside is not
    # ours to route under, and a track there cannot be inspected.
    if "--no-u7-keepout" not in sys.argv:
        rule_area("u7_body_no_tracks", [pcbnew.F_Cu],
                  [(ux - 5.5, uy - 8.25 + k["depth"]), (ux + 5.5, uy - 8.25 + k["depth"]),
                   (ux + 5.5, uy + 6.5), (ux - 5.5, uy + 6.5)])
    # ---- permanent rule area: the RM2's RF keep-out, all layers ----
    # Datasheet fig. 6: 35.5 x 18.5 mm, from 13.5 beyond the antenna end to
    # 5.0 into the body, 10.5 either side. On this board that is the whole
    # top strip, both sides, every layer: no tracks, no vias, no pour.
    y_k = uy - 8.25 + k["depth"]
    x0 = -hw - 1.0          # the full width: the keep-out (10.5 mm each side) passes both edges; a narrower band let the planes fill a sliver beside the antenna (placement review)
    x1 = min(hw + 1.0, ux + 7.25 + k["side"])
    rule_area("antenna_keepout", list(pcbnew.LSET.AllCuMask(design["board"]["layers"]).Seq()),
              [(x0, -hh - 1.0), (x1, -hh - 1.0), (x1, y_k), (x0, y_k)],
              tracks=True, vias=True, pour=True)
    # ---- permanent rule areas: no vias under the tactile sensors ----
    # Each DPS368 sits on the back under the cast rubber; a via under its
    # body would print through and its plug could tilt the 50 um stand-off
    # LGA (placement review). Tracks on B.Cu may pass between its pads.
    from circuit import TACTILE
    for ref, _cap in TACTILE:
        f = fps[ref]
        f.BuildCourtyardCaches()
        bb = f.GetCourtyard(pcbnew.B_CrtYd).BBox()
        x0s, y0s = to_mm(bb.GetLeft()) - CX, to_mm(bb.GetTop()) - CY
        x1s, y1s = to_mm(bb.GetRight()) - CX, to_mm(bb.GetBottom()) - CY
        rule_area(f"tac_novia_{ref}", list(pcbnew.LSET.AllCuMask(design["board"]["layers"]).Seq()),
                  [(x0s, y0s), (x1s, y0s), (x1s, y1s), (x0s, y1s)], tracks=False, vias=True)

    # ---- GND pads that can take no via and get walled in ----
    # C91 (a 3V3 100 nF by the RP2350): the QSPI lanes run under its GND
    # pad on In2, so it reached the F.Cu pour only round the side WL_DATA
    # now takes; a via 0.5 above the pad, laid before WL_DATA is routed.
    c91g = rel(pad_net(fps["C91"], "GND").GetPosition())
    vg = (-3.80, 5.38)                             # west of J2.1 (-3.45), below pwr_vbat (5.15), above QSPI_SD3 (5.80)
    rt.path([c91g, (-3.38, c91g[1]), vg], "GND", width=0.2, chamfer=0.0)
    rt.via(vg, "GND")
    # R61 / C64 (the battery divider's GND end and its filter cap) sit on
    # F.Cu over J5's test pads on the back, and VBAT_SENSE walls them in:
    # R61's GND down the edge side into C64's, and C64's to a via below.
    r61g = rel(pad_net(fps["R61"], "GND").GetPosition())
    c64g = rel(pad_net(fps["C64"], "GND").GetPosition())
    xe = max(r61g[0], c64g[0]) + 0.6
    rt.path([r61g, (xe, r61g[1]), (xe, c64g[1]), c64g], "GND", width=0.25, chamfer=0.2)
    vg = (c64g[0] - 0.1, c64g[1] + 0.62)
    rt.track(c64g, vg, "GND", width=0.25)
    rt.via(vg, "GND")

    # ---- debug-probe connector J6 (DNP): pin 2 GND to its mounting pad ----
    j6 = fps["J6"]
    p2 = rel(pad_of(j6, 2).GetPosition())
    mps = [rel(pd.GetPosition()) for pd in j6.Pads() if pd.GetNumber() == "MP"]
    mp = min(mps, key=lambda q: abs(q[0] - p2[0] - 2.3) + abs(q[1] - p2[1] - 2.5))
    sgn = 1 if mp[1] > p2[1] else -1
    sx = 1 if mp[0] > p2[0] else -1
    k1 = (p2[0], p2[1] + sgn * 1.1)
    run = abs(mp[1] - k1[1])
    k2 = (p2[0] + sx * run, mp[1])
    rt.path([p2, k1, k2, mp], "GND", pcbnew.B_Cu, width=0.25)

    # ---- tactile sensors' GND: pad 1 -> pad 7 under the body, then out ----
    for ref, _cap in TACTILE:
        f = fps[ref]
        p1, p7, p8 = (rel(pad_of(f, n).GetPosition()) for n in (1, 7, 8))
        d = math.hypot(p8[0] - p1[0], p8[1] - p1[1])
        ux, uy = (p8[0] - p1[0]) / d, (p8[1] - p1[1]) / d
        vx, vy = -uy, ux                       # along the pad column
        spot = None
        for s in (0.9, 1.2, 1.5, 1.8, 2.1):
            for l in (0.0, 0.65, -0.65, 1.3, -1.3):
                knee = (p7[0] + 0.9 * ux, p7[1] + 0.9 * uy)
                via_at = (p7[0] + s * ux + l * vx, p7[1] + s * uy + l * vy)
                legs = [(p7, knee), (knee, via_at)]
                if free_for_gnd(board, via_at, legs):
                    spot = (knee, via_at)
                    break
            if spot:
                break
        new_via = spot is not None
        if not new_via:
            knee = (p7[0] + 0.9 * ux, p7[1] + 0.9 * uy)
            targets = [rel(v.GetPosition()) for v in board.GetTracks()
                       if isinstance(v, pcbnew.PCB_VIA) and v.GetNetname() == "GND"]
            targets += [rel(pd.GetPosition()) for fp in board.GetFootprints() if fp.GetReference() != ref
                        for pd in fp.Pads() if pd.GetNetname() == "GND" and pd.IsOnLayer(pcbnew.B_Cu)]
            targets.sort(key=lambda q: math.dist(q, p7))
            for q in targets:
                if math.dist(q, p7) > 2.5:
                    break
                if free_for_gnd(board, None, [(p7, knee), (knee, q)]):
                    spot = (knee, q)
                    break
        assert spot, f"no room for {ref}'s GND via and no GND copper within reach"
        knee, via_at = spot
        rt.track(p1, p7, "GND", pcbnew.B_Cu, width=0.15)
        rt.path([p7, knee, via_at] if math.dist(knee, via_at) > 1e-3 else [p7, via_at],
                "GND", pcbnew.B_Cu, width=0.25)
        if new_via:
            rt.via(via_at, "GND")
        print(f"  {ref} GND: pads 1+7 -> {'new via' if new_via else 'existing GND'} at "
              f"({via_at[0]:.2f}, {via_at[1]:.2f})")

    plane_pad_vias(board, rt, design, in_pad_only=True)
    # VSYS: the In3 plane is its only route, so every VSYS pad takes vias;
    # the RM2's VIN (271 mA bursts) and the motor flyback diodes take 2 vias each.
    VSYS_VIAS = {("U7", "16"): 2, ("D3", "1"): 2, ("D4", "1"): 2}
    plane_pad_vias(board, rt, design, in_pad_only=True, net="VSYS", counts=VSYS_VIAS)

    # ---- pre-route: the VBUS trunk, by the grid router ----
    from finish import preroute
    d6 = rel(pad_net(fps["D6"], "VBUS").GetPosition())
    every = list(pcbnew.LSET.AllCuMask(design["board"]["layers"]).Seq())
    nv = preroute(board, design, "VBUS", (vin, every), (d6, [pcbnew.F_Cu]))
    assert nv is not None, "no path for the VBUS trunk"
    print(f"VBUS trunk: {nv} vias")
    for n in ("A4", "A9"):
        nv = preroute(board, design, "VBUS", (inb(P[n], 0.8), [pcbnew.F_Cu]), (d6, [pcbnew.F_Cu]))
        print(f"VBUS {n} -> D6: {'no path' if nv is None else f'{nv} vias'}")
    # C13 (VBUS 100 nF on the back) to the trunk beside it NOW while the 3 mm B.Cu hop is open
    c13v = rel(pad_net(fps["C13"], "VBUS").GetPosition())
    nv = preroute(board, design, "VBUS", (c13v, [pcbnew.B_Cu]), (vin, every), layers=[pcbnew.B_Cu])
    if nv is None:
        nv = preroute(board, design, "VBUS", (c13v, [pcbnew.B_Cu]), (vin, every))
    print(f"C13 -> VBUS: {'no path' if nv is None else f'{nv} vias'}")

    # the motor switch nodes (Motor class: 0.4 mm, B.Cu): FET drain ->
    # flyback diode -> the MOT pad's B.Cu bar, routed first so USB_DP/DM don't wall off J4 on B.Cu
    for q, dd, n in (("Q1", "D3", 2), ("Q2", "D4", 3)):
        net = f"MOTOR{n - 1}_SW"
        qp = rel(pad_net(fps[q], net).GetPosition())
        dp = rel(pad_net(fps[dd], net).GetPosition())
        bar = (q4[n][0], q4[n][1] + 0.6)
        for a_, b_ in ((dp, bar), (qp, dp)):
            nv = preroute(board, design, net, (a_, [pcbnew.B_Cu]), (b_, [pcbnew.B_Cu]), layers=[pcbnew.B_Cu])
            print(f"{net}: {'no path' if nv is None else 'routed'}")

    # USB_DP (left/inner side) then USB_DM (right/outer side) from J1 joins to R3/R4 vias through the U1-C121 corridor
    r3 = rel(pad_net(fps["R3"], "USB_DP").GetPosition())
    r4 = rel(pad_net(fps["R4"], "USB_DM").GetPosition())
    avoid_dp = [(pcbnew.B_Cu, 6.0, 10.5, 12.8, 13.5)]
    avoid_dm = [(pcbnew.B_Cu, 7.0, 10.0, 12.8, 13.8)]
    nv = preroute(board, design, "USB_DP", (dpv, [pcbnew.B_Cu]), (r3, [pcbnew.B_Cu]), layers=[pcbnew.B_Cu], avoid=avoid_dp)
    if nv is None:
        nv = preroute(board, design, "USB_DP", (dpv, every), (r3, every), avoid=avoid_dp)
    print(f"USB_DP: {'no path' if nv is None else f'{nv} vias'}")
    nv = preroute(board, design, "USB_DM", (dma, [pcbnew.B_Cu]), (r4, [pcbnew.B_Cu]), layers=[pcbnew.B_Cu], avoid=avoid_dm)
    if nv is None:
        nv = preroute(board, design, "USB_DM", (dma, every), (r4, every), avoid=avoid_dm)
    print(f"USB_DM: {'no path' if nv is None else f'{nv} vias'}")

    # WL_DATA (gSPI data, R81 -> pin 4 and U7.5 -> R81) first so WL_CS/WL_CLK don't wall off R81 or pin 4
    r81 = rel(pad_net(fps["R81"], "WL_DATA").GetPosition())
    p4 = rel(pad_of(fps["U1"], 4).GetPosition())
    nv = preroute(board, design, "WL_DATA", (r81, [pcbnew.F_Cu]), (p4, [pcbnew.F_Cu]),
                  layers=[pcbnew.F_Cu, pcbnew.B_Cu])
    if nv is None:
        nv = preroute(board, design, "WL_DATA", (r81, [pcbnew.F_Cu]), (p4, [pcbnew.F_Cu]))
    print(f"WL_DATA: {'no path' if nv is None else f'{nv} vias'}")
    p5_u7 = rel(pad_of(fps["U7"], 5).GetPosition())
    nv = preroute(board, design, "WL_DATA", (p5_u7, [pcbnew.F_Cu]), (r81, [pcbnew.F_Cu]))
    print(f"WL_DATA (U7.5->R81): {'no path' if nv is None else f'{nv} vias'}")

    # PG_N, WL_CS, WL_CLK via grid router
    nv = preroute(board, design, "PG_N", (v1_pg, every), (v2_pg, every))
    print(f"PG_N: {'no path' if nv is None else f'{nv} vias'}")
    p9_u7 = rel(pad_of(fps["U7"], 9).GetPosition())
    nv = preroute(board, design, "WL_CS", (p9_u7, [pcbnew.F_Cu]), (v37, every))
    print(f"WL_CS: {'no path' if nv is None else f'{nv} vias'}")
    p3_u7 = rel(pad_of(fps["U7"], 3).GetPosition())
    nv = preroute(board, design, "WL_CLK", (p3_u7, [pcbnew.F_Cu]), (vb_clk, every))
    print(f"WL_CLK: {'no path' if nv is None else f'{nv} vias'}")

    # PDM_CLK (pin 43 -> U40.3) and PDM_DATA (pin 42 -> U40.4) up the right F.Cu channel
    p43u = rel(pad_of(fps["U1"], 43).GetPosition())
    u40_clk = rel(pad_net(fps["U40"], "PDM_CLK").GetPosition())
    nv = preroute(board, design, "PDM_CLK", (p43u, [pcbnew.F_Cu]), (u40_clk, [pcbnew.F_Cu]), layers=[pcbnew.F_Cu],
                  avoid=[(pcbnew.F_Cu, 5.8, 10.5, 8.0, 11.0)])
    if nv is None:
        nv = preroute(board, design, "PDM_CLK", (p43u, [pcbnew.F_Cu]), (u40_clk, [pcbnew.F_Cu]))
    print(f"PDM_CLK: {'no path' if nv is None else f'{nv} vias'}")
    p42u = rel(pad_of(fps["U1"], 42).GetPosition())
    u40_dat = rel(pad_net(fps["U40"], "PDM_DATA").GetPosition())
    nv = preroute(board, design, "PDM_DATA", (p42u, [pcbnew.F_Cu]), (u40_dat, [pcbnew.F_Cu]), layers=[pcbnew.F_Cu],
                  avoid=[(pcbnew.F_Cu, 5.8, 10.95, 7.0, 11.4)])
    if nv is None:
        nv = preroute(board, design, "PDM_DATA", (p42u, [pcbnew.F_Cu]), (u40_dat, [pcbnew.F_Cu]))
    print(f"PDM_DATA: {'no path' if nv is None else f'{nv} vias'}")
    # WL_ON (pin 41 -> U7.12)
    p41u = rel(pad_of(fps["U1"], 41).GetPosition())
    u7_12 = rel(pad_of(fps["U7"], 12).GetPosition())
    nv = preroute(board, design, "WL_ON", (p41u, [pcbnew.F_Cu]), (u7_12, [pcbnew.F_Cu]))
    print(f"WL_ON: {'no path' if nv is None else f'{nv} vias'}")

    # TAC_CS2 (pin 18's escape via -> the East sensor U21) and TAC_CS3 (pin 19's escape via -> the West sensor U22)
    u21 = rel(pad_net(fps["U21"], "TAC_CS2").GetPosition())
    nv = preroute(board, design, "TAC_CS2", (v18u, [pcbnew.In2_Cu, pcbnew.B_Cu]), (u21, [pcbnew.B_Cu]),
                  layers=[pcbnew.In2_Cu, pcbnew.B_Cu])
    if nv is None:
        nv = preroute(board, design, "TAC_CS2", (v18u, every), (u21, [pcbnew.B_Cu]))
    print(f"TAC_CS2: {'no path' if nv is None else f'{nv} vias'}")
    u22 = rel(pad_net(fps["U22"], "TAC_CS3").GetPosition())
    nv = preroute(board, design, "TAC_CS3", (v19u, [pcbnew.In2_Cu, pcbnew.B_Cu]), (u22, [pcbnew.B_Cu]),
                  layers=[pcbnew.In2_Cu, pcbnew.B_Cu])
    if nv is None:
        nv = preroute(board, design, "TAC_CS3", (v19u, every), (u22, [pcbnew.B_Cu]))
    print(f"TAC_CS3: {'no path' if nv is None else f'{nv} vias'}")

    # local 3V3_SENS links (pad 6 -> cap, pad 8 -> cap) on B.Cu for each sensor so 3V3_SENS never wraps around signal pads 2..5
    for sref, cref in TACTILE:
        sf, cf = fps[sref], fps[cref]
        cp = rel(pad_net(cf, "3V3_SENS").GetPosition())
        p2s, p5s = rel(pad_of(sf, 2).GetPosition()), rel(pad_of(sf, 5).GetPosition())
        av_s = [(pcbnew.B_Cu, min(p2s[0], p5s[0]) - 0.8, min(p2s[1], p5s[1]) - 0.8,
                 max(p2s[0], p5s[0]) + 0.8, max(p2s[1], p5s[1]) + 0.8)] if sref in ("U20", "U23") else [
                (pcbnew.B_Cu, p2s[0] - 0.8, min(p2s[1], p5s[1]) - 0.8, p2s[0] + 0.8, max(p2s[1], p5s[1]) + 0.8)]
        for pn in (6, 8):
            sp = rel(pad_of(sf, pn).GetPosition())
            preroute(board, design, "3V3_SENS", (sp, [pcbnew.B_Cu]), (cp, [pcbnew.B_Cu]),
                     layers=[pcbnew.B_Cu], avoid=av_s)
    # 3V3_SENS trunk from U5.5/C52 to C121 and C122
    u5_3v3s = rel(pad_of(fps["U5"], 5).GetPosition())
    u5_3v3s6 = rel(pad_of(fps["U5"], 6).GetPosition())
    c52_s = rel(pad_net(fps["C52"], "3V3_SENS").GetPosition())
    c121_s = rel(pad_net(fps["C121"], "3V3_SENS").GetPosition())
    c122_s = rel(pad_net(fps["C122"], "3V3_SENS").GetPosition())
    preroute(board, design, "3V3_SENS", (u5_3v3s, [pcbnew.B_Cu]), (u5_3v3s6, [pcbnew.B_Cu]), layers=[pcbnew.B_Cu])
    preroute(board, design, "3V3_SENS", (u5_3v3s6, [pcbnew.B_Cu]), (c52_s, [pcbnew.B_Cu]))
    nv = preroute(board, design, "3V3_SENS", (u5_3v3s, [pcbnew.B_Cu]), (c121_s, [pcbnew.B_Cu]))
    print(f"3V3_SENS (U5->C121): {'no path' if nv is None else f'{nv} vias'}")
    # SENS_EN (v7 -> R50.1 -> U5.3) before IMU_INT1 and J5 1V1
    r50_en = rel(pad_net(fps["R50"], "SENS_EN").GetPosition())
    u5_en = rel(pad_net(fps["U5"], "SENS_EN").GetPosition())
    preroute(board, design, "SENS_EN", (r50_en, [pcbnew.B_Cu]), (u5_en, [pcbnew.B_Cu]), layers=[pcbnew.B_Cu])
    nv = preroute(board, design, "SENS_EN", (v7, every), (r50_en, [pcbnew.B_Cu]))
    print(f"SENS_EN: {'no path' if nv is None else f'{nv} vias'}")
    # SWDIO (v25 -> J6.3)
    j6_swdio = rel(pad_net(fps["J6"], "SWDIO").GetPosition())
    nv = preroute(board, design, "SWDIO", (fan_vias["SWDIO"], every), (j6_swdio, [pcbnew.B_Cu]))
    print(f"SWDIO: {'no path' if nv is None else f'{nv} vias'}")
    # TAC_SDO (U22.5 -> U30)
    u22_sdo = rel(pad_net(fps["U22"], "TAC_SDO").GetPosition())
    u30_sdo = rel(pad_net(fps["U30"], "TAC_SDO").GetPosition())
    nv = preroute(board, design, "TAC_SDO", (u22_sdo, [pcbnew.B_Cu]), (u30_sdo, [pcbnew.B_Cu]))
    print(f"TAC_SDO (U22->U30): {'no path' if nv is None else f'{nv} vias'}")
    # VBAT sense (R60.1 -> C15.1)
    r60_vbat = rel(pad_net(fps["R60"], "VBAT").GetPosition())
    c15_vbat = rel(pad_net(fps["C15"], "VBAT").GetPosition())
    nv = preroute(board, design, "VBAT", (r60_vbat, [pcbnew.F_Cu]), (c15_vbat, [pcbnew.F_Cu]))
    print(f"VBAT (R60->C15): {'no path' if nv is None else f'{nv} vias'}")
    # WL_IRQ (R81 -> RM2 pad 10)
    r81i = rel(pad_net(fps["R81"], "WL_IRQ").GetPosition())
    u710 = rel(pad_of(fps["U7"], 10).GetPosition())
    nv = preroute(board, design, "WL_IRQ", (r81i, [pcbnew.F_Cu]), (u710, [pcbnew.F_Cu]))
    print(f"WL_IRQ: {'no path' if nv is None else f'{nv} vias'}")
    # TAC_CS1 (pin 2's escape via -> the North sensor U20)
    u20 = rel(pad_net(fps["U20"], "TAC_CS1").GetPosition())
    cols = sorted({round(rel(pd.GetPosition())[0], 2) for pd in fps["U20"].Pads()})
    ys = [rel(pd.GetPosition())[1] for pd in fps["U20"].Pads()]
    gap = (pcbnew.B_Cu, cols[0] + 0.3, min(ys) - 0.6, cols[-1] - 0.3, max(ys) + 0.6)
    nv = preroute(board, design, "TAC_CS1", (v2u, every), (u20, [pcbnew.B_Cu]), avoid=[gap])
    print(f"TAC_CS1: {'no path' if nv is None else f'{nv} vias'}")
    # IMU_INT1 (pin 8's escape via -> the IMU, U30 on B.Cu)
    p30 = rel(pad_net(fps["U30"], "IMU_INT1").GetPosition())
    nv = preroute(board, design, "IMU_INT1", (v8, every), (p30, [pcbnew.B_Cu]))
    print(f"IMU_INT1: {'no path' if nv is None else f'{nv} vias'}")
    # CHG_N (v9c -> R14), TS (v_ts -> J2.3), J5.3 (1V1 -> C98)
    r14_chg = rel(pad_net(fps["R14"], "CHG_N").GetPosition())
    nv = preroute(board, design, "CHG_N", (v9c, every), (r14_chg, [pcbnew.F_Cu]))
    print(f"CHG_N: {'no path' if nv is None else f'{nv} vias'}")
    j2_ts = rel(pad_net(fps["J2"], "TS").GetPosition())
    nv = preroute(board, design, "TS", (v_ts, every), (j2_ts, [pcbnew.B_Cu]))
    print(f"TS: {'no path' if nv is None else f'{nv} vias'}")
    j5_1v1 = rel(pad_net(fps["J5"], "1V1").GetPosition())
    c98_1v1 = rel(pad_net(fps["C98"], "1V1").GetPosition())
    nv = preroute(board, design, "1V1", (j5_1v1, [pcbnew.B_Cu]), (c98_1v1, [pcbnew.B_Cu]))
    print(f"J5 1V1: {'no path' if nv is None else f'{nv} vias'}")
    # GND return vias for the pre-routes' layer changes (USB, WL_CLK, WL_CS,
    # WL_DATA, the pin escapes), now, while there is room for them
    # (stitch.py does the routed ones). After the grid-routed nets: a
    # return via first took pin 4's only way out.
    from stitch import return_vias
    print("return vias for the pre-routes: %d placed, %d without room"
          % return_vias(board, rt, ahead=True, fast_only=True))

    # ---- edge keepout, for freerouting only ----
    # Freerouting keeps wires a net-clearance (0.127) from the outline,
    # not the 0.2 mm copper-edge clearance JLC wants, so it lays power
    # traces along the edge that DRC then rejects. A rule area ring
    # (outline down to 0.3 mm inside it, no tracks / no vias) is exported
    # as a DSN keepout it must stay clear of; it is deleted after import.
    ring = pcbnew.ZONE(board)
    ring.SetIsRuleArea(True)
    ring.SetDoNotAllowTracks(True)
    ring.SetDoNotAllowVias(True)
    ring.SetDoNotAllowCopperPour(False)
    ring.SetDoNotAllowPads(False)
    ring.SetDoNotAllowFootprints(False)
    ring.SetLayerSet(pcbnew.LSET.AllCuMask(design["board"]["layers"]))
    ring.SetZoneName("edge_keepout_tmp")
    ol = ring.Outline()
    ol.NewOutline()
    for x, y in board_poly(design, -0.5):
        ol.Append(mm(CX + x), mm(CY + y))
    ol.NewHole()
    for x, y in board_poly(design, 0.3):
        ol.Append(mm(CX + x), mm(CY + y), 0, 0)
    board.Add(ring)
    # the same for the RP2350 block's F.Cu zones: freerouting treats no zone
    # as an obstacle (and GND, the PGND zone's net, is not in its netlist),
    # so without these it routes signals through the 1V1 ring, the 3V3 band
    # and the regulator's high-current zones
    # (each zone's own outline: one box over the regulator also shut pin
    # 45 off and the strip between R4 and L1 where USB takes its vias)
    # (and route.py's own power zones, pwr_*: the charger's OUT and BAT)
    for z in list(board.Zones()):
        if z.GetIsRuleArea() or not z.GetZoneName().startswith(("rp2350_", "pwr_")):
            continue
        ol = z.Outline()
        rule_area(f"{z.GetZoneName()}_tmp", [z.GetLayer()],
                  [rel(ol.CVertex(i)) for i in range(ol.TotalVertices())], tracks=True, vias=True)
    pcbnew.SaveBoard(str(PCB), board)
    if os.environ.get("ROUTE_DRY"):
        print("ROUTE_DRY: pre-routes saved, no freerouting")
        return 0

    # ---- freerouting ----
    if not no_freeroute:
        dsn = ROOT / "out" / "bluebuzz-rm2.dsn"
        ses = ROOT / "out" / "bluebuzz-rm2.ses"
        ses.unlink(missing_ok=True)
        if not pcbnew.ExportSpecctraDSN(board, str(dsn)):
            print("DSN export failed")
            sys.exit(1)
        reorder_placement(dsn, attempt)
        tame_dsn(dsn, design)
        ses = route_with_resume(dsn, ses, attempt, design)
        if not ses.exists():
            print("freerouting produced no SES")
            return 3                             # another attempt may fare better
        board = pcbnew.LoadBoard(str(PCB))
        if not pcbnew.ImportSpecctraSES(board, str(ses)):
            print("SES import failed")
            return 3                             # keep the best of the other attempts
        rt = Router(board, design)
        fps = {fp.GetReference(): fp for fp in board.GetFootprints()}
        board.BuildConnectivity()
        print(f"after freerouting: {board.GetConnectivity().GetUnconnectedCount(True)} unconnected, "
              f"{sum(1 for x in board.GetTracks() if not isinstance(x, pcbnew.PCB_VIA))} wires, "
              f"{sum(1 for x in board.GetTracks() if isinstance(x, pcbnew.PCB_VIA))} vias")
        for z in list(board.Zones()):
            if z.GetZoneName().endswith("_tmp"):
                board.Delete(z)
        zl = 0
        for t in list(board.GetTracks()):
            if not isinstance(t, pcbnew.PCB_VIA) and t.GetLength() < 1000:   # < 1 um
                board.Delete(t)
                zl += 1
        if zl:
            print(f"removed {zl} zero-length wires")
        deb = drop_debris(board)
        if deb:
            print(f"removed {deb} wires ending on another net's pad (freerouting debris)")
        # GND has a plane (In1), two pours and stitching vias: a GND WIRE
        # from freerouting is at best redundant and at worst debris -- a
        # ripped-up fragment it leaves lying across another net (seen:
        # a 0.4 mm GND stub 0.05 mm from a VSYS wire inside the LDO's
        # footprint). Every unlocked GND wire goes; a GND pad the pours
        # cannot reach is closed by the finish stage with a via.
        gw = 0
        for t in list(board.GetTracks()):
            if (not isinstance(t, pcbnew.PCB_VIA) and t.GetNetname() == "GND"
                    and not t.IsLocked()):
                board.Delete(t)
                gw += 1
        print(f"removed {gw} freerouting GND wires (planes and pours carry GND)")
        # In1 is the GND plane: everything freerouting put there goes to
        # B.Cu (always fits, see relayer). Then as much of In2 as fits,
        # so the 3V3 pour keeps its shape too.
        dropped, peeled = drop_flat_vias(board)
        if dropped:
            print(f"dropped {dropped} unused / single-layer vias, "
                  f"{peeled} dangling wires")
        left1, left2 = relayer(board, design)
        print(f"relayer: {left1} wires left on the planes, {left2} on the inner signal layer")
        if left1:
            # a wire on In1 is a slot in the ground plane. Take them out
            # (and whatever then dangles) and leave the connection open
            # for close_gaps / finish, which route on F.Cu, In2 and B.Cu.
            n = 0
            for tr in list(board.GetTracks()):
                if (not isinstance(tr, pcbnew.PCB_VIA) and tr.GetLayer() in stackup(design)["planes"]
                        and not tr.IsLocked()):
                    board.Delete(tr)
                    n += 1
            peeled = prune_dangling(board)
            print(f"removed {n} plane-layer wires and {peeled} dangling wires for the finish stage")
        # Re-layering moves wires between layers, so a via that changed a
        # layer before it can be flat after: sweep again, or the board
        # ships with what DRC calls a dangling via.
        dropped, peeled = drop_flat_vias(board)
        if dropped:
            print(f"dropped {dropped} vias flattened by re-layering, "
                  f"{peeled} dangling wires")

    else:
        for z in list(board.Zones()):
            if z.GetZoneName().endswith("_tmp"):
                board.Delete(z)

    hw, hh = design["board"]["width_mm"] / 2, design["board"]["height_mm"] / 2
    plane_pad_vias(board, rt, design, in_pad_only=False)
    plane_pad_vias(board, rt, design, in_pad_only=False, net="VSYS", counts=VSYS_VIAS)

    # ---- outer pours + stitching (post-route: as DSN planes they stall
    #      freerouting, and it routes better with the outer layers open) ----
    outer = board_poly(design, 0.4)
    gf = rt.zone(pcbnew.F_Cu, "GND", outer, name="gnd_front")
    # the RP2350 regulator's PGND meets GND at its via pair only: the front
    # pour has a hole over the block (rp2350_block.POUR_HOLE)
    from rp2350_block import POUR_HOLE
    ux1, uy1 = rel(fps["U1"].GetPosition())
    gf.Outline().NewHole()
    for x, y in POUR_HOLE:
        gf.Outline().Append(mm(CX + ux1 + x), mm(CY + uy1 + y), 0, 0)
    rt.zone(pcbnew.B_Cu, "GND", outer, name="gnd_back")
    obs = Obstacles(board)      # rebuilt: the stubs are copper too
    n = add_stitching(board, rt, design, obs, pitch=2.0)
    print(f"stitching vias: {n}")

    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())
    pcbnew.SaveBoard(str(PCB), board)
    board.BuildConnectivity()
    unconnected = board.GetConnectivity().GetUnconnectedCount(True)
    print(f"routing done; unconnected: {unconnected}")
    # (close_gaps / finish take it from here; drc is the gate)
    return 0 if (unconnected <= 12 or no_freeroute) else 2


if __name__ == "__main__":
    # Freerouting's outcome depends on the order of the components in the
    # DSN (its stop rule is "score has not improved for 10 passes", and
    # which item that strands depends on what it tried first). KiCad's
    # exporter emits that order from a hash, different in every process
    # -- which is what looked like thread-timing nondeterminism before.
    # reorder_placement() makes attempt 0 canonical and each retry a
    # seeded permutation, so the retries really are different attempts and
    # any of them can be reproduced. Everything up to the DSN export is
    # regenerated from scratch each time (wipe + pre-route). The failure
    # is reported honestly if all tries miss.
    # The board is built from the ordering design.yaml names (routing:
    # ordering), one try. ROUTE_FIRST / ROUTE_TRIES search instead: start
    # at another ordering and try several (to run orderings side by side
    # in copies of the project and pick the best).
    chosen = load_design().get("routing", {}).get("ordering", 0)
    tries = int(os.environ.get("ROUTE_TRIES", "1" if "ROUTE_FIRST" not in os.environ else "3"))
    best_pcb = PCB.with_name("bluebuzz-rm2.best.kicad_pcb")
    rc, best = 2, None
    first = int(os.environ.get("ROUTE_FIRST", str(chosen)))
    for attempt in range(first, first + tries):
        if attempt > first:
            print(f"--- route attempt {attempt + 1}/{tries} ---")
        rc = main(attempt)
        if rc in (0, 2):
            bb = pcbnew.LoadBoard(str(PCB))
            bb.BuildConnectivity()
            n = bb.GetConnectivity().GetUnconnectedCount(True)
            # rank by copper defects, then by the open SIGNAL connections:
            # the GND ones (pads to pours, pour islands) are what the
            # finish stage closes, and they swamped the count (freerouting
            # 3 unrouted -> 57 here)
            bad, sig = attempt_score(PCB)
            print(f"attempt {attempt + 1}: {bad} copper defects, {n} unconnected, "
                  f"{sig} of them not GND")
            shutil.copy(PCB, PCB.with_name(f"bluebuzz-rm2.attempt{attempt + 1}.kicad_pcb"))
            if best is None or (bad, sig, n) < best[0]:
                shutil.copy(PCB, best_pcb)
                best = ((bad, sig, n), attempt + 1)
        if best is not None and best[0][0] == 0 and best[0][2] == 0:
            break                            # clean and nothing left open: no need for more orderings
    if best is not None:
        shutil.copy(best_pcb, PCB)       # an attempt that produced no SES must not leave its wiped board behind
        bad, sig, n = best[0]
        print(f"kept attempt {best[1]} ({bad} copper defects, {n} unconnected, {sig} not GND)")
        rc = 0 if n <= 12 else 2
    sys.exit(rc)
