#!/usr/bin/env python3
"""Board art: dripping fluid, on the back silkscreen (user, 2026-10-18).

A pool of fluid along the top of the art zone with five drips hanging from
it, each ending in a round bead, two of them shedding a falling droplet.
Drawn as filled silkscreen polygons, so the fab prints solid shapes rather
than outlines (JLC's minimum silk line is 0.15 mm; every feature here is
wider than that).

The art zone (design/brief.md, item 9) is the free strip of the back on the
left half as seen from the front: x -13.2..-5.2, y -10..9 mm from the board
centre -- clear of the corner and centre pressure sensors and their caps,
the BAT/SWD/MOT/test pad rows, the debug-probe footprint, the USB-C's shell
pads and SW1's pegs. Coordinates are front-view (place.py's frame); the
back is seen mirrored, which a drip pattern does not mind.
"""
import math

import pcbnew

CX, CY = 100.0, 100.0
ZONE = (-13.2, -10.0, -5.2, 9.0)          # x0, y0, x1, y1
POOL_TOP, POOL_BOTTOM = -10.0, -8.6
# (centre x, neck half-width, length below the pool, bead radius, droplet?)
DRIPS = [
    (-12.25, 0.28, 3.2, 0.42, False),
    (-10.75, 0.33, 9.6, 0.55, True),
    (-9.15, 0.30, 5.4, 0.48, False),
    (-7.55, 0.36, 13.0, 0.62, True),
    (-6.05, 0.28, 6.6, 0.45, False),
]
LINE = 0.1


def _arc(cx, cy, r, t0, t1, n=14):
    """Points on a circle (y down), angle t0 -> t1 in degrees."""
    return [(cx + r * math.cos(math.radians(t0 + (t1 - t0) * k / n)),
             cy + r * math.sin(math.radians(t0 + (t1 - t0) * k / n))) for k in range(n + 1)]


def pool_and_drips():
    """One outline: the wavy pool surface right-to-left along the top, then
    left-to-right along the bottom, dropping down each drip and back up."""
    x0, _, x1, _ = ZONE
    pts = []
    # top surface, a gentle wave, right to left
    n = 40
    for k in range(n + 1):
        x = x1 - (x1 - x0) * k / n
        pts.append((x, POOL_TOP + 0.22 * math.sin(k / n * 3 * math.pi)))
    # bottom edge, left to right, with the drips
    pts.append((x0, POOL_BOTTOM))
    for cx, w, length, r, _ in DRIPS:
        ye = POOL_BOTTOM + length                 # bottom of the bead
        # a curved neck flaring into the pool
        pts += [(cx - w - 0.45, POOL_BOTTOM), (cx - w - 0.15, POOL_BOTTOM + 0.25),
                (cx - w, POOL_BOTTOM + 0.7)]
        pts.append((cx - w, ye - 2.0 * r))        # down the left side
        pts += _arc(cx, ye - r, r, 200, -20)      # round the bead: left, bottom, right (y down)
        pts.append((cx + w, ye - 2.0 * r))        # up the right side
        pts += [(cx + w, POOL_BOTTOM + 0.7), (cx + w + 0.15, POOL_BOTTOM + 0.25),
                (cx + w + 0.45, POOL_BOTTOM)]
    pts.append((x1, POOL_BOTTOM))
    return pts


def droplets():
    """A falling teardrop below each drip that sheds one."""
    out = []
    for cx, _, length, r, drop in DRIPS:
        if not drop:
            continue
        top = POOL_BOTTOM + length + 0.9
        rr = r * 0.8
        cy = top + 2.2 * rr
        pts = [(cx, top)] + _arc(cx, cy, rr, -40, 220)
        out.append(pts)
    return out


def _poly(board, pts, layer):
    # Built as a SHAPE_LINE_CHAIN -> SHAPE_POLY_SET held in Python for the
    # whole call: SetPolyPoints() with a list of temporary VECTOR2I
    # segfaulted intermittently inside _pcbnew (KiCad 9.0.8).
    chain = pcbnew.SHAPE_LINE_CHAIN()
    for x, y in pts:
        chain.Append(int(pcbnew.FromMM(CX + x)), int(pcbnew.FromMM(CY + y)))
    chain.SetClosed(True)
    poly = pcbnew.SHAPE_POLY_SET()
    poly.AddOutline(chain)
    shape = pcbnew.PCB_SHAPE(board)
    shape.SetShape(pcbnew.SHAPE_T_POLY)
    shape.SetPolyShape(poly)
    shape.SetLayer(layer)
    shape.SetWidth(pcbnew.FromMM(LINE))
    shape.SetFilled(True)
    board.Add(shape)
    return shape


def add_art(board):
    """Remove any earlier art (tagged by layer and zone) and draw it fresh."""
    x0, y0, x1, y1 = ZONE
    for d in list(board.GetDrawings()):
        if d.GetLayer() == pcbnew.B_SilkS and isinstance(d, pcbnew.PCB_SHAPE) \
                and d.GetShape() == pcbnew.SHAPE_T_POLY:
            bb = d.GetBoundingBox()
            if x0 - 0.5 <= pcbnew.ToMM(bb.GetLeft()) - CX and pcbnew.ToMM(bb.GetRight()) - CX <= x1 + 0.5:
                board.Delete(d)                # Remove() left a dangling proxy; place.py then crashed (KiCad 9.0.8)
    n = 0
    _poly(board, pool_and_drips(), pcbnew.B_SilkS)
    n += 1
    for pts in droplets():
        _poly(board, pts, pcbnew.B_SilkS)
        n += 1
    return n
