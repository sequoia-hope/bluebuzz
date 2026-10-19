# Gate 7 — routing

Status: **FAILED** (2026-10-19). Independent review: fail, with 5 BLOCKER and 7 MAJOR findings. The board is connected and DRC-clean. It fails on current capacity (single vias on every high-current layer change, and a VSYS pour cut into pieces by signal wiring) and on return-path hygiene.

Board reviewed: `out/bluebuzz-rm2.kicad_pcb` at commit `6571908` (route ordering `ROUTE_FIRST=5`).
Note: phases 2, 4, 5 and 6 have no gate files in `design/gates/`, so this gate sits on unreviewed placement and rules.

## Checklist

- [x] DRC 0 errors, 0 unrouted (`drc.rpt`: 9 violations, all silkscreen warnings; 0 unconnected pads)
- [ ] Parity 0 differences. Connectivity: **0 differences** (`check_parity.txt`). KiCad's own parity: 85 `net_conflict`, all name-only (24 nets renamed one to one) or unconnected-pin placeholders (`drc_parity.rpt`). The 6 BOM/DNP flag mismatches are fixed (`DNP` set in `circuit.py`, written to the schematic by `gen_schematic.py`).
- [ ] Current capacity: **FAIL**. `check_current.txt` shows 7 FAILs, and the review found the VSYS pour is two pieces joined by 0.24–0.32 mm necks (finding B1), which the check could not see.
- [ ] Plane integrity: **FAIL**. In1 and In4 are each one piece, and no fast track leaves its plane. Four fast-net vias change between In1 and In4 with no GND via within 1.5 mm. The review found the In2/In3 reference model is wrong (M9).
- [ ] Every warning explained: the 9 silk warnings are listed below and deferred to phase 9.
- [x] Per-layer renders reviewed (`copper_*.png`, about 64 px/mm, every layer viewed from the front).
- [ ] PCB view regenerated (after the fixes).

## Evidence

Commands (from the project root):

```
kicad-cli pcb drc --severity-all --all-track-errors --format report -o design/gates/phase7/drc.rpt out/bluebuzz-rm2.kicad_pcb
kicad-cli pcb drc --schematic-parity --severity-all --format report -o design/gates/phase7/drc_parity.rpt out/bluebuzz-rm2.kicad_pcb
python3 scripts/check_parity.py   > design/gates/phase7/check_parity.txt    # exit 0
python3 scripts/check_current.py  > design/gates/phase7/check_current.txt   # exit 1
python3 scripts/check_planes.py   > design/gates/phase7/check_planes.txt    # exit 1
python3 scripts/audit.py          > design/gates/phase7/audit.txt           # exit 0
```

```
** Found 9 DRC violations **          (drc.rpt; 1 silk_overlap, 4 silk_over_copper, 4 silk_edge_clearance)
** Found 0 unconnected pads **
connectivity differences: 0           (check_parity.txt; 24 nets renamed only)
FAIL  VBUS  USB-C -> U2 IN        0.53 A of 1.00 A  neck: one 0.2 via at (86.65,85.75)
FAIL  VBAT  U2 BAT -> cell pad    0.67 A of 2.00 A  neck: one 0.25 via at (93.80,88.80)
FAIL  VSYS  U2 OUT -> J4.1 (MOT)  0.80 A of 2.00 A  neck: one 0.3 via at (96.69,120.18)
FAIL  MOTOR1_SW Q1/D3 -> J4.2     0.53 A of 1.00 A  neck: one 0.2 via at (99.85,120.45)
FAIL  MOTOR2_SW Q2/D4 -> J4.3     0.80 A of 1.00 A  neck: one 0.3 via at (106.76,120.71)
ok    VSYS -> U7 (0.35 A), VSYS -> U3 (0.25 A), 3V3_SYS -> U1 / U7
In1.Cu / In4.Cu: 1 piece each; no fast track off its plane > 0.5 mm
FAIL  USB_DM (100.25,113.09) 2.22 mm, USB_DM (104.70,95.59) 2.00 mm, WL_CLK (100.45,102.30) 3.29 mm,
      WL_CLK (97.00,88.10) 1.55 mm to the nearest GND via
audit: clean
```

The 9 silkscreen warnings (deferred to phase 9; none involves copper):
- U2 / R13 silk overlap.
- Silk clipped by mask:
  - the "ST" text at (87.7,112.85)
  - U7's pin-1 circle
  - L1's dot
  - U2's polygon
- Silk past the board edge:
  - U7's outline (×2), because the module's silk is drawn beyond its body at the top edge
  - J1's outline (×2), because the receptacle overhangs the bottom edge

## Independent review (fresh context; artifacts and this checklist only)

Findings as reported, each with its status. B = BLOCKER, M = MAJOR, m = MINOR.

| # | Finding | Status |
|---|---|---|
| B1 | In3 VSYS pour fills as 2 pieces (583 + 176 mm², confirmed), joined to the charger by 0.24–0.32 mm necks. 312 mm of signal wire on In3 (TAC_SDO 37.6, VBUS 33.2, TAC_SDI 32.7, WL_CS 22.8, TAC_SCK 18.5, TAC_CS4 16.4, WL_CLK 15.6, RUN 15.4 mm …). | open |
| B2 | Motor VSYS feed to J4.1 (2 A) through single vias at each transfer. | open |
| B3 | MOTOR1_SW / MOTOR2_SW: one via each into J4 (on the back) for 1 A. | open |
| B4 | VBUS (1 A) reaches U2.13 through one 0.2 via; 33 mm on In3 at 0.4 mm (≈0.75 A), 8 vias along the way. | open |
| B5 | VBAT cell path: one 0.25 via (stackup.md itself asks for 2); 0.3 mm on F.Cu. | open |
| M6 | In1 LX cut-out 1.7 × 5.4 mm, larger than LX + L1's pad; the In2 VBAT sense trace (to R60/R61, 500 kΩ source) crosses it 0.65 mm under the switch node; VREG_AVDD on F.Cu crosses its edge. | open |
| M7 | Return vias missing at fast-net layer changes (above). Also 63 of 69 signal vias that move the return between In1 and In4 have no GND via within 1 mm. | open |
| M8 | WL_CLK (gSPI, ≤ 50 MHz) runs 15.6 mm on In3, 0.109 mm under In2 traffic. | open |
| M9 | In2 ↔ In3 are 0.109 mm apart (0.55 mm cores to In1 / In4), so In2 signals reference the cut-up In3 pour, not In1. QSPI SCLK/SD0/SD3 on In2 are over VSYS copper for only 28–36 % of their length, with broadside parallel runs at 0.109 mm. `check_planes.py`'s reference map is wrong for In2/In3. | open |
| M10 | GND stitching far below stackup.md's "2 mm": 102 GND vias, edge gaps up to 15 mm, 26 % of the board > 2 mm from a GND via (worst 5.2 mm at (86.2,111.5)). | open |
| M11 | RM2 VIN (U7.16) on one 0.2 via; its 10 µF (C100) 6 mm away. | open |
| M12 | Check-script gaps: pours counted as unlimited capacity; VSYS fill pieces not checked; voids informational only; wrong In2/In3 references; return-via test only on fast nets; no stitching-density check. | open |
| m13 | 36 right-angle bends and 7 acute or doubled joints (U2 pad stubs, MOTOR1_SW at (100.0,120.31), QSPI_SS at (98.55,103.2)). | open |
| m14 | B.Cu GND pour in 23 pieces, 4 unconnected around U22/U20; F.Cu sliver at (113.2–113.6,107.3–108.9). | open |
| m15 | USB_DM joins J1 A7/B7 through 4 vias and a 2.9 mm In3 hop (DP uses 2). | open |
| m16 | XIN 5.2 mm against the 5 mm limit in nets.csv. | open |
| m17 | C12 6.6 mm from U2.2; C100 6 mm from U7.16. | open |
| m18 | Silk warnings not explained in the gate file. | explained above, phase 9 |
| m19 | MOTOR1_SW runs 4.6 mm under the USB-C body, 0.2 mm from a shell pad: legal but uninspectable. | open |

Reviewer's notes (no action): parity differences are name-only; RF keep-out clean on all six layers; RM2 body has a GND pour with a 3 × 3 via grid and no F.Cu tracks under it; PGND single return point verified; crystal block clean apart from m16; DRC 0/0, ERC 0/0.

Verdict (reviewer): **fail**. In3 must become a power layer again, every power transition needs a via array, and the check methods must be corrected before resubmission.

## Fix plan (proposed, not started)

1. **In3 carries VSYS only** (B1, M8, M9, part of B4): forbid signal routing on In3 in the DSN. In2 then takes the overflow over In1, and the In3 pour becomes a solid VSYS plane. WL_CLK's In3 pre-route moves to In2 or F.Cu.
2. **Via arrays at every power transition** (B2–B5, M11), sized from stackup.md (0.2 mm drill ≈ 0.8 A, × 1.5 margin):
   - in the pads: J4.1 (≥ 4), J4.2 / J4.3 (≥ 3 each), J2.1 (≥ 3), U7.16 (2)
   - beside U2's VBUS / VBAT / VSYS pins
   - locked before freerouting, as pre-routes
3. **VBUS** (B4): a pour or a ≥ 0.6 mm outer-layer trace from the receptacle up the left edge to the charger, with ≥ 2 vias at every transfer. It is no longer on In3.
4. **Return vias** (M7): a GND via within 1 mm of every signal via that moves between In1 and In4; first the USB pair's four and WL_CLK's two.
5. **LX cut-out** (M6): shrink to LX + L1's pad as the chip notes say; keep VBAT_SENSE and VREG_AVDD over solid GND.
6. **Stitching** (M10): an edge ring at ≤ 3 mm pitch plus stitching around the crystal, motor block and RM2 pad row.
7. **Checks** (M12): `check_current.py` rates pours by their fill (a neck width from the deflated fill); `check_planes.py` gets the true In2/In3 references, checks the VSYS fill is one piece, and flags all return vias; `audit.py` checks stitching density.
8. **Minor** (m13–m17, m19): cleanup pass after re-routing; the right-angle bends are mostly freerouting's.
9. **Parity names**: label the 24 nets in the schematic (`SCH_NAME_LOCAL_NETS`) so KiCad's parity is also clean, or keep the waiver; user's call (it reverses an earlier schematic-review decision to keep block-internal nets unlabelled).

Then re-route, re-run every check, and re-review.
