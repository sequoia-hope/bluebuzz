# U5 — TPS22918DBVR load switch (3V3_SYS → 3V3_SENS, the DPS368 array rail)

Datasheet: datasheets/tps22918.pdf (SLVSD76C, rev C, July 2017; package addendum 15-Jul-2026). Read: all sections, pp. 1–22 plus addendum and mechanical drawings.
MPN: TPS22918DBVR   Supplier: JLC/LCSC C131941 (extended part; `bom/parts.yaml` says verified 2026-08-18 — stock and price NOT re-checked in this audit). Addendum p.1: Active, Production, NIPDAU | SN finish, **MSL 2 (1 year floor life)**, −40 to 105 °C, marking "13MW".
Footprint: SOT-23-6 (DBV0006A, pitch 0.95 mm, 2.6 mm lead span, pads 0.6 × 1.1 mm, mech. drawing after p.22) → KiCad `Package_TO_SOT_SMD:SOT-23-6` matches the "DBV" suffix.

Wiring (scripts/circuit.py Block 5): 1 VIN = 3V3_SYS, 2 GND, 3 ON = SENS_EN (RP2350 GPIO4, R50 100 k to GND), 4 CT = C50 470 pF to GND, 5 QOD and 6 VOUT both = 3V3_SENS (QOD "tied directly to VOUT", p.3 / p.13 option 2). C51 1 µF on VIN, C52 10 µF on VOUT. Load: four DPS368 (U20–U23 per the TACTILE table) at 0.3 mA each with one 100 nF each.

## Absolute max vs our worst case

| Parameter | Abs max (p.4) | Recommended (p.4) | Our worst case | Margin |
|---|---|---|---|---|
| VIN | −0.3 / 6 V | 0–5.5 V | 3.333 V (LDO +1 %) | OK |
| VOUT | −0.3 / 6 V | ≤ VIN | ≤ VIN by construction | OK |
| VON | −0.3 / 6 V | 0–5.5 V; VIH ≥ 1 V, VIL ≤ 0.5 V | GPIO4 at IOVDD = 3V3_SYS (0 / 3.3 V) | OK |
| IMAX continuous (TA = 70 °C) | 2 A | — | 1.2 mA steady; ≈ 30 mA inrush | OK, > 60× |
| IPLS (< 300 µs, 2 % duty) | 2.5 A | — | ≈ 30 mA inrush | OK |
| TJ | 125 °C | TA −40 to 105 °C | ≈ TA (PD ≈ 0.1 µW) | OK |
| CIN | — | ≥ 1 µF (footnote 2) | C51 1 µF + the 3V3_SYS bulk (C22 10 µF, C131 10 µF) | OK |
| QOD-shorted load capacitance | ≤ 200 µF (p.14, 8.3.2.2) | — | 10.4 µF nominal | OK |
| ESD HBM / CDM | ±2 kV / ±1 kV (p.4) | — | internal node | OK |

## Required external parts (from datasheet)

- CIN 1 µF ceramic X5R/X7R "placed close to the pins" (p.17 9.2.2.1, p.20 §10/§11.1) → C51 1 µF 0603 X5R 50 V (CL10A105KB8NNNC), ≈ 1 µF at 3.3 V. OK.
- CL on VOUT "optional" (p.17 9.2.2.2) → C52 10 µF 0603 X5R 10 V (CL10A106KP8NNNC): ≈ 7.5 µF at 3.3 V DC bias (Samsung family curve, ≈ −25 %), ≈ 5 µF worst with tolerance and X5R temperature. Plus 4 × 100 nF at the sensors. Datasheet recommends CIN ≥ CL, ideally 10:1, because of the body diode and VIN dip (p.17); ours is the inverse locally (1 : 10.4). See Calculations and Findings — harmless here, but an easy improvement.
- CT capacitor on pin 4: Table 3 (p.15) recommends ≥ 16 V rating for VIN 1.2–4 V; "effective capacitance reduces as the voltage approaches the rated voltage, dielectric dependent" (p.14) → C50 470 pF 0402 **C0G 50 V** (0402CG471J500NT): no DC-bias loss, ±5 %. Better than the X7R 25 V 10 % used for the datasheet's Table 2. OK.
- ON pull-down (not in the datasheet, ours): R50 100 k keeps ON low while the RP2350 is in reset or its GPIOs are high-Z. ION leakage 0.1 µA max (p.5) → 10 mV across 100 k, far under VIL 0.5 V. OK. ON "cannot be left floating" (p.13, 8.3.1) — satisfied.
- No external QOD resistor: pin 5 tied to pin 6 → discharge through the internal RPD (p.13 option 1 — the datasheet's wording calls direct-to-VOUT the "shorted" case; p.3 lists it as method 2).

## Calculations

**Rise time from CT = 470 pF** (Eq. 3, p.14, revised in rev B): SR = 0.55 µs/(V·pF) × CT + 30 µs/V = 0.55 × 470 + 30 = **288.5 µs/V**. tR (10–90 %) = SR × VIN = 288.5 × 3.3 = **952 µs**. Table 2 (p.14, measured at 25 °C, X7R 25 V 10 % cap at CT, CL = 0.1 µF, RL = 10 Ω) gives **850 µs** for 470 pF at 3.3 V; the formula over-reads the table by ≈ 12 % at every row (1000 pF: 1914 vs 1680), so with our C0G cap at its full 470 pF expect ≈ 0.85–0.95 ms. Fig 8 (p.9) shows ≈ ±5 % over −40..105 °C. Turn-on delay tD ≈ 590 µs at 3.3 V (p.6), so VOUT reaches 90 % about **1.5 ms** after SENS_EN rises; the firmware's "rail up" wait before the DPS368's own start-up time should be ≥ 2 ms.

**Inrush into C52 + the sensors' caps** (Eq. 9, p.19): IINRUSH = CL × dVOUT/dt with dV = 80 % of VIN = 2.64 V over tR.

| CL assumption | tR | IINRUSH |
|---|---|---|
| 10.4 µF nominal (10 µF + 4 × 100 nF) | 0.85 ms | 32 mA |
| ≈ 9 µF (C52 averaged over the ramp, where bias is below 3.3 V) | 0.90 ms | 26 mA |
| CT absent (Table 2, 95 µs at 3.3 V) — for reference | 95 µs | 290 mA |

Plus the sensors' 1.2 mA. The 30 mA step is seen by the LDO U3 (ICL ≥ 560 mA) and dropped across C51 + the 3V3_SYS bulk; ΔV on 3V3_SYS ≈ I × ESR is negligible. OK against IMAX 2 A and IPLS 2.5 A, and the CT cap is what makes it so (without CT the inrush would be ≈ 0.3 A, still legal but a visible dip on the LDO).

**On-resistance drop** (Eq. 8, p.19): RON at VIN = 3.3 V, 200 mA: 53 mΩ typ, 71 mΩ max to 85 °C, 80 mΩ max to 105 °C (p.5). ΔV = 1.2 mA × 80 mΩ = **0.1 mV**. 3V3_SENS = 3V3_SYS to all intents.

**Power dissipation / thermal** (Eq. 14, p.21): PD = I² × RON = (1.2 mA)² × 80 mΩ ≈ 0.12 µW; during QOD discharge a one-off 3.3² / 25 Ω = 0.44 W peak for ≈ 0.3 ms (54 µJ in C52). RθJA 183.2 °C/W (p.4) → TJ = TA. Nothing to do.

**Quiescent current** (p.5): ON, VIN = 3.3 V: IQ = 8.3 µA typ / 15 µA max. OFF (VON = 0, VOUT = 0): ISD = 0.5 µA typ / 3.5 µA max at 3.3 V. **The R50 pull-down adds 3.3 V / 100 k = 33 µA whenever SENS_EN is high** — four times the switch's own IQ while the array is on, zero in sleep. Plus the sensors' 1.2 mA when on. Sleep cost of this block therefore ≤ 3.5 µA (plus DPS368 leakage, which the switch removes entirely because the rail is pulled to ground).

**Quick-output-discharge behaviour** (p.13, Eq. 2 and Table 1; p.15 Table 4): with ON low and QOD tied to VOUT, VOUT is connected to GND through RPD = 25 Ω typ / 35 Ω max at 3.3 V (p.5; Fig 7, p.8 — rises steeply only below VIN ≈ 1.8 V). τ = RPD × CL = 25 Ω × 10.4 µF = 0.26 ms; 90 → 10 % = τ × ln 9 ≈ **0.57 ms by Eq. 2**, while Table 1's measured value for 10 µF at 3.3 V is **230 µs** (260 µs at 85 °C); with our derated ≈ 7.5 µF expect ≈ 0.2–0.4 ms. Peak discharge current 3.3 V / 25 Ω = 132 mA, decaying — inside the "≤ 200 µF with internal RPD" rule (p.14, 8.3.2.2). The rail is at ground within a millisecond of SENS_EN falling, so the sensors fully reset and cannot hold state or draw leakage in sleep; on the next enable they go through their full power-on (and the DPS368 reads CSB at power-up to pick SPI vs I2C — see Fine print).

**Switching the ON pin from GPIO4:** VIH 1 V min over the full range (p.4), hysteresis 107 mV typ (p.5, Fig 6: ≈ 100–120 mV at 3.3 V). A 3.3 V CMOS output has > 2 V of margin; the RP2350's ≈ 12 mA drive into 100 k + 0.1 µA is trivially fine. Rise/fall of the control edge does not matter (the slew is set by CT, not by ON; p.20 §10 — "if ON is applied before VIN the slew rate is not controlled", impossible here since the GPIO is powered from VIN).

## Fine print / gotchas

- **"The remaining charge from CL must decay naturally through the internal QOD resistance and should not be driven" (p.14, 8.3.2.2) — and our SPI lines can drive it.** When SENS_EN is low the RP2350 still owns TAC_SCK, TAC_SDI and TAC_CS1–4. If any of them is left high, it back-powers the unpowered DPS368s through their I/O protection diodes into the 3V3_SENS net, which the switch is holding at ≈ 25 Ω to ground: roughly (3.3 − 0.7 V) / (GPIO ≈ 40 Ω + 25 Ω) ≈ 40 mA per high line, flowing through a sensor's ESD diode (far above a MEMS sensor's typical ±10 mA I/O limit) and sinking continuously in the QOD FET. Firmware must drive all six lines low (or high-Z with pull-down) *before* dropping SENS_EN and keep them so until the rail is back up. No hardware change is required; 1 k series resistors in SCK/SDI/CS would cap the fault at ≈ 2.6 mA each at the cost of SPI edge rate. See the DPS368 audit for that part's I/O ratings.
- **TAC_SDO (MISO) floats while the rail is off**: enable the RP2350 input pull-down on that pin in sleep to avoid an oscillating input.
- **MSL 2** (addendum): 1 year floor life after the bag opens; a non-issue for JLC assembly from reel but worth knowing for leftover stock.
- **IMAX is specified at TA = 70 °C** (p.4) — irrelevant at 1.2 mA.
- **Switching characteristics are only valid when VIN is in steady state before ON rises** (p.6 header). Ours is: VIN is the always-on 3V3_SYS.
- **CIN : CL ratio.** "A CIN greater than CL is highly recommended... CL greater than CIN can cause VOUT to exceed VIN when the system supply is removed" → body-diode current VOUT → VIN (p.17 9.2.2.2). Locally the ratio is 1 µF : 10.4 µF, but the VIN node is the LDO output with ≈ 28 µF on it, and the only way 3V3_SYS collapses while 3V3_SENS is up is total system power loss, when 10 µF discharging through the body diode into 3V3_SYS is harmless (54 µJ). Not a fault; see Findings for the cheaper option.
- **The 200 µF QOD limit (p.14)** applies only to the direct QOD-to-VOUT tie we use; 10.4 µF is far below it.
- **Table 2 and Eq. 3 are "approximate" and measured with RL = 10 Ω, CL = 0.1 µF**; our load is ≈ 2.7 kΩ and 10 µF, so the real 10–90 % time is dominated by the CT ramp and will be close to the table's 850 µs (the gate ramp sets dV/dt; CL only adds the 30 mA inrush).
- **The Application section (§9) is not part of the TI specification** (p.16 note) — the rise-time formula lives in §8.3.3 which is.
- **Pin 5 QOD and pin 6 VOUT are adjacent** on the same side of the package; the tie is a 0.95 mm pad-to-pad short. Do not let the generator route pin 5 to the net anywhere other than straight to pin 6.
- **Body diode** VOUT → VIN (block diagram p.12): 3V3_SENS can never sit more than a diode above 3V3_SYS, and anything that drives 3V3_SENS while 3V3_SYS is down back-feeds the whole 3V3_SYS rail. Nothing on 3V3_SENS can source (only the back-drive fault above).

## Layout guidance from datasheet (p.20 §11.1, p.21 Fig 32 and §11.3)

- "VIN and VOUT traces as short and wide as possible" — at 1.2 mA this is about inductance, not current; a 0.3 mm trace is plenty.
- C51: "low-ESR ceramic bypass on VIN, placed as close to the device pins as possible" — between pin 1 and the GND pour at pin 2, GND through a via to the plane (Fig 32 shows the via right at the cap's GND pad).
- C50 on CT: Fig 32 puts it directly at pin 4 with its own GND via; keep CT's trace short and away from switching nodes — it is a high-impedance 470 pF timing node, and a few pF of stray only lengthens the ramp (harmless).
- QOD (pin 5) to VOUT (pin 6): short link along the package edge.
- ON (pin 3): plain logic trace from GPIO4; R50 at either end.
- C52 "input and output capacitors placed close to the device" (p.21 §11.3) — at pin 6; the sensors' 100 nF stay beside each DPS368 on the back, fed through the 3V3_SENS via(s).

## Open questions

1. **Firmware contract for the SPI lines while the rail is off** (drive low / pull-down, and the rail-up wait ≥ 2 ms before the DPS368 start-up time) — needs to be written into the firmware notes alongside the DPS368 audit's CSB-at-power-up requirement.
2. **Is 10 µF on 3V3_SENS needed?** Four DPS368 at 0.3 mA with 100 nF each do not need bulk. 1 µF (same part as C51) would make CIN = CL, cut inrush to ≈ 3 mA and QOD time to ≈ 25 µs, and free a 0603. Keep 10 µF only if the sensor audit shows conversion-current spikes that need it.
3. **R50 value**: 100 k costs 33 µA while the array is on. 1 M would still hold ON < 0.1 V against the 0.1 µA max leakage. Only worth changing if the play-time budget is tight; sleep is unaffected.
4. **Stock/price at LCSC C131941** not re-checked today; confirm before ordering.

## Findings

- **MAJOR — Back-drive of the unpowered sensors through SPI while QOD holds the rail at 25 Ω** (p.14 "should not be driven"). Any TAC_SCK/SDI/CS line left high while SENS_EN is low pushes tens of mA through a DPS368 protection diode into the QOD pull-down. Firmware-only fix: drive those GPIOs low (or pull-down) before disabling the rail and until it is back up; optionally 1 k series resistors next spin. No change to U5's circuit.
- **MINOR — C52 10 µF is larger than needed and inverts the recommended CIN ≥ CL ratio** (p.17). Consequences here are benign (≈ 30 mA inrush, 54 µJ through the body diode on power loss), so it is acceptable as drawn; 1 µF would be the cleaner choice unless the DPS368 audit wants the bulk.
- **MINOR — R50 100 k burns 33 µA while the array is on**, 4× the switch's own IQ (p.5). Irrelevant in sleep (the only state where µA matter here). Optional change to 1 M.
- **NOTE — Rise time ≈ 0.85–0.95 ms (Eq. 3 / Table 2, p.14), delay ≈ 0.6 ms (p.6)**: allow ≥ 2 ms after SENS_EN before starting the DPS368 power-on wait. Inrush ≈ 30 mA, well inside IMAX 2 A and the LDO's 560 mA limit.
- **NOTE — QOD drains the rail in ≈ 0.2–0.6 ms (Table 1 / Eq. 2, p.13)**, giving the sensors a true power cycle every sleep; the sensors' CSB lines must be in the state that selects SPI when the rail returns.
- **NOTE — All abs-max and recommended conditions met with ≥ 60× margin on current**; thermal dissipation is ≈ 0.1 µW. CT cap C0G 50 V exceeds the recommended 16 V (Table 3, p.15). Footprint `SOT-23-6` matches DBV0006A.
- **NOTE — MSL 2 and sourcing** (LCSC C131941, extended): not re-verified; check stock before the order.
