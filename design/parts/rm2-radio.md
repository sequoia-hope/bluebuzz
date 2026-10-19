# U7 — Raspberry Pi Radio Module 2 (RM2, CYW43439) + gSPI network

Datasheet: datasheets/rm2-datasheet.pdf (Raspberry Pi Ltd, release 7, build 20/02/2026, 17 PDF pages). Read: all sections, figures 4, 6 and 7 measured from the drawings. Page numbers below are the document's footer page numbers (PDF page = footer + 1).
MPN: RMC20452T (castellated, 2.4 GHz only, Wi-Fi 4, BT 5.2, tape and reel; p.15). Production lifetime to January 2036, RRP $4, reel of 960 (table 8, p.15).
Supplier: not an LCSC part. Raspberry Pi approved resellers only (p.15). bom/parts.yaml: `lcsc: ""`, consigned at JLCPCB or hand-soldered. Stock not checked online for this audit (reseller stock, not LCSC).
Footprint: `bluebuzz-rm2:RM2` from scripts/gen_footprints.py `rm2()`, 21 castellated pads at 1.5 mm pitch, body 14.5 × 16.5 × 2.55 mm (fig. 4, p.7). Verified against fig. 6 (p.9): **one mismatch, see Land pattern**.

Group covered: U7, R80 470 Ω (DOUT → DATA), R81 10 kΩ (nIRQ → DATA), C100 10 µF + C101 100 nF on Vin (VSYS), C102 100 nF on VDDIO (3V3_SYS).

## Absolute max vs our worst case

The datasheet has **no absolute-maximum table**. It gives only operating ranges (p.10 table 2, p.11 section 2.6). The CYW43439's own abs max (Infineon) is behind the module's on-board regulators and is not reproduced; the module ranges below are therefore both the "abs max" and the operating spec we can hold the design to.

| Parameter | Datasheet limit | Our worst case | Margin |
|---|---|---|---|
| Vin, pad 16 | 3.0 – 4.8 V (table 2 p.10; §2.6 p.11). "A Vin of less than 3.2 V reduces RF performance" (p.11) | VSYS 3.0 – 4.4 V (intent.md). High end: BQ24074 OUT regulation, ≈4.4 V typ, see the charger audit for its max | High: ≥ 0.3 V OK. **Low: 0 V margin at 3.0 V; the 3.0–3.2 V band is "reduced RF"; any droop under a motor peak at an empty cell takes Vin below spec** → MAJOR |
| VDDIO, pad 14 | 1.8 V ±5 % or 3.3 V ±5 % (3.135 – 3.465 V) (p.11) | 3V3_SYS from TLV75533, 3.3 V ±1 % nominal (see rails audit for load/line terms) | OK (≈ 0.13 V each side) |
| Input high / low, 3.3 V IO | VIH ≥ 2.0 V, VIL ≤ 0.8 V (table 4 p.11) | RP2350 driving at IOVDD 3.3 V, VOH ≥ IOVDD − 0.5 V ≈ 2.8 V (host audit to confirm) | OK |
| Output high / low at 2 mA | VOH ≥ VDDIO − 0.4 V ≈ 2.9 V, VOL ≤ 0.4 V (table 4 p.11) | RP2350 input thresholds at 3.3 V IO (host audit) | OK |
| ESD | HBM 1000 V, MM 30 V, CDM 300 V (table 5 p.11) | No module pin is user-accessible; gSPI, Vin, VDDIO are all internal nets. Hand-soldering/consignment handling only | OK, but low: handle with ESD precautions (p.14 "Handling") |
| Ambient operating temperature | −30 to +70 °C, "specifications require de-rating at extreme temperatures" (table 6 p.12) | 0 – 45 °C ambient (intent.md) plus self-heating in sealed rubber with no airflow, next to the charger and motor FETs | OK on paper; the inside-the-rubber temperature is unmeasured → NOTE |
| Storage | −40 to +125 °C, RH < 60 % (table 6 p.12) | Casting cure is room temperature (VytaFlex) | OK |
| Operating humidity | < 85 % RH, non-condensing implied; "Don't expose RM2 to water or moisture" (p.12, p.14) | Sealed in cured elastomer; body is washed; the casting resin contacts the module directly | See Fine print |
| Reflow | Tp 260 °C peak, time within 5 °C of Tc 30 s, ramp-up ≤ 3 °C/s, ramp-down ≤ 6 °C/s, ≤ 8 min 25 °C to peak (table 7 p.13) | JLCPCB lead-free profile (peak ≈ 245–250 °C) or hand soldering | OK |

## Required external parts (from datasheet)

The module "requires only SPI, power, and reset signals" (p.3). Table 1 (p.5) and table 2 (p.10) are the only external-part requirements in the document:

| Datasheet requirement | Source | Ours | Status |
|---|---|---|---|
| WL_REG_ON ("Regulator on to power up CYW43") from one host GPIO to **both** pads 12 (Wi-Fi on) and 13 (Bluetooth on) | table 1 p.5, table 2 p.10 | GPIO23 → pads 12 and 13 (`RM2` dict, circuit.py) | OK |
| DATA_OUT, DATA_IN and HOST_WAKE "must share the same GPIO pin" | table 1 p.5 | all on GPIO2 (`WL_DATA`) | OK |
| gSPI Data In, pad 5: direct | table 2 p.10 | pad 5 → WL_DATA direct | OK |
| gSPI Data Out, pad 6: **through a 470 Ω resistor** | table 1 p.5, table 2 p.10 | R80 470 Ω, pad 6 → WL_DATA, 0402 C25117 basic | OK |
| nIRQ, pad 10: **through a 10 kΩ resistor** | table 1 p.5, table 2 p.10 | R81 10 kΩ, pad 10 → WL_DATA, 0402 C25744 basic | OK |
| gSPI SCLK, pad 3: direct | table 2 p.10 | GPIO3 → pad 3 | OK |
| gSPI CS, pad 9: direct, no pull-up/down specified | table 2 p.10 | GPIO25 → pad 9, no pull | OK (nothing required; see Fine print on power-up state) |
| VDDIO pad 14: 3.3 V or 1.8 V | table 2 p.10 | 3V3_SYS | OK, matches the RP2350's 3.3 V IOVDD |
| Vin pad 16: 3.0–4.8 V ("3.3 V" default) | table 2 p.10 | VSYS | OK (decision R1) |
| Grounds: pads 1, 4, 7, 11, 15, 21 | table 2 p.10 | all GND | OK |
| No connect: pads 2, 19, 20 | table 2 p.10 | left open | OK |
| GPIO0 / GPIO2 / GPIO1: pads 8 / 17 / 18, host-controlled over gSPI | table 2 p.10, p.6 | left open | OK (see Fine print) |
| Decoupling on Vin / VDDIO | **none specified anywhere in the datasheet**; the module has "supporting circuitry: power supply that allows the RM2 to operate from a single external power rail" (p.4) | C100 10 µF + C101 100 nF on Vin, C102 100 nF on VDDIO | Ours is our own engineering choice, not a datasheet value. Reasonable; placement note below |
| Pull-up / pull-down on CS, WL_ON, SCLK, DATA | none specified | none fitted | OK |

GPIO change from the defaults: "These defaults match the Pico W configuration. You can change the default GPIO assignments at build time" (p.10) and "certain lines require external components such as series resistors" (p.5). Our DATA on GPIO2 and CLK on GPIO3 instead of 24 / 29 (decision R2) is explicitly permitted at the datasheet level; the remaining constraint is the SDK's PIO program, which uses side-set for the clock and in/out pins for data so any two GPIOs work (SDK fact, not datasheet; verify against the pico-sdk `cyw43_bus_pio_spi.c` of the SDK version used).

## Calculations

- **Vin current budget.** Datasheet: TX active MCS7 at 16 dBm 271 mA, RX active 43 mA, PM1 DTIM1 1.19 mA average (p.3). No figure for 802.11b TX, Bluetooth TX, or the peak during firmware download. The CYW43439 draws more at 802.11b rates than MCS7 (Infineon figure, not in this datasheet); budget **≥ 350 mA peak** on VSYS for the radio, on top of the motors' 2 A. VSYS is the charger's power-path output so this never touches the 500 mA LDO (decision R1) — correct split.
- **Vin minimum.** Spec floor 3.0 V, "reduced RF" below 3.2 V (p.11). With a cell at 3.3 V and a 2 A motor peak through cell IR + charger pass-FET (order 100 mΩ total, see charger audit), VSYS droops ≈ 0.2 V to ≈ 3.1 V: inside spec but in the degraded band. At the intent's 3.0 V cell floor the same peak takes Vin to ≈ 2.8 V, below spec. Mitigation is firmware, not board: a low-battery cutoff for motors at ≈ 3.3 V cell, or lower motor peak current, and keep the radio bulk cap (next item) close.
- **C100 10 µF DC-bias.** CL10A106KP8NNNC, 0603 X5R 10 V. At 4.4 V bias expect roughly −25 to −35 % → ≈ 6.5–7.5 µF effective (Samsung curve; typical for 0603 X5R 10 V). Voltage rating 10 V vs 4.8 V max: 2.1× OK. C101/C102 100 nF X7R 16 V 0402: no meaningful derating at 4.4 V, 3.6× OK.
- **R80 470 Ω on DOUT.** Purpose (not stated but implied by the three-signals-on-one-pin wiring, table 1 p.5): limits contention current when host and module drive DATA at once: 3.3 V / 470 Ω = 7 mA, within either driver's capability. RC with the host input + trace (≈ 10 pF): 4.7 ns against a 32 ns bit at the "approximately 31.25 MHz" default clock (p.5), 27 ns at 37.5 MHz if the divisor is left at 2 with a 150 MHz RP2350 clock. Fine. Power: 23 mW peak during contention, 0402 63 mW OK.
- **R81 10 kΩ on nIRQ.** Weak enough that DATA traffic overrides it; nIRQ is only read when the bus is idle (the SDK's HOST_WAKE). 1.1 mW max. OK.
- **Land pattern (fig. 6, p.9, measured at 32.0 px/mm):** see next section.

## Land pattern: datasheet fig. 6 vs rm2()

Measured from fig. 6 (p.9) with the body outline as reference (14.5 × 16.5 mm = 464 × 527 px):

| Feature | Datasheet fig. 6 | Our rm2() | Match |
|---|---|---|---|
| Pad size, side columns | 2.0 long × 1.0 wide, 0.5 outside the body edge, 1.5 under it ("2.0", "0.5", "1.0" labels) | 2.0 × 1.0, centred 0.5 outside (`-hw + 0.5`) | OK |
| Pad size, bottom row | 1.0 wide × 2.0 long, 0.5 below the body edge ("0.5" label) | 1.0 × 2.0, centred 0.5 outside (`hh - 0.5`) | OK |
| Pitch | 1.5 ("1.5" label; measured 48 px) | 1.5 | OK |
| Bottom row x | first pad centre 2.75 from the left body edge ("2.75" label), symmetric, 7 pads | `-hw + 2.75 + 1.5k` | OK |
| Side columns y | **lowest side pad (pins 7 and 15) centre 1.8 mm above the body's bottom edge ("1.8" label; measured 14.70 mm from the antenna end = 1.80 from the bottom).** Top side pad (pins 1 and 21) centre therefore at 5.7 mm from the antenna end, pad top edge at 5.2 mm, 0.2 mm clear of the 5.0 mm keep-out line | pins 1/21 centre at `-hh + 5.5` (5.5 mm from the antenna end), pins 7/15 at `hh - 2.0` (2.0 from the bottom). **Pads are 0.2 mm too far toward the antenna end on all 14 side pads**, and the pad's top edge sits exactly on the keep-out line | **MISMATCH** |
| Keep-out box | 35.5 × 18.5 mm: 13.5 beyond the antenna end (30.0 − 16.5), 5.0 into the body (18.5 − 13.5), 10.5 either side ((35.5 − 14.5)/2) | depth 5.0, side 10.5, beyond 13.5 (design.yaml `radio.keepout_mm`, RM2_KEEPOUT) | OK, numbers verified |
| Courtyard | not given | body + 0.5 pad overhang | OK |

The side-column offset is a one-line fix in `rm2_pads()`: left column `y = -hh + 5.7 + 1.5k`, right column `y = hh - 1.8 - 1.5k`. The pads are 1.0 mm wide so an unfixed board would still capture the castellations with 0.8 mm overlap, but a systematic 0.2 mm error on 14 of 21 pads against the vendor's own drawing is a land-pattern mismatch and the footprint is marked `verified: yes` in parts.yaml on the strength of that drawing.

## Keep-out: datasheet fig. 6 vs ours

Datasheet text: the blue box "represents the 'keep out area', which is the minimum region around the pins that must remain free of **any metal**" (p.8); "The area around the antenna must be clear of grounding to prevent shielding and de-tuning of the antenna" (p.11); "we recommend that you follow the guidance outlined in Section 2.4" (p.6). It does not say "all layers" or "both sides" in words; "any metal" covers copper on every layer, both sides, components, and anything in the enclosure. The box is 2-D; there is no height or clearance-above-the-module figure.

Ours (route.py `antenna_keepout`, place.py `keepout_box` / `check`):
- Rule area on every copper layer, no tracks / no vias / no pour, from 1 mm above the board's top edge down to 5.0 mm into the module body (board y 77 → 83; module body top at the board edge, y 78). Verified on the routed board: no segment or via with y < 83 on any layer. **Depth 5.0 OK, all layers OK.**
- Placement check rejects any footprint, either side, whose courtyard enters the box. **Both sides OK.** The SWD pogo pads (J3, back, y ≈ −8.5) and BAT pads (J2, back, y −13.5, left of the module) are outside the box.
- Width: x from `ux − 7.25 − 10.5` = board x −11.85 to the right edge (clamped). The board is 28 mm wide, so the **top-left corner strip x −14 … −11.85 (2.15 mm wide × 5 mm tall) is outside the rule area and the In1 / In3 / In4 planes do fill it** (verified: `gnd_in1`, `vsys_pour`, `gnd_in4` have fill points at x 86.5–88.15, y < 83). This is outside the datasheet's 10.5 mm side band so it is compliant, but place.py's docstring ("the datasheet's 10.5 mm either side reaches both edges here") is wrong by 2.15 mm, and the sliver is useless copper right at the edge of the box. Recommend extending the rule area to the full board width.
- Beyond: 13.5 mm past the antenna end is off the board, inside the rubber. Nothing on the PCB can violate it, but the cast assembly can: the LiPo cell (metallised pouch), the two ERM motors (steel weights, metal cans), and their leads must stay out of a 35.5 × 13.5 mm volume above the top edge and the 10.5 mm bands beside the top 5 mm of the module. The BAT pad row is at the top of the back side, which invites running the cell leads straight through this zone. intent.md states the requirement but no drawing fixes the cell and motor positions.

## Enclosure / dielectric near the antenna (the rubber)

The datasheet says nothing about enclosures, dielectric loading, overmoulding or potting. Its only environmental statements are the metal keep-out (p.8, p.11), the humidity/moisture limits (p.12, p.14) and "RM2 is supplied fully tested and tuned... doesn't require further RF tuning" (p.14), which assumes the fig. 6 footprint in air. The antenna is an inverted-F on the module PCB (p.6), tuned for a free-space load. Casting it in polyurethane (relative permittivity ≈ 3–4, loss tangent of the order 0.02–0.05 at 2.4 GHz for cast PU, plus water uptake over time) will:
- shift the resonance downward (the IFA sees a higher effective permittivity), reducing match at 2.4–2.48 GHz;
- add dielectric loss in the near field, reducing efficiency;
- both grow with rubber thickness over the antenna; a few mm matters.
Expect several dB of range loss, consistent with intent.md's "detuned, expected range loss, to be measured". The datasheet gives no way to retune (the module is sealed, "fully tested and tuned"). Antenna patterns are on the Product Information Portal (PIP), account required (p.6). Mitigation options are mechanical only: thinnest possible rubber over the antenna end, antenna end at the body surface (as placed), no metal in the box. Document the measured RSSI / throughput in air vs cast before committing to the body geometry.

## Fine print / gotchas

- "RM2 is exclusively designed for Raspberry Pi microcontrollers and is not compatible with other platforms" (p.5); firmware "is precompiled and can't be modified" (p.6). RP2350A host: OK. The CYW43 driver and BTstack are licensed for use with RM2 (p.6).
- Build requires `PICO_CYW43_SUPPORTED` (p.5); the board header must override `CYW43_DEFAULT_PIN_WL_DATA_OUT/_DATA_IN/_HOST_WAKE` (2) and `_WL_CLOCK` (3) (decision R2). WL_REG_ON 23 and CS 25 are the defaults.
- "SPI clock defaults to approximately 31.25 MHz when the system clock is 125 MHz... If the system clock frequency is changed, you might need to update the PIO clock divisor or modify the PIO program" (p.5). The RP2350 default sysclk is 150 MHz; use the Pico 2 W board header as the model, which the SDK already supports.
- Three module GPIOs (pads 8, 17, 18) are readable/controllable "only when the chip is powered and communication is active" (p.6). On the Pico W they are LED, SMPS power-save and VBUS sense; on RM2 "available for general-purpose use". We leave them open: the SDK's Pico W-style init may toggle GPIO1 (SMPS mode) and read GPIO2 (VBUS) with no effect here. Do not use `cyw43_arch_gpio_get(2)` as a VBUS detect; USB presence is the charger's /PGOOD (decision R5).
- Power-up state: the datasheet gives no reset timing or required default level for WL_ON / CS. The RP2350's GPIOs come up as inputs with pull-downs (host audit to confirm for GPIO23/25), so WL_ON is low (module off) until the SDK raises it, and CS is low meanwhile, which is harmless with the module unpowered.
- Pads 12 and 13 tied together means Wi-Fi and Bluetooth cannot be powered independently. The SDK expects exactly this (table 1).
- "Device compatibility. The connection of incompatible devices to the RM2 can compromise regulatory compliance" (p.14).
- Moisture: "Don't expose RM2 to water or moisture" (p.14), operating RH < 85 % (p.12). Casting puts uncured PU in direct contact with the module and, under vacuum degassing, draws it under the RF shield can and around the crystal and antenna. Cured PU is a sealant, so steady-state is fine; the cure chemistry (moisture-sensitive two-part PU, mild exotherm) is not an operating condition the datasheet contemplates. No rework after casting (intent.md), so the radio must be fully link-tested before casting.
- Heat: "Don't expose RM2 to heat" (p.14); 70 °C ambient max with de-rating at extremes (p.12).
- Reflow: "temperature measurements should be taken at the top centre surface (live-bug orientation)"; dead-bug reflow must hold Tp within ±2 °C (p.12). We reflow live-bug (module on top of our board) or hand-solder: no issue. The 260 °C classification profile "isn't intended to specify a board assembly profile" (p.13).
- ESD HBM 1000 V only (table 5 p.11): below the usual 2 kV. Pins are internal; handling only.
- Regulatory / modular certification (p.14): full modular approval in EU, UK, USA, Canada; "manufacturers of host devices in these regions can integrate RM2 into their product with minimal additional testing". Not modular in India or Malaysia. Test reports, certifications and "integration test software" are on PIP (p.14). The datasheet does not list the grant conditions (antenna as certified, RF-exposure separation, co-location, labelling). Two points matter here even though intent.md says no formal compliance: (1) the module is certified with its antenna in the fig. 6 configuration, and embedding it in a dielectric body changes the antenna, which a certification body would treat as a change to the certified configuration; (2) a device used against or inside the body is "portable" in FCC terms (< 20 cm), where a mobile-class modular grant does not cover RF exposure without SAR evaluation. Hobby device, single user: NOTE, not a design change.
- Package marking: product code, FCC ID and IC ID are on the shield can (p.8); they end up inside the rubber, invisible. Irrelevant without formal compliance; would matter for a product.

## Layout guidance from datasheet

- "For optimal RF performance, RM2 requires a good ground plane. Connect the ground of RM2 to the ground of the host system. The better the ground connections are, the lower the inductance, and the better the RF performance. The area around the antenna must be clear of grounding to prevent shielding and de-tuning of the antenna." (p.11). Ours: six GND pads (1, 4, 7, 11, 15, 21) each with a via in or beside the pad to the In1 plane (route.py `gnd_pad_vias`), continuous In1 and In4 GND planes under the body below the keep-out line, F/B GND pours. Good.
- Keep-out per fig. 6 (p.9): see above. Nothing else: no trace-length, impedance or routing guidance for gSPI, no decoupling placement guidance.
- Ours beyond the datasheet: R80 spans pads 5 and 6 right at the module (2 mm), R81 3 mm from pad 10, C102 1.9 mm from pad 14: good. C101 100 nF is ≈ 4.6 mm from Vin pad 16 (right column faces the board edge with 1.35 mm to spare, so the cap sits below the bottom row) and C100 10 µF is ≈ 15 mm away on the left of the module, fed through the In3 VSYS pour. circuit.py's comment "Vin, at pin 16" is not what the placement does. For 271 mA+ TX bursts the module's own on-board supply and the 100 nF nearby make this workable, but the 10 µF should be the nearest thing to pad 16 that fits: the slot below pad 14/16 where C101/C102 are, or the back side under pad 16 if a via-in-pad is acceptable there.
- DATA is a three-way net (pad 5 direct, pad 6 via R80, pad 10 via R81) running ≈ 11 mm to GPIO2 at the RP2350's top-left; keep it and CLK short and away from the motor PWM and the VREG_LX inductor. No stubs beyond the two resistors.
- Height 2.55 mm (fig. 4 p.7) is the tallest part on the front; no clearance-above figure in the datasheet. Rubber directly over the shield can is fine.

## Open questions

1. Land pattern: fix the 0.2 mm side-column offset (`rm2_pads()` 5.5 → 5.7 and 2.0 → 1.8) and regenerate; confirm against a physical module before ordering (the datasheet calls its dimensions "approximate", p.8).
2. Where do the cell, the motors and their leads sit in the casting relative to the 35.5 × 13.5 mm zone above the top edge? Needs a drawing; intent.md states the rule but nothing enforces it off-board.
3. Rubber thickness over the antenna end, and a plan to measure in-air vs cast RSSI/throughput before fixing the body geometry.
4. VSYS low end: firmware motor cutoff / current limit so Vin stays ≥ 3.2 V (preferably) and never < 3.0 V under motor peaks. Coordinate with the charger and rails audits on the actual droop.
5. Peak current for 802.11b TX, Bluetooth TX and firmware download is not in this datasheet; take it from the CYW43439 datasheet or measure; the VSYS budget currently assumes 271–300 mA.
6. PIP account: antenna patterns (p.6) and the modular-grant conditions / test reports (p.14), if the radio's in-rubber behaviour or any compliance question is pursued.
7. Verify in the SDK version used that the PIO gSPI program accepts DATA = GPIO2, CLK = GPIO3 (non-default, non-adjacent), and that the 150 MHz RP2350 clock divisor is handled (Pico 2 W header as reference).
8. Extend the `antenna_keepout` rule area to the full board width and correct the place.py docstring.
9. Sourcing: RM2 from an approved reseller, quantity and lead time; consigned to JLCPCB or hand-soldered (parts.yaml). ESD handling for hand assembly given the 1 kV HBM rating.

## Findings

**BLOCKER**
- B1. Land pattern mismatch: the 14 side-column pads are 0.2 mm closer to the antenna end than the datasheet's fig. 6 (p.9: lowest side pad centre 1.8 mm from the body's bottom edge, ours 2.0 mm; top pad centre 5.7 mm from the antenna end, ours 5.5 mm, with the pad edge on the keep-out line instead of 0.2 mm clear). Bottom row, pad sizes, pitch and overhang match. One-line fix in `rm2_pads()`; regenerate and re-run DRC.

**MAJOR**
- M1. Vin low-end margin is zero: VSYS worst case 3.0 V equals the module's floor (p.10/p.11) and sits inside the "reduced RF performance below 3.2 V" band; a motor peak at a low cell takes Vin below spec. Needs a firmware low-battery motor cutoff / current limit and the rails audit's droop number. No board change if those hold.
- M2. The 13.5 mm "beyond" and 10.5 mm "side" bands extend off the board into the rubber; the cell, motors and leads have no fixed positions that respect them, and the BAT pad row at the top edge invites leads through the zone. Needs a casting drawing.
- M3. The antenna will be embedded in polyurethane; the datasheet is silent on dielectric loading, the module is tuned for free space and cannot be retuned (p.14). Expect detuning and loss; measure before freezing the body. (Design-level acceptance already noted in intent.md; recorded here as the datasheet-level consequence.)

**MINOR**
- m1. C100 10 µF is ≈ 15 mm from Vin pad 16 (through the In3 pour), C101 100 nF ≈ 4.6 mm; circuit.py's "at pin 16" comment does not match the placement. Move the 10 µF closer to pad 16 if it can fit; otherwise accept and note.
- m2. The RF keep-out rule area stops 2.15 mm short of the left board edge; the In1/In3/In4 planes fill that corner. Compliant with the 10.5 mm band but pointless copper beside the antenna; extend to the full width and fix the place.py docstring.
- m3. The datasheet gives no peak current for 802.11b / BT TX / firmware download; the VSYS budget uses the MCS7 figure (271 mA, p.3). Budget ≥ 350 mA until measured.

**NOTE**
- n1. No absolute-maximum table exists in this datasheet; operating ranges were used as the limits.
- n2. No decoupling, pull-up/down, reset-timing or gSPI routing guidance exists; our values are engineering choices, documented above.
- n3. ESD HBM 1000 V (table 5 p.11): internal pins only, but handle with precautions during hand assembly.
- n4. Operating RH < 85 % and "don't expose to moisture" (p.12, p.14): cured PU seals the module; the uncured casting contacts it directly and vacuum degassing draws resin under the shield can. Fully test the radio link before casting (no rework after).
- n5. Modular approval (EU/UK/USA/Canada, p.14) assumes the certified antenna configuration and, for a body-contact device, does not cover RF exposure; grant conditions are on PIP, not in the datasheet. Hobby, no formal compliance: recorded only.
- n6. Module GPIO0/1/2 (pads 8/17/18) left open; the SDK's Pico W defaults may drive/read them harmlessly. Don't use GPIO2 as VBUS sense.
- n7. gSPI on non-default GPIO2/3 is permitted by the datasheet (p.10); the SDK PIO program's pin constraints are to be verified against the SDK version used.
- n8. Reflow profile (table 7 p.13) is within JLC's lead-free process; live-bug orientation.
- n9. Production lifetime January 2036 (table 8 p.15); not on LCSC, consigned or hand-soldered.
