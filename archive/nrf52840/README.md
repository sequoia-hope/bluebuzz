# bluebuzz

A small Bluetooth vibrator controller: nRF52840 module (E73-2G4M08S1C,
onboard antenna) + BQ24074 USB-C charger with power path + two low-side
motor channels + HX711 load-cell ADC + a pressure-sensor port, on a LiPo
cell. **34 x 44 mm, 4-layer, double-sided assembly.**

The design is *generated*: edit `design.yaml` and `scripts/circuit.py`, then
rebuild. The schematic is drawn by code, wired by code, and checked against
the netlist by code; the board is placed from a table and routed by a
script. The pipeline is the bike-tracker's (`../bike-tracker`), which
supplies the nRF52840 module, the USB-C/charger/LDO blocks and every check;
the motor driver is the activity_tracker's (`../activity_tracker`).

## Pipeline

```sh
python3 build.py                  # everything: schematic -> ... -> export
python3 build.py --to place       # stop after a stage
python3 build.py --only route     # one stage
```

| stage      | script              | what it does |
|------------|---------------------|---|
| schematic  | `gen_schematic.py`  | lays out and wires `out/bluebuzz.kicad_sch`, round-trips it through `kicad-cli` and diffs it against `circuit.py` |
| project    | `gen_project.py`    | `out/bluebuzz.kicad_pro` — root sheet, netclasses (Power 0.4 / USB 0.25 mm) |
| erc        | kicad-cli           | electrical rules check |
| netlist    | kicad-cli           | `out/bluebuzz.net` |
| footprints | `gen_footprints.py` | the E73 module footprint into `library/parts.pretty/` (43 pads from the manual's drawing) |
| models     | `fetch_models.py`   | the LCSC 3D model of every part into `library/3d/`, aligned to its KiCad footprint by pad matching |
| board      | `gen_board.py`      | fresh 4-layer `out/bluebuzz.kicad_pcb`: outline, nets, footprints, JLC rules, silkscreen legend |
| place      | `place.py`          | positions every part from its table, front and back; fails on any courtyard overlap, part off the board, or part in the antenna keepout |
| preview    | `render.py --placement` | unrouted 3D render, for eyeballing placement before routing |
| route      | `route.py`          | planes + pre-placed vias + keepouts, freerouting, then re-layering (wires it cannot get off the GND plane are removed for the next two stages), outer pours, stitching |
| close      | `close_gaps.py`     | the short hops freerouting abandons: a straight line or one L where the path is provably clear (activity_tracker's) |
| finish     | `finish.py`         | A* grid router on F.Cu / In2 / B.Cu for whatever is still open (activity_tracker's) |
| drc        | `drc.py`            | kicad-cli DRC; fails on errors or unconnected items |
| audit      | `audit.py`          | the layout rules DRC cannot express (nothing conductive in the antenna keepout, nothing under the module on F.Cu, Tag-Connect pad clearance, motor path width, JLC hole-to-copper limits) |
| render     | `render.py`         | 3D renders, per-layer copper, `out/index.html` (served by `proj up bluebuzz`) |
| export     | `export.py`         | `out/jlcpcb/`: gerbers + drill zip, BOM, pick-and-place; `out/bluebuzz.step` |
| site       | pcbview             | the SCH / PCB / 3D viewer ([pcbview](https://github.com/sequoia-hope/pcbview), `~/Software/pcbview`) into `viewer/` and into `index.html` between the pcbview markers; `pcbview.toml` says what |

Needs KiCad 9 (`kicad-cli`, python `pcbnew`), Java 17+ and
`tools/freerouting.jar` (freerouting v2.2.4, not in git — copy it from
`../bike-tracker/tools/`), ImageMagick and Pillow for the renders.

## Sources of truth

- `design.yaml` — parameters: board size, charge current, the antenna
  keepout, which rail feeds the motor.
- `scripts/circuit.py` — **the electrical source of truth.** Every
  component, every pin, every net, and the decisions Z1..Z7 in its
  docstring.
- `bom/parts.yaml` — every part with its footprint, LCSC number and the
  datasheet facts that justify the choice.
- `scripts/place.py` — the placement table and the floorplan reasoning.

## What it is

| | |
|---|---|
| MCU | EBYTE E73-2G4M08S1C — nRF52840, **onboard ceramic antenna** (the bike-tracker used the u.FL `-X`). LCSC C356849. |
| Charger | BQ24074: USB-C in, 500 mA charge, 1 A input limit, 6 h safety timer, power path. VSYS feeds the LDO *and* the motor, so it runs on the cable with a flat cell. |
| Rails | TLV75533 → 3V3_SYS (always on). TPS22918 → 3V3_SENS (switched: HX711, bridge excitation, pressure port). |
| Motors | Two channels: AO3400A low-side N-FET from VSYS, 100R gate / 100k pull-down, B5819W 1 A Schottky flyback each, 2 × 22 µF bulk. PWM on P1.11 and P0.31. One 4-way JST PH 2.0 lead: VSYS M1 VSYS M2. Each channel sized for 1 A. |
| Load cell | HX711 without its internal regulator (VSUP = AVDD = DVDD = 3V3_SENS, VFB to GND, BASE/VBG open), on-chip oscillator, 80 SPS. JST SH 1.0 4-way: E+ A- A+ E-. |
| Pressure | JST SH 1.0 5-way: 3V3_SENS GND AIN SDA SCL — an analog ratiometric sensor into AIN1 (P0.03) through 10k/100n, or an I2C sensor with 4.7k pull-ups on the switched rail. |
| Sense / UI | VBAT through 1M/1M into AIN0 (P0.02). Side-actuated button (P0.13). Status LED (P0.24). Charge LED on /CHG. USB presence from the nRF52840's own VBUSDETECT (the charger's /PGOOD is left open). |
| Debug | Tag-Connect TC2030 pads on the back. USB-C also reaches the module's USB (DFU). |
| GPIO | Every signal is on a castellated **edge** pad of the module — no escape vias under it. |

## Layout

Front: module bottom-left with its antenna end **at** the bottom edge
(no copper on any layer under the antenna end, out to the edge; a
permanent rule area + the audit enforce it), USB-C top edge, the IC
column (charger, LDO, switch, FET) between the USB and the connectors,
every lead on the right edge (battery JST PH, the 4-way motor JST PH, pressure and
load-cell JST SH), the HX711 beside the module, button and LEDs on the
left edge. Back: all the passives behind their ICs, the crystal's load
caps, the Tag-Connect pads behind the module body.

Stackup: F = parts + signal, In1 = GND plane, In2 = 3V3_SYS pour, B =
parts + signal + GND pour. JLC 4-layer rules: 0.127 track/clearance,
0.4/0.2 vias, 0.2 hole-to-hole.

## The RP2350 + RM2 variant

`rm2/` holds a second board built by the same pipeline: an RP2350A host
with a Raspberry Pi Radio Module 2 (Wi-Fi + Bluetooth Classic/LE, so
A2DP audio sink and USB audio are both possible), 28 x 42 mm, six layers,
USB-C on the left edge and **every other lead on SMT pad rows on the back**,
each row a single line along an edge. See `rm2/README.md`;
its viewer is board `b` of `pcbview.toml` (`viewer/b.html`).

## Pages

- `index.html` — status, what is on it, and the **board viewer** (schematic, every copper layer, 3D with the part pane) embedded by pcbview; `proj up bluebuzz` serves it on the registered port.
- `viewer/index.html` — the same viewer filling the window.
- `out/index.html` — the pipeline's own renders, per-layer PNGs and layer-stack viewer.

## State

2026-10-17: routed, 0 DRC errors, 0 unconnected, audit clean, exported
(66 parts, 42 nets, 516 track segments, 212 vias). Not ordered. See `index.html` (the status page `proj up bluebuzz` serves) for where
it stands; `out/index.html` for the latest renders.

## Before ordering

- **Antenna keepout.** EBYTE's own keep-out drawing for the
  E73-2G4M08S1C was not retrievable when this was designed
  (2026-10-17). The board uses the generic chip-antenna rule (no copper
  under the antenna end on any layer, out to the board edge, 1 mm
  margin either side, 6.5 mm deep). Check it against the module manual.
- **JST SH 5-way (C136657) stock was 99** on 2026-10-17. Same part under
  other listings: C20089326, C5306070.
- **HX711 3D model**: LCSC's land pattern does not align with KiCad's
  SOIC-16, so the render shows KiCad's generic model. Pinout is from
  the datasheet in `docs/HX711.pdf`, not from the model.
- The firmware must tristate HX_SCK before gating 3V3_SENS off
  (DVDD is on the switched rail); R55 (1k) limits the damage if it does
  not.
