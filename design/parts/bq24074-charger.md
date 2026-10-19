# U2 — BQ24074 1-cell linear charger with power path

Datasheet: `design/datasheets/bq24074.pdf` (SLUS810N, rev N, October 2021; package addendum dated 2026-09-18). Read: all 55 pages.
MPN: BQ24074RGTR   Supplier: LCSC C54313 (`bom/parts.yaml` `charger:`; number inherited from bike-tracker, marked `verified: yes` — **stock count and price not confirmed in this audit**, see Open questions). Extended part at JLC.
Footprint: `Package_DFN_QFN:VQFN-16-1EP_3x3mm_P0.5mm_EP1.6x1.6mm`. Package suffix RGT = VQFN-16 3 × 3 mm, 0.5 mm pitch (addendum p.46; outline RGT0016C p.50–52: body 2.9–3.1 mm, lead 0.18–0.30 × 0.3–0.5 mm, exposed pad 1.68 ± 0.07 mm). KiCad's 1.6 mm EP is 0.08 mm under the drawing's nominal; TI's land pattern (p.51) uses 1.68 mm EP, 0.6 × 0.24 mm pads, four 0.2 mm vias in the EP. Match is acceptable.

Companion parts audited here: R10 ISET 1.78 k, R11 ILIM 1.62 k, R12 TMR 45.3 k, R13 TS 10 k, C10/C13 (IN), C11/C14 (OUT), C12/C15 (BAT), D1 + R14 (CHG LED), J2 (BAT pads). Wiring from `scripts/circuit.py` Block 2.

## Pin-by-pin wiring check (Table 7-1, p.8–9; Figure 7-2, p.7)

The BQ24074 variant's pin 15 is **ITERM** (not TD as on the '72/'73, not SYSOFF as on the '75/'79).

| Pin | Name | Our net | Datasheet requirement | OK? |
|---|---|---|---|---|
| 1 | TS | R13 10 k → GND | NTC, or 10 k fixed to VSS when TS not used (p.8, p.29, p.35) | OK (no temperature protection, see TS section) |
| 2, 3 | BAT | VBAT (C12 10 µ, C15 100 n, J2) | battery +, 4.7–47 µF bypass | OK |
| 4 | /CE | GND | low = charger enabled; internal 285 k pull-down; do not float | OK, charging always enabled |
| 5 | EN2 | 3V3_SYS | logic input, internal 285 k pull-down; do not float | OK, see EN1/EN2 section |
| 6 | EN1 | GND | logic input, internal 285 k pull-down | OK |
| 7 | /PGOOD | PG_N → RP2350 GPIO9 | open drain; 1–100 k pull-up to logic rail or LED | **no external pull-up** — see status outputs |
| 8 | VSS | GND | ground, tie to thermal pad | OK |
| 9 | /CHG | R14 330 R → D1 → 3V3_SYS | open drain; 1–100 k pull-up or LED | OK |
| 10, 11 | OUT | VSYS (C11 10 µ, C14 100 n, plus downstream bulk) | 4.7–47 µF bypass | OK (see caps) |
| 12 | ILIM | R11 1.62 k → GND | 1.1–8 k; open disables all charging | OK |
| 13 | IN | VBUS (C10 10 µ, C13 100 n) | 1–10 µF bypass | OK (at the top of the range) |
| 14 | TMR | R12 45.3 k → GND | 18–72 k; open = defaults; VSS = timers off | OK |
| 15 | ITERM | open | 0–15 k; **open = default 10 % termination** (p.8, p.27) | OK |
| 16 | ISET | R10 1.78 k → GND | 590–8900 Ω, 1 % (p.10 footnote 1); open disables charging | OK |
| 17 | thermal pad | GND | must be tied to VSS potential; VSS is the main ground input, not the pad (p.9) | OK |

## Absolute max vs our worst case (p.10)

| Parameter | Abs max | Recommended | Our worst case | Margin |
|---|---|---|---|---|
| IN voltage | 28 V | 4.35–10.2 V operating ('74) | 5.5 V (USB high line); OVP trips at 10.2–10.8 V | OK |
| BAT voltage | 5 V | — | 4.35 V (cell protector limit) | OK |
| OUT, EN1, EN2, /CE, TS, ISET, /PGOOD, /CHG, ILIM, TMR, ITERM | 7 V | — | OUT 4.5 V max regulated; EN2 3.3 V; LED node 3.3 V | OK |
| IN current | 1.6 A | 1.5 A | ILIM programs 1.06 A max (K_ILIM max 1720 / 1.62 k) | OK |
| OUT current continuous | 5 A | 4.5 A | ~2.3 A peak (2 × 1 A motors + 0.3 A radio) | OK on the rating; **limited by supplement-mode short-circuit detect**, see power path |
| BAT charge current | 1.5 A | 1.5 A | 0.55 A max (K_ISET max 975 / 1.78 k) | OK |
| BAT discharge current | 5 A | 4.5 A | ~2.3 A | OK |
| /CHG, /PGOOD sink | 15 mA | — | ~2.4 mA LED (/CHG), ~0 (/PGOOD) | OK |
| T_J | 150 °C | 125 °C | see thermal calc: 94–116 °C at 45 °C ambient while fast-charging a 3.4 V cell | OK but close; thermal loop throttles at 125 °C |
| Op temp (addendum) | −40 to 85 °C | | 0–45 °C | OK |

Logic levels (p.14): V_IL max 0.4 V, V_IH min 1.4 V. EN2 at 3.3 V and EN1/CE at 0 V are valid.

## Required external parts (from datasheet)

- **IN bypass 1–10 µF ceramic** (p.8; p.21 says "< 10 µF" to pass the USB-IF 50 µC inrush test; typical application uses 1 µF, p.33) → C10 10 µF 0603 X5R 10 V (CL10A106KP8NNNC) + C13 100 nF 0402 X7R 16 V. Nominal 10 µF is at the top of the range; after DC-bias derating at 5 V it is well inside (below). 10 V rating vs 5.5 V: 1.8× margin, acceptable for USB. p.35 warns that if the 28 V / 10.5 V OVP tolerance is relied on for "wrong adapter" protection, the IN cap must be rated for it; a 10 V cap is not. With a USB-C receptacle and no PD, VBUS cannot legitimately exceed 5.5 V, so this is accepted (NOTE). Other capacitance on VBUS: C2 100 nF at the receptacle; USBLC6 negligible. Total VBUS capacitance ≈ 10.2 µF nominal, ≈ 6 µF effective: within the USB 10 µF limit after derating.
- **OUT bypass 4.7–47 µF ceramic** (p.8) → C11 10 µF + C14 100 nF at the pin. Also on VSYS: C20 1 µF (LDO in), C40/C42 2 × 22 µF (motor bulk), C41/C43 100 nF. Nominal total ≈ 55 µF, above the 47 µF figure; derated at 4.4 V ≈ 7 + 2 × ~11 + 1 ≈ 30 µF, inside the range. The upper limit is not explained as a stability bound; the output is an LDO-type regulated FET. Accepted (NOTE).
- **BAT bypass 4.7–47 µF ceramic** (p.8) → C12 10 µF 0603 X5R 10 V + C15 100 nF. ≈ 7 µF at 4.2 V. OK. 10 V rating vs 4.35 V: 2.3×. OK.
- **R_ISET 590 Ω–8.9 kΩ, 1 %** (p.10, p.25) → R10 1.78 k 0402 1 % (0402WGF1781TCE, "F" = 1 %). OK.
- **R_ILIM 1.1–8 kΩ** (p.10, p.21) → R11 1.62 k 1 %. OK. Start-up short test (p.12, p.19): I_SC 1.3 mA must not pull the pin below V_SC 0.52 V → R > 400 Ω; both 1.78 k and 1.62 k pass.
- **R_TMR 18–72 kΩ** (p.10, p.27) or open → R12 45.3 k. OK.
- **TS: 10 k NTC in the pack, or 10 k fixed to VSS** (p.8, p.29, p.35) → R13 10 k. OK (fixed).
- **ITERM 0–15 k or open** (p.8, p.27) → open. OK.
- **/CHG LED: 1.5 k + LED from OUT** or 100 k pull-up to the processor rail (p.35) → R14 330 R + D1 from 3V3_SYS. OK (LED, see calc).
- **/PGOOD: 1 k–100 k pull-up or LED** (p.8, p.35) → none external; GPIO9 only. See status outputs.

### DC-bias derating of the 10 µF 0603 X5R 10 V (CL10A106KP8NNNC)

Samsung's published bias curve for this part is not in the repo; the figures below are estimates from the family's typical curve and must be confirmed against Samsung's characterisation tool before the gate is signed.

| Bias | Est. remaining capacitance | Effective C |
|---|---|---|
| 4.2–4.4 V (BAT, OUT) | ~65–70 % | ~6.5–7 µF |
| 5.0 V (IN) | ~55–60 % | ~5.5–6 µF |
| 5.5 V (IN, USB high line) | ~50 % | ~5 µF |

All three rails remain inside the datasheet's ranges after derating (IN 1–10 µF, OUT/BAT 4.7–47 µF).

## Calculations

### Fast-charge current (ISET), eq. 2 p.25, K_ISET p.13

I_CHG = K_ISET / R_ISET = 890 AΩ / 1780 Ω = **500 mA typ** (min 797/1780 = 448 mA, max 975/1780 = 548 mA). Target 500 mA: matches. Charge-current monitor voltage V_ISET = I/400 × R = 0.5/400 × 1780 = 2.23 V (eq. 3) — not used (ISET not routed to an ADC).

Pre-charge current I_PRECHG = K_PRECHG / R_ISET = 88 / 1780 = **49 mA** (39–60 mA), applied below V_LOWV = 3.0 V (p.13).

Termination (ITERM open): I_TERM = 0.1 × I_CHG = **50 mA** (45–55 mA) in ILIM mode (p.13). Note the threshold drops to 0.033 × I_CHG = 17 mA if the device is in USB100 mode (EN1 = EN2 = 0), which only occurs transiently at start-up here. Recharge when V_BAT < V_BAT(REG) − 100 mV = 4.1 V (p.13).

Battery regulation V_BAT(REG) = 4.20 V (4.16–4.23 V, p.13). Standard LiPo.

### Input current limit (ILIM), eq. 1 p.21, K_ILIM p.12

I_IN(MAX) = K_ILIM / R_ILIM = 1610 / 1620 = **994 mA typ** (min 1500/1620 = 926 mA, max 1720/1620 = 1.06 A). Target 1 A: matches. Below the 1.5 A pin rating and the 1.6 A abs max.

### Safety timers (TMR), eq. 6–7 p.27, K_TMR = 48 s/kΩ (36–60) p.13

- t_PRECHG = K_TMR × R_TMR = 48 × 45.3 = 2174 s = **36 min** (27–45 min).
- t_MAXCHG = 10 × K_TMR × R_TMR = 480 × 45.3 = 21 744 s = **6.0 h** (4.5–7.6 h).

**This does not match `intent.md`, which states a 10 h safety timer.** 10 h would need R_TMR = 36 000 / 480 = 75 k, above the 72 k maximum; the longest programmable timer is 10 × 48 × 72 k = 9.6 h typ. The 45.3 k value (46.4 k in TI's 6.25 h example, p.34) gives 6 h. Whether 6 h is enough depends on the cell capacity (an **ASK** in intent.md): at 500 mA CC plus CV taper, a cell up to ~2000 mAh completes in under 6 h; a larger cell, or heavy system load during charge (DPPM slows the timer clock proportionally, p.28, so that case self-corrects), would not. Either the intent text or R12 must change.

### CHG LED (R14, D1)

I_LED = (3.3 V − V_F − V_OL) / 330 Ω = (3.3 − ~2.0 (Everlight green, V_F to be read from its datasheet) − 0.4) / 330 ≈ **2.7 mA**. Within the 15 mA sink rating; V_OL spec'd at 5 mA (p.14). Brightness is low but fine for an indicator inside a translucent body. The datasheet's 1.5 k from 4.4 V OUT gives ~1.3 mA, so ours is brighter than TI's example.

### TS pin with a fixed 10 k

I_TS = 75 µA typ (72–78 µA, p.13) into 10 k → V_TS = **0.75 V** (0.72–0.78 V). Window: V_HOT = 0.30 V (0.27–0.33), V_COLD = 2.1 V (2.0–2.2) (p.13). 0.75 V sits inside the window with > 0.4 V to either trip point; a 1 % resistor is more than adequate. Consequence: **charging is always enabled and there is no cell-temperature cutoff.** The datasheet names this exact arrangement for "applications that do not use the TS function" (p.8, p.29, p.35). It is valid for the IC; whether it is acceptable for a cell cast in rubber next to two motors is a design decision already flagged in intent.md. If the chosen cell has an NTC, it needs a third pad on J2 and R13 removed; the window then equals 0–50 °C with a 10 k 103AT-type thermistor (p.14 footnote, p.30), extendable with Rs/Rp per Table 9-3.

### Thermal (eq. 11 p.42; θ_JA 44.5 °C/W p.11)

P = (V_IN − V_OUT) × (I_OUT + I_BAT) + (V_OUT − V_BAT) × I_BAT, using the 3.4 V battery the datasheet recommends for the max-dissipation point (p.42). With the 1 A input limit, I_OUT + I_BAT ≤ 1 A.

| Case | V_IN | I_OUT | I_BAT | P | ΔT at 44.5 °C/W | T_J at 45 °C ambient |
|---|---|---|---|---|---|---|
| Idle system, fast charge, nominal USB | 5.0 V | 0.1 A | 0.5 A | 0.36 + 0.5 = 0.86 W | 38 °C | 83 °C |
| Busy system, fast charge, nominal USB | 5.0 V | 0.5 A | 0.5 A | 0.6 + 0.5 = 1.1 W | 49 °C | 94 °C |
| Busy system, fast charge, USB high line | 5.5 V | 0.5 A | 0.5 A | 1.1 + 0.5 = 1.6 W | 71 °C | 116 °C |

T_J(REG) = 125 °C, so the high-line/busy/cold-cell corner is within 10 °C of thermal regulation on a JEDEC board in still air; the cast elastomer with no airflow will be worse than the JEDEC θ_JA. The thermal loop only throttles charge current (p.28–29) and slows the timers proportionally, so the failure mode is slower charging, not damage. The datasheet recommends not running in thermal regulation under nominal conditions (p.42). A solid thermal-pad via field into the GND planes (six-layer stackup) is the main mitigation; charging with the motors off is the operational one.

### Power path: what VSYS does (p.12, p.21–24)

- With USB present and the system drawing less than the input limit, OUT regulates to **V_O(REG) = 4.4 V typ (4.3–4.5 V)**, provided V_IN > V_OUT + dropout (V_DO(IN-OUT) 300 mV typ, 475 mV max at 1 A). At a 4.75 V USB low line, OUT is 4.28–4.45 V.
- When I_OUT + I_BAT reaches the ~1 A input limit, OUT sags; at V_DPPM = V_O(REG) − 100 mV = 4.3 V the DPPM loop reduces charge current to zero (p.22). Charge termination is disabled while in DPPM (p.22, p.25), so a busy system during charge delays "charge done" and keeps the LED on.
- When the system load alone exceeds the input limit, OUT falls to V_BAT − 40 mV (V_BSUP1) and the battery FET turns fully on: **battery supplement mode**. The jump from 4.4 V to ~V_BAT is a step VSYS consumers must tolerate (the LDO, RM2 and motors all accept 3.0–4.4 V per intent.md). Exit at V_OUT ≥ V_BAT − 20 mV.
- With no USB, OUT is the battery through the BAT FET: V_DO(BAT-OUT) = 50 mV typ, **100 mV max at 1 A** (≈ 50–100 mΩ). Not current-limited except by the short-circuit detector.
- **Short-circuit detector in supplement/battery mode** (p.12, p.22, p.24): if V_BAT − V_OUT > V_O(SC2) = 250 mV typ (**200 mV min**) for t_DGL(SC2) = 250 µs, OUT is switched off and retried after t_REC(SC2) = 60 ms. At the intent's 2.3 A peak, the FET drop is 2.3 A × 50–100 mΩ = 115–230 mV: inside the typical 250 mV, but a worst-case FET against a worst-case 200 mV threshold trips. Two 1 A motors at full duty plus a radio burst can therefore brown the system out for 60 ms, with the retry hiccuping. At the ERM figures intent.md calls typical (60–500 mA each), the total is ≤ 1.3 A and the drop is ≤ 130 mV, fine. **Practical VSYS current ceiling from the battery is about 2 A worst case**; the real motor current (an ASK) decides whether this matters. The 22 µF bulk caps do not help: a 1 A PWM pulse for 20 µs droops 44 µF by 0.45 V, and the 250 µs deglitch is longer than a 25 kHz PWM period, so the FET supplies the pulses.
- OUT short-circuit at start-up (V_O(SC1) 0.9 V, p.12): start-up is at a 100 mA input limit until OUT exceeds 0.9 V (p.19); with ~55 µF on VSYS and the LDO's load this is fast. OK.
- Sleep: input between UVLO (3.3 V) and V_BAT + 80 mV → IN-OUT FET off, I_BAT(PDWN) 4.3 µA typ, 6.5 µA max (p.12, p.31). Negligible.

### EN1/EN2 as wired (Table 7-2 p.9, p.19)

EN1 = 0 (GND), EN2 = 1 (3V3_SYS) → **input limit set by R_ILIM** (~1 A). USB suspend (EN1 = EN2 = 1) is unreachable since EN1 is grounded, which is fine. Two consequences:

1. **Start-up loop.** 3V3_SYS comes from the TLV75533 on VSYS, which is the charger's own OUT. When USB is first applied with no 3V3 yet, EN2 reads low through its internal 285 k pull-down, so the chip reads EN1 = EN2 = 0 → USB100 (100 mA). Start-up is at 100 mA regardless (p.19), OUT rises, the LDO starts, EN2 goes high, and because the device "continuously monitors the status of /CE, EN1 and EN2" during normal operation (p.19) it moves to the ILIM limit. TI's own standalone BQ24074 example (Figure 10-12, p.38) ties EN2 to OUT, the same bootstrap one stage removed, so this is an accepted pattern. If the LDO cannot start on 100 mA (it can: RP2350 idle plus LDO quiescent is well under that), the system would be stuck in USB100. Acceptable; NOTE.
2. **No V_IN-DPM protection in ILIM mode.** V_IN-DPM (4.5 V typ) is specified only for EN2 = LO (p.12, p.22). In our mode a weak source (a legacy 500 mA USB-A port through an A-to-C cable) is pulled to its limit; VBUS sags until V_IN < V_BAT + 80 mV, /PGOOD deasserts, OUT drops to the battery, VBUS recovers, and the cycle repeats. No damage, but a 1 A draw from a 500 mA port is out of USB spec. The board has 5.1 k CC pull-downs so a USB-C source advertises ≥ 1.5 A, which covers the common case. The firmware cannot change the limit because neither EN pin is on a GPIO. MINOR; see open questions.

### Status outputs (p.28, Tables 9-1/9-2)

- /PGOOD is low only when V_BAT + 80 mV < V_IN < V_OVP (10.5 V), with a 1.2 ms deglitch. It goes to GPIO9 with **no external pull-up**. The RP2350 pads default to pull-down after reset, so firmware must enable the internal pull-up (within the 1–100 k range the datasheet allows) before reading, and the pin reads low (as if "USB present") until it does. A 100 k to 3V3_SYS would make the state unambiguous from power-on and costs a basic 0402. MINOR.
- /CHG drives D1 only. It is low (LED on) for the **first** charge cycle after power-up, /CE toggling, or an OVP event; subsequent top-up recharges after termination leave it high-impedance (LED off) (p.28, Table 9-2). It flashes at 2 Hz on a safety-timer fault; with /CE hard-wired low the fault clears only by removing USB or an OVP event (p.28). The LED also stays on while charge is suspended by the thermal loop. No logic monitoring of /CHG, so firmware cannot distinguish charging from done. NOTE.

## Fine print / gotchas

- "Do not leave /CE, EN1 or EN2 unconnected" (p.8): all three are tied. OK.
- "Do not use the thermal pad as the primary ground input; VSS must be connected to ground at all times" (p.9): pin 8 is on GND. OK.
- "Leaving ILIM unconnected disables all charging" and "charging is disabled if ISET is left unconnected" (p.8): both have resistors; an open solder joint on R10 or R11 silently disables charging — a test point to probe.
- "Use a 1 % resistor for R_ISET to avoid issues with the R_ISET short test" (p.10): R10 is 1 %.
- Abs-max footnote 2 (p.10): charging-FET life is 20 000 h at 1.5 A and 125 °C. We charge at 0.5 A; not a concern.
- Timer slowing (p.28): in DPPM, V_IN-DPM, or thermal regulation the timer clock slows proportionally to the charge-current reduction, so a loaded system does not cause false timer faults.
- Termination is disabled in DPPM, supplement and thermal-regulation modes (p.22, p.25, p.29).
- Battery detection (p.27): after termination, with V_BAT < V_RCH the IC sinks 7.5 mA / sources the pre-charge current for 250 ms pulses to test for a battery; a protected cell whose protector has opened looks like "no battery". Normal.
- Half-wave adapters (p.39): the charger stays on 20 ms after sleep entry; not relevant to USB.
- EN1/EN2 abs max 7 V: EN2 is on 3V3, not VBUS, so a 28 V input fault cannot reach it. Good.
- OVP for the '74 is 10.5 V (not 6.6 V as for the siblings), so a 9 V or 12 V USB-PD supply would be passed through to the IN cap and the USBLC6 if one were ever negotiated. Nothing on this board negotiates PD. The 10 V IN capacitor is the weakest point in that hypothetical.
- Op temp of the orderable part is −40 to 85 °C (addendum p.46); MSL 2.

## Layout guidance from datasheet (p.40–42, p.51–52)

- Place the IN decoupling cap and the OUT filter caps as close as possible to the IC with short traces to IN, OUT and the thermal pad ground (p.40). C10/C13 at pin 13, C11/C14 at pins 10–11, returns into the pad.
- Keep low-current grounds (ISET, ILIM, TMR, TS, LED) separate from the high-current charge/discharge ground; single-point ground joining the small-signal and power ground paths (p.40). The R10–R13 ground ends should return to the pad/VSS side, not through the motor return.
- Size the IN and OUT copper for the maximum current (p.40): IN at 1 A, OUT/VSYS at the 2.3 A motor peak, BAT at 2.3 A discharge.
- Thermal pad to the PCB ground plane with multiple vias (p.42: "pad should have multiple vias"); TI's land pattern shows four 0.2 mm vias at the pad corners, vias under paste filled, plugged or tented (p.51 note 5); stencil 85 % coverage of the EP (p.52); NSMD pads preferred (p.51). This is the device's main heat path; with the six-layer stack, stitch the pad into both GND planes.
- Figure 12-1 (p.41) shows the IN, OUT and BAT caps each with its own via pair to ground immediately beside the cap, and the ISET/ILIM/TS resistors on the low-current side.
- Verify thermal performance on the first boards by charging a fully discharged cell with the system running and watching the charge current taper (p.42).

## Open questions

1. **Safety timer: 6 h (R12 45.3 k) vs the 10 h in intent.md.** Which is intended? 10 h is not programmable (max 9.6 h with 72 k). Needs the cell capacity to decide.
2. **Cell capacity, protection and NTC** (intent.md ASK). An NTC cell needs a third BAT pad and R13 removed; a cell without one keeps the fixed 10 k and has no temperature cutoff while charging inside a rubber body beside two motors.
3. **Actual motor current.** At the 1 A-per-channel design figure the battery-mode short-circuit detector can trip at a worst-case 2.3 A; at realistic ERM currents it cannot. Confirm before relying on 1 A channels.
4. **Should EN1 (and/or EN2) go to a GPIO** so firmware can fall back to USB500 on a weak port, or is the ILIM-only mode acceptable for a hobby device charged from phone chargers?
5. **/PGOOD pull-up**: add 100 k to 3V3_SYS, or document that firmware enables the internal pull-up before reading GPIO9?
6. **Sourcing**: LCSC C54313 stock, price and basic/extended status were not confirmed on 2026-10-17 (the number is inherited from bike-tracker).
7. **Capacitor derating**: confirm the CL10A106KP8NNNC bias curve at 4.4 V and 5.5 V from Samsung's tool; the estimates above have no source in the repo.

## Findings

**BLOCKER**
- None. The wiring is valid for the BQ24074 pinout; every pin has a legal termination and every programmed value is inside its range.

**MAJOR**
- M1. **Safety timer mismatch.** R12 45.3 k programs a 6.0 h fast-charge timer (4.5–7.6 h over K_TMR tolerance), not the 10 h in intent.md; 10 h cannot be programmed. Fix intent.md or pick R12 for the cell's capacity (p.13, p.27).
- M2. **Battery-mode current ceiling.** With the BAT-OUT FET at its 100 mΩ max and the short-circuit threshold at its 200 mV min, a sustained VSYS draw above ~2 A (the intent's 2.3 A peak) turns OUT off for 60 ms. The intent's "up to 2 A discharge peak" is at the edge; either confirm the motors draw far less (likely) or cap total VSYS load at ~2 A worst case (p.12, p.22, p.24).
- M3. **Thermal margin while charging a cold cell with the system busy at 5.5 V in** is ~10 °C below thermal regulation on a JEDEC board; the elastomer will be worse. Not damaging (the loop throttles), but charging will slow and the thermal-pad via field is mandatory (p.11, p.28, p.42).

**MINOR**
- m1. **/PGOOD has no pull-up resistor**; GPIO9 relies on the RP2350's internal pull-up being enabled by firmware. Add 100 k to 3V3_SYS or document the firmware requirement (p.8, p.35).
- m2. **No V_IN-DPM in ILIM mode.** A 500 mA legacy USB port will be overdrawn to 1 A and cycle /PGOOD; neither EN pin is host-controllable. Accept, or move EN1 to a GPIO (p.12, p.22).
- m3. **IN capacitor rating.** 10 V on VBUS is fine for 5.5 V USB but not for the 10.5 V OVP ceiling the '74 would pass through; a 16 V 0603 10 µF closes the gap if the user cares about wrong-adapter cases (p.35).
- m4. **Nominal OUT capacitance (~55 µF) exceeds the 47 µF upper figure** on p.8; derated it is ~30 µF. Accepted, but noted in case the upper bound turns out to be a stability requirement.

**NOTE**
- n1. ISET 1.78 k → 500 mA (448–548 mA); ILIM 1.62 k → 994 mA (926–1062 mA); ITERM open → 50 mA termination; pre-charge 49 mA below 3.0 V; recharge at 4.1 V. All as intended.
- n2. TS 10 k fixed → V_TS 0.75 V, inside the 0.3–2.1 V window: charging always enabled, no temperature cutoff. Matches the datasheet's prescribed "TS not used" termination and the risk already recorded in intent.md.
- n3. EN2 on 3V3_SYS bootstraps through USB100 at start-up before switching to ILIM mode; same pattern as TI's standalone example with EN2 on OUT (Figure 10-12).
- n4. VSYS is 4.4 V (4.3–4.5 V) with USB, drops to V_BAT − 40 mV in supplement mode, and is the raw battery through ~50–100 mΩ without USB. Downstream parts must accept the 4.4 V → ~3.0 V range (already in intent.md).
- n5. /CHG lights D1 only on the first charge cycle after plug-in and flashes at 2 Hz on a timer fault; with /CE grounded, a fault clears only by unplugging. The LED cannot tell "done" from "top-up recharge".
- n6. Footprint VQFN-16 3 × 3 EP 1.6 mm matches the RGT suffix (drawing EP 1.68 ± 0.07, land 1.68). Four EP vias per TI's land pattern.
- n7. An open R10 or R11 silently disables charging; keep ISET and ILIM probe-able before casting.
