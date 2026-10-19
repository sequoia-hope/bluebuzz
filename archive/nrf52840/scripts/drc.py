#!/usr/bin/env python3
"""Run DRC via kicad-cli and summarize violations."""
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PCB = ROOT / "out" / "bluebuzz.kicad_pcb"
REPORT = ROOT / "out" / "drc.json"


def main():
    r = subprocess.run(
        ["kicad-cli", "pcb", "drc", "--format", "json", "--severity-all",
         "--all-track-errors", "-o", str(REPORT), str(PCB)],
        capture_output=True, text=True)
    if r.returncode not in (0, 5):  # 5 = violations found
        print(r.stdout, r.stderr)
        sys.exit(1)
    d = json.loads(REPORT.read_text())
    viol = d.get("violations", [])
    unconnected = d.get("unconnected_items", [])
    by_type = Counter(v["type"] for v in viol)
    print(f"DRC: {len(viol)} violations, {len(unconnected)} unconnected items")
    for t, n in by_type.most_common():
        sev = next(v["severity"] for v in viol if v["type"] == t)
        print(f"  {n:4d}  {t} ({sev})")
    # show a few details for the worst offenders
    for t, _ in by_type.most_common(3):
        v = next(v for v in viol if v["type"] == t)
        desc = v.get("description", "")
        items = "; ".join(i.get("description", "") for i in v.get("items", [])[:2])
        print(f"  e.g. {t}: {desc} [{items}]")
    errors = [v for v in viol if v["severity"] == "error"]
    sys.exit(1 if (errors or unconnected) else 0)


if __name__ == "__main__":
    main()
