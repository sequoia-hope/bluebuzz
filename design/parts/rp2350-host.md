# U1 — RP2350A host block (core buck, decoupling, crystal, QSPI flash, USB series, RUN/BOOTSEL, SWD, battery ADC)

Status: DRAFT audit by Claude, 2026-10-17. Independent re-read still required (review-protocol).

Datasheets read:
- `design/datasheets/hardware-design-with-rp2350.pdf` — "Hardware design with RP2350", release 3, build 20 Aug 2026 (cited below as **HDG p.N**, printed page numbers). Read in full (25 pages, including the Appendix A schematic, which was rendered and read at 300 dpi).
- `design/datasheets/rp2350-datasheet.pdf` — RP2350 Datasheet, build 1 Oct 2026, 1371 pages (cited as **DS p.N**, printed page numbers; PDF page = printed + 1). Read: §6.1 Power supplies, §6.3 Core voltage regulator incl. §6.3.7 application circuit and §6.3.8 external components / PCB layout (pp.400–411); §8.2 XOSC (pp.506–509); §12.4 ADC (pp.963–969); §12.7.1–12.7.3 USB (pp.1058–1060); §12.14.1–12.14.2 QMI (pp.1136–1139); §14.1 QFN-60 package and footprint (pp.1324–1325); §14.8 pinout (pp.1330–1335); §14.9 electrical specs (pp.1335–1343).
- `design/datasheets/w25q32jv.pdf` — Winbond W25Q32JV rev I, May 2021 (cited as **W25 p.N**). Read: §2–3 features/pins (pp.4–7), §3.9 chip select and power-up (p.9), §8 electrical (pp.58–63), §9.7 USON 4x3 package (p.71), §10 ordering (pp.75–76).
- `design/datasheets/inductor-mpl2016.pdf` — Sunlord MPL series, rev 2011-03-15, 4 pages (cited as **MPL p.N**). Read in full.
- Crystal TXM12M0004252FBCEO00T: **datasheet not available** (download blocked, see decisions.md). Its parameters below (12 MHz, CL 12 pF, ESR 120 Ω max, 2520 4-pad) are from the LCSC listing recorded in `bom/parts.yaml`, not from a datasheet. Open item.

## Parts in this block

| Ref | Part | MPN | LCSC | Footprint | Sourcing (bom/parts.yaml, JLC API 2026-10-17) |
|---|---|---|---|---|---|
| U1 | RP2350A, QFN-60 7x7 0.4 mm | RP2350A | C42411118 | `Package_DFN_QFN:QFN-60-1EP_7x7mm_P0.4mm_EP3.4x3.4mm_ThermalVias` | extended, 6,240 in stock, $1.29 |
| L1 | 3.3 µH 2016 core-buck inductor | MPL2016S3R3MHT | C98336 | `bluebuzz-rm2:L_pol_2016` | extended, 6,117 in stock |
| C80 | 4.7 µF X5R 10 V 0402, buck output (COUT) | CL05A475MP5NRNC | C23733 | 0402 | basic |
| C81 | 4.7 µF, DVDD pin 23 | same | C23733 | 0402 | basic |
| C82 | 100 nF X7R 16 V, DVDD pin 39 | CL05B104KO5NNNC | C1525 | 0402 | basic |
| C83 | 4.7 µF, VREG_VIN pin 49 (CIN) | C23733 | | 0402 | basic |
| R84 / C84 | 33 Ω + 4.7 µF, VREG_AVDD pin 46 (RFILT/CFILT) | 0402WGF330JTCE / C23733 | C25105 / C23733 | 0402 | basic |
| R85 / C85 | 10 Ω + 1 µF X5R 50 V 0603, ADC_AVDD pin 44 | 0402WGF100JTCE / CL10A105KB8NNNC | C25077 / C15849 | 0402 / 0603 | basic |
| C91–C96 | 6 × 100 nF, IOVDD pins 1, 11, 20, 30, 38, 45, 54 | C1525 | | 0402 | basic |
| Y1 | 12 MHz, CL 12 pF, 2520 4-pad | TXM12M0004252FBCEO00T | C284155 | `Crystal:Crystal_SMD_2520-4Pin_2.5x2.0mm` | extended, ~67k in stock |
| C86 / C87 | 18 pF C0G 50 V 5 % | 0402CG180J500NT | C1549 | 0402 | basic |
| R86 | 1 kΩ in series with XOUT | 0402WGF1001TCE | C11702 | 0402 | basic |
| U6 | W25Q32JV 32 Mbit QSPI flash, USON-8 4x3 | W25Q32JVUUIQ | C2999380 | `Package_SON:Winbond_USON-8-2EP_3x4mm_P0.8mm_EP0.2x0.8mm` | extended, 2,203 in stock, $2.51 |
| C88 | 100 nF, flash VCC | C1525 | | 0402 | basic |
| R87 | 1 kΩ, QSPI_SS → BOOTSEL pad | C11702 | | 0402 | basic |
| R88 / C89 | 10 kΩ + 100 nF on RUN | C25744 / C1525 | | 0402 | basic |
| R3 / R4 | 27 Ω 5 % USB series (wired in Block 1, placed at the chip) | 0402WGF270JTCE | C25100 | 0402 | extended |
| R60 / R61 / C64 | 1 MΩ / 1 MΩ / 100 nF battery divider into GPIO26 (ADC0) | C26083 / C1525 | | 0402 | basic |
| J3 | SWD pogo pad row: SWDIO SWCLK RUN BOOT GND | PCB | — | `bluebuzz-rm2:PadRow_5x_pogo` | — |

Pin wiring checked against `scripts/circuit.py` Block 8 and the ROLE map, and against DS p.1330 (Figure 152 pinout) and DS pp.1331–1335 (pin tables): IOVDD 1, 11, 20, 30, 38, 45; QSPI_IOVDD 54; DVDD 6, 23, 39; USB_OTP_VDD 53; ADC_AVDD 44; VREG_AVDD 46; VREG_PGND 47; VREG_LX 48; VREG_VIN 49; VREG_FB 50; USB_DM 51; USB_DP 52; QSPI_SD3 55, SCLK 56, SD0 57, SD2 58, SD1 59, SS 60; XIN 21, XOUT 22; SWCLK 24, SWDIO 25, RUN 26; GPIO26_ADC0 = pin 40; EP = 61 GND. **All match.** The circuit's note that pin 54 is "IOVDD" is harmless (it is QSPI_IOVDD, tied to the same 3.3 V; DS p.400 §6.1.2).

Footprints vs packages:
- **U1**: DS p.1325 Figure 148 recommended land: 60 pads 0.20 × 0.875 mm on 0.40 mm pitch, outer extent 7.75 mm, EP 3.40 mm. KiCad footprint: pads 0.2 × 0.8 at ±3.45 (outer extent 7.70), EP 3.4 × 3.4, 15 pads per side at ±2.8 max. Matches within 0.075 mm on pad length. OK.
- **U6**: ordering code W25Q32JV**UU**IQ = "8-pad USON 4x3 mm", I = industrial −40…85 °C, Q = QE bit fixed to 1 and /HOLD disabled (W25 p.75). W25 p.71 drawing: D = 4.00 (pin rows along the 4.0 mm edges, 4 pads at 0.80 pitch), E = 3.00, pad b = 0.30, L = 0.60, two centre metal strips D1/D2 0.80 long × E1 0.20 wide, "not connected to any internal electrical signals … Avoid placement of exposed PCB vias under the pad". KiCad footprint: 8 pads 0.3 × 1.05 at x = ±1.35, y = ±0.4/±1.2 (0.8 pitch), two pads "9" 0.2 × 0.8 at (0, ±0.8). **Matches the UU package.** Pad 9 is unassigned in circuit.py — correct (leave floating or GND; no vias under it). The parts.yaml "CHECK the KiCad land against Winbond's drawing" item is closed by this audit.
- **L1**: MPL p.1: 2016 body 2.0 (+0.3/−0.1) × 1.6 ± 0.2 × 0.9 ± 0.1 mm, terminal length a = 0.5 ± 0.3. Custom land: two pads 0.7 × 1.7 at x = ±0.7 (pad spans 0.35…1.05 from centre). Body half-length is 0.95…1.15 → the pad ends inside the body outline with no toe, and the terminal inner edge (0.2…0.8 from the end) can sit at 0.15…0.95 from centre, i.e. for a short terminal the pad barely overlaps it. Sunlord gives no recommended land. See finding MINOR-3.
- **Y1**: 2520 4-pad; pin order (1 & 3 crystal, 2 & 4 can/GND) is the usual convention but **unverified** without the datasheet.

## Absolute max vs our worst case

Worst case from intent.md: IOVDD = VREG_VIN = USB_OTP_VDD = 3.3 V from the TLV75533 (±1 % → 3.27–3.33 V), ambient 0–45 °C, VBAT ≤ 4.35 V.

| Parameter | Abs max (DS Table 1680, p.1335) | Recommended (DS Table 1688, p.1340) | Our worst case | Margin |
|---|---|---|---|---|
| IOVDD / QSPI_IOVDD | −0.5 … 3.63 V | 1.62 … 3.63 V | 3.33 V | OK (0.30 V) |
| DVDD (from on-chip buck) | −0.5 … 1.21 V | 1.05 … 1.16 V, transients ±100 mV | 1.1 V ± 3 % = 1.067–1.133 V (DS Table 1689 δVOUT) | OK; note firmware can raise VSEL above 1.16 V only after disabling the limit (DS p.406) |
| VREG_VIN | (not separately listed) | 2.7 … 5.5 V | 3.33 V | OK |
| VREG_AVDD | — | **3.135 … 3.63 V** | 3.27 V − 33 Ω × 0.2 mA ≈ 3.26 V | OK but only 0.13 V above min — see NOTE-4 on LDO dropout at low battery |
| USB_OTP_VDD | — | 3.135 … 3.63 V | 3.27 V | OK (same caveat) |
| ADC_AVDD | — | 1.62 … 3.63 V; performance compromised < 2.97 V | 3.27 V − 10 Ω × ~1 mA | OK |
| VPIN, standard IO (GPIO26..29, ADC) | −0.5 … IOVDD + 0.5 V | 0 … ADC_AVDD (ADC range, Table 1685) | VBAT_SENSE = 4.35 / 2 = 2.18 V | OK while IOVDD is up. If IOVDD were off with a battery present, the 1 MΩ limits the ESD-diode current to ≈ 1.7 µA — harmless |
| VPIN, FT IO (all other GPIO, RUN, SWD, QSPI) | 5.5 V with IOVDD = 3.3 V | — | 3.3 V logic everywhere | OK |
| Tj | −40 … 125 °C | ambient −40 … 85 °C (Table 1682) | 45 °C + P·θJA; P ≈ 0.4 W worst (200 mA core + buck loss + IO) × 40.5 °C/W (Table 1670, p.1325) = +16 °C → 61 °C | OK |
| IIOVDD_MAX, sum of sourced GPIO current | 100 mA (Table 1683) | | LEDs (330 Ω → ~6 mA), gate resistors 100 Ω into AO3400A gates (average small at 25 kHz), SPI/gSPI | OK |
| IQSPI_IOVDD_MAX | 20 mA | | 6 lines into CIN ≤ 6 pF each at ≤ 75 MHz: ~5 mA | OK |
| W25Q32JV VCC | −0.6 … 4.6 V (W25 p.58) | 2.7 … 3.6 V | 3.33 V | OK |
| W25Q32JV VIO | −0.6 … VCC + 0.4 V | | 3.3 V logic from QSPI_IOVDD on the same rail | OK |
| W25Q32JV TA | — | −40 … 85 °C (industrial, "I") | 0 … 45 °C | OK |
| L1 operating temperature | −40 … 85 °C (MPL p.1) | | | OK |
| L1 rated current Ir | 1.2 A (40 °C rise, MPL p.2) | | 0.24 A peak normal, ≤ 0.8 A in current limit | OK (see calc) |

## Required external parts (from the datasheets) vs ours

Core buck (DS §6.1.3, §6.1.6, §6.1.7, §6.3.7 Figure 22, §6.3.8 Figures 25/26, pp.400–411; HDG §2.1 pp.5–7):
- L 3.3 µH 0806/2016 between VREG_LX and the 1.1 V node, **Abracon AOTA-B201610S3R3-101-T** (polarity-dotted, 2.1 A per the HDG schematic L1 annotation) → **L1 MPL2016S3R3MHT substituted** (3.3 µH, 1.2 A Ir, 120 mΩ, SRF 40 MHz, no polarity marking). See MAJOR-1.
- COUT 4.7 µF 0402 X5R at the inductor output, VREG_FB tied to this node (HDG C7; DS Figure 25 "COUT") → **C80 4.7 µF 10 V X5R, pin 50 on the same 1V1 net.** OK. (HDG uses 6.3 V; ours is 10 V, better DC-bias behaviour.)
- CIN 4.7 µF 0402 X5R at VREG_VIN pin 49 (HDG C6; DS p.401 "A 4.7 μF capacitor should be connected between VREG_VIN and ground close to the chip's VREG_VIN pin") → **C83 4.7 µF.** OK.
- VREG_AVDD RC filter 33 Ω + 4.7 µF (HDG p.7: "VREG_AVDD only draws around 200 μA, an RC filter of 33 Ω and 4.7 μF is adequate"; DS p.411: "VREG_AVDD is a noise sensitive signal and must be RC filtered as per Figure 25") → **R84 33 Ω + C84 4.7 µF.** OK. Not optional: the DS says *must*.
- VREG_PGND pin 47 to GND with the switching return going straight to the pin (HDG p.5; DS p.411) → pin 47 on GND; decisions.md records a hand-routed "pin 47 GND bridge to the EP". OK.
- DVDD decoupling, DS p.400 §6.1.3: "the two DVDD pins closest to the regulator should be decoupled with a 100 nF capacitor close to the pins. The DVDD pin furthest from the regulator should be decoupled with a 4.7 μF capacitor close to the pin." From Figure 152 the regulator pins are 46–50 (top-right corner); the closest DVDD pins are **39** (right side) and **6** (left side, across the top-left corner from pin 60); the furthest is **23** (bottom). HDG Figure 6 / Appendix A puts 100 nF on all three (C8, C10, C11) plus C7 4.7 µF at the inductor. Ours: **C81 4.7 µF at pin 23 (correct), C82 100 nF at pin 39 (correct), nothing at pin 6.** See MAJOR-2.
- IOVDD: "100 nF capacitor per power pin" (HDG p.8), 7 IOVDD/QSPI_IOVDD pins + USB_OTP_VDD pin 53 which "should be decoupled with a 100nF capacitor close to the chip's USB_OTP_VDD pin" (DS p.400). HDG fits 7 caps (C12–C18) for these 8 pins, with pins 53 and 54 sharing C12 as the single deliberate deviation (HDG pp.8–9). Ours: **six 100 nF (C91–C96) for eight pins** — one fewer than the reference, and no cap is nominated for pin 53. See MAJOR-3.
- ADC_AVDD: DS p.401 "should be decoupled with a 100nF capacitor close to the chip's ADC_AVDD pin"; may share the IOVDD/VREG_AVDD source. HDG ties pin 44 straight to +3V3 with no filter (Appendix A). Ours: **R85 10 Ω + C85 1 µF** — a stricter filter than either document asks for. OK; the 0603 must still sit at pin 44.
- Crystal: 12 MHz ABM8-272-T3 (CL 10 pF, ESR ≤ 50 Ω, C0 ≤ 3 pF, drive 10 µW typ / 200 µW max), 2 × 15 pF C0G, 1 kΩ in series with XOUT (HDG pp.13–14; DS p.507 Table "Key Crystal Specifications"). Ours: **TXM12M (CL 12 pF, ESR 120 Ω max per LCSC), 2 × 18 pF C0G, 1 kΩ.** Loads recomputed below; ESR deviation see MAJOR-4.
- Flash: any 25-series QSPI flash supporting 03h, 02h, 05h, 06h, 20h (HDG p.11–12); QSPI pins wired directly and short (HDG p.10); R6 1 kΩ from QSPI_SS to the BOOTSEL switch, placed close to the flash (HDG p.10); R1 10 kΩ pull-up on QSPI_SS marked DNF, "with this particular flash device the external pull-up is unnecessary … if a different flash is used, it may become important" (HDG p.10); 100 nF on flash VCC (HDG C2). Ours: **U6 W25Q32JVUUIQ, R87 1 kΩ to the BOOT pad, C88 100 nF, no pull-up footprint.** See MINOR-1.
- USB: 27 Ω series in each line "placed close to the chip, in order to meet the USB impedance specification"; no external pull-ups/downs (built in: RPU2 0.87–1.55 kΩ, RPD 14.25–15.75 kΩ, DS Table 1684) (HDG p.15; DS p.1332 "USB operation requires external 27Ω series resistors"). Ours: **R3/R4 27 Ω 5 % "at the chip".** OK (HDG uses 1 %; 5 % of 27 Ω is 1.35 Ω, irrelevant).
- USB_OTP_VDD "must always be provided, even in applications where the USB PHY is never used" (DS p.400) → pin 53 on 3V3_SYS. OK.
- RUN: internal pull-up (DS Table 1677, p.1334: "Digital In (FT), Pull-Up"); HDG uses only a button with 1 kΩ series (R4) and no external pull-up or cap. Ours: **R88 10 kΩ + C89 100 nF.** OK, redundant pull-up; the cap gives ~1 ms of extra hold-off (see calc).
- SWD: SWDIO/SWCLK with internal pull-ups; "Always connect ground directly between the SWD probe and RP2350 … minimise the wire length" (DS p.1339). Ours: **J3 pads SWDIO SWCLK RUN BOOT GND.** OK.
- Thermal/ground: EP 61 to GND with vias (footprint has thermal vias). OK.

## Calculations

**Buck inductor: ripple, peak and saturation.**
- fsw = 3 MHz typ (DS Table 1689 p.1342), Vin = 3.3 V, Vout = 1.1 V, D = 0.33, L = 3.3 µH.
- ΔI(p-p) = (Vin − Vout) · D / (fsw · L) = 2.2 V × 0.333 / (3 MHz × 3.3 µH) = **74 mA**.
- Ipk at IMAX 200 mA (DS Table 1689) = 200 + 37 = **237 mA**. Startup current limit 240–300 mA; running current limit 260–500–800 mA (min/typ/max, DS Table 1689 p.1341): during a limit event the inductor can see **up to 0.8 A**.
- Guide's requirement: the HDG states no numeric saturation figure; it specifies the Abracon AOTA-B201610S3R3-101-T, annotated 2.1 A on the schematic (HDG Appendix A, L1), and says "if you choose not to use our example, then you do so at your own risk" (HDG p.7).
- MPL2016S3R3MHT: Ir = 1.2 A defined as a 40 °C temperature rise (MPL p.2 footnote), **no saturation current is specified**. The "Inductance vs DC current" curves (MPL p.3) show only 2R2 and 4R7 for the 2016 size: 4R7H starts rolling off at ~300 mA and 2R2H at ~500 mA; interpolating, 3R3 holds nominal L to ~400 mA and is perhaps 20–40 % down at 0.8 A. So: ✓ at the 237 mA normal peak; degraded but not catastrophic at the 0.8 A current-limit ceiling (loop still current-limited; ripple rises). The Abracon is 2.1 A-rated; ours is a weaker part on this axis.
- DCR 120 mΩ ± 25 % → 24–30 mV drop at 200 mA, inside the feedback loop (VREG_FB at COUT). Loss 6 mW. SRF 40 MHz ≫ 3 MHz. OK.
- Input RMS ripple current ≈ Iout·√(D(1−D)) = 0.2 × 0.47 = 94 mA — trivial for a 0402 MLCC.
- Output ripple ≈ ΔI / (8·fsw·C) = 0.074 / (8 × 3 MHz × 4.4 µF) = **0.7 mV** + ESR term; well inside the ±100 mV DVDD transient budget (DS Table 1688 note b).

**MLCC DC-bias derating, CL05A475MP5NRNC (4.7 µF X5R 10 V 0402).** Assumed curve (Samsung's published typical for this part; to be confirmed on Samsung's web simulator — not in `design/datasheets/`): ≈ −7 % at 1.1 V, ≈ −40 … −55 % at 3.3 V.
- C80, C81 at 1.1 V: ≈ **4.4 µF**. Fine.
- C83 (VREG_VIN), C84 (VREG_AVDD) at 3.3 V: ≈ **2.1–2.8 µF**. The reference design's 6.3 V-rated 0402 4.7 µF (HDG C6/C9) derates worse at 3.3 V (typically ≈ −60 %, ~1.9 µF), so ours is no worse than the validated circuit. VREG_AVDD filter corner = 1/(2π·33 Ω·2.5 µF) ≈ **1.9 kHz**; DC drop 33 Ω × 0.2 mA = 6.6 mV.
- Voltage rating margin: 10 V on a 3.3 V rail = 3×; 10 V on 1.1 V = 9×. OK. 100 nF X7R 16 V on 3.3 V: 4.8×, negligible bias loss. 1 µF X5R 50 V 0603 on 3.3 V: negligible loss.

**Crystal load capacitors.** HDG p.13 method: CL = C3·C4/(C3 + C4) + Cstray, with Cstray assumed 3 pF (pins + tracks).
- Ours: 18 pF ∥ 18 pF in series = 9 pF; + 3 pF = **12.0 pF = CL of the TXM12M.** Correct for a 12 pF crystal (the HDG's 15 pF give 7.5 + 3 = 10.5 pF for its 10 pF crystal).
- Tolerance: 18 pF ± 5 % → 8.55–9.45 + 3 → 11.6–12.5 pF. If the real stray on this 6-layer board (ground on In1 close under the tracks) is 5 pF rather than 3 pF, CL = 14 pF; for a 12 MHz AT-cut the pull is of order 10–20 ppm/pF → ≤ 40 ppm, far inside USB FS's ±2500 ppm. Keep the XIN/XOUT tracks short (HDG p.13).
- Deviation from the reference: larger load caps reduce the oscillator's negative resistance roughly as (15/18)² ≈ 0.69 (−31 %), and the crystal's ESR is 120 Ω vs ≤ 50 Ω. Because the 1 kΩ series resistor dominates the loop loss, the ESR change alone adds only ~7 % to (R86 + ESR), but combined with the heavier load the start-up margin is not demonstrated by any document we hold. HDG p.13: "Any deviation from the crystal circuit shown here … will require extensive testing to ensure that the crystal oscillates under all conditions, and starts-up sufficiently quickly." See MAJOR-4.
- Drive level: the 1 kΩ (HDG p.13) limits drive at IOVDD = 3.3 V; our IOVDD is 3.3 V, so the 1 kΩ is the right value per HDG p.14 ("tuned for 3.3 V operation"). A lower IOVDD would need a smaller R86; not our case.
- Start-up delay register: (12 MHz × 1 ms) / 256 ≈ 47 (DS p.508); the SDK default suffices.

**Battery divider into ADC0.**
- Thevenin source: 1 MΩ ∥ 1 MΩ = **500 kΩ**; divider current at 4.2 V = 2.1 µA (negligible standby drain, the reason for 1 M).
- VBAT 3.0–4.35 V → pin 1.50–2.18 V; ADC full scale = ADC_AVDD ≈ 3.27 V (DS Table 1685), 12-bit LSB 0.8 mV → 1.6 mV of battery per LSB. ENOB 9.5 bits → effective resolution ≈ 9 mV of battery. Meets the ±2 % intent target on resolution grounds.
- ADC input: "about 1 pF across the input" when sampling, "effective impedance, even when sampling at 500 kS/s, is over 100 kΩ" (DS p.967; RIN_ADC ≥ 100 kΩ Table 1685). Without C64, 500 kΩ source vs 100 kΩ input = gross error; **C64 100 nF is what makes the 1 M divider work**: per-sample charge transfer 1 pF × 2.1 V on 100 nF = 21 µV droop per conversion.
- Sampling-rate limit: average sampling current = Cs·V·fs = 1 pF × 2.1 V × fs; to keep the IR drop across 500 kΩ ≤ 1 % (21 mV) needs ≤ 42 nA → **fs ≤ 20 kS/s** on this channel (continuous). Recovery time constant 500 kΩ × 100 nF = **50 ms**, so after power-up or a burst, wait ≥ 250 ms before trusting a reading. A battery monitor at ≤ 1 S/s is far inside this.
- Pin leakage: DS Table 1683 specifies IIN ≤ **1 µA** max; 1 µA × 500 kΩ = 0.5 V = a 24 % error worst case on paper. Real leakage on an unpowered-digital, ADC-mode pad is nA-class and the Pico's own VSYS divider (200 k/100 k) relies on the same, but this is the one spec that formally breaks the ±2 % target. Mitigation is firmware calibration against a known VBAT, or a 200 k/100 k divider at 14 µA drain. See MINOR-2.
- Pad config: "always disable the pin's digital functions by setting IE low and OD high in the pin's pad control register" when used as ADC (DS p.965) — firmware item.

**USB series resistors.** 27 Ω each (DS p.1332; HDG p.15), with the PHY's internal 1.5 kΩ pull-up and 15 kΩ pull-downs. Nothing to compute except placement: at pins 51/52, and the pair must run as a 90 Ω differential pair over unbroken ground to the receptacle (HDG p.15). On our JLC06161H-3313 stack the outer-to-In1 dielectric is ~0.1 mm, so 90 Ω differential will be narrow tracks; HDG notes FS USB is forgiving if not compliant.

**QSPI flash clock.** W25Q32JV: 133 MHz max for all instructions except 03h (3.0–3.6 V; 104 MHz at 2.7–3.0 V); 03h Read Data ≤ **50 MHz** (W25 p.62). RP2350 QMI SCK = clk_sys / N, N = 1…256 (DS p.1136); the SDK default PICO_FLASH_SPI_CLKDIV = 2 at 150 MHz → **75 MHz with EBh quad I/O** (boot2_w25q080, HDG p.12) — inside 133 MHz. The bootrom's probe uses 03h at ~1 MHz (HDG p.11) — inside 50 MHz. The W25Q family's continuous-read mode is the one the bootrom's exit sequence (HDG p.12) was written for. OK. Flash supply current: read 18–20 mA max, program/erase 25 mA max (W25 p.60) — budget on 3V3_SYS.

**BOOTSEL via R87.** The pad sits at QSPI_SS (internal pull-up 32–86 kΩ at power-up, DS Table 1683; "Pull-Up" reset state, Table 1676). Bridging BOOT to the adjacent GND pad during power-up pulls QSPI_SS to ≈ 0 V through 1 kΩ → bootrom sees 0 → USB mass-storage boot (HDG p.10). Once the chip drives QSPI_SS high with the bridge still in place, the 1 kΩ limits the fight to 3.3 mA, which is the resistor's purpose ("allows the QSPI_SS pin to safely over-drive the applied pull-down", HDG p.10). 1 kΩ, 11 mW — OK in 0402 (63 mW).

**RUN RC.** R88 10 kΩ ∥ internal 32–86 kΩ ≈ 7.6–9 kΩ with C89 100 nF → τ ≈ 0.8–0.9 ms; RUN crosses VIH (2.0 V at 3.3 V, Table 1683) ≈ 1 ms after 3.3 V is up. Harmless, slightly beneficial hold-off; a probe or the RUN pad pulling low only has to sink the 10 kΩ (0.33 mA) and discharge 100 nF. HDG itself uses no cap.

**Current budget for the 3.3 V rail (this block only).** Core 200 mA at 1.1 V through the buck at 59 % (DS Table 1689, 200 mA/3.3 V) → 113 mA from VREG_VIN worst case (~50 mA busy per intent.md → ~30 mA); IOVDD/QSPI switching a few mA; flash ≤ 25 mA; VREG_AVDD 0.2 mA.

## Fine print / gotchas

- "The most critical part of an RP2350 PCB layout is the core voltage regulator. This should be placed first on any board design and these guidelines must be strictly followed." (DS p.409)
- Inductor **orientation matters**: "the regulator performance could be massively improved if the inductor is 'the right way round' … the magnetic field emitting from a 'wrong way round' inductor interferes with the regulator output capacitor (C7)"; unmarked inductors are "randomly distributed along a reel" (HDG pp.6–7). The Sunlord MPL has no polarity mark (MPL p.1 drawing shows none).
- VREG_VIN and VREG_AVDD "should be powered up together" (DS p.401) — both from 3V3_SYS, AVDD through a 0.1 ms RC. OK.
- VREG_AVDD "also powers the chip's power-on reset and brownout detection blocks, so it must be powered even if the on-chip voltage regulator is not used" (DS p.401); its minimum is 3.135 V (Table 1688).
- ADC_AVDD / DVDD sequencing: small transient currents if ADC_AVDD comes up before DVDD; "will not damage the chip" and the single-3.3 V scheme "is acceptable behaviour" (DS p.401).
- "The regulator must be in normal mode before the core supply current is allowed to exceed 1mA"; low-power (linear) mode ≤ 1 mA, Vout ≤ 1.3 V; "the regulator can't be relocked after it's been unlocked" (DS pp.406). Firmware items.
- "VOUT can exceed the maximum core supply (DVDD) … the limit can be disabled under software control" (DS p.1342).
- ADC input range is bounded by IOVDD, not ADC_AVDD: "the voltage on the ADC analogue inputs must not exceed IOVDD" (DS p.401, p.965). Our 2.18 V max is fine.
- ADC conversion errors (FCS.ERR) must be discarded (DS p.969).
- Flash: "/CS must track the VCC supply level at power-up and power-down … If needed a pull-up resister on the /CS pin can be used" (W25 p.9); tVSL 20 µs after VCC(min) before the first /CS low, tPUW 5 ms before any write, VWI 1.0–2.0 V (W25 p.59). The RP2350 bootrom's own start-up exceeds 20 µs, and QSPI_SS defaults to pull-up — but HDG p.10 warns of "a short period of time during switch-on where the state of the QSPI_SS pin cannot be guaranteed" and keeps a DNF 10 kΩ footprint for exactly that.
- Flash "Q" ordering option: QE = 1 fixed, /HOLD disabled "to support Standard, Dual and Quad I/O without user setting" (W25 p.75 note 4) — required for our wiring where pins 3 and 7 are SD2/SD3. Correct suffix.
- USON centre strips: no electrical function; "Avoid placement of exposed PCB vias under the pad" (W25 p.71).
- USB: USB_OTP_VDD must be present always (DS p.400); clear MAIN_CTRL.PHY_ISO at start-up (DS p.1059); USB boot mode relies on a 12 MHz crystal unless OTP overrides (DS p.1338 note).
- Crystal: "The crystal oscillator is powered from the IOVDD voltage … tuned for 3.3 V operation" (HDG p.14, DS p.507); XOSC output cannot be taken from XIN/XOUT (DS p.506); if going DORMANT on XOSC, restart takes > 1 ms (DS p.508).
- SWD: reliable to 50 MHz internally; reduce SWCLK if parity errors; ground pin adjacent (DS p.1339). Our pad row has GND.
- HDG p.8: the one place the reference shares a decoupler (pins 53/54) is justified only by 2-layer routing pressure; they note a 4-layer board with parts on both sides removes that excuse (p.9). We have 6 layers.

## Layout guidance from the datasheets (for the placement/routing gate)

Core buck (DS §6.3.8.1 p.411, Figures 25/26 p.410; HDG Figure 4 p.6, Figure 7 p.8):
- Copy the Pico 2 regulator layout "as closely as possible": L1 directly above pins 48–50, COUT (C80) and CIN (C83) stacked between L1 and the chip, RFILT/CFILT (R84/C84) to the right beside pin 46, all on the **top layer**: "Don't place any of CIN/LX/COUT on the opposite side of the PCB."
- "CIN needs its own separate GND via / low impedance path back to the RP2350 GND pad."
- Keep the two switching-phase loops (VREG_VIN → LX → L1 → COUT → PGND, and LX → L1 → COUT → PGND) "as small and low-impedance as possible, while also keeping them isolated (i.e. only connect to main GND at one point)."
- "Reduce parasitics on the VREG_LX node"; "cut away any extra copper underneath the inductor, cut back copper near the VREG_LX trace where possible."
- Bottom layer under the regulator is a ground plane tied to the EP.
- Inductor orientation per its polarity dot (HDG p.7) — not possible with the Sunlord part.
- decisions.md records the LX pre-route "to the inductor on B.Cu": this puts the highest-di/dt node through two vias and onto the back layer, contrary to the LX guidance above. See MAJOR-5.

Decoupling (HDG pp.8–9, Figure 7): one 100 nF per power pin, right at the pin, on the component side; VREG_FB track from pin 50 to the COUT node, not to a far DVDD pin.

Crystal (HDG p.13): shortest possible XIN/XOUT tracks, load caps at the crystal pads with short ground returns; keep the 3 pF stray assumption honest.

Flash (HDG p.10): QSPI lines short and direct, away from other signals (crosstalk); R87 (and any QSPI_SS pull-up) close to the flash; decoupler C88 at pin 8. No vias under the USON centre strips (W25 p.71).

USB (HDG p.15): R3/R4 at pins 51/52; 90 Ω differential pair over solid, unbroken ground the whole way; HDG notes FS is tolerant if the impedance is off.

SWD (DS p.1339): ground adjacent to SWDIO/SWCLK, short leads.

ADC (DS p.965/967): no buffer needed for DC; keep the VBAT_SENSE node and C64 at pin 40 away from the PWM/gate-drive nets.

## Open questions

1. **Crystal datasheet missing.** CL 12 pF, ESR 120 Ω, 2520 pin order (1/3 crystal, 2/4 GND), drive level and C0 are unverified. Attach the TXM12M0004252FBCEO00T datasheet, or substitute a crystal that matches the HDG spec table (CL 10 pF, ESR ≤ 50 Ω, C0 ≤ 3 pF, −40…85 °C, ±30 ppm) and revert the loads to 15 pF.
2. **Abracon AOTA-B201610S3R3-101-T** availability for consignment: LCSC had 3 in stock (parts.yaml); Mouser/Digikey not checked here. Its saturation current and DCR are not in `design/datasheets/`.
3. **Samsung CL05A475MP5NRNC DC-bias curve** not in `design/datasheets/`; the derating figures above are assumed.
4. **LCSC C42411118 = RP2350A** (QFN-60, no internal flash) should be re-confirmed by the exact JLC listing before ordering; parts.yaml records only "RP2350A".
5. Does the rails audit guarantee 3V3_SYS ≥ 3.135 V over the battery range (TLV75533 dropout at VSYS 3.0–3.4 V)? Below that VREG_AVDD, USB_OTP_VDD and the ADC are out of spec (see NOTE-4).
6. Is a VSYS/3V3 test pad planned (intent.md ASK)? Measuring DVDD under load is the acceptance test for the substituted inductor.

## Findings

**MAJOR-1 — L1 substitution: unmarked, lower-rated inductor in a layout the guide says to copy exactly.** The HDG specifies the polarity-dotted Abracon AOTA-B201610S3R3-101-T (2.1 A) and reports that regulator performance depends on coil orientation (HDG pp.6–7); the DS says the regulator guidelines "must be strictly followed" (DS p.409). The Sunlord MPL2016S3R3MHT has no polarity mark, no specified saturation current, Ir 1.2 A (thermal), and the 2016 curves suggest L rolls off from ~400 mA — above the 237 mA normal peak but below the 0.8 A current-limit ceiling. Not a blocker for a prototype: it will "work" (HDG p.6), but DVDD regulation under load must be measured. Recommended: consign the Abracon (buy 5–10 from a distributor) or, failing that, keep the Sunlord and add a DVDD test point.

**MAJOR-2 — No decoupler on DVDD pin 6.** DS p.400 requires 100 nF close to each of the two DVDD pins nearest the regulator (pins 39 and 6); HDG fits 100 nF on all three DVDD pins (C8, C10, C11). We have C82 on pin 39 and C81 4.7 µF on pin 23 but nothing at pin 6. Add a 100 nF (C1525) at pin 6.

**MAJOR-3 — Six 100 nF for eight 3.3 V pins (IOVDD ×6, QSPI_IOVDD, USB_OTP_VDD).** HDG p.8: "100 nF capacitor per power pin", seven fitted for these eight pins, sharing only at 53/54 under 2-layer routing pressure; DS p.400 separately asks for 100 nF at USB_OTP_VDD. On a 6-layer board the HDG's own excuse does not apply. Add at least one more 100 nF, nominate which cap serves pin 53 (sharing with 54 as the HDG does is acceptable), and place each at its pin.

**MAJOR-4 — Crystal circuit deviates from the only validated configuration.** CL 12 pF / 18 pF loads / ESR 120 Ω vs the HDG's CL 10 pF / 15 pF / ESR ≤ 50 Ω with the same 1 kΩ; the load caps alone cut negative resistance ~30 %, and the HDG requires "extensive testing" over temperature for any deviation (HDG pp.13–14; DS p.507). The 18 pF value is correctly computed for CL 12 pF (C = 2·(CL − 3 pF)). Options: (a) use a 12 MHz 2520 crystal with CL 10 pF and ESR ≤ 50 Ω and 15 pF loads, or (b) keep Y1 and verify start-up at 0 °C and 45 °C with XOSC amplitude measured, with R86 pads ready to drop to 470 Ω if marginal. Since the crystal datasheet is missing, (a) is preferred.

**MAJOR-5 — VREG_LX pre-routed on B.Cu.** decisions.md lists "LX to the inductor on B.Cu" among the hand-laid pre-routes. DS p.411: "Reduce parasitics on the VREG_LX node", keep the switching loops minimal and single-point grounded, and keep CIN/LX/COUT on the component side; HDG Figure 4 shows LX as a short top-layer stub from pin 48 to L1. Re-place L1 so LX is a top-layer track, as in Figure 26.

**MINOR-1 — No DNF 10 kΩ pull-up footprint on QSPI_SS.** HDG p.10 keeps R1 (DNF) because /CS must track VCC at power-up (W25 p.9) and the RP2350's QSPI_SS state is briefly undefined at switch-on. The W25Q32JV is the same family the HDG validated without it, so this is insurance only; add the footprint near the flash if space allows.

**MINOR-2 — Battery divider accuracy depends on unspecified ADC-pin leakage.** 500 kΩ source impedance × the 1 µA spec maximum (DS Table 1683) = 0.5 V; real leakage is nA-class and C64 handles the sampling charge (≤ 20 kS/s continuous, 50 ms recovery). Accept with a firmware calibration step, or change to 200 k/100 k (14 µA drain) if ±2 % must be guaranteed by spec.

**MINOR-3 — L1 custom land pattern.** Pads 0.7 × 1.7 at ±0.7 end inside the 2016 body outline (body half-length up to 1.15 mm) with no toe; the terminal length tolerance (0.2–0.8 mm) can leave little pad–terminal overlap. Widen to ~0.9 × 1.8 at ±0.75 (standard 0806 land), unless the pattern was copied from the Abracon recommendation — in which case document that.

**MINOR-4 — Crystal datasheet and pin order unverified** (open question 1). Pads 2/4 = GND is the usual 2520 convention; a wrong assumption shorts XIN or XOUT to ground.

**NOTE-1 — Inductor saturation vs current limit.** Normal peak 237 mA; regulator current limit up to 0.8 A max (DS Table 1689). The MPL curves imply reduced but non-zero inductance at 0.8 A; the limit still functions. Acceptable.

**NOTE-2 — MLCC derating.** 4.7 µF 10 V 0402 at 3.3 V ≈ 2.1–2.8 µF (assumed curve) — no worse than the HDG's 6.3 V parts; at 1.1 V ≈ 4.4 µF. Confirm the curve (open question 3).

**NOTE-3 — Flash and USB are within spec.** W25Q32JVUUIQ matches the USON 4x3 KiCad land, the Q suffix gives QE = 1 for our SD2/SD3 wiring, 75 MHz EBh ≤ 133 MHz, 03h probe ≤ 50 MHz. 27 Ω series resistors are correct and the internal USB terminations need nothing external.

**NOTE-4 — 3.3 V rail minimum.** VREG_AVDD and USB_OTP_VDD need ≥ 3.135 V and the ADC ≥ 2.97 V; our margin at nominal is ~0.13 V. If the LDO drops out at low battery, the chip keeps running (IOVDD/VREG_VIN minimums are far lower) but the regulator's analogue supply and the ADC are out of spec. Cross-check with the rails audit; firmware should sleep/shut down before the LDO leaves regulation.

**NOTE-5 — Items the HDG has that we deliberately omit.** No reset or BOOTSEL buttons (replaced by pads, decision R6), no 10 µF LDO caps here (rails block), no I/O headers. None affect the RP2350's requirements.
