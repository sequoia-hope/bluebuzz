#!/usr/bin/env python3
"""Current-capacity check for the routed board (routing gate, phase 7).

Each current path -- source pads to load pads, through tracks, vias, pads
and pours -- is rated as a max-flow: every track carries what its width
allows on its layer, every via what its drill allows, pads and pours are
unlimited, and parallel routes add. The path passes when the max-flow
covers the design current (intent.md: 1 A continuous per motor channel,
the 1 A USB input limit, ...); the min cut is its narrowest neck and is
listed. Branches that carry no current (a sense divider, a cap's feed)
are not on a path and are not judged.

Ratings (design/stackup.md, IPC-2152 at 10 C rise): a track of width w
carries (w / 0.3)^(1/1.38) A on 1 oz outer copper (0.3 mm per amp, width
growing as I^1.38) and (w / 0.6)^(1/1.38) A on the 0.5 oz inner layers; a
via 0.8 A per 0.2 mm of drill, divided by stackup.md's 1.5 margin. A pad-
entry neck (<= 1.0 mm, an end on a pad) is not rated: a 0.5 mm-pitch pin
cannot take a wide track and the pad sinks its heat. Exits 1 on any FAIL.

    python3 scripts/check_current.py
"""
import math
import sys
from pathlib import Path

import networkx as nx
import pcbnew

ROOT = Path(__file__).resolve().parent.parent
PCB = ROOT / "out" / "bluebuzz-rm2.kicad_pcb"
T = pcbnew.ToMM
OUTER = ("F.Cu", "B.Cu")
VIA_A_PER_MM_DRILL = 0.8 / 0.2           # 0.2 mm drill ~0.8 A (stackup.md)
VIA_MARGIN = 1.5
W_1A = {True: 0.3, False: 0.6}           # mm for 1 A: outer 1 oz, inner 0.5 oz

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


def seg_dist(p, a, b):
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    return math.hypot(p[0] - ax - t * dx, p[1] - ay - t * dy)


def vec(p):
    return pcbnew.VECTOR2I(pcbnew.FromMM(p[0]), pcbnew.FromMM(p[1]))


class Net:
    """The copper of one net as a graph: tracks, vias, pads, zone fills."""

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
        for z in board.Zones():
            if z.GetNetname() != name or z.GetIsRuleArea():
                continue
            for l in z.GetLayerSet().Seq():
                if l in cu:
                    self.items.append(dict(kind="zone", name=z.GetZoneName(), layer=l,
                                           fill=z.GetFilledPolysList(l)))
        for i in range(len(self.items)):
            self.adj[i] = set()
        for i, p in enumerate(self.items):
            for j in range(i + 1, len(self.items)):
                if self.touch(p, self.items[j]):
                    self.adj[i].add(j)
                    self.adj[j].add(i)

    @staticmethod
    def on(item, layer):
        return layer in item["layers"] if "layers" in item else item["layer"] == layer

    def touch(self, p, q):
        if p["kind"] == "zone" and q["kind"] == "zone":
            return False
        if q["kind"] == "zone" or (p["kind"] == "track" and q["kind"] != "track"):
            p, q = q, p
        if p["kind"] == "zone":
            ly, fill = p["layer"], p["fill"]
            if not self.on(q, ly):
                return False
            if q["kind"] == "track":
                return any(fill.Contains(vec(e)) for e in (q["a"], q["b"]))
            return fill.Collide(vec(q["pos"]), pcbnew.FromMM(0.05))
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
        return pad["obj"].HitTest(vec(other["pos"]))

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
        """(amps, [items in the min cut]) from the src pads to the dst pads."""
        g = nx.DiGraph()
        for i in self.adj:
            c = self.capacity(i)
            g.add_edge(("in", i), ("out", i), **({} if c == math.inf else {"capacity": c}))
            for j in self.adj[i]:
                g.add_edge(("out", i), ("in", j))
        for i in src:
            g.add_edge("S", ("in", i))
        for i in dst:
            g.add_edge(("out", i), "T")
        amps, (reach, _) = nx.minimum_cut(g, "S", "T")
        cut = [i for i in self.adj if ("in", i) in reach and ("out", i) not in reach]
        return amps, cut


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
        cap, cut = g.maxflow(src, dst)
        tag = "ok  " if cap >= amps else "FAIL"
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
    print(f"\ncurrent check: {fails} FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
