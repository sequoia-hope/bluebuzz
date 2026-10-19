# U30 — LSM6DS3TR-C 6-axis IMU (accelerometer + gyroscope)

**Datasheet: NOT AVAILABLE.** The LSM6DS3TR-C datasheet could not be downloaded (ST and the
distributor mirrors block the fetcher). This audit is written against
`datasheets/lsm6dso-family-reference.pdf` (ST LSM6DSO, DS12140 Rev 2, January 2019, 172 pages,
read in full). The LSM6DSO is a newer part in the same LGA-14 2.5 x 3 x 0.83 mm package with the
same pin positions, but it is a different die: different current figures, different WHO_AM_I, an
extra MIPI I3C interface, different default pin states. **Every number below that comes from the
LSM6DSO datasheet is tagged `[DSO-VERIFY]`, which means "LSM6DSO reference — VERIFY against the
LSM6DS3TR-C datasheet".** Nothing tagged this way may be treated as confirmed for U30 until the
real datasheet is attached and this file is re-checked.

MPN: LSM6DS3TR-C   Supplier: JLC/LCSC C967633 ($1.67 at qty 1, 13973 in stock, checked 2026-10-17; extended part, one loading fee)
Footprint: `Package_LGA:LGA-14_3x2.5mm_P0.5mm_LayoutBorder3x4y` (KiCad library; its description cites the LSM6DS3TR-C datasheet). Compared against LSM6DSO Figure 25 (p.151) and the EasyEDA land for C967633 below.
Wiring: Block 7 of `scripts/circuit.py` (lines 246-256). Placement: `scripts/place.py` line 195, left edge, middle.

## Pinout — LSM6DSO Table 1 (p.7-8) vs the circuit

LSM6DSO pin names and Mode 1 (host I2C/SPI, no sensor hub, no aux SPI) function, against what Block 7 wires. `[DSO-VERIFY]` applies to the whole table: the LSM6DS3TR-C pin *positions* are believed identical (the KiCad footprint generator used the LSM6DS3TR-C drawing and yields the same 4/3/4/3 pattern), but pins 10 and 11 are plain NC on the LSM6DS3TR-C rather than OCS_Aux/SDO_Aux, and INT1 has no I3C-detect role there.

| Pin | LSM6DSO name | Mode 1 function (p.7-8) | Circuit (Block 7) | Verdict |
|---|---|---|---|---|
| 1 | SDO/SA0 | I2C address LSB; input, no pull-up by default (Table 19) | GND | OK, address 0x6A (see below) |
| 2 | SDx | "Connect to VDDIO or GND"; input without pull-up | **open** | **MAJOR: floating input, tie to GND** |
| 3 | SCx | "Connect to VDDIO or GND"; input without pull-up | **open** | **MAJOR: floating input, tie to GND** |
| 4 | INT1 | programmable interrupt; default input with pull-down; must be '0' or open at power-on when I2C/SPI used (Table 19 note 2) | IMU_INT1 → GPIO17 | OK if GPIO17 is high-Z/low at power-up (see fine print) |
| 5 | VDDIO | I/O supply, "recommended 100 nF filter capacitor" | 3V3_SYS, C132 100n | OK |
| 6 | GND | 0 V | GND | OK |
| 7 | GND | 0 V | GND | OK |
| 8 | VDD | core supply, "recommended 100 nF filter capacitor" | 3V3_SYS, C130 100n + C131 10u | OK |
| 9 | INT2 | programmable interrupt 2 / DEN; default output forced to ground | IMU_INT2 → GPIO18 | OK |
| 10 | OCS_Aux (NC on LSM6DS3TR-C) | "Leave unconnected" (footnote: electrically unconnected and soldered to PCB) | open | OK |
| 11 | SDO_Aux (NC on LSM6DS3TR-C) | "Connect to VDD_IO or leave unconnected" | open | OK |
| 12 | CS | 1 = I2C enabled / SPI idle; 0 = SPI mode, I2C disabled; internal pull-up 30-50 kΩ | 3V3_SYS | OK, I2C selected (p.17: "CS line must be tied high, i.e. connected to Vdd_IO") |
| 13 | SCL | I2C clock; input without pull-up | SCL, R131 4.7k to 3V3_SYS | OK |
| 14 | SDA | I2C data; input without pull-up | SDA, R130 4.7k to 3V3_SYS | OK |

The schematic symbol pin map in `scripts/gen_schematic.py` (line 927-929) uses the same names and agrees with this table.

## Absolute max vs our worst case (LSM6DSO Table 7, p.15) `[DSO-VERIFY]`

| Parameter | Abs max | Our worst case | Margin |
|---|---|---|---|
| VDD | -0.3 to 4.8 V | 3.3 V from TLV75533 (3V3_SYS); LDO input is VSYS ≤ 4.4 V, so even an LDO failure cannot exceed 4.8 V | OK |
| Vin on any control pin (CS, SCL, SDA, SDO/SA0, INT) | -0.3 to VDD_IO + 0.3 V | all pulled/driven from 3V3_SYS, the same rail as VDDIO | OK, no rail can lead another |
| Acceleration | 20,000 g for 0.2 ms | ERM vibration 100-300 Hz, drops of a hand-held device (hundreds to a few thousand g) | OK |
| Storage temperature | -40 to +125 °C | reflow per J-STD-020, then room temperature in rubber | OK |
| Operating temperature | -40 to +85 °C | body-contact device, motors warm the casting a few degrees | OK |
| ESD (HBM) | 2 kV | handled during assembly and test only; pads are inside the casting afterwards | OK with normal ESD practice |

"Supply voltage on any pin should never exceed 4.8 V" (note under Table 7). "This device is sensitive to mechanical shock, improper handling can cause permanent damage" and "sensitive to electrostatic discharge" (p.15).

## Operating conditions (LSM6DSO Table 3, p.12) `[DSO-VERIFY]`

| Parameter | Min | Typ | Max | Ours |
|---|---|---|---|---|
| VDD | 1.71 | 1.8 | 3.6 V | 3.3 V OK |
| VDD_IO | 1.62 | | 3.6 V | 3.3 V OK |
| VIH | 0.7 x VDD_IO = 2.31 V | | | RP2350 drives 3.3 V CMOS, OK |
| VIL | | | 0.3 x VDD_IO = 0.99 V | OK |
| VOH (IOH = 4 mA) | VDD_IO - 0.2 = 3.1 V | | | into RP2350 GPIO input, OK |
| VOL (IOL = 4 mA) | | | 0.2 V | with 4.7 k pull-ups the sink is 0.7 mA, OK |
| Turn-on time | | 35 ms | | firmware: wait before first access after power-up |

Supply sequencing: the LSM6DSO datasheet states no VDD/VDDIO order requirement. The only constraint is the abs-max on control pins (Vin ≤ VDD_IO + 0.3 V), which forbids driving SDA/SCL/CS/INT before VDDIO is up. Here VDD, VDDIO, the pull-ups and the RP2350 IOVDD are all 3V3_SYS, so they rise together and the question does not arise. `[DSO-VERIFY]` that the LSM6DS3TR-C datasheet likewise has no ordering note (some ST MEMS parts require VDDIO ≤ VDD or VDD first; the same-rail design is immune either way).

## I2C address and interface selection

- Slave address (p.18): 110101x b. With SDO/SA0 = GND the LSB is 0: **7-bit 0x6A**, write 0xD4, read 0xD5. `[DSO-VERIFY]` — the LSM6DS3TR-C uses the same 0x6A/0x6B scheme per the decision log entry of 2026-10-17 but this must be confirmed in its Table 10 equivalent.
- CS high selects I2C (p.17). CS has an internal pull-up (30-50 kΩ, p.39 `[DSO-VERIFY]`) so a hard tie to 3V3_SYS is belt-and-braces and correct.
- I2C fast mode 400 kHz supported, standard mode too (Table 6, p.14) `[DSO-VERIFY]`. Both SDA and SCL "must be connected to Vdd_IO through external pull-up resistors" (p.17).
- Pull-up value: the datasheet application figure (Figure 21, p.35) shows Rpu = 10 kΩ `[DSO-VERIFY]`. The design uses 4.7 k. See the calculation below; 4.7 k is within the device's sink capability and is the better choice for 400 kHz.
- WHO_AM_I (0x0F) reads 0x6C on the LSM6DSO (p.49). `[DSO-VERIFY]` — the LSM6DS3TR-C returns a different value (believed 0x6A); firmware must use the LSM6DS3TR-C value.
- LSM6DSO only: the SDA/SCL pins also carry MIPI I3C, and the datasheet recommends writing I3C_disable = 1 in CTRL9_XL during initial configuration when I3C is unused (p.59). The LSM6DS3TR-C has no I3C `[DSO-VERIFY]`; if confirmed, this item and the INT1 power-on rule below do not apply.
- Other 0x6A users on I2C1: none. The I2C1 bus (GPIO6/7) carries only the IMU; the DPS368 array is on SPI (circuit.py line 113 comment), so there is no address clash and no second set of pull-ups.

## Required external parts (from datasheet)

- VDD decoupling: 100 nF ceramic "as near as possible to the supply pin" (p.35, Figure 21 C1) → C130 100n. C131 10 µF is additional bulk, not required by the datasheet; harmless and useful because the IMU shares 3V3_SYS with the RP2350 and RM2.
- VDDIO decoupling: 100 nF ceramic close to pin 5 (Figure 21 C2) → C132 100n.
- I2C pull-ups on SDA and SCL to VDD_IO (p.17, Figure 21) → R130, R131 4.7 k.
- Nothing else: no external reference, crystal, or filter.

## Calculations

- **I2C pull-up.** Sink limit: the device guarantees VOL ≤ 0.2 V at 4 mA (Table 3 note 2) `[DSO-VERIFY]`; the I2C spec limit is 3 mA. Current through 4.7 k at 3.3 V: I = 3.3 / 4700 = 0.70 mA, well under both. Rise time: fast mode allows tr ≤ 300 ns; tr ≈ 0.8473 x R x Cb, so Cb,max = 300 ns / (0.8473 x 4.7 k) ≈ 75 pF. The bus is one IMU plus the RP2350 pins and a few centimetres of trace (≈ 20-30 pF), so 4.7 k meets fast mode with margin. The datasheet's 10 k example would give Cb,max ≈ 35 pF, tighter. Chosen value: 4.7 k, 0402, 1%/5% either is fine. Standby cost: none while the bus idles high (no current flows through the pull-ups).
- **Decoupling.** 100 nF per supply pin as specified; 10 µF bulk. DC-bias derating on C131: a 10 µF X5R 0603 at 3.3 V typically retains 70-80% (≈ 7-8 µF), far more than needed for a 0.55 mA load `[DSO-VERIFY]`. Voltage rating ≥ 6.3 V (≥ 1.9x margin at 3.3 V); 10 V preferred if the shared 10u part is 10 V anyway. The 100n parts at 3.3 V are uncritical (16 V X7R 0402 is the usual choice).
- **Supply current / power budget.** `[DSO-VERIFY]` all of: combo accel+gyro high-performance 0.55 mA; accel only high-performance 170 µA; accel low-power 26 µA at 52 Hz, 4.5 µA at 1.6 Hz; accel ultra-low-power 9.5 µA at 52 Hz; power-down 3 µA (Table 3, p.12). `intent.md` budgets 1 mA for the IMU, so even the worst mode fits. Wake-on-motion standby (accel only, low power, gyro off) is tens of µA. The LSM6DS3TR-C is an older process and draws more (believed ≈ 0.9 mA combo high-performance); the 1 mA budget line should be re-checked against the real Table.
- **Data rate.** `intent.md` asks for 100 Hz: select ODR = 104 Hz for both sensors (Tables 44 and 48, p.50-51) `[DSO-VERIFY]`; the LSM6DS3TR-C has the same 104 Hz step.

## Fine print / gotchas

- **SDx/SCx must not float.** Table 1 Mode 1: "Connect to VDDIO or GND". Table 19: default "input without pull-up" on both. Figure 21 shows them bussed to "GND or VDDIO". Block 7 leaves pins 2 and 3 open → two floating CMOS inputs on an always-on part: extra leakage, possible noise coupling, and if firmware ever enables the sensor hub they become an I2C master with nowhere to go. **Tie both to GND** (simplest; the sensor hub is never used). `[DSO-VERIFY]` — the LSM6DS3TR-C pin table carries the same "Connect to VDDIO or GND" wording for Mode 1 per the family convention; confirm.
- **INT1 at power-on (LSM6DSO only).** Table 19 note 2: "INT1 must be set to '0' or left unconnected during power-on if the I2C/SPI interfaces are used." INT1 defaults to an input with pull-down; if it is high at power-up the device becomes I3C-only and the I2C slave is disabled (Section 5.3, p.25). GPIO17 on the RP2350 is high-impedance at reset and the two chips share a rail, so this is satisfied as long as firmware never configures GPIO17 as an output driving high before the IMU has booted (35 ms). `[DSO-VERIFY]`: the LSM6DS3TR-C has no I3C, so this rule probably does not exist there; keep GPIO17 as an input regardless.
- **INT polarity and drive.** CTRL3_C (p.52): H_LACTIVE = 0 → interrupts active high; PP_OD = 0 → push-pull. Defaults are push-pull active-high, so no pull-ups are needed on IMU_INT1/IMU_INT2 and none are fitted. INT2 is "output forced to ground" at power-on (Table 19); INT1 is an input with pull-down until configured. If firmware ever selects open-drain (PP_OD = 1) it must also enable the RP2350 internal pull-ups on GPIO17/18. `[DSO-VERIFY]` for the LSM6DS3TR-C register defaults (same CTRL3_C bit names are expected).
- **Pins 10/11:** "Leave pin electrically unconnected and soldered to PCB" (Table 1 footnote 2). The KiCad footprint has pads for them, so they get soldered; they are not on any net. Correct.
- **Interrupt routing.** All interrupt sources can be ORed onto INT1 with INT2_on_INT1 (CTRL4_C, p.53), so INT2 is a convenience, not a requirement. Wake-up goes through MD1_CFG INT1_WU (p.79), tap through INT1_SINGLE_TAP/DOUBLE_TAP, activity/inactivity through INT1_SLEEP_CHANGE and TAP_CFG2 INACT_EN (p.74), which drops the accelerometer to 12.5 Hz and can power the gyro down automatically. `[DSO-VERIFY]` register names and bit positions against the LSM6DS3TR-C map before writing firmware; the two parts' maps differ.
- **Reserved registers:** writing them "may cause permanent damage to the device" (p.90, p.125, p.137). Firmware must never write unknown addresses, and must use the LSM6DS3TR-C map, not this one.
- **Offsets shift with board stress.** Section 4.6.2 (p.16): the zero-g and zero-rate levels are "to some extent a result of stress to the MEMS sensor and therefore ... can slightly change after mounting the sensor onto a printed circuit board or exposing it to extensive mechanical stress." Typical zero-g accuracy ±20 mg, zero-rate ±1 dps (Table 2) `[DSO-VERIFY]`. The casting step adds stress (rubber shrinkage and any board bending during potting); plan an offset calibration after casting, stored by firmware. The LSM6DSO has user offset registers X/Y/Z_OFS_USR (p.86-87) that subtract a stored accelerometer offset in hardware; `[DSO-VERIFY]` whether the LSM6DS3TR-C has the equivalent (believed yes, at 0x73-0x75).
- **Vibration and the embedded functions.** The ERM motors run at 100-300 Hz on the same 28 x 44 mm board. Wake-up, tap and activity detection use the accelerometer slope/high-pass path (Figure 24, p.58); they will trigger continuously while a motor runs. This is firmware (gate detection while motors are on, or raise thresholds), not a hardware defect, but it is worth stating in intent.md so nobody expects tap detection during play. The gyroscope will also show vibration-induced rate noise; its LPF2 at 104 Hz ODR has a 33 Hz cutoff (Table 18) `[DSO-VERIFY]`.
- **Temperature sensor** is on-chip (Table 4, ±15 °C offset) `[DSO-VERIFY]`; it reads the die, which the casting insulates, so it is a poor body-temperature sensor but fine for offset temperature compensation.
- **Washing / ultrasonic:** the datasheet says nothing beyond "qualified for soldering heat resistance according to JEDEC J-STD-020" (p.150). ST's general MEMS guidance (not in this document) is to avoid ultrasonic cleaning. The user washes the finished cast body only, with the board sealed inside; fine. Do not ultrasonic-clean the bare assembly before casting.

## Land pattern vs the KiCad footprint

Package (LSM6DSO Figure 25, p.151) `[DSO-VERIFY]`: L = 2.50 ±0.1, W = 3.00 ±0.1, H = 0.86 max; 14 pads 0.25 ±0.05 x 0.475 ±0.05 mm, 0.5 mm pitch, pad outer edge 0.1 mm inside the body edge; the 4-pad columns span 1.5 mm, the 3-pad rows span 1.0 mm. From that drawing the package pad centres are at:

| Group | Package pad centre | KiCad pad centre | KiCad pad size | EasyEDA (C967633) pad centre | EasyEDA pad size |
|---|---|---|---|---|---|
| 4-pad columns (pins 1-4, 8-11) | x = ±(1.50 - 0.10 - 0.2375) = ±1.1625 | ±1.1625 | 0.625 x 0.35 | ±1.262 (2.524 apart) | 0.68 x 0.28 |
| 3-pad rows (pins 5-7, 12-14) | y = ±(1.25 - 0.10 - 0.2375) = ±0.9125 | ±0.9125 | 0.35 x 0.625 | ±1.012 (2.024 apart) | 0.28 x 0.68 |

- The KiCad pads sit exactly on the package pad centres, 0.075 mm longer than the package pad at each end and 0.10 mm wider (0.35 vs 0.25). Pad gap at 0.5 mm pitch: 0.15 mm. Pin 1 is at (-1.1625, -0.75) = top-left in KiCad coordinates, with a silkscreen chevron at the top-left corner, which matches the datasheet top view (Figure 21: pin 1 top of the left column, 14-13-12 along the top edge, 5-6-7 along the bottom, 11-10-9-8 down the right). Courtyard 3.5 x 3.0 mm.
- The EasyEDA land keeps the pad inner edges where the package pads are (0.922 / 0.672 mm from centre vs 0.925 / 0.675) and extends the pads 0.2 mm outward past the package pad, 0.1 mm beyond the body edge: a toe-fillet style. Pad width 0.28 mm leaves a 0.22 mm gap.
- Both are plausible; neither is ST's own recommended pattern, which the datasheet defers to www.st.com/mems (p.150) and which is not in hand. The KiCad footprint is the one in use; it is centred, so it does not pull the part during reflow, and the 0.35 mm width gives more paste than EasyEDA's 0.28 mm. **Minor concern:** with no toe extension the solder fillet is hidden under the body, which is normal for LGA but gives no visual inspection, and the 0.15 mm pad gap at 0.5 mm pitch is at the JLCPCB stencil limit; keep the stencil aperture at 1:1 or slightly reduced, do not enlarge. `[DSO-VERIFY]` the LSM6DS3TR-C mechanical drawing (same package family; the KiCad generator cites that drawing so a match is expected).
- Package height 0.86 mm max `[DSO-VERIFY]` (LSM6DS3TR-C believed 0.83 typ): irrelevant inside the casting.

## Layout guidance from datasheet

What the datasheet actually says (p.35): "Power supply decoupling capacitors (C1, C2 = 100 nF ceramic) should be placed as near as possible to the supply pin of the device (common design practice)." Nothing else about layout, ground planes, keep-outs or mechanical placement is in this document; the land pattern and soldering notes are referred to www.st.com/mems.

Applied to `place.py`: C130 is 1.4 mm from pin 8 and C132 2 mm from pin 5; fine. C131 is 2.6 mm further out; fine for bulk.

General MEMS placement practice (not from this datasheet, flagged as such):
- **Keep the IMU away from board edges, panel tabs and flex points.** `place.py` puts U30 at x = -12.2 on a 28 mm wide board, so its body is 0.3 mm from the left edge and its courtyard 0.05 mm from it. Depanelling (V-score or tab-route) and any bending during potting concentrate stress at the edge, and Section 4.6.2 says stress shifts the offsets. Moving it 1.5-2 mm inboard would help, if the left-edge real estate allows (the button and LED are above it).
- Keep it away from heat sources (the two motor FETs and the LDO) so the temperature-dependent offsets stay small; the casting equalises temperature slowly anyway.
- Solid ground under the part, no vias in the pads, and the SDA/SCL pair routed short to GPIO6/7 (they are on the left column of the RP2350, which is why the IMU is on the left edge).
- Record the axis orientation (Figure 3, p.6): with rotation 0 and pin 1 top-left, +X points toward the right column (pins 8-11), +Y toward the top edge (pins 12-14), +Z out of the top of the package. Put this in the firmware notes.

## Sourcing

LCSC C967633, LSM6DS3TR-C, $1.67 at qty 1, 13973 in stock on 2026-10-17. JLCPCB extended part (one loading fee; already counted in intent.md's extended-parts list). Not NRND as far as is known; the LSM6DSO/LSM6DSOX are the newer family members but cost $3.90 with 519 in stock, which is why the decision log chose the LSM6DS3TR-C.

## Findings

- **BLOCKER — no LSM6DS3TR-C datasheet.** Every electrical, register and mechanical number above is from the LSM6DSO and tagged `[DSO-VERIFY]`. The phase-1 gate ("every non-trivial part has an audit file with datasheet in `datasheets/`") cannot close for U30 until the user attaches `datasheets/lsm6ds3tr-c.pdf` and this file is re-verified: pin table, VDD/VDDIO ranges, abs max, I2C address, WHO_AM_I, current consumption, INT defaults, pin 2/3 handling, package drawing.
- **MAJOR — SDx and SCx (pins 2, 3) left floating.** Datasheet Mode 1 says "Connect to VDDIO or GND" and they have no internal pull. Change Block 7 to tie pins 2 and 3 to GND (`2: "GND", 3: "GND"` in circuit.py line 249) and update the schematic symbol side list so they are drawn to ground, not as no-connects.
- **MAJOR — IMU 0.3 mm from the board edge** (`place.py` line 195, U30 at x = -12.2 on a ±14 mm board). Offsets shift with package stress (p.16); the edge is where depanel and potting stress concentrate. Move inboard by 1.5-2 mm if the left-edge column allows. This is a placement-phase item but is raised now because the left-edge layout was chosen around the IMU.
- **MINOR — pull-ups 4.7 k vs the datasheet's 10 k example.** 4.7 k is better for 400 kHz and within the 4 mA sink spec; no change needed, record the choice.
- **MINOR — GPIO17 (IMU_INT1) must be an input, never driven high, before the IMU boots.** Satisfied by the RP2350 reset state; add to the firmware notes. Only matters if the LSM6DS3TR-C shares the LSM6DSO's I3C-detect behaviour, which it is believed not to.
- **MINOR — C131 10 µF rating.** Confirm the shared `c_10u` part is ≥ 6.3 V X5R/X7R (10 V preferred) so DC-bias derating leaves ≥ 5 µF at 3.3 V. Covered by the decoupling-group audit if one exists.
- **NOTE — post-casting offset calibration.** Add a firmware/test step: after potting, read the zero-g/zero-rate offsets at rest and store them (or write the user offset registers). Document it in intent.md's test plan since nothing can be reworked after casting.
- **NOTE — motor vibration will saturate the wake/tap detectors while a motor runs.** Firmware must gate motion detection; gyro LPF2 at 104 Hz ODR cuts off at 33 Hz `[DSO-VERIFY]`.
- **NOTE — firmware must use the LSM6DS3TR-C register map and WHO_AM_I value**, not the LSM6DSO's (0x6C). Writing LSM6DSO-only registers (I3C_BUS_AVB, OIS, FSM pages) on the LSM6DS3TR-C would hit reserved addresses, which the datasheet warns can permanently damage the device.
- **NOTE — stencil.** 0.5 mm pitch, 0.15 mm pad gap on the KiCad footprint: 1:1 aperture, do not oversize.
- **NOTE — axis orientation** recorded above (rotation 0, pin 1 top-left: +X right, +Y up the board, +Z out of the front).

## Open questions

1. **User: attach the LSM6DS3TR-C datasheet** (`design/datasheets/lsm6ds3tr-c.pdf`). Until then every `[DSO-VERIFY]` item is unconfirmed and the phase-1 gate stays open for U30.
2. Confirm in that datasheet: pins 2/3 Mode 1 text ("Connect to VDDIO or GND"), pins 10/11 NC, INT1/INT2 power-on states, VDD/VDDIO ranges and any sequencing note, I2C address with SA0 = 0, WHO_AM_I, current in combo and accel-low-power modes, and the package drawing (pad 0.25 x 0.475, 0.1 mm edge inset).
3. Is there room to move U30 1.5-2 mm inboard from the left edge?
4. Which `c_10u` part (voltage rating, dielectric, size) is C131?
5. Will the user accept GND (rather than VDDIO) for the SDx/SCx tie? GND is recommended; both are allowed.
