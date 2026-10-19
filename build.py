#!/usr/bin/env python3
"""Build orchestrator: runs the pipeline stages in order.

Usage:
  python3 build.py                  # all stages
  python3 build.py --to schematic   # stop after a stage
  python3 build.py --only erc       # run a single stage

Schematic stages first (schematic / project / erc / netlist), then the
board (footprints / models / board / place / preview / route / close /
finish / stitch / drc / audit / render / export), then the pcbview site (site). Every stage regenerates its output from circuit.py + design.yaml
+ the placement table; nothing in out/ is hand-edited.
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
STAGES = ["schematic", "project", "erc", "netlist",
          "footprints", "models", "board", "place", "preview", "route",
          "close", "finish", "stitch", "drc", "audit", "render", "export", "site"]
SCRIPTS = {
    "schematic": "gen_schematic.py",
    "project": "gen_project.py",
    "footprints": "gen_footprints.py",
    "models": "fetch_models.py",          # LCSC 3D models; network only for new parts
    "board": "gen_board.py",
    "place": "place.py",
    "preview": "render.py --placement",   # unrouted render, before routing
    "route": "route.py",
    "close": "close_gaps.py",             # the short hops freerouting abandons
    "finish": "finish.py",                # grid router for what close cannot
    "stitch": "stitch.py",                # GND return vias, edge fence, interior stitching
    "drc": "drc.py",
    "audit": "audit.py",                  # layout rules DRC cannot express (board review)
    "render": "render.py",
    "export": "export.py",
}
# kicad-cli needs a writable HOME and no display when run headless
ENV = dict(os.environ,
           HOME=os.environ.get("KICAD_HOME", "/tmp/kh"),
           XDG_CONFIG_HOME=os.environ.get("KICAD_HOME", "/tmp/kh") + "/.config",
           XDG_CACHE_HOME=os.environ.get("KICAD_HOME", "/tmp/kh") + "/.cache",
           QT_QPA_PLATFORM="offscreen")
SCH = ROOT / "out" / "bluebuzz-rm2.kicad_sch"


def run(cmd, cwd=ROOT):
    return subprocess.run(cmd, cwd=cwd, env=ENV)


def stage_script(name):
    parts = SCRIPTS[name].split()
    script = ROOT / "scripts" / parts[0]
    if not script.exists():
        print(f"[{name}] SKIP — {script.name} not written yet")
        return True
    return run([sys.executable, str(script)] + parts[1:]).returncode == 0


def stage_erc():
    """ERC is a gate on errors; warnings are reported."""
    rpt = ROOT / "out" / "erc.rpt"
    r = run(["kicad-cli", "sch", "erc", "--output", str(rpt),
             "--severity-all", str(SCH)])
    if not rpt.exists():
        return False
    counts = {}
    for line in rpt.read_text().splitlines():
        if line.startswith("["):
            k = line[1:line.index("]")]
            counts[k] = counts.get(k, 0) + 1
    if counts:
        for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
            print(f"    {v:4}  {k}")
    else:
        print("    clean")
    return r.returncode in (0, 5)


def stage_netlist():
    out = ROOT / "out" / "bluebuzz-rm2.net"
    return run(["kicad-cli", "sch", "export", "netlist",
                "--output", str(out), str(SCH)]).returncode == 0


PCBVIEW = Path.home() / "Software" / "pcbview" / "bin" / "pcbview"


def stage_site():
    """The SCH / PCB / 3D viewer (pcbview, ~/Software/pcbview) into viewer/
    and into index.html between the pcbview markers; pcbview.toml says what."""
    if not PCBVIEW.exists():
        print(f"[site] SKIP -- {PCBVIEW} not installed")
        return True
    # pcbview reads KiCad's own settings for the 3D model library, so it
    # gets the real HOME, not kicad-cli's scratch one
    env = dict(ENV, HOME=str(Path.home()), XDG_CONFIG_HOME=str(Path.home() / ".config"))
    return subprocess.run([str(PCBVIEW), "build", str(ROOT / "pcbview.toml"),
                           "--board", "b"], cwd=ROOT, env=env).returncode == 0


RUNNERS = {name: (lambda n=name: stage_script(n)) for name in SCRIPTS}
RUNNERS["site"] = stage_site
RUNNERS["erc"] = stage_erc
RUNNERS["netlist"] = stage_netlist


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", choices=STAGES, help="stop after this stage")
    ap.add_argument("--only", choices=STAGES, help="run a single stage")
    args = ap.parse_args()

    if args.only:
        stages = [args.only]
    elif args.to:
        stages = STAGES[: STAGES.index(args.to) + 1]
    else:
        stages = STAGES

    for name in stages:
        print(f"\n=== [{name}] ===")
        t0 = time.time()
        ok = RUNNERS[name]()
        print(f"=== [{name}] {'ok' if ok else 'FAILED'} in "
              f"{time.time() - t0:.1f}s ===")
        if not ok:
            print(f"\nBuild stopped at stage '{name}'.")
            sys.exit(1)
    print("\nBuild complete.")


if __name__ == "__main__":
    main()
