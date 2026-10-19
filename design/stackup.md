# Stackup and rules (phase 5) — bluebuzz-rm2

Source: JLCPCB impedance-control stackups page (https://jlcpcb.com/impedance) and capabilities page (https://jlcpcb.com/capabilities/pcb-capabilities), read 2026-10-17.

## Stackup: JLC06161H-3313, 1.6 mm, 6 layers

| Layer | Role | Copper | Dielectric below | Er |
|---|---|---|---|---|
| F.Cu | parts, escapes, GND pour | 1 oz (35 µm) | 3313 prepreg 0.0994 mm | 4.1 |
| In1.Cu | solid GND plane (no wires) | 0.5 oz (15 µm) | core 0.55 mm | 4.6 |
| In2.Cu | signals (QSPI lanes, PG_N, overflow) | 0.5 oz | 2116 prepreg 0.1088 mm | 4.16 |
| In3.Cu | VSYS pour (power), few wires | 0.5 oz | core 0.55 mm | 4.6 |
| In4.Cu | solid GND plane | 0.5 oz | 3313 prepreg 0.0994 mm | 4.1 |
| B.Cu | sensors, pad rows, wiring, GND pour | 1 oz | — | |

Every outer-layer signal references a GND plane 0.1 mm below it; In2 references In1 (0.55 mm core) and In3 references In4.

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
| POWER_HI VSYS | 2.3 A peak, 1 A cont. | 0.75 mm | pour | In3 pour (whole board) + 0.4 mm feeds |
| POWER_HI VBAT | 2 A peak, 0.5 A cont. | 0.3 mm | 0.6 mm | 0.3 mm (Battery class), short |
| SWITCH_HI MOTORx_SW | 1 A | 0.3 mm | — | 0.4 mm (Power class), F.Cu only |
| POWER VBUS | 1 A | 0.3 mm | — | 0.4 mm (Power class) |
| POWER 3V3_SYS | 0.4 A | 0.15 mm | 0.3 mm | 0.2 mm (Supply class) |
| POWER 1V1 | 0.3 A | 0.15 mm | — | 0.2 mm (Supply class) |

Via capacity: 0.2 mm drill, 20–25 µm plating ≈ 0.8–1 A each at 10 °C rise. Derived counts: VSYS into the In3 pour from the charger's pins and out to the motor block and the RM2: ≥ 3 vias at each transfer (2.3 A / 0.8 A × 1.5 → 4, use 4); VBAT: 2 (the cell pad to the charger uses a 0.5/0.25 via: ≈ 1.2 A each, 2 A peak only in bursts → 2); MOTORx_SW: F.Cu only, no vias; GND: via-in-pad everywhere plus 2 mm stitching.

## Net classes in the tool (`gen_project.py`)

| Class | Width | Clearance | Via | Nets | Source |
|---|---|---|---|---|---|
| Default | 0.15 | 0.127 | 0.4/0.2 | SIGNAL, SE_HS, CLOCK, ANALOG, GATE | nets.csv |
| Power | 0.4 | 0.127 | 0.4/0.2 | GND, VBUS, VSYS, MOTOR?_SW | nets.csv POWER/POWER_HI/SWITCH_HI |
| USB | 0.15 → **set to 0.15 / gap 0.15** | 0.127 | 0.4/0.2 | USB_D?, USB_D?_C | 90 Ω above |
| Supply | 0.2 | 0.127 | 0.4/0.2 | 3V3_SYS, 3V3_SENS, 3V3A, VREG_AVDD, 1V1 | nets.csv POWER (low current) |
| Battery | 0.3 | 0.127 | 0.5/0.25 | VBAT | nets.csv POWER_HI 0.5 A cont. |

## Custom rules (as implemented in `route.py` / `audit.py`, to be moved into a `.kicad_dru` in a later pass)

- RF keep-out: no copper on any layer, no parts, top 5 mm of the board (RM2 datasheet, parts/rm2-radio.md).
- No F.Cu tracks under the RM2 body (inspectability).
- No vias / no copper pour between the RP2350's exposed pad and its pin 47 bridge guard (route.py).
- Copper to edge 0.2 mm, hole to hole 0.2 mm, PTH hole to other copper 0.28 mm (JLC).
- Thermal reliefs: none on the GND planes (solid), via-in-pad on every GND pad (JLC fills and caps on 6 layers).

## DRC severities

KiCad defaults with unconnected, clearance, courtyard overlap, hole clearance, track width, annular ring, copper-edge clearance, shorting items, items-not-allowed as errors; silk overlap/clipping, dangling vias and solder-mask bridges as warnings (`drc.py` lists every warning in the gate file). **To do:** promote silk overlap and silk-over-copper to error for phase 9.
