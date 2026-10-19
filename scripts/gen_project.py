#!/usr/bin/env python3
"""Write out/bluebuzz-rm2.kicad_pro so the generated sheet opens as a project.

Kept separate from gen_schematic.py because it is the one file a person may
legitimately want to edit by hand, so it is written once and then only
touched where it is still empty -- except the netclasses (generated design
intent, always resynced) and the board rules (gen_board.py owns those).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_schematic import SHEET_UUID  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PRO = ROOT / "out" / "bluebuzz-rm2.kicad_pro"

# The symbols are generated into the sheet itself rather than kept in an
# installed library, so KiCad cannot find a library called "gen" to compare
# them against. That is what a self-contained generated sheet looks like;
# the warning says nothing about the design, so it is turned off here
# rather than left to bury the warnings that do mean something.
ERC_IGNORE = {
    "lib_symbol_issues": "ignore",
    "footprint_filter": "ignore",
    "simulation_model_issue": "ignore",
}

DEFAULT = {
    "board": {"design_settings": {"defaults": {}, "rules": {}},
              "layer_presets": [], "viewports": []},
    "boards": [],
    "cvpcb": {"equivalence_files": []},
    "erc": {"erc_exclusions": [], "meta": {"version": 0},
            "pin_map": [], "rule_severities": {}},
    "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []},
    "meta": {"filename": "bluebuzz-rm2.kicad_pro", "version": 3},
    "net_settings": {
        "classes": [
            # "priority" is not optional: KiCad 9's loader throws on a class
            # without it and silently drops the WHOLE list (seen: pcbnew
            # loaded this file and reported no netclasses at all).
            {"name": "Default", "priority": 2147483647,
             "clearance": 0.127, "track_width": 0.15,
             "via_diameter": 0.4, "via_drill": 0.2, "microvia_diameter": 0.2,
             "microvia_drill": 0.1, "diff_pair_width": 0.2,
             "diff_pair_gap": 0.25, "diff_pair_via_gap": 0.25,
             "line_style": 0, "pcb_color": "rgba(0, 0, 0, 0.000)",
             "schematic_color": "rgba(0, 0, 0, 0.000)", "wire_width": 6,
             "bus_width": 12},
            # Power carries the charge current and the whole system load.
            {"name": "Power", "priority": 0, "clearance": 0.127, "track_width": 0.4,
             "via_diameter": 0.6, "via_drill": 0.3, "microvia_diameter": 0.2,
             "microvia_drill": 0.1, "diff_pair_width": 0.2,
             "diff_pair_gap": 0.25, "diff_pair_via_gap": 0.25,
             "line_style": 0, "pcb_color": "rgba(0, 0, 0, 0.000)",
             "schematic_color": "rgba(0, 0, 0, 0.000)", "wire_width": 6,
             "bus_width": 12},
            # Full-speed USB (12 Mbps), 20 mm of trace: impedance is not
            # critical, but 0.15 wide with a 0.15 gap is ~90 ohm differential
            # over the 0.1 mm 3313 prepreg of JLC06161H-3313 (design/stackup.md),
            # and 0.15 still fits the 0.4 mm-pitch QFN pads the pair ends on.
            {"name": "USB", "priority": 1, "clearance": 0.127, "track_width": 0.15,
             "via_diameter": 0.4, "via_drill": 0.2, "microvia_diameter": 0.2,
             "microvia_drill": 0.1, "diff_pair_width": 0.15,
             "diff_pair_gap": 0.15, "diff_pair_via_gap": 0.25,
             "line_style": 0, "pcb_color": "rgba(0, 0, 0, 0.000)",
             "schematic_color": "rgba(0, 0, 0, 0.000)", "wire_width": 6,
             "bus_width": 12},
            # The cell's lead: 500 mA of charge current, 0.3 wide so it can
            # pass the charger's thermal vias and the pads behind it.
            {"name": "Battery", "priority": 3, "clearance": 0.127, "track_width": 0.3,
             "via_diameter": 0.5, "via_drill": 0.25, "microvia_diameter": 0.2,
             "microvia_drill": 0.1, "diff_pair_width": 0.2,
             "diff_pair_gap": 0.25, "diff_pair_via_gap": 0.25,
             "line_style": 0, "pcb_color": "rgba(0, 0, 0, 0.000)",
             "schematic_color": "rgba(0, 0, 0, 0.000)", "wire_width": 6,
             "bus_width": 12},
            # The low-current rails the RP2350 and the sensors draw from:
            # 0.2 wide, so they can reach the QFN's IOVDD / DVDD pins.
            {"name": "Supply", "priority": 2, "clearance": 0.127, "track_width": 0.2,
             "via_diameter": 0.4, "via_drill": 0.2, "microvia_diameter": 0.2,
             "microvia_drill": 0.1, "diff_pair_width": 0.2,
             "diff_pair_gap": 0.25, "diff_pair_via_gap": 0.25,
             "line_style": 0, "pcb_color": "rgba(0, 0, 0, 0.000)",
             "schematic_color": "rgba(0, 0, 0, 0.000)", "wire_width": 6,
             "bus_width": 12},
        ],
        "meta": {"version": 4},
        "net_colors": None,
        "netclass_assignments": None,
        "netclass_patterns": [
            {"netclass": "Power", "pattern": "GND"},
            {"netclass": "Power", "pattern": "VBUS"},
            {"netclass": "Power", "pattern": "VSYS"},     # also the In3 pour
            {"netclass": "Battery", "pattern": "VBAT"},
            {"netclass": "Supply", "pattern": "3V3_SYS"},
            {"netclass": "Supply", "pattern": "3V3_SENS"},
            {"netclass": "Supply", "pattern": "3V3A"},
            {"netclass": "Supply", "pattern": "VREG_AVDD"},
            {"netclass": "Power", "pattern": "MOTOR?_SW"},
            {"netclass": "Supply", "pattern": "1V1"},
            {"netclass": "USB", "pattern": "USB_D?"},
            {"netclass": "USB", "pattern": "USB_D?_C"},
        ],
    },
    "pcbnew": {"last_paths": {}, "page_layout_descr_file": ""},
    "schematic": {"legacy_lib_dir": "", "legacy_lib_list": []},
    "sheets": [[str(SHEET_UUID), ""]],
    "text_variables": {},
}


def main():
    PRO.parent.mkdir(exist_ok=True)
    doc = json.loads(PRO.read_text()) if PRO.exists() else DEFAULT
    doc["sheets"] = [[str(SHEET_UUID), ""]]
    doc.setdefault("erc", {}).setdefault("rule_severities", {}).update(ERC_IGNORE)
    # The netclasses are generated design intent (and pcbnew.SaveBoard
    # rewrites this block from whatever it managed to load), so they are
    # always resynced from here rather than only filled in when missing.
    doc["net_settings"] = DEFAULT["net_settings"]
    PRO.write_text(json.dumps(doc, indent=2) + "\n")
    classes = [c["name"] for c in doc["net_settings"]["classes"]]
    print(f"wrote {PRO}: root sheet registered, netclasses {classes}")


if __name__ == "__main__":
    main()
