# J1/U10 — USB-C front end (receptacle, ESD array, CC pull-downs, series termination)

Block 1 of `scripts/circuit.py`: J1 TYPE-C-31-M-12 receptacle → U10 USBLC6-2P6 ESD array
(D+ in on pin 1 / out on pin 6, D− in on 3 / out on 4, VBUS pin 5, GND pin 2) + C2 100 nF on
VBUS at the array → R3/R4 27 R at the RP2350's USB_DP/USB_DM (nets USB_DP_C / USB_DM_C).
R1/R2 5.1 k from CC1/CC2 to GND. VBUS continues to the BQ24074 IN pin (Block 2). The USB-C
is the only connector on the board and the only user-accessible metal (intent.md).

| Ref | Part | Datasheet | LCSC | Footprint |
|---|---|---|---|---|
| J1 | TYPE-C-31-M-12 (HRO), 16-pin USB 2.0 receptacle, mid-mount/top-mount hybrid | **NOT in `datasheets/`** (LCSC blocked the fetch). Everything receptacle-specific is **UNVERIFIED** | C165948 (extended) | `Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12` (KiCad library; 3D offset override in library/3d/overrides.yaml) |
| U10 | USBLC6-2P6, SOT-666 | **NOT in `datasheets/`** (ST blocked the fetch). Part-specific numbers **UNVERIFIED** | C15999 | `Package_TO_SOT_SMD:SOT-666`, pins 1=IO1 2=GND 3=IO2 4=IO2 5=VBUS 6=IO1 |
| C2 | 100 nF X7R 16 V 0402 | — | C1525 | C_0402 |
| R1, R2 | 5.1 k 1 % 0402 | — | C25905 (basic) | R_0402 |
| R3, R4 | 27 R 1 % 0402 | — | C25100 (extended) | R_0402 |

Related, read for this audit: `design/datasheets/hardware-design-with-rp2350.pdf` §USB
(p.16), `design/datasheets/rp2350-datasheet.pdf` §14.9 (p.1335–1339), and the BQ24074 IN
pin limits in `design/datasheets/bq24074.pdf` (p.8, 10, 12).

Operating conditions (intent.md): USB 2.0 full-speed device; VBUS 5 V nominal, 5.5 V worst
(4.75–5.5 V per USB 2.0 / Type-C for a 5 V source); 1 A input limit (BQ24074 ILIM); hot-plug;
user-handled → ESD; 0–45 °C.

## What the design assumes about J1 (UNVERIFIED until the drawing is attached)

- 16-pin "USB 2.0 only" Type-C receptacle: A1/B1/A12/B12 GND; A4/B4/A9/B9 VBUS; A5 CC1;
  B5 CC2; A6/B6 D+; A7/B7 D−; A8/B8 SBU1/SBU2 (left open in circuit.py — correct, a USB 2.0
  UFP has no use for them); S1 = shell. No SuperSpeed pins (A2/A3/A10/A11/B2/B3/B10/B11 are
  absent in the 16-pin variant).
- The two D+ pins (A6, B6) and the two D− pins (A7, B7) are **tied together on the board**
  so either plug orientation works. circuit.py does this (both map to USB_DP / USB_DM).
  In a 16-pin receptacle they are physically adjacent, so the join is a short stub, which is
  fine at 12 Mb/s.
- VBUS pads paired (A4+A9, B4+B9): all four on the VBUS net. Each contact is rated 1.25 A
  class in the USB-C spec; four in parallel for our 1 A limit → fine with margin.
- GND pads (four) plus the shell tabs: all on GND. The shell is tied directly to GND
  (decision: direct, not RC — the board's ground is the only reference and the shell is the
  user-touched metal; a direct low-inductance shell-to-plane path is what the ESD array
  needs to clamp against).
- Shell / pegs: KiCad's HRO footprint has two through-hole shell tabs and two pegs; the
  tabs must be on GND with plane connection on every layer they pass through (via-in-plane).
  Mechanical: 3.2 mm height, mouth flush with the bottom edge (intent.md). **Verify from the
  drawing**: the mouth overhang vs the board edge for "flush", the pad-to-edge distance, and
  that the KiCad footprint variant (HRO TYPE-C-31-M-12) is the same as C165948.
- Contact rating: Type-C receptacles are 5 V/3 A class on VBUS; current per our ILIM is 1 A.
- ESD: receptacle shells are typically rated to survive IEC 61000-4-2 ±8 kV contact; the
  pins are not, which is what U10 is for.

## What the circuit needs from U10 (USBLC6-2P6 class, UNVERIFIED)

Topology: a low-capacitance rail-to-rail diode array. Each I/O line has a steering diode to
the VBUS pin and one to GND; a TVS (≈ 6 V breakdown) sits between VBUS and GND. An ESD
strike on D+ steers through the diode into VBUS and is clamped by the TVS (positive) or
through the GND diode (negative). The two I/O pins per line (1/6, 3/4) are internally one
node: the trace enters on one and leaves on the other so the strike passes *through* the
array's pads rather than past a stub.

Requirements from the circuit, and the class values to confirm from the datasheet:

| Need | Why | Expected (UNVERIFIED) |
|---|---|---|
| Working voltage on VBUS pin ≥ 5.5 V | VBUS worst case 5.5 V must not leak through the TVS | VRM 5.25 V — **check leakage at 5.5 V**; ST specs IRM at 5.25 V. At 5.5 V the TVS (6 V min breakdown) may draw tens of µA, harmless to a 1 A charger input but confirm |
| Clamp voltage on D+/D− below the RP2350 USB pad abs max | RP2350 USB_DP/DM are FT pads: abs max 5.5 V with IOVDD present (Table 1680, p.1335), HBM 2 kV (p.1335). An IEC 8 kV strike is not an HBM 2 kV strike | VCL ≈ 17 V at 8 kV IEC peak on the line (dynamic), ≈ 6–7 V TVS clamp. The 27 R R3/R4 and ~30 mm of trace add series impedance; the residual at the RP2350's own pad diodes is what the pads must absorb. This is the standard USB 2.0 arrangement and is what the Raspberry Pi design guide uses |
| ESD rating ≥ IEC 61000-4-2 level 4 | user-handled connector, intent.md | ±15 kV air / ±8 kV contact class (USBLC6-2: "15 kV air, 8 kV contact" per ST — confirm) |
| Line capacitance ≤ ~5 pF, matched | USB 2.0 FS edges 4–20 ns; the hub/host tolerates ~ 50 pF per line, but matching matters for the differential eye | ≈ 3.5 pF per line, 0.05 pF mismatch class |
| Peak pulse current | TVS absorbs the VBUS-side strike | ≈ 5 A 8/20 µs class — this is an **ESD** part, not a surge part (below) |
| Pinout | circuit.py: 1=IO1 (D+ in) 6=IO1 (D+ out) 3=IO2 (D− in) 4=IO2 (D− out) 5=VBUS 2=GND | matches the ST USBLC6-2P6 (SOT-666) pin table from memory — **confirm**, the SC6 (SOT-23-6) variant has a *different* pinout (1=IO1, 2=GND, 3=IO2, 4=IO2, 5=VBUS, 6=IO1 for SC6 too, but confirm the P6 pin 1 marking/orientation on the SOT-666 drawing) |

C2 100 nF on VBUS at pin 5: gives the array's VBUS node a local low-impedance return so the
steered ESD current has somewhere to go in the first nanoseconds before the cable/charger
responds; also the first HF decoupler on VBUS. 16 V rated vs 5.5 V (2.9×) — OK; vs the
BQ24074 OVP threshold 10.8 V max (p.12) still OK. It would be over-rated only if 20 V PD
were ever applied, which the BQ24074's 28 V abs max survives but C2 does not (NOTE below).

## Absolute max vs our worst case

| Parameter | Abs max | Our worst case | Margin |
|---|---|---|---|
| BQ24074 IN (p.10, Table 8.1) | 28 V; "input can accept voltages up to 26 V without damage but operation is suspended" (p.8) | 5.5 V normal; hot-plug overshoot (below) ≈ 7 V; a mis-applied 9/12/15/20 V PD brick cannot happen with Rd-only CC (no PD negotiation) but a broken brick could | OK; OVP at 10.2–10.8 V (p.12) suspends operation above that |
| BQ24074 IN operating (p.10) | 4.35–10.2 V ('74 variant) | 4.75–5.5 V | OK |
| BQ24074 IIN (p.10) | 1.5 A | 1 A (ILIM, R11 1.62 k) | OK |
| RP2350 USB_DP/DM (FT pad) | 5.5 V with IOVDD ≥ 3.3 V (p.1335) | 3.3 V signalling; ESD residual after U10 + 27 R | OK for normal; ESD depends on U10 clamp (UNVERIFIED) |
| RP2350 ESD | HBM 2 kV, CDM 500 V class (p.1335) | IEC 8 kV contact at the connector | **not OK alone** — U10 required, present |
| C2 16 V | 16 V | 5.5 V / 10.8 V OVP edge | OK (2.9× / 1.5×) |
| C10 10 µF **10 V** (Block 2, charger audit) | 10 V | 5.5 V normal, up to 10.8 V before the charger's OVP acts | 1.8× normal; **no margin during an OVP event** — cross-reference to the charger audit |
| R1/R2 5.1 k 0402 | 62.5 mW, 50 V | Rp 3 A source: 330 µA → 1.68 V → 0.55 mW; a non-compliant 5 V on CC: 4.9 mW | OK |
| R3/R4 27 R 0402 | 62.5 mW | 3.3 V/(27+27+45 Ω driver) transients only; DC ≈ 0 | OK |
| CC1/CC2 pins | Type-C: CC must survive 5.5 V (vCC abs); PD-capable cables may put VCONN (5 V, up to 1 W) on the unconnected CC | 1.68 V normal (Rp 3 A); 5 V if a cable's VCONN lands on it: 5 V/5.1 k = 1 mA, 4.9 mW in a 62.5 mW resistor | OK (a UFP with Rd only is exactly what the spec expects) |

## Calculations

### CC pull-downs for a UFP (sink)

USB Type-C spec (release 2.x, §4.5.1.2.1 / Table 4-25): a UFP presents **Rd = 5.1 kΩ ±10 %**
on each CC pin to GND. The source presents Rp (or a current source) and reads the resulting
CC voltage; the sink reads the same voltage to learn the source's advertised current:

| Source advertisement | Rp (to 5 V) / Ip | CC voltage at Rd 5.1 k | Sink may draw |
|---|---|---|---|
| Default USB | 56 k / 80 µA | ≈ 0.41 V | 500 mA (USB 2.0) |
| 1.5 A | 22 k / 180 µA | ≈ 0.92 V | 1.5 A |
| 3 A | 10 k / 330 µA | ≈ 1.68 V | 3 A |

- **5.1 k is the right and only value for a sink regardless of how much current it wants**;
  the sink's capability is not advertised through Rd. R1/R2 5.1 k 1 % → correct.
- Both CC pins need their own Rd (the cable connects only one of them; which one depends on
  plug orientation). Two separate resistors, never one shared → correct in circuit.py.
- The 5.1 k must go **straight to GND** with nothing else on the node: a CC pull-down that
  sees capacitance > 100 pF class or any other load confuses source detection. Nothing else
  is on CC1/CC2 → OK.
- What the design does *not* do: read the CC voltage. The RP2350 has no CC connection, so
  firmware can't tell a 500 mA source from a 3 A one; the BQ24074 pulls up to 1 A (ILIM)
  from any 5 V source. From a strict USB 2.0 host port (500 mA) or a default-Rp Type-C port
  that is a spec violation that in practice is tolerated by phone chargers and most hosts
  (the BQ24074's VIN-DPM folds back if the source sags, p.27 class behaviour — the charger
  audit covers it). Legacy USB-A chargers over an A-to-C cable present Rp = 56 k (default)
  and supply whatever they can. MINOR below; a CC ADC tap (two 1 M dividers into spare ADC
  pins) would let firmware honour the advertisement, or ILIM could be set to 500 mA.
- Dead battery: with Rd always present on both CC pins, a source sees a sink even with the
  board unpowered → VBUS is supplied → the charger starts. Correct for a dead-battery device.

### USB 2.0 full-speed series termination and trace impedance

- R3/R4 27 R: required by the RP2350 (hardware design guide p.16: "these I/Os do require
  27 Ω series termination resistors ... placed close to the chip, in order to meet the USB
  impedance specification"). The RP2350's internal pull-ups (RPU2 0.87–1.55 k, Table p.1337)
  provide the FS speed indication; no external 1.5 k → none in circuit.py. Correct.
- Why 27 R: the USB 2.0 spec wants the driver output impedance in 28–44 Ω; the RP2350's
  driver plus 27 R lands in that window. Keep 27 R, 1 %, at the chip (R3/R4 are placed at
  U1 per architecture.md).
- Differential impedance target **90 Ω ±15 %** (USB 2.0 §7.1.1.3). FS edges are 4–20 ns
  (≈ 1.2–6 m of trace per edge), and the on-board run is ≈ 30–40 mm, so reflections settle
  within the edge and the eye is not at risk even at 70 or 110 Ω; still, route it as a pair.
  On JLC06161H-3313 the L1→L2 (GND) prepreg is ≈ 0.1 mm, so 90 Ω differential comes out
  near 0.1 mm trace / 0.15 mm gap (JLC's calculator; `nets.csv` carries the final numbers,
  the router uses them). The Raspberry Pi guide's 0.8 mm / 0.15 mm figure is for a 2-layer
  1 mm board and does not apply here.
- Pair rules for `nets.csv`: USB_DP/USB_DM (receptacle → U10 → R3/R4) and USB_DP_C/USB_DM_C
  (R3/R4 → U1): length-matched within 1 mm (≈ 7 ps; irrelevant at FS but free), no stubs
  other than the A6/B6 and A7/B7 pad joins, solid GND (In2) beneath for the whole run, no
  plane splits, vias in pairs if the pair changes layer. The D+/D− stub at the receptacle
  (two pads tied) is ≈ 1 mm: fine.
- U10 is in-line: D+ enters pin 1 and leaves pin 6; D− enters pin 3 and leaves pin 4. The
  router must honour that (both pins are on the same net, so it could legally route
  receptacle → pin 6 → pin 1 and on; or bypass the part entirely with pin 1 and 6 as stubs).
  Layout item below.

### ESD path and clamp budget

IEC 61000-4-2 contact 8 kV: 30 A peak in < 1 ns, ≈ 16 A at 30 ns. The strike on D+ at the
receptacle pad sees, in order: ≈ 2–3 mm of trace → U10 pin 1 → steering diode → VBUS node
(C2 + the TVS) → GND via(s) → plane. Residual on the line = TVS clamp + diode drop + L × di/dt
of the loop. With a 2 mm × 2 mm loop (≈ 2 nH) and 30 A/ns, L·di/dt ≈ 60 V for the first
nanosecond: **the ground loop from U10 pin 2 to the plane and from C2 to the plane dominates
the residual, not the part's VCL.** Layout, not selection, is the lever. Downstream the
27 R + the RP2350 pad diodes handle what is left; this is the arrangement every RP2040/RP2350
reference design uses.

VBUS ESD: U10's internal TVS clamps the VBUS pin too (pin 5), which protects the BQ24074 IN
(28 V abs max) from the strike's fast edge. The charger's 10 µF (C10) absorbs the slower part.

### VBUS hot-plug and surge

- Hot-plug overshoot: cable L ≈ 0.5–1 µH (1 m) into C2 100 nF + C10 10 µF + C13 100 nF ≈
  10.2 µF; f = 1/(2π√(LC)) ≈ 50–70 kHz; Q is set by the cable's ≈ 0.2–0.4 Ω and the source's
  output impedance. Undamped worst case is 2 × 5.5 = 11 V; realistic with a cable and a
  regulated adapter is 6–7 V. **BQ24074 IN survives 28 V; the OVP (10.2–10.8 V, 50 µs
  deglitch, p.12) ignores a sub-50 µs ring.** The weakest part on VBUS is **C10 at 10 V**
  (charger audit), not the front end.
- Surge (IEC 61000-4-5) is not a requirement (intent.md: no formal compliance, indoor
  personal device); U10's ≈ 5 A 8/20 µs TVS is an ESD part and would not survive a real
  surge. Nothing on the board does; acceptable and recorded.
- What protects VBUS beyond the array: the BQ24074's 28 V abs max, 10.5 V OVP (operation
  suspended, OUT connected to VBAT), 1.5 A IIN max and its 1 A ILIM/VIN-DPM current limiting;
  the only exposure is MLCC voltage ratings during an OVP event. There is no fuse: the
  charger's input current limit is the short-circuit protection for VBUS on this side, and
  the source's own limit for the cable side.
- Inrush: 10.2 µF of ceramic on VBUS at 5 V hot-plug is a ≈ 50 µC charge pulse; the Type-C
  spec allows sinks up to 10 µF on VBUS at connect (vBus capacitance limit for a sink) —
  **we are right at it** (10.2 µF); fine in practice, NOTE below.

### Shell and chassis

Shell → GND directly (four pads + two shell tabs). Decision logged here: direct bond. The
board has no separate chassis; the user's hand on the rubber body is not referenced to
anything; the shell is the ESD discharge path and must be the lowest-impedance one.
Alternative (shell via 1 nF ‖ 1 M to GND, the "isolated chassis" pattern) rejected: it would
raise the shell above the plane during a strike and push the energy into the pins instead.

## Fine print / gotchas

- The 5.1 k on both CC pins **must not** be shared or replaced by a single resistor; a
  source-side cable with VCONN may put 5 V on the unused CC pin (p. Type-C §4.5.1), which
  the 5.1 k 0402 tolerates (4.9 mW).
- SBU1/SBU2 (A8/B8) unconnected: correct. They carry nothing for USB 2.0 and are only
  driven in alt modes we never negotiate.
- Both D+ pads and both D− pads must be tied (parts.yaml note); a receptacle that only
  connects one orientation would appear to "work half the time".
- USBLC6-2 pass-through: a trace that enters and leaves on the *same* pin (treating pin 6 as
  an unconnected duplicate) defeats the purpose; both pins are in the netlist, so DRC will not
  catch a bypass. Check the routed board visually.
- The RP2350's USB pads are FT (5.5 V tolerant **only while IOVDD is present**, p.1335).
  With the board off (no battery, USB plugged), IOVDD is up as soon as VBUS → OUT → LDO
  comes up, which precedes USB enumeration; OK. Reverse order (IOVDD off, USB signalling
  present) does not occur because the host only signals after VBUS.
- The hardware design guide (p.16) wants the 27 R "placed close to the chip" — not at the
  connector. architecture.md places R3/R4 at U1. Correct.
- The guide's ground reference remark (p.16): a solid, uninterrupted ground area under the
  USB pair for its entire length. In2 is a full GND plane here; keep the USB pair off any
  In2 void and away from the VSYS pour's vias.
- ESD arrays have a small leakage at working voltage that rises with temperature; at 45 °C
  it is µA-class and irrelevant to a 1 A charger.
- USBLC6-2P6 vs USBLC6-2SC6: same function, different package (SOT-666 vs SOT-23-6) — the
  footprint in parts.yaml is SOT-666, which matches the "P6" suffix. Confirm pin 1 orientation
  on the drawing (SOT-666 pin 1 is at the marked corner; the KiCad footprint follows JEDEC).

## Layout guidance (for place.py / route.py)

- Order along the signal path, nothing in between: **J1 pads → U10 (≤ 3 mm from the D+/D−
  pads) → pair → R3/R4 at U1 → U1 pins 51/52.** U10's GND pin 2 and C2's GND end each get
  two vias straight down to In2.
- C2 within 1 mm of U10 pin 5; VBUS from the receptacle pads to U10 pin 5 and on to the
  charger as a short, wide trace (1 A: ≥ 0.3 mm 1 oz; `nets.csv`).
- D+/D−: differential pair, 90 Ω per `nets.csv`, solid In2 GND beneath, matched, no stubs
  (the receptacle's two-pad join and the U10 pass-through are the only allowed ones).
- CC1/CC2: R1/R2 within 2 mm of the A5/B5 pads, to GND with their own via. Keep the CC
  traces short and away from the D± pair (CC is DC; coupling is harmless but the pads are
  neighbours).
- Receptacle: all four GND pads and both shell tabs on the plane with via-in-plane; the
  mouth flush with the bottom edge (verify overhang from the drawing); keep-out for the
  shell tabs on inner layers; no other parts within ≈ 1.5 mm of the shell tabs (JLC
  assembly, hand-solderable).
- Keep the receptacle and VBUS run at the bottom edge, away from the top-edge antenna
  keep-out (design.yaml rf keep-out; decision log).
- Silkscreen at the connector (io-protection.md): "USB-C 5V 1A  ESD".

## Open questions

1. **TYPE-C-31-M-12 datasheet / drawing** — not downloadable; the user must attach it.
   Verify: 16-pin pin map against circuit.py, VBUS contact rating, shell-tab geometry vs the
   KiCad HRO footprint, mouth overhang for the flush-edge placement, ESD rating of the shell,
   LCSC C165948 stock (extended part, fee).
2. **USBLC6-2P6 datasheet** — not downloadable; the user must attach it. Verify: SOT-666 pin
   map and pin 1 mark, VRM and IRM at 5.25 V (and leakage at 5.5 V), VBR, VCL at 8 kV IEC,
   IEC 61000-4-2 level, line capacitance, IPP, Tj max, LCSC C15999 stock.
3. Should firmware know the source's current advertisement (CC ADC tap) or should ILIM drop
   to 500 mA for strict-USB compliance? (MINOR finding; the charger audit owns ILIM.)
4. Is the user content with no surge protection on VBUS (ESD only)? Consistent with
   intent.md's "no formal compliance"; recorded as a decision, not a defect.
5. Sourcing: parts.yaml has "verified: yes/api" with no stock counts or dates for J1, U10,
   R3/R4 (27 R is an *extended* part — consider 22 R or 33 R if a basic 27 R is unavailable;
   the RP2350 guide specifies 27 R, so prefer paying the fee). Record before the gate.

## Findings

| Rank | Finding | Action |
|---|---|---|
| **MAJOR** | Two of the three datasheets for this block (J1 receptacle, U10 ESD array) are missing; every receptacle- and array-specific number above is UNVERIFIED. The pin maps in circuit.py come from parts.yaml notes, not from drawings. The gate cannot be signed without them. | User attaches both datasheets; re-check the two pin maps and the five UNVERIFIED array parameters. |
| MINOR | The sink draws up to 1 A (ILIM) from any 5 V source without reading the CC advertisement, which a default-Rp or USB 2.0 host port rates at 500 mA. Tolerated in practice; the charger's VIN-DPM handles a sagging source. | Either accept (log in decisions.md) or add a CC voltage tap to an ADC pin, or set ILIM to 500 mA. Charger audit's call. |
| MINOR | C10 (charger block) is a **10 V** MLCC on VBUS; it has 1.8× margin at 5.5 V but none during a BQ24074 OVP event (10.2–10.8 V) or a hard hot-plug ring. C2 at 16 V is fine. | Cross-reference to the charger audit: consider a 16 V 10 µF (0805) for C10. |
| MINOR | VBUS capacitance at the connector ≈ 10.2 µF, right at the Type-C sink limit (10 µF) for inrush at attach. | None required; note for the charger audit if C10 grows. |
| NOTE | R1/R2 5.1 k 1 % on each CC pin to GND is exactly the Type-C Rd for a UFP; the value does not depend on the current wanted (sink capability is not advertised via Rd). Both pins need their own resistor; they have them. Correct. | None. |
| NOTE | R3/R4 27 R at the RP2350 per the hardware design guide p.16; no external 1.5 k pull-up needed (internal). Correct. | None. |
| NOTE | 90 Ω differential for USB_DP/DM and USB_DP_C/DM_C: at 12 Mb/s over ≈ 40 mm it is not critical, but `nets.csv` must carry the pair (width/gap for the 3313 outer prepreg, length match, solid In2 beneath, no stubs). | Add to `nets.csv`; the generated route must pass D+ through U10 pin 1→6 and D− through 3→4, not bypass the array. |
| NOTE | Protection on VBUS beyond the array is the BQ24074 itself: IN abs max 28 V (p.10), 26 V survivable with operation suspended (p.8), OVP 10.2–10.8 V (p.12), IIN 1.5 A max, ILIM 1 A. No fuse, no surge TVS, by design (intent.md: no formal compliance). | Log the "ESD only, no surge" decision in decisions.md. |
| NOTE | Shell bonded directly to GND through four pads and two tabs; decision recorded here. | Via-in-plane on the shell tabs. |
| NOTE | The ESD residual at the RP2350 is dominated by the U10/C2 ground-loop inductance, not the array's clamp spec: two vias each, ≤ 3 mm from the receptacle pads. | place.py / route.py constraint. |
