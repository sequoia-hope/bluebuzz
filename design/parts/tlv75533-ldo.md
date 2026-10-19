# U3 — TLV75533PDBVR 3.3 V 500 mA LDO (3V3_SYS, always on)

Datasheet: datasheets/tlv755p.pdf (SBVS320D, rev D, September 2024; package addendum 14-Oct-2026). Read: all sections, pp. 1–24 plus addendum and mechanical drawings.
MPN: TLV75533PDBVR   Supplier: JLC/LCSC C404027 (extended part; `bom/parts.yaml` says verified 2026-08-18 — stock and price NOT re-checked in this audit, see Open questions). Addendum p.4: Active, Production, SN finish, MSL 1, −40 to 125 °C, marking "1FWF".
Footprint: SOT-23-5 (DBV0005A, pitch 0.95 mm, 2.6 mm lead span, pads 0.6 × 1.1 mm, mech. drawing after p.24) → KiCad `Package_TO_SOT_SMD:SOT-23-5` matches the "DBV" suffix. The DBV variant has **no thermal pad** (p.3, Table 4-1); the DYD variant with a pad is a different footprint and MPN (TLV75533PDYDR).

Wiring (scripts/circuit.py Block 3): 1 IN = VSYS, 2 GND, 3 EN = VSYS, 4 NC (unconnected), 5 OUT = 3V3_SYS. C20 1 µF on IN, C21 1 µF + C22 10 µF on OUT. EN tied to IN is exactly the datasheet's "if shutdown capability is not required, connect EN to IN" (p.12, 6.3.2).

## Absolute max vs our worst case

| Parameter | Abs max (p.4) | Recommended (p.4) | Our worst case | Margin |
|---|---|---|---|---|
| VIN | −0.3 / 6.0 V | 1.45–5.5 V | VSYS 4.4 V (BQ24074 VSYS clamp); even raw VBUS 5.5 V | OK |
| VEN | −0.3 / 6.0 V | 0–5.5 V | = VIN, 4.4 V | OK |
| VOUT | VIN + 0.3 V (or 6.0) | 0.6–5.0 V | 3.3 V, nothing else drives 3V3_SYS (SWD pad row has no 3V3 pin; USB enters via the charger) | OK, see reverse-current note |
| IOUT | — | 0–500 mA | ~250 mA estimate (intent.md), ~150 mA realistic (RP2350 VREG_VIN ≤ 100 mA, flash ≤ 25 mA, RM2 VDDIO few mA, IMU 1 mA, CHG LED (3.3 − 2)/330 R ≈ 4 mA, sensors via U5 1.2 mA) | OK, 2× |
| TJ | 150 °C | −40 to 125 °C | ≈ 73–109 °C (see thermal) | OK |
| COUT | — | 1–200 µF | ~28 µF nominal across the whole 3V3_SYS net | OK |
| EN toggle | — | ≤ 10 kHz | DC | n/a |
| ESD HBM / CDM | ±1000 / ±500 V (p.4) | — | Not user-accessible (cast in rubber; USB has USBLC6-2) | OK |

## Required external parts (from datasheet)

- CIN ≥ 1 µF ceramic, X5R/X7R, effective ≥ 0.47 µF at the pin (p.3 footnote 1, p.15 7.1.1) → C20 1 µF 0603 X5R 50 V (CL10A105KB8NNNC). At 4.4 V bias a 50 V 0603 X5R loses < 10 %; effective ≈ 0.9 µF. Plus C11 10 µF and C14 100 nF already on VSYS. OK.
- COUT ≥ 1 µF ceramic X5R/X7R, ≥ 0.47 µF effective, ≤ 200 µF, "generally derate ceramics by 50 %" (p.15) → C21 1 µF (≈ 0.95 µF at 3.3 V) + C22 10 µF 0603 X5R 10 V (CL10A106KP8NNNC). **DC-bias derating of C22 at 3.3 V: a 10 V 0603 10 µF X5R is a high-density dielectric; Samsung's curve for this family gives roughly −25 % at 3.3 V (≈ 7.5 µF), −40 % at 4.4 V.** With −10 % tolerance and X5R −15 % at 85 °C: worst ≈ 5 µF. Effective COUT at the pin ≈ 6–8.5 µF, 13× the 0.47 µF minimum. OK. No ESR requirement beyond "ceramic X5R/X7R" (p.15); stable from 1 µF (Fig 5-3, PSRR shown for 1–100 µF).
- Nothing else required: no feedback divider (fixed output), no EN pull-up (tied to IN), pin 4 NC has no internal connection (p.3).

## Calculations

**Dropout at the load current.** VOUT = 3.3 V falls in the "3.3 V ≤ VOUT < 5.0 V" row of the VDO table (p.6; the features list confirms "238 mV max at 500 mA, 3.3 VOUT", p.1): 150 mV typ / 215 mV max at 500 mA (−40..85 °C) / 238 mV max at 125 °C. VDO is RDS(on)-like and scales linearly with IOUT (p.15, 7.1.2; Fig 5-13 shows ≈ 75 mV at 250 mA, 25 °C; ≈ 90 mV at 85 °C):

| IOUT | VDO typ | VDO max (85 °C) | VIN needed for regulation (VOUT +1 % = 3.333 V) |
|---|---|---|---|
| 150 mA | 45 mV | 65 mV | 3.40 V |
| 250 mA | 75 mV | 108 mV | 3.44 V |
| 500 mA | 150 mV | 215 mV | 3.55 V |

**At VSYS = 3.0 V (intent.md minimum) the LDO is NOT in regulation.** Below ≈ 3.4 V it enters dropout (Table 6-1, p.14) and the output tracks VIN minus the pass-FET drop: VOUT ≈ 3.0 − 0.075 = **2.92 V typ, ≈ 2.89 V worst at 250 mA**; ≈ 2.95 V at 150 mA. In dropout "line or load transients result in large output voltage deviations" (p.14, 6.4.2) and PSRR collapses (p.15); on exiting dropout the output overshoots briefly (p.16, Fig 7-2). The regulator does not shut down (UVLO is 1.44 V max, p.6); it simply becomes a ~0.3 Ω resistor. Consequences for the loads at 2.9 V are in Fine print.

Transient dropout is more likely than the DC case: a 2 A motor pulse through ~100–150 mΩ of cell + protection FET + BQ24074 path drops VSYS by 0.2–0.3 V, so with the cell at 3.6 V VSYS dips to ~3.3–3.4 V and the LDO skates in and out of dropout at the PWM rate. The 1 µF + 10 µF output caps and ~28 µF net total hold the rail during the 40–50 µs pulses; the 1.1 V core buck downstream is unaffected (VREG_VIN min 2.7 V).

**Current limit.** ICL = 560 mA min (p.5, "VOUT = 0.9 × VOUT, 1.5 < VOUT < 4.5 V") > 250 mA. Short-circuit limit ISC = 355 mA typ with foldback below 0.4 × VOUT (p.13, Fig 5-26). Start-up inrush: COUT at the pin ≈ 8 µF, tSTR = 550 µs typ (p.6) → I = C × dV/dt = 8 µF × 3.3 V / 0.55 ms ≈ 48 mA (whole-net 28 µF: ≈ 170 mA) plus load, inside the foldback limit of ≈ 300 mA at low VOUT (Fig 5-26). No constant-current load is on the rail at start-up (the RP2350 draws little until RUN releases via its 10k/100n). OK.

**Ground current.** IGND ≈ 550 µA at 250 mA, ≈ 450 µA at 150 mA (Fig 5-17, p.9); 25 µA typ / 33 µA max at no load over −40..85 °C (p.5) — the standby figure. Note Fig 5-19 (p.10): with VIN between ~1.5 and 3.3 V (dropout) IQ rises to ≈ 200–250 µA.

**Power dissipation and junction temperature** (Eq. 6/7, p.20): PD = (IGND + IOUT) × (VIN − VOUT) = (0.55 mA + 250 mA) × (4.4 − 3.3) = **0.276 W** worst (USB present, VSYS clamped at 4.4 V, 250 mA). Realistic: 150 mA → 0.166 W; on battery at 3.8 V, 150 mA → 0.075 W.

| RθJA (p.5) | Board it applies to | ΔT at 0.276 W | TJ at TA = 45 °C | TA(max) for TJ = 125 °C (Eq. 8) |
|---|---|---|---|---|
| 231.1 °C/W | JEDEC 2s2p, no vias to planes (worst published) | 64 °C | 109 °C | 61 °C |
| ~150 °C/W | Estimate for a small 6-layer board with GND on L2 and a few vias at pin 2 | 41 °C | 86 °C | 84 °C |
| 100.8 °C/W | TI LP087A EVM (dedicated copper) | 28 °C | 73 °C | 97 °C |

OK at every published figure, but note the 45 °C "ambient" is the body-contact figure: the board is cast in elastomer with no convection, and the elastomer's internal temperature is also lifted by the charger (BQ24074 ≈ 0.4 W while charging at 500 mA from 5 V — the same condition that puts 4.4 V on VSYS), the RM2 and the motors. Even so the margin in the pessimistic JEDEC row is 16 °C. Thermal shutdown is 165 °C (p.6) and "continuously running into thermal shutdown degrades reliability" (p.13). At the full 500 mA rating the part would dissipate 0.55 W and the JEDEC row gives TJ = 172 °C: **do not plan more 3V3_SYS load without the DYD (thermal-pad) variant.**

**PSRR against motor PWM.** VSYS carries 20–25 kHz PWM ripple from the two motor channels. PSRR ≈ 50 dB at 25 kHz, ≈ 46 dB at 100 kHz, ≈ 30–40 dB at 1–10 MHz (Figs 5-1/5-2, p.7, VIN = 4.3 V, 500 mA) — only valid out of dropout.

**Output accuracy.** ±1 % over −40..85 °C for DBV (p.5): 3.267–3.333 V, plus load regulation 0.060 V/A × 0.25 A = −15 mV (Fig 5-12). Inside IOVDD (1.8–3.63 V), flash (2.7–3.6 V), IMU (1.71–3.6 V) limits.

## Fine print / gotchas

- **Dropout below VSYS ≈ 3.4 V (p.6, p.14).** 3V3_SYS ≈ VSYS − 0.05..0.1 V from there down to the cell cutoff. The loads tolerate it (RP2350 IOVDD ≥ 1.8 V, VREG_VIN ≥ 2.7 V, W25Q32JV ≥ 2.7 V, LSM6DS3TR-C ≥ 1.71 V, DPS368 ≥ 1.7 V), **except** (a) the RM2's VDDIO minimum must be checked against ≈ 2.9 V (Open question 1), and (b) the battery ADC: ADC_AVDD (net 3V3A) is 3V3_SYS through R85 10 R, so the ADC's reference falls with the battery exactly where the gauge matters, compressing the reading of VBAT/2. Firmware should treat any reading implying VSYS < 3.4 V as "reference invalid, battery low" rather than compute a voltage.
- **Start-up into dropout (p.15, 7.1.3, Fig 7-1).** With a cell below 3.4 V the LDO starts in dropout and overshoots slightly as VIN ramps; the datasheet's cure is an EN signal, which we deliberately do not have. Harmless at these amplitudes (Fig 5-7 shows 20–30 mV excursions for a 1 V/µs line step).
- **EN driven above VIN draws current (p.13, Fig 5-23).** Not applicable: EN is tied to IN. Keep it that way (do not move EN to a GPIO on 3V3_SYS — that would be a bootstrap loop anyway).
- **Reverse current (p.17, 7.1.4):** abs max VOUT > VIN + 0.3 V. VSYS has ≈ 75 µF of bulk against ≈ 28 µF on 3V3_SYS, so VSYS cannot collapse faster than the output unless the cell's protection FET opens during a motor pulse; the stored energy (28 µF × 3.3 V) then flows through the body diode once — far below "excessive". No Schottky needed.
- **Active discharge (p.12, 6.3.2, Fig 5-25):** the 120 Ω pull-down only engages when EN < VLO, which never happens here (EN = IN). When VSYS falls below UVLO (1.3 V) the output is tied to ground through the 120 Ω (p.12, 6.3.1) — irrelevant.
- **Foldback current limit (p.13, 6.3.3):** a constant-current load at start-up can keep the output from rising; none present. "Excess inductance causes the current limit to oscillate" — keep VSYS → pin 1 short and wide, no ferrite.
- **Iq rises ~8× in dropout** (Fig 5-19): standby current with a deeply discharged cell is ≈ 200 µA, not 25 µA. Only matters at end-of-charge where the cell's own protection takes over anyway.
- **DBV has no thermal pad (p.3)**; its main heat path is the GND lead (RθJB 64.4 °C/W, p.5) and the leads into the copper. The mechanical drawing's land pattern is 2.6 mm span, pads 0.6 × 1.1 mm; "non-solder-mask-defined preferred".
- **Application section is not part of the TI spec** (p.15 note); the thermal numbers above are from section 5.4, which is.
- Addendum: SN (matte tin) lead finish for the PDBVR; MSL 1 unlimited.

## Layout guidance from datasheet (p.21, 7.4; Fig 7-7)

- Place CIN (C20) and COUT (C21 then C22) "as close as possible to the device": C20 between pin 1 and pin 2 on the pin-1 side, C21 at pin 5 with its GND returned to the same plane area as pin 2 (Fig 7-7 shows both caps' GND pads flowing into one GND pour under the package).
- "Use copper planes for device connections to optimise thermal performance" and "place thermal vias around the device to distribute the heat": give pin 2 a GND pour on F.Cu stitched with ≥ 4 vias to the L2 GND plane; widen the VSYS trace to pin 1 and the 3V3_SYS trace from pin 5 (they also conduct heat).
- EN (pin 3) is tied to VIN: Fig 7-7 does it with a via to the VIN pour; a short F.Cu trace from pad 3 round to pad 1 is equivalent.
- "Make sure the PCB area around the regulator is as free of other heat-generating devices as possible" (p.18): keep U3 away from the BQ24074, the two AO3400A motor FETs and the RM2.
- "Connect a low-impedance supply directly to IN; if the source is reactive add parallel input caps" (p.20, 7.3): the VSYS pour (inner layer) plus C11/C14/C20 satisfies this.

## Open questions

1. **RM2 VDDIO minimum** — if the module's VDDIO spec is 3.0 V or higher, the dropout region (VSYS 3.0–3.4 V) violates it and firmware must stop radio use (or the board must shut down) below ≈ 3.45 V. Check rm2-datasheet.pdf §2.6 and the CYW43439 VDDIO range.
2. **Battery low-voltage policy**: the cell's protection PCB trips around 2.5–3.0 V, well below the LDO's 3.4 V dropout knee. Firmware should define a software cutoff ≈ 3.5 V (sleep, motors off) so that the system never sits in dropout; the ADC-reference compression above means that threshold must be detected via the raw ratio, not a computed voltage.
3. **Real 3V3_SYS load**: the 250 mA estimate is conservative; confirm the RP2350 VREG_VIN draw at the chosen core clock (RP-006440) and the LED budget, since thermal margin at 4.4 V in depends on it.
4. **Elastomer internal temperature** when charging + playing: no data; a thermal test of the cast prototype (thermocouple at U3 and at the charger) before the second spin.
5. **Stock/price at LCSC C404027** not re-checked today (the fetcher is blocked for LCSC per decisions.md); confirm before ordering. Alternative if short: TLV75533PDYDR (thermal pad, 60.3 °C/W) — different footprint.

## Findings

- **MAJOR — Out of regulation below VSYS ≈ 3.4 V.** At the intent's 3.0 V minimum the rail is ≈ 2.9 V, with PSRR and transient response gone (p.6, p.14). Every load survives it except possibly the RM2 VDDIO (open question 1), and the battery ADC's reference (ADC_AVDD = 3V3_SYS) falls with it, so the gauge is wrong exactly at low battery. Fix in firmware: sleep/shut down at ≈ 3.5 V measured while the reference is still valid; or in hardware next spin: a buck-boost or a lower-dropout/lower-current split of the rails. Not a blocker for a prototype.
- **MINOR — Thermal margin depends on the 3V3 load estimate.** 0.28 W at 4.4 V in / 250 mA gives TJ = 73–109 °C at 45 °C ambient depending on the copper (p.5, p.20). OK, but the rubber body has no convection and the charger heats the same slab while VSYS is at 4.4 V. Pour and stitch GND at pin 2; keep U3 away from the BQ24074 and the motor FETs; measure on the cast prototype.
- **MINOR — C22 derating.** The 10 µF 10 V 0603 X5R is ≈ 7.5 µF at 3.3 V, ≈ 5 µF worst-case; still 10× the required 0.47 µF, so no change needed; record it so nobody later "saves" by dropping C21.
- **NOTE — EN tied to IN is correct** (p.12) and avoids the EN-above-VIN current; keep pin 4 unconnected (NC, p.3).
- **NOTE — Standby Iq** is 25 µA typ / 33 µA max at no load (p.5) but ≈ 200 µA in dropout (Fig 5-19); fine for the battery-life budget once the firmware cutoff above exists.
- **NOTE — Footprint** `SOT-23-5` matches DBV0005A (no thermal pad). If the DYD variant is ever substituted for thermal reasons, the footprint and MPN both change.
- **NOTE — Sourcing not re-verified** (LCSC C404027, extended part): check stock before the order.
