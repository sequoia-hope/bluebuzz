#!/usr/bin/env python3
"""Routing pipeline.

1. Wipe existing tracks / vias / zones (idempotent).
2. Pre-route: the inner planes (In1 = GND, In2 = 3V3_SYS), the thermal
   vias under the charger's PowerPad, the USB pad-pair joins and the ESD
   array's middle-pin vias, the module's interior GND pad via, the
   Tag-Connect pad escapes (on the back, where J3 lives). Plus the rule
   areas: no F.Cu tracks under the E73 body, NO COPPER AT ALL under the
   module's antenna end out to the board edge (permanent), an edge ring
   and a Tag-Connect keepout (exported for freerouting, deleted after).
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
import subprocess
import os
import sys
from pathlib import Path

import pcbnew

sys.path.insert(0, str(Path(__file__).resolve().parent))
from circuit import load_design  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PCB = ROOT / "out" / "bluebuzz.kicad_pcb"
JAR = ROOT / "tools" / "freerouting.jar"
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


def board_poly(design, inset, n_arc=8):
    """The rounded-rectangle outline shrunk by `inset` mm."""
    b = design["board"]
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
                r = max(to_mm(bb.GetWidth()), to_mm(bb.GetHeight())) / 2
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
    In1, In2, B = pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu
    LAYERS = (B, In2, In1)                 # preference order
    COST = {B: 0.0, In2: 1.0, In1: 1000.0}  # per mm of wire
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
    return (sum(len(g[0]) for g in wg.on(In1)),
            sum(len(g[0]) for g in wg.on(In2)))


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
            base = nm.split("::")[0]
            groups.setdefault(base, []).append((nm, "\n".join(b[1:])))
        rename = {}
        for base, var in groups.items():
            if len(var) < 2:
                continue
            var.sort(key=lambda v: v[1])
            for n, (nm, _) in enumerate(var):
                rename[nm] = base if n == 0 else f"{base}::{n}"
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
    Path(dsn_path).write_text("\n".join(lines) + "\n")


def wipe(board):
    # Delete (not Remove): Remove leaves ownership dangling on the python
    # proxy side -> heap corruption / segfaults later in the run
    for t in list(board.GetTracks()):
        board.Delete(t)
    for z in list(board.Zones()):
        board.Delete(z)


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
                r = max(to_mm(bb.GetWidth()), to_mm(bb.GetHeight())) / 2
                # a pad's own clearance (the Tag-Connect pads carry 0.5 mm)
                lc = p.GetLocalClearance()
                if lc:
                    r += to_mm(int(lc)) - 0.127
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
    b = design["board"]
    hw, hh = b["width_mm"] / 2, b["height_mm"] / 2
    r_via = design["jlcpcb"]["via_diameter_mm"] / 2
    cands = []
    x = -hw + inset
    while x <= hw - inset + 1e-6:
        cands += [(x, -hh + inset), (x, hh - inset)]
        x += pitch
    # ...and the far corners, which the stride above walks past; a pour
    # piece hanging on a connector's GND tab in a corner (J2's) was the
    # one GND island the first clean build still reported
    cands += [(hw - inset, -hh + inset), (hw - inset, hh - inset)]
    y = -hh + inset + pitch
    while y < hh - inset - 1e-6:
        cands += [(-hw + inset, y), (hw - inset, y)]
        y += pitch
    cands += [(-hw + inset, hh - inset - pitch / 2), (hw - inset, hh - inset - pitch / 2),
              (-hw + inset, -hh + inset + pitch / 2), (hw - inset, -hh + inset + pitch / 2)]
    # interior grid, offset so it does not land on the perimeter rows
    yy = -hh + inset + pitch
    while yy < hh - inset:
        xx = -hw + inset + pitch
        while xx < hw - inset:
            cands.append((xx, yy))
            xx += pitch
        yy += pitch
    no_via = [z for z in board.Zones() if z.GetIsRuleArea() and z.GetDoNotAllowVias()]

    def in_keepout(x, y):
        pt = pcbnew.VECTOR2I(mm(CX + x), mm(CY + y))
        return any(z.Outline().Collide(pt, mm(r_via + 0.1)) for z in no_via)
    placed = 0
    for x, y in cands:
        if abs(x) > hw - 0.6 or abs(y) > hh - 0.6 or in_keepout(x, y):
            continue
        if obs.clear(x, y, r_via, 0.25):
            rt.via((x, y), "GND", locked=False)
            obs.items.append((x, y, r_via, rt.net("GND").GetNetCode(), None, "stitch"))
            placed += 1
    return placed


def main(attempt=0):
    no_freeroute = "--no-freeroute" in sys.argv
    design = load_design()
    board = pcbnew.LoadBoard(str(PCB))
    wipe(board)
    rt = Router(board, design)
    fps = {fp.GetReference(): fp for fp in board.GetFootprints()}

    # ---- pre-route: charger PowerPad thermal vias (via-in-pad, 4x) ----
    ep = pad_of(fps["U2"], 17)
    ex, ey = rel(ep.GetPosition())
    for dx, dy in ((-0.4, -0.4), (0.4, -0.4), (-0.4, 0.4), (0.4, 0.4)):
        rt.via((ex + dx, ey + dy), "GND")

    # ---- pre-route: the charger's EN2 pad (3V3_SYS) to the In2 pour ----
    # A lone plane-net pad in a 0.5 mm QFN row: freerouting left it with a
    # 0.7 mm stub and no via, twice. Stub outward from the pad, via at the
    # end, locked.
    u2 = fps["U2"]
    u2x, u2y = rel(u2.GetPosition())
    p5 = rel(pad_of(u2, 5).GetPosition())
    dx, dy = p5[0] - u2x, p5[1] - u2y
    if abs(dx) > abs(dy):
        out = (p5[0] + (0.8 if dx > 0 else -0.8), p5[1])
    else:
        out = (p5[0], p5[1] + (0.8 if dy > 0 else -0.8))
    rt.track(p5, out, "3V3_SYS", width=0.15)
    rt.via(out, "3V3_SYS")

    # ---- pre-route: USB pad-pair joins (bike-tracker, unchanged) ----
    # The receptacle's D+ pads (A6, B6) and D- pads (A7, B7) alternate at
    # 0.5 mm pitch with 0.2 mm gaps: the two halves of each signal can
    # only meet through another layer. Three bare vias under the row give
    # freerouting the layer change.
    j1 = fps["J1"]
    a6, a7, b7 = (rel(pad_of(j1, n).GetPosition()) for n in ("A6", "A7", "B7"))
    row_y = a6[1]
    down = 1.0 if fps["U10"].GetPosition().y > pad_of(j1, "A6").GetPosition().y else -1.0
    rt.via((a7[0], row_y + down * 1.46), "USB_DM")
    rt.via((b7[0], row_y + down * 1.46), "USB_DM")
    rt.via((a6[0], row_y + down * 2.11), "USB_DP")
    # Each VBUS via gets the pad's own hop down to it, locked. Not a
    # courtesy: a via cluster that touches no pad of its net is re-netted
    # by KiCad's net propagation (the DSN exporter runs it) to the plane
    # it passes through -- on the first build every VBUS pre-route came
    # back as GND, and freerouting then dutifully routed it as ground.
    for n in ("A4", "A9"):
        px, py = rel(pad_of(j1, n).GetPosition())
        rt.via((px, row_y + down * 1.41), "VBUS")
        rt.track((px, py), (px, row_y + down * 1.41), "VBUS", width=0.4)
    # The ESD array's middle pins (2 GND, 5 VBUS) can only be entered from
    # their outer ends: a via past each end now, a scripted stub after.
    u10 = fps["U10"]
    p2, p5 = (rel(pad_of(u10, n).GetPosition()) for n in (2, 5))
    esd_vias = {2: (p2[0], p2[1] - down * 0.55), 5: (p5[0], p5[1] + down * 0.55)}
    rt.via(esd_vias[2], "GND")
    rt.via(esd_vias[5], "VBUS")
    v5 = esd_vias[5]
    for n in ("A4", "A9"):
        vx, vy = rel(pad_of(j1, n).GetPosition())[0], row_y + down * 1.41
        knee = (v5[0] + (0.5 if vx > v5[0] else -0.5), vy + down * (abs(vx - v5[0]) - 0.5))
        rt.track((vx, vy), knee, "VBUS", layer=pcbnew.In2_Cu, width=0.4)
        rt.track(knee, v5, "VBUS", layer=pcbnew.In2_Cu, width=0.4)

    # ---- pre-route: the module's interior GND pad (24) ----
    # Two of the E73's three GND pads are edge pads; the third is interior
    # and could only reach ground through the front pour's thermal spokes.
    # A via 0.8 mm inside it ties it to the In1 plane directly (B5). No
    # signal here uses an interior pad (circuit.py Z6), so this is the
    # only via under the module.
    u1 = fps["U1"]
    ux, uy = rel(u1.GetPosition())
    assert abs(u1.GetOrientationDegrees()) < 0.01, "route.py assumes U1 at rot 0"
    esc_pos = set()
    for pad in u1.Pads():
        if pad.GetNetname() != "GND":
            continue
        px, py = rel(pad.GetPosition())
        if abs(py - (uy - 4.91)) < 0.05 and abs(px - ux) < 4.0:        # interior top row
            rt.via((px, py + 0.80), "GND")
            rt.track((px, py), (px, py + 0.80), "GND", width=0.25)
        elif abs(px - (ux - 4.40)) < 0.05 and py > uy - 4.0:            # interior left column
            rt.via((px + 0.80, py), "GND")
            rt.track((px, py), (px + 0.80, py), "GND", width=0.25)

    # ---- pre-route: Tag-Connect escapes (B2), on J3's own layer ----
    # TC2030-IDC-NL drawing: nothing between the contact pads, no other
    # track within 0.5 mm of one. Each connected pad leaves perpendicular
    # to its row, locked, and a temporary keepout over the array keeps
    # freerouting out. J3 is on the BACK of this board.
    j3 = fps["J3"]
    j3_layer = pcbnew.B_Cu if j3.GetLayer() == pcbnew.B_Cu else pcbnew.F_Cu
    j3_pads = [p for p in j3.Pads() if p.GetNumber()]
    xs = [rel(p.GetPosition())[0] for p in j3_pads]
    ys = [rel(p.GetPosition())[1] for p in j3_pads]
    ymid = (min(ys) + max(ys)) / 2
    for p in j3_pads:
        if not p.GetNetname():
            continue
        px, py = rel(p.GetPosition())
        d = 1.0 if py > ymid else -1.0
        rt.track((px, py), (px, py + d * 1.2), p.GetNetname(), layer=j3_layer, width=0.15)
        if p.GetNetname() in ("3V3_SYS", "GND"):
            rt.via((px, py + d * 1.2), p.GetNetname())
    j3_box = [(min(xs) - 0.9, min(ys) - 0.9), (max(xs) + 0.9, min(ys) - 0.9),
              (max(xs) + 0.9, max(ys) + 0.9), (min(xs) - 0.9, max(ys) + 0.9)]

    # ---- inner planes ----
    inner = board_poly(design, 0.5)
    rt.zone(pcbnew.In1_Cu, "GND", inner, name="gnd_in1", full=True)
    rt.zone(pcbnew.In2_Cu, "3V3_SYS", inner, name="3v3_in2", full=True)

    # ---- permanent rule area: no F.Cu tracks under the E73 body ----
    # The module wants solid ground under it (manual sec 5), and a trace
    # threading between the interior pads is a trace nobody can inspect.
    # The band holding the interior pads themselves stays open for their
    # escape stubs (they can only leave through a via: the gaps between
    # the edge pads are 0.37 mm, narrower than one track + clearances).
    # (A no-tracks rule area over the whole In1 plane was tried for the
    # same reason and killed freerouting's plane fanout: 3 -> 45 unrouted.
    # relayer() below is what keeps In1 clean instead.)
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

    u1 = fps["U1"]
    ux, uy = rel(u1.GetPosition())
    # module frame (rot 0): interior pads (0.9 sq) at y=-4.91 and x=-4.40;
    # body to +10.99 in y and +-6.5 in x. The keep-out starts 0.85 mm
    # inside the pad edges: room for a 0.4 via + 0.127 clearance, which
    # is the only way an interior pad gets out.
    if "--no-u1-keepout" not in sys.argv:
        rule_area("u1_body_no_tracks", [pcbnew.F_Cu],
                  [(ux - 3.1, uy - 3.6), (ux + 5.5, uy - 3.6),
                   (ux + 5.5, uy + 10.0), (ux - 3.1, uy + 10.0)])
    # ---- permanent rule area: NOTHING under the antenna end ----
    # The ceramic antenna sits at the pad-free +y end of the module body
    # (footprint y 8.0..10.4, body end 10.99). No copper on any layer
    # under it and out to the board edge, and no vias: this cuts the two
    # inner planes and the outer pours too (DoNotAllowCopperPour). Depth
    # and side margin come from design.yaml; EBYTE's own drawing was not
    # retrievable, so this is the generic chip-antenna rule.
    ak = design["mcu"]["antenna_keepout_mm"]
    hh = design["board"]["height_mm"] / 2
    y_ant = uy + 10.99 - ak["depth"]
    rule_area("antenna_keepout", list(pcbnew.LSET.AllCuMask(design["board"]["layers"]).Seq()),
              [(ux - 6.5 - ak["margin"], y_ant), (ux + 6.5 + ak["margin"], y_ant),
               (ux + 6.5 + ak["margin"], hh + 1.0), (ux - 6.5 - ak["margin"], hh + 1.0)],
              tracks=True, vias=True, pour=True)
    # ---- Tag-Connect keepout, for freerouting only (see the pre-route) ----
    rule_area("j3_keepout_tmp", [j3_layer], j3_box, tracks=True, vias=True)

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
    pcbnew.SaveBoard(str(PCB), board)

    # ---- freerouting ----
    if not no_freeroute:
        dsn = ROOT / "out" / "bluebuzz.dsn"
        ses = ROOT / "out" / "bluebuzz.ses"
        ses.unlink(missing_ok=True)
        if not pcbnew.ExportSpecctraDSN(board, str(dsn)):
            print("DSN export failed")
            sys.exit(1)
        reorder_placement(dsn, attempt)
        cmd = ["java", "-jar", str(JAR), "-de", str(dsn), "-do", str(ses),
               "-mp", "40", "--gui.enabled=false"]
        r = None
        for fr_try in range(2):
            print("running freerouting…")
            try:
                r = subprocess.run(cmd, capture_output=True, text=True,
                                   timeout=900)
                break
            except subprocess.TimeoutExpired:
                print(f"freerouting timed out (try {fr_try + 1}); retrying")
        if not ses.exists():
            if r is not None:
                print(r.stdout[-3000:])
                print(r.stderr[-2000:])
            print("freerouting produced no SES")
            sys.exit(1)
        board = pcbnew.LoadBoard(str(PCB))
        if not pcbnew.ImportSpecctraSES(board, str(ses)):
            print("SES import failed")
            sys.exit(1)
        rt = Router(board, design)
        fps = {fp.GetReference(): fp for fp in board.GetFootprints()}
        board.BuildConnectivity()
        print(f"after freerouting: {board.GetConnectivity().GetUnconnectedCount(True)} unconnected, "
              f"{sum(1 for x in board.GetTracks() if not isinstance(x, pcbnew.PCB_VIA))} wires, "
              f"{sum(1 for x in board.GetTracks() if isinstance(x, pcbnew.PCB_VIA))} vias")
        for z in list(board.Zones()):
            if z.GetZoneName() in ("edge_keepout_tmp", "j3_keepout_tmp"):
                board.Delete(z)
        zl = 0
        for t in list(board.GetTracks()):
            if not isinstance(t, pcbnew.PCB_VIA) and t.GetLength() < 1000:   # < 1 um
                board.Delete(t)
                zl += 1
        if zl:
            print(f"removed {zl} zero-length wires")
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
        print(f"relayer: {left1} wires left on In1, {left2} on In2")
        if left1:
            # a wire on In1 is a slot in the ground plane. Take them out
            # (and whatever then dangles) and leave the connection open
            # for close_gaps / finish, which route on F.Cu, In2 and B.Cu.
            n = 0
            for tr in list(board.GetTracks()):
                if (not isinstance(tr, pcbnew.PCB_VIA) and tr.GetLayer() == pcbnew.In1_Cu
                        and not tr.IsLocked()):
                    board.Delete(tr)
                    n += 1
            peeled = prune_dangling(board)
            print(f"removed {n} In1 wires and {peeled} dangling wires for the finish stage")
        # Re-layering moves wires between layers, so a via that changed a
        # layer before it can be flat after: sweep again, or the board
        # ships with what DRC calls a dangling via.
        dropped, peeled = drop_flat_vias(board)
        if dropped:
            print(f"dropped {dropped} vias flattened by re-layering, "
                  f"{peeled} dangling wires")

    else:
        for z in list(board.Zones()):
            if z.GetZoneName() in ("edge_keepout_tmp", "j3_keepout_tmp"):
                board.Delete(z)

    # ---- same-net neighbour pins on the QFN charger ----
    # VBAT is pins 2+3 and VSYS pins 10+11, 0.25 wide at 0.5 pitch. One
    # 0.4 mm power trace reaches one pad; the neighbour is left hanging.
    # A pad-to-pad bridge lies entirely inside the pin row (nothing of
    # another net can legally be there), so it needs no gate.
    for a, b in ((2, 3), (10, 11)):
        pa, pb = pad_of(fps["U2"], a), pad_of(fps["U2"], b)
        rt.track(rel(pa.GetPosition()), rel(pb.GetPosition()), pa.GetNetname(),
                 pcbnew.F_Cu, width=0.25)

    # ---- ESD array middle-pin stubs (see the pre-route comment) ----
    obs = Obstacles(board)
    for n, net in ((2, "GND"), (5, "VBUS")):
        pad = pad_of(fps["U10"], n)
        px, py = rel(pad.GetPosition())
        vx, vy = esd_vias[n]
        # start 0.05 mm inside the pad's outer end
        half = to_mm(pad.GetBoundingBox().GetHeight()) / 2
        sy = py + (0.05 - half) * (1 if vy < py else -1)
        # 0.2 wide: 0.25 from the flanking USB pads (their class: 0.2)
        blk = obs.blocker((px, sy), (vx, vy), 0.10, net, pcbnew.F_Cu)
        if blk is None:
            rt.track((px, sy), (vx, vy), net, pcbnew.F_Cu, width=0.2)
        else:
            print(f"WARNING: U10 pin {n} stub blocked by routed copper: {blk}")

    # ---- outer pours + stitching (post-route: as DSN planes they stall
    #      freerouting, and it routes better with the outer layers open) ----
    outer = board_poly(design, 0.4)
    rt.zone(pcbnew.F_Cu, "GND", outer, name="gnd_front")
    rt.zone(pcbnew.B_Cu, "GND", outer, name="gnd_back")
    obs = Obstacles(board)      # rebuilt: the stubs are copper too
    n = add_stitching(board, rt, design, obs, pitch=2.5)
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
    tries = int(os.environ.get("ROUTE_TRIES", "3"))
    rc = 2
    for attempt in range(tries):
        if attempt:
            print(f"--- route attempt {attempt + 1}/{tries} ---")
        rc = main(attempt)
        if rc == 0:
            break
    sys.exit(rc)
