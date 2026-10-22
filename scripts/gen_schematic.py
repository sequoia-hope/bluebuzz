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

Output: out/bluebuzz-rm2.kicad_sch (+ .svg/.pdf).
Regenerate with `python3 build.py --only schematic`.
"""
import functools
import math
import os
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from circuit import DNP, TACTILE, TACTILE_COLS, DVDD_PINS, GPIO_PINS, IOVDD_PINS, ROLE, build_circuit, load_design, load_parts  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out" / "bluebuzz-rm2.kicad_sch"

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

        # A top and a bottom pin in the same column write their names toward
        # each other down the middle of the box (the 1010 LED's VDD and GND
        # printed on top of each other). Grow the box a slot at each end
        # until both names fit with a gap between them.
        def cols(side):
            x0 = -(len(side) - 1) * GRID / 2.0
            return [(x0 + GRID * i, len(p[1])) for i, p in enumerate(side) if p]
        need = max([(nt + nb) * GRID / 2.0 + 2 * 0.508 + 1.0
                    for xt, nt in cols(T) for xb, nb in cols(B) if abs(xt - xb) < 1.5] or [0])
        while (max(len(L), len(R), 1) + 1) * GRID < need:
            L = [None] + L + [None]
            R = [None] + R + [None]
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
              hide_value=False, ref_off=None, in_bom=True, dnp=False):
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
            if ref_off == "corner":
                # beside the top-left corner, clear of tall supply stubs
                rx, ry, rj = x - hw - 1.27, y - hh - 0.6, "right bottom"
                ref_off = None
            # The value goes under the box, but bottom pins drop their wires
            # from the middle of that edge straight into a ground symbol, so
            # run the value leftwards out of the centre instead of starting
            # at the left edge and crossing it.
            vx = x - 3.81 if d.has_bot else x - hw
            vy = y + hh + (4.4 if d.has_bot else 3.4)
            vj = "right bottom" if d.has_bot else "left bottom"
            if ref_off == "below-right":
                # value under the box's bottom-right corner, clear of the
                # ground stub that drops from the middle of the bottom edge
                vx, vy, vj = x + hw, y + hh + 4.4, "right bottom"
                ref_off = None
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
                 "\t\t(unit 1) (exclude_from_sim no)"
                 f" (in_bom {'yes' if in_bom else 'no'})"
                 f" (on_board yes) (dnp {'yes' if dnp else 'no'})",
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
        parts.append('\t\t(instances (project "bluebuzz-rm2"'
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

    def resolve_flags(self):
        """Draw each small net label as a flag: a short stub at right angles
        to the wire it names, ending in the label, placed on the connection
        grid, clear of every other wire. Falls back to a label lying on the
        wire when no side is free."""
        g = 1.27

        def on(a, c, pt):
            return (min(a[0], c[0]) - 1e-6 <= pt[0] <= max(a[0], c[0]) + 1e-6
                    and min(a[1], c[1]) - 1e-6 <= pt[1] <= max(a[1], c[1]) + 1e-6
                    and (abs(a[0] - c[0]) < 1e-6 or abs(a[1] - c[1]) < 1e-6)
                    and ((abs(a[0] - c[0]) < 1e-6 and abs(pt[0] - a[0]) < 1e-6)
                         or (abs(a[1] - c[1]) < 1e-6 and abs(pt[1] - a[1]) < 1e-6)))
        for net, p, size, flag in getattr(self, "pending_flags", []):
            host = next(((a, c) for a, c in self.wires
                         if (abs(a[0] - c[0]) < 1e-6 and abs(p[0] - a[0]) < 0.01
                             and min(a[1], c[1]) - 0.01 <= p[1] <= max(a[1], c[1]) + 0.01)
                         or (abs(a[1] - c[1]) < 1e-6 and abs(p[1] - a[1]) < 0.01
                             and min(a[0], c[0]) - 0.01 <= p[0] <= max(a[0], c[0]) + 0.01)), None)
            placed = False
            if host is not None:
                a, c = host
                vertical = abs(a[0] - c[0]) < 1e-6
                if vertical:
                    lo, hi = sorted((a[1], c[1]))
                    ys = sorted({min(max(round(p[1] / g) * g, lo), hi)}
                                | {round(y * 100) / 100 for y in (p[1] - g, p[1] + g)})
                    bases = [(a[0], q(y)) for y in ys if lo <= y <= hi and self._on_grid(y)]
                    dirs = [(1, 0, 0), (-1, 0, 180)]
                else:
                    lo, hi = sorted((a[0], c[0]))
                    xs = [round(p[0] / g) * g, round(p[0] / g) * g + g, round(p[0] / g) * g - g]
                    bases = [(q(x), a[1]) for x in xs if lo <= x <= hi and self._on_grid(x)]
                    dirs = [(0, -1, 90), (0, 1, 270)]
                for bpt in bases:
                    for dx, dy, rot in dirs:
                        for L in (flag, flag + g):
                            qpt = (q(bpt[0] + dx * L), q(bpt[1] + dy * L))
                            clash = False
                            for w0, w1 in self.wires:
                                if (w0, w1) == host or (w1, w0) == host:
                                    continue
                                # any wire touching the stub other than at its base
                                for s in (qpt,) + tuple((q(bpt[0] + dx * k * g), q(bpt[1] + dy * k * g))
                                                        for k in range(1, int(round(L / g)) + 1)):
                                    if on(w0, w1, s):
                                        clash = True
                                        break
                                if clash:
                                    break
                                if on(bpt, qpt, w0) or on(bpt, qpt, w1):
                                    if w0 != bpt and w1 != bpt:
                                        clash = True
                                        break
                            if not clash:
                                # nor through any text already on the sheet
                                sx0, sx1 = sorted((bpt[0], qpt[0]))
                                sy0, sy1 = sorted((bpt[1], qpt[1]))
                                for tb in self.texts:
                                    if sx0 <= tb[2] and tb[0] <= sx1 and sy0 <= tb[3] and tb[1] <= sy1:
                                        clash = True
                                        break
                            if not clash:
                                # and the label it ends in must not land on text,
                                # a wire or a pin either: its box, by rotation
                                Lt = (len(net) + 3) * size * 0.75
                                hw = size * 0.75
                                X, Y = qpt
                                box = {0: (X, Y - hw, X + Lt, Y + hw), 180: (X - Lt, Y - hw, X, Y + hw),
                                       90: (X - hw, Y - Lt, X + hw, Y), 270: (X - hw, Y, X + hw, Y + Lt)}[rot]
                                if any(box[0] < tb[2] and tb[0] < box[2] and box[1] < tb[3] and tb[1] < box[3]
                                       for tb in self.texts):
                                    clash = True
                                for w0, w1 in self.wires:
                                    if clash:
                                        break
                                    if (w0 == bpt or w1 == bpt) and (w0, w1) != host and (w1, w0) != host:
                                        pass
                                    wx0, wx1 = sorted((w0[0], w1[0]))
                                    wy0, wy1 = sorted((w0[1], w1[1]))
                                    # shrink the box off the anchor end so the stub itself does not count
                                    bx0, by0, bx1, by1 = box
                                    if rot == 0: bx0 += 0.3
                                    if rot == 180: bx1 -= 0.3
                                    if rot == 90: by1 -= 0.3
                                    if rot == 270: by0 += 0.3
                                    if wx0 <= bx1 and bx0 <= wx1 and wy0 <= by1 and by0 <= wy1:
                                        clash = True
                            if clash:
                                continue
                            self.wire(bpt, qpt)
                            if bpt != a and bpt != c:
                                self.junction(bpt)
                            self.glabel(net, qpt, rot=rot, just="left", size=size)
                            if rot in (90, 270):
                                self.texts.append((box[0], box[1], box[2], box[3], f"label {net}", True, None))
                            placed = True
                            break
                        if placed:
                            break
                    if placed:
                        break
            if not placed:
                self.glabel(net, p, rot=0, just="left", size=size)
        self.pending_flags = []

    def path(self, *pts):
        for a, b in zip(pts, pts[1:]):
            self.wire(a, b)

    def junction(self, p):
        self.jpts.add((q(p[0]), q(p[1])))

    def nc(self, p):
        self.body.append(
            f"\t(no_connect (at {q(p[0])} {q(p[1])})"
            f'\n\t\t(uuid "{uid("nc", p)}"))')

    def label(self, net, p, rot=0, just="left", size=1.0, flag=2.54, keep=False):
        """Name a wire that KiCad would otherwise auto-name.

        These are GLOBAL labels even though the run is local, because a
        plain label on the root sheet comes back out of the netlister as
        `/LED_D7`, and the board is matched to circuit.py by net name — a
        rename would relabel every net on a hand-routed board. Drawn small
        at the end of a short stub standing up from the wire, so the word
        sits beside the wire it names rather than on it.
        """
        if not keep and not os.environ.get("SCH_NAME_LOCAL_NETS"):
            # Block-internal nodes are not named on the sheet: the wire is the
            # connection, and a tag on every node is clutter (schematic
            # review). The board takes its net names from circuit.py, and
            # verify_netlist matches these nodes by their pins instead.
            return
        if flag:
            # resolved once every wire is drawn (resolve_flags), because the
            # flag must leave the wire at right angles and must not land on
            # another wire
            if not hasattr(self, "pending_flags"):
                self.pending_flags = []
            self.pending_flags.append((net, p, size, flag))
        else:
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
        cols = max(16, int(width / (size * 1.1)))     # KiCad's stroke font runs ~1.0 x size per character
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
                '\t(title_block (title "bluebuzz-rm2") (date "2026-10-18") (rev "A")\n'
                '\t\t(company "sequoia-hope")\n'
                '\t\t(comment 1 "RP2350A + RM2 vibrator controller, DPS368 tactile array, LSM6DS3TR-C IMU")\n'
                '\t\t(comment 2 "generated from scripts/circuit.py by gen_schematic.py"))\n'
                "\t(lib_symbols\n"
                + "\n".join(d.sexpr for d in self.defs.values())
                + "\n\t)\n" + "\n".join(self.body) + "\n)\n")




# ---------------------------------------------------------------------------
# IC symbol pin maps: pins are placed by FUNCTION, not by pad order.
# ---------------------------------------------------------------------------
def mcu_sides():
    """The RP2350A: 61 pins placed by function. Left: USB, SWD, QSPI, the
    crystal and the regulator pins. Right: every GPIO in use, grouped by
    the block it talks to. Top: supplies (the seven IOVDD pads stacked on
    one pin, the DVDD pads on another). Bottom: GND and the spare GPIOs."""
    used = {GPIO_PINS[g] for g in ROLE}
    spare = sorted(p for g, p in GPIO_PINS.items() if p not in used)
    gp = {p: g for g, p in GPIO_PINS.items()}

    def gpio(g, label):
        return (str(GPIO_PINS[g]), f"GPIO{g}/{label}")

    left = [("52", "USB_DP"), ("51", "USB_DM"), None,
            ("24", "SWCLK"), ("25", "SWDIO"), ("26", "RUN"), None,
            ("60", "QSPI_SS"), ("56", "QSPI_SCLK"), ("57", "QSPI_SD0"),
            ("59", "QSPI_SD1"), ("58", "QSPI_SD2"), ("55", "QSPI_SD3"), None,
            ("21", "XIN"), ("22", "XOUT"), None, None, None, None,
            ("48", "VREG_LX"), None, None, None, None,
            ("46", "VREG_AVDD"), None, None, None, None, ("44", "ADC_AVDD")]
    right = [gpio(13, "M1_PWM"), gpio(17, "M2_PWM"), None,
             gpio(2, "WL_DATA"), gpio(3, "WL_CLK"), gpio(27, "WL_ON"), gpio(25, "WL_CS"), None,
             gpio(10, "TAC_SCK"), gpio(11, "TAC_SDI"), gpio(12, "TAC_SDO"), None,
             gpio(0, "TAC_CS1"), gpio(14, "TAC_CS2"), gpio(15, "TAC_CS3"), gpio(16, "TAC_CS4"), None,
             gpio(29, "PDM_CLK"), gpio(28, "PDM_DATA"), None,
             gpio(6, "SDA"), gpio(7, "SCL"), gpio(5, "IMU_INT1"), gpio(18, "IMU_INT2"), None,
             gpio(19, "PWR_HOLD"),
             gpio(4, "SENS_EN"), gpio(22, "LED"), gpio(8, "BTN"), gpio(9, "PG"), None,
             gpio(26, "ADC0")]
    top = [("1", "IOVDD", ["11", "20", "30", "38", "45", "54"]), ("49", "VREG_VIN"),
           ("53", "USB_OTP_VDD"), None, ("6", "DVDD", ["23", "39"]), ("50", "VREG_FB")]
    bot = [("61", "GND", ["47"]), None] + [(str(p), f"GPIO{gp[p]}") for p in spare]
    return {"l": left, "r": right, "t": top, "b": bot}


IC_SIDES = {
    # the enable pins 12.7 mm apart: each gets an upright power symbol on a
    # short stub, and the symbol and its name fit between the pins
    "charger": {"l": [("13", "IN"), None, None, ("4", "/CE"), None, None, None, None,
                      ("5", "EN2"), None, None, None, None, ("6", "EN1")],
                "r": [("10", "OUT", ["11"]), None, ("2", "BAT", ["3"]), None,
                      ("7", "/PGOOD"), ("9", "/CHG")],
                "b": [("16", "ISET"), None, None, None, ("12", "ILIM"), None, None, None,
                      ("14", "TMR"), None, None, None, ("1", "TS"), None, None, None,
                      ("15", "ITERM"), None, None, None, ("8", "VSS", ["17"])]},
    "ldo": {"l": [("1", "IN"), ("3", "EN")], "r": [("5", "OUT"), ("4", "NC")],
            "b": [("2", "GND")]},
    "load_switch": {"l": [("1", "VIN"), None, ("3", "ON"), ("4", "CT")],
                    "r": [("6", "VOUT"), ("5", "QOD")], "b": [("2", "GND")]},
    # LSM6DS3TR-C: the I2C and interrupts on the left, the mode/aux pins right
    "imu": {"l": [("14", "SDA"), ("13", "SCL")],
            "r": [("4", "INT1"), ("9", "INT2"), None, ("2", "SDx"), ("3", "SCx"), None, ("10", "NC"), ("11", "NC")],
            "t": [("8", "VDD"), ("5", "VDDIO"), ("12", "CS")], "b": [("6", "GND", ["7"]), ("1", "SA0")]},
    # DPS368: the SPI on the left, supplies top, grounds stacked bottom
    "baro": {"l": [("2", "CSB"), ("4", "SCK"), ("3", "SDI"), ("5", "SDO")],
             "t": [("8", "VDD"), ("6", "VDDIO")], "b": [("1", "GND", ["7"])]},
    "pdm_mic": {"l": [("3", "CLK"), ("4", "DOUT")],
                "t": [("1", "VDD")], "b": [("5", "GND"), ("2", "LR")]},
    "motor_fet": {"l": [("1", "G")], "r": [("3", "D")], "b": [("2", "S")]},
    "sig_fet": {"l": [("1", "G")], "r": [("3", "D")], "b": [("2", "S")]},
    "rgb_led": {"l": [("4", "DI")], "r": [("1", "DOUT")], "t": [("2", "VDD")], "b": [("3", "GND")]},
    # the probe cable: SC and SD in, GND (pin 2, the middle) and the shell down
    "debug_jst": {"l": [("1", "SC"), None, ("3", "SD")], "b": [("2", "GND"), ("MP", "MP")]},
    "dual_schottky": {"l": [("1", "A1"), None, ("2", "A2")], "r": [("3", "K")]},
    "usb_esd": {"t": [("1", "IO1", ["6"])], "b": [("3", "IO2", ["4"])],
                "l": [("5", "VBUS")], "r": [("2", "GND")]},
    # W25Q32: the QSPI bus faces the MCU on the left
    "flash": {"l": [("1", "/CS"), ("6", "CLK"), ("5", "DI/IO0"), ("2", "DO/IO1"),
                    ("3", "/WP/IO2"), ("7", "/HOLD/IO3")],
              "t": [("8", "VCC")], "b": [("4", "GND")]},
    # RM2: the gSPI faces the MCU on the left; the five grounds stack
    "radio": {"l": [("3", "SCLK"), None, ("5", "DIN"), None, None, None, ("6", "DOUT"),
                    None, None, None, ("10", "nIRQ"), None, None, None, ("9", "CS"), None,
                    ("12", "WL_ON", ["13"])],
              "r": [("8", "GPIO0"), ("18", "GPIO1"), ("17", "GPIO2"), None,
                    ("2", "NC"), ("19", "NC"), ("20", "NC")],
              "t": [("16", "Vin"), None, None, ("14", "VDDIO")],
              "b": [("1", "GND", ["4", "7", "11", "15", "21"])]},
    # pad rows: pins down the left, in pad order
    "usb_conn": {"r": [("A4", "VBUS", ["A9", "B4", "B9"]), None,
                       ("A6", "D+"), ("B6", "D+"), None, None, None, None,
                       ("A7", "D-"), ("B7", "D-"), None,
                       ("A5", "CC1"), ("B5", "CC2"), None,
                       ("A8", "SBU1"), ("B8", "SBU2")],
                 "b": [("A1", "GND", ["A12", "B1", "B12"]), ("S1", "SHIELD")]},
    "pads_swd": {"l": [("1", "SWDIO"), ("2", "SWCLK"), ("3", "RUN"), ("4", "BOOT"), ("5", "GND")]},
    "pads_bat": {"l": [("1", "+"), ("2", "-"), ("3", "T")]},
    "pads_tp": {"l": [("1", "VSYS"), ("2", "3V3"), ("3", "1V1")]},
    "pads_3": {"l": [("1", "VSYS"), None, ("2", "M1"), None, ("3", "M2")]},
}

IC_MIN_W = {"rgb_led": 17.78, "debug_jst": 15.24, "sig_fet": 15.24, "dual_schottky": 15.24, "usb_esd": 17.78, "pads_2": 15.24, "pads_bat": 15.24, "pads_tp": 15.24, "pads_3": 15.24, "motor_fet": 15.24, "baro": 17.78, "pdm_mic": 17.78, "imu": 20.32,
            "pads_4": 15.24, "pads_5": 10.16, "pads_swd": 15.24,
            "flash": 20.32}

PASSIVE_SYM = {"r_": "R", "c_": "C", "core_inductor": "L", "crystal": "XTAL",
               "button": "SW2", "led": "LED", "motor_flyback": "D", "signal_diode": "D"}


def sym_for(part):
    for k, v in PASSIVE_SYM.items():
        if part == k or part.startswith(k):
            return v
    return part


def defdiode(s):
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
         poly([(-1.905, 1.905), (1.905, 1.905), (0, -1.27), (-1.905, 1.905)], 0.254)],
        (2.1, 3.81), hide_numbers=True, hide_names=True, ref_prefix="D")
    return s.defs["D"]


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
        missing = [f"{ref}.{p}" for ref, c in self.comps.items() for p in c.pins
                   if (ref, p) not in self.seen]
        assert not missing, ("pins in circuit.py that the sheet never drew: "
                             + ", ".join(missing[:40]))


@functools.cache
def parts_table():
    return load_parts()


def put(s, cir, ref, x, y, rot=0, hide_value=False, ref_off=None):
    c = cir.components[ref]
    # as on the board: bare-copper pad rows (mpn PCB) are no BOM line, and
    # a DNP footprint is neither in the BOM nor fitted
    bare = parts_table()[c.part].get("mpn") == "PCB"
    return s.place(sym_for(c.part), ref, c.value, x, y, rot=rot,
                   footprint=c.footprint, hide_value=hide_value, ref_off=ref_off,
                   in_bom=not (bare or ref in DNP), dnp=ref in DNP)


def vdrop(s, cir, bk, ref, x, ytop, rail="GND", drop=3.81, hide_value=False, ref_off=None):
    p = put(s, cir, ref, x, ytop + 3.81, hide_value=hide_value, ref_off=ref_off)
    bk.take(ref, "1")
    bk.take(ref, "2", rail)
    s.wire(p["2"], (x, p["2"][1] + drop))
    s.rail(rail, (x, p["2"][1] + drop))
    return p


def bank(s, cir, bk, refs, x, ytop, rail, pitch=10.16):
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


def left_pins(s, cir, bk, ref, pins, dx=15.24, rails=()):
    """Wire a box's left-side pins out to global labels (or to a rail for
    the nets named in `rails`)."""
    u = None
    return u


# --- Block 1 ---------------------------------------------------------------
def blk_usb(s, cir, bk, x, y):
    s.begin("1 — USB-C and ESD")
    j = put(s, cir, "J1", x, y, hide_value=True)
    for pad in ("A4", "A9", "B4", "B9"):
        bk.take("J1", pad, "VBUS")
    xv = j["A4"][0] + 15.24
    ycap = j["A4"][1] - 22.86
    s.wire(j["A4"], (xv, j["A4"][1]))
    s.wire((xv, j["A4"][1]), (xv, ycap))
    s.wire((xv, ycap), (xv + 15.24, ycap))
    bank(s, cir, bk, ["C2"], xv + 15.24, ycap, "VBUS")
    # D+ / D-: each pair joins on a short vertical, runs out past the ESD
    # array, then through 27 R into the chip
    xd = j["A6"][0] + 7.62
    ydp = q((j["A6"][1] + j["B6"][1]) / 2.0)
    ydn = q((j["A7"][1] + j["B7"][1]) / 2.0)
    u10 = put(s, cir, "U10", j["A6"][0] + 40.64, q((ydp + ydn) / 2.0))
    # the runs pass above and below the array; where its box is taller than
    # the gap between the receptacle's pin pairs, they step out to clear it
    ydp = min(ydp, q(u10["1"][1] - GRID))
    ydn = max(ydn, q(u10["3"][1] + GRID))
    assert ydp < u10["1"][1] and u10["3"][1] < ydn, \
        "the ESD array must sit between the D+ and D- runs"
    for a, b, pin, extra, net, mid, rref, cnet in (
            ("A6", "B6", "1", "6", "USB_DP", ydp, "R3", "USB_DP_C"),
            ("A7", "B7", "3", "4", "USB_DM", ydn, "R4", "USB_DM_C")):
        bk.take("J1", a, net)
        bk.take("J1", b, net)
        bk.take("U10", pin, net)
        bk.take("U10", extra, net)
        s.wire(j[a], (xd, j[a][1]))
        s.wire(j[b], (xd, j[b][1]))
        ys = sorted({j[a][1], j[b][1], mid})
        for y0, y1 in zip(ys, ys[1:]):
            s.wire((xd, y0), (xd, y1))
        if ys[0] < mid < ys[-1]:
            s.junction((xd, mid))
        s.wire((xd, mid), (u10[pin][0] + 15.24, mid))
        s.junction((u10[pin][0], mid))
        s.wire(u10[pin], (u10[pin][0], mid))
        s.label(net, (u10[pin][0] + 2.0, mid), size=1.0)
        r = put(s, cir, rref, u10[pin][0] + 19.05, mid, rot=90,
                ref_off=(-2.5, -6.8) if pin == "1" else (-2.5, 4.2))
        bk.take(rref, "1", net)
        bk.take(rref, "2", cnet)
        s.wire((u10[pin][0] + 15.24, mid), r["1"])
        s.wire(r["2"], (r["2"][0] + 10.16, mid))
        s.glabel(cnet, (r["2"][0] + 10.16, mid))
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
    s.note("The one connector on the board, on the BOTTOM edge (the top edge is "
           "the RM2's RF keep-out). A6/B6 and A7/B7 are tied or the board "
           "enumerates in one cable orientation only; 5.1k on each CC. The "
           "USBLC6-2P6 clamps VBUS and protects D+/D-; 27 R in each line at "
           "the RP2350 is the reference design's.",
           x - 6.0, ybus + 12.7, 110.0)
    s.end()


# --- Block 2 ---------------------------------------------------------------
def blk_charger(s, cir, bk, x, y):
    s.begin("2 — BQ24074 charger with power path")
    u = put(s, cir, "U2", x, y, ref_off=(0.0, -3.0))
    bk.take("U2", "13", "VBUS")
    s.wire(u["13"], (u["13"][0] - 7.62, u["13"][1]))
    s.rail("VBUS", (u["13"][0] - 7.62, u["13"][1]))
    # /CE and EN1 to ground, EN2 to VSYS (ILIM mode, also while the system is off):
    # a short stub left, then a symbol standing the right way up
    for pin, rail, dx in (("4", "GND", 7.62), ("5", "VSYS", 15.24), ("6", "GND", 7.62)):
        bk.take("U2", pin, rail)
        e = (u[pin][0] - dx, u[pin][1])
        s.wire(u[pin], e)
        r = (e[0], e[1] + 3.81) if rail == "GND" else (e[0], e[1] - 3.81)
        s.wire(e, r)
        s.rail(rail, r)
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
    bk.take("U2", "7", "PG_N")
    s.wire(u["7"], (u["7"][0] + 10.16, u["7"][1]))
    s.glabel("PG_N", (u["7"][0] + 10.16, u["7"][1]))
    bk.take("U2", "9", "CHG_N")
    ych = u["9"][1]
    xled = u["9"][0] + 33.02
    s.wire(u["9"], (xled, ych))
    s.label("CHG_N", (u["9"][0] + 5.08, ych), size=1.0)
    r14 = put(s, cir, "R14", xled, ych - 3.81)
    bk.take("R14", "2", "CHG_N")
    bk.take("R14", "1", "CHG_LED")
    d1 = put(s, cir, "D1", xled, ych - 15.24)
    bk.take("D1", "1", "CHG_LED")
    bk.take("D1", "2", "VSYS")
    s.wire(r14["1"], d1["1"])
    s.label("CHG_LED", (xled, q((r14["1"][1] + d1["1"][1]) / 2.0)), size=1.0)
    s.wire(d1["2"], (d1["2"][0], d1["2"][1] - 3.81))
    s.rail("VSYS", (d1["2"][0], d1["2"][1] - 3.81))
    ybot = u["16"][1]
    for ref, pin in (("R10", "16"), ("R11", "12"), ("R12", "14"), ("R13", "1")):
        net = bk.take("U2", pin)
        xp = u[pin][0]
        s.wire(u[pin], (xp, ybot + 5.08))
        s.label(net, (xp, ybot + 3.81), rot=90, size=1.0, keep=(net == "TS"))   # TS also reaches J2's T pad
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
    bk.take("J2", "3", "TS")
    s.wire(j2["3"], (j2["3"][0] - 12.7, j2["3"][1]))
    s.glabel("TS", (j2["3"][0] - 12.7, j2["3"][1]), just="right")
    s.note("EN2 = 1, EN1 = 0: the R_ILIM input limit (0.99 A). 45.3k = 6 h "
           "safety timer. ITERM open = 10% default. VSYS is the power-path "
           "output and feeds the LDO, both motors AND the RM2 (Vin 3.0-4.8 V). "
           "/PGOOD goes to GPIO9: the RP2350 has no VBUS detect of its own. "
           "J2: solder pads on the back for the cell: + - T. T is TS for a "
           "cell with a 10 k NTC; fit it and leave R13 off. Without an NTC "
           "R13 holds TS mid-window (always charging).",
           x - 46.0, y + 93.98, 165.0)
    s.end()


# --- Block 3 ---------------------------------------------------------------
def blk_ldo(s, cir, bk, x, y):
    s.begin("4 — 3.3 V LDO, enabled by the power latch")
    u = put(s, cir, "U3", x, y)
    bk.take("U3", "1", "VSYS")
    bk.take("U3", "3", "LDO_EN")
    xin = u["1"][0] - 10.16
    s.wire(u["1"], (xin, u["1"][1]))
    s.wire((xin, u["1"][1]), (xin, u["1"][1] - 6.35))
    s.rail("VSYS", (xin, u["1"][1] - 6.35))
    s.wire(u["3"], (u["3"][0] - 17.78, u["3"][1]))
    s.glabel("LDO_EN", (u["3"][0] - 17.78, u["3"][1]), just="right")
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
    s.note("500 mA, 25 uA Iq. Feeds the RP2350, the flash, the sensors, the "
           "IMU and the RM2's VDDIO; off (EN low) is the system's off state. "
           "The motors and the RM2's Vin take VSYS directly.",
           x - 26.0, y + 41.91, 104.0)
    s.end()


# --- battery sense ----------------------------------------------------------
def blk_sense(s, cir, bk, x, y):
    s.begin("3 — battery voltage sense")
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
    s.note("1M/1M, 2.1 uA, into ADC0 (GPIO26). C64 feeds the ADC's sampling "
           "charge; the RP2350's ADC input is 500 ohm-ish during a sample, so "
           "oversample.", x - 8.0, r61["2"][1] + 12.7, 96.0)
    s.end()


# --- Block 4 ---------------------------------------------------------------
def motor_channel(s, cir, bk, n, x, y):
    qn, rg, rpd, d = f"Q{n}", f"R{40 + 2 * (n - 1)}", f"R{41 + 2 * (n - 1)}", f"D{2 + n}"
    qf = put(s, cir, qn, x + 38.1, y)
    bk.take(qn, "1", f"MOTOR{n}_G")
    bk.take(qn, "2", "GND")
    bk.take(qn, "3", f"MOTOR{n}_SW")
    s.wire(qf["2"], (qf["2"][0], qf["2"][1] + 5.08))
    s.rail("GND", (qf["2"][0], qf["2"][1] + 5.08))
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
    vdrop(s, cir, bk, rpd, xd, qf["1"][1], ref_off=(-6.35, 7.0))   # fields left of it, clear of the FET's value
    bk.take(rpd, "1", f"MOTOR{n}_G")
    yd = qf["3"][1]
    xm = qf["3"][0] + 12.7
    s.wire(qf["3"], (xm, yd))
    s.label(f"MOTOR{n}_SW", (qf["3"][0] + 5.08, yd), size=1.0)
    dd = put(s, cir, d, xm, yd - 7.62, rot=180, ref_off=(2.6, -1.0))   # fields beside the body, not on it
    bk.take(d, "1", "VSYS")
    bk.take(d, "2", f"MOTOR{n}_SW")
    s.wire((xm, yd), dd["2"])
    s.wire(dd["1"], (xm, dd["1"][1] - 3.81))
    s.rail("VSYS", (xm, dd["1"][1] - 3.81))
    s.junction((xm, yd))
    return (xm, yd)


def blk_motor(s, cir, bk, x, y):
    s.begin("13 — motors: two low-side FET channels from VSYS")
    m1 = motor_channel(s, cir, bk, 1, x, y + 20.32)
    m2 = motor_channel(s, cir, bk, 2, x, y + 60.96)
    # pads_3: pin 2 (M1) is the middle slot of five, so the box centres on
    # channel 1's drain run; pin 3 (M2) is two rows below it
    j4 = put(s, cir, "J4", m1[0] + 40.64, m1[1], hide_value=True)
    assert abs(j4["2"][1] - m1[1]) < 0.01, "J4 pin 2 must sit on channel 1's drain run"
    bk.take("J4", "2", "MOTOR1_SW")
    bk.take("J4", "3", "MOTOR2_SW")
    bk.take("J4", "1", "VSYS")
    s.wire(m1, j4["2"])
    xr = j4["3"][0] - 10.16
    s.wire(m2, (xr, m2[1]))
    s.wire((xr, m2[1]), (xr, j4["3"][1]))
    s.wire((xr, j4["3"][1]), j4["3"])
    s.wire(j4["1"], (j4["1"][0] - 6.35, j4["1"][1]))
    s.rail("VSYS", (j4["1"][0] - 6.35, j4["1"][1]), rot=90)
    bank(s, cir, bk, ["C40", "C41", "C42", "C43"], x + 5.08, y + 93.98, "VSYS")
    s.note("Two identical PWM channels (GPIO13, GPIO17): AO3400A low side, "
           "B5819W 1 A Schottky across each motor, 2 x 22 u of bulk at the "
           "pads. R41/R43 hold the gates down until firmware runs. J4 is three "
           "solder pads on the back: VSYS M1 M2 -- the two motors share the "
           "supply pad. Each channel is sized for 1 A.",
           x - 4.0, y + 124.46, 140.0)
    s.end()


# --- Blocks 5 + 6 -----------------------------------------------------------
def blk_sensors(s, cir, bk, x, y):
    s.begin("5 — switched sensor rail")
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
    c50 = put(s, cir, "C50", u5["4"][0] - 8.89, u5["4"][1] + 3.81, ref_off=(-4.5, -2.0))
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

    s.note("The switched 3.3 V rail for the tactile array (block 6): the "
           "sensors draw little, but gating them lets firmware power-cycle "
           "the array and keeps the rail off in sleep.", x - 30.0, y + 45.72, 120.0)
    s.end()


# --- Block 7 ---------------------------------------------------------------
def blk_tactile(s, cir, bk, x, y):
    """Block 6: the DPS368 array, drawn as the board has it (rows x cols),
    every sensor on the shared SPI with its own chip select."""
    s.begin("11 — tactile array: DPS368 barometers on SPI1, cast in elastomer")
    caps = []
    for k, (ref, cap) in enumerate(TACTILE, 1):
        r, c = divmod(k - 1, TACTILE_COLS)
        u = put(s, cir, ref, x + c * 66.04, y + r * 66.04, hide_value=True, ref_off="corner")
        for pin, net in (("2", f"TAC_CS{k}"), ("4", "TAC_SCK"), ("3", "TAC_SDI"), ("5", "TAC_SDO")):
            bk.take(ref, pin, net)
            s.wire(u[pin], (u[pin][0] - 10.16, u[pin][1]))
            s.glabel(net, (u[pin][0] - 10.16, u[pin][1]), just="right")
        for pin in ("8", "6"):
            bk.take(ref, pin, "3V3_SENS")
        yt = u["8"][1] - 13.97
        s.wire(u["8"], (u["8"][0], yt))
        s.wire(u["6"], (u["6"][0], yt))
        s.wire((u["8"][0], yt), (u["6"][0], yt))
        s.junction((u["8"][0], yt))
        s.wire((u["8"][0], yt), (u["8"][0], yt - 5.08))
        s.rail("3V3_SENS", (u["8"][0], yt - 5.08))
        # its 100n beside the VDD / VDDIO pins, as on the board
        xc = u["6"][0] + 10.16
        s.wire((u["6"][0], yt), (xc, yt))
        s.junction((u["6"][0], yt))
        vdrop(s, cir, bk, cap, xc, yt, ref_off=(2.3, -0.4))
        bk.take(cap, "1", "3V3_SENS")
        for pin in ("1", "7"):
            bk.take(ref, pin, "GND")
        s.wire(u["1"], (u["1"][0], u["1"][1] + 7.62))
        s.rail("GND", (u["1"][0], u["1"][1] + 7.62))
        caps.append(cap)
    s.note("Four Infineon DPS368s on the BACK of the board in a diamond pattern "
           "(North U20, East U21, West U22, South U23), cast in soft elastomer after Tenzer, Jentoft & Howe "
           "2014 (The Feel of MEMS Barometers): rubber poured over the array "
           "and pressure-cast (not vacuum: DPS368 p.43) so it fills the ports; a load on the "
           "surface then reads as pressure. CSB low at power-up puts each "
           "sensor in SPI mode; SPI1 on GPIO10-12, one chip select each on "
           "GPIO0 and GPIO14-16. 100n at every sensor.",
           x - 20.0, y + 66.04 + 30.48, 150.0)
    s.end()


def blk_mic(s, cir, bk, x, y):
    s.begin("14 — PDM MEMS microphone: MP34DT05-A (top-port)")
    u = put(s, cir, "U40", x, y, ref_off="corner")
    for pin, net in (("3", "PDM_CLK"), ("4", "PDM_DATA")):
        bk.take("U40", pin, net)
        s.wire(u[pin], (u[pin][0] - 15.24, u[pin][1]))
        s.glabel(net, (u[pin][0] - 15.24, u[pin][1]), just="right")
    bk.take("U40", "1", "3V3_SYS")
    yt = u["1"][1] - 11.43
    s.wire(u["1"], (u["1"][0], yt))
    xc = u["1"][0] + 12.7
    s.wire((u["1"][0], yt), (xc, yt))
    s.junction((u["1"][0], yt))
    s.wire((u["1"][0], yt), (u["1"][0], yt - 5.08))
    s.rail("3V3_SYS", (u["1"][0], yt - 5.08))
    vdrop(s, cir, bk, "C140", xc, yt, ref_off=(2.3, -0.4))
    bk.take("C140", "1", "3V3_SYS")
    for pin in ("5", "2"):
        bk.take("U40", pin, "GND")
    yb = u["5"][1] + 5.08
    s.wire(u["5"], (u["5"][0], yb))
    s.wire(u["2"], (u["2"][0], yb))
    s.wire((u["5"][0], yb), (u["2"][0], yb))
    s.junction((u["5"][0], yb))
    s.wire((u["5"][0], yb), (u["5"][0], yb + 3.81))
    s.rail("GND", (u["5"][0], yb + 3.81))
    s.note("ST MP34DT05TR-A top-port digital PDM MEMS microphone (3 x 4 x 1 mm "
           "HCLGA-4, 64 dB SNR, 122.5 dBSPL AOP) on the always-on 3.3 V rail. "
           "LR tied to GND selects the left-channel slot; CLK on GPIO29, DOUT "
           "on GPIO28 (PIO PDM state machine). Top acoustic port needs no PCB hole.",
           x - 20.0, y + 30.48, 130.0)
    s.end()


def blk_imu(s, cir, bk, x, y):
    s.begin("12 — IMU: LSM6DS3TR-C on I2C1, always on")
    u = put(s, cir, "U30", x, y, ref_off="corner")
    # SDA's pull-up rises from its wire, SCL's hangs below it: nothing crosses
    for pin, net, dx, rref, down in (("14", "SDA", 7.62, "R130", False),
                                     ("13", "SCL", 12.7, "R131", True)):
        bk.take("U30", pin, net)
        s.wire(u[pin], (u[pin][0] - 20.32, u[pin][1]))
        s.glabel(net, (u[pin][0] - 20.32, u[pin][1]), just="right")
        xp = u[pin][0] - dx
        s.junction((xp, u[pin][1]))
        bk.take(rref, "1", "3V3_SYS")
        bk.take(rref, "2", net)
        if not down:
            r = put(s, cir, rref, xp, u[pin][1] - 8.89, ref_off=(-9.5, 0.0))
            s.wire(r["2"], (xp, u[pin][1]))
            s.wire(r["1"], (xp, r["1"][1] - 3.81))
            s.rail("3V3_SYS", (xp, r["1"][1] - 3.81))
        else:
            # hangs below SCL (a riser would cross SDA), and its supply comes
            # round the side so the 3V3 symbol still stands upright
            r = put(s, cir, rref, xp, u[pin][1] + 8.89, rot=180, ref_off=(2.0, 0.0))
            s.wire(r["2"], (xp, u[pin][1]))
            yb = r["1"][1] + 2.54
            s.path(r["1"], (xp, yb), (xp - 5.08, yb), (xp - 5.08, r["1"][1] - 1.27))
            s.rail("3V3_SYS", (xp - 5.08, r["1"][1] - 1.27))
    for pin, net in (("4", "IMU_INT1"), ("9", "IMU_INT2")):
        bk.take("U30", pin, net)
        s.wire(u[pin], (u[pin][0] + 10.16, u[pin][1]))
        s.glabel(net, (u[pin][0] + 10.16, u[pin][1]))
    for pin in ("10", "11"):
        bk.take("U30", pin, "")
        s.nc(u[pin])
    # SDx / SCx: the unused aux I2C, tied to GND (inputs with no pull)
    for pin in ("2", "3"):
        bk.take("U30", pin, "GND")
    xg = u["2"][0] + 7.62
    s.wire(u["2"], (xg, u["2"][1]))
    s.wire(u["3"], (xg, u["3"][1]))
    s.wire((xg, u["2"][1]), (xg, u["3"][1]))
    s.junction((xg, u["3"][1]))
    s.wire((xg, u["3"][1]), (xg, u["3"][1] + 5.08))
    s.rail("GND", (xg, u["3"][1] + 5.08))
    for pin in ("8", "5", "12"):
        bk.take("U30", pin, "3V3_SYS")
    yt = u["8"][1] - 13.97
    for pin in ("8", "5", "12"):
        s.wire(u[pin], (u[pin][0], yt))
    # the 100n + 10u on VDD and the 100n on VDDIO, in a row off the supply node
    xa, xb, xd = u["12"][0] + 30.48, u["12"][0] + 20.32, u["12"][0] + 10.16
    s.wire((u["8"][0], yt), (xa, yt))
    for xj in (xb, xd, u["5"][0], u["12"][0]):
        s.junction((xj, yt))
    s.wire((u["8"][0], yt), (u["8"][0], yt - 5.08))
    s.rail("3V3_SYS", (u["8"][0], yt - 5.08))
    for ref, xc in (("C131", xa), ("C130", xb), ("C132", xd)):
        vdrop(s, cir, bk, ref, xc, yt, ref_off=(2.3, -0.4))
        bk.take(ref, "1", "3V3_SYS")
    for pin in ("6", "7", "1"):
        bk.take("U30", pin, "GND")
    yb = u["6"][1] + 3.81
    s.wire(u["6"], (u["6"][0], yb))
    s.wire(u["1"], (u["1"][0], yb))
    s.wire((u["6"][0], yb), (u["1"][0], yb))
    s.junction((u["6"][0], yb))
    s.wire((u["6"][0], yb), (u["6"][0], yb + 3.81))
    s.rail("GND", (u["6"][0], yb + 3.81))
    s.note("ST LSM6DS3TR-C six-axis IMU on I2C1 (GPIO6/7, 4.7k pull-ups to "
           "the always-on rail): CS high selects I2C, SA0 low gives address "
           "0x6A; the aux I2C (SDx/SCx) is unused and tied to GND. INT1/INT2 to GPIO5/18 for "
           "wake-on-motion, tap and tilt. 100n + 10u on VDD, 100n on VDDIO.",
           x - 30.0, y + 73.66, 150.0)
    s.end()


def blk_mcu(s, cir, bk, cx, cy):
    s.begin("9 — RP2350A: core regulator, clock, USB, decoupling")
    u = put(s, cir, "U1", cx, cy, ref_off="below-right")

    # --- supplies on top: IOVDD stack + VREG_VIN + USB_OTP_VDD on 3V3; DVDD
    #     stack + VREG_FB on 1V1 --------------------------------------------
    for p in IOVDD_PINS:
        bk.take("U1", str(p), "3V3_SYS")
    bk.take("U1", "49", "3V3_SYS")
    bk.take("U1", "53", "3V3_SYS")
    yb = u["1"][1] - 7.62
    for p in ("1", "49", "53"):
        s.wire(u[p], (u[p][0], yb))
    s.wire((u["1"][0], yb), (u["53"][0], yb))
    s.junction((u["49"][0], yb))
    s.wire((u["49"][0], yb), (u["49"][0], yb - 3.81))
    s.rail("3V3_SYS", (u["49"][0], yb - 3.81))
    for p in DVDD_PINS:
        bk.take("U1", str(p), "1V1")
    bk.take("U1", "50", "1V1")
    s.wire(u["6"], (u["6"][0], yb))
    s.wire(u["50"], (u["50"][0], yb))
    s.wire((u["6"][0], yb), (u["50"][0], yb))
    s.junction((u["50"][0], yb))
    s.wire((u["50"][0], yb), (u["50"][0], yb - 3.81))
    s.rail("1V1", (u["50"][0], yb - 3.81))

    # --- ground -----------------------------------------------------------
    bk.take("U1", "61", "GND")
    bk.take("U1", "47", "GND")
    s.wire(u["61"], (u["61"][0], u["61"][1] + 5.08))
    s.rail("GND", (u["61"][0], u["61"][1] + 5.08))
    # spare GPIOs
    for g, p in GPIO_PINS.items():
        if g not in ROLE:
            bk.take("U1", str(p), "")
            s.nc(u[str(p)])

    # --- left: USB, SWD, QSPI, crystal, regulator -----------------------
    for pin, net in (("52", "USB_DP_C"), ("51", "USB_DM_C"), ("24", "SWCLK"),
                     ("25", "SWDIO"), ("26", "RUN")):
        bk.take("U1", pin, net)
        s.wire(u[pin], (u[pin][0] - 17.78, u[pin][1]))
        s.glabel(net, (u[pin][0] - 17.78, u[pin][1]), just="right")
    for pin, net in (("60", "QSPI_SS"), ("56", "QSPI_SCLK"), ("57", "QSPI_SD0"),
                     ("59", "QSPI_SD1"), ("58", "QSPI_SD2"), ("55", "QSPI_SD3")):
        bk.take("U1", pin, net)
        s.wire(u[pin], (u[pin][0] - 17.78, u[pin][1]))
        s.glabel(net, (u[pin][0] - 17.78, u[pin][1]), just="right")
    # crystal: XIN straight in, XOUT through 1k; the crystal lies below and
    # well to the left of the regulator rows (whose rails reach x1 - 24),
    # so the two columns down to it cross nothing
    bk.take("U1", "21", "XIN")
    bk.take("U1", "22", "XOUT")
    x1, y1 = u["21"]
    x2, y2 = u["22"]
    xc = x1 - 35.56
    xa, xb = xc - 3.81, xc + 3.81          # XIN column, XTAL2 column
    yc = y2 + 50.8
    s.wire((x1, y1), (xa, y1))
    s.label("XIN", (x1 - 6.0, y1), size=1.0)
    r86 = put(s, cir, "R86", x2 - 10.16, y2, rot=270, ref_off=(-2.5, 2.6))
    bk.take("R86", "1", "XOUT")
    bk.take("R86", "2", "XTAL2")
    s.wire((x2, y2), r86["1"])
    s.label("XOUT", (x2 - 5.5, y2), size=1.0)
    s.wire(r86["2"], (xb, y2))
    s.label("XTAL2", (r86["2"][0] - 7.0, y2), size=1.0)
    s.wire((xa, y1), (xa, yc))
    s.wire((xb, y2), (xb, yc))
    yq = put(s, cir, "Y1", xc, yc, hide_value=True, ref_off=(-3.0, -6.6))
    bk.take("Y1", "1", "XIN")
    bk.take("Y1", "3", "XTAL2")
    bk.take("Y1", "2", "GND")
    bk.take("Y1", "4", "GND")
    assert yq["1"] == (q(xa), q(yc)) and yq["3"] == (q(xb), q(yc)), (yq["1"], yq["3"], xa, xb)
    s.wire(yq["2"], (yq["2"][0], yq["2"][1] + 2.54))
    s.rail("GND", (yq["2"][0], yq["2"][1] + 2.54))
    # load caps, tapped off the two columns just above the crystal
    yt = yc - 7.62
    for ref, xcol, xt, off in (("C86", xa, xa - 7.62, (-9.4, -0.4)),
                               ("C87", xb, xb + 7.62, (2.3, -0.4))):
        s.junction((xcol, yt))
        s.wire((xcol, yt), (xt, yt))
        c = put(s, cir, ref, xt, yt + 3.81, ref_off=off)
        bk.take(ref, "1")
        bk.take(ref, "2", "GND")
        s.wire(c["2"], (xt, c["2"][1] + 3.81))
        s.rail("GND", (xt, c["2"][1] + 3.81))
    s.text("12 MHz", xc - 2.6, yc - 11.4, size=1.2, bold=True)

    # regulator rows, 12.7 mm apart: the part at x1 - 12.7, its far pin
    # out to a column, and a vertical rail there -- the columns alternate
    # (-21.59, -26.67, -21.59) so no rail stands on its neighbour's wire
    bk.take("U1", "48", "VREG_LX")
    xl, yl = u["48"]
    l1 = put(s, cir, "L1", xl - 12.7, yl, rot=90, ref_off=(-2.5, -6.0))
    bk.take("L1", "2", "VREG_LX")
    bk.take("L1", "1", "1V1")
    s.wire((xl, yl), l1["2"])
    s.label("VREG_LX", (xl - 7.6, yl), size=1.0)
    s.wire(l1["1"], (xl - 21.59, yl))
    s.wire((xl - 21.59, yl), (xl - 21.59, yl - 6.35))
    s.rail("1V1", (xl - 21.59, yl - 6.35))
    bk.take("U1", "46", "VREG_AVDD")
    xv, yv = u["46"]
    r84 = put(s, cir, "R84", xv - 12.7, yv, rot=90, ref_off=(-2.5, -6.0))
    bk.take("R84", "2", "VREG_AVDD")
    bk.take("R84", "1", "3V3_SYS")
    s.wire((xv, yv), r84["2"])
    s.label("VREG_AVDD", (xv - 8.0, yv), size=1.0, keep=True)   # joins C84 below
    s.wire(r84["1"], (xv - 26.67, yv))
    s.wire((xv - 26.67, yv), (xv - 26.67, yv - 6.35))
    s.rail("3V3_SYS", (xv - 26.67, yv - 6.35))
    bk.take("U1", "44", "3V3A")
    xd, yd = u["44"]
    r85 = put(s, cir, "R85", xd - 12.7, yd, rot=90, ref_off=(-2.5, -6.0))
    bk.take("R85", "2", "3V3A")
    bk.take("R85", "1", "3V3_SYS")
    s.wire((xd, yd), r85["2"])
    s.label("3V3A", (xd - 6.0, yd), size=1.0, keep=True)   # joins C85 below
    s.wire(r85["1"], (xd - 21.59, yd))
    s.wire((xd - 21.59, yd), (xd - 21.59, yd - 6.35))
    s.rail("3V3_SYS", (xd - 21.59, yd - 6.35))

    # --- right: the GPIO roles ------------------------------------------
    for g, net in ROLE.items():
        pin = str(GPIO_PINS[g])
        bk.take("U1", pin, net)
        s.wire(u[pin], (u[pin][0] + 17.78, u[pin][1]))
        s.glabel(net, (u[pin][0] + 17.78, u[pin][1]))

    # --- decoupling banks, below the chip --------------------------------
    yb2 = u["61"][1] + 20.32
    bank(s, cir, bk, ["C91", "C92", "C93", "C94", "C95", "C96", "C97", "C83"], cx - 50.8, yb2, "3V3_SYS")
    bank(s, cir, bk, ["C80", "C81", "C82", "C98"], cx + 35.56, yb2, "1V1")
    # which pin each cap serves (the board places each one there)
    s.text("100 n each at IOVDD 1, 11, 20, 30, 38, 45 and 54/53; C83 4.7 u at VREG_VIN 49",
           cx - 50.8, yb2 + 22.86, size=1.27, frame=False)
    s.text("C80 4.7 u at L1, C81 4.7 u at DVDD 23, C82 / C98 100 n at DVDD 39 / 6",
           cx + 35.56, yb2 + 22.86, size=1.27, frame=False)
    vdrop(s, cir, bk, "C84", cx - 66.04, yb2, ref_off=(-8.4, -0.4))
    bk.take("C84", "1", "VREG_AVDD")
    s.wire((cx - 66.04, yb2), (cx - 66.04, yb2 - 3.81))
    s.rail("VREG_AVDD", (cx - 66.04, yb2 - 3.81))
    vdrop(s, cir, bk, "C85", cx + 73.66, yb2, ref_off=(2.3, -0.4))
    bk.take("C85", "1", "3V3A")
    s.wire((cx + 73.66, yb2), (cx + 73.66, yb2 - 3.81))
    s.rail("3V3A", (cx + 73.66, yb2 - 3.81))

    s.note("Raspberry Pi's RP2350A minimal design: 3.3 uH on VREG_LX with 4.7 u "
           "at the output and at DVDD, 100 n at the third DVDD, 4.7 u on "
           "VREG_VIN, VREG_AVDD through 33 R + 4.7 u, ADC_AVDD through 10 R + "
           "1 u, 27 R in each USB line, 12 MHz crystal with 1 k in series with "
           "XOUT, the reference's ABM8-272-T3 (CL 10 pF) with its 15 pF loads. "
           "The radio's gSPI is on GPIO2/3/23/25 (the board file overrides the "
           "SDK's data and clock pins).",
           cx - 60.0, yb2 + 28.0, 165.0)
    s.end()
    return u


def blk_flash(s, cir, bk, x, y):
    s.begin("8 — QSPI flash, reset and boot")
    u = put(s, cir, "U6", x, y)
    for pin, net in (("1", "QSPI_SS"), ("6", "QSPI_SCLK"), ("5", "QSPI_SD0"),
                     ("2", "QSPI_SD1"), ("3", "QSPI_SD2"), ("7", "QSPI_SD3")):
        bk.take("U6", pin, net)
        s.wire(u[pin], (u[pin][0] - 15.24, u[pin][1]))
        s.glabel(net, (u[pin][0] - 15.24, u[pin][1]), just="right")
    bk.take("U6", "8", "3V3_SYS")
    s.wire(u["8"], (u["8"][0], u["8"][1] - 6.35))
    s.rail("3V3_SYS", (u["8"][0], u["8"][1] - 6.35))
    bk.take("U6", "4", "GND")
    s.wire(u["4"], (u["4"][0], u["4"][1] + 5.08))
    s.rail("GND", (u["4"][0], u["4"][1] + 5.08))
    vdrop(s, cir, bk, "C88", x + 25.4, y - 12.7)
    bk.take("C88", "1", "3V3_SYS")
    s.wire((x + 25.4, y - 12.7), (x + 25.4, y - 16.51))
    s.rail("3V3_SYS", (x + 25.4, y - 16.51))
    # BOOTSEL: QSPI_SS through 1k to the BOOT pad
    xcs = u["1"][0] - 8.89
    s.junction((xcs, u["1"][1]))
    r87 = put(s, cir, "R87", xcs, u["1"][1] - 8.89, rot=180, ref_off=(-4.6, 0.0))
    bk.take("R87", "1", "QSPI_SS")
    bk.take("R87", "2", "BOOTSEL")
    s.wire(r87["1"], (xcs, u["1"][1]))
    s.wire(r87["2"], (xcs, r87["2"][1] - 3.81))
    s.glabel("BOOTSEL", (xcs, r87["2"][1] - 3.81), rot=90)
    # RUN: 10k up, 100n down, to a pad
    yr = y + 38.1
    r88 = put(s, cir, "R88", x - 17.78, yr - 8.89)
    bk.take("R88", "1", "3V3_SYS")
    bk.take("R88", "2", "RUN")
    s.wire(r88["1"], (x - 17.78, r88["1"][1] - 3.81))
    s.rail("3V3_SYS", (x - 17.78, r88["1"][1] - 3.81))
    s.wire(r88["2"], (x - 17.78, yr))
    s.junction((x - 17.78, yr))
    s.wire((x - 17.78, yr), (x + 2.54, yr))
    vdrop(s, cir, bk, "C89", x + 2.54, yr)
    bk.take("C89", "1", "RUN")
    s.wire((x - 17.78, yr), (x - 30.48, yr))
    s.glabel("RUN", (x - 30.48, yr), just="right")
    s.note("W25Q32JVUUIQ, 3 x 4 mm USON (the 2 x 3 16 Mbit part had no stock). "
           "QSPI_SS doubles as BOOTSEL: pull it low through the BOOT pad while "
           "power comes up and the RP2350 enumerates as a UF2 drive. RUN has "
           "the reference's 10k/100n and its own pad.",
           x - 30.0, yr + 20.0, 110.0)
    s.end()


def blk_swd(s, cir, bk, x, y):
    s.begin("6 — SWD / boot pads, test pads, debug-probe connector (back)")
    j = put(s, cir, "J3", x, y, hide_value=True)
    for pin, net in (("1", "SWDIO"), ("2", "SWCLK"), ("3", "RUN"), ("4", "BOOTSEL")):
        bk.take("J3", pin, net)
        s.wire(j[pin], (j[pin][0] - 15.24, j[pin][1]))
        s.glabel(net, (j[pin][0] - 15.24, j[pin][1]), just="right")
    bk.take("J3", "5", "GND")
    s.wire(j["5"], (j["5"][0] - 7.62, j["5"][1]))
    s.rail("GND", (j["5"][0] - 7.62, j["5"][1]))
    j6 = put(s, cir, "J6", x, y + 50.8, hide_value=True)
    for pin, net in (("1", "SWCLK"), ("3", "SWDIO")):
        bk.take("J6", pin, net)
        s.wire(j6[pin], (j6[pin][0] - 15.24, j6[pin][1]))
        s.glabel(net, (j6[pin][0] - 15.24, j6[pin][1]), just="right")
    bk.take("J6", "2", "GND")
    bk.take("J6", "MP", "GND")
    yb = j6["2"][1] + 2.54
    s.wire(j6["2"], (j6["2"][0], yb))
    s.wire(j6["MP"], (j6["MP"][0], yb))
    s.wire((j6["2"][0], yb), (j6["MP"][0], yb))
    s.junction((j6["2"][0], yb))
    s.wire((j6["2"][0], yb), (j6["2"][0], yb + 3.81))
    s.rail("GND", (j6["2"][0], yb + 3.81))
    j5 = put(s, cir, "J5", x, y + 25.4, hide_value=True)
    for pin, rail in (("1", "VSYS"), ("2", "3V3_SYS"), ("3", "1V1")):
        bk.take("J5", pin, rail)
    for pin, rail, dx in (("1", "VSYS", 7.62), ("2", "3V3_SYS", 15.24), ("3", "1V1", 22.86)):
        e = (j5[pin][0] - dx, j5[pin][1])
        s.wire(j5[pin], e)
        s.wire(e, (e[0], e[1] - 3.81 - 2.54 * int(pin)))
        s.rail(rail, (e[0], e[1] - 3.81 - 2.54 * int(pin)))
    s.note("Five 1.6 x 2.2 mm ENIG pads at 2.0 mm pitch for a pogo clip: "
           "SWDIO SWCLK RUN BOOT GND. Bridge BOOT to GND while applying "
           "power for the UF2 bootloader; SWD is for debugging only. J5: "
           "three test pads (VSYS, 3V3, 1V1) for bring-up, GND on the SWD row. "
           "J6: the Raspberry Pi Debug Probe's 3-pin JST-SH (1 SC, 2 GND, 3 SD), "
           "footprint only (DNP), on the back.",
           x - 20.0, y + 76.2, 76.0)
    s.end()


def blk_radio(s, cir, bk, x, y):
    s.begin("10 — Raspberry Pi Radio Module 2 (CYW43439)")
    u = put(s, cir, "U7", x, y, ref_off="corner")
    # gSPI: CLK, CS and WL_ON straight to labels; DIN direct to WL_DATA,
    # DOUT and nIRQ join it through 470 R and 10 k
    for pin, net in (("3", "WL_CLK"), ("9", "WL_CS")):
        bk.take("U7", pin, net)
        s.wire(u[pin], (u[pin][0] - 20.32, u[pin][1]))
        s.glabel(net, (u[pin][0] - 20.32, u[pin][1]), just="right")
    bk.take("U7", "12", "WL_ON")
    bk.take("U7", "13", "WL_ON")
    s.wire(u["12"], (u["12"][0] - 20.32, u["12"][1]))
    s.glabel("WL_ON", (u["12"][0] - 20.32, u["12"][1]), just="right")
    bk.take("U7", "5", "WL_DATA")
    xd = u["5"][0] - 20.32
    s.wire(u["5"], (xd, u["5"][1]))
    s.glabel("WL_DATA", (xd - 12.7, u["5"][1]), just="right")
    s.wire((xd, u["5"][1]), (xd - 12.7, u["5"][1]))
    for pin, rref, net in (("6", "R80", "WL_DOUT"), ("10", "R81", "WL_IRQ")):
        bk.take("U7", pin, net)
        r = put(s, cir, rref, u[pin][0] - 10.16, u[pin][1], rot=270, ref_off=(-2.5, 4.2))
        bk.take(rref, "1", net)
        bk.take(rref, "2", "WL_DATA")
        s.wire(u[pin], r["1"])
        s.label(net, (u[pin][0] - 6.0, u[pin][1]), size=1.0)
        s.wire(r["2"], (xd, u[pin][1]))
        s.junction((xd, u[pin][1]))
    s.wire((xd, u["5"][1]), (xd, u["10"][1]))
    # supplies and grounds
    bk.take("U7", "16", "VSYS")
    bk.take("U7", "14", "3V3_SYS")
    yv = u["16"][1] - 13.97
    s.wire(u["16"], (u["16"][0], yv))
    s.wire((u["16"][0] - 17.78, yv), (u["16"][0], yv))
    s.junction((u["16"][0] - 7.62, yv))
    s.wire((u["16"][0], yv), (u["16"][0], yv - 5.08))
    s.rail("VSYS", (u["16"][0], yv - 5.08))
    for ref, xc in (("C100", u["16"][0] - 17.78), ("C101", u["16"][0] - 7.62)):
        vdrop(s, cir, bk, ref, xc, yv, ref_off=(2.3, -0.4))
        bk.take(ref, "1", "VSYS")
    s.wire(u["14"], (u["14"][0], yv))
    s.wire((u["14"][0], yv), (u["14"][0] + 10.16, yv))
    s.wire((u["14"][0], yv), (u["14"][0], yv - 5.08))
    s.junction((u["14"][0], yv))
    s.rail("3V3_SYS", (u["14"][0], yv - 5.08))
    vdrop(s, cir, bk, "C102", u["14"][0] + 10.16, yv, ref_off=(2.3, -0.4))
    bk.take("C102", "1", "3V3_SYS")
    for pin in ("1", "4", "7", "11", "15", "21"):
        bk.take("U7", pin, "GND")
    s.wire(u["1"], (u["1"][0], u["1"][1] + 5.08))
    s.rail("GND", (u["1"][0], u["1"][1] + 5.08))
    for pin in ("8", "18", "17", "2", "19", "20"):
        bk.take("U7", pin, "")
        s.nc(u[pin])
    s.note("RMC20452T: Wi-Fi 4 + Bluetooth 5.2 Classic/LE, PCB antenna, "
           "modular certification. Vin 3.0-4.8 V from VSYS (271 mA TX peaks "
           "stay off the LDO), VDDIO 3V3. gSPI: GPIO3 clock, GPIO2 data "
           "(DIN direct, DOUT via 470 R, nIRQ via 10 k), GPIO25 CS, GPIO27 "
           "WL_ON on pads 12 and 13 (WL_REG_ON and BT_REG_ON). The datasheet's RF keep-out -- 5 mm "
           "into the body, 10.5 mm either side, 13.5 mm beyond -- is a rule "
           "area on every layer; the module's antenna end is the board edge.",
           x - 50.0, y + 60.0, 160.0)
    s.end()


def blk_ui(s, cir, bk, x, y):
    """Soft power: SW1 puts VSYS on BTN_RAW; D5 ORs BTN_RAW and PWR_HOLD onto
    the LDO's EN; Q3 reads the button onto BTN."""
    s.begin("7 — power button (soft latch) and status LED")
    sw = put(s, cir, "SW1", x, y, hide_value=True)
    bk.take("SW1", "1", "VSYS")
    bk.take("SW1", "2", "BTN_RAW")
    s.wire(sw["1"], (sw["1"][0] - 7.62, sw["1"][1]))
    s.wire((sw["1"][0] - 7.62, sw["1"][1]), (sw["1"][0] - 7.62, sw["1"][1] - 5.08))
    s.rail("VSYS", (sw["1"][0] - 7.62, sw["1"][1] - 5.08))
    # BTN_RAW runs right: a tap down to R64 and Q3's gate, on to D5's A1
    xr = sw["2"][0] + 7.62
    d5 = put(s, cir, "D5", xr + 30.48, sw["2"][1] + 2.54)
    bk.take("D5", "1", "BTN_RAW")
    bk.take("D5", "2", "PWR_HOLD")
    bk.take("D5", "3", "LDO_EN")
    s.wire(sw["2"], (xr, sw["2"][1]))
    s.wire((xr, sw["2"][1]), (xr, d5["1"][1]))
    s.wire((xr, d5["1"][1]), d5["1"])
    s.wire(d5["2"], (d5["2"][0] - 12.7, d5["2"][1]))
    s.glabel("PWR_HOLD", (d5["2"][0] - 12.7, d5["2"][1]), just="right")
    xk = d5["3"][0] + 10.16
    s.wire(d5["3"], (xk + 10.16, d5["3"][1]))
    s.glabel("LDO_EN", (xk + 10.16, d5["3"][1]))
    s.junction((xk, d5["3"][1]))
    vdrop(s, cir, bk, "R63", xk, d5["3"][1], ref_off=(2.3, -0.4))
    bk.take("R63", "1", "LDO_EN")
    # VBUS -> D6 -> R66 joins EN from above: USB keeps the board on
    xu = xk + 5.08
    s.junction((xu, d5["3"][1]))
    r66 = put(s, cir, "R66", xu, d5["3"][1] - 8.89, ref_off=(2.3, 0.0))
    bk.take("R66", "2", "LDO_EN")
    bk.take("R66", "1", "VBUS_EN")
    s.wire(r66["2"], (xu, d5["3"][1]))
    d6 = put(s, cir, "D6", xu, r66["1"][1] - 7.62, ref_off=(2.3, 0.0))
    bk.take("D6", "1", "VBUS_EN")
    bk.take("D6", "2", "VBUS")
    k, a = d6["1"], d6["2"]
    assert k[1] > a[1], "D6: expected the cathode at the bottom"
    s.wire(k, r66["1"])
    s.wire(a, (a[0], a[1] - 3.81))
    s.rail("VBUS", (a[0], a[1] - 3.81))
    # Q3: gate on BTN_RAW (R64 to ground), drain onto BTN
    yq = d5["1"][1] + 25.4
    q3 = put(s, cir, "Q3", xr + 17.78, yq)
    bk.take("Q3", "1", "BTN_RAW")
    bk.take("Q3", "2", "GND")
    bk.take("Q3", "3", "BTN")
    s.junction((xr, d5["1"][1]))
    s.wire((xr, d5["1"][1]), (xr, q3["1"][1]))
    s.wire((xr, q3["1"][1]), q3["1"])
    xg = xr - 5.08
    s.wire((xr, q3["1"][1] - 7.62), (xg, q3["1"][1] - 7.62))
    s.junction((xr, q3["1"][1] - 7.62))
    vdrop(s, cir, bk, "R64", xg, q3["1"][1] - 7.62, ref_off=(-7.0, -0.4))
    bk.take("R64", "1", "BTN_RAW")
    s.wire(q3["2"], (q3["2"][0], q3["2"][1] + 3.81))
    s.rail("GND", (q3["2"][0], q3["2"][1] + 3.81))
    s.wire(q3["3"], (q3["3"][0] + 12.7, q3["3"][1]))
    s.glabel("BTN", (q3["3"][0] + 12.7, q3["3"][1]))
    # status: the addressable LED; its VSYS supply through U11 (TPS22918,
    # ON = 3V3_SYS), then the LED's VDD node with C133, R62 into DI.
    u11 = put(s, cir, "U11", x + 45.72, yq + 40.64)
    bk.take("U11", "1", "VSYS")
    bk.take("U11", "3", "3V3_SYS")
    bk.take("U11", "2", "GND")
    bk.take("U11", "4", "")
    s.nc(u11["4"])
    s.wire(u11["1"], (u11["1"][0] - 7.62, u11["1"][1]))
    s.wire((u11["1"][0] - 7.62, u11["1"][1]), (u11["1"][0] - 7.62, u11["1"][1] - 5.08))
    s.rail("VSYS", (u11["1"][0] - 7.62, u11["1"][1] - 5.08))
    s.wire(u11["3"], (u11["3"][0] - 15.24, u11["3"][1]))
    s.wire((u11["3"][0] - 15.24, u11["3"][1]), (u11["3"][0] - 15.24, u11["3"][1] - 10.16))
    s.rail("3V3_SYS", (u11["3"][0] - 15.24, u11["3"][1] - 10.16))
    s.wire(u11["2"], (u11["2"][0], u11["2"][1] + 3.81))
    s.rail("GND", (u11["2"][0], u11["2"][1] + 3.81))
    bk.take("U11", "5", "LED_VDD")
    bk.take("U11", "6", "LED_VDD")
    xo = u11["6"][0] + 7.62
    s.wire(u11["6"], (xo, u11["6"][1]))
    s.wire(u11["5"], (xo, u11["5"][1]))
    s.wire((xo, u11["6"][1]), (xo, u11["5"][1]))
    s.junction((xo, u11["6"][1]))
    q4 = {"3": (xo, max(u11["5"][1], u11["6"][1]))}
    yn = q4["3"][1] + 5.08
    s.wire(q4["3"], (q4["3"][0], yn))
    d = put(s, cir, "D2", q4["3"][0], yn + 20.32)
    bk.take("D2", "4", "LED_DIN")
    bk.take("D2", "1", "")
    bk.take("D2", "3", "GND")
    bk.take("D2", "2", "LED_VDD")
    xs = sorted((q4["3"][0], d["2"][0]))
    xc = xs[1] + 12.7
    s.wire((xs[0], yn), (xc, yn))
    s.wire(d["2"], (d["2"][0], yn))
    for xj in {q4["3"][0], d["2"][0]}:
        if xs[0] < xj < xc:
            s.junction((xj, yn))
    vdrop(s, cir, bk, "C133", xc, yn, ref_off=(2.3, -0.4))
    bk.take("C133", "1", "LED_VDD")
    s.nc(d["1"])
    s.wire(d["3"], (d["3"][0], d["3"][1] + 3.81))
    s.rail("GND", (d["3"][0], d["3"][1] + 3.81))
    r = put(s, cir, "R62", d["4"][0] - 12.7, d["4"][1], rot=90)
    bk.take("R62", "1", "LED_STAT")
    bk.take("R62", "2", "LED_DIN")
    s.wire(r["2"], d["4"])
    s.wire(r["1"], (r["1"][0] - 7.62, r["1"][1]))
    s.glabel("LED_STAT", (r["1"][0] - 7.62, r["1"][1]), just="right")
    yl = d["3"][1]
    s.note("Press SW1: VSYS reaches the LDO's EN through D5 and 3V3 comes up; "
           "the RP2350 boots and drives PWR_HOLD (GPIO19) high, so the board "
           "stays on after release. Firmware reads the button on GPIO8 (Q3, "
           "active low, internal pull-up) and switches off by driving PWR_HOLD "
           "low. R63 holds EN off; R64 discharges the gate. USB in (VBUS through "
           "D6 and R66) also holds EN on, so flashing and SWD need no button. Charging runs "
           "while off. Status: a 1010 addressable RGB LED (WS2812B type) on "
           "GPIO22 through 330 R; its VSYS supply goes through U11 (a second "
           "TPS22918, ON = 3V3_SYS), so it draws nothing while the system is off.",
           x - 16.0, yl + 20.32, 110.0)
    s.end()


def blk_flags(s, x, y):
    s.begin("Power flags — the ERC root for each rail")
    rails = ["GND", "VBUS", "VSYS", "VBAT", "3V3_SYS", "3V3_SENS", "1V1", "3V3A", "VREG_AVDD"]
    for i, rail in enumerate(rails):
        xf = q(x + i * 30.48)
        s.place("PWR_FLAG", f"#FLG{i + 1}", "PWR_FLAG", xf, y)
        s.wire((xf, y), (xf + 10.16, y))
        s.rail(rail, (xf + 10.16, y))
    s.note("No copper, no netlist entry: every rail is fed through a pin the "
           "symbols declare passive, so ERC needs a driver per rail.",
           x - 4.0, y + 17.78, 150.0)
    s.end()


def build_sheet(design, cir):
    s = Sch()
    s.defpassives()
    s.defflag()
    defdiode(s)
    s.defbox("mcu", "RP2350A", mcu_sides())
    for part, sides in IC_SIDES.items():
        c = next(c for c in cir.components.values() if c.part == part)
        s.defbox(part, c.value, sides, min_w=IC_MIN_W.get(part, 0.0))
    bk = Book(cir.components)

    s.text("bluebuzz-rm2 — generated schematic", 16, 15, size=4.0, bold=True, frame=False)
    s.text(f"{len(cir.components)} components / {len(cir.nets)} nets / "
           f"{design['board']['layers']}-layer.  "
           "Bluetooth-audio vibrator controller: RP2350A + Raspberry Pi RM2 "
           "(CYW43439); USB-C, every other lead on back-side pads; BQ24074 "
           "charger with power path, a soft power latch (button, GPIO hold, USB), two low-side "
           f"motor channels, {len(TACTILE)} DPS368 barometers on the back (four corners and the centre, a tactile "
           "skin) on a switched 3.3 V rail, an IMU and a 1010 RGB status LED.  Rails are power symbols; "
           "cross-block signals are global labels.  Generated from "
           "scripts/circuit.py; rebuild with `python3 build.py --only schematic`.",
           16, 21, size=1.8, frame=False)

    blk_usb(s, cir, bk, 43.18, 101.6)
    blk_charger(s, cir, bk, 83.82, 223.52)
    blk_ldo(s, cir, bk, 231.14, 58.42)
    blk_sense(s, cir, bk, 43.18, 365.76)
    blk_swd(s, cir, bk, 238.76, 241.3)
    blk_ui(s, cir, bk, 220.98, 398.78)
    blk_motor(s, cir, bk, 640.08, 190.5)
    blk_sensors(s, cir, bk, 251.46, 149.86)
    blk_tactile(s, cir, bk, 528.32, 231.14)
    blk_mic(s, cir, bk, 528.32, 419.1)
    blk_imu(s, cir, bk, 668.02, 83.82)
    blk_mcu(s, cir, bk, 403.86, 243.84)
    blk_flash(s, cir, bk, 358.14, 76.2)
    blk_radio(s, cir, bk, 556.26, 99.06)
    blk_flags(s, 38.1, 568.96)
    s.resolve_flags()

    bk.report()
    s.check_frames(verbose=bool(os.environ.get("SCH_LAYOUT")))
    clashes = s.check_text(verbose=bool(os.environ.get("SCH_LAYOUT")))
    if clashes and os.environ.get("SCH_ALLOW_TEXT_CLASH"):
        print(f"  WARNING: {len(clashes)} text clashes, emitted anyway")
        for m in clashes:
            print("    " + m)
        clashes = []
    assert not clashes, (f"{len(clashes)} text clashes (SCH_LAYOUT=1 lists them, "
                         "SCH_ALLOW_TEXT_CLASH=1 emits anyway):\n  " + "\n  ".join(clashes))
    placed = {r for r in s.refs if not r.startswith("#PWR")}
    missing = sorted(set(cir.components) - placed)
    assert not missing, f"components not drawn: {missing}"
    return s


def verify_netlist(cir):
    xml = OUT.parent / "bluebuzz-rm2-netlist.xml"
    r = subprocess.run(["kicad-cli", "sch", "export", "netlist", "--format", "kicadxml",
                        "-o", str(xml), str(OUT)], capture_output=True, text=True)
    if r.returncode:
        print("  WARNING: netlist export failed, cannot verify:", r.stderr.strip())
        return False
    root = ET.parse(xml).getroot()
    got = defaultdict(set)
    for net in root.find("nets"):
        for node in net.findall("node"):
            got[net.get("name")].add((node.get("ref"), node.get("pin")))
    want = defaultdict(set)
    for ref, c in cir.components.items():
        for pad, net in c.pins.items():
            if net:
                want[net].add((ref, pad))
    got_sets = {frozenset(v): k for k, v in got.items() if len(v) > 1}
    problems, local = [], []
    for net, pins in sorted(want.items()):
        fs = frozenset(pins)
        if fs in got_sets:
            if got_sets[fs] != net and not got_sets[fs].startswith("Net-("):
                problems.append(f"net {net}: drawn as {got_sets[fs]!r}")
            elif got_sets[fs] != net:
                local.append(net)
            continue
        drawn = got.get(net)
        if drawn is None:
            problems.append(f"net {net}: missing from the sheet entirely")
        else:
            extra, short = drawn - pins, pins - drawn
            if extra:
                problems.append(f"net {net}: sheet also has " + ", ".join(f"{a}.{b}" for a, b in sorted(extra)))
            if short:
                problems.append(f"net {net}: sheet is missing " + ", ".join(f"{a}.{b}" for a, b in sorted(short)))
    xml.unlink(missing_ok=True)
    if problems:
        print("  NETLIST MISMATCH (sheet vs circuit.py):")
        for p in problems[:80]:
            print("   ", p)
        raise SystemExit(1)
    print(f"  netlist verified against circuit.py: {len(want)} nets match"
          + (f" ({len(local)} block-internal nets unnamed on the sheet, matched by pins)" if local else ""))
    return True


def main():
    design = load_design()
    cir = build_circuit(design)
    s = build_sheet(design, cir)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(s.render())
    print(f"wrote {OUT}: {len(s.defs)} symbols, {len(cir.components)} components, "
          f"{len(cir.nets)} nets, {len(s.frames)} blocks")
    verify_netlist(cir)
    for args, label in ((["--exclude-drawing-sheet", "-o", str(OUT.parent)], "svg"),
                        (["-o", str(OUT.parent / "bluebuzz-rm2-schematic.pdf")], "pdf")):
        r = subprocess.run(["kicad-cli", "sch", "export", label] + args + [str(OUT)],
                           capture_output=True, text=True)
        if r.returncode:
            print(f"  WARNING: {label} export failed: {r.stderr.strip()}")


if __name__ == "__main__":
    main()
