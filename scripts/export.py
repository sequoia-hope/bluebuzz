#!/usr/bin/env python3
"""Export JLCPCB fabrication + assembly files.

out/bluebuzz-rm2.step        the assembled board, for the enclosure
out/jlcpcb/
  gerbers/…                  individual layers + drill
  bluebuzz-rm2_gerbers.zip   upload this for the PCB
  bom.csv                    JLC assembly BOM  (Comment,Designator,Footprint,MPN,LCSC Part #)
  cpl.csv                    JLC pick&place    (Designator,Mid X,Mid Y,Layer,Rotation)

Every part in bom/parts.yaml carries an `lcsc:` number (verified against
LCSC/JLC on 2026-08-18); a part whose lcsc is "" (Tag-Connect pads) is
bare copper and is left out of the BOM and CPL. A part with no `lcsc:`
key at all is reported. JLC rotations may need per-part correction after
their DFM preview -- known quirk of their library.
"""
import csv
import subprocess
import sys
import zipfile
from pathlib import Path

import pcbnew

sys.path.insert(0, str(Path(__file__).resolve().parent))
from circuit import build_circuit, load_design, load_parts  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PCB = ROOT / "out" / "bluebuzz-rm2.kicad_pcb"
OUT = ROOT / "out" / "jlcpcb"


def _copper_layers():
    n = load_design()["board"]["layers"]
    return ["F.Cu"] + [f"In{i}.Cu" for i in range(1, n - 1)] + ["B.Cu"]


LAYERS = ",".join(_copper_layers() + [
    "F.Mask", "B.Mask", "F.Paste", "B.Paste",
    "F.Silkscreen", "B.Silkscreen", "Edge.Cuts"])


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(" ".join(str(c) for c in cmd))
        print(r.stdout, r.stderr)
        sys.exit(1)


def main():
    gdir = OUT / "gerbers"
    gdir.mkdir(parents=True, exist_ok=True)
    for f in gdir.glob("*"):
        f.unlink()
    run(["kicad-cli", "pcb", "export", "gerbers", "--layers", LAYERS,
         "--subtract-soldermask", "-o", str(gdir) + "/", str(PCB)])
    run(["kicad-cli", "pcb", "export", "drill", "--format", "excellon",
         "--drill-origin", "absolute", "--excellon-units", "mm",
         "--generate-map", "--map-format", "gerberx2",
         "-o", str(gdir) + "/", str(PCB)])
    zpath = OUT / "bluebuzz-rm2_gerbers.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        for f in sorted(gdir.glob("*")):
            z.write(f, f.name)
    print(f"wrote {zpath}")

    # whole-board STEP for enclosure work: every footprint carries its
    # LCSC part's model (library/3d, see fetch_models.py), .wrl in the
    # board file with a .step sibling that --subst-models picks up
    step = ROOT / "out" / "bluebuzz-rm2.step"
    run(["kicad-cli", "pcb", "export", "step", "--subst-models", "-f",
         "-o", str(step), str(PCB)])
    print(f"wrote {step}")

    cir = build_circuit()
    parts = load_parts()
    board = pcbnew.LoadBoard(str(PCB))
    bom_rows = {}   # (value, footprint, mpn, lcsc) -> [refs]
    cpl_rows = []
    missing_lcsc = set()
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        comp = cir.components.get(ref)
        if comp is None:
            continue          # mounting holes: board-only
        p = parts[comp.part]
        if "lcsc" not in p:
            missing_lcsc.add(comp.part)
        lcsc = p.get("lcsc") or ""
        if "lcsc" in p and not lcsc:
            continue          # nothing is mounted (bare pads)
        key = (comp.value, comp.footprint.split(":")[1], p.get("mpn", ""), lcsc)
        bom_rows.setdefault(key, []).append(ref)
        pos = fp.GetPosition()
        cpl_rows.append([
            ref,
            f"{pcbnew.ToMM(pos.x):.3f}mm",
            f"{-pcbnew.ToMM(pos.y):.3f}mm",   # JLC wants +y up
            "bottom" if fp.GetLayer() == pcbnew.B_Cu else "top",
            f"{fp.GetOrientationDegrees():.1f}",
        ])
    with open(OUT / "bom.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "MPN", "LCSC Part #"])
        for (val, fpname, mpn, lcsc), refs in sorted(bom_rows.items(), key=lambda kv: kv[1][0]):
            w.writerow([val, ",".join(sorted(refs)), fpname, mpn, lcsc])
    with open(OUT / "cpl.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        w.writerows(sorted(cpl_rows))
    n_parts = sum(len(r) for r in bom_rows.values())
    print(f"wrote bom.csv ({len(bom_rows)} lines) and cpl.csv ({n_parts} parts)")
    if missing_lcsc:
        print(f"NOTE: no LCSC number yet for {len(missing_lcsc)} part types "
              f"({', '.join(sorted(missing_lcsc))}) -- fill bom/parts.yaml before ordering")


if __name__ == "__main__":
    main()
