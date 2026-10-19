#!/usr/bin/env python3
"""Images and part data for the component-choice document
(docs/components/index.html, served by `proj up bluebuzz` at
/docs/components/).

  img/ds-*.png    datasheet excerpts: one page of a PDF in design/datasheets/,
                  cropped to a box given in percent of the page
  img/sch-N.png   schematic block N, cropped to the block's frame (the
                  "N — title" text above each polyline frame in the sheet)
  img/sch-all.jpg the whole sheet, scaled down
  img/loc-*.png   where a block's parts sit: the 3D render, front and back,
                  dimmed except for the block's footprints
  parts.json      every component with its value, MPN, LCSC number and
                  footprint, from circuit.py + bom/parts.yaml

Re-run after the schematic, placement or parts change:
    python3 scripts/doc_images.py
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from circuit import build_circuit, load_parts  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DS = ROOT / "design" / "datasheets"
OUT = ROOT / "docs" / "components"
IMG = OUT / "img"
SCH = ROOT / "out" / "bluebuzz-rm2.kicad_sch"
SCH_PDF = ROOT / "out" / "bluebuzz-rm2-schematic.pdf"
PCB = ROOT / "out" / "bluebuzz-rm2.kicad_pcb"

# (id, pdf, page, (x0, y0, x1, y1) in percent of the page)
EXCERPTS = [
    ("hdg-regulator-layout", "hardware-design-with-rp2350.pdf", 7, (10, 9, 90, 92)),
    ("hdg-inductor", "hardware-design-with-rp2350.pdf", 8, (10, 7, 96, 32)),
    ("hdg-decoupling", "hardware-design-with-rp2350.pdf", 9, (10, 15, 90, 44)),
    ("hdg-flash", "hardware-design-with-rp2350.pdf", 11, (10, 18, 96, 90)),
    ("hdg-crystal", "hardware-design-with-rp2350.pdf", 14, (10, 15, 92, 90)),
    ("hdg-crystal-rec", "hardware-design-with-rp2350.pdf", 15, (10, 8, 95, 29)),
    ("hdg-usb", "hardware-design-with-rp2350.pdf", 16, (10, 18, 90, 66)),
    ("rp2350-fig22", "rp2350-datasheet.pdf", 409, (10, 9, 75, 48)),
    ("rp2350-fig25", "rp2350-datasheet.pdf", 411, (10, 9, 90, 56)),
    ("w25q-pins", "w25q32jv.pdf", 6, (10, 36, 90, 88)),
    ("abm8-specs", "abm8-272-t3.pdf", 1, (3, 3, 98, 60)),
    ("rm2-gpio", "rm2-datasheet.pdf", 6, (10, 49, 90, 77)),
    ("rm2-footprint", "rm2-datasheet.pdf", 10, (10, 8, 90, 57)),
    ("rm2-pins", "rm2-datasheet.pdf", 11, (10, 45, 95, 92)),
    ("bq-front", "bq24074.pdf", 1, (52, 50, 98, 76)),
    ("bq-design", "bq24074.pdf", 34, (5, 36, 98, 93)),
    ("tlv-front", "tlv755p.pdf", 1, (8, 12, 50, 66)),
    ("tlv-absmax", "tlv755p.pdf", 4, (8, 9, 92, 24)),
    ("tlv-ec", "tlv755p.pdf", 6, (8, 9, 98, 80)),
    ("tps-front", "tps22918.pdf", 1, (8, 10, 50, 77)),
    ("tps-rise", "tps22918.pdf", 14, (8, 37, 98, 77)),
    ("dps-pins", "dps368.pdf", 6, (5, 17, 95, 75)),
    ("dps-spi", "dps368.pdf", 19, (5, 43, 95, 63)),
    ("dps-caps", "dps368.pdf", 20, (5, 32, 98, 53)),
    ("dps-land", "dps368.pdf", 41, (5, 11, 95, 53)),
    ("dps-handling", "dps368.pdf", 43, (5, 10, 98, 39)),
    ("lsm-app", "lsm6dso-family-reference.pdf", 35, (5, 13, 95, 72)),
    ("ao-front", "ao3400a.pdf", 1, (13, 10, 95, 75)),
    ("ao-rds", "ao3400a.pdf", 3, (10, 55, 50, 80)),
    ("b5819w", "b5819w-mcc.pdf", 1, (2, 25, 80, 72)),
    ("bat54", "bat54-diodes.pdf", 1, (3, 10, 95, 57)),
    ("jst-sh", "jst-sh.pdf", 3, (53, 10, 98, 58)),
]

# schematic block number -> the footprints that block places on the board
BLOCKS = {
    1: ["J1", "U10", "C2", "R1", "R2", "R3", "R4"],
    2: ["U2", "R10", "R11", "R12", "R13", "C10", "C11", "C12", "C13", "C14", "C15", "D1", "R14", "J2"],
    3: ["R60", "R61", "C64"],
    4: ["U3", "C20", "C21", "C22"],
    5: ["U5", "C50", "R50", "C51", "C52"],
    6: ["J3", "J5", "J6"],
    7: ["SW1", "D5", "R63", "D6", "R66", "Q3", "R64", "D2", "R62", "C133", "U11"],
    8: ["U6", "C88", "R87", "R88", "C89"],
    9: ["U1", "L1", "C80", "C81", "C82", "C83", "C84", "R84", "R85", "C85", "Y1", "R86", "C86", "C87"]
       + [f"C9{k}" for k in range(1, 9)],
    10: ["U7", "R80", "R81", "C100", "C101", "C102"],
    11: [f"U{20 + k}" for k in range(5)] + [f"C{120 + k}" for k in range(5)],
    12: ["U30", "C130", "C131", "C132", "R130", "R131"],
    13: ["Q1", "Q2", "R40", "R41", "R42", "R43", "D3", "D4", "C40", "C41", "C42", "C43", "J4"],
}

# kicad-cli render geometry: --zoom 0.8 at 1100 x 1600 frames the board at
# 28 px/mm with its top-left corner (86, 78) at pixel (140, 168); measured
# from the rendered alpha mask (x extent = the 28 mm board exactly)
PX_MM, ORIGIN_PX, BOARD = 28.0, (140, 168), (86.0, 78.0, 114.0, 122.0)


def font(size):
    for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"):
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def excerpts(tmp):
    for key, pdf, page, (x0, y0, x1, y1) in EXCERPTS:
        png = tmp / f"{key}"
        subprocess.run(["pdftoppm", "-r", "170", "-f", str(page), "-l", str(page), "-png",
                        "-singlefile", str(DS / pdf), str(png)], check=True)
        im = Image.open(f"{png}.png").convert("RGB")
        w, h = im.size
        im = im.crop((int(w * x0 / 100), int(h * y0 / 100), int(w * x1 / 100), int(h * y1 / 100)))
        im.save(IMG / f"ds-{key}.png", optimize=True)
    print(f"  {len(EXCERPTS)} datasheet excerpts")


def schematic(tmp):
    s = SCH.read_text()
    w_mm, h_mm = map(float, re.search(r'\(paper "User" ([\d.]+) ([\d.]+)\)', s).groups())
    titles = [(int(m.group(1)), m.group(2), float(m.group(3)), float(m.group(4)))
              for m in re.finditer(r'\(text "(\d+) — ([^"]*)" \(at ([\d.]+) ([\d.]+)', s)]
    frames = []
    for m in re.finditer(r'\n\t\(polyline\s*\(pts((?:\s*\(xy [\d.\-]+ [\d.\-]+\))+)', s):
        pts = [(float(a), float(b)) for a, b in re.findall(r'xy ([\d.\-]+) ([\d.\-]+)', m.group(1))]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        frames.append((min(xs), min(ys), max(xs), max(ys)))
    dpi = 220
    subprocess.run(["pdftoppm", "-r", str(dpi), "-png", "-singlefile", str(SCH_PDF), str(tmp / "sch")], check=True)
    sheet = Image.open(tmp / "sch.png").convert("RGB")
    k = sheet.size[0] / w_mm
    blocks = {}
    for n, title, tx, ty in titles:
        # the frame whose top edge sits just below the title
        fx0, fy0, fx1, fy1 = min((f for f in frames if 0 < f[1] - ty < 4 and abs(f[0] - tx) < 3),
                                 key=lambda f: f[1] - ty)
        box = (fx0 - 2, ty - 4, fx1 + 2, fy1 + 2)
        sheet.crop(tuple(int(v * k) for v in box)).save(IMG / f"sch-{n}.png", optimize=True)
        blocks[n] = title
    small = sheet.copy()
    small.thumbnail((2400, 2400))
    small.save(IMG / "sch-all.jpg", quality=85)
    print(f"  {len(blocks)} schematic blocks ({sheet.size[0]} x {sheet.size[1]} px sheet)")
    return blocks


def locators(tmp):
    import pcbnew
    renders = {}
    for side in ("top", "bottom"):
        png = tmp / f"{side}.png"
        subprocess.run(["kicad-cli", "pcb", "render", "--side", side, "--quality", "high",
                        "--width", "1100", "--height", "1600", "--zoom", "0.8",
                        "--background", "transparent", "-o", str(png), str(PCB)],
                       check=True, capture_output=True)
        im = Image.open(png).convert("RGBA")
        bg = Image.new("RGBA", im.size, (246, 246, 242, 255))
        renders[side] = Image.alpha_composite(bg, im).convert("RGB")
    board = pcbnew.LoadBoard(str(PCB))
    fps = {f.GetReference(): f for f in board.GetFootprints()}
    bx0, by0, bx1, by1 = BOARD
    crop = (ORIGIN_PX[0] - 24, ORIGIN_PX[1] - 24,
            ORIGIN_PX[0] + int((bx1 - bx0) * PX_MM) + 24, ORIGIN_PX[1] + int((by1 - by0 + 0.8) * PX_MM) + 24)

    def to_px(x, y, side):
        px = (x - bx0) if side == "top" else (bx1 - x)
        return ORIGIN_PX[0] + px * PX_MM, ORIGIN_PX[1] + (y - by0) * PX_MM

    lab = font(22)
    for n, refs in BLOCKS.items():
        panels = []
        for side in ("top", "bottom"):
            mine = [fps[r] for r in refs if r in fps and (fps[r].IsFlipped() == (side == "bottom"))]
            base = renders[side]
            dim = Image.blend(base, Image.new("RGB", base.size, (255, 255, 255)), 0.62)
            mask = Image.new("L", base.size, 0)
            md = ImageDraw.Draw(mask)
            boxes = []
            for f in mine:
                bb = f.GetBoundingBox(False)
                x0, y0 = to_px(pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetTop()), side)
                x1, y1 = to_px(pcbnew.ToMM(bb.GetRight()), pcbnew.ToMM(bb.GetBottom()), side)
                x0, x1 = sorted((x0, x1))
                boxes.append((f.GetReference(), (x0 - 3, y0 - 3, x1 + 3, y1 + 3)))
                md.rectangle(boxes[-1][1], fill=255)
            im = Image.composite(base, dim, mask)
            d = ImageDraw.Draw(im)
            for ref, b in boxes:
                d.rectangle(b, outline=(230, 40, 90), width=3)
            for ref, b in boxes:
                tw = d.textlength(ref, font=lab)
                tx = min(max(b[0], crop[0] + 4), crop[2] - tw - 6)
                ty = b[1] - 26 if b[1] - 26 > crop[1] else b[3] + 2
                d.rectangle((tx - 2, ty, tx + tw + 2, ty + 24), fill=(255, 255, 255))
                d.text((tx, ty), ref, fill=(190, 20, 70), font=lab)
            im = im.crop(crop)
            d = ImageDraw.Draw(im)
            d.text((10, 6), "FRONT" if side == "top" else "BACK (seen from behind)", fill=(60, 60, 60), font=font(20))
            panels.append(im)
        gap = 24
        out = Image.new("RGB", (panels[0].size[0] * 2 + gap, panels[0].size[1]), (255, 255, 255))
        out.paste(panels[0], (0, 0))
        out.paste(panels[1], (panels[0].size[0] + gap, 0))
        out.thumbnail((900, 900))
        out.save(IMG / f"loc-{n}.png", optimize=True)
    print(f"  {len(BLOCKS)} board locators")


def parts_json():
    cir = build_circuit()
    parts = load_parts()
    rows = []
    for ref, c in cir.components.items():
        p = parts[c.part]
        rows.append({"ref": ref, "value": c.value, "part": c.part, "mpn": p.get("mpn", ""),
                     "lcsc": p.get("lcsc", ""), "footprint": p.get("footprint", "").split(":")[-1]})
    block_of = {r: n for n, refs in BLOCKS.items() for r in refs}
    for r in rows:
        r["block"] = block_of.get(r["ref"])
    missing = [r["ref"] for r in rows if r["block"] is None]
    assert not missing, f"components in no block: {missing}"
    (OUT / "parts.json").write_text(json.dumps(rows, indent=1))
    print(f"  parts.json: {len(rows)} components")


def main():
    IMG.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        parts_json()
        excerpts(tmp)
        schematic(tmp)
        locators(tmp)


if __name__ == "__main__":
    main()
