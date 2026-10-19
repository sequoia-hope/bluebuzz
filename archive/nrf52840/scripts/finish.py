#!/usr/bin/env python3
"""Close the last unconnected hops with a real path search.

close_gaps draws a straight line or one L on a single layer, and on this
board the survivors are precisely the hops that need more: a bend or two,
a layer change, a via placed where there is room for one. This stage is a
tiny grid router for exactly those. It reads KiCad's DRC unconnected
list, then for each pair runs A* over a 0.1 mm lattice on the three
signal layers (F.Cu, In2.Cu, B.Cu), with layer changes through 0.4/0.2
vias. What it draws is locked, so the routing stages keep it.

Obstacles are modelled the hard way, as RECTANGLES for pads: the shared
`Obstacles` bounding-circle model is fine for close_gaps' straight shots
through open space, but an A* path hugs the blocked boundary by
construction, and a circle of radius max(w,h)/2 misses the corners of
every non-square pad -- the first version of this stage put a via in the
exposed pad's corner and shorted the motor line to ground. Rectangle
masks are exact, so a found path is a legal path.

Endpoints on a plane layer (a stranded fragment `relayer` parked on In3)
are deleted and the search retargeted at the net's nearest copper on a
usable layer.

Run as a build stage between `close` and `drc`.
"""
import json
import math
import shutil
import subprocess
import sys
from heapq import heappush, heappop
from pathlib import Path

import pcbnew

sys.path.insert(0, str(Path(__file__).resolve().parent))
from circuit import load_design  # noqa: E402
from route import CX, CY, Router, rel, smd_layer, to_mm  # noqa: E402
from close_gaps import REPORT, drc_unconnected, index_board  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PCB = ROOT / "out" / "bluebuzz.kicad_pcb"


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


def set_width(w):
    """The masks and the drawn wire follow the net's class width."""
    global TRACK_W, HALF, W_GAP
    TRACK_W = w
    HALF = w / 2
    # 0.2, not 0.127: KiCad applies the LARGER of two nets' class
    # clearances, and the USB class wants 0.2 from everything
    W_GAP = 0.2 + HALF

STEP = 0.1
LAYERS = None            # filled in main() from the stackup
VIA_COST = 18            # in grid steps: a via is worth ~1.8 mm of detour
TRACK_W = 0.15
HALF = TRACK_W / 2
W_GAP = 0.127 + HALF     # copper margin for a new wire, from the item edge
V_GAP = 0.2 + 0.2 + 0.01   # copper margin for a new via's centre (0.4 via, USB-class gap)


def grid_of(design, step=STEP):
    """The whole board, inset 0.35 mm (the antenna keepout and the other
    rule areas are masked by build_masks)."""
    b = design["board"]
    hw, hh = b["width_mm"] / 2, b["height_mm"] / 2
    x0, x1 = -hw + 0.35, hw - 0.35
    y0, y1 = -hh + 0.35, hh - 0.35
    nx = int((x1 - x0) / step) + 1
    ny = int((y1 - y0) / step) + 1
    return x0, y0, nx, ny, step


def build_masks(board, design, netcode, grid):
    """blocked[layer_index] and via_blocked, as sets of (ix, iy)."""
    x0, y0, nx, ny, STEP = grid
    b = design["board"]
    hw, hh = b["width_mm"] / 2, b["height_mm"] / 2
    blocked = [set() for _ in LAYERS]
    via_blocked = set()
    lidx = {ly: k for k, ly in enumerate(LAYERS)}

    def mark_rect(target, rx0, ry0, rx1, ry1):
        i0 = max(0, math.ceil((rx0 - x0) / STEP - 1e-9))
        i1 = min(nx - 1, math.floor((rx1 - x0) / STEP + 1e-9))
        j0 = max(0, math.ceil((ry0 - y0) / STEP - 1e-9))
        j1 = min(ny - 1, math.floor((ry1 - y0) / STEP + 1e-9))
        for i in range(i0, i1 + 1):
            for j in range(j0, j1 + 1):
                target.add((i, j))

    def mark_disk(target, cx, cy, r):
        i0 = max(0, int((cx - r - x0) / STEP))
        i1 = min(nx - 1, int((cx + r - x0) / STEP) + 1)
        j0 = max(0, int((cy - r - y0) / STEP))
        j1 = min(ny - 1, int((cy + r - y0) / STEP) + 1)
        r2 = r * r
        for i in range(i0, i1 + 1):
            dx = x0 + i * STEP - cx
            for j in range(j0, j1 + 1):
                dy = y0 + j * STEP - cy
                if dx * dx + dy * dy <= r2:
                    target.add((i, j))

    # pads: exact rectangles, per layer for SMD, everywhere for through
    for fp in board.GetFootprints():
        for pd in fp.Pads():
            if pd.GetNetCode() == netcode:
                continue
            bb = pd.GetBoundingBox()
            px0, py0 = to_mm(bb.GetLeft()) - CX, to_mm(bb.GetTop()) - CY
            px1, py1 = to_mm(bb.GetRight()) - CX, to_mm(bb.GetBottom()) - CY
            lc = pd.GetLocalClearance()
            extra = max(0.0, to_mm(int(lc)) - 0.127) if lc else 0.0
            w = W_GAP + extra
            if pd.GetAttribute() == pcbnew.PAD_ATTRIB_SMD:
                targets = [lidx[smd_layer(pd)]] \
                    if smd_layer(pd) in lidx else []
            else:
                targets = list(range(len(LAYERS)))
            for li in targets:
                mark_rect(blocked[li], px0 - w, py0 - w, px1 + w, py1 + w)
            v = V_GAP + extra
            mark_rect(via_blocked, px0 - v, py0 - v, px1 + v, py1 + v)

    # tracks and vias: sampled disks (they are thin; circles are honest)
    for t in board.GetTracks():
        same = t.GetNetCode() == netcode
        if isinstance(t, pcbnew.PCB_VIA):
            vx, vy = rel(t.GetPosition())
            rv = to_mm(t.GetWidth(pcbnew.F_Cu)) / 2     # 0.2, or 0.3 on a Power via
            rd = to_mm(t.GetDrillValue()) / 2
            if not same:
                for bl in blocked:
                    mark_disk(bl, vx, vy, rv + W_GAP)
            # hole-to-hole (0.2) applies to SAME-net vias too; other nets
            # need full copper clearance from this via's rim to ours
            mark_disk(via_blocked, vx, vy,
                      max(rd + 0.1 + 0.2, 0.45) if same else rv + 0.2 + 0.2 + 0.01)
            continue
        if same:
            continue
        a, b2 = rel(t.GetStart()), rel(t.GetEnd())
        hw2 = to_mm(t.GetWidth()) / 2
        L = math.hypot(b2[0] - a[0], b2[1] - a[1])
        n = max(1, int(L / (STEP / 2)))
        ly = t.GetLayer()
        li = lidx.get(ly)
        for k in range(n + 1):
            sx = a[0] + (b2[0] - a[0]) * k / n
            sy = a[1] + (b2[1] - a[1]) * k / n
            if li is not None:
                mark_disk(blocked[li], sx, sy, hw2 + W_GAP)
            mark_disk(via_blocked, sx, sy, hw2 + V_GAP)

    # rule areas (all rectangles on this board)
    for z in board.Zones():
        if not z.GetIsRuleArea():
            continue
        bb = z.GetBoundingBox()
        bx0, by0 = to_mm(bb.GetLeft()) - CX, to_mm(bb.GetTop()) - CY
        bx1, by1 = to_mm(bb.GetRight()) - CX, to_mm(bb.GetBottom()) - CY
        if z.GetDoNotAllowTracks():
            for ly in z.GetLayerSet().Seq():
                if ly in lidx:
                    mark_rect(blocked[lidx[ly]], bx0 - HALF, by0 - HALF,
                              bx1 + HALF, by1 + HALF)
        if z.GetDoNotAllowVias():
            mark_rect(via_blocked, bx0 - 0.225, by0 - 0.225,
                      bx1 + 0.225, by1 + 0.225)

    # a via wants 0.2 copper-to-edge on its 0.45 annulus: keep centres
    # 0.45 in from every edge (the wire grid is already inset 0.35)
    for i in range(nx):
        for j in range(ny):
            x, y = x0 + i * STEP, y0 + j * STEP
            if abs(y) > hh - 0.45 or abs(x) > hw - 0.45:
                via_blocked.add((i, j))
    return blocked, via_blocked


def free_anchor(pos, blocked_l, grid):
    """The anchor cell, or the nearest free cell within ~3 cells."""
    x0, y0, nx, ny, STEP = grid
    i = round((pos[0] - x0) / STEP)
    j = round((pos[1] - y0) / STEP)
    best = None
    for di in range(-3, 4):
        for dj in range(-3, 4):
            c = (i + di, j + dj)
            if not (0 <= c[0] < nx and 0 <= c[1] < ny):
                continue
            if c in blocked_l:
                continue
            d = di * di + dj * dj
            if best is None or d < best[0]:
                best = (d, c)
    return best[1] if best else None


def astar(starts, goals, blocked, via_blocked, grid):
    x0, y0, nx, ny, _step = grid
    goalset = set(goals)
    gx = sum(g[0][0] for g in goals) / len(goals)
    gy = sum(g[0][1] for g in goals) / len(goals)

    def h(c):
        return abs(c[0][0] - gx) + abs(c[0][1] - gy)

    openq = []
    came = {}
    dist = {}
    for s in starts:
        dist[s] = 0
        heappush(openq, (h(s), 0, s))
    seen = set()
    expansions = 0
    while openq:
        _, d, cur = heappop(openq)
        if cur in seen:
            continue
        seen.add(cur)
        expansions += 1
        if expansions > 1500000:
            return None
        if cur in goalset:
            path = [cur]
            while cur in came:
                cur = came[cur]
                path.append(cur)
            return path[::-1]
        (ci, cj), cl = cur
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ni, nj = ci + di, cj + dj
            if not (0 <= ni < nx and 0 <= nj < ny):
                continue
            nxt = ((ni, nj), cl)
            if (ni, nj) in blocked[cl] or nxt in seen:
                continue
            nd = d + 1
            if nd < dist.get(nxt, 1 << 30):
                dist[nxt] = nd
                came[nxt] = cur
                heappush(openq, (nd + h(nxt), nd, nxt))
        if (ci, cj) not in via_blocked:
            for nl in range(len(LAYERS)):
                if nl == cl:
                    continue
                nxt = ((ci, cj), nl)
                if (ci, cj) in blocked[nl] or nxt in seen:
                    continue
                nd = d + VIA_COST
                if nd < dist.get(nxt, 1 << 30):
                    dist[nxt] = nd
                    came[nxt] = cur
                    heappush(openq, (nd + h(nxt), nd, nxt))
    return None


def draw(rt, path, netname, grid, true_start, true_goal):
    x0, y0, _, _, STEP = grid

    def pt(cell):
        return (x0 + cell[0][0] * STEP, y0 + cell[0][1] * STEP)

    nodes = [path[0]]
    for k in range(1, len(path) - 1):
        a, b, c = path[k - 1], path[k], path[k + 1]
        turn = ((b[0][0] - a[0][0], b[0][1] - a[0][1])
                != (c[0][0] - b[0][0], c[0][1] - b[0][1]))
        if turn or a[1] != b[1] or b[1] != c[1]:
            nodes.append(b)
    nodes.append(path[-1])
    pts = [pt(n) for n in nodes]
    if true_start is not None:
        pts[0] = true_start
    if true_goal is not None:
        pts[-1] = true_goal
    vias = 0
    for k in range(len(nodes) - 1):
        a, b = nodes[k], nodes[k + 1]
        if a[1] != b[1]:
            rt.via(pts[k], netname)
            vias += 1
            continue
        if pts[k] == pts[k + 1]:
            continue
        rt.track(pts[k], pts[k + 1], netname, layer=LAYERS[a[1]],
                 width=TRACK_W)
    return vias


def endpoint(kind, obj, toward):
    lidx = {ly: k for k, ly in enumerate(LAYERS)}
    if kind == "pad":
        pos = rel(obj.GetPosition())
        if obj.GetAttribute() == pcbnew.PAD_ATTRIB_SMD:
            ls = [lidx[smd_layer(obj)]] if smd_layer(obj) in lidx else []
        else:
            ls = list(range(len(LAYERS)))
        return pos, ls
    if kind == "via":
        return rel(obj.GetPosition()), list(range(len(LAYERS)))
    a, b = rel(obj.GetStart()), rel(obj.GetEnd())
    da = math.hypot(a[0] - toward[0], a[1] - toward[1])
    db = math.hypot(b[0] - toward[0], b[1] - toward[1])
    ly = obj.GetLayer()
    return (a if da <= db else b), ([lidx[ly]] if ly in lidx else [])


def retarget(board, netcode, near):
    """The net's nearest joinable copper on a usable layer: a pad centre,
    a via, or a track end. For endpoints stranded on a plane layer."""
    lidx = {ly: k for k, ly in enumerate(LAYERS)}
    best = None

    def offer(pos, ls):
        nonlocal best
        d = math.hypot(pos[0] - near[0], pos[1] - near[1])
        if d < 0.2:
            return                     # that is the stranded thing itself
        if best is None or d < best[0]:
            best = (d, pos, ls)

    for fp in board.GetFootprints():
        for pd in fp.Pads():
            if pd.GetNetCode() != netcode:
                continue
            if pd.GetAttribute() == pcbnew.PAD_ATTRIB_SMD:
                if smd_layer(pd) in lidx:
                    offer(rel(pd.GetPosition()), [lidx[smd_layer(pd)]])
            else:
                offer(rel(pd.GetPosition()), list(range(len(LAYERS))))
    for t in board.GetTracks():
        if t.GetNetCode() != netcode:
            continue
        if isinstance(t, pcbnew.PCB_VIA):
            offer(rel(t.GetPosition()), list(range(len(LAYERS))))
        elif t.GetLayer() in lidx:
            li = [lidx[t.GetLayer()]]
            offer(rel(t.GetStart()), li)
            offer(rel(t.GetEnd()), li)
    return (best[1], best[2]) if best else (None, None)


def anchors_near(board, netcode, near, k=4, radius=4.0, within=None):
    """Up to k of the net's nearest other copper anchors: pad centres,
    vias, track ends. For retrying an entombed endpoint -- an In2 stub
    parked inside the optical via ban cannot reach any other layer,
    even though the net's own barrel sits a millimetre away with every
    layer open. (An alternate may belong to the far island, in which
    case the drawn copper merely parallels existing net copper; the
    next round's DRC is the arbiter either way.)"""
    lidx = {ly: kk for kk, ly in enumerate(LAYERS)}
    cands = []

    def offer(pos, ls, item):
        if within is not None and item.m_Uuid.AsString() not in within:
            return
        d = math.hypot(pos[0] - near[0], pos[1] - near[1])
        if 0.05 < d <= radius:
            cands.append((d, pos, ls, item))

    for fp in board.GetFootprints():
        for pd in fp.Pads():
            if pd.GetNetCode() != netcode:
                continue
            if pd.GetAttribute() == pcbnew.PAD_ATTRIB_SMD:
                if smd_layer(pd) in lidx:
                    offer(rel(pd.GetPosition()), [lidx[smd_layer(pd)]], pd)
            else:
                offer(rel(pd.GetPosition()), list(range(len(LAYERS))), pd)
    for t in board.GetTracks():
        if t.GetNetCode() != netcode:
            continue
        if isinstance(t, pcbnew.PCB_VIA):
            offer(rel(t.GetPosition()), list(range(len(LAYERS))), t)
        elif t.GetLayer() in lidx:
            li = [lidx[t.GetLayer()]]
            offer(rel(t.GetStart()), li, t)
            offer(rel(t.GetEnd()), li, t)
    cands.sort(key=lambda c: c[0])
    out, seen = [], set()
    for _d, pos, ls, item in cands:
        key = (round(pos[0], 2), round(pos[1], 2))
        if key in seen:
            continue
        seen.add(key)
        out.append((pos, ls, item))
        if len(out) >= k:
            break
    return out


def item_cluster(board, item):
    """Uuid set of the copper island `item` belongs to."""
    board.BuildConnectivity()
    conn = board.GetConnectivity()
    ids = {item.m_Uuid.AsString()}
    for o in list(conn.GetConnectedTracks(item)) \
            + list(conn.GetConnectedPads(item)):
        ids.add(o.m_Uuid.AsString())
    return ids


def finish_board(design, plane_layers):

    closed_total = 0
    for _round in range(3):
        board = pcbnew.LoadBoard(str(PCB))
        rt = Router(board, design)
        idx = index_board(board)
        pairs = drc_unconnected()
        if not pairs:
            break
        closed = 0
        for u in pairs:
            items = [idx.get(i["uuid"]) for i in u["items"]]
            if all(i is None for i in items):
                continue
            if any(i is None for i in items):
                # one end is a ZONE (a pour piece the pad could not reach):
                # aim the pad at the net's nearest other copper instead
                k1, o1 = next(i for i in items if i is not None)
                netname = o1.GetNetname()
                nc = o1.GetNetCode()
                set_width(class_width(netname, design))
                p1, l1 = endpoint(k1, o1, rel(o1.GetPosition()) if k1 != "track"
                                  else rel(o1.GetStart()))
                p2, l2 = retarget(board, nc, p1)
                if p2 is None:
                    continue
                k2, o2 = "pad", o1
            else:
                (k1, o1), (k2, o2) = items
                netname = o1.GetNetname()
                nc = o1.GetNetCode()
                set_width(class_width(netname, design))
                p2_guess = rel(o2.GetPosition()) if k2 != "track" else \
                    rel(o2.GetStart())
                p1, l1 = endpoint(k1, o1, p2_guess)
                p2, l2 = endpoint(k2, o2, p1)
            # an endpoint stranded on a plane layer: delete the fragment
            # (it is a slot in somebody's plane) and aim at the net's
            # nearest reachable copper instead
            for kk, oo, pp, ll, which in ((k1, o1, p1, l1, 1),
                                          (k2, o2, p2, l2, 2)):
                if kk == "track" and not ll \
                        and oo.GetLayer() in plane_layers \
                        and not oo.IsLocked():
                    other = p2 if which == 1 else p1
                    # the stranded thing is a RUN of segments, and the
                    # pair comes back each round if only one is deleted:
                    # remove every unlocked same-net wire on that layer
                    ly = oo.GetLayer()
                    for tt in list(board.GetTracks()):
                        if (not isinstance(tt, pcbnew.PCB_VIA)
                                and tt.GetNetCode() == nc
                                and tt.GetLayer() == ly
                                and not tt.IsLocked()):
                            board.Delete(tt)
                    np_, nl_ = retarget(board, nc, other)
                    if which == 1:
                        p1, l1 = np_, nl_
                    else:
                        p2, l2 = np_, nl_
            if not l1 or not l2:
                print(f"  unusable endpoints: {netname}")
                continue
            path = grid = None
            for step in (STEP, STEP / 2):
                grid = grid_of(design, step)
                blocked, via_blocked = build_masks(board, design, nc, grid)
                starts, goals = [], []
                for ls, pos, out in ((l1, p1, starts), (l2, p2, goals)):
                    for li in ls:
                        c = free_anchor(pos, blocked[li], grid)
                        if c is not None:
                            out.append((c, li))
                if not starts or not goals:
                    print(f"  no free anchor at {step}: {netname} {p1}")
                    continue
                path = astar(starts, goals, blocked, via_blocked, grid)
                if path is not None:
                    break
                print(f"  no path at {step}: {netname} "
                      f"({p1[0]:.2f},{p1[1]:.2f}) -> "
                      f"({p2[0]:.2f},{p2[1]:.2f})")
            if path is None:
                # the chosen endpoints may be entombed; retry from the
                # net's other copper anchors near each end
                grid = grid_of(design, STEP)
                blocked, via_blocked = build_masks(board, design, nc, grid)
                # alternates must stay on their own end's island, or
                # the A* happily "closes" the pair with a zero-length
                # path from an anchor to itself
                cl1 = item_cluster(board, o1)
                cl2 = item_cluster(board, o2)
                a1s = [(p1, l1)] + [
                    (q, m) for q, m, _it in
                    anchors_near(board, nc, p1, within=cl1)]
                a2s = [(p2, l2)] + [
                    (q, m) for q, m, _it in
                    anchors_near(board, nc, p2, within=cl2)]
                print(f"    retrying {netname} with {len(a1s)}x{len(a2s)} "
                      f"anchor pairs (cluster of {len(cl1)})")
                tried = 0
                for q1, m1 in a1s:
                    for q2, m2 in a2s:
                        if ((q1, q2) == (p1, p2)) or tried >= 8:
                            continue
                        if math.hypot(q1[0] - q2[0], q1[1] - q2[1]) < 0.3:
                            continue
                        starts = [(c, li) for li in m1
                                  if (c := free_anchor(
                                      q1, blocked[li], grid)) is not None]
                        goals = [(c, li) for li in m2
                                 if (c := free_anchor(
                                     q2, blocked[li], grid)) is not None]
                        if not starts or not goals:
                            continue
                        tried += 1
                        path = astar(starts, goals, blocked,
                                     via_blocked, grid)
                        if path is not None:
                            print(f"  alternate anchors won: {netname} "
                                  f"({q1[0]:.2f},{q1[1]:.2f}) -> "
                                  f"({q2[0]:.2f},{q2[1]:.2f})")
                            p1, p2 = q1, q2
                            break
                    if path is not None:
                        break
            if path is None:
                continue
            nv = draw(rt, path, netname, grid, p1, p2)
            print(f"  closed {netname}: ({p1[0]:.2f},{p1[1]:.2f}) -> "
                  f"({p2[0]:.2f},{p2[1]:.2f}), {nv} vias")
            closed += 1
        if closed:
            filler = pcbnew.ZONE_FILLER(board)
            filler.Fill(board.Zones())
            pcbnew.SaveBoard(str(PCB), board)
            closed_total += closed
        else:
            break
    board = pcbnew.LoadBoard(str(PCB))
    board.BuildConnectivity()
    left = board.GetConnectivity().GetUnconnectedCount(True)
    print(f"    closed {closed_total}; {left} unconnected left")
    return left


def board_score():
    """(error violations, unconnected) for the board on disk."""
    unc = drc_unconnected()
    viol = []
    if REPORT.exists():
        viol = json.loads(REPORT.read_text()).get("violations", [])
    return len(viol), len(unc)


def main():
    """Close what close_gaps left, with the grid router. In1 is the GND
    plane and never gets a wire; In2 carries the 3V3_SYS pour and may."""
    global LAYERS
    design = load_design()
    LAYERS = [pcbnew.F_Cu, pcbnew.In2_Cu, pcbnew.B_Cu]
    left = finish_board(design, {pcbnew.In1_Cu})
    viol, unc = board_score()
    print(f"finish: {unc} unconnected, {viol} DRC errors")
    REPORT.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
