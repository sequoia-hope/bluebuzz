#!/usr/bin/env python3
"""Current-capacity check for the routed board (routing gate, phase 7).

Each current path -- source pads to load pads, through tracks, vias, pads
and pours -- is rated as a max-flow: every track carries what its width
allows on its layer, every via what its drill allows, pads are unlimited,
and parallel routes add. The path passes when the max-flow covers the
design current (intent.md: 1 A continuous per motor channel, the 1 A USB
input limit, ...); the min cut is its narrowest neck and is listed.
Branches that carry no current (a sense divider, a cap's feed) are not on
a path and are not judged.

Ratings (design/stackup.md, IPC-2152 at 10 C rise): a track of width w
carries (w / 0.3)^(1/1.38) A on 1 oz outer copper (0.3 mm per amp, width
growing as I^1.38) and (w / 0.6)^(1/1.38) A on the 0.5 oz inner layers; a
via 0.8 A per 0.2 mm of drill, divided by stackup.md's 1.5 margin. A pad-
entry neck (<= 1.0 mm, an end on a pad) is not rated: a 0.5 mm-pitch pin
cannot take a wide track and the pad sinks its heat.

Pours are rated by their FILL, not taken as unlimited (the phase-7 review
found the In3 VSYS pour in two pieces joined by 0.24-0.32 mm necks, which
an unlimited pour hid). Each fill piece is rasterised into CELL x CELL
cells, each a node that carries CELL mm of copper width, 4-connected to
its neighbours; the min cut through a fill is then its narrowest neck.
Width is turned into amps linearly at the IPC-2152 rate for a 2 mm
conductor (1.19 A/mm inner, 1.98 A/mm outer), which under-rates a neck
narrower than 2 mm (a 0.3 mm inner neck: 0.36 A against IPC's 0.6 A) and
a 45-degree neck by up to 1/sqrt(2) (a 4-connected cut runs as a
staircase) -- conservative, which is the side a check should err on.
The pad-entry rule holds for fills as for tracks: fill within 1.0 mm of
a fine-pitch pad of the net (one no wider than 0.3 mm, a QFN pin) is not
rated -- copper cannot be wider than the gap between the pin's
neighbours there, and the pin sinks its heat.

Exits 1 on any FAIL.

    python3 scripts/check_current.py [board.kicad_pcb]
"""
import math
import sys
from collections import deque
from pathlib import Path

import numpy as np
import pcbnew
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import maximum_flow

ROOT = Path(__file__).resolve().parent.parent
PCB = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "out" / "bluebuzz-rm2.kicad_pcb"
T = pcbnew.ToMM
OUTER = ("F.Cu", "B.Cu")
VIA_A_PER_MM_DRILL = 0.8 / 0.2           # 0.2 mm drill ~0.8 A (stackup.md)
VIA_MARGIN = 1.5
W_1A = {True: 0.3, False: 0.6}           # mm for 1 A: outer 1 oz, inner 0.5 oz
CELL = 0.1                               # mm, pour raster
PAD_ENTRY = 1.0                          # mm: unrated fill around a fine-pitch pin
FINE_PAD = 0.3                           # mm: a pad this narrow is a fine-pitch pin
MA = 1000                                # capacities in mA (integers for the solver)
INF = 10 ** 7

# (net, sources, loads, design A, what) -- loads as "REF" (any pad of the net)
# or "REF.PAD". Currents: intent.md (the fitted motors draw 0.09-0.2 A; the
# design rating is 1 A continuous per channel).
FLOWS = [
    ("VBUS", ["J1"], ["U2.13"], 1.0, "USB-C VBUS pads to the charger's IN (ILIM 1 A)"),
    ("VBAT", ["U2.2", "U2.3"], ["J2.1"], 2.0, "charger BAT to the cell pad (both motors on battery)"),
    ("VSYS", ["U2.10", "U2.11"], ["J4.1"], 2.0, "charger OUT to the motors' common pad (2 x 1 A)"),
    ("VSYS", ["U2.10", "U2.11"], ["U7"], 0.35, "charger OUT to the RM2's VIN (TX peaks)"),
    ("VSYS", ["U2.10", "U2.11"], ["U3"], 0.25, "charger OUT to the LDO's IN"),
    ("MOTOR1_SW", ["Q1"], ["J4.2"], 1.0, "motor 1 low-side FET drain to its pad"),
    ("MOTOR1_SW", ["D3"], ["J4.2"], 1.0, "motor 1 flyback diode to its pad"),
    ("MOTOR2_SW", ["Q2"], ["J4.3"], 1.0, "motor 2 low-side FET drain to its pad"),
    ("MOTOR2_SW", ["D4"], ["J4.3"], 1.0, "motor 2 flyback diode to its pad"),
    ("3V3_SYS", ["U3"], ["U1"], 0.25, "LDO OUT to the RP2350's 3V3 (all its loads)"),
    ("3V3_SYS", ["U3"], ["U7"], 0.05, "LDO OUT to the RM2's VDDIO"),
]


def track_amps(w, outer):
    return (w / W_1A[outer]) ** (1 / 1.38)


def via_amps(drill):
    return VIA_A_PER_MM_DRILL * drill / VIA_MARGIN


def fill_amps_per_mm(outer):
    return track_amps(2.0, outer) / 2.0


def seg_dist(p, a, b):
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    return math.hypot(p[0] - ax - t * dx, p[1] - ay - t * dy)


def vec(p):
    return pcbnew.VECTOR2I(pcbnew.FromMM(float(p[0])), pcbnew.FromMM(float(p[1])))


class Net:
    """The copper of one net as a flow graph: tracks, vias and pads are
    items (one node pair each, carrying the item's rating); every zone fill
    is a raster of cells (one node pair per cell)."""

    def __init__(self, board, name):
        self.items, self.adj = [], {}
        cu = list(pcbnew.LSET.AllCuMask(board.GetCopperLayerCount()).Seq())
        for t in board.GetTracks():
            if t.GetNetname() != name:
                continue
            if t.Type() == pcbnew.PCB_VIA_T:
                p = t.GetPosition()
                self.items.append(dict(kind="via", pos=(T(p.x), T(p.y)), r=T(t.GetWidth(pcbnew.F_Cu)) / 2,
                                       drill=T(t.GetDrillValue()), layers=set(cu)))
            else:
                a, b = t.GetStart(), t.GetEnd()
                self.items.append(dict(kind="track", a=(T(a.x), T(a.y)), b=(T(b.x), T(b.y)),
                                       w=T(t.GetWidth()), layer=t.GetLayer(), len=T(t.GetLength())))
        for fp in board.GetFootprints():
            for pd in fp.Pads():
                if pd.GetNetname() == name:
                    c = pd.GetPosition()
                    self.items.append(dict(kind="pad", name=f"{fp.GetReference()}.{pd.GetNumber()}",
                                           ref=fp.GetReference(), pos=(T(c.x), T(c.y)), obj=pd,
                                           layers={l for l in cu if pd.IsOnLayer(l)}))
        n_items = len(self.items)
        for i in range(n_items):
            self.adj[i] = set()
        for i in range(n_items):
            for j in range(i + 1, n_items):
                if self.touch(self.items[i], self.items[j]):
                    self.adj[i].add(j)
                    self.adj[j].add(i)
        # pour cells: (layer, piece, ix, iy) -> cell index; cell centres
        self.cells, self.cell_at, self.cell_adj = [], {}, []
        self.cell_item = []                   # (cell, item) touching pairs
        for z in board.Zones():
            if z.GetNetname() != name or z.GetIsRuleArea():
                continue
            for ly in z.GetLayerSet().Seq():
                if ly in cu:
                    self.raster(z, ly)

    def raster(self, z, ly):
        fill = z.GetFilledPolysList(ly)
        outer = pcbnew.LayerName(ly) in OUTER
        for k in range(fill.OutlineCount()):
            chain = fill.COutline(k)
            bb = chain.BBox()
            x0, y0 = T(bb.GetLeft()), T(bb.GetTop())
            nx, ny = int(T(bb.GetWidth()) / CELL) + 1, int(T(bb.GetHeight()) / CELL) + 1
            mine = {}
            for ix in range(nx):
                for iy in range(ny):
                    c = (x0 + (ix + 0.5) * CELL, y0 + (iy + 0.5) * CELL)
                    if chain.PointInside(vec(c)):
                        key = (ly, z.GetZoneName(), k, ix, iy)
                        mine[(ix, iy)] = len(self.cells)
                        self.cell_at[key] = len(self.cells)
                        self.cells.append(dict(pos=c, layer=ly, outer=outer, zone=z.GetZoneName(),
                                               entry=self.near_fine_pad(c, ly)))
            for (ix, iy), ci in mine.items():
                for nb in ((ix + 1, iy), (ix, iy + 1)):
                    if nb in mine:
                        self.cell_adj.append((ci, mine[nb]))
            # which items touch which cells (item on this layer, cell centre
            # inside the item's copper)
            idx = np.array([[c[0], c[1]] for c in (self.cells[ci]["pos"] for ci in mine.values())]) \
                if mine else np.zeros((0, 2))
            ids = list(mine.values())
            for i, it in enumerate(self.items):
                if not self.on(it, ly) or not len(ids):
                    continue
                if it["kind"] == "track":
                    a, b = np.array(it["a"]), np.array(it["b"])
                    d = b - a
                    L2 = float(d @ d)
                    t = np.zeros(len(ids)) if L2 == 0 else np.clip(((idx - a) @ d) / L2, 0, 1)
                    dist = np.hypot(*(idx - a - np.outer(t, d)).T)
                    hit = np.nonzero(dist <= it["w"] / 2 + CELL / 2)[0]
                elif it["kind"] == "via":
                    hit = np.nonzero(np.hypot(*(idx - np.array(it["pos"])).T) <= it["r"] + CELL / 2)[0]
                else:
                    bbp = it["obj"].GetBoundingBox()
                    px0, py0, px1, py1 = T(bbp.GetLeft()), T(bbp.GetTop()), T(bbp.GetRight()), T(bbp.GetBottom())
                    near = np.nonzero((idx[:, 0] > px0 - CELL) & (idx[:, 0] < px1 + CELL)
                                      & (idx[:, 1] > py0 - CELL) & (idx[:, 1] < py1 + CELL))[0]
                    hit = [h for h in near if it["obj"].HitTest(vec(idx[h]), pcbnew.FromMM(CELL / 2))]
                for h in hit:
                    self.cell_item.append((ids[h], i))

    def near_fine_pad(self, c, ly):
        if not hasattr(self, "_fine"):
            self._fine = []
            for it in self.items:
                if it["kind"] == "pad":
                    sz = it["obj"].GetSize()
                    if min(T(sz.x), T(sz.y)) <= FINE_PAD:
                        bb = it["obj"].GetBoundingBox()
                        self._fine.append((it, T(bb.GetLeft()), T(bb.GetTop()), T(bb.GetRight()), T(bb.GetBottom())))
        for it, x0, y0, x1, y1 in self._fine:
            if self.on(it, ly) and math.hypot(max(x0 - c[0], 0, c[0] - x1), max(y0 - c[1], 0, c[1] - y1)) <= PAD_ENTRY:
                return True
        return False

    @staticmethod
    def on(item, layer):
        return layer in item["layers"] if "layers" in item else item["layer"] == layer

    def touch(self, p, q):
        if p["kind"] == "track" and q["kind"] != "track":
            p, q = q, p
        if p["kind"] == "track":                      # track - track
            if q["layer"] != p["layer"]:
                return False
            r = max(p["w"], q["w"]) / 2 + 1e-3
            return (min(seg_dist(e, q["a"], q["b"]) for e in (p["a"], p["b"])) <= r
                    or min(seg_dist(e, p["a"], p["b"]) for e in (q["a"], q["b"])) <= r)
        # p is a via or a pad, q is a via, pad or track
        if q["kind"] == "track":
            if not self.on(p, q["layer"]):
                return False
            if p["kind"] == "via":
                return min(seg_dist(p["pos"], q["a"], q["b"]), *(math.hypot(e[0] - p["pos"][0], e[1] - p["pos"][1])
                                                                  for e in (q["a"], q["b"]))) <= p["r"] + 1e-3
            return any(p["obj"].HitTest(vec(e)) for e in (q["a"], q["b"]))
        if not (p["layers"] & q["layers"]):
            return False
        if p["kind"] == "via" and q["kind"] == "via":
            return math.hypot(p["pos"][0] - q["pos"][0], p["pos"][1] - q["pos"][1]) <= p["r"] + q["r"]
        pad, other = (p, q) if p["kind"] == "pad" else (q, p)
        # a via touches a pad when its copper overlaps it, not only when its
        # centre is inside (the VBUS via beside C10's pad)
        reach = pcbnew.FromMM(other["r"]) if other["kind"] == "via" else 0
        return pad["obj"].HitTest(vec(other["pos"]), reach)

    def capacity(self, i):
        it = self.items[i]
        if it["kind"] == "via":
            return via_amps(it["drill"])
        if it["kind"] != "track":
            return math.inf
        if it["len"] <= 1.0 and any(self.items[j]["kind"] == "pad" for j in self.adj[i]):
            return math.inf                  # pad-entry neck
        return track_amps(it["w"], pcbnew.LayerName(it["layer"]) in OUTER)

    def maxflow(self, src, dst):
        """(amps, [items in the min cut], [cells in the min cut]) from the src
        pads to the dst pads. Node k: item i -> in 2i, out 2i+1; cell c ->
        in 2(n+c), out 2(n+c)+1; then S, T."""
        n, m = len(self.items), len(self.cells)
        S, Tn = 2 * (n + m), 2 * (n + m) + 1
        rows, cols, caps = [], [], []

        def edge(a, b, c):
            rows.append(a)
            cols.append(b)
            caps.append(c)

        def amps(c):
            return INF if c == math.inf else int(c * MA)
        for i in range(n):
            edge(2 * i, 2 * i + 1, amps(self.capacity(i)))
            for j in self.adj[i]:
                edge(2 * i + 1, 2 * j, INF)
        for c, cell in enumerate(self.cells):
            k = 2 * (n + c)
            edge(k, k + 1, INF if cell["entry"] else int(CELL * fill_amps_per_mm(cell["outer"]) * MA))
        for a, b in self.cell_adj:
            ka, kb = 2 * (n + a), 2 * (n + b)
            edge(ka + 1, kb, INF)
            edge(kb + 1, ka, INF)
        for c, i in self.cell_item:
            kc = 2 * (n + c)
            edge(kc + 1, 2 * i, INF)
            edge(2 * i + 1, kc, INF)
        for i in src:
            edge(S, 2 * i, INF)
        for i in dst:
            edge(2 * i + 1, Tn, INF)
        N = Tn + 1
        C = coo_matrix((np.array(caps, dtype=np.int64), (rows, cols)), shape=(N, N)).tocsr()
        C.sum_duplicates()
        C = C.astype(np.int32)
        res = maximum_flow(C, S, Tn, method="dinic")
        R = (C - res.flow).tocsr()
        seen = np.zeros(N, bool)
        seen[S] = True
        q = deque([S])
        while q:
            u = q.popleft()
            for p in range(R.indptr[u], R.indptr[u + 1]):
                v = R.indices[p]
                if R.data[p] > 0 and not seen[v]:
                    seen[v] = True
                    q.append(v)
        cut = [i for i in range(n) if seen[2 * i] and not seen[2 * i + 1]]
        cut_cells = [c for c in range(m) if seen[2 * (n + c)] and not seen[2 * (n + c) + 1]]
        return res.flow_value / MA, cut, cut_cells


def pick(net, specs):
    out = set()
    for i, it in enumerate(net.items):
        if it["kind"] != "pad":
            continue
        for s in specs:
            if it["name"] == s or ("." not in s and it["ref"] == s):
                out.add(i)
    return out


def main():
    board = pcbnew.LoadBoard(str(PCB))
    nets, fails = {}, 0
    for net, srcs, loads, amps, what in FLOWS:
        g = nets.setdefault(net, Net(board, net))
        src, dst = pick(g, srcs), pick(g, loads)
        assert src and dst, (net, srcs, loads)
        cap, cut, cut_cells = g.maxflow(src, dst)
        tag = "ok  " if cap >= amps - 1e-6 else "FAIL"
        fails += tag == "FAIL"
        print(f"\n{tag}  {net}: {what} -- carries {cap:.2f} A, needs {amps:.2f} A")
        for i in cut:
            it = g.items[i]
            if it["kind"] == "via":
                print(f"        neck: via drill {it['drill']:.2f} at ({it['pos'][0]:.2f},{it['pos'][1]:.2f}), "
                      f"{via_amps(it['drill']):.2f} A")
            else:
                ly = pcbnew.LayerName(it["layer"])
                print(f"        neck: {ly} {it['w']:.2f} mm x {it['len']:.2f} mm "
                      f"({it['a'][0]:.2f},{it['a'][1]:.2f})-({it['b'][0]:.2f},{it['b'][1]:.2f}), "
                      f"{track_amps(it['w'], ly in OUTER):.2f} A")
        by_zone = {}
        for c in cut_cells:
            by_zone.setdefault((g.cells[c]["zone"], g.cells[c]["layer"]), []).append(g.cells[c])
        for (zn, ly), cs in by_zone.items():
            xs, ys = [c["pos"][0] for c in cs], [c["pos"][1] for c in cs]
            a = len(cs) * CELL * fill_amps_per_mm(cs[0]["outer"])
            print(f"        neck: {pcbnew.LayerName(ly)} fill '{zn}' {len(cs) * CELL:.2f} mm of cut "
                  f"around ({min(xs):.2f},{min(ys):.2f})-({max(xs):.2f},{max(ys):.2f}), {a:.2f} A")
    print(f"\ncurrent check: {fails} FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
