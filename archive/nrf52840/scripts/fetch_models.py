#!/usr/bin/env python3
"""Fetch the LCSC (EasyEDA) 3D model of every part and align it to the
KiCad footprint the part uses. Writes library/3d/<model>.wrl + .step and
library/3d/models.yaml (the per-part model file + transform gen_board.py
applies). Network is only used for parts that have no entry yet
(--force refetches everything).

Why LCSC models: they are the parts that will actually be placed, so the
render and the STEP export show the real connector, module, crystal and
button, not KiCad's generic stand-ins -- and fetching by LCSC number is
one more check that the number in bom/parts.yaml resolves to the part
we mean.

Alignment. easyeda2kicad writes each model relative to EasyEDA's OWN
footprint. Ours is KiCad's (or gen_footprints.py's), whose origin and
rotation differ. The pads are the same physical pads, so the rigid
transform between the two footprint frames comes from matching pads by
number (fallback: by geometry), one of four 90-degree rotations plus a
translation. That transform is composed onto the model's offset/rotation.
KiCad's model conventions, established by experiment (render, look):
offset.y is board-UP (-y on screen) and rotate.z = +theta turns the model
CLOCKWISE on screen. A bounding-box check of the model against the
footprint's courtyard then catches a vendor model that is itself off --
matching pads cannot, since such a model was never on its own pads
either (the USB-C receptacle: 2.2 mm behind them). The check runs on the
final transform, after library/3d/overrides.yaml; a part that fails it
keeps KiCad's model and is reported.
"""
import math
import re
import shutil
import os
import pwd
import subprocess
import sys
import tempfile
from pathlib import Path

import pcbnew
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from circuit import load_parts  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LIB3D = ROOT / "library" / "3d"
MODELS = LIB3D / "models.yaml"
OVERRIDES = LIB3D / "overrides.yaml"     # hand corrections, see that file
LOCAL_LIB = ROOT / "library" / "parts.pretty"
STOCK = Path("/usr/share/kicad/footprints")
WRL_UNIT = 2.54     # KiCad .wrl unit is 0.1 inch


def load_footprint(fpid):
    lib, name = fpid.split(":")
    path = LOCAL_LIB if lib == "bluebuzz" else STOCK / f"{lib}.pretty"
    return pcbnew.FootprintLoad(str(path), name)


def kicad_pads(fp):
    """{number: (x, y)} mm in the footprint frame (y down), first pad per number
    plus a list of all (number, x, y) for geometric matching."""
    out = []
    for p in fp.Pads():
        pos = p.GetPosition()
        out.append((p.GetNumber(), pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y)))
    return out


def parse_ee_footprint(text):
    """Pads and model line of an easyeda2kicad .kicad_mod (legacy syntax)."""
    pads = []
    for m in re.finditer(r'\(pad\s+"?([^"\s]+)"?\s+(smd|thru_hole|np_thru_hole)\s+\S+\s+'
                         r'\(at\s+(-?[\d.]+)\s+(-?[\d.]+)', text):
        pads.append((m.group(1), float(m.group(3)), float(m.group(4)), m.group(2)))
    mm_ = re.search(r'\(model\s+"([^"]+)"\s*'
                    r'\(offset\s*\(xyz\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\)\)\s*'
                    r'\(scale\s*\(xyz\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\)\)\s*'
                    r'\(rotate\s*\(xyz\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\)\)', text)
    model = None
    if mm_:
        g = mm_.groups()
        model = {"file": g[0], "offset": [float(v) for v in g[1:4]],
                 "scale": [float(v) for v in g[4:7]], "rotate": [float(v) for v in g[7:10]]}
    return pads, model


def rot(phi_deg, x, y):
    """Clockwise-on-screen rotation in y-down coordinates."""
    c, s = math.cos(math.radians(phi_deg)), math.sin(math.radians(phi_deg))
    return (c * x - s * y, s * x + c * y)


def align(ee_pads, k_pads):
    """Candidates (phi, t, residual, method) with p_K = R(phi) p_E + t,
    best first. Pads matched by number, or by geometry when the numbers
    disagree (EasyEDA and KiCad number a switch's four pads differently).
    A footprint symmetric under 180 degrees leaves two candidates that
    the pads cannot tell apart; the caller breaks the tie with the model's
    bounding box against the courtyard (the plunger side of a switch)."""
    ee = {}
    for n, x, y, kind in ee_pads:
        if kind == "np_thru_hole":
            continue
        ee.setdefault(n, []).append((x, y))
    kk = {}
    for n, x, y in k_pads:
        if n:
            kk.setdefault(n, []).append((x, y))
    cands = []
    common = [n for n in ee if n in kk]
    if len(common) >= 2:
        for phi in (0, 90, 180, 270):
            # translation from the mean over common numbers (first pad each)
            dx = dy = 0.0
            for n in common:
                ex, ey = rot(phi, *ee[n][0])
                dx += kk[n][0][0] - ex
                dy += kk[n][0][1] - ey
            tx, ty = dx / len(common), dy / len(common)
            res = 0.0
            for n in common:
                # a number may map to several pads (USB shells): nearest one
                ex, ey = rot(phi, *ee[n][0])
                d = min(math.hypot(kx - (ex + tx), ky - (ey + ty)) for kx, ky in kk[n])
                res = max(res, d)
            cands.append((phi, (tx, ty), res, "numbers"))
    if True:
        # geometry as well (not only as fallback): when the two libraries
        # number a symmetric part differently, the by-number solution can
        # be the wrong one of two pad-identical rotations, and only the
        # courtyard fit downstream can tell -- so it must see both
        E = [(x, y) for n, x, y, kind in ee_pads if kind != "np_thru_hole"]
        K = [(x, y) for n, x, y in k_pads if n]
        if len(E) >= 2 and len(K) >= 2:
            kcx, kcy = sum(p[0] for p in K) / len(K), sum(p[1] for p in K) / len(K)
            for phi in (0, 90, 180, 270):
                R = [rot(phi, *p) for p in E]
                ecx, ecy = sum(p[0] for p in R) / len(R), sum(p[1] for p in R) / len(R)
                tx, ty = kcx - ecx, kcy - ecy
                res = max(min(math.hypot(kx - (ex + tx), ky - (ey + ty)) for kx, ky in K)
                          for ex, ey in R)
                cands.append((phi, (tx, ty), res, "geometry"))
    return sorted(cands, key=lambda c: c[2])


def wrl_bbox(path):
    t = Path(path).read_text(errors="ignore")
    xs, ys, zs = [], [], []
    for m in re.finditer(r"point\s*\[(.*?)\]", t, re.S):
        nums = [float(v) for v in re.findall(r"-?\d+\.?\d*(?:[eE]-?\d+)?", m.group(1))]
        for i in range(0, len(nums) - 2, 3):
            xs.append(nums[i]); ys.append(nums[i + 1]); zs.append(nums[i + 2])
    if not xs:
        return None
    return (min(xs) * WRL_UNIT, min(ys) * WRL_UNIT, max(xs) * WRL_UNIT, max(ys) * WRL_UNIT)


def courtyard_bbox(fp):
    fp.BuildCourtyardCaches()
    bb = fp.GetCourtyard(pcbnew.F_CrtYd).BBox()
    if bb.GetWidth() == 0:
        bb = fp.GetBoundingBox(False)
    return (pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetTop()),
            pcbnew.ToMM(bb.GetRight()), pcbnew.ToMM(bb.GetBottom()))


def model_screen_bbox(bbox_model, offset, rz):
    """Model-frame xy bbox (mm, y up) -> screen-frame bbox after KiCad's
    transform: rotate rz clockwise on screen, then offset (x, -y)."""
    x0, y0, x1, y1 = bbox_model
    pts = []
    for mx, my in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
        sx, sy = rot(rz, mx, -my)
        pts.append((sx + offset[0], sy - offset[1]))
    return (min(p[0] for p in pts), min(p[1] for p in pts),
            max(p[0] for p in pts), max(p[1] for p in pts))


def bbox_check(mb, cb, slack=0.5):
    """Model footprint-plane bbox vs courtyard: inside it, overlapping.
    Returns (ok, inside_fraction, message).

    The courtyard is the body plus ~0.25-0.5 mm, so a correctly aligned
    model lands wholly inside it: all 32 parts here sit 100% in, the worst
    of them 0.04 mm from an edge. The thresholds are therefore tight on
    purpose. The USB-C receptacle passed the first cut's 60% / 1.5 mm and
    was still 2.4 mm out of place -- enough to render its mouth inboard of
    the board edge, where no plug can reach it."""
    ox = min(mb[2], cb[2]) - max(mb[0], cb[0])
    oy = min(mb[3], cb[3]) - max(mb[1], cb[1])
    if ox <= 0 or oy <= 0:
        return False, 0.0, "no overlap"
    marea = (mb[2] - mb[0]) * (mb[3] - mb[1])
    frac = ox * oy / marea if marea else 0
    outside = max(cb[0] - mb[0], cb[1] - mb[1], mb[2] - cb[2], mb[3] - cb[3])
    if frac < 0.95:
        return False, frac, f"only {frac:.0%} of the model over the courtyard"
    if outside > slack:
        return False, frac, f"model sticks out {outside:.2f} mm past the courtyard"
    return True, frac, f"{frac:.0%} inside, {outside:.2f} mm past"


def fetch(lcsc, workdir):
    out = workdir / f"ee_{lcsc}"
    out.mkdir(exist_ok=True)
    # build.py points HOME at a scratch dir for kicad-cli; easyeda2kicad
    # lives in the user's site-packages, which Python finds via HOME.
    env = dict(os.environ, HOME=pwd.getpwuid(os.getuid()).pw_dir)
    r = subprocess.run(["easyeda2kicad", "--full", f"--lcsc_id={lcsc}",
                        "--output", str(out / "ee")], capture_output=True, text=True,
                       timeout=180, env=env)
    mods = list((out / "ee.pretty").glob("*.kicad_mod")) if (out / "ee.pretty").exists() else []
    if not mods:
        return None, r.stdout + r.stderr
    return out, r.stdout


def main():
    force = "--force" in sys.argv
    only = [a for a in sys.argv[1:] if not a.startswith("--")]
    parts = load_parts()
    LIB3D.mkdir(parents=True, exist_ok=True)
    models = yaml.safe_load(MODELS.read_text()) if MODELS.exists() else {}
    models = models or {}
    overrides = (yaml.safe_load(OVERRIDES.read_text()) or {}) if OVERRIDES.exists() else {}
    work = Path(tempfile.mkdtemp(prefix="ee_"))
    problems = []
    for key, p in parts.items():
        lcsc = p.get("lcsc")
        if not lcsc or (only and key not in only):
            continue
        if lcsc in models and not force and models[lcsc].get("file"):
            continue
        fp = load_footprint(p["footprint"])
        if fp is None:
            problems.append(f"{key}: KiCad footprint {p['footprint']} not found")
            continue
        out, log = fetch(lcsc, work)
        if out is None:
            problems.append(f"{key} ({lcsc}): fetch failed: {log.strip()[-200:]}")
            models[lcsc] = {"part": key, "file": None, "why": "fetch failed"}
            continue
        mod = next((out / "ee.pretty").glob("*.kicad_mod"))
        ee_pads, ee_model = parse_ee_footprint(mod.read_text())
        if ee_model is None:
            problems.append(f"{key} ({lcsc}): no 3D model on LCSC")
            models[lcsc] = {"part": key, "file": None, "why": "no 3D model on LCSC"}
            continue
        base = Path(ee_model["file"]).stem
        src_wrl = out / "ee.3dshapes" / f"{base}.wrl"
        src_step = out / "ee.3dshapes" / f"{base}.step"
        cands = [c for c in align(ee_pads, kicad_pads(fp)) if c[2] <= 0.25]
        if not cands:
            problems.append(f"{key} ({lcsc}): pads do not align with the KiCad footprint")
            models[lcsc] = {"part": key, "file": None, "why": "pad alignment failed"}
            continue
        mb = wrl_bbox(src_wrl) if src_wrl.exists() else None
        cb = courtyard_bbox(fp)
        best = None
        for phi, (tx, ty), res, method in cands:
            # compose: model screen offset = R(phi) * (ox, -oy) + t ; rz += phi
            ox, oy, oz = ee_model["offset"]
            sx, sy = rot(phi, ox, -oy)
            sx, sy = sx + tx, sy + ty
            offset = [round(sx, 4), round(-sy, 4), oz]
            rotate = [ee_model["rotate"][0], ee_model["rotate"][1],
                      (ee_model["rotate"][2] + phi) % 360]
            ok, frac, why = (bbox_check(model_screen_bbox(mb, offset, rotate[2]), cb)
                             if mb else (True, 1.0, "no wrl bbox"))
            # a candidate whose model lands on the courtyard beats one
            # whose model does not; then the pad residual (coarsely --
            # 0.1 mm is library slop, not a different rotation); then the
            # courtyard fit breaks the ties the pads cannot
            score = (not ok, round(res, 1), -frac)
            if best is None or score < best[0]:
                best = (score, ok, why, offset, rotate, res, method, phi)
        _, ok, why, offset, rotate, res, method, phi = best
        ov = overrides.get(lcsc, {})
        if ov:
            rotate = [rotate[0], rotate[1], (rotate[2] + ov.get("rotate_z_add", 0)) % 360]
            offset = [offset[0] + ov.get("dx", 0), offset[1] + ov.get("dy", 0),
                      offset[2] + ov.get("dz", 0)]
            # The check above only breaks ties between candidate rotations;
            # what is reported and accepted has to be the transform actually
            # written, override and all -- otherwise a hand correction is
            # neither checked nor visible in models.yaml.
            if mb:
                ok, _, why = bbox_check(model_screen_bbox(mb, offset, rotate[2]), cb)
        entry = {"part": key, "file": f"{base}.wrl", "offset": offset,
                 "rotate": rotate, "scale": ee_model["scale"],
                 "align": f"{method}, residual {res:.3f} mm, phi {phi}"
                          + (f", override {ov}" if ov else ""),
                 "bbox": why}
        if not ok:
            problems.append(f"{key} ({lcsc}): {why}; keeping KiCad's model")
            entry["file"] = None
            entry["why"] = why
        else:
            for src in (src_wrl, src_step):
                if src.exists():
                    shutil.copy(src, LIB3D / src.name)
        models[lcsc] = entry
        print(f"{key:14} {lcsc:10} {base[:48]:48} {method} r={res:.3f} phi={phi} {why}")
    MODELS.write_text("# generated by scripts/fetch_models.py -- LCSC 3D models and the\n"
                      "# transform that puts each on the KiCad footprint parts.yaml names\n"
                      + yaml.safe_dump(models, sort_keys=True))
    shutil.rmtree(work, ignore_errors=True)
    n_ok = sum(1 for m in models.values() if m.get("file"))
    print(f"models.yaml: {n_ok} models, {len(models) - n_ok} without")
    for pr in problems:
        print("  PROBLEM:", pr)


if __name__ == "__main__":
    main()
