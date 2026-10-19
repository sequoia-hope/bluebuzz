#!/usr/bin/env python3
"""Close the last few connections freerouting abandons.

On a board this dense freerouting stops when its score stops improving,
and what it leaves behind is not a routing failure but a handful of short
hops: a track that ends 0.5 mm off its pad, a pad whose neighbour on the
same net was never joined to it. This stage reads KiCad's own DRC report
-- which gives a position and a UUID for both ends of every missing
connection -- and draws each one, but only where it can prove the path is
clear of everything else on the board.

It is not a router. It draws a straight line or a single L, on one layer
or across a via, and if the geometry says that path is blocked it says so
and leaves the connection open for a human. Anything it does draw is
locked, so a later routing pass keeps it.

Run as a build stage between `route` and `drc`.
"""
import json
import math
import subprocess
import sys
from pathlib import Path

import pcbnew

sys.path.insert(0, str(Path(__file__).resolve().parent))
from circuit import load_design  # noqa: E402
from route import CX, CY, Obstacles, Router, mm, rel, smd_layer, to_mm  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PCB = ROOT / "out" / "bluebuzz.kicad_pcb"
REPORT = ROOT / "out" / "drc_gaps.json"


def class_width(netname, design):
    """Track width for a net from the project's netclass patterns (gen_project):
    power nets get 0.4 mm, everything else the default."""
    import fnmatch
    from gen_project import DEFAULT
    ns = DEFAULT["net_settings"]
    classes = {c["name"]: c["track_width"] for c in ns["classes"]}
    for pat in ns["netclass_patterns"]:
        if fnmatch.fnmatchcase(netname, pat["pattern"]):
            return classes[pat["netclass"]]
    return design["jlcpcb"]["default_track_mm"]


def drc_unconnected():
    subprocess.run(
        ["kicad-cli", "pcb", "drc", "--format", "json", "--severity-error",
         "-o", str(REPORT), str(PCB)], capture_output=True, text=True)
    if not REPORT.exists():
        return []
    return json.loads(REPORT.read_text()).get("unconnected_items", [])


def index_board(board):
    """{uuid: (kind, object)} for everything a connection can end on."""
    idx = {}
    for t in board.GetTracks():
        kind = "via" if isinstance(t, pcbnew.PCB_VIA) else "track"
        idx[t.m_Uuid.AsString()] = (kind, t)
    for fp in board.GetFootprints():
        for p in fp.Pads():
            idx[p.m_Uuid.AsString()] = ("pad", p)
    return idx


def anchor(kind, obj, toward):
    """Where to attach on this item, and which layers it can be reached on.

    A pad is its centre; a track is whichever end is nearer the other item
    (its middle is already carrying copper of its own net)."""
    if kind == "pad":
        pos = rel(obj.GetPosition())
        if obj.GetAttribute() == pcbnew.PAD_ATTRIB_SMD:
            # GetLayer() answers F.Cu even for back-side pads (route.py
            # smd_layer says why); drawing the closing hop on the wrong
            # side of the board is worse than not drawing it
            layers = [smd_layer(obj)]
        else:
            layers = [pcbnew.F_Cu, pcbnew.B_Cu]
        return pos, layers, obj.GetNetname()
    if kind == "via":
        return rel(obj.GetPosition()), [pcbnew.F_Cu, pcbnew.B_Cu], obj.GetNetname()
    a, b = rel(obj.GetStart()), rel(obj.GetEnd())
    da = math.hypot(a[0] - toward[0], a[1] - toward[1])
    db = math.hypot(b[0] - toward[0], b[1] - toward[1])
    return (a if da <= db else b), [obj.GetLayer()], obj.GetNetname()


def paths(p, q):
    """Straight, or the two L's between p and q."""
    if abs(p[0] - q[0]) < 1e-6 or abs(p[1] - q[1]) < 1e-6:
        return [[p, q]]
    return [[p, (q[0], p[1]), q], [p, (p[0], q[1]), q]]


def try_path(obs, way, halfw, net, layer, gap):
    for a, b in zip(way, way[1:]):
        if not obs.clear_seg(a, b, halfw, net, layer, gap):
            return False
    return True


def main():
    design = load_design()
    j = design["jlcpcb"]
    gaps = drc_unconnected()
    if not gaps:
        print("nothing to close: 0 unconnected items")
        return 0
    board = pcbnew.LoadBoard(str(PCB))
    rt = Router(board, design)
    idx = index_board(board)
    obs = Obstacles(board)
    width = j["default_track_mm"]
    halfw = width / 2
    gap = 0.2       # the USB class's clearance; KiCad applies the larger of two nets'

    drawn, blocked = 0, []
    for g in gaps:
        items = g.get("items", [])
        if len(items) != 2:
            continue
        ends = []
        for it in items:
            e = idx.get(it.get("uuid"))
            if e is None:
                break
            pos = (it["pos"]["x"] - CX, it["pos"]["y"] - CY)
            ends.append((e, pos))
        if len(ends) != 2:
            blocked.append(f"{items[0]['description']}: item not on the board")
            continue
        (ka, oa), pa_hint = ends[0]
        (kb, ob), pb_hint = ends[1]
        pa, la, net = anchor(ka, oa, pb_hint)
        pb, lb, _ = anchor(kb, ob, pa_hint)
        what = (f"{net}: {items[0]['description'][:36]} -> "
                f"{items[1]['description'][:36]}")
        width = class_width(net, design)
        halfw = width / 2

        # same layer: straight or one L, whichever is clear
        done = False
        for layer in [ly for ly in la if ly in lb]:
            for way in paths(pa, pb):
                if try_path(obs, way, halfw, net, layer, gap):
                    for a, b in zip(way, way[1:]):
                        rt.track(a, b, net, layer=layer, width=width)
                        obs.items.append(
                            ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2,
                             math.hypot(b[0] - a[0], b[1] - a[1]) / 2 + halfw,
                             rt.net(net).GetNetCode(), layer, "closer"))
                    drawn += 1
                    done = True
                    break
            if done:
                break
        if done:
            continue

        # different layers, or blocked on the shared one: go out of the
        # first end on its layer, drop a via clear of both, come back on
        # the second's layer
        for lya in la:
            for lyb in lb:
                for corner in ((pb[0], pa[1]), (pa[0], pb[1])):
                    if not obs.clear(corner[0], corner[1],
                                     j["via_diameter_mm"] / 2, gap):
                        continue
                    if try_path(obs, [pa, corner], halfw, net, lya, gap) \
                            and try_path(obs, [corner, pb], halfw, net, lyb,
                                         gap):
                        rt.track(pa, corner, net, layer=lya, width=width)
                        rt.via(corner, net)
                        rt.track(corner, pb, net, layer=lyb, width=width)
                        obs.items.append((corner[0], corner[1],
                                          j["via_diameter_mm"] / 2,
                                          rt.net(net).GetNetCode(), None,
                                          "closer via"))
                        drawn += 1
                        done = True
                        break
                if done:
                    break
            if done:
                break
        if not done:
            blocked.append(what)

    if drawn:
        filler = pcbnew.ZONE_FILLER(board)
        filler.Fill(board.Zones())
        pcbnew.SaveBoard(str(PCB), board)
        board.BuildConnectivity()
    print(f"closed {drawn} of {len(gaps)} gaps; "
          f"{board.GetConnectivity().GetUnconnectedCount(True)} unconnected left")
    for b in blocked:
        print("  could not close: " + b)
    REPORT.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
