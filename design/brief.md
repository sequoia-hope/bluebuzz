# Mechanical and layout brief (phase 4) — bluebuzz-rm2

Status: DRAFT for user sign-off. The board exists at this brief already (`scripts/place.py`); the brief records the decisions so the placement gate can be checked against it.

1. **Outline.** 28 × 44 mm rectangle, 2 mm corner radius, free (no enclosure yet: the board is cast into the rubber body). Portrait: the RM2 antenna edge is the top short edge, the USB-C the bottom short edge. Size limit TBD; minimal for now (**USER**).
2. **Mounting holes.** None. The board is held by the cast elastomer. No standoffs, no screws.
3. **Connectors.**
   - USB-C receptacle J1 (TYPE-C-31-M-12, 16-pin, mid-mount hybrid): bottom edge, centred (**USER**, 2026-10-18), opening flush with the edge, pads facing up the board. Mating clearance: the plug body extends below the board edge; the rubber body must leave a 9 × 4 mm window and a plug recess.
   - BAT pads J2 (three 1.6 × 2.2 mm pads at 2.0 mm: + − T, back, top-left under the charger; T is the charger's TS for a cell with an NTC): the cell lead soldered before casting, strain relieved by the rubber.
   - MOT pads J4 (three pads, back, bottom-left): VSYS M1 M2, motor leads soldered before casting.
   - SWD pads J3 (five pads, back, under the RM2, ENIG, no paste): pogo clip for debug/flash before casting; also the BOOT strap (bridge BOOT to GND).
   - Debug probe J6 (JST-SH BM03B-SRSS-TB, 3-pin, back, **not fitted**, **USER**): SWCLK GND SWDIO in the Raspberry Pi Debug Probe pin order, for bench work before casting; silk "PROBE SC GND SD".
   Grouping: power in and the debug pads at the top of the back; motor outputs at the bottom-left; the receptacle alone on the bottom edge (the only opening in the body).
4. **Assembly sides.** Front: every component except the tactile array. Back: the five DPS368 and their five 100n, the two RP2350 supply caps C97/C98 under the chip, the unfitted debug connector, plus the pad rows. Two-sided SMT at JLC because the sensors must face the rubber; the user asked that everything else be on one side.
5. **Layers.** Six: F (parts, escapes) / In1 GND plane / In2 signals / In3 VSYS pour / In4 GND plane / B (sensors, pad rows, wiring). Four layers left 40–55 connections open at this density (decisions.md).
6. **Density.** Compact and portable: 0402 passives (0603 for the 10/22 µF), no test points beyond the pad rows, designators on the fab layer only. The rubber makes rework impossible after casting; the board must be tested bare through the pogo pads and USB.
7. **Floorplan** (front, x from the left, y from the top of the 28 × 44 board):
   - Top 5 mm: RF keep-out, no metal on any layer, no parts.
   - Top-right: RM2 (x 13.6–28, y 0–16.5) with its castellations facing in; its supply caps below its pad row, R80/R81 at its data pads.
   - Top-left: BQ24074 charger block with its set resistors in line with their pins at the left edge, VBUS/VSYS caps above the chip, cell caps and the BAT pads to its right; the LDO and the load switch below it in a column with their caps in line with their pins.
   - Centre: RP2350 (1 mm lower than first placed, so four rows of 0402s fit above it: its top-edge decoupling, the USB terminations, the VREG filter, the inductor, the RM2's VDDIO/Vin caps). Flash to its left, rotated so SS/SD1/SD2 face the QSPI pins. Crystal and its network below the chip's bottom edge. Right-edge decoupling, the ADC filter and the battery divider to its right.
   - Left edge, middle: the IMU with pull-ups above and caps beside it; the power button (soft latch, plunger 0.5 mm past the left edge) and its latch parts (Q3, D5, R63, R64, D6, R66) between it and the chip.
   - Right edge, lower middle: the status LED (WS2812-class 1010) with its 330 R, its 100 n and its supply switch U11.
   - Bottom corners: the two motor channels, mirrored either side of the USB-C (gate network beside each FET, flyback and bulk cap at each output); the MOT pads on the back behind the receptacle.
   - Bottom centre: the USB-C with the ESD array, its cap and the CC pull-downs just above it; the 27 R terminations stay at the RP2350's USB pins.
   - Back: five DPS368, one in each corner (top pair just below the RF keep-out, bottom pair in the bottom corners) and one at the centre (**USER**), each with its 100 n inboard and a no-via rule area under its body; the pad rows along the edges; the SWD pads under the radio; the art in the left-half strip.
   Noisy vs sensitive: the motor switch nodes and flybacks at the bottom-left, the crystal at the centre-bottom (≈ 5 mm from motor channel 2 over solid ground; 10 mm is not available on this board, decisions.md), the ADC inputs at the right edge, the antenna at the top with the whole keep-out between it and everything.
8. **Thermal.** Hot parts: the LDO at up to ~0.3 W (4.4 V → 3.3 V at 250 mA) with its thermal pad… (SOT-23-5: no pad; relies on the GND pour and the In1 plane), the charger's PowerPad with four thermal vias into In1/In4, the FETs (<50 mW each). No heatsinking; the rubber insulates, so dissipation is budgeted low (parts audits).
9. **Art zone.** **USER**: art of dripping fluid. Back side, front-view x −13.2…−5.2 mm, y −10…9 mm from the centre (the right half as the back is seen), clear of the sensors, pads and holes. Drawn by scripts/art.py as filled silkscreen.
10. **Silkscreen policy.** No designators on silk (fab layer carries them). Silk: pad-row labels with pin 1 and polarity (BAT + −, MOT VSYS M1 M2, SWD pin names), the LED names, board identity "bluebuzz-rm2 rev A 2026-10" (no repo URL yet, **USER**), on the back where the pads are (the front is dense). JLC minimums: 1.0 mm text height, 0.15 mm line.
11. **Keepouts.** The RM2 RF keep-out (top 5 mm, all layers, both sides, no parts); no F.Cu tracks under the RM2 body (not inspectable after soldering); the receptacle's pegs; the sensor pads' via-free zones on the back.
12. **Test and debug.** The SWD pogo pads (SWDIO SWCLK RUN BOOT GND), a three-pad pogo row J5 (VSYS, 3V3, 1V1) on the back at the right edge (**USER**: yes), and the USB-C. No isolation jumpers (density).
