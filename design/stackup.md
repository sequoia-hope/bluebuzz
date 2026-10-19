# Stackup and rules (phase 5) — bluebuzz-rm2

Source: JLCPCB impedance-control stackups page (https://jlcpcb.com/impedance) and capabilities page (https://jlcpcb.com/capabilities/pcb-capabilities), read 2026-10-17.

## Stackup: JLC06161H-3313, 1.6 mm, 6 layers

| Layer | Role | Copper | Dielectric below | Er |
|---|---|---|---|---|
| F.Cu | parts, escapes, GND pour | 1 oz (35 µm) | 3313 prepreg 0.0994 mm | 4.1 |
| In1.Cu | solid GND plane (no wires) | 0.5 oz (15 µm) | core 0.55 mm | 4.6 |
| In2.Cu | signals (QSPI lanes, PG_N, WL_CS, overflow) | 0.5 oz | 2116 prepreg 0.1088 mm | 4.16 |
| In3.Cu | solid VSYS plane (no wires) | 0.5 oz | core 0.55 mm | 4.6 |
| In4.Cu | solid GND plane | 0.5 oz | 3313 prepreg 0.0994 mm | 4.1 |
| B.Cu | sensors, pad rows, wiring, GND pour | 1 oz | — | |

Every outer-layer signal references a GND plane 0.1 mm below it (F.Cu → In1, B.Cu → In4). In2 references **In3, the VSYS plane**: it is 0.109 mm away, against 0.55 mm to In1, so In2's return current runs in In3 (phase-7 review M9). In3 is therefore a solid plane with no wires at all (`route.py` `stackup()`; freerouting sees it as a `power` layer, and VSYS is not in its netlist). A signal that changes between F.Cu and B.Cu moves its return between In1 and In4 and takes a GND via within 1.0 mm (`stitch.py`, checked by `check_planes.py`). A signal that changes between In2 and an outer layer moves its return between VSYS and GND through the nearest VSYS decoupling cap, so fast nets stay off In2 except the QSPI lanes (see `decisions.md`).

## Fab minimums (JLC, 2026-10-17) and what the board uses

| Item | JLC | Board (`design.yaml` → `gen_project.py`) |
|---|---|---|
| Trace / space, 1 oz outer, multilayer | 0.09 / 0.09 mm | 0.127 / 0.127 mm (min), 0.15 default |
| Via drill / diameter | 0.15 / 0.25 mm (0.2 / 0.3 preferred) | 0.2 / 0.4 mm |
| Via hole to hole | 0.2 mm | checked by `audit.py` |
| PTH annular ring | ≥ 0.15 mm (0.2 recommended) | 0.1 mm on 0.4/0.2 vias (= 0.2 ring diameter) |
| Copper to routed edge | 0.2 mm | 0.2 mm (`audit.py`) and 0.3 mm edge ring during routing |
| Silk line / text height | 0.15 mm / 1.0 mm | **legend 0.12 mm / 0.8 mm — below minimum, fix in phase 9** |
| Solder-mask dam | 0.10 mm | KiCad default 0.1 |
| NPTH min | 0.5 mm | receptacle pegs 0.65 mm |

## Impedance (microstrip on F/B over the 0.0994 mm 3313 prepreg, IPC-2141 estimate)

| Target | Width | Gap | Estimate | Note |
|---|---|---|---|---|
| 90 Ω differential (USB D+/D−) | 0.15 mm | 0.15 mm | ≈ 89 Ω | single-ended ≈ 50 Ω; current USB class is 0.2 / 0.127 ≈ 71 Ω, change to 0.15 / 0.15 |
| 50 Ω single-ended | 0.15 mm | — | ≈ 50 Ω | not needed: no RF trace (the RM2 carries its antenna) |

USB is Full Speed (12 Mb/s, 20 mm of trace): impedance is not critical, but the pair should still be routed as a pair on one layer over In1.

## Current-carrying widths (IPC-2152, 10 °C rise, estimates)

| Net class | Current | 1 oz outer | 0.5 oz inner | Board |
|---|---|---|---|---|
| POWER_HI VSYS | 2.3 A peak, 1 A cont. | 0.75 mm | pour | solid In3 plane; every VSYS pad has via-in-pad; the charger's OUT pins feed an F.Cu zone with 4 × 0.6/0.3 vias |
| POWER_HI VBAT | 2 A peak, 0.5 A cont. | 0.78 mm | 1.6 mm | the charger's BAT pins feed an F.Cu zone with 4 × 0.5/0.25 vias into the cell pad |
| SWITCH_HI MOTORx_SW | 1 A | 0.3 mm | — | 0.4 mm (Motor class), F.Cu only; 3 × 0.4/0.2 vias into the MOT pad |
| POWER VBUS | 1 A | 0.3 mm | 0.6 mm | 0.65 mm (Vbus class) on F.Cu, In2, B.Cu, 0.7/0.4 vias; one entry via beside C10 |
| POWER 3V3_SYS | 0.4 A | 0.15 mm | 0.3 mm | 0.2 mm (Supply class) |
| POWER 1V1 | 0.3 A | 0.15 mm | — | 0.2 mm (Supply class) |

Via capacity: 0.2 mm drill, 20–25 µm plating ≈ 0.8 A each at 10 °C rise; with the 1.5 margin, **0.53 A per 0.2 mm of drill** (`check_current.py`: 0.2 → 0.53 A, 0.25 → 0.67 A, 0.3 → 0.8 A, 0.4 → 1.07 A). Counts, each layer change sized for the design current (2 A for VSYS to the motors and for VBAT, 1 A per motor channel, 1 A VBUS):

| Transfer | Vias | Rating |
|---|---|---|
| charger OUT (F.Cu zone) → In3 | 4 × 0.6/0.3 | 3.2 A |
| In3 → MOT pad J4.1 (back) | 4 × 0.4/0.2, in the pad | 2.1 A |
| charger BAT (F.Cu zone) → cell pad J2.1 (back) | 4 × 0.5/0.25, in the pad | 2.7 A |
| MOTORx_SW F.Cu bar → J4.2 / J4.3 (back) | 3 × 0.4/0.2 each, in the pad | 1.6 A |
| flyback diodes D3 / D4 VSYS pad → In3 | 2 × 0.4/0.2 each | 1.07 A |
| RM2 VIN U7.16 → In3 (C100 on the back under it) | ≥ 2 × 0.4/0.2 | ≥ 1.07 A |
| VBUS, any layer change | 1 × 0.7/0.4 (Vbus class) | 1.07 A |
| other VSYS pads → In3 | 1 × 0.4/0.2 | 0.53 A |

GND: via-in-pad everywhere, and stitching (`stitch.py`): a return via within 1.0 mm of every signal via that moves between F.Cu and B.Cu (1.5 mm for slow nets; the motor switch nodes return through VSYS at J4.1, not GND), an edge fence (every point of the line 1.2 mm inside the outline within 1.6 mm of a GND via, i.e. ≤ 3 mm pitch), and interior stitching (every via-allowed point within 3 mm of one). The original "2 mm stitching" was never what the board had (phase-7 review M10).

## Net classes in the tool (`gen_project.py`)

| Class | Width | Clearance | Via | Nets | Source |
|---|---|---|---|---|---|
| Default | 0.15 | 0.127 | 0.4/0.2 | SIGNAL, SE_HS, CLOCK, ANALOG, GATE | nets.csv |
| Power | 0.4 | 0.127 | 0.6/0.3 | GND, VSYS (both plane nets: never routed) | nets.csv POWER/POWER_HI |
| Motor | 0.4 | 0.127 | — (F.Cu only) | MOTOR?_SW | nets.csv SWITCH_HI, 1 A: 1.24 A at 0.4 mm |
| Vbus | 0.65 | 0.127 | 0.7/0.4 (not on the planes) | VBUS | nets.csv POWER, 1 A |
| USB | 0.15 → **set to 0.15 / gap 0.15** | 0.127 | 0.4/0.2 | USB_D?, USB_D?_C | 90 Ω above |
| Supply | 0.2 | 0.127 | 0.4/0.2 | 3V3_SYS, 3V3_SENS, 3V3A, VREG_AVDD, 1V1 | nets.csv POWER (low current) |
| Battery | 0.3 | 0.127 | 0.5/0.25 | VBAT | nets.csv POWER_HI 0.5 A cont. |

## Custom rules (as implemented in `route.py` / `audit.py`, to be moved into a `.kicad_dru` in a later pass)

- RF keep-out: no copper on any layer, no parts, top 5 mm of the board (RM2 datasheet, parts/rm2-radio.md).
- LX cut-out (RP2350 s6.3.8.1): no In1 copper under the VREG_LX zone and L1's LX pad, grown by 0.25 mm (their outline, not their bounding box), and no In2 wiring under that opening (`rp2350_lx_in2_clear`).
- No F.Cu tracks under the RM2 body (inspectability).
- No vias / no copper pour between the RP2350's exposed pad and its pin 47 bridge guard (route.py).
- Copper to edge 0.2 mm, hole to hole 0.2 mm, PTH hole to other copper 0.28 mm (JLC).
- Thermal reliefs: none on the GND planes (solid), via-in-pad on every GND pad (JLC fills and caps on 6 layers).

## DRC severities

KiCad defaults with unconnected, clearance, courtyard overlap, hole clearance, track width, annular ring, copper-edge clearance, shorting items, items-not-allowed as errors; silk overlap/clipping, dangling vias and solder-mask bridges as warnings (`drc.py` lists every warning in the gate file). **To do:** promote silk overlap and silk-over-copper to error for phase 9.
