#!/usr/bin/env python3
"""Generate a readable, hand-laid-out .kicad_sch from circuit.py.

The drawing engine (the Sch class below) is lifted unchanged from the
simple_earring board, which is where it was written and proven. What is
specific to this board is everything after it: the IC pin maps, the block
functions, and build_sheet().

The idea is the same one that board uses. The schematic is generated, but
it is drawn the way a person would draw it rather than dumped as a grid of
boxes with a label on every pin:

  * Real symbols. R/C/L/crystal/LED/switch use the standard shapes; ICs
    are boxes whose pins are placed by FUNCTION -- power on top, ground on
    the bottom, a bus on the side that faces the part it talks to.
  * Functional blocks. Each of the design document's eight blocks is drawn
    inside a dashed frame with a title, and the parts inside it are
    DIRECTLY WIRED to each other.
  * Rails are power symbols (GND / VBUS / VSYS / VBAT / 3V3_SYS /
    3V3_GPS / V_BCKP), so power stays grouped instead of smeared across
    the sheet as text.
  * Labels only where a wire would otherwise have to travel: block-to-block
    signals (the SPI bus, the GPS UART, the GPIO control lines).

Layout is hand-authored -- positions are code, derived from each symbol's
real pin coordinates -- but the CONTENT is not: every net comes from
circuit.py, every pin is asserted against it, and the finished sheet is
re-imported through `kicad-cli sch export netlist` and diffed against
circuit.py. If the netlist changes and the layout does not, the build fails
loudly instead of drawing a lie.

Five checks keep the drawing honest:
  - every pin in circuit.py must be drawn and wired (Book);
  - wires may only meet at declared junctions, and may not cross;
  - block frames may not overlap, and the paper is cut to fit them;
  - no reference, value or note may land on a wire or on other text;
  - the exported netlist must equal circuit.py's, net for net.

Output: out/bluebuzz.kicad_sch (+ .svg/.pdf).
Regenerate with `python3 build.py --only schematic`.
"""
import math
import os
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from circuit import E73, ROLE, build_circuit, load_design  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out" / "bluebuzz.kicad_sch"

# Deterministic UUIDs: same circuit -> same file, so git diffs show real
# changes instead of a fresh set of random ids every build.
NS = uuid.UUID("b1c7e4a2-5d38-4f61-9a0c-7e2d4b8f3a16")
SHEET_UUID = uuid.uuid5(NS, "sheet")

# Footprints are written exactly as bom/parts.yaml gives them: every one
# is already "Library:Name", either a KiCad stock library or the project's
# own "bluebuzz" nickname for library/parts.pretty/.
# KiCad's schematic CONNECTION grid is 50 mil, half the 100 mil pin
# pitch: a wire end has to land on it or it connects to nothing.
CONN_GRID = 1.27
GRID = 2.54            # 100mil pin pitch
PINLEN = 2.54          # pin stub length on generated box symbols
# The sheet is cut to fit the drawing rather than the drawing padded out to
# a standard size: this is a review document read on screen, and a page with
# 30% empty margin just means everything is 30% smaller when you zoom to fit.
MARGIN = 12.0          # KiCad draws its border ~10mm in from the paper edge
TITLE_BLOCK = (120.0, 40.0)   # keep the bottom-right corner clear

FONT = "(effects (font (size 1.27 1.27)))"


def uid(*parts):
    return str(uuid.uuid5(NS, "/".join(str(p) for p in parts)))


def esc(s):
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


def q(v):
    """Round to the 1.27mm half-grid the whole sheet lives on."""
    return round(v, 4)


def eff(size=1.27, bold=False, just=None, hide=False, rot=None):
    b = " (bold yes)" if bold else ""
    # KiCad only knows left/right/top/bottom/mirror; horizontal centring is
    # the default, so "center" is spelled by leaving the token out.
    if just:
        just = " ".join(t for t in just.split() if t != "center")
    j = f" (justify {just})" if just else ""
    h = " (hide yes)" if hide else ""
    return f"(effects (font (size {size} {size}){b}){j}{h})"


# ---------------------------------------------------------------------------
# symbol geometry
# ---------------------------------------------------------------------------
def xf(px, py, rot):
    """Library coords (+y up) -> sheet offset (+y down) for a placed symbol."""
    x, y = px, -py
    if rot == 0:
        return x, y
    if rot == 90:
        return y, -x
    if rot == 180:
        return -x, -y
    if rot == 270:
        return -y, x
    raise ValueError(f"rotation {rot} not supported")


class SymDef:
    def __init__(self, name, style, pins, extent, sexpr, tb=(False, False)):
        self.name = name        # lib_id suffix
        self.style = style      # box | passive | power | point
        self.pins = pins        # num -> (px, py) connection anchor
        self.extent = extent    # (half_w, half_h) including pin stubs
        self.sexpr = sexpr
        self.has_top, self.has_bot = tb   # pins on the top / bottom edge


class Sch:
    def __init__(self):
        self.defs = {}          # name -> SymDef
        self.body = []
        self.refs = set()
        self.pwr_n = 0
        self.frames = []        # (x0, y0, x1, y1, title)
        self.head = []          # header text, outside every block frame
        self.wires = []         # (a, b) — split at junctions on render
        self.jpts = set()
        self.texts = []         # (x0, y0, x1, y1, what) for check_text()
        self._bb = None
        self.page = None        # (w, h), measured in render()

    # -- library -------------------------------------------------------
    def _emit_def(self, name, value, style, pins, gfx, extent,
                  hide_numbers=False, hide_names=False, power=False,
                  ref_prefix="U", name_offset=0.508, tb=(False, False)):
        """pins: list of (num, pname, px, py, angle, length, etype)."""
        head = [f'\t\t(symbol "gen:{esc(name)}"']
        if power:
            head.append("\t\t\t(power)")
        head += [f'\t\t\t(pin_numbers (hide {"yes" if hide_numbers else "no"}))',
                 f'\t\t\t(pin_names (offset {name_offset})'
                 + (' (hide yes))' if hide_names else ')'),
                 "\t\t\t(exclude_from_sim no)",
                 "\t\t\t(in_bom yes)",
                 "\t\t\t(on_board yes)",
                 f'\t\t\t(property "Reference" "{ref_prefix}" (at 0 0 0)'
                 f"\n\t\t\t\t{eff(hide=True)})",
                 f'\t\t\t(property "Value" "{esc(value)}" (at 0 0 0)'
                 f"\n\t\t\t\t{eff(hide=True)})",
                 f'\t\t\t(property "Footprint" "" (at 0 0 0)'
                 f"\n\t\t\t\t{eff(hide=True)})",
                 f'\t\t\t(symbol "{esc(name)}_0_1"']
        head += ["\t\t\t\t" + g for g in gfx]
        head.append("\t\t\t)")
        head.append(f'\t\t\t(symbol "{esc(name)}_1_1"')
        for p in pins:
            num, pname, px, py, ang, ln, etype = p[:7]
            hid = " (hide yes)" if len(p) > 7 and p[7] else ""
            head.append(f"\t\t\t\t(pin {etype} line (at {q(px)} {q(py)} {ang})"
                        f" (length {q(ln)}){hid}")
            head.append(f'\t\t\t\t\t(name "{esc(pname)}" {FONT})')
            head.append(f'\t\t\t\t\t(number "{esc(num)}" {FONT}))')
        head.append("\t\t\t)")
        head.append("\t\t)")
        anchors = {p[0]: (p[2], p[3]) for p in pins}
        self.defs[name] = SymDef(name, style, anchors, extent,
                                 "\n".join(head), tb)

    def defbox(self, name, value, sides, min_w=0.0):
        """sides: dict with 'l','r','t','b' -> list of slots, each None or
        (num, pname) or (num, pname, [more_nums]). The third form stacks
        several pads on one graphical pin — KiCad's idiom for pads that are
        internally connected (the ESD array's two IO1 pads, a crystal's two
        ground tabs), which is the only honest way to draw them as one net."""
        if name in self.defs:
            return self.defs[name]
        L = list(sides.get("l", []))
        R = list(sides.get("r", []))
        T = list(sides.get("t", []))
        B = list(sides.get("b", []))
        # Top/bottom pin names run vertically INSIDE the box and would be
        # written straight through any side-pin name whose text reaches the
        # same columns. Where they would collide, reserve as many side slots
        # as the vertical name is tall so the two never share a row.
        CW = 1.3   # per-character advance, generous on purpose

        def band(side, hw):
            names = [p[1] for p in side if p]
            if not names:
                return 0
            half = (len(side) - 1) * GRID / 2.0 + 0.8      # name columns
            lw = max([len(p[1]) for p in L if p] or [0]) * CW
            rw = max([len(p[1]) for p in R if p] or [0]) * CW
            if -hw + 0.5 + lw < -half and half < hw - 0.5 - rw:
                return 0                                   # they clear
            return min(6, math.ceil(max(map(len, names)) * 1.27 / GRID) + 1)
        nv = max(len(L), len(R), 1)
        nh = max(len(T), len(B), 0)
        h = (nv + 1) * GRID
        wname = 0.0
        lw = max([len(p[1]) for p in L if p] or [0])
        rw = max([len(p[1]) for p in R if p] or [0])
        if lw or rw:
            wname = (lw + rw) * 1.15 + 5.0
        w = max((nh + 1) * GRID, wname, min_w)
        w = math.ceil(w / GRID) * GRID
        L = [None] * band(T, w / 2.0) + L + [None] * band(B, w / 2.0)
        R = [None] * band(T, w / 2.0) + R + [None] * band(B, w / 2.0)
        nv = max(len(L), len(R), 1)
        h = (nv + 1) * GRID
        hw, hh = w / 2.0, h / 2.0
        gfx = [f"(rectangle (start {q(-hw)} {q(hh)}) (end {q(hw)} {q(-hh)})",
               "\t\t\t\t\t(stroke (width 0.254) (type default))",
               "\t\t\t\t\t(fill (type background)))"]
        pins = []

        def add(p, px, py, ang):
            pins.append((p[0], p[1], px, py, ang, PINLEN, "passive"))
            for extra in (p[2] if len(p) > 2 else []):
                pins.append((extra, p[1], px, py, ang, PINLEN, "passive",
                             True))

        for i, p in enumerate(L):
            if p:
                add(p, -hw - PINLEN, hh - GRID * (i + 1), 0)
        for i, p in enumerate(R):
            if p:
                add(p, hw + PINLEN, hh - GRID * (i + 1), 180)
        x0 = -(len(T) - 1) * GRID / 2.0 if T else 0.0
        for i, p in enumerate(T):
            if p:
                add(p, x0 + GRID * i, hh + PINLEN, 270)
        x0 = -(len(B) - 1) * GRID / 2.0 if B else 0.0
        for i, p in enumerate(B):
            if p:
                add(p, x0 + GRID * i, -hh - PINLEN, 90)
        self._emit_def(name, value, "box", pins, gfx,
                       (hw + PINLEN, hh + PINLEN),
                       tb=(any(T), any(B)))
        return self.defs[name]

    def defpassives(self):
        st = "\t\t\t\t\t(stroke (width {w}) (type default))\n" \
             "\t\t\t\t\t(fill (type none)))"

        def poly(pts, w=0):
            s = " ".join(f"(xy {q(a)} {q(b)})" for a, b in pts)
            return f"(polyline (pts {s})\n" + st.format(w=w)

        # resistor
        self._emit_def("R", "R", "passive", [
            ("1", "~", 0, 3.81, 270, 1.27, "passive"),
            ("2", "~", 0, -3.81, 90, 1.27, "passive")],
            ["(rectangle (start -1.016 -2.54) (end 1.016 2.54)\n"
             "\t\t\t\t\t(stroke (width 0.254) (type default))\n"
             "\t\t\t\t\t(fill (type none)))"],
            (2.0, 3.81), hide_numbers=True, hide_names=True, ref_prefix="R")
        # capacitor
        self._emit_def("C", "C", "passive", [
            ("1", "~", 0, 3.81, 270, 2.794, "passive"),
            ("2", "~", 0, -3.81, 90, 2.794, "passive")],
            [poly([(-2.032, 0.762), (2.032, 0.762)], 0.508),
             poly([(-2.032, -0.762), (2.032, -0.762)], 0.508)],
            (2.1, 3.81), hide_numbers=True, hide_names=True, ref_prefix="C")
        # inductor
        arcs = []
        for k in range(4):
            y0 = 2.54 - 1.27 * k
            arcs.append(f"(arc (start 0 {q(y0)}) (mid 0.6323 {q(y0 - 0.635)})"
                        f" (end 0 {q(y0 - 1.27)})\n"
                        "\t\t\t\t\t(stroke (width 0) (type default))\n"
                        "\t\t\t\t\t(fill (type none)))")
        self._emit_def("L", "L", "passive", [
            ("1", "~", 0, 3.81, 270, 1.27, "passive"),
            ("2", "~", 0, -3.81, 90, 1.27, "passive")],
            arcs, (1.5, 3.81), hide_numbers=True, hide_names=True,
            ref_prefix="L")
        # 4-pin crystal, GND on 2/4
        self._emit_def("XTAL", "Crystal", "passive", [
            ("1", "~", -3.81, 0, 0, 1.27, "passive"),
            ("3", "~", 3.81, 0, 180, 1.27, "passive"),
            ("2", "~", 0, -5.08, 90, 1.27, "passive"),
            ("4", "~", 0, -5.08, 90, 1.27, "passive", True)],
            [poly([(-2.54, 2.286), (-2.54, 3.556), (2.54, 3.556),
                   (2.54, 2.286)]),
             poly([(-2.54, -2.286), (-2.54, -3.556), (2.54, -3.556),
                   (2.54, -2.286)]),
             poly([(-2.54, 0), (-2.032, 0)]),
             poly([(2.032, 0), (2.54, 0)]),
             poly([(-2.032, -1.27), (-2.032, 1.27)], 0.508),
             poly([(2.032, -1.27), (2.032, 1.27)], 0.508),
             poly([(0, -3.81), (0, -3.556)]),
             "(rectangle (start -1.143 2.54) (end 1.143 -2.54)\n"
             "\t\t\t\t\t(stroke (width 0.3048) (type default))\n"
             "\t\t\t\t\t(fill (type none)))"],
            (3.81, 5.08), hide_numbers=True, hide_names=True, ref_prefix="Y")
        # test point
        self._emit_def("TP", "TestPoint", "point", [
            ("1", "~", 0, 0, 90, 2.54, "passive")],
            [poly([(0, 2.54), (0, 3.048)]),
             "(circle (center 0 3.556) (radius 0.762)\n"
             "\t\t\t\t\t(stroke (width 0.254) (type default))\n"
             "\t\t\t\t\t(fill (type none)))"],
            (1.2, 4.4), hide_numbers=True, hide_names=True, ref_prefix="TP")
        # battery cell
        self._emit_def("BATT", "Battery", "passive", [
            ("1", "+", 0, 3.81, 270, 2.54, "passive"),
            ("2", "-", 0, -3.81, 90, 2.54, "passive")],
            [poly([(-2.54, 1.27), (2.54, 1.27)]),
             poly([(-1.27, -1.27), (1.27, -1.27)], 0.762),
             poly([(0, 1.27), (0, 0.508)]),
             poly([(-2.54, 0.508), (2.54, 0.508)], 0.0),
             poly([(-1.27, -0.508), (1.27, -0.508)], 0.762),
             poly([(0, -1.27), (0, -1.27)])],
            (2.7, 3.81), hide_numbers=True, hide_names=True, ref_prefix="BT")
        # 4-terminal tact switch. Two terminals leave each side of the body
        # and are the same node; the LCSC footprint numbers them across the
        # part, so the blades are {1,3} (one side) and {2,4} (the other) —
        # which is why the numbering here is not 1,2 | 3,4.
        self._emit_def("SW_PUSH", "SW_Push", "passive", [
            ("1", "~", -6.35, 2.54, 0, 2.54, "passive"),
            ("3", "~", -6.35, -2.54, 0, 2.54, "passive"),
            ("2", "~", 6.35, 2.54, 180, 2.54, "passive"),
            ("4", "~", 6.35, -2.54, 180, 2.54, "passive")],
            [poly([(-3.81, 2.54), (-2.54, 2.54), (-2.54, -2.54),
                   (-3.81, -2.54)]),
             poly([(3.81, 2.54), (2.54, 2.54), (2.54, -2.54), (3.81, -2.54)]),
             poly([(-3.302, 1.27), (3.302, 1.27)]),
             poly([(0, 1.27), (0, 3.302)]),
             poly([(-1.905, 3.302), (1.905, 3.302)])],
            (6.35, 4.4), hide_numbers=True, hide_names=True, ref_prefix="SW")
        # SPDT slide switch, 2 = common
        self._emit_def("SW_SPDT", "SW_SPDT", "passive", [
            ("1", "~", -6.35, 2.54, 0, 3.81, "passive"),
            ("3", "~", -6.35, -2.54, 0, 3.81, "passive"),
            ("2", "~", 6.35, 0, 180, 3.81, "passive")],
            ["(circle (center -2.286 2.54) (radius 0.254)\n"
             "\t\t\t\t\t(stroke (width 0) (type default))\n"
             "\t\t\t\t\t(fill (type outline)))",
             "(circle (center -2.286 -2.54) (radius 0.254)\n"
             "\t\t\t\t\t(stroke (width 0) (type default))\n"
             "\t\t\t\t\t(fill (type outline)))",
             "(circle (center 2.286 0) (radius 0.254)\n"
             "\t\t\t\t\t(stroke (width 0) (type default))\n"
             "\t\t\t\t\t(fill (type outline)))",
             poly([(2.286, 0), (-2.032, 2.032)])],
            (6.35, 4.4), hide_numbers=True, hide_names=True, ref_prefix="SW")

        # LED. Anode at the top, cathode at the bottom, so it hangs the
        # same way the R and C symbols do; numbered KiCad's way (1 = K,
        # 2 = A), which is what the LED footprints' silk bracket marks --
        # an assembler reading the board sees the cathode where the
        # netlist has it.
        self._emit_def("LED", "LED", "passive", [
            ("2", "A", 0, 3.81, 270, 1.905, "passive"),
            ("1", "K", 0, -3.81, 90, 1.905, "passive")],
            [poly([(-1.905, -1.27), (1.905, -1.27)], 0.254),
             poly([(-1.905, 1.905), (-1.905, 1.905)]),
             "(polyline (pts (xy -1.905 1.905) (xy 1.905 1.905)"
             " (xy 0 -1.27) (xy -1.905 1.905))\n"
             "\t\t\t\t\t(stroke (width 0.254) (type default))\n"
             "\t\t\t\t\t(fill (type none)))",
             poly([(2.032, 0.508), (3.302, 1.778)], 0.152),
             poly([(3.302, 1.778), (2.794, 1.651)], 0.152),
             poly([(3.302, 1.778), (3.175, 1.27)], 0.152),
             poly([(2.032, -0.762), (3.302, 0.508)], 0.152),
             poly([(3.302, 0.508), (2.794, 0.381)], 0.152),
             poly([(3.302, 0.508), (3.175, 0)], 0.152)],
            (3.4, 3.81), hide_numbers=True, hide_names=True, ref_prefix="D")
        # 2-pin crystal, drawn horizontally: the LFXO sits between the
        # module's XL1 and XL2 pads with a load cap under each end.
        self._emit_def("XTAL2", "Crystal", "passive", [
            ("1", "~", -3.81, 0, 0, 1.778, "passive"),
            ("2", "~", 3.81, 0, 180, 1.778, "passive")],
            [poly([(-2.032, -1.27), (-2.032, 1.27)], 0.508),
             poly([(2.032, -1.27), (2.032, 1.27)], 0.508),
             "(rectangle (start -1.143 1.905) (end 1.143 -1.905)\n"
             "\t\t\t\t\t(stroke (width 0.254) (type default))\n"
             "\t\t\t\t\t(fill (type none)))"],
            (3.81, 2.2), hide_numbers=True, hide_names=True, ref_prefix="Y")
        # 2-terminal tact switch (EVQ-PU*: the two internal blades are the
        # two numbered pads, unlike the 4-terminal part on the earring).
        self._emit_def("SW2", "SW_Push", "passive", [
            ("1", "~", -5.08, 0, 0, 2.54, "passive"),
            ("2", "~", 5.08, 0, 180, 2.54, "passive")],
            [poly([(-2.54, 0), (-2.032, 0)]),
             poly([(2.032, 0), (2.54, 0)]),
             "(circle (center -2.286 0) (radius 0.254)\n"
             "\t\t\t\t\t(stroke (width 0) (type default))\n"
             "\t\t\t\t\t(fill (type outline)))",
             "(circle (center 2.286 0) (radius 0.254)\n"
             "\t\t\t\t\t(stroke (width 0) (type default))\n"
             "\t\t\t\t\t(fill (type outline)))",
             poly([(-1.905, 0.762), (1.905, 0.762)]),
             poly([(0, 0.762), (0, 2.286)]),
             poly([(-1.27, 2.286), (1.27, 2.286)])],
            (5.08, 3.2), hide_numbers=True, hide_names=True, ref_prefix="SW")

    def defflag(self):
        if "PWR_FLAG" in self.defs:
            return self.defs["PWR_FLAG"]
        gfx = ["(polyline (pts (xy 0 0) (xy 0 1.27) (xy -1.016 1.905)"
               " (xy 0 2.54) (xy 1.016 1.905) (xy 0 1.27))\n"
               "\t\t\t\t\t(stroke (width 0.254) (type default))\n"
               "\t\t\t\t\t(fill (type none)))"]
        self._emit_def("PWR_FLAG", "PWR_FLAG", "power",
                       [("1", "pwr", 0, 0, 90, 0, "power_out")],
                       gfx, (1.5, 3.2), hide_numbers=True, hide_names=True,
                       power=True, ref_prefix="#FLG")
        return self.defs["PWR_FLAG"]

    def defpower(self, rail):
        name = f"P_{rail}"
        if name in self.defs:
            return self.defs[name]
        st = "\t\t\t\t\t(stroke (width 0) (type default))\n" \
             "\t\t\t\t\t(fill (type none)))"

        def poly(pts):
            s = " ".join(f"(xy {q(a)} {q(b)})" for a, b in pts)
            return f"(polyline (pts {s})\n" + st
        if rail == "GND":
            gfx = [poly([(0, 0), (0, -1.27)]),
                   poly([(-1.27, -1.27), (1.27, -1.27), (0, -2.54),
                         (-1.27, -1.27)])]
            ext = (1.5, 4.6)
        else:
            gfx = [poly([(0, 0), (0, 2.54)]),
                   poly([(-0.762, 1.27), (0, 2.54), (0.762, 1.27)])]
            ext = (1.5, 4.6)
        self._emit_def(name, rail, "power",
                       [("1", rail, 0, 0, 90 if rail != "GND" else 270, 0,
                         "power_in")],
                       gfx, ext, hide_numbers=True, hide_names=True,
                       power=True, ref_prefix="#PWR")
        return self.defs[name]

    # -- bbox / frames -------------------------------------------------
    def _grow(self, x, y, pad=0.0):
        """Grow the current block's frame box.

        Only symbols, labels and notes count — NOT the wires. A block's
        frame is meant to say "these parts belong together"; the wires that
        leave it to reach the MCU would otherwise stretch every satellite
        frame back over the chip it connects to.
        """
        if self._bb is None:
            self._bb = [x - pad, y - pad, x + pad, y + pad]
        else:
            b = self._bb
            b[0] = min(b[0], x - pad)
            b[1] = min(b[1], y - pad)
            b[2] = max(b[2], x + pad)
            b[3] = max(b[3], y + pad)

    def begin(self, title):
        self._title = title
        self._bb = None

    def end(self, pad=5.0):
        b = self._bb
        assert b, f"empty block {self._title}"
        x0, y0, x1, y1 = b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad
        pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
        s = " ".join(f"(xy {q(a)} {q(c)})" for a, c in pts)
        self.body.append(
            f"\t(polyline (pts {s})\n"
            "\t\t(stroke (width 0.1524) (type dash))\n"
            f'\t\t(uuid "{uid("frame", self._title)}"))')
        self.body.append(
            f'\t(text "{esc(self._title)}" (at {q(x0 + 1.27)} {q(y0 - 1.6)} 0)'
            f"\n\t\t{eff(2.2, bold=True, just='left bottom')}"
            f'\n\t\t(uuid "{uid("ftitle", self._title)}"))')
        self.frames.append((x0, y0 - 6.0, x1, y1, self._title))
        self._bb = None

    # -- text collisions -----------------------------------------------
    # Every readability bug this sheet has ever had was a label sitting on
    # a wire or on another label. Nothing in KiCad complains about that, so
    # the generator has to: record a box for every piece of text drawn and
    # refuse to emit a sheet where one lands on a wire or on its neighbour.
    def _text_box(self, s, x, y, size, just):
        w = len(str(s)) * size * 0.72
        j = (just or "").split()
        if "right" in j:
            x0, x1 = x - w, x
        elif "left" in j:
            x0, x1 = x, x + w
        else:
            x0, x1 = x - w / 2.0, x + w / 2.0
        # KiCad anchors vertically by baseline-ish; which side the glyphs
        # fall on depends on the justify token, so claim both. Conservative
        # in the safe direction: a false positive costs a nudge, a missed
        # one ships an unreadable sheet.
        return (x0, y - size, x1, y + size)

    def _note_text(self, s, x, y, size, just, what, on_wire=False,
                   group=None):
        """on_wire: a net label is SUPPOSED to sit on the wire it names, so
        those are only checked against other text, never against copper.
        group: consecutive lines of one wrapped note share a group and are
        allowed to sit tight against each other."""
        if not str(s).strip():
            return
        self.texts.append(self._text_box(s, x, y, size, just)
                          + (what, on_wire, group))

    @staticmethod
    def _overlap(a, b, pad=0.0):
        return (a[0] < b[2] - pad and b[0] < a[2] - pad
                and a[1] < b[3] - pad and b[1] < a[3] - pad)

    def check_text(self, verbose=False):
        """Report text that lands on a wire or on other text."""
        bad = []
        for i, t in enumerate(self.texts):
            for u in self.texts[i + 1:]:
                if t[6] is not None and t[6] == u[6]:
                    continue           # two lines of the same note
                if self._overlap(t, u, pad=0.01):
                    bad.append(f"{t[4]!r} overlaps text {u[4]!r}")
        for t in self.texts:
            if t[5]:
                continue
            for a, b in self.wires:
                if a[1] == b[1]:                       # horizontal run
                    x0, x1 = sorted((a[0], b[0]))
                    seg = (x0, a[1], x1, a[1])
                else:
                    y0, y1 = sorted((a[1], b[1]))
                    seg = (a[0], y0, a[0], y1)
                # text needs air around it, not just non-overlap
                if (t[0] - 0.5 < seg[2] and seg[0] < t[2] + 0.5
                        and t[1] - 0.5 < seg[3] and seg[1] < t[3] + 0.5):
                    bad.append(f"{t[4]!r} sits on the wire {a}-{b}")
                    break
        if verbose:
            for m in sorted(set(bad)):
                print("  TEXT:", m)
        return sorted(set(bad))

    def measure_page(self):
        """Paper size = everything drawn, plus a margin, on a 5mm grid."""
        x1 = max(f[2] for f in self.frames)
        y1 = max(f[3] for f in self.frames)
        for s, x, y, size in self.head:
            x1 = max(x1, x + len(s) * size * 0.72)
            y1 = max(y1, y)
        w = math.ceil((x1 + MARGIN) / 5.0) * 5.0
        h = math.ceil((y1 + MARGIN) / 5.0) * 5.0
        # nothing may sit under the title block in the bottom-right corner
        tb = (w - MARGIN - TITLE_BLOCK[0], h - MARGIN - TITLE_BLOCK[1])
        clash = [f[4] for f in self.frames if f[2] > tb[0] and f[3] > tb[1]]
        if clash:
            h = math.ceil((y1 + MARGIN + TITLE_BLOCK[1]) / 5.0) * 5.0
        self.page = (w, h)
        return self.page

    def check_frames(self, verbose=False):
        """Blocks must not overlap and must fit the sheet.

        Set SCH_LAYOUT=1 to print every block's measured box first — that
        listing is how the anchors below were chosen, and it is what you
        want when a netlist change makes a block outgrow its slot.
        """
        if verbose:
            for f in sorted(self.frames, key=lambda f: (f[0], f[1])):
                print(f"  [{f[0]:7.1f} {f[1]:7.1f}] .. [{f[2]:7.1f} "
                      f"{f[3]:7.1f}]  {f[2]-f[0]:6.1f} x {f[3]-f[1]:6.1f}"
                      f"  {f[4]}")
        bad = []
        for i in range(len(self.frames)):
            for j in range(i + 1, len(self.frames)):
                a, b = self.frames[i], self.frames[j]
                if (a[0] < b[2] and b[0] < a[2]
                        and a[1] < b[3] and b[1] < a[3]):
                    bad.append(f"{a[4]!r} overlaps {b[4]!r}")
        assert not bad, "block frames overlap:\n  " + "\n  ".join(bad)
        for f in self.frames:
            assert f[0] > 0 and f[1] > 0, \
                f"block {f[4]!r} runs off the top/left of the sheet: {f[:4]}"

    # -- placement -----------------------------------------------------
    @staticmethod
    def _on_grid(v):
        return abs(v / CONN_GRID - round(v / CONN_GRID)) < 1e-4

    def place(self, symname, ref, value, x, y, rot=0, footprint="",
              hide_value=False, ref_off=None):
        d = self.defs[symname]
        assert ref not in self.refs, f"duplicate reference {ref}"
        self.refs.add(ref)
        x, y = q(x), q(y)
        assert self._on_grid(x) and self._on_grid(y), (
            f"{ref} placed off the {CONN_GRID}mm connection grid at "
            f"({x}, {y}) — "
            "every symbol origin must be a whole number of grid steps, or "
            "its pins land where no wire can reach them")
        hw, hh = d.extent
        if rot in (90, 270):
            hw, hh = hh, hw
        self._grow(x - hw, y - hh)
        self._grow(x + hw, y + hh)
        # reference / value text placement
        if d.style == "box":
            rx = x - hw
            ry = y - hh - (4.6 if d.has_top else 1.6)
            rj = "left bottom"
            # The value goes under the box, but bottom pins drop their wires
            # from the middle of that edge straight into a ground symbol, so
            # run the value leftwards out of the centre instead of starting
            # at the left edge and crossing it.
            vx = x - 3.81 if d.has_bot else x - hw
            vy = y + hh + (4.4 if d.has_bot else 3.4)
            vj = "right bottom" if d.has_bot else "left bottom"
        elif d.style == "point":
            # A test point is a stub: the pad faces its wire and the body
            # (the circle) faces away, so the only free side is behind it.
            rx, ry, rj = x - hw - 0.6, y - 2.0, "right bottom"
            vx, vy, vj = x - hw - 0.6, y + 1.1, "right bottom"
        elif d.style == "power":
            rx, ry, rj = x, y, "left bottom"
            vx, vj = x, "center"
            vy = y + 4.6 if symname.endswith("GND") else y - 3.4
            if rot == 180:
                vy = y - 4.0 if symname.endswith("GND") else y + 5.2
        else:
            # Put the text where this part's pins are NOT. Every pin grows a
            # wire, so the free side depends on which way the part is turned,
            # not on the rotation angle as such: read it off the placed pin
            # offsets and pick the axis with the shorter reach.
            pts = [xf(px, py, rot) for px, py in d.pins.values()]
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            if max(ys) - min(ys) >= max(xs) - min(xs):
                # pins stack vertically -> park the text alongside the body,
                # between the two pins so it cannot reach either run
                rx, ry, rj = x + hw + 0.6, y - 2.0, "left bottom"
                vx, vy, vj = x + hw + 0.6, y + 1.1, "left bottom"
            else:
                # pins run left-right -> stack the text above and below,
                # stepped off the pin axis so it clears the wires' corners
                rx, ry, rj = x + 1.9, y - hh - 2.8, "left bottom"
                vx, vy, vj = x + 1.9, y + hh + 4.2, "left bottom"
        if ref_off:
            rx, ry = x + ref_off[0], y + ref_off[1]
            vx, vy = x + ref_off[0], y + ref_off[1] + 3.4
        self._grow(rx, ry - 1.3)
        self._grow(rx + len(ref) * 1.0, ry)
        if d.style != "power":
            self._note_text(ref, rx, ry, 1.27, rj, f"{ref} ref")
        if not hide_value:
            self._note_text(value, vx, vy, 1.27, vj, f"{ref} value {value!r}")
        # KiCad adds the symbol's orientation to a property's own angle, and
        # renders a resulting 180 deg upside-down. Cancel the rotation for
        # quarter turns; a half turn already reads the right way up.
        tang = 0 if rot in (0, 180) else (360 - rot) % 360
        parts = [f'\t(symbol (lib_id "gen:{esc(symname)}")',
                 f"\t\t(at {x} {y} {rot})",
                 "\t\t(unit 1) (exclude_from_sim no) (in_bom yes)"
                 " (on_board yes) (dnp no)",
                 f'\t\t(uuid "{uid("sym", ref)}")',
                 f'\t\t(property "Reference" "{esc(ref)}" '
                 f"(at {q(rx)} {q(ry)} {tang})\n\t\t\t"
                 + eff(1.27, just=rj, hide=(d.style == "power")) + ")",
                 f'\t\t(property "Value" "{esc(value)}" '
                 f"(at {q(vx)} {q(vy)} {tang})\n\t\t\t"
                 + eff(1.27, just=vj, hide=hide_value) + ")"]
        if footprint:
            parts.append(f'\t\t(property "Footprint" "{esc(footprint)}"'
                         f" (at {x} {y} 0)\n\t\t\t{eff(hide=True)})")
        for num in d.pins:
            parts.append(f'\t\t(pin "{esc(num)}" (uuid "{uid("pin", ref, num)}"))')
        parts.append('\t\t(instances (project "bluebuzz"'
                     f'\n\t\t\t(path "/{SHEET_UUID}"'
                     f'\n\t\t\t\t(reference "{esc(ref)}") (unit 1)))))')
        self.body.append("\n".join(parts))
        out = {}
        for num, (px, py) in d.pins.items():
            dx, dy = xf(px, py, rot)
            out[num] = (q(x + dx), q(y + dy))
        return out

    # -- connectivity items --------------------------------------------
    def wire(self, a, b):
        for pt in (a, b):
            assert self._on_grid(pt[0]) and self._on_grid(pt[1]), \
                f"wire endpoint {pt} is off the {CONN_GRID}mm connection grid"
        a, b = (q(a[0]), q(a[1])), (q(b[0]), q(b[1]))
        if a == b:
            return
        assert a[0] == b[0] or a[1] == b[1], \
            f"diagonal wire {a} -> {b} (schematic wires must be orthogonal)"
        self.wires.append((a, b))

    def path(self, *pts):
        for a, b in zip(pts, pts[1:]):
            self.wire(a, b)

    def junction(self, p):
        self.jpts.add((q(p[0]), q(p[1])))

    def nc(self, p):
        self.body.append(
            f"\t(no_connect (at {q(p[0])} {q(p[1])})"
            f'\n\t\t(uuid "{uid("nc", p)}"))')

    def label(self, net, p, rot=0, just="left", size=1.0):
        """Name a wire that KiCad would otherwise auto-name.

        These are GLOBAL labels even though the run is local, because a
        plain label on the root sheet comes back out of the netlister as
        `/LED_D7`, and the board is matched to circuit.py by net name — a
        rename would relabel every net on a hand-routed board. Drawn small,
        so naming a wire costs a word rather than a box.
        """
        self.glabel(net, p, rot=rot, just=just, size=size)

    def glabel(self, net, p, rot=0, just="left", size=1.27):
        # the label box is the text plus KiCad's arrow shape around it. A
        # right-justified label at rotation 0 is drawn to the LEFT of its
        # anchor, so its box goes that side too (or the block frame is
        # measured without it and cuts through the label).
        if rot == 0:
            self._note_text(f" {net} ", p[0], p[1], size,
                            "right" if just == "right" else "left",
                            f"label {net}", on_wire=True)
        elif rot == 180:
            self._note_text(f" {net} ", p[0], p[1], size, "left" if just == "right" else "right",
                            f"label {net}", on_wire=True)
        self.body.append(
            f'\t(global_label "{esc(net)}" (shape input) '
            f"(at {q(p[0])} {q(p[1])} {rot})\n\t\t"
            + eff(size, just=just) + f'\n\t\t(uuid "{uid("gl", net, p)}"))')

    def note(self, s, x, y, width, size=1.4):
        """Block note, wrapped to `width` mm. KiCad has no text box, and an
        unwrapped note stretches the block frame across half the sheet."""
        cols = max(16, int(width / (size * 0.72)))
        line, lines = "", []
        for word in s.split():
            if line and len(line) + 1 + len(word) > cols:
                lines.append(line)
                line = word
            else:
                line = f"{line} {word}".strip()
        if line:
            lines.append(line)
        for i, ln in enumerate(lines):
            self.text(ln, x, y + i * size * 1.9, size=size,
                      group=("note", q(x), q(y)))

    def text(self, s, x, y, size=1.27, bold=False, just="left bottom",
             frame=True, group=None):
        if not frame:
            self.head.append((s, x, y, size))
        if frame:
            self._grow(x, y - size)
            self._grow(x + len(s) * size * 0.72, y)
            self._note_text(s, x, y, size, just, f"note {s[:24]!r}",
                            group=group)
        self.body.append(
            f'\t(text "{esc(s)}" (at {q(x)} {q(y)} 0)\n\t\t'
            + eff(size, bold=bold, just=just)
            + f'\n\t\t(uuid "{uid("txt", x, y, s[:28])}"))')

    # -- convenience ---------------------------------------------------
    def rail(self, net, p, rot=0):
        """Power/ground symbol whose pin lands exactly on p."""
        self.defpower(net)
        self.pwr_n += 1
        self.place(f"P_{net}", f"#PWR{self.pwr_n:04d}", net, p[0], p[1],
                   rot=rot)
        return p

    @staticmethod
    def _interior(a, b, p):
        """Is p strictly between the ends of the orthogonal segment a-b?"""
        if a[0] == b[0] == p[0]:
            return min(a[1], b[1]) < p[1] < max(a[1], b[1])
        if a[1] == b[1] == p[1]:
            return min(a[0], b[0]) < p[0] < max(a[0], b[0])
        return False

    def finish_wires(self):
        """Split every wire at the junctions on it, and put a junction
        wherever one wire ENDS in the middle of another.

        Both steps are what the KiCad editor does as you draw. Without
        them the connectivity engine only breaks a run at its first
        junction, so a single long rail wire silently connects the first
        two taps and leaves the rest floating — which is exactly what the
        netlist round-trip caught the first time this sheet was drawn.
        """
        ends = set()
        for a, b in self.wires:
            ends.add(a)
            ends.add(b)
        stray = set()
        for a, b in self.wires:
            for e in ends:
                if self._interior(a, b, e):
                    if e not in self.jpts:
                        stray.add(e)
                    self.jpts.add(e)
        # Every intended tap is declared with junction(); anything else that
        # lands mid-wire is a layout collision that would silently short two
        # nets, so refuse to emit it.
        assert not stray, ("wires meet at undeclared points (layout "
                           "collision): "
                           + ", ".join(f"({x}, {y})" for x, y in sorted(stray)))
        # Crossings. Two wires that cross without a junction are legal but
        # they are exactly where a net label lands on two nets at once (a
        # label attaches to every wire under it), and they are the thing
        # that makes a sheet hard to read. Route around them instead.
        hs = [(a, b) for a, b in self.wires if a[1] == b[1]]
        vs = [(a, b) for a, b in self.wires if a[0] == b[0] and a[1] != b[1]]
        cross = []
        for ha, hb in hs:
            x0, x1 = sorted((ha[0], hb[0]))
            for va, vb in vs:
                y0, y1 = sorted((va[1], vb[1]))
                if x0 < va[0] < x1 and y0 < ha[1] < y1:
                    cross.append((va[0], ha[1]))
        assert not cross, ("wires cross without connecting: "
                           + ", ".join(f"({x}, {y})" for x, y in sorted(set(cross))))
        out = []
        for a, b in self.wires:
            cuts = sorted((p for p in self.jpts if self._interior(a, b, p)),
                          key=lambda p: (p[0] - a[0]) ** 2 + (p[1] - a[1]) ** 2)
            prev = a
            for c in cuts:
                out.append((prev, c))
                prev = c
            out.append((prev, b))
        seen = set()
        for a, b in out:
            k = tuple(sorted([a, b]))
            if k in seen:
                continue
            seen.add(k)
            self.body.append(
                f"\t(wire (pts (xy {a[0]} {a[1]}) (xy {b[0]} {b[1]}))"
                "\n\t\t(stroke (width 0) (type default))"
                f'\n\t\t(uuid "{uid("w", a, b)}"))')
        for p in sorted(self.jpts):
            self.body.append(
                f"\t(junction (at {p[0]} {p[1]}) (diameter 0)"
                " (color 0 0 0 0)"
                f'\n\t\t(uuid "{uid("j", p)}"))')

    def render(self):
        self.finish_wires()
        w, h = self.page or self.measure_page()
        return ("(kicad_sch\n\t(version 20250114)\n"
                '\t(generator "gen_schematic")\n'
                '\t(generator_version "9.0")\n'
                f'\t(uuid "{SHEET_UUID}")\n'
                f'\t(paper "User" {w} {h})\n'
                "\t(lib_symbols\n"
                + "\n".join(d.sexpr for d in self.defs.values())
                + "\n\t)\n" + "\n".join(self.body) + "\n)\n")




# ---------------------------------------------------------------------------
# IC symbol pin maps: pins are placed by FUNCTION, not by pad order.
# ---------------------------------------------------------------------------
def module_sides():
    """The E73 module: 43 pads, most of them unused.

    Used pads go on the side that faces the block they talk to; the spare
    GPIOs go along the bottom as a row of no-connects.
    """
    used = set()
    for pad_name in ROLE:
        used.add(E73[pad_name])
    named = {"VCC", "VDDH", "GND1", "GND2", "GND3", "XL1", "XL2", "SWDIO",
             "SWCLK", "RST", "VBUS", "USB_DP", "USB_DM", "DCCH"}
    spare = sorted(p for n, p in E73.items()
                   if p not in used and n not in named)
    rev = {v: k for k, v in E73.items()}

    def sl(pad, label=None):
        return (str(pad), label or rev[pad])

    left = ([sl(E73["RST"], "P0.18/RST"), sl(E73["SWDIO"], "SWDIO"),
             sl(E73["SWCLK"], "SWCLK")]
            + [None] * 3
            # the LFXO is drawn in the gap between XL1 and XL2, inside
            # the module's own frame, so neither run has to cross the other
            + [sl(E73["XL1"], "P0.00/XL1")] + [None] * 7
            + [sl(E73["XL2"], "P0.01/XL2")]
            + [None] * 7
            + [sl(E73["USB_DM"], "D-"), sl(E73["USB_DP"], "D+")]
            + [None] * 3
            + [sl(E73["P0.13"], "P0.13/BTN"), sl(E73["P0.24"], "P0.24/LED")])
    right = ([sl(E73["P1.11"], "P1.11/M1_PWM"), sl(E73["P0.31"], "P0.31/M2_PWM"), None,
              sl(E73["P1.10"], "P1.10/HX_DOUT"), sl(E73["P0.28"], "P0.28/HX_SCK"),
              sl(E73["P1.13"], "P1.13/SENS_EN")]
             + [None]
             + [sl(E73["P0.03"], "P0.03/AIN1"), sl(E73["P0.02"], "P0.02/AIN0")]
             + [None]
             + [sl(E73["P0.29"], "P0.29/SDA"), sl(E73["P0.30"], "P0.30/SCL")])
    # VCC and VDDH are tied: normal-voltage mode, REG0 unused, DCCH open.
    top = [(str(E73["VCC"]), "VCC"), (str(E73["VDDH"]), "VDDH"),
           None, (str(E73["VBUS"]), "VBUS")]
    bot = ([(str(E73["GND1"]), "GND", [str(E73["GND2"]), str(E73["GND3"])]),
            (str(E73["DCCH"]), "DCCH(NC)")]
           + [None] + [sl(p) for p in spare] + [None] * 2)
    return {"l": left, "r": right, "t": top, "b": bot}


IC_SIDES = {
    # BQ24074: supplies left, battery and status right, programming
    # resistors on the bottom where their pulldowns can drop straight to GND.
    "charger": {"l": [("13", "IN"), None, None,
                      ("4", "/CE"), None, None,
                      ("5", "EN2"), None, None,
                      ("6", "EN1")],
                "r": [("10", "OUT", ["11"]), None, ("2", "BAT", ["3"]), None,
                      ("7", "/PGOOD"), ("9", "/CHG")],
                "b": [("16", "ISET"), None, None, None,
                      ("12", "ILIM"), None, None, None,
                      ("14", "TMR"), None, None, None,
                      ("1", "TS"), None, None, None,
                      ("15", "ITERM"), None, None, None,
                      ("8", "VSS", ["17"])]},
    "ldo": {"l": [("1", "IN"), ("3", "EN")],
            "r": [("5", "OUT"), ("4", "NC")],
            "b": [("2", "GND")]},
    "load_switch": {"l": [("1", "VIN"), None, ("3", "ON"), ("4", "CT")],
                    "r": [("6", "VOUT"), ("5", "QOD")],
                    "b": [("2", "GND")]},
    # HX711: the bridge on the left, the host interface and the pins the
    # datasheet says to tie or leave open on the right, supplies on top.
    "hx711": {"l": [("8", "INA+"), ("7", "INA-"), None,
                    ("10", "INB+"), ("9", "INB-")],
              # four blank rows under PD_SCK: R55 and its value sit on
              # that row, and RATE's rail caption needs air above it
              "r": [("12", "DOUT"), ("11", "PD_SCK"), None, None, None, None,
                    ("15", "RATE"), ("14", "XI"), ("13", "XO"), None,
                    ("2", "BASE"), ("6", "VBG")],
              "t": [("1", "VSUP"), ("3", "AVDD"), ("16", "DVDD")],
              "b": [("5", "AGND"), None, ("4", "VFB")]},
    "motor_fet": {"l": [("1", "G")], "r": [("3", "D")], "b": [("2", "S")]},
    "usb_esd": {"t": [("1", "IO1", ["6"])], "b": [("3", "IO2", ["4"])],
                "l": [("5", "VBUS")], "r": [("2", "GND")]},
    "usb_conn": {"r": [("A4", "VBUS", ["A9", "B4", "B9"]), None,
                       ("A6", "D+"), ("B6", "D+"), None, None, None, None,
                       ("A7", "D-"), ("B7", "D-"), None,
                       ("A5", "CC1"), ("B5", "CC2"), None,
                       ("A8", "SBU1"), ("B8", "SBU2")],
                 "b": [("A1", "GND", ["A12", "B1", "B12"]), ("S1", "SHIELD")]},
    "swd": {"l": [("1", "VCC"), ("2", "SWDIO"), ("3", "nRESET"),
                  ("4", "SWCLK"), ("5", "GND"), ("6", "NC")]},
    "batt_conn": {"l": [("1", "+"), ("2", "-")]},
    # both motors on one housing; the two VSYS pins are drawn as one
    "motor_conn": {"l": [("1", "VSYS", ["3"]), None, ("2", "M1"), None,
                         None, None, ("4", "M2")]},
    # The MP tabs are the connector's mechanical joint: drawn with the
    # GND pin, not as a separate net.
    "lc_conn": {"l": [("1", "E+"), ("2", "A-"), ("3", "A+")],
                "b": [("4", "E-", ["MP"])]},
    # SDA/SCL at the top so both pull-ups can hang above their lines
    # without crossing anything; the supply pin at the bottom so its
    # rail can drop down.
    "press_conn": {"l": [("4", "SDA"), None, ("5", "SCL"), None, None,
                         ("3", "AIN"), None, ("1", "3V3")],
                   "b": [("2", "GND", ["MP"])]},
}

IC_MIN_W = {"usb_esd": 17.78, "batt_conn": 15.24, "motor_fet": 15.24, "motor_conn": 15.24,
            "lc_conn": 15.24, "press_conn": 10.16}

PASSIVE_SYM = {"r_": "R", "c_": "C", "crystal": "XTAL2", "button": "SW2",
               "led": "LED", "motor_flyback": "D"}


def sym_for(part):
    for k, v in PASSIVE_SYM.items():
        if part == k or part.startswith(k):
            return v
    return part


def defdiode(s):
    """Plain diode, drawn like the LED (anode up, cathode down), numbered
    1 = cathode, 2 = anode as KiCad's and LCSC's SOD footprints are."""
    if "D" in s.defs:
        return s.defs["D"]
    st = "\t\t\t\t\t(stroke (width {w}) (type default))\n" \
         "\t\t\t\t\t(fill (type none)))"

    def poly(pts, w=0):
        p = " ".join(f"(xy {a} {b})" for a, b in pts)
        return f"(polyline (pts {p})\n" + st.format(w=w)
    s._emit_def("D", "D", "passive", [
        ("1", "K", 0, -3.81, 90, 1.905, "passive"),
        ("2", "A", 0, 3.81, 270, 1.905, "passive")],
        [poly([(-1.905, -1.27), (1.905, -1.27)], 0.254),
         poly([(-1.905, 1.905), (1.905, 1.905), (0, -1.27), (-1.905, 1.905)],
              0.254)],
        (2.1, 3.81), hide_numbers=True, hide_names=True, ref_prefix="D")
    return s.defs["D"]


# ---------------------------------------------------------------------------
# electrical bookkeeping: every pin drawn must match circuit.py, and every
# pin in circuit.py must be drawn.
# ---------------------------------------------------------------------------
class Book:
    def __init__(self, comps):
        self.comps = comps
        self.seen = set()

    def net(self, ref, pin):
        return self.comps[ref].pins[str(pin)]

    def take(self, ref, pin, expect=None):
        p = str(pin)
        assert p in self.comps[ref].pins, f"{ref} has no pin {p}"
        got = self.comps[ref].pins[p]
        if expect is not None:
            assert got == expect, f"{ref}.{p} is net {got!r}, expected {expect!r}"
        self.seen.add((ref, p))
        return got

    def report(self):
        missing = []
        for ref, c in self.comps.items():
            for p in c.pins:
                if (ref, p) not in self.seen:
                    missing.append(f"{ref}.{p}")
        assert not missing, ("pins in circuit.py that the sheet never drew: "
                             + ", ".join(missing[:40]))


# ---------------------------------------------------------------------------
# blocks
# ---------------------------------------------------------------------------
def put(s, cir, ref, x, y, rot=0, hide_value=False, ref_off=None):
    c = cir.components[ref]
    return s.place(sym_for(c.part), ref, c.value, x, y, rot=rot,
                   footprint=c.footprint, hide_value=hide_value,
                   ref_off=ref_off)


def vdrop(s, cir, bk, ref, x, ytop, rail="GND", drop=3.81, hide_value=False,
          ref_off=None):
    """2-pin part hanging down from (x, ytop) into a rail symbol below."""
    p = put(s, cir, ref, x, ytop + 3.81, hide_value=hide_value,
            ref_off=ref_off)
    bk.take(ref, "1")
    bk.take(ref, "2", rail)
    s.wire(p["2"], (x, p["2"][1] + drop))
    s.rail(rail, (x, p["2"][1] + drop))
    return p


def bank(s, cir, bk, refs, x, ytop, rail, pitch=10.16):
    """A row of decoupling caps strung between `rail` above and GND below."""
    xs = [x + i * pitch for i in range(len(refs))]
    for xi, ref in zip(xs, refs):
        p = put(s, cir, ref, xi, ytop + 3.81, ref_off=(2.3, -0.4))
        bk.take(ref, "1", rail)
        bk.take(ref, "2", "GND")
        s.wire((xi, ytop), p["1"])
        s.wire(p["2"], (xi, ytop + 11.43))
    if len(xs) > 1:
        s.wire((xs[0], ytop), (xs[-1], ytop))
        s.wire((xs[0], ytop + 11.43), (xs[-1], ytop + 11.43))
    for xi in xs[1:-1]:
        s.junction((xi, ytop))
        s.junction((xi, ytop + 11.43))
    s.wire((xs[0], ytop), (xs[0], ytop - 3.81))
    s.rail(rail, (xs[0], ytop - 3.81))
    s.wire((xs[-1], ytop + 11.43), (xs[-1], ytop + 15.24))
    s.rail("GND", (xs[-1], ytop + 15.24))
    return xs


# --- Block 1 ---------------------------------------------------------------
def blk_usb(s, cir, bk, x, y):
    s.begin("Block 1 — USB-C input and ESD")
    j = put(s, cir, "J1", x, y, hide_value=True)

    for pad in ("A4", "A9", "B4", "B9"):
        bk.take("J1", pad, "VBUS")
    xv = j["A4"][0] + 15.24
    ycap = j["A4"][1] - 22.86
    s.wire(j["A4"], (xv, j["A4"][1]))
    s.wire((xv, j["A4"][1]), (xv, ycap))
    s.wire((xv, ycap), (xv + 15.24, ycap))
    bank(s, cir, bk, ["C2"], xv + 15.24, ycap, "VBUS")

    xd = j["A6"][0] + 7.62
    ydp = q((j["A6"][1] + j["B6"][1]) / 2.0)
    ydn = q((j["A7"][1] + j["B7"][1]) / 2.0)
    u10 = put(s, cir, "U10", j["A6"][0] + 40.64, q((ydp + ydn) / 2.0))
    assert ydp < u10["1"][1] and u10["3"][1] < ydn, \
        "the ESD array must sit between the D+ and D- runs"
    for a, b, pin, extra, net, mid in (
            ("A6", "B6", "1", "6", "USB_DP", ydp),
            ("A7", "B7", "3", "4", "USB_DM", ydn)):
        bk.take("J1", a, net)
        bk.take("J1", b, net)
        bk.take("U10", pin, net)
        bk.take("U10", extra, net)
        s.wire(j[a], (xd, j[a][1]))
        s.wire(j[b], (xd, j[b][1]))
        s.wire((xd, j[a][1]), (xd, j[b][1]))
        s.junction((xd, mid))
        s.wire((xd, mid), (u10[pin][0] + 15.24, mid))
        s.junction((u10[pin][0], mid))
        s.wire(u10[pin], (u10[pin][0], mid))
        s.glabel(net, (u10[pin][0] + 15.24, mid))
    bk.take("U10", "5", "VBUS")
    s.wire(u10["5"], (u10["5"][0] - 6.35, u10["5"][1]))
    s.rail("VBUS", (u10["5"][0] - 6.35, u10["5"][1]))
    bk.take("U10", "2", "GND")
    s.wire(u10["2"], (u10["2"][0] + 6.35, u10["2"][1]))
    s.rail("GND", (u10["2"][0] + 6.35, u10["2"][1]))

    for cc, rref, dx in (("B5", "R2", 15.24), ("A5", "R1", 25.4)):
        net = bk.take("J1", cc)
        s.wire(j[cc], (j[cc][0] + dx, j[cc][1]))
        s.label(net, (j[cc][0] + 3.0, j[cc][1]), size=1.0)
        s.wire((j[cc][0] + dx, j[cc][1]), (j[cc][0] + dx, j["B5"][1] + 6.35))
        r = put(s, cir, rref, j[cc][0] + dx, j["B5"][1] + 10.16)
        bk.take(rref, "1", net)
        bk.take(rref, "2", "GND")
        s.wire(r["2"], (r["2"][0], r["2"][1] + 3.81))
        s.rail("GND", (r["2"][0], r["2"][1] + 3.81))
    for n in ("A8", "B8"):
        bk.take("J1", n, "")
        s.nc(j[n])

    for pad in ("A1", "A12", "B1", "B12"):
        bk.take("J1", pad, "GND")
    bk.take("J1", "S1", "GND")
    ybus = j["A1"][1] + 5.08
    s.wire(j["A1"], (j["A1"][0], ybus))
    s.wire(j["S1"], (j["S1"][0], ybus))
    s.wire((j["A1"][0], ybus), (j["S1"][0], ybus))
    xg = q((j["A1"][0] + j["S1"][0]) / 2.0)
    s.junction((xg, ybus))
    s.wire((xg, ybus), (xg, ybus + 3.81))
    s.rail("GND", (xg, ybus + 3.81))
    s.note("A6/B6 and A7/B7 are the same signal on a USB-C receptacle and "
           "must be tied, or the board only enumerates in one cable "
           "orientation. 5.1k on EACH CC line advertises a default-current "
           "sink. The USBLC6-2P6 (SOT-666) clamps VBUS and protects D+/D-, "
           "not CC — accepted, CC is short-traced.",
           x - 6.0, ybus + 12.7, 100.0)
    s.end()


# --- Block 2 ---------------------------------------------------------------
def blk_charger(s, cir, bk, x, y):
    s.begin("Block 2 — BQ24074 charger with power path")
    u = put(s, cir, "U2", x, y, ref_off=(0.0, -3.0))

    bk.take("U2", "13", "VBUS")
    s.wire(u["13"], (u["13"][0] - 7.62, u["13"][1]))
    s.rail("VBUS", (u["13"][0] - 7.62, u["13"][1]))

    for pin, rail, dx in (("4", "GND", 10.16), ("5", "3V3_SYS", 22.86),
                          ("6", "GND", 10.16)):
        bk.take("U2", pin, rail)
        s.wire(u[pin], (u[pin][0] - dx, u[pin][1]))
        s.rail(rail, (u[pin][0] - dx, u[pin][1]), rot=90)

    for pad in ("10", "11"):
        bk.take("U2", pad, "VSYS")
    xo = u["10"][0] + 10.16
    s.wire(u["10"], (xo, u["10"][1]))
    s.wire((xo, u["10"][1]), (xo, u["10"][1] - 6.35))
    s.rail("VSYS", (xo, u["10"][1] - 6.35))

    for pad in ("2", "3"):
        bk.take("U2", pad, "VBAT")
    xb = u["2"][0] + 17.78
    s.wire(u["2"], (xb, u["2"][1]))
    s.wire((xb, u["2"][1]), (xb, u["2"][1] - 8.89))
    s.rail("VBAT", (xb, u["2"][1] - 8.89))

    # /PGOOD open: the nRF52840's own VBUSDETECT says whether USB is there
    bk.take("U2", "7", "")
    s.nc(u["7"])
    bk.take("U2", "9", "CHG_N")
    ych = u["9"][1]
    xled = u["9"][0] + 33.02
    s.wire(u["9"], (xled, ych))
    s.label("CHG_N", (u["9"][0] + 5.08, ych), size=1.0)
    r14 = put(s, cir, "R14", xled, ych - 3.81, rot=0)
    bk.take("R14", "2", "CHG_N")
    bk.take("R14", "1", "CHG_LED")
    d1 = put(s, cir, "D1", xled, ych - 15.24)
    bk.take("D1", "1", "CHG_LED")          # cathode, bottom
    bk.take("D1", "2", "3V3_SYS")          # anode, top
    s.wire(r14["1"], d1["1"])
    s.label("CHG_LED", (xled, q((r14["1"][1] + d1["1"][1]) / 2.0)), size=1.0)
    s.wire(d1["2"], (d1["2"][0], d1["2"][1] - 3.81))
    s.rail("3V3_SYS", (d1["2"][0], d1["2"][1] - 3.81))

    ybot = u["16"][1]
    for ref, pin in (("R10", "16"), ("R11", "12"), ("R12", "14"), ("R13", "1")):
        net = bk.take("U2", pin)
        xp = u[pin][0]
        s.wire(u[pin], (xp, ybot + 5.08))
        s.label(net, (xp, ybot + 3.81), rot=90, size=1.0)
        p = put(s, cir, ref, xp, ybot + 8.89)
        bk.take(ref, "1", net)
        bk.take(ref, "2", "GND")
        s.wire(p["2"], (xp, p["2"][1] + 3.81))
        s.rail("GND", (xp, p["2"][1] + 3.81))
    bk.take("U2", "15", "")
    s.nc(u["15"])
    for pad in ("8", "17"):
        bk.take("U2", pad, "GND")
    s.wire(u["8"], (u["8"][0], u["8"][1] + 5.08))
    s.rail("GND", (u["8"][0], u["8"][1] + 5.08))

    bank(s, cir, bk, ["C10", "C13"], x - 45.72, y + 60.96, "VBUS")
    bank(s, cir, bk, ["C11", "C14"], x - 2.54, y + 60.96, "VSYS")
    bank(s, cir, bk, ["C12", "C15"], x + 40.64, y + 60.96, "VBAT")

    j2 = put(s, cir, "J2", x + 88.9, y + 60.96, hide_value=True)
    bk.take("J2", "1", "VBAT")
    bk.take("J2", "2", "GND")
    s.wire(j2["1"], (j2["1"][0] - 7.62, j2["1"][1]))
    s.rail("VBAT", (j2["1"][0] - 7.62, j2["1"][1]))
    s.wire(j2["2"], (j2["2"][0] - 7.62, j2["2"][1]))
    s.rail("GND", (j2["2"][0] - 7.62, j2["2"][1]))

    s.note("EN2 = 1, EN1 = 0 selects the R_ILIM input limit (1610/1.62k = "
           "0.99 A). R12 = 45.3k gives a 6.0 h safety timer (10 x 48 s/kohm); "
           "the legal window is 18-72k. ITERM is left open on purpose: pin "
           "15 is ITERM on the '74 and open selects the 10% default. VSYS "
           "is the power-path output and feeds the LDO AND the motor, so the "
           "toy runs on the cable with a flat cell. The PowerPad carries up "
           "to 1.0 W and must go to a stitched pour. J2 is the cell.",
           x - 46.0, y + 93.98, 165.0)
    s.end()


# --- Block 3 ---------------------------------------------------------------
def blk_ldo(s, cir, bk, x, y):
    s.begin("Block 3 — system LDO, always on")
    u = put(s, cir, "U3", x, y)
    bk.take("U3", "1", "VSYS")
    bk.take("U3", "3", "VSYS")
    xin = u["1"][0] - 10.16
    s.wire(u["1"], (xin, u["1"][1]))
    s.wire(u["3"], (xin, u["3"][1]))
    s.wire((xin, u["1"][1]), (xin, u["3"][1]))
    s.junction((xin, u["1"][1]))
    s.wire((xin, u["1"][1]), (xin, u["1"][1] - 6.35))
    s.rail("VSYS", (xin, u["1"][1] - 6.35))
    bk.take("U3", "5", "3V3_SYS")
    s.wire(u["5"], (u["5"][0] + 10.16, u["5"][1]))
    s.wire((u["5"][0] + 10.16, u["5"][1]), (u["5"][0] + 10.16, u["5"][1] - 6.35))
    s.rail("3V3_SYS", (u["5"][0] + 10.16, u["5"][1] - 6.35))
    bk.take("U3", "4", "")
    s.nc(u["4"])
    bk.take("U3", "2", "GND")
    s.wire(u["2"], (u["2"][0], u["2"][1] + 5.08))
    s.rail("GND", (u["2"][0], u["2"][1] + 5.08))
    vdrop(s, cir, bk, "C20", x - 22.86, y + 12.7)
    bk.take("C20", "1", "VSYS")
    s.wire((x - 22.86, y + 12.7), (x - 22.86, y + 8.89))
    s.rail("VSYS", (x - 22.86, y + 8.89))
    bank(s, cir, bk, ["C21", "C22"], x + 15.24, y + 12.7, "3V3_SYS")
    s.note("SOT-23-5: 1 = IN, 5 = OUT, EN tied to IN. 25 uA Iq. C22 is "
           "bulk for the radio's TX bursts. The motor does NOT run from "
           "this rail (Block 4 takes VSYS directly).",
           x - 26.0, y + 41.91, 104.0)
    s.end()


# --- battery sense ----------------------------------------------------------
def blk_sense(s, cir, bk, x, y):
    s.begin("Battery voltage sense")
    r60 = put(s, cir, "R60", x, y)
    bk.take("R60", "1", "VBAT")
    bk.take("R60", "2", "VBAT_SENSE")
    s.wire(r60["1"], (x, y - 7.62))
    s.rail("VBAT", (x, y - 7.62))
    ymid = r60["2"][1] + 3.81
    s.wire(r60["2"], (x, ymid))
    r61 = put(s, cir, "R61", x, ymid + 3.81)
    bk.take("R61", "1", "VBAT_SENSE")
    bk.take("R61", "2", "GND")
    s.wire(r61["2"], (x, r61["2"][1] + 3.81))
    s.rail("GND", (x, r61["2"][1] + 3.81))
    s.junction((x, ymid))
    s.wire((x, ymid), (x + 12.7, ymid))
    vdrop(s, cir, bk, "C64", x + 12.7, ymid)
    bk.take("C64", "1", "VBAT_SENSE")
    s.junction((x + 12.7, ymid))
    s.wire((x + 12.7, ymid), (x + 25.4, ymid))
    s.glabel("VBAT_SENSE", (x + 25.4, ymid))
    s.note("1M/1M draws 2.1 uA and needs no switch. C64 sources the SAADC "
           "sampling charge from the 500k source impedance — use a long "
           "acquisition time. AIN0 = P0.02, module pad 7.",
           x - 8.0, r61["2"][1] + 12.7, 96.0)
    s.end()


# --- Block 4 ---------------------------------------------------------------
def motor_channel(s, cir, bk, n, x, y):
    """One low-side channel: gate resistor + pull-down, FET, flyback diode.
    Returns the drain node's (x, y) at the right-hand end of its run."""
    q, rg, rpd, d = f"Q{n}", f"R{40 + 2 * (n - 1)}", f"R{41 + 2 * (n - 1)}", f"D{2 + n}"
    qf = put(s, cir, q, x + 38.1, y)
    bk.take(q, "1", f"MOTOR{n}_G")
    bk.take(q, "2", "GND")
    bk.take(q, "3", f"MOTOR{n}_SW")
    s.wire(qf["2"], (qf["2"][0], qf["2"][1] + 5.08))
    s.rail("GND", (qf["2"][0], qf["2"][1] + 5.08))
    # gate: 100R in series from the GPIO, 100k to ground so the FET is off
    # until firmware exists (A10)
    xg = qf["1"][0] - 17.78
    r = put(s, cir, rg, xg, qf["1"][1], rot=90)
    bk.take(rg, "1", f"MOTOR{n}_PWM")
    bk.take(rg, "2", f"MOTOR{n}_G")
    s.wire(r["2"], qf["1"])
    s.wire(r["1"], (r["1"][0] - 12.7, qf["1"][1]))
    s.glabel(f"MOTOR{n}_PWM", (r["1"][0] - 12.7, qf["1"][1]), just="right")
    xd = xg + 8.89
    s.junction((xd, qf["1"][1]))
    s.label(f"MOTOR{n}_G", (xg + 5.08, qf["1"][1]), size=1.0)
    vdrop(s, cir, bk, rpd, xd, qf["1"][1], ref_off=(2.6, 2.0))
    bk.take(rpd, "1", f"MOTOR{n}_G")
    # drain: the flyback diode to VSYS, and the run out to the connector
    yd = qf["3"][1]
    xm = qf["3"][0] + 12.7
    s.wire(qf["3"], (xm, yd))
    s.label(f"MOTOR{n}_SW", (qf["3"][0] + 5.08, yd), size=1.0)
    dd = put(s, cir, d, xm, yd - 7.62, rot=180)   # cathode up, to VSYS
    bk.take(d, "1", "VSYS")
    bk.take(d, "2", f"MOTOR{n}_SW")
    s.wire((xm, yd), dd["2"])
    s.wire(dd["1"], (xm, dd["1"][1] - 3.81))
    s.rail("VSYS", (xm, dd["1"][1] - 3.81))
    s.junction((xm, yd))
    return (xm, yd)


def blk_motor(s, cir, bk, x, y):
    s.begin("Block 4 — motors: two low-side FET channels from VSYS")
    m1 = motor_channel(s, cir, bk, 1, x, y + 20.32)
    m2 = motor_channel(s, cir, bk, 2, x, y + 60.96)
    # The connector: pin 2 (M1) sits 2 rows under the VSYS pin, pin 4 (M2)
    # 4 rows under that -- 10.16 mm apart -- so place it so pin 2 lands on
    # channel 1's drain run and bring channel 2's up to pin 4.
    j4 = put(s, cir, "J4", m1[0] + 40.64, m1[1] + 2.54, hide_value=True)
    assert abs(j4["2"][1] - m1[1]) < 0.01, "J4 pin 2 must sit on channel 1's drain run"
    bk.take("J4", "2", "MOTOR1_SW")
    bk.take("J4", "4", "MOTOR2_SW")
    bk.take("J4", "1", "VSYS")
    bk.take("J4", "3", "VSYS")
    s.wire(m1, j4["2"])
    xr = j4["4"][0] - 10.16
    s.wire(m2, (xr, m2[1]))
    s.wire((xr, m2[1]), (xr, j4["4"][1]))
    s.wire((xr, j4["4"][1]), j4["4"])
    s.wire(j4["1"], (j4["1"][0] - 6.35, j4["1"][1]))
    s.rail("VSYS", (j4["1"][0] - 6.35, j4["1"][1]), rot=90)
    bank(s, cir, bk, ["C40", "C41", "C42", "C43"], x + 5.08, y + 93.98, "VSYS")
    s.note("Two identical PWM channels: AO3400A low side (30 mOhm from a "
           "3.3 V gate), B5819W 1 A Schottky across each motor for the "
           "off-time current, 2 x 22 u of bulk at the connector so the PWM "
           "ripple stays off the LDO's input. R41/R43 matter: an nRF GPIO "
           "floats from reset until firmware drives it, and a floating gate "
           "is a toy that buzzes on the bench. J4 is one 4-way JST PH for "
           "both leads: 1 VSYS, 2 M1, 3 VSYS, 4 M2. Each channel is sized "
           "for 1 A.",
           x - 4.0, y + 124.46, 140.0)
    s.end()


# --- Blocks 5 + 6 -----------------------------------------------------------
def blk_sensors(s, cir, bk, x, y):
    s.begin("Blocks 5 + 6 — switched sensor rail, HX711 load-cell ADC and port")

    # --- load switch ---------------------------------------------------
    u5 = put(s, cir, "U5", x, y)
    bk.take("U5", "1", "3V3_SYS")
    s.wire(u5["1"], (u5["1"][0] - 8.89, u5["1"][1]))
    s.rail("3V3_SYS", (u5["1"][0] - 8.89, u5["1"][1]))
    bk.take("U5", "3", "SENS_EN")
    s.wire(u5["3"], (u5["3"][0] - 25.4, u5["3"][1]))
    s.glabel("SENS_EN", (u5["3"][0] - 25.4, u5["3"][1]), just="right")
    xpd = u5["3"][0] - 17.78
    s.junction((xpd, u5["3"][1]))
    vdrop(s, cir, bk, "R50", xpd, u5["3"][1], ref_off=(-6.9, 0.0))
    bk.take("R50", "1", "SENS_EN")
    bk.take("U5", "2", "GND")
    s.wire(u5["2"], (u5["2"][0], u5["2"][1] + 5.08))
    s.rail("GND", (u5["2"][0], u5["2"][1] + 5.08))
    bk.take("U5", "4", "CT_SENS")
    s.wire(u5["4"], (u5["4"][0] - 8.89, u5["4"][1]))
    s.label("CT_SENS", (u5["4"][0] - 7.4, u5["4"][1]), size=1.0)
    c50 = put(s, cir, "C50", u5["4"][0] - 8.89, u5["4"][1] + 3.81,
              ref_off=(-4.5, -2.0))
    bk.take("C50", "1", "CT_SENS")
    bk.take("C50", "2", "GND")
    s.wire(c50["2"], (c50["2"][0], c50["2"][1] + 3.81))
    s.rail("GND", (c50["2"][0], c50["2"][1] + 3.81))
    bk.take("U5", "6", "3V3_SENS")
    bk.take("U5", "5", "3V3_SENS")
    xq = u5["6"][0] + 8.89
    s.wire(u5["6"], (xq, u5["6"][1]))
    s.wire(u5["5"], (xq, u5["5"][1]))
    s.wire((xq, u5["6"][1]), (xq, u5["5"][1]))
    s.junction((xq, u5["6"][1]))
    s.wire((xq, u5["6"][1]), (xq, u5["6"][1] - 6.35))
    s.rail("3V3_SENS", (xq, u5["6"][1] - 6.35))
    vdrop(s, cir, bk, "C51", x - 38.1, y + 20.32, ref_off=(-8.4, -0.4))
    bk.take("C51", "1", "3V3_SYS")
    s.wire((x - 38.1, y + 20.32), (x - 38.1, y + 16.51))
    s.rail("3V3_SYS", (x - 38.1, y + 16.51))
    bank(s, cir, bk, ["C52"], x + 5.08, y + 20.32, "3V3_SENS")

    # --- HX711 ----------------------------------------------------------
    u = put(s, cir, "U4", x + 91.44, y + 20.32)
    for pin in ("1", "3", "16"):
        bk.take("U4", pin, "3V3_SENS")
    yb = u["1"][1] - 7.62
    for pin in ("1", "3", "16"):
        s.wire(u[pin], (u[pin][0], yb))
    s.wire((u["1"][0], yb), (u["16"][0], yb))
    s.junction((u["3"][0], yb))
    s.wire((u["3"][0], yb), (u["3"][0], yb - 5.08))
    s.rail("3V3_SENS", (u["3"][0], yb - 5.08))
    for pin in ("5", "4"):
        bk.take("U4", pin, "GND")
    yg = u["5"][1] + 5.08
    s.wire(u["5"], (u["5"][0], yg))
    s.wire(u["4"], (u["4"][0], yg))
    s.wire((u["5"][0], yg), (u["4"][0], yg))
    xgm = q((u["5"][0] + u["4"][0]) / 2.0)
    s.junction((xgm, yg))
    s.wire((xgm, yg), (xgm, yg + 3.81))
    s.rail("GND", (xgm, yg + 3.81))
    # bridge inputs out to the left, to the port below
    for pin, net in (("8", "LC_A_P"), ("7", "LC_A_N")):
        bk.take("U4", pin, net)
        s.wire(u[pin], (u[pin][0] - 15.24, u[pin][1]))
        s.glabel(net, (u[pin][0] - 15.24, u[pin][1]), just="right")
    # channel B unused: both inputs to ground
    for pin in ("10", "9"):
        bk.take("U4", pin, "GND")
    xg2 = u["10"][0] - 5.08
    s.wire(u["10"], (xg2, u["10"][1]))
    s.wire(u["9"], (xg2, u["9"][1]))
    s.wire((xg2, u["10"][1]), (xg2, u["9"][1]))
    s.junction((xg2, u["9"][1]))
    s.wire((xg2, u["9"][1]), (xg2, u["9"][1] + 3.81))
    s.rail("GND", (xg2, u["9"][1] + 3.81))
    # host interface
    bk.take("U4", "12", "HX_DOUT")
    s.wire(u["12"], (u["12"][0] + 25.4, u["12"][1]))
    s.glabel("HX_DOUT", (u["12"][0] + 25.4, u["12"][1]))
    bk.take("U4", "11", "HX_SCK_IN")
    s.label("HX_SCK_IN", (u["11"][0] + 2.0, u["11"][1]), size=1.0)
    r55 = put(s, cir, "R55", u["11"][0] + 12.7, u["11"][1], rot=270,
              ref_off=(-2.5, 4.2))
    bk.take("R55", "2", "HX_SCK_IN")
    bk.take("R55", "1", "HX_SCK")
    s.wire(u["11"], r55["2"])
    s.wire(r55["1"], (r55["1"][0] + 8.89, r55["1"][1]))
    s.glabel("HX_SCK", (r55["1"][0] + 8.89, r55["1"][1]))
    # RATE = DVDD (80 SPS), XI = 0 (on-chip oscillator)
    bk.take("U4", "15", "3V3_SENS")
    xr = u["15"][0] + 5.08
    s.wire(u["15"], (xr, u["15"][1]))
    s.wire((xr, u["15"][1]), (xr, u["15"][1] - 5.08))
    s.rail("3V3_SENS", (xr, u["15"][1] - 5.08))
    bk.take("U4", "14", "GND")
    xi = u["14"][0] + 10.16
    s.wire(u["14"], (xi, u["14"][1]))
    s.wire((xi, u["14"][1]), (xi, u["14"][1] + 5.08))
    s.rail("GND", (xi, u["14"][1] + 5.08))
    for pin in ("13", "2", "6"):
        bk.take("U4", pin, "")
        s.nc(u[pin])
    bank(s, cir, bk, ["C60", "C61", "C62"], u["1"][0] + 17.78,
         u["1"][1] - 35.56, "3V3_SENS")

    # --- the port -------------------------------------------------------
    j5 = put(s, cir, "J5", x + 38.1, y + 55.88, hide_value=True)
    bk.take("J5", "1", "3V3_SENS")
    xr5 = j5["1"][0] - 7.62
    s.wire(j5["1"], (xr5, j5["1"][1]))
    s.wire((xr5, j5["1"][1]), (xr5, j5["1"][1] - 6.35))
    s.rail("3V3_SENS", (xr5, j5["1"][1] - 6.35))
    for pin, net in (("2", "LC_A_N"), ("3", "LC_A_P")):
        bk.take("J5", pin, net)
        s.wire(j5[pin], (j5[pin][0] - 17.78, j5[pin][1]))
        s.glabel(net, (j5[pin][0] - 17.78, j5[pin][1]), just="right")
    bk.take("J5", "4", "GND")
    bk.take("J5", "MP", "GND")
    s.wire(j5["4"], (j5["4"][0], j5["4"][1] + 5.08))
    s.rail("GND", (j5["4"][0], j5["4"][1] + 5.08))

    s.note("The HX711 runs WITHOUT its analog regulator: VSUP tied to AVDD, "
           "VFB to ground, BASE and VBG open (datasheet, Power Supply "
           "Options). XI = 0 selects the on-chip oscillator; RATE = DVDD "
           "is 80 SPS. Full scale is +-0.5 AVDD/128 = +-12.9 mV; a 2 mV/V "
           "cell on 3.3 V excitation gives 6.6 mV. The whole rail is "
           "switched (U5) because a 350 ohm bridge draws 9.4 mA forever; "
           "DVDD is therefore switched too, so firmware must tristate "
           "HX_SCK before gating, and R55 caps the current into an "
           "unpowered pin if it does not. QOD to VOUT or the rail never "
           "discharges; 100k so ON cannot float. J5: E+ A- A+ E-.",
           x - 30.0, y + 88.9, 180.0)
    s.end()


# --- Block 7 ---------------------------------------------------------------
def blk_pressure(s, cir, bk, x, y):
    s.begin("Block 7 — pressure sensor port (analog or I2C)")
    j = put(s, cir, "J6", x, y, hide_value=True)
    # I2C pair with pull-ups on the SWITCHED rail (Z5). SDA's hangs above
    # its line close in; SCL's further out, past the end of SDA's wire.
    for pin, net, dx, xr in (("4", "SDA", 20.32, 10.16),
                             ("5", "SCL", 33.02, 27.94)):
        bk.take("J6", pin, net)
        s.wire(j[pin], (j[pin][0] - dx, j[pin][1]))
        s.glabel(net, (j[pin][0] - dx, j[pin][1]), just="right")
        xp = j[pin][0] - xr
        s.junction((xp, j[pin][1]))
        r = put(s, cir, "R71" if pin == "4" else "R72", xp, j[pin][1] - 8.89,
                ref_off=(-4.6, 0.0))
        bk.take(r and ("R71" if pin == "4" else "R72"), "1", "3V3_SENS")
        bk.take("R71" if pin == "4" else "R72", "2", net)
        s.wire(r["2"], (xp, j[pin][1]))
        s.wire(r["1"], (xp, r["1"][1] - 3.81))
        s.rail("3V3_SENS", (xp, r["1"][1] - 3.81))
    # analog line: 10k series, 100n to ground, into AIN1
    bk.take("J6", "3", "PRESS_IN")
    r70 = put(s, cir, "R70", j["3"][0] - 12.7, j["3"][1], rot=270,
              ref_off=(-3.5, 4.2))
    bk.take("R70", "1", "PRESS_IN")
    bk.take("R70", "2", "PRESS_AIN")
    s.wire(r70["1"], j["3"])
    s.label("PRESS_IN", (r70["1"][0] + 1.0, j["3"][1]), size=1.0)
    xa = r70["2"][0] - 7.62
    s.wire(r70["2"], (xa, j["3"][1]))
    s.junction((xa, j["3"][1]))
    vdrop(s, cir, bk, "C70", xa, j["3"][1])
    bk.take("C70", "1", "PRESS_AIN")
    s.wire((xa, j["3"][1]), (xa - 10.16, j["3"][1]))
    s.glabel("PRESS_AIN", (xa - 10.16, j["3"][1]), just="right")
    # supply at the bottom of the connector, rail dropping down
    bk.take("J6", "1", "3V3_SENS")
    xs = j["1"][0] - 5.08
    s.wire(j["1"], (xs, j["1"][1]))
    s.wire((xs, j["1"][1]), (xs, j["1"][1] + 6.35))
    s.rail("3V3_SENS", (xs, j["1"][1] + 6.35), rot=180)
    bk.take("J6", "2", "GND")
    bk.take("J6", "MP", "GND")
    s.wire(j["2"], (j["2"][0], j["2"][1] + 5.08))
    s.rail("GND", (j["2"][0], j["2"][1] + 5.08))
    s.note("One 5-way port, two kinds of sensor. Analog (a ratiometric "
           "0..3.3 V part): its output goes through 10k/100n (~160 Hz) "
           "into AIN1 = P0.03; the 10k also limits what a 5 V sensor "
           "plugged in by mistake can push into the pin's clamps. I2C (a "
           "digital barometric or gauge sensor): 4.7k pull-ups on 3V3_SENS, "
           "so an unpowered sensor is not back-fed through them. The nRF52840 "
           "puts TWIM on any pins.",
           x - 50.0, j["2"][1] + 16.51, 120.0)
    s.end()


# --- Block 8 ---------------------------------------------------------------
def blk_mcu(s, cir, bk, cx, cy):
    s.begin("Block 8 — nRF52840 module (E73-2G4M08S1C, onboard antenna)")
    u = put(s, cir, "U1", cx, cy)

    for pad in ("19", "23"):
        bk.take("U1", pad, "3V3_SYS")
    xp = u["19"][0]
    s.wire(u["19"], (xp, u["19"][1] - 7.62))
    s.wire(u["23"], (u["23"][0], u["23"][1] - 7.62))
    s.wire((xp, u["19"][1] - 7.62), (u["23"][0], u["23"][1] - 7.62))
    s.junction((xp, u["19"][1] - 7.62))
    s.wire((xp, u["19"][1] - 7.62), (xp, u["19"][1] - 11.43))
    s.rail("3V3_SYS", (xp, u["19"][1] - 11.43))
    bk.take("U1", "27", "VBUS")
    yv = u["27"][1] - 7.62
    s.wire(u["27"], (u["27"][0], yv))
    s.junction((u["27"][0], yv))
    s.wire((u["27"][0], yv), (u["27"][0], yv - 3.81))
    s.rail("VBUS", (u["27"][0], yv - 3.81))
    c65 = put(s, cir, "C65", u["27"][0] + 8.89, yv, rot=90,
              ref_off=(-1.0, -6.4))
    bk.take("C65", "1", "VBUS")
    bk.take("C65", "2", "GND")
    s.wire((u["27"][0], yv), c65["1"])
    s.wire(c65["2"], (c65["2"][0] + 3.81, yv))
    s.rail("GND", (c65["2"][0] + 3.81, yv), rot=90)

    for pad in ("5", "21", "24"):
        bk.take("U1", pad, "GND")
    s.wire(u["5"], (u["5"][0], u["5"][1] + 5.08))
    s.rail("GND", (u["5"][0], u["5"][1] + 5.08))
    bk.take("U1", "25", "")
    s.nc(u["25"])
    for pad, name in sorted(((p, n) for n, p in E73.items()), key=lambda t: t[0]):
        if str(pad) in u and cir.components["U1"].pins[str(pad)] == "" \
                and str(pad) != "25":
            bk.take("U1", pad, "")
            s.nc(u[str(pad)])

    # left edge: programming, USB, the two UI lines
    for pad, net in (("26", "RESET_N"), ("37", "SWDIO"), ("39", "SWCLK"),
                     ("29", "USB_DM"), ("31", "USB_DP"),
                     (str(E73["P0.13"]), "BTN"), (str(E73["P0.24"]), "LED_STAT")):
        bk.take("U1", pad, net)
        s.wire(u[pad], (u[pad][0] - 17.78, u[pad][1]))
        s.glabel(net, (u[pad][0] - 17.78, u[pad][1]), just="right")
    for pad in ("11", "13"):
        bk.take("U1", pad)

    # right edge: everything the satellites talk to
    for pad_name, net in ROLE.items():
        pad = str(E73[pad_name])
        if net in ("BTN", "LED_STAT"):
            continue
        bk.take("U1", pad, net)
        s.wire(u[pad], (u[pad][0] + 17.78, u[pad][1]))
        s.glabel(net, (u[pad][0] + 17.78, u[pad][1]))

    bank(s, cir, bk, ["C80", "C81"], cx + 7.62, u["19"][1] - 38.1, "3V3_SYS")
    draw_xtal(s, cir, bk, u)
    s.note("43 pads: 28 castellated plus 15 bottom-only interior pads, so "
           "this board needs a stencil. Every GPIO used here is on an EDGE "
           "pad; only GND (24) is interior. The ceramic antenna is at the "
           "pad-free end of the body: that end sits at the board edge with "
           "no copper under it on any layer. Pad 26 is P0.18, the only pin "
           "the nRF52840 can use as nRESET. Y1 is Nordic's reference LFXO: "
           "a 3215 9 pF-CL part with 12 pF NP0 loads.",
           cx - 40.0, cy + 74.0, 150.0)
    s.end()
    return u


def draw_xtal(s, cir, bk, u):
    """32.768 kHz LFXO, wired straight onto the module's XL1/XL2 pads."""
    x1, y1 = u["11"]      # XL1, the upper pad
    x2, y2 = u["13"]      # XL2, the lower pad
    yc = q((y1 + y2) / 2.0)
    xa = x1 - 22.86
    xb = x1 - 53.34

    s.label("XL1", (x1 - 15.24, y1), size=1.0)
    s.label("XL2", (x2 - 15.24, y2), size=1.0)
    s.wire((x1, y1), (xb, y1))
    s.wire((xb, y1), (xb, yc))
    s.wire((x2, y2), (xa, y2))
    s.wire((xa, y2), (xa, yc))

    xc = q((xa + xb) / 2.0)
    p = put(s, cir, "Y1", xc, yc, hide_value=True, ref_off=(-3.0, -4.4))
    bk.take("Y1", "1", "XL1")
    bk.take("Y1", "2", "XL2")
    s.wire((xb, yc), p["1"])
    s.wire(p["2"], (xa, yc))

    ycap = yc + 8.89
    for ref, xt in (("C82", q(xb + 5.08)), ("C83", q(xa - 5.08))):
        s.junction((xt, yc))
        s.wire((xt, yc), (xt, ycap))
        c = put(s, cir, ref, xt, ycap + 3.81, ref_off=(-9.4, -0.4))
        bk.take(ref, "1")
        bk.take(ref, "2", "GND")
        s.wire(c["2"], (xt, c["2"][1] + 3.81))
        s.rail("GND", (xt, c["2"][1] + 3.81))
    s.text("32.768 kHz LFXO", xb - 4.0, yc - 12.7, size=1.6, bold=True)


def blk_swd(s, cir, bk, x, y):
    s.begin("SWD — Tag-Connect TC2030-IDC-NL (back side)")
    j = put(s, cir, "J3", x, y, hide_value=True)
    bk.take("J3", "1", "3V3_SYS")
    s.wire(j["1"], (j["1"][0] - 7.62, j["1"][1]))
    s.rail("3V3_SYS", (j["1"][0] - 7.62, j["1"][1]))
    for pin, net in (("2", "SWDIO"), ("3", "RESET_N"), ("4", "SWCLK")):
        bk.take("J3", pin, net)
        s.wire(j[pin], (j[pin][0] - 15.24, j[pin][1]))
        s.glabel(net, (j[pin][0] - 15.24, j[pin][1]), just="right")
    bk.take("J3", "5", "GND")
    s.wire(j["5"], (j["5"][0] - 7.62, j["5"][1]))
    s.rail("GND", (j["5"][0] - 7.62, j["5"][1]))
    bk.take("J3", "6", "")
    s.nc(j["6"])
    s.note("Pads only, on the BACK of the board where the plug's 9.9 x "
           "7.2 mm head has room. Standard ARM order.",
           x - 20.0, y + 20.0, 76.0)
    s.end()


def blk_ui(s, cir, bk, x, y):
    s.begin("User button and status LED")
    sw = put(s, cir, "SW1", x, y, hide_value=True)
    bk.take("SW1", "1", "BTN")
    bk.take("SW1", "2", "GND")
    s.wire(sw["1"], (sw["1"][0] - 12.7, sw["1"][1]))
    s.glabel("BTN", (sw["1"][0] - 12.7, sw["1"][1]), just="right")
    s.wire(sw["2"], (sw["2"][0] + 7.62, sw["2"][1]))
    s.rail("GND", (sw["2"][0] + 7.62, sw["2"][1]))

    yl = y + 20.32
    r = put(s, cir, "R62", x, yl, rot=90)
    bk.take("R62", "1", "LED_STAT")
    bk.take("R62", "2", "LED_STAT_A")
    s.wire(r["1"], (r["1"][0] - 12.7, r["1"][1]))
    s.glabel("LED_STAT", (r["1"][0] - 12.7, r["1"][1]), just="right")
    d = put(s, cir, "D2", r["2"][0] + 8.89, yl, hide_value=True)
    bk.take("D2", "2", "LED_STAT_A")       # anode, top
    bk.take("D2", "1", "GND")              # cathode, bottom
    s.wire(r["2"], (d["2"][0], yl))
    s.label("LED_STAT_A", (r["2"][0] + 1.5, yl), size=1.0)
    s.wire((d["2"][0], yl), d["2"])
    s.wire(d["1"], (d["1"][0], d["1"][1] + 3.81))
    s.rail("GND", (d["1"][0], d["1"][1] + 3.81))
    s.note("Side-actuated button on the left board edge, internal pull-up "
           "on P0.13. Green 0603 at ~1.5 mA from 330R; drive P0.24 "
           "high-drive.", x - 16.0, yl + 20.0, 76.0)
    s.end()


def blk_flags(s, x, y):
    """One PWR_FLAG per rail: every supply arrives through a passive pin."""
    s.begin("Power flags — the ERC root for each rail")
    rails = ["GND", "VBUS", "VSYS", "VBAT", "3V3_SYS", "3V3_SENS"]
    for i, rail in enumerate(rails):
        xf = q(x + i * 25.4)
        s.place("PWR_FLAG", f"#FLG{i + 1}", "PWR_FLAG", xf, y)
        s.wire((xf, y), (xf + 7.62, y))
        s.rail(rail, (xf + 7.62, y))
    s.note("These carry no copper and appear in no netlist. They exist "
           "because every rail here is fed through a pin the symbols "
           "declare passive, so ERC would otherwise report six "
           "undriven power nets.", x - 4.0, y + 17.78, 150.0)
    s.end()


# ---------------------------------------------------------------------------
def build_sheet(design, cir):
    s = Sch()
    s.defpassives()
    s.defflag()
    defdiode(s)
    s.defbox("mcu_module", "E73-2G4M08S1C", module_sides())
    for part, sides in IC_SIDES.items():
        c = next(c for c in cir.components.values() if c.part == part)
        s.defbox(part, c.value, sides, min_w=IC_MIN_W.get(part, 0.0))
    bk = Book(cir.components)

    s.text("bluebuzz — generated schematic", 16, 15, size=4.0,
           bold=True, frame=False)
    s.text(f"{len(cir.components)} components / {len(cir.nets)} nets / "
           f"{design['board']['layers']}-layer.  "
           "Bluetooth vibrator controller: nRF52840 module, USB-C charger "
           "with power path, two low-side motor channels from VSYS, HX711 "
           "load-cell ADC and a pressure-sensor port on a switched 3.3 V "
           "rail.  Power rails are power symbols; only cross-block signals "
           "use global labels.  Generated from scripts/circuit.py — do not "
           "hand-edit; rebuild with `python3 build.py --only schematic`.",
           16, 21, size=1.8, frame=False)

    # Anchors are packed by hand against the measured block boxes; run with
    # SCH_LAYOUT=1 to print them when a netlist change resizes something.
    blk_usb(s, cir, bk, 40.64, 99.06)
    blk_charger(s, cir, bk, 99.06, 231.14)
    blk_ldo(s, cir, bk, 299.72, 81.28)
    blk_sense(s, cir, bk, 299.72, 172.72)
    blk_swd(s, cir, bk, 299.72, 281.94)
    blk_ui(s, cir, bk, 299.72, 381.0)
    blk_motor(s, cir, bk, 469.9, 81.28)
    blk_sensors(s, cir, bk, 469.9, 284.48)
    blk_pressure(s, cir, bk, 830.58, 81.28)
    blk_mcu(s, cir, bk, 830.58, 233.68)
    blk_flags(s, 744.22, 350.52)

    bk.report()
    s.check_frames(verbose=bool(os.environ.get("SCH_LAYOUT")))
    clashes = s.check_text(verbose=bool(os.environ.get("SCH_LAYOUT")))
    if clashes and os.environ.get("SCH_ALLOW_TEXT_CLASH"):
        print(f"  WARNING: {len(clashes)} text clashes, emitted anyway")
        for m in clashes:
            print("    " + m)
        clashes = []
    assert not clashes, (f"{len(clashes)} text clashes — a reference, value "
                         "or note lands on a wire or on other text "
                         "(SCH_LAYOUT=1 lists them, SCH_ALLOW_TEXT_CLASH=1 "
                         "emits anyway):\n  " + "\n  ".join(clashes))
    placed = {r for r in s.refs if not r.startswith("#PWR")}
    missing = sorted(set(cir.components) - placed)
    assert not missing, f"components not drawn: {missing}"
    return s


# ---------------------------------------------------------------------------
def verify_netlist(cir):
    """Round-trip the finished sheet through KiCad and diff it against
    circuit.py. This is what makes the hand-authored layout trustworthy."""
    xml = OUT.parent / "bluebuzz-netlist.xml"
    r = subprocess.run(["kicad-cli", "sch", "export", "netlist",
                        "--format", "kicadxml", "-o", str(xml), str(OUT)],
                       capture_output=True, text=True)
    if r.returncode:
        print("  WARNING: netlist export failed, cannot verify:",
              r.stderr.strip())
        return False
    root = ET.parse(xml).getroot()
    got = defaultdict(set)
    for net in root.find("nets"):
        name = net.get("name")
        for node in net.findall("node"):
            got[name].add((node.get("ref"), node.get("pin")))
    want = defaultdict(set)
    for ref, c in cir.components.items():
        for pad, net in c.pins.items():
            if net:
                want[net].add((ref, pad))
    got_sets = {frozenset(v): k for k, v in got.items() if len(v) > 1}
    problems = []
    for net, pins in sorted(want.items()):
        fs = frozenset(pins)
        if fs in got_sets:
            if got_sets[fs] != net:
                problems.append(f"net {net}: drawn as {got_sets[fs]!r}")
            continue
        drawn = got.get(net)
        if drawn is None:
            problems.append(f"net {net}: missing from the sheet entirely")
        else:
            extra = drawn - pins
            short = pins - drawn
            if extra:
                problems.append(f"net {net}: sheet also has "
                                + ", ".join(f"{a}.{b}" for a, b in sorted(extra)))
            if short:
                problems.append(f"net {net}: sheet is missing "
                                + ", ".join(f"{a}.{b}" for a, b in sorted(short)))
    xml.unlink(missing_ok=True)
    if problems:
        print("  NETLIST MISMATCH (sheet vs circuit.py):")
        for p in problems[:80]:
            print("   ", p)
        raise SystemExit(1)
    print(f"  netlist verified against circuit.py: {len(want)} nets match")
    return True


def main():
    design = load_design()
    cir = build_circuit(design)
    s = build_sheet(design, cir)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(s.render())
    print(f"wrote {OUT}: {len(s.defs)} symbols, {len(cir.components)} "
          f"components, {len(cir.nets)} nets, {len(s.frames)} blocks")

    verify_netlist(cir)
    for args, label in (
            (["--exclude-drawing-sheet", "-o", str(OUT.parent)], "svg"),
            (["-o", str(OUT.parent / "bluebuzz-schematic.pdf")], "pdf")):
        r = subprocess.run(["kicad-cli", "sch", "export", label] + args
                           + [str(OUT)], capture_output=True, text=True)
        if r.returncode:
            print(f"  WARNING: {label} export failed: {r.stderr.strip()}")


if __name__ == "__main__":
    main()
