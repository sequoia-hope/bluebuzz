#!/usr/bin/env python3
"""Write the footprints KiCad does not ship, into library/parts.pretty/.

  * RM2 -- Raspberry Pi Radio Module 2 (RMC20452T), from the datasheet's
    PCB footprint drawing (docs/RM2-datasheet.pdf, fig. 6 and 7):
      body 14.5 x 16.5 mm; origin = body centre, +y down, antenna at -y.
      21 castellated pads at 1.5 mm pitch, numbered counter-clockwise
      from the top-left: 1..7 down the LEFT edge, 8..14 along the BOTTOM
      left to right, 15..21 up the RIGHT edge.
      Side pads 2.0 x 1.0 (0.5 outside the body, 1.5 under it), the top
      one 5.5 mm below the body's top edge (its top edge at 5.0 = the
      keep-out line), so centres 5.5 + 1.5 k from the top.
      Bottom pads 1.0 x 2.0 (0.5 outside, 1.5 under), centres 2.75 + 1.5 k
      from the left edge (2.75 .. 11.75, symmetric on the 14.5 body).
      RF keep-out (drawn on Dwgs.User and enforced by route.py as a rule
      area): 35.5 x 18.5, from 13.5 beyond the antenna end to 5.0 into
      the body, 10.5 either side of it.
  * PadRow_<n> -- n bare 1.6 x 2.2 mm pads at 2.0 mm pitch for a flying
    lead or a pogo pin, pad 1 at the left; the row is placed on the BACK.
    Two flavours: with paste (tins at reflow, wire soldered on) and
    without (ENIG contact for a pogo: USB, SWD).

Everything is regenerated on every build; nothing here is hand-edited.
"""
from pathlib import Path

import pcbnew

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "library" / "parts.pretty"
NICK = "bluebuzz-rm2"


def mm(v):
    return pcbnew.FromMM(v)


def new_fp(name, descr, tags):
    fp = pcbnew.FOOTPRINT(None)
    fp.SetFPID(pcbnew.LIB_ID(NICK, name))
    fp.SetLibDescription(descr)
    fp.SetKeywords(tags)
    fp.SetAttributes(pcbnew.FP_SMD)
    fp.Reference().SetText("REF**")
    fp.Reference().SetLayer(pcbnew.F_Fab)
    fp.Reference().SetTextSize(pcbnew.VECTOR2I(mm(0.6), mm(0.6)))
    fp.Reference().SetTextThickness(mm(0.1))
    fp.Value().SetText(name)
    fp.Value().SetLayer(pcbnew.F_Fab)
    fp.Value().SetTextSize(pcbnew.VECTOR2I(mm(0.6), mm(0.6)))
    fp.Value().SetVisible(False)
    return fp


def smd_pad(fp, num, x, y, w, h, mask=True, paste=True, roundrect=0.25):
    p = pcbnew.PAD(fp)
    p.SetNumber(str(num))
    p.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
    p.SetShape(pcbnew.PAD_SHAPE_ROUNDRECT if roundrect else pcbnew.PAD_SHAPE_RECT)
    if roundrect:
        p.SetRoundRectRadiusRatio(roundrect)
    p.SetSize(pcbnew.VECTOR2I(mm(w), mm(h)))
    p.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
    layers = pcbnew.LSET()
    layers.addLayer(pcbnew.F_Cu)
    if mask:
        layers.addLayer(pcbnew.F_Mask)
    if paste:
        layers.addLayer(pcbnew.F_Paste)
    p.SetLayerSet(layers)
    fp.Add(p)
    return p


def line(fp, a, b, layer, width=0.12):
    s = pcbnew.PCB_SHAPE(fp)
    s.SetShape(pcbnew.SHAPE_T_SEGMENT)
    s.SetStart(pcbnew.VECTOR2I(mm(a[0]), mm(a[1])))
    s.SetEnd(pcbnew.VECTOR2I(mm(b[0]), mm(b[1])))
    s.SetLayer(layer)
    s.SetWidth(mm(width))
    fp.Add(s)


def rect(fp, x0, y0, x1, y1, layer, width=0.12):
    for a, b in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)),
                 ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
        line(fp, a, b, layer, width)


def text(fp, s, x, y, layer, size=0.7):
    t = pcbnew.PCB_TEXT(fp)
    t.SetText(s)
    t.SetLayer(layer)
    t.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
    t.SetTextSize(pcbnew.VECTOR2I(mm(size), mm(size)))
    t.SetTextThickness(mm(0.1))
    fp.Add(t)


def save(fp, name):
    LIB.mkdir(parents=True, exist_ok=True)
    io = pcbnew.PCB_IO_MGR.PluginFind(pcbnew.PCB_IO_MGR.KICAD_SEXP)
    io.FootprintSave(str(LIB), fp)
    return name


# RM2 body, in the footprint frame (origin = body centre, +y down)
RM2_W, RM2_H = 14.5, 16.5
RM2_KEEPOUT = dict(depth=5.0, side=10.5, beyond=13.5)


def rm2_pads():
    """pad number -> (x, y, w, h) in the footprint frame."""
    hw, hh = RM2_W / 2, RM2_H / 2
    pads = {}
    # left column 1..7, top to bottom; side pad centred 0.5 under the edge
    for k in range(7):
        y = -hh + 5.7 + 1.5 * k          # fig. 6 p.9: pad 1 centre 5.7 mm from the antenna end
        pads[1 + k] = (-hw + (0.6 if k == 0 else 0.5), y, 1.8 if k == 0 else 2.0, 1.0)
    # bottom row 8..14, left to right
    for k in range(7):
        x = -hw + 2.75 + 1.5 * k
        pads[8 + k] = (x, hh - 0.5, 1.0, 2.0)
    # right column 15..21, bottom to top
    for k in range(7):
        y = hh - 1.8 - 1.5 * k           # fig. 6: lowest side pad centre 1.8 mm from the bottom edge
        pads[15 + k] = (hw - (0.6 if k == 6 else 0.5), y, 1.8 if k == 6 else 2.0, 1.0)
    return pads


def rm2():
    name = "RM2"
    fp = new_fp(name, "Raspberry Pi Radio Module 2 (RMC20452T), CYW43439 Wi-Fi + BT, "
                "14.5 x 16.5 x 2.55 mm, 21 castellated pads P1.5mm, antenna at -y",
                "RM2 CYW43439 radio module raspberry pi")
    hw, hh = RM2_W / 2, RM2_H / 2
    for num, (x, y, w, h) in rm2_pads().items():
        smd_pad(fp, num, x, y, w, h, roundrect=0.2)
    rect(fp, -hw, -hh, hw, hh, pcbnew.F_Fab, 0.1)
    # antenna band (the keep-out's depth into the body)
    line(fp, (-hw, -hh + RM2_KEEPOUT["depth"]), (hw, -hh + RM2_KEEPOUT["depth"]),
         pcbnew.F_Fab, 0.1)
    text(fp, "ANT", 0, -hh + 2.5, pcbnew.F_Fab, 0.8)
    text(fp, "${REFERENCE}", 0, 2.0, pcbnew.F_Fab, 1.0)
    # courtyard: body plus the 0.5 mm the pads stick out
    rect(fp, -hw - 0.5, -hh - 0.25, hw + 0.5, hh + 0.5, pcbnew.F_CrtYd, 0.05)
    # silk: the pad-free top end, and a pin-1 dot by pad 1
    line(fp, (-hw - 0.1, -hh - 0.1), (hw + 0.1, -hh - 0.1), pcbnew.F_SilkS, 0.12)
    line(fp, (-hw - 0.1, -hh - 0.1), (-hw - 0.1, -hh + 4.5), pcbnew.F_SilkS, 0.12)
    line(fp, (hw + 0.1, -hh - 0.1), (hw + 0.1, -hh + 4.5), pcbnew.F_SilkS, 0.12)
    c = pcbnew.PCB_SHAPE(fp)
    c.SetShape(pcbnew.SHAPE_T_CIRCLE)
    c.SetStart(pcbnew.VECTOR2I(mm(-hw - 1.2), mm(-hh + 5.7)))
    c.SetEnd(pcbnew.VECTOR2I(mm(-hw - 1.0), mm(-hh + 5.7)))
    c.SetLayer(pcbnew.F_SilkS)
    c.SetWidth(mm(0.2))
    c.SetFilled(True)
    fp.Add(c)
    # the RF keep-out, drawn for the human (route.py makes the rule area)
    k = RM2_KEEPOUT
    rect(fp, -hw - k["side"], -hh - k["beyond"], hw + k["side"], -hh + k["depth"],
         pcbnew.Dwgs_User, 0.1)
    text(fp, "RF KEEP OUT", 0, -hh - 2.0, pcbnew.Dwgs_User, 1.0)
    return save(fp, name)


def dps368():
    """Infineon DPS368, LGA-8 2.0 x 2.5 mm: two columns of four pads at
    0.65 mm pitch, 1.45 mm apart. Datasheet fig. 18 (p.41): 0.35 x 0.35 mm
    solder-mask-DEFINED pads with 0.35 mm paste apertures -- drawn as 0.5 mm
    copper with the mask and paste pulled in 0.075 mm per side. (The EasyEDA
    land had 0.6 x 0.4 mm pads with 1:1 paste: 2.5x the paste, on a part
    that cannot be reworked once cast.) Pin 1 top-right, pins 1-4 down the
    right column, 5-8 up the left. The vent hole is near the pin 4/5 end."""
    name = "DPS368_LGA-8"
    fp = new_fp(name, "Infineon DPS368 barometric pressure sensor, LGA-8 2.0x2.5x1.1 mm, "
                "pressure port on top", "DPS368 barometer LGA pressure tactile")
    for k in range(4):
        y = -0.975 + 0.65 * k
        for num, x in ((1 + k, 0.725), (8 - k, -0.725)):
            pad = smd_pad(fp, num, x, y, 0.5, 0.5, roundrect=0)
            pad.SetLocalSolderMaskMargin(mm(-0.075))     # 0.35 mm mask opening
            pad.SetLocalSolderPasteMargin(mm(-0.075))    # 0.35 mm stencil aperture
    rect(fp, -1.0, -1.25, 1.0, 1.25, pcbnew.F_Fab, 0.1)
    c = pcbnew.PCB_SHAPE(fp)
    c.SetShape(pcbnew.SHAPE_T_CIRCLE)
    c.SetStart(pcbnew.VECTOR2I(mm(0.3), mm(0.6)))      # vent hole, pin 4/5 end (fig. 1)
    c.SetEnd(pcbnew.VECTOR2I(mm(0.5), mm(0.6)))
    c.SetLayer(pcbnew.F_Fab)
    c.SetWidth(mm(0.08))
    fp.Add(c)
    text(fp, "${REFERENCE}", 0, 0.4, pcbnew.F_Fab, 0.5)
    rect(fp, -1.25, -1.5, 1.25, 1.5, pcbnew.F_CrtYd, 0.05)
    # silk: the two short ends, outside the body tolerance (1.25 +/- 0.05),
    # and a pin-1 dot by the top-right pad; nothing under the 50 um stand-off
    line(fp, (-1.1, -1.55), (1.1, -1.55), pcbnew.F_SilkS, 0.15)
    line(fp, (-1.1, 1.55), (1.1, 1.55), pcbnew.F_SilkS, 0.15)
    d = pcbnew.PCB_SHAPE(fp)
    d.SetShape(pcbnew.SHAPE_T_CIRCLE)
    d.SetStart(pcbnew.VECTOR2I(mm(1.45), mm(-1.0)))
    d.SetEnd(pcbnew.VECTOR2I(mm(1.55), mm(-1.0)))
    d.SetLayer(pcbnew.F_SilkS)
    d.SetWidth(mm(0.2))
    d.SetFilled(True)
    fp.Add(d)
    return save(fp, name)


def led_1010():
    """XINGLIGHT XL-1010RGBC-2812B-S, 1.0 x 1.0 mm: four 0.45 mm square pads
    at 0.85 mm centres (EasyEDA C51900942). 1 DOUT top-left, 2 VDD
    top-right, 3 GND bottom-left, 4 DI bottom-right."""
    name = "LED_1010_WS2812"
    fp = new_fp(name, "XL-1010RGBC-2812B-S addressable RGB LED, 1.0 x 1.0 mm", "LED RGB WS2812 1010")
    for num, (x, y) in {1: (-0.425, -0.425), 2: (0.425, -0.425), 3: (-0.425, 0.425), 4: (0.425, 0.425)}.items():
        smd_pad(fp, num, x, y, 0.45, 0.45, roundrect=0)
    rect(fp, -0.5, -0.5, 0.5, 0.5, pcbnew.F_Fab, 0.08)
    rect(fp, -0.9, -0.9, 0.9, 0.9, pcbnew.F_CrtYd, 0.05)
    # pin-1 mark outside the top-left corner
    line(fp, (-0.85, -0.85), (-0.85, -0.45), pcbnew.F_SilkS, 0.12)
    line(fp, (-0.85, -0.85), (-0.45, -0.85), pcbnew.F_SilkS, 0.12)
    return save(fp, name)


def pad_row(n, paste):
    """n pads in a row at 2.0 mm pitch, 1.6 wide x 2.2 tall, pad 1 at the
    left; '1' marked beside it on silk. Placed on the back by place.py."""
    kind = "solder" if paste else "pogo"
    name = f"PadRow_{n}x_{kind}"
    fp = new_fp(name, f"{n} x 1.6 x 2.2 mm pads, 2.0 mm pitch, for "
                + ("a soldered lead" if paste else "a pogo pin (no paste, ENIG)"),
                "pad row wire pogo")
    if not paste:
        fp.SetAttributes(pcbnew.FP_SMD | pcbnew.FP_EXCLUDE_FROM_BOM
                         | pcbnew.FP_EXCLUDE_FROM_POS_FILES)
    else:
        fp.SetAttributes(pcbnew.FP_SMD | pcbnew.FP_EXCLUDE_FROM_BOM
                         | pcbnew.FP_EXCLUDE_FROM_POS_FILES)
    x0 = -(n - 1) * 1.0
    for i in range(n):
        smd_pad(fp, i + 1, x0 + 2.0 * i, 0.0, 1.6, 2.2, paste=paste, roundrect=0.15)
    if paste:
        # Larger courtyard for hand-soldered wire leads (motor/battery leads)
        rect(fp, x0 - 2.05, -2.4, x0 + 2.0 * (n - 1) + 2.05, 2.4, pcbnew.F_CrtYd, 0.05)
        rect(fp, x0 - 1.9, -2.2, x0 + 2.0 * (n - 1) + 1.9, 2.2, pcbnew.F_Fab, 0.1)
    else:
        rect(fp, x0 - 0.95, -1.25, x0 + 2.0 * (n - 1) + 0.95, 1.25, pcbnew.F_CrtYd, 0.05)
    # pin-1 tick, outside the row on the left
    line(fp, (x0 - 1.15, -1.1), (x0 - 1.15, 1.1), pcbnew.F_SilkS, 0.15)
    return save(fp, name)


def mp34dt05():
    """ST MP34DT05TR-A / MP34DT06JTR, HCLGA-4 3.0 x 4.0 x 1.0 mm top-port
    digital PDM MEMS microphone (LCSC C2688664 / C503097).
    1 = VDD, 2 = LR, 3 = CLK, 4 = DOUT, 5 = GND frame (4 segments with
    corner openings for signal escape)."""
    name = "MP34DT05_HCLGA-4"
    fp = new_fp(name, "ST MP34DT05TR-A top-port digital PDM MEMS microphone, HCLGA-4 3x4x1 mm",
                "MP34DT05 MP34DT06 PDM MEMS microphone ST")
    for num, (x, y) in {1: (-0.68, 0.42), 2: (0.68, 0.42), 3: (0.68, -0.42), 4: (-0.68, -0.42)}.items():
        smd_pad(fp, num, x, y, 0.95, 0.40, roundrect=0.15)
    for x, y, w, h in ((-1.72, 0.0, 0.35, 1.00), (1.72, 0.0, 0.35, 1.00),
                       (0.0, 1.23, 2.00, 0.35), (0.0, -1.23, 2.00, 0.35)):
        smd_pad(fp, 5, x, y, w, h, roundrect=0.15)
    rect(fp, -2.0, -1.5, 2.0, 1.5, pcbnew.F_Fab, 0.1)
    c = pcbnew.PCB_SHAPE(fp)
    c.SetShape(pcbnew.SHAPE_T_CIRCLE)
    c.SetStart(pcbnew.VECTOR2I(mm(1.0), mm(0.0)))       # top-port acoustic hole indicator
    c.SetEnd(pcbnew.VECTOR2I(mm(1.35), mm(0.0)))
    c.SetLayer(pcbnew.F_Fab)
    c.SetWidth(mm(0.08))
    fp.Add(c)
    text(fp, "${REFERENCE}", -0.4, 0.0, pcbnew.F_Fab, 0.5)
    rect(fp, -2.2, -1.7, 2.2, 1.7, pcbnew.F_CrtYd, 0.05)
    # silk corners outside the 4.0 x 3.0 body, and pin-1 dot at (-2.0, +1.5)
    for sx in (-1, 1):
        for sy in (-1, 1):
            line(fp, (sx * 2.1, sy * 1.6), (sx * 1.4, sy * 1.6), pcbnew.F_SilkS, 0.12)
            line(fp, (sx * 2.1, sy * 1.6), (sx * 2.1, sy * 0.9), pcbnew.F_SilkS, 0.12)
    d = pcbnew.PCB_SHAPE(fp)
    d.SetShape(pcbnew.SHAPE_T_CIRCLE)
    d.SetStart(pcbnew.VECTOR2I(mm(-2.35), mm(1.5)))
    d.SetEnd(pcbnew.VECTOR2I(mm(-2.25), mm(1.5)))
    d.SetLayer(pcbnew.F_SilkS)
    d.SetWidth(mm(0.2))
    d.SetFilled(True)
    fp.Add(d)
    return save(fp, name)


def main():
    made = [rm2(), dps368(), led_1010(), mp34dt05()]
    for n in (2, 3):
        made.append(pad_row(n, paste=True))
    for n in (3, 5):
        made.append(pad_row(n, paste=False))
    for name in made:
        fp = pcbnew.FootprintLoad(str(LIB), name)
        assert fp is not None, name
        print(f"wrote {LIB / (name + '.kicad_mod')}: {len(list(fp.Pads()))} pads")


if __name__ == "__main__":
    main()
