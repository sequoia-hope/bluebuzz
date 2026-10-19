# Q1/Q2 — motor channels (AO3400A low-side switches, flyback, bulk caps)

Two identical low-side PWM channels, Block 4 of `scripts/circuit.py`:
GPIO0/1 (MOTOR1_PWM / MOTOR2_PWM) → R40/R42 100 R → gate; R41/R43 100 k gate to GND;
Q1/Q2 AO3400A source to GND, drain = MOTOR1_SW / MOTOR2_SW; D3/D4 B5819W cathode on VSYS,
anode on the switch node; C40/C42 22 µF and C41/C43 100 nF VSYS to GND; J4 pads VSYS, M1, M2.
The motor hangs between VSYS and Mn, so the FET sinks the motor current and the diode
recirculates it into VSYS when the FET is off.

| Ref | Part | Datasheet | LCSC | Footprint |
|---|---|---|---|---|
| Q1, Q2 | AO3400A, SOT-23 | `design/datasheets/ao3400a.pdf` (AOS rev 3.1, July 2023, 5 pages). **Read: all.** | C20917 (basic) | `Package_TO_SOT_SMD:SOT-23`, pin 1 G, 2 S, 3 D — matches the p.1 top-view drawing (G lower-left, S lower-right, D top) |
| D3, D4 | B5819W, SOD-123 | **NOT in `datasheets/`** (LCSC blocked the fetch). Everything B5819W-specific below is **UNVERIFIED** | C8598 | `Diode_SMD:D_SOD-123`, pin 1 = cathode (KiCad convention; parts.yaml says the same) |
| R40, R42 | 100 R 0402 | — | C25076 | R_0402 |
| R41, R43 | 100 k 0402 | — | C25741 | R_0402 |
| C40, C42 | 22 µF X5R 10 V 0603, CL10A226MP8NUNE | Samsung DC-bias curve not in `datasheets/` — derating below is an estimate | C86295 | C_0603 |
| C41, C43 | 100 nF X7R 16 V 0402 | — | C1525 | C_0402 |
| J4 | 3 bare pads | — | — | library/parts.pretty |

Operating conditions from `design/intent.md`: VSYS 3.0–4.4 V; 3.7 V ERM motors, up to 1 A
per channel (design value; real ERMs 60–500 mA, **ASK** item in intent.md); PWM 20–25 kHz;
0–45 °C ambient; the board is cast in elastomer with no airflow.

## Absolute max vs our worst case (AO3400A, p.1)

| Parameter | Abs max | Our worst case | Margin |
|---|---|---|---|
| VDS | 30 V | VSYS 4.4 V + diode Vf ≈ 0.6 V + ringing; say 6 V | OK (5×) |
| VGS | ±12 V | 3.3 V from the GPIO (3V3_SYS) | OK |
| ID continuous, TA = 70 °C | 4.7 A | 1 A | OK |
| IDM pulsed | 30 A | motor start inrush: stalled-rotor current = VSYS / R_motor. For a 1 A @ 3.7 V motor R ≈ 3.7 Ω, so ≤ 1.2 A at 4.4 V. Even a 1 Ω "strong" ERM gives 4.4 A | OK |
| PD, TA = 70 °C | 0.9 W (on 1 in² 2 oz FR-4, note B) | ≈ 70 mW worst case (below) | OK |
| TJ | 150 °C | ≈ 60 °C (below) | OK |
| Body diode IS | 2 A | never forward biased (low-side, drain always ≥ 0 V) | n/a |

B5819W (**UNVERIFIED**, 1 A / 40 V SOD-123 Schottky class): VRRM 40 V vs reverse voltage
VSYS − Vds(on) ≈ 4.4 V → ~9× margin; IF(AV) 1 A vs ≤ 1 A × (1 − D) average → OK at the
spec limit; IFSM (typ. 25 A for this class) vs the motor's stall current → OK.

## Required external parts

The AO3400A datasheet has no application section; it specifies nothing external. What the
circuit needs and has:

- Gate series resistor R40/R42 100 R — damps the gate/SW ringing and limits the pad's
  transient current (calc below). Keep.
- Gate pull-down R41/R43 — holds the FET off while the GPIO is high-Z. **Value must change
  to ≤ 8.2 k** (RP2350-E9, calc below).
- Flyback diode D3/D4 across each motor, cathode to VSYS, anode to the switch node — correct
  orientation for a low-side switch (when Q turns off the switch node flies above VSYS and
  the diode clamps it to VSYS + Vf). Pin 1 = cathode is on VSYS in circuit.py. **Verify pin 1
  = cathode against the B5819W drawing and the SOD-123 cathode band once the datasheet is in.**
- Bulk C40/C42 22 µF + C41/C43 100 nF on VSYS beside each diode/FET pair: they supply the
  pulsed motor current so it doesn't run through the battery lead and the charger's power-path
  FET (calc below: capacitance is marginal at 1 A).

## Calculations

### Rds(on) at Vgs = 3.3 V (Fig. 5, p.3; table p.2)

The gate drives to IOVDD = 3.3 V (no static gate current, so the pad's VOH drop doesn't
apply). Figure 5 (Rds vs Vgs at ID = 5.7 A) reads:

| Vgs | 25 °C typ | 125 °C typ |
|---|---|---|
| 2.5 V | 24 mΩ (table) | ≈ 37 mΩ |
| 3.3 V | **≈ 21 mΩ** | ≈ 33 mΩ |
| 4.5 V | 19 mΩ (table) | ≈ 30 mΩ |

Max from typ: the table gives max/typ = 32/19 = 1.68 at 4.5 V and 48/24 = 2.0 at 2.5 V.
Take 1.75 at 3.3 V → **Rds(on,max, 25 °C, 3.3 V) ≈ 37 mΩ**. Temperature (Fig. 4): ×1.25 at
Tj ≈ 75 °C → **design value 45 mΩ** (worst case, hot). Typical hot: ≈ 25 mΩ. At ID = 1 A
Fig. 3 shows ~1 mΩ less than at 5.7 A; ignored.

### Conduction loss

P_cond = I² × Rds(on) × D. Worst case D → 1 (full-on):

| Motor current | Rds 45 mΩ (max, hot) | Rds 25 mΩ (typ, hot) |
|---|---|---|
| 0.5 A | 11 mW | 6 mW |
| 1 A | **45 mW** | 25 mW |

Vds(on) at 1 A = 45 mV, so the motor sees VSYS − 0.045 V: no meaningful drop.

### Gate charge and switching time with 100 R from a 3.3 V GPIO

- Qg to 3.3 V from Fig. 7 (p.4; test at VDS = 15 V, ID = 5.7 A): ≈ 4.5 nC (table Qg = 6 nC
  typ / 7 nC max is to 10 V). Qgs 1.3 nC, Qgd 1.8 nC at 15 V; at our 5 V swing Qgd is
  roughly 0.8 nC (Fig. 8 Crss ≈ 60–300 pF over 0–5 V). The 1.8 nC figure is used below as
  the conservative case.
- Miller plateau at ID = 1 A: Fig. 2 (transfer, p.3) gives ID = 1 A at Vgs ≈ 1.65 V (25 °C),
  ≈ 1.55 V (125 °C). With Vgs(th) max 1.45 V (p.2) the plateau is ≤ ~1.9 V worst case.
- Driver source impedance: RP2350 pad at the 12 mA setting, VOH min 2.62 V at 12 mA and VOL
  max 0.5 V at 12 mA (datasheet Table 1683, p.1336) → worst-case ≈ 57 Ω source / 42 Ω sink;
  typical ≈ 20 Ω (Fig. 154, p.1339). Total loop: R_pad + R40 100 R + Rg 3 Ω (p.2) ≈
  **125 Ω typ, 160 Ω worst**.
- Turn-on, plateau at 1.7 V: I_g = (3.3 − 1.7) / 160 Ω = 10 mA → t_v = Qgd / I_g = 1.8 nC /
  10 mA = **180 ns** (≈ 80 ns with the 5 V-scaled Qgd). Pre-plateau (Vth → plateau):
  Ciss 630 pF × 0.6 V / 13 mA ≈ 30 ns. Delay to Vth: τ = 160 Ω × 630 pF = 100 ns,
  t ≈ τ × ln(3.3/(3.3−1.05)) ≈ 40 ns.
- Turn-off: I_g = 1.7 V / 145 Ω = 12 mA → t_v ≈ 150 ns; delay from 3.3 V to plateau ≈
  τ × ln(3.3/1.7) ≈ 65 ns.
- **Per edge ≈ 200–250 ns including delays; ≈ 0.5 % of the 40 µs period at 25 kHz.**
  PWM resolution is unaffected.

Is 100 R needed or limiting?
- Peak pad current at the instant of switching = 3.3 V / 160 Ω ≈ 21 mA (worst 3.3/125 =
  26 mA), decaying with τ ≈ 100 ns. This exceeds the "12 mA" drive-strength number, but
  the RP2350 datasheet (p.1339) defines drive strength as the current at which VOH/VOL are
  guaranteed, not a limit; the hard limits are IIOVDD_MAX = 100 mA summed over the bank
  (p.1338). Average gate current = Qg × f = 4.5 nC × 25 kHz = 0.11 mA. Not limiting.
- Without R40 the peak would be 3.3 V / 45 Ω ≈ 75 mA for ~30 ns, edges ~4× faster, and the
  switch node (which goes straight to a soldered motor lead, an antenna for the RM2 a few cm
  away) would ring harder. 100 R costs ≈ 15 mW of switching loss (below) and buys slower
  dV/dt and gate damping. **Keep 100 R.** 47 R would halve the switching loss if ever needed.
- Firmware: set GPIO0/1 to 12 mA drive, fast slew (`gpio_set_drive_strength`,
  `gpio_set_slew_rate`). At the default 4 mA setting R_pad worst ≈ 170 Ω and the edges
  roughly double; still fine.

### Switching loss at 25 kHz

Inductive load, hard-switched (diode clamps the node to VSYS + Vf ≈ 5 V while the current
transfers): P_sw ≈ ½ × V × I × (t_on + t_off) × f
= ½ × 5 V × 1 A × (210 + 180) ns × 25 kHz ≈ **25 mW worst case**, ≈ 10 mW typical.
Gate drive power Qg × V × f = 4.5 nC × 3.3 V × 25 kHz = 0.4 mW. Coss loss ½ × 150 pF × 5² ×
25 kHz ≈ 0.05 mW. Body-diode reverse recovery: n/a (the Schottky carries the freewheel).

### Junction temperature

P_total(1 A, D = 1) ≈ 45 + 25 = **70 mW worst** (≈ 35 mW typical). RθJA (p.1, note A):
100 °C/W typ, 125 °C/W max on 1 in² 2 oz copper in still air. This board: 28 × 44 mm
(1.9 in²) six-layer with two ground planes, 1 oz outer / 0.5 oz inner, 0402 neighbours, and
the whole board is cast in rubber (no convection). Assume **RθJA ≈ 150–200 °C/W** effective
(the copper spreads well, but the board-to-ambient path is through elastomer).
ΔTj = 70 mW × 200 °C/W = **14 °C** → Tj ≈ 45 + 14 = **59 °C**, vs 150 °C max. Both channels
together put ≈ 140 mW into the board, which is a few °C of board rise. No thermal concern,
even at 2× the design current. The Rds(on) temperature factor of 1.25 used above is
therefore conservative.

### Power-up state: 100 k pull-down and Vgs(th)

- Vgs(th) (p.2): 0.65 V min, 1.05 V typ, 1.45 V max at ID = 250 µA, 25 °C. Fig. 2 shows the
  125 °C threshold ~0.3 V lower, so **≈ 0.5 V min hot**. ID at Vgs = 1 V is still tens of
  µA; the FET conducts real current (> 100 mA) only above ~1.3–1.5 V.
- Static: IGSS ≤ 100 nA (p.2) × 100 k = 10 mV. The RP2350 pad after reset is an input
  (NULL function) with leakage ≤ 1 µA at 0 V → 100 mV worst. Both far below 0.5 V. OK.
- Divider when driven: 100 R / 100 k → gate high = 3.297 V. Negligible.
- Miller pull-up when VSYS rises with the FET off: Vg ≈ Crss × R_pd × dV/dt. Charger
  power-up (ms ramp): 50 pF × 100 k × 4.4 V/1 ms ≈ 20 mV. OK. Battery hot-plug with USB
  already present (V/µs edges): 50 pF × 100 k × 4 V/µs ≈ 20 V, i.e. the gate is yanked up for
  the duration of the edge (~1 µs), then decays with τ = Crss·R = 5 µs. A ~µs motor blip,
  harmless by itself, **but see the next point**.
- **RP2350-E9 (datasheet Appendix D.5.1, p.1358): "Increased leakage current on Bank 0 GPIO
  when pad input is enabled."** When a GPIO is configured as an input (NULL function, as
  GPIO0/1 are from reset until firmware starts the PWM slice, and permanently in BOOTSEL
  mode) and the pad voltage is in the undefined region between VIL 0.8 V and VIH 2 V, the pad
  sources ≈ 120 µA and **holds itself at ≈ 2.2 V**. 120 µA × 100 k = 12 V, so a 100 k
  pull-down cannot pull it back out. Vgs = 2.2 V is above Vgs(th) max and Fig. 5 puts Rds at
  ≈ 30 mΩ there: **the FET would be fully on and the motor would run, uncontrolled, until
  firmware takes the pin.** The erratum's own fix is an external pull-down of **8.2 kΩ or
  less**. Any event that lifts the gate through 0.8–2 V while the pad is an input triggers it:
  the hot-plug Miller pulse above (its 5 µs decay passes right through the latch window), a
  transient on the motor lead, or firmware leaving the pin as an input. The exposure window
  is boot and BOOTSEL mode; in BOOTSEL the user is plugging USB in, which is exactly when
  VSYS steps from VBAT to 4.4 V.
  **Change R41/R43 to 4.7 k** (or 8.2 k; 4.7 k keeps margin against the ≤ 8.2 k requirement
  with 1 % parts and leaves the gate at 3.3 × 4.7/4.8 = 3.23 V when driven, Rds unchanged).
  Cost: 0.7 mA from 3V3_SYS per channel at 100 % duty, 2.3 mW. The pull-down's static
  attenuation of the hot-plug Miller pulse also improves 20× (Crss × 4.7 k = 0.24 µs).

### Flyback diode current and reverse voltage (B5819W numbers UNVERIFIED)

Motor: ERM with R ≈ 3.7 Ω at the 1 A design point, L of order 100 µH–1 mH → τ = L/R ≈
30–300 µs ≫ the 16–20 µs off time at 50–60 % duty, so the motor current is continuous and
the diode carries the full motor current during the off time.
- Peak I_F = I_motor ≤ 1 A (stall ≤ 1.2 A at 4.4 V for the 3.7 Ω motor). Within a 1 A
  rating with no peak margin; fine for the realistic 60–500 mA motors.
- Average I_F = I × (1 − D). Diode power P_D = Vf × I × (1 − D) with Vf ≈ 0.55–0.6 V at 1 A
  for this class (UNVERIFIED). Worst at D = 0.5, I = 1 A: **≈ 0.3 W**. SOD-123 RθJA on
  minimal pads is 150–250 °C/W (UNVERIFIED, no datasheet) → **ΔTj ≈ 45–75 °C**, Tj ≈
  90–120 °C at 45 °C ambient. Within a typical 125–150 °C rating but hot, and Schottky
  reverse leakage grows ~2× per 10 °C (VSYS 4.4 V reverse, trivial at 40 V rating).
  At 150 mA (a normal ERM) P_D = 0.04 W, ΔTj < 10 °C.
- Reverse voltage: when Q is on, V_R = VSYS − Vds(on) ≤ 4.4 V vs VRRM 40 V. When Q is off
  the diode is forward biased; the FET sees VSYS + Vf ≈ 5 V.
- Reverse recovery: Schottky, negligible; the FET's turn-on sees only the diode's junction
  capacitance (~100 pF class) — a small current spike through Rds, no loss worth counting.
- The diode loop (motor → D → VSYS → C41/C43 → GND → Q source → Q drain → motor) is where
  the motor current commutates at every edge; C41/C43 100 nF must sit across that loop
  (layout below).

### Bulk capacitor ripple current and DC-bias derating

VSYS supplies I_motor during the on time and nothing during the off time (the diode
recirculates locally). The capacitors absorb the AC part:
- Cap RMS current per channel I_rms = I × √(D(1−D)) → max **0.5 A at D = 0.5, I = 1 A**;
  1 A rms if both channels switch in phase. MLCC ripple is ESR-limited only: with ESR ≈ 5 mΩ
  the heating is I² × ESR ≈ 1–5 mW. No ripple-current concern for X5R.
- Ripple voltage per channel: ΔV = I × D × (1−D) × T / C_eff = 1 A × 0.25 × 40 µs / C_eff
  = 10 µC / C_eff.
- DC-bias derating of C40/C42 (CL10A226MP8NUNE, 22 µF X5R 10 V 0603): Samsung's curve is
  not in `datasheets/`; 22 µF 0603 10 V X5R parts typically retain **40–55 % at 4.4 V →
  ≈ 9–12 µF each**, ≈ 15 µF at 3.0 V. The other VSYS caps (C11 10 µF 0603 10 V at the
  charger, C14 100 nF, C20 1 µF) add ≈ 5 µF but sit across the board, behind the VSYS pour.
- With both 22 µF effective ≈ 20 µF at 4.4 V: **ΔV ≈ 0.5 V per channel at 1 A, up to 1 V
  with both channels in phase.** At 3.0 V battery (caps ≈ 30 µF): ≈ 0.33 V per channel.
  That ripple lands on the VSYS rail that feeds the TLV75533 (which is already in dropout
  near 3.0 V) and the RM2's Vin. At a realistic 150 mA motor: ΔV ≈ 75 mV per channel, fine.
- The battery and the BQ24074's power-path FET are the DC source; at 25 kHz the lead
  inductance and the cell's ~100–200 mΩ (with its protection PCB) make them poor AC sources,
  so the number above is close to what the rail will see.
- Mitigations, cheapest first: (1) **firmware: run the two PWM slices 180° out of phase**
  (halves the worst case for free), (2) raise bulk to 2 × 22 µF per channel or move to a
  0805 22 µF 16 V (better bias retention, ≈ 60–70 % at 4.4 V), (3) accept, if the real
  motors are ≤ 300 mA (the **ASK** in intent.md decides this).

### Gate resistor / pull-down power

R40: 0.11 mA average, ≈ 0 W. R41 at 4.7 k: 3.3² / 4.7 k = 2.3 mW at 100 % duty vs 62.5 mW
rating (0402). OK.

## Fine print / gotchas (AO3400A)

- Note A (p.2): RθJA is measured on 1 in² of 2 oz copper in still air; "the value in any
  given application depends on the user's specific board design". Our board is cast in
  rubber; the estimate above derates to 200 °C/W.
- Note B: PD is based on the ≤ 10 s RθJA (90 °C/W), not steady state (125 °C/W). The 1.4 W
  / 0.9 W headline is not a continuous rating; continuous at 70 °C ambient on the reference
  board is (150−70)/125 = 0.64 W. Still 9× our load.
- Note C: IDM = 30 A is a repetitive pulse rating limited by Tj, assuming Tj starts at 25 °C.
- Note E: Figures 1–6 are from < 300 µs pulses at ≤ 0.5 % duty (no self-heating); the Rds
  temperature correction (Fig. 4) must be applied by hand, as done above.
- Note F: the SOA (Fig. 9) and transient thermal curves (Figs. 10–11) are for the reference
  board. Our DC operating point (Vds 45 mV, 1 A) is deep inside the Rds-limited region.
- Vgs(th) 0.65–1.45 V is a logic-level threshold with a wide spread; it is the reason the
  gate must be held low by a resistor, not left to the MCU's internal pull-down (which, per
  E9, is weaker than the pad's own leakage).
- Gate ESD: **the datasheet gives no ESD rating and no gate protection diode.** Vgs abs max
  is ±12 V. The gate sits behind 100 R from a GPIO (RP2350 HBM 2 kV, p.1335) and 4.7 k to
  ground, on an internal node with no external access; nothing to add. The drain is external
  (motor lead inside the cast body): the 30 V Vds abs max and the Schottky to VSYS are its
  only protection. Acceptable because the pads are not user-accessible after casting
  (intent.md); a 5 V motor lead transient would ring the node, not break it.
- The static "ID(ON) 30 A at Vgs 4.5 V" and "Rds 48 mΩ max at 2.5 V" lines bracket our
  3.3 V operating point; the datasheet does not specify 3.3 V, so the 37 mΩ max above is an
  interpolation, flagged in the findings.
- B5819W: the generic 1N5819-class SOD-123 has Tj max 125 °C (some vendors 150 °C), VF
  0.6 V max at 1 A, IR up to 1 mA at 40 V hot. Confirm all three from the real sheet.

## Layout guidance

The AO3400A datasheet has no layout section. From the circuit:

- **Commutation loop per channel**: Q drain pad → D anode → D cathode (VSYS) → C41/C43
  100 nF → GND → Q source. Place D and the 100 nF within ~2 mm of the FET, with the 100 nF
  across VSYS-to-FET-source directly; the 22 µF beside it. This loop carries the full motor
  current step at every edge; its inductance sets the ringing on the switch node, which is
  also a wire antenna next to the RM2 (keep-out in design.yaml).
- Switch node (MOTORn_SW): FET drain, diode anode, J4 pad only. Short and wide (1 A: ≥ 0.3
  mm 1 oz for 10 °C rise; `nets.csv`), no detour; keep it off the top edge (RM2 antenna).
- Gate loop: GPIO → R40 → gate, with R41 at the gate pad and the FET source tied to the GND
  plane by its own via(s) right at pin 2, so the gate return doesn't share the 1 A path.
- FET source pin 2 and the diode/cap GND: at least two vias each to the In2/In4 ground
  planes (1 A pulsed per channel; `nets.csv`).
- VSYS feed from the In3 pour to each channel's bulk caps with a via array sized for 1 A
  continuous + 2 A peak for both channels (`nets.csv`).
- Thermal: the SOT-23 drain tab on 1 oz copper with a small pour and a couple of vias into
  the inner ground-adjacent copper is plenty (70 mW). The SOD-123 diode is the hotter part
  at 1 A / 50 %; give both its pads copper and vias.
- J4 pads: VSYS, M1, M2 single row, 1.6 × 2.2 mm at 2 mm pitch, back side (intent.md). Order
  VSYS, M1, M2 so each motor's pair is adjacent for twisted leads.
- Silkscreen: "MOT  VSYS M1 M2  1A max" (intent.md convention).

## Open questions

1. **B5819W datasheet** — not downloadable; the user must attach it. To verify: VRRM, IF(AV)
   and its reference pad area, VF at 1 A, Tj max, RθJA, IR at 4.4 V hot, SOD-123 pin 1 =
   cathode marking, LCSC C8598 stock.
2. **Samsung CL10A226MP8NUNE DC-bias curve** — attach or look up; the 9–12 µF at 4.4 V is an
   estimate from the 0603/10 V/22 µF class.
3. **Actual motor current** (intent.md ASK). Every finding below that says "at 1 A" vanishes
   at 150 mA. If the answer is ≤ 300 mA, the diode heating and VSYS ripple findings close.
4. Should the PWM slices be phase-staggered in firmware? (Recommended regardless.)
5. Sourcing dates: parts.yaml marks AO3400A C20917 "verified: yes" and B5819W C8598
   "verified: api" with no stock count or date; record them before the gate.

## Findings

| Rank | Finding | Action |
|---|---|---|
| **MAJOR** | R41/R43 100 k cannot overcome RP2350-E9 pad leakage (≈ 120 µA, holds the pad at ≈ 2.2 V > Vgs(th) max 1.45 V) while GPIO0/1 are inputs at boot / in BOOTSEL mode. A gate transient in that window (battery hot-plug with USB present couples ≈ 20 V·µs through Crss) latches the motor **on** with no firmware control, in a body-worn device. The erratum requires ≤ 8.2 k. | **Change R41/R43 to 4.7 k** (C25900, basic, already on the BOM for I2C). Must be fixed before ordering; trivial. |
| **MAJOR** | VSYS ripple at the 1 A design current: ≈ 0.5 V per channel, ≈ 1 V with both in phase, from 2 × 22 µF derated to ≈ 20 µF at 4.4 V. This rides on the rail feeding the LDO and the RM2. | Stagger the two PWM phases in firmware (free, halves it). If the real motor current is > 300 mA, add bulk (2 × 22 µF per channel, or 0805 16 V parts). Closes if the ASK answer is ≤ 300 mA. |
| **MAJOR** | D3/D4 at 1 A, 50 % duty dissipate ≈ 0.3 W in SOD-123 → Tj ≈ 90–120 °C inside rubber at 45 °C ambient (UNVERIFIED Vf and RθJA). Marginal against a 125 °C rating; fine at ≤ 300 mA motors. | Attach the B5819W sheet and recompute. If 1 A at 50 % is a real operating point, use an SMA/SMB-footprint Schottky or a lower-Vf part, or give the diode a copper pour. |
| MINOR | Rds(on) at Vgs = 3.3 V is interpolated from Fig. 5 (≈ 21 mΩ typ, ≈ 37 mΩ max est.); the datasheet guarantees only 2.5 V (48 mΩ max) and 4.5 V (32 mΩ max). Even at 48 mΩ max × 1.25 hot, P_cond = 60 mW and Tj < 65 °C. | None; noted for the reviewer. |
| MINOR | Peak gate current ≈ 21–26 mA exceeds the pad's nominal 12 mA drive-strength figure for ~100 ns per edge. The RP2350 defines that figure as a VOH/VOL spec, not a limit (p.1339); IIOVDD_MAX 100 mA is the limit. | Set GPIO0/1 to 12 mA, fast slew in firmware. Keep R40/R42 = 100 R. |
| MINOR | B5819W pinout (pin 1 = cathode on VSYS) is from parts.yaml and the KiCad SOD-123 convention, not from the datasheet. | Verify against the drawing when the datasheet is attached. |
| NOTE | FET losses at 1 A: ≈ 45 mW conduction (max, hot) + ≈ 25 mW switching → Tj ≈ 59 °C with RθJA 200 °C/W in rubber. 5× headroom on current, > 10× on power. | None. |
| NOTE | Switching edges ≈ 200–250 ns with 100 R + pad ≈ 0.5 % of the 25 kHz period. | None. |
| NOTE | No gate ESD structure in the AO3400A; the gate is internal to the board. The drain goes to the motor lead inside the cast body: no TVS, by design (not user-accessible). | Note on the MOT silkscreen per io-protection.md if the leads are ever exposed. |
| NOTE | Bulk-cap ripple current (≤ 0.5 A rms per channel) is a non-issue for MLCC; capacitance (ripple voltage) is the limit, not ripple current. | None. |
