#!/usr/bin/env python3
"""Generate a fresh 4-layer .kicad_pcb from circuit.py + design.yaml.

(bluebuzz: no mounting holes -- design.yaml has mounting_holes: null.)

Creates the board outline, mounting holes, nets, footprints (all parked at
the board centre -- place.py positions them) and the JLCPCB design rules.
Output: out/bluebuzz-rm2.kicad_pcb, fully regenerated every run.

Board frame: the board centre is sheet (100,100) mm; +y is DOWN on screen.
Every other board script uses the same centre-relative mm coordinates.
"""
import json
import sys

import yaml
from pathlib import Path

import pcbnew

sys.path.insert(0, str(Path(__file__).resolve().parent))
from circuit import build_circuit, load_design, load_parts  # noqa: E402
from gen_schematic import SHEET_UUID, uid  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out" / "bluebuzz-rm2.kicad_pcb"
PRO = ROOT / "out" / "bluebuzz-rm2.kicad_pro"
LOCAL_LIB = ROOT / "library" / "parts.pretty"
LOCAL_NICK = "bluebuzz-rm2"      # nickname used in bom/parts.yaml
STOCK = Path("/usr/share/kicad/footprints")

CENTER = (100.0, 100.0)


def mm(v):
    return pcbnew.FromMM(v)


def vec(x, y):
    """centre-relative mm -> sheet VECTOR2I"""
    return pcbnew.VECTOR2I(mm(CENTER[0] + x), mm(CENTER[1] + y))


def write_fp_lib_table():
    """Register library/parts.pretty under the nickname parts.yaml uses, so
    both the schematic's footprint fields and the board resolve it. KiCad
    looks for this file next to the project file, which lives in out/."""
    (OUT.parent / "fp-lib-table").write_text(
        "(fp_lib_table\n  (version 7)\n"
        f'  (lib (name "{LOCAL_NICK}")(type "KiCad")'
        '(uri "${KIPRJMOD}/../library/parts.pretty")'
        '(options "")(descr "bluebuzz-rm2 generated footprints"))\n)\n')


def link_to_schematic(fp, ref):
    """Stamp the schematic symbol's UUID path so "Update PCB from Schematic"
    matches board U1 to schematic U1. gen_schematic.py derives its UUIDs
    deterministically, so both sides compute the same value."""
    fp.SetPath(pcbnew.KIID_PATH(f"/{SHEET_UUID}/{uid('sym', ref)}"))


def load_footprint(fpid):
    lib, name = fpid.split(":")
    path = LOCAL_LIB if lib == LOCAL_NICK else STOCK / f"{lib}.pretty"
    fp = pcbnew.FootprintLoad(str(path), name)
    if fp is not None:
        fp.SetFPID(pcbnew.LIB_ID(lib, name))
    return fp


def load_models():
    """library/3d/models.yaml: the LCSC 3D model per part and its transform
    onto the KiCad footprint (scripts/fetch_models.py writes it)."""
    f = ROOT / "library" / "3d" / "models.yaml"
    return (yaml.safe_load(f.read_text()) or {}) if f.exists() else {}


def attach_model(fp, entry):
    """Replace the footprint's 3D models with the part's LCSC model."""
    fp.Models().clear()
    m = pcbnew.FP_3DMODEL()
    m.m_Filename = "${KIPRJMOD}/../library/3d/" + entry["file"]
    m.m_Offset = pcbnew.VECTOR3D(*[float(v) for v in entry["offset"]])
    m.m_Rotation = pcbnew.VECTOR3D(*[float(v) for v in entry["rotate"]])
    m.m_Scale = pcbnew.VECTOR3D(*[float(v) for v in entry.get("scale", [1, 1, 1])])
    m.m_Show = True
    fp.Models().push_back(m)


def setup_rules(board, design):
    """Board-level minimums (JLCPCB 4-layer, checked against their
    capabilities page 2026-08). Netclass geometry lives in the .kicad_pro
    that gen_project.py writes; pcbnew loads it with the board."""
    j = design["jlcpcb"]
    bds = board.GetDesignSettings()
    bds.m_TrackMinWidth = mm(j["min_track_mm"])
    bds.m_ViasMinSize = mm(j["via_diameter_mm"])
    bds.m_MinThroughDrill = mm(j["via_drill_mm"])
    bds.m_MinClearance = mm(j["min_clearance_mm"])
    bds.m_HoleClearance = mm(0.2)
    bds.m_HoleToHoleMin = mm(0.2)
    bds.m_ViasMinAnnularWidth = mm(0.05)
    bds.m_CopperEdgeClearance = mm(0.2)
    bds.m_SolderMaskMinWidth = mm(0.1)
    ns = bds.m_NetSettings
    default = ns.GetDefaultNetclass()
    default.SetTrackWidth(mm(j["default_track_mm"]))
    default.SetClearance(mm(j["min_clearance_mm"]))
    default.SetViaDiameter(mm(j["via_diameter_mm"]))
    default.SetViaDrill(mm(j["via_drill_mm"]))


def sync_project_rules(design):
    """pcbnew.SaveBoard writes the project file too, but only what it
    knows; make sure the .kicad_pro's board rules say what the board
    says (kicad-cli drc reads the .kicad_pro, and without these keys it
    falls back to KiCad defaults such as a 0.5mm minimum via)."""
    j = design["jlcpcb"]
    d = json.loads(PRO.read_text())
    rules = d.setdefault("board", {}).setdefault(
        "design_settings", {}).setdefault("rules", {})
    rules.update({
        "min_clearance": j["min_clearance_mm"],
        "min_track_width": j["min_track_mm"],
        "min_via_diameter": j["via_diameter_mm"],
        "min_through_hole_diameter": j["via_drill_mm"],
        "min_via_annular_width": 0.05,
        "min_hole_clearance": 0.2,
        "min_hole_to_hole": 0.2,
        "min_copper_edge_clearance": 0.2,
        "min_microvia_diameter": 0.2,
        "min_microvia_drill": 0.1,
        "min_silk_clearance": 0.0,
        "min_text_height": 0.8,
        "min_text_thickness": 0.08,
        # 1, not KiCad's 2: the USB-C GND pads A1/B12 sit between other
        # pads and only ever get one spoke; their real ground is the plane
        "min_resolved_spokes": 1,
        "min_connection": 0.0,
        "solder_mask_to_copper_clearance": 0.005,
        "max_error": 0.005,
    })
    sev = d["board"]["design_settings"].setdefault("rule_severities", {})
    # KiCad's U.FL footprint opens one mask window over both pads on
    # purpose (the connector shell floats over them); DRC calls that a
    # bridge. Warn, don't fail.
    sev["solder_mask_bridge"] = "warning"
    PRO.write_text(json.dumps(d, indent=2) + "\n")


def outline(board, design):
    b = design["board"]
    if b.get("outline") == "squish":
        from squish_outline import add_squish_outline_to_board
        add_squish_outline_to_board(
            board,
            r_tip=float(b.get("r_tip_mm", 10.0)),
            top_y_pcb=float(b.get("top_y_mm", -22.0)),
            offset_mm=float(b.get("offset_mm", 0.0)),
        )
        return
    w, h, r = b["width_mm"], b["height_mm"], b["corner_radius_mm"]
    hw, hh = w / 2, h / 2

    def seg(a, c):
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(vec(*a))
        s.SetEnd(vec(*c))
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(mm(0.1))
        board.Add(s)

    def arc(start, mid, end):
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_ARC)
        s.SetArcGeometry(vec(*start), vec(*mid), vec(*end))
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(mm(0.1))
        board.Add(s)

    k = r * (1 - 0.7071067811865476)   # arc midpoint inset
    seg((-hw + r, -hh), (hw - r, -hh))
    arc((hw - r, -hh), (hw - k, -hh + k), (hw, -hh + r))
    seg((hw, -hh + r), (hw, hh - r))
    arc((hw, hh - r), (hw - k, hh - k), (hw - r, hh))
    seg((hw - r, hh), (-hw + r, hh))
    arc((-hw + r, hh), (-hw + k, hh - k), (-hw, hh - r))
    seg((-hw, hh - r), (-hw, -hh + r))
    arc((-hw, -hh + r), (-hw + k, -hh + k), (-hw + r, -hh))


def mounting_holes(board, design):
    """Board-only NPTH holes, one per corner. Not in circuit.py and not in
    the schematic (attr board_only keeps the sync from complaining)."""
    b = design["board"]
    mh = b.get("mounting_holes")
    if not mh:
        return
    hw, hh, ins = b["width_mm"] / 2, b["height_mm"] / 2, mh["inset_mm"]
    d = mh["drill_mm"]
    name = f"MountingHole_{d}mm_M2" if d == 2.2 else f"MountingHole_{d}mm"
    for i, (sx, sy) in enumerate(((-1, -1), (1, -1), (-1, 1), (1, 1))):
        fp = pcbnew.FootprintLoad(str(STOCK / "MountingHole.pretty"), name)
        assert fp is not None, name
        fp.SetReference(f"H{i + 1}")
        fp.SetValue("M2")
        fp.SetBoardOnly(True)
        fp.SetExcludedFromBOM(True)
        fp.SetExcludedFromPosFiles(True)
        fp.Reference().SetVisible(False)
        fp.Value().SetVisible(False)
        fp.SetPosition(vec(sx * (hw - ins), sy * (hh - ins)))
        board.Add(fp)


def _silk(board, text, x, y, size=1.0, back=False, thickness=0.15, rot=0.0):
    """Silkscreen text (centred), in centre-relative mm; back-side text is
    mirrored so it reads correctly looking at the back."""
    t = pcbnew.PCB_TEXT(board)
    t.SetText(text)
    t.SetLayer(pcbnew.B_SilkS if back else pcbnew.F_SilkS)
    t.SetPosition(vec(x, y))
    t.SetTextSize(pcbnew.VECTOR2I(mm(size), mm(size)))
    t.SetTextThickness(mm(thickness))
    t.SetTextAngleDegrees(rot)
    t.SetMirrored(back)
    t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
    t.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
    board.Add(t)
    return t


def legend(board, design):
    """Silkscreen: the pad groups named beside their rows on the back (the
    only place a person solders to), the LEDs on the front, name and
    revision on the back. Positions follow place.py's table."""
    from place import LEGEND          # the pad-row names live with the placement
    for text, x, y, kw in LEGEND:
        _silk(board, text, x, y, **kw)
    _silk(board, f"bluebuzz-rm2 rev {design.get('revision', 'A')}", *design.get("_rev_xy", (0.0, 0.0)),
          back=True, size=0.8, thickness=0.12) if False else None


def main():
    design = load_design()
    cir = build_circuit(design)
    OUT.parent.mkdir(exist_ok=True)
    if OUT.exists():
        OUT.unlink()
    write_fp_lib_table()
    board = pcbnew.NewBoard(str(OUT))
    board.SetCopperLayerCount(design["board"]["layers"])
    setup_rules(board, design)
    outline(board, design)
    mounting_holes(board, design)

    nets = {}
    for name in sorted(cir.nets):
        ni = pcbnew.NETINFO_ITEM(board, name)
        board.Add(ni)
        nets[name] = ni

    parts = load_parts()
    models = load_models()
    missing, with_lcsc_model = [], 0
    for ref, comp in cir.components.items():
        fp = load_footprint(comp.footprint)
        if fp is None:
            missing.append((ref, comp.footprint))
            continue
        fp.SetReference(ref)
        fp.SetValue(comp.value)
        link_to_schematic(fp, ref)
        lcsc = parts[comp.part].get("lcsc") or ""
        fp.SetField("LCSC", lcsc)
        for field in fp.GetFields():
            if field.GetName() == "LCSC":
                field.SetVisible(False)
        entry = models.get(lcsc)
        if entry and entry.get("file"):
            attach_model(fp, entry)
            with_lcsc_model += 1
        fp.Value().SetVisible(False)
        fp.SetPosition(vec(0, 0))
        for pad in fp.Pads():
            net = comp.pins.get(pad.GetNumber(), "")
            if net:
                pad.SetNet(nets[net])
        if comp.part == "__none__":
            # Tag-Connect's footprint rules (TC2030-IDC-NL drawing, notes
            # 1-2): no other track or signal within 0.020" (0.5 mm) of a
            # contact pad and nothing between the pads. A pad clearance
            # makes DRC and the pours honour it (0.48, not 0.5: the pads
            # themselves sit 0.4826 mm apart on the 1.27 grid, and the
            # rule is about OTHER copper); route.py keeps freerouting out
            # with a keepout and pre-drawn escapes (board review B2).
            for pad in fp.Pads():
                if pad.GetNumber():
                    pad.SetLocalClearance(mm(0.48))
        board.Add(fp)
    if missing:
        for ref, f in missing:
            print(f"ERROR: footprint not found: {ref} -> {f}")
        sys.exit(1)

    legend(board, design)
    pcbnew.SaveBoard(str(OUT), board)
    sync_project_rules(design)
    print(f"wrote {OUT}: {len(cir.components)} footprints ({with_lcsc_model} with "
          f"LCSC 3D models), {len(nets)} nets, "
          f"{design['board']['width_mm']}x{design['board']['height_mm']}mm, "
          f"{design['board']['layers']} layers")


if __name__ == "__main__":
    main()
