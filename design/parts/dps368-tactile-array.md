# U20–U23 — DPS368 barometric pressure sensors (tactile array) + C120–C123

Datasheet: datasheets/dps368.pdf (Infineon DPS368, v1.1, 2019-07-03, 44 pages). Read: all sections.
MPN: DPS368XTSA1 (package PG-VLGA-8-2, p.39)   Supplier: LCSC C3232508 (extended part, $4.21 at qty 1, 6613 in stock, checked 2026-10-17)
Footprint: `DPS368_LGA-8` from scripts/gen_footprints.py — 2.0 × 2.5 × 1.1 mm LGA-8, 0.65 mm pitch (p.39–41). **Pad size does not match the datasheet pattern — see "Land pattern" below.**
Decoupling: C120–C123, 100 nF 0402 X7R 16 V, Samsung CL05B104KO5NNNC, LCSC C1525 (basic part).

Where it sits: four sensors in a 2 × 2 grid (6 × 8 mm pitch) on the **back** of the board, left of centre (scripts/place.py), port facing away from the board into cast polyurethane (VytaFlex 20 or similar, 4–10 mm, vacuum degassed — intent.md). Powered from 3V3_SENS (TLV75533 → TPS22918 switch, SENS_EN = GPIO4). Bus: SPI1 (GPIO10 SCK, 11 SDI, 12 SDO), one chip select each on GPIO13–16.

Wiring as built (scripts/circuit.py, Block 6) vs datasheet Table 2 (p.6):

| Pin | Datasheet name | SPI 4-wire role (p.6) | Our net | OK |
|---|---|---|---|---|
| 1 | GND | ground | GND | yes |
| 2 | CSB | chip select, active low | TAC_CS1..4 | yes |
| 3 | SDI | serial data in (MOSI) | TAC_SDI | yes |
| 4 | SCK | clock | TAC_SCK | yes |
| 5 | SDO | serial data out (MISO), tri-state when CSB high (Fig. 13, p.21) | TAC_SDO (shared by all four) | yes |
| 6 | VDDIO | digital / IO supply | 3V3_SENS | yes |
| 7 | GND | ground | GND | yes |
| 8 | VDD | analog supply | 3V3_SENS | yes |

## Absolute max vs our worst case

Abs max from Table 4 (p.8); operating range from Table 3 (p.7); our worst case from intent.md.

| Parameter | Abs max | Operating range | Our worst case | Margin |
|---|---|---|---|---|
| VDD | 4 V | 1.7–3.6 V | 3.3 V + 1 % (TLV75533) minus switch drop ≈ 3.33 V | OK (0.67 V to abs max, 0.27 V to op max) |
| VDDIO | 4 V | 1.2–3.6 V | 3.33 V | OK |
| Voltage on any pin | 4 V | — | 3.3 V logic from the RP2350 (IOVDD = 3V3_SYS, same nominal as VDDIO) | OK while 3V3_SENS is on; see gotcha on driving pins while 3V3_SENS is off |
| Supply ramp to 90 % (t_vddup) | — | 0.001–5 ms | ≈ 0.95 ms (calc below) | OK |
| Pressure | 10 000 hPa | 300–1200 hPa (calibrated) | ambient 1013 hPa + squeeze load through the rubber; unknown, see open questions | OK vs abs max; may leave calibrated range under a hard squeeze |
| Ambient temperature | storage −40…125 °C | −40…85 °C operating | 0–45 °C, plus motor self-heating inside a sealed body | OK |
| ESD | ±2 kV HBM | — | inside the cast body, not user-accessible | OK |
| Reflow | 260 °C peak Pb-free, MSL1 (p.41–42) | — | JLC reflow, two-sided assembly (sensors on the back, so they are reflowed once, or twice if the back goes first) | OK |

The accuracy specs are tighter than the operating range: absolute accuracy ±100 Pa over 0–65 °C and relative ±6 Pa over 20–60 °C (Table 7, p.10). Our 0–45 °C is inside both.

## Required external parts (from datasheet)

- **Supply blocking capacitors C1 (VDDIO) and C2 (VDD): 100 nF minimum each, "placed as close to the package pins as possible"** (Table 11, p.20; Figs. 7–10 p.19–20). We have **one** 100 nF per sensor (C120–C123) on 3V3_SENS, not one per supply pin. VDD (pin 8) and VDDIO (pin 6) are adjacent pins on the same column with GND (pin 7) between them, and both are on the same rail, so one cap at pin 7 can serve both if it sits right at those pins. The datasheet still asks for two. See MINOR finding.
- **Pull-ups R1/R2 (≤ 10 kΩ): I2C only** (Table 11, p.20). Not needed in SPI; we have none. Correct.
- **R3 (address select on SDO, ≤ 100 kΩ): I2C only.** Not needed. Correct.
- **CSB and SDO in SPI 4-wire mode: no external resistor.** CSB and SDO have internal pull-ups to VDDIO, R_pull = 60–180 kΩ (Table 12, p.23; Table 2 p.6 "internal pull-up"; p.21 "0x77 if SDO pin is left floating or pulled-up"). SDO is tri-stated when CSB is high (Fig. 13, p.21), so four SDOs can share one MISO line without a pull-up. Correct as built.
- **Bulk capacitance on the rail:** none required by this datasheet; the rail has C52 10 µF at the switch output. The datasheet asks for VDD ripple below 50 mVpp (p.19); power-supply rejection is 0.063 Pa rms with 100 mVpp noise (Table 7, p.10). A dedicated LDO-fed rail with nothing else on it meets this comfortably.

## Calculations

- **Supply ramp-up (Table 3, p.7: 0.001 ms ≤ t_vddup ≤ 5 ms to 90 %).** The TPS22918 sets the slew with its CT cap: SR = 0.55 × CT + 30 µs/V (TPS22918 datasheet §8.3.3, Equation 3, 10–90 %). With CT = C50 = 470 pF: SR = 288.5 µs/V, t_rise = 3.3 V × 288.5 µs/V ≈ **0.95 ms**. Within 0.001–5 ms with a 5× margin. The load (10 µF + 4 × 100 nF) is small enough that the CT ramp, not the load, sets the slope. **Do not raise C50 above ~2.7 nF** (that would give 3.3 V × (0.55 × 2700 + 30) ≈ 5 ms).
- **Current at the intent.md rate (≥ 50 Hz per sensor).** Background-mode rates are powers of two: 1…128 Hz (PRS_CFG PM_RATE, p.30). The nearest options are 64 Hz and 128 Hz, with the constraint rate × measurement time < 1 s (Table 17 note, p.31): at 64 Hz the oversampling is limited to 8× (14.8 ms × 64 = 0.95 s; 16× is "n.a."), at 128 Hz to 2× (5.2 ms). Current ≈ rate × per-measurement current from the 1 Hz column (Table 17, p.31):
  - 64 Hz, OSR 8 (0.4 Pa rms, Table 16): ≈ 64 × 6.1 µA ≈ **0.39 mA** per sensor
  - 64 Hz, OSR 2 (1 Pa rms): ≈ 64 × 2.7 µA ≈ 0.17 mA
  - 128 Hz, OSR 2: ≈ 128 × 2.7 µA ≈ 0.35 mA
  - Peak during a pressure conversion: 345 µA (Table 5, p.8)
  Four sensors: ≤ 1.6 mA average, ≤ 1.4 mA if all four convert at once. The intent.md figure of 0.3 mA each is consistent. Negligible for the TPS22918 (2 A) and TLV75533 (500 mA). Standby (3V3_SENS on, no measurements) is 0.5 µA each; with 3V3_SENS switched off, zero.
- **SPI timing (Table 8 p.11, Table 14 p.25).** Max SCK 10 MHz; CSB setup and hold 15 ns min; SDI setup/hold 2 ns; SCK high-time duty ≥ 20 % at VDDIO 1.8–3.6 V. Mode: **SPI mode 3 only, CPOL = CPHA = 1** (p.13, p.20, p.21). One compensated sample is a 6-byte burst (PSR_B2…TMP_B0, auto-increment, p.26) plus 1 control byte = 56 clocks. At 64 Hz × 4 sensors that is ~14 kbit/s; at 1 MHz SCK the bus is ~1.5 % busy. Any RP2350 SPI clock from 1 to 10 MHz works; the 4-load shared SCK/SDI/SDO (a few cm of back-side trace plus four 5–10 pF inputs) is nothing at these speeds. No series termination needed.
- **Logic levels.** V_IH min 0.7 × VDDIO = 2.31 V, V_IL max 0.3 × VDDIO = 0.99 V (Table 12, p.23). RP2350 at IOVDD 3.3 V drives rail to rail. Sensor V_OH ≥ 0.8 × VDDIO = 2.64 V at 1 mA, well above the RP2350 input high threshold. Both rails are 3.3 V from the same LDO, so no level issue.
- **C120–C123, 100 nF 0402 X7R 16 V at 3.3 V.** DC-bias loss on a 16 V 0402 X7R at 3.3 V is under ~10 %, so ≥ 90 nF effective; the datasheet minimum is 100 nF nominal (Table 11 p.20 gives min 100, typ 100). Voltage rating 16 V vs 3.3 V: 4.8×, fine. Dielectric X7R, fine.

## Fine print / gotchas

Interface selection and power-up:
- **I2C is the default. The part switches to SPI when it sees CSB low, and after that I2C stays disabled until the next power-on reset** (p.13 §4.5, p.20 §6). "If CSB is connected to VDDIO, the I2C interface is active. If CSB is low, the SPI interface is active."
- **The first 2.5 ms after power-up there is no chip access and all SPI/I2C pads are inputs** (Fig. 4, p.12). SENSOR_RDY asserts within 12 ms, COEF_RDY within 40 ms (Table 8, p.11; MEAS_CFG p.33). Start-up timing is "measured from VDD > 1.2 V and VDDIO > 0.6 V or soft reset".
- **Until the first CSB-low on each sensor, that sensor is an I2C slave at 0x77 listening on SCK (as SCL) and SDI (as SDA).** SDO is then the I2C address LSB, and ours is tied to the shared MISO. While any sensor is still in I2C mode, SPI traffic to another sensor can look like I2C traffic to it; an ACK would drive the shared SDI line low against the RP2350 driving it. **Firmware must, right after enabling 3V3_SENS and waiting ≥ 12 ms, pull each of the four CS lines low once (e.g. read ID register 0x0D, expect 0x10, p.37) before any other traffic, and hold all CS lines high at all other times.** A CS pulse inside the first 2.5 ms may not be registered.
- The RP2350 is up before 3V3_SENS is enabled (GPIO4), so the CS, SCK and SDI pins are under firmware control before the sensors see power. That is the right structure; the ordering above is a firmware rule to write down.
- **Do not drive SCK/SDI/CS high while 3V3_SENS is off.** With VDDIO at 0 V, a 3.3 V input would forward-bias the pin-to-VDDIO protection path and back-feed the rail. Before de-asserting SENS_EN, set the five SPI1/CS GPIOs low or high-Z. (The sensors' internal 60–180 kΩ pull-ups on CSB/SDO then pull the CS and MISO lines toward 0 V; harmless.)
- Soft reset: write 0b1001 to RESET[3:0] (0x0C) "runs the same sequences as power-on reset" (p.37). It does **not** say it restores I2C mode; the datasheet only promises I2C comes back on a power-on reset. Treat it as SPI-sticky.
- The interrupt (SDO pin) is **not available in 4-wire SPI** (p.13 §4.6). We poll PRS_RDY (MEAS_CFG bit 4, p.33) or read at fixed timing in background mode. The FIFO (32 results, p.14) can hold ~0.5 s at 64 Hz.
- Oversampling above 8× requires P_SHIFT / T_SHIFT = 1 in CFG_REG (p.34, footnote on p.30), and the scale factors kP/kT change with OSR (Table 9, p.16). Firmware.
- Use the same temperature source for compensation as the one the coefficients were made with (TMP_COEF_SRCE, p.39; TMP_EXT, p.32) "highly recommended".

Operating range and the tactile use:
- Calibrated range is 300–1200 hPa, i.e. up to only ~0.19 bar above ambient (p.7). Abs max is 10 000 hPa (p.8). A hard squeeze through 4–10 mm of soft rubber over a 2 mm stiff lid reaches the port as some fraction of the contact stress; it is not obvious the reading stays inside 1200 hPa. Outside 1200 hPa the compensation polynomial (p.15) is unverified but the part is not harmed below 10 bar.
- Pressure temperature coefficient 0.5 Pa/K (p.10) and relative accuracy ±6 Pa: the body warms from the motors and the hand. For a tactile baseline that drifts with temperature the firmware must track a slow baseline (the datasheet itself suggests IIR filtering at the application level, p.20 §5.3).
- "Solder drift" 0.8 hPa typical, "minimum solder height 50 µm", removable by one-point calibration (AN487) (p.7, footnote 1). Casting the lid in rubber will add a static offset of the same character; a per-sensor zero after casting is needed anyway.
- Long-term stability ±1 hPa (p.7).

Gel, encapsulation and the port (what the datasheet actually says):
- **The datasheet contains no statement about gel, potting, encapsulation, or filling the port**, in either direction. Its only claims about the environment are the headline ones: "robust against water, dust and humidity", "IPx8 certified: temporary immersion of 50 m for 1 hour" (p.1), and "can be used in harsh environment". Casting the port full of polyurethane is outside anything Infineon documents. The evidence for it is the Tenzer/Jentoft/Howe paper, which used a different sensor (MPL115A2, larger port). Whether 1000 cP polyurethane wicks into a **0.4 mm** lid hole (Fig. 17, p.40) is not established by any document in this repo. See open questions.
- Package-handling rules (p.43), several of which bear directly on the casting plan:
  - "Do not pick the sensor with vacuum tools which make contact with the sensor vent port hole."
  - **"The sensor's vent hole should not be exposed to vacuum, this can destroy or damage the MEMS."** intent.md plans vacuum degassing of the poured rubber over the sensors so that the rubber fills the port. The datasheet statement is in the pick-and-place context but is worded without qualification. See MAJOR finding.
  - "Do not blow air into the sensor vent hole."
  - "Air blow and ultrasonic cleaning procedures shall not be applied … A non-clean paste is recommended … The MEMS sensor can be severely damaged by cleaning substances." Relevant to JLC's process (they use no-clean paste; confirm there is no wash step on the two-sided assembly) and to any flux cleaning the user does on the hand-soldered RM2 and leads: **no IPA bath, no ultrasonic** after the sensors are on.
  - "To prevent the blocking or partial blocking of vent hole during PCB assembly, it is recommended to cover the sound port with protective tape during PCB sawing or system assembly." The board is panelised and depanelled at JLC; dust from routing/V-scoring can enter the port. There is no way to ask JLC to tape four 0.4 mm holes; accept the risk or inspect the ports before casting.
  - "It is recommended to perform the PCB assembly in a clean room environment" — not achievable; noted.
  - "Do not use excessive force to place the sensor." Not under our control.
- MSL1, reflow per Table 19 (p.42): Pb-free peak 260 °C +0/−5, 20–40 s within 5 °C of peak, soak 150–200 °C 60–120 s, ramp-down ≤ 6 °C/s, ≤ 8 min 25 °C to peak. Standard JLC Pb-free profile.

Land pattern and package:
- Package pads are 0.35 ± 0.05 mm square, 8×, on 0.65 mm pitch, rows 1.45 mm apart (Fig. 17, p.40). Height 1.1 mm max. The 0.4 mm vent hole is in the lid at the pin 4 / pin 5 end of the package, off the centreline (Fig. 1 p.6, Fig. 17 p.40).
- Recommended board pads (Fig. 18, p.41): **0.35 × 0.35 mm copper, solder-mask-defined**, at 0.65 mm pitch, columns 0.725 mm either side of centre (1.45 mm apart). **Stencil: 0.35 mm diameter round apertures**, one per pad. "The specific design rules of the board manufacturer should be considered" (p.40).

## Recommended land pattern vs our footprint

| | Datasheet (Fig. 18, p.41) | Ours (`dps368()` in gen_footprints.py) | Match |
|---|---|---|---|
| Pitch along the column | 0.65 mm | 0.65 mm | yes |
| Column-to-column (centre) | 1.45 mm (±0.725) | 1.45 mm (±0.725) | yes |
| Pad size | 0.35 × 0.35 mm, SMD | **0.6 × 0.4 mm** (0.6 across the columns), NSMD, roundrect | **no** |
| Paste aperture | ⌀ 0.35 round (0.096 mm²) | 1:1 with the pad (0.24 mm²) | **no, 2.5× the paste** |
| Pin numbering | 1 GND top-right, 1–4 down one side, 5–8 up the other, clockwise from the top (Fig. 1 p.6; Fig. 17 bottom view p.40) | pin 1 top-right, 1–4 down the right, 5–8 up the left | yes |
| Body | 2.0 × 2.5 mm | 2.0 × 2.5 mm F.Fab rect | yes |
| Vent hole marker | pin 4/5 end, off-centre | drawn at the pin 1/8 end, centred (F.Fab only) | no (cosmetic) |
| Silk | — | two lines at y = ±1.35, 0.12 wide, i.e. 1.29–1.41 from centre; body edge at 1.25 ± 0.05 | marginal, see MINOR |

Our footprint copies the EasyEDA/LCSC land pattern for C3232508, which is bigger than Infineon's. The pitch and column spacing are right, so the part will sit on it, but with JLC's default 1:1 stencil each joint gets about 2.5× the paste Infineon specifies, on pads whose gaps along the column are 0.25 mm. On a 50 µm-stand-off LGA that is bridging and tilt risk, and the board cannot be reworked after casting. Fix: copper 0.35 × 0.35 mm SMD exactly as Fig. 18, or (friendlier to JLC's NSMD defaults) copper 0.4 × 0.4 mm NSMD with the paste layer reduced to 0.35 × 0.35 mm (pad solder-paste margin −0.025 mm). Either way the paste aperture should be ~0.35 mm.

## Layout guidance from datasheet

The datasheet's explicit layout statements are only these:
- Blocking capacitors "as close to the package pins as possible" (Table 11, p.20). Our C120–C123 are placed 3.0 mm from each sensor centre on the back (place.py: C120 at (−6.5, −0.5) vs U20 at (−9.5, −0.5)); VDD/VDDIO are the left-column pins 6 and 8, at x ≈ −0.725 from the sensor centre. KiCad's flip mirrors x, so on the board the pin 5–8 column is on the +x side of each sensor, which is the side the caps are on: the side is right, the distance (≈ 2.3 mm from the cap's near pad to pin 8) is more than "as close as possible". Pull each cap in to within ~1 mm of pins 6–8 with a short ground return to pin 7, and add it to the FACING list so the 3V3_SENS pad faces the sensor.
- SMD pads and a 0.35 mm round stencil aperture (Fig. 18, p.41).
- Nothing covering, blowing into, or sucking on the vent hole during assembly (p.43).

Derived from the above and the mechanical facts:
- No silkscreen, vias, or copper features under or within the body outline (2.0 × 2.5 mm ± 0.1): a 50 µm stand-off package tilts on a silk line. Our silk lines at ±1.35 are within the body tolerance; move them to ≥ ±1.5 or drop them (designators are on the fab layer per intent.md).
- Keep the back-side area over each port free of anything the rubber must flow around; the 6 × 8 mm pitch leaves plenty of room.
- Both GND pins (1 and 7) to the ground plane with their own via each; they are on opposite columns.
- Keep the shared SCK/SDI/SDO away from the motor PWM traces (20–25 kHz, 1 A on the front); a plane between them on a 6-layer board does that.
- Route 3V3_SENS as a short back-side trace or a small island fed by one or two vias from C52; four sensors at ≤ 1.6 mA need no width.

## Open questions

1. **Vacuum degassing over the sensors vs. "the sensor's vent hole should not be exposed to vacuum" (p.43).** Options: degas the mixed rubber in the cup first and pour without pulling vacuum on the board; or pour, then cure in a pressure pot (≈ 4 bar absolute is below the 10 000 hPa abs max and pushes rubber into the port rather than pulling on the membrane); or accept the datasheet's wording as a pick-and-place nozzle rule and degas anyway at a modest vacuum, after a test on one loose sensor. The user should decide, and a one-sensor casting test before the board is cast is the cheap way to find out.
2. Does VytaFlex 20 actually enter a 0.4 mm hole over the MEMS cavity, and does the sensor still respond with the port full of cured rubber? Nothing in the repo answers this for the DPS368 specifically (the paper used MPL115A2). Test with one sensor on a breakout before committing four to a cast board.
3. Does a firm squeeze take the port above 1200 hPa (the top of the calibrated range)? Measure on the prototype; if so, the firmware may need to accept uncalibrated readings above that.
4. Does JLC wash two-sided assemblies after the second reflow? The sensors must see no cleaning fluid, no ultrasonic, no air blow (p.43). If unknown, ask in the order notes that the boards be left unwashed.
5. Firmware: confirm the RP2350 GPIO13–16 default state at reset (pull-down) is acceptable, i.e. that the CS lines are already driven high by firmware before SENS_EN is raised, and that the SPI1 pins are parked low before SENS_EN is dropped.
6. One cap per sensor vs. the datasheet's two: accept (same rail, adjacent pins, cap placed at pin 7) or add four more C1525 (basic part, 0402, trivial cost)?

## Findings

**BLOCKER**
- Land-pattern pad size: our pads are 0.6 × 0.4 mm NSMD with a 1:1 paste layer; the datasheet calls for 0.35 × 0.35 mm SMD pads and 0.35 mm round stencil apertures (Fig. 18, p.41). Pitch (0.65) and row spacing (1.45) match, pin order matches, so this is a pad-size / paste-volume problem, not a wiring one. ~2.5× the specified paste on a 0.65 mm-pitch LGA with 0.25 mm gaps is a bridging/tilt risk on a board that cannot be reworked after casting. Fix in `dps368()`: 0.35 × 0.35 SMD, or 0.4 × 0.4 NSMD with the paste aperture reduced to 0.35.

**MAJOR**
- Casting process conflict: intent.md plans vacuum degassing of the poured rubber over the sensors; the datasheet says the vent hole "should not be exposed to vacuum, this can destroy or damage the MEMS" and must not have air blown into it (p.43). Decide the casting method (pre-degassed pour, pressure pot, or a tested modest vacuum) before boards are cast; test on one sensor first.
- The datasheet makes no statement supporting operation with the port filled with elastomer; the whole sensing concept rests on the Tenzer paper's different sensor. Prototype test required before relying on it (open question 2).
- Firmware power-up protocol is load-bearing for correct bus behaviour: all four CS high before SENS_EN rises; wait ≥ 12 ms; pulse each CS low once (ID read) to lock every sensor into SPI before any other traffic (p.12, p.13, p.20). Until that is done, un-selected sensors are I2C slaves on the shared SCK/SDI lines. Record this in the firmware notes.

**MINOR**
- One 100 nF per sensor serves both VDD and VDDIO; the datasheet shows one 100 nF per supply pin, "as close to the package pins as possible" (Table 11, p.20). Acceptable on a dedicated 3.3 V rail if the cap sits at pins 6–8. The caps are on the correct (VDD/VDDIO) side after the back-side mirror but 3.0 mm from the sensor centre, ≈ 2.3 mm from pin 8. Either add a cap per pin or pull each cap in to within ~1 mm of pins 6–8.
- Silkscreen outline lines at ±1.35 mm sit within the body's ±0.1 mm tolerance of its 1.25 mm half-length; a silk line under a 50 µm-stand-off LGA tilts it. Move to ≥ ±1.5 mm or remove.
- The F.Fab vent-hole marker is at the wrong end of the package (pin 1/8 end; the datasheet puts it at the pin 4/5 end, off-centre, Fig. 1 p.6 / Fig. 17 p.40). Cosmetic, but the drawing is what someone will use to check the rubber fill and to tape ports.
- No cleaning after the sensors are on the board: no IPA bath, no ultrasonic, no compressed air (p.43). Applies to the hand-soldering of the RM2 and the battery/motor leads, and to JLC's process (ask for no wash).
- Depanelling dust can block the 0.4 mm port (p.43 recommends taping it during sawing); inspect the four ports under magnification before casting.

**NOTE**
- Supply ramp: 0.95 ms with the 470 pF CT cap on the TPS22918, inside the 0.001–5 ms window (p.7). Do not increase C50 beyond ~2.7 nF.
- Current: ≈ 0.17–0.39 mA per sensor at 64 Hz depending on oversampling, 345 µA peak; ≤ 1.6 mA for the array. Matches intent.md.
- SPI: mode 3 only (CPOL = CPHA = 1), ≤ 10 MHz, CS setup/hold 15 ns. No pull-ups or series resistors needed in 4-wire mode; SDO tri-states when deselected.
- Background-mode rates are 1/2/4/…/128 Hz; "≥ 50 Hz" means 64 Hz (OSR ≤ 8, 0.4 Pa rms) or 128 Hz (OSR ≤ 2, 1 Pa rms). No interrupt in 4-wire SPI; poll or use the FIFO.
- Calibrated range tops out at 1200 hPa (~0.19 bar over ambient); abs max 10 000 hPa. Expect a static offset after casting (same character as the documented 0.8 hPa solder drift) and 0.5 Pa/K temperature drift; zero each sensor after casting and track a slow baseline.
- Extended part at JLC (one loading fee for all four); 6613 in stock on 2026-10-17. The cap C1525 is a basic part.
