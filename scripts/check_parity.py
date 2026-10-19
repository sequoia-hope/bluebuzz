#!/usr/bin/env python3
"""Connectivity parity: schematic netlist vs routed board, by pads, not names.

KiCad's own parity check (kicad-cli pcb drc --schematic-parity) also
compares net NAMES. The generated schematic leaves block-internal nets
unlabelled (a wire is the connection; see gen_schematic.label), so KiCad
calls them Net-(U5-CT) while the board carries circuit.py's CT_SENS, and
every unconnected pin is its own unconnected-(...) net in the schematic
but has no net on the board. This check compares what matters for the
copper: which pads are joined. Each schematic net's pads must be exactly
one board net's pads, and a single-pad schematic net must be a pad with no
net (or a net of its own) on the board. Exits 1 on any difference.

    python3 scripts/check_parity.py
"""
import re
import sys
from collections import defaultdict
from pathlib import Path

import pcbnew

ROOT = Path(__file__).resolve().parent.parent
NETLIST = ROOT / "out" / "bluebuzz-rm2.net"
PCB = ROOT / "out" / "bluebuzz-rm2.kicad_pcb"


def schematic_nets():
    """{net name: {(ref, pin)}} from kicad-cli's netlist."""
    nets, cur = {}, None
    for line in NETLIST.read_text().splitlines():
        m = re.search(r'\(net \(code "\d+"\) \(name "((?:[^"\\]|\\.)*)"\)', line)
        if m:
            cur = m.group(1)
            nets[cur] = set()
            continue
        m = re.search(r'\(node \(ref "([^"]+)"\) \(pin "([^"]+)"\)', line)
        if m and cur is not None:
            nets[cur].add((m.group(1), m.group(2)))
    return nets


def board_nets(board, refs):
    """{net name: {(ref, pad)}} for pads of schematic parts; '' for no net."""
    nets = defaultdict(set)
    for fp in board.GetFootprints():
        if fp.GetReference() not in refs:
            continue                       # board-only (mounting holes, art)
        for pad in fp.Pads():
            if not pad.GetNumber():
                continue                   # unnumbered (paste / mechanical) pads
            nets[pad.GetNetname()].add((fp.GetReference(), pad.GetNumber()))
    return nets


def main():
    sch = schematic_nets()
    refs = {r for pads in sch.values() for r, _ in pads}
    board = pcbnew.LoadBoard(str(PCB))
    brd = board_nets(board, refs)
    pad_to_board = {p: n for n, pads in brd.items() for p in pads}
    problems, renamed, singles = [], {}, 0
    for name, pads in sorted(sch.items()):
        bnets = {pad_to_board.get(p, "<missing pad>") for p in pads}
        if len(pads) == 1:
            singles += 1
            (p,) = pads
            b = pad_to_board.get(p, "<missing pad>")
            if b not in ("",) and brd.get(b) != pads:
                problems.append(f"{name}: lone pin {p} is on board net {b!r} with {sorted(brd.get(b, ()))}")
            continue
        if len(bnets) != 1:
            problems.append(f"{name}: its pads are split over board nets {sorted(bnets)}")
            continue
        (b,) = bnets
        if b == "":
            problems.append(f"{name}: pads {sorted(pads)} have no net on the board")
        elif brd[b] != pads:
            extra = sorted(brd[b] - pads)
            problems.append(f"{name}: board net {b!r} also joins {extra}")
        elif b != name:
            renamed[name] = b
    print(f"schematic nets: {len(sch)} ({singles} single-pin), board nets: {len([n for n in brd if n])}")
    print(f"renamed only (same pads): {len(renamed)}")
    for s, b in sorted(renamed.items(), key=lambda kv: kv[1]):
        print(f"  {b:14s} <- {s}")
    print(f"connectivity differences: {len(problems)}")
    for p in problems:
        print(f"  DIFF  {p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
