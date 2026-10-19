# bluebuzz-rm2 — design intent (phase 0)

Status: user answers received 2026-10-18 (marked **USER**); remaining **ASK** items are noted. Awaiting sign-off.

## Purpose

A small, battery-powered Bluetooth vibrator controller. It lives inside a soft, cast elastomer body; a phone streams audio (A2DP) or control (BLE) to it; the board drives two vibration motors, senses squeeze through a tactile array of MEMS barometers under the rubber, and senses motion with an IMU. Used by one person; charged from USB-C. Open source (personal project, KiCad, served at the user's local project hub).

## Open source or confidential

Open source. Repo URL on silkscreen: none yet (**USER**); the silk carries name, revision and date only.

## External interfaces

| Interface | Direction | Signal | Voltage range (normal / worst) | Current | What plugs in |
|---|---|---|---|---|---|
| USB-C receptacle (bottom edge) | in/out | USB 2.0 FS device, 5 V power in | 5 V / 5.5 V (USB), hot-plug, user-handled: ESD | 1 A input limit (BQ24074 ILIM) | phone charger, computer |
| BAT pads (2, back, soldered lead) | in | single-cell LiPo | 3.0–4.2 V / 4.35 V | 500 mA charge; up to 2 A discharge peak (two motors) | 1-cell LiPo with its own protection PCB; an NTC is optional (**USER**): the BAT row has a T pad on TS. Capacity: ≥ 600 mAh from the life target below |
| MOT pads (3, back, soldered leads) | out | VSYS, M1, M2 low-side PWM | VSYS 3.0–4.4 V, flyback-clamped | 1 A continuous per channel (design), **USER**: 0.09 A per motor (one version), 0.2 A per motor (another) | two 3.7 V DC vibration motors |
| SWD pads (5, back, pogo) | in/out | SWDIO SWCLK RUN BOOT GND | 3.3 V logic | mA | debug probe / boot strap |
| Debug JST-SH (3-pin, back, not fitted) | in/out | SWCLK GND SWDIO | 3.3 V logic | mA | Raspberry Pi Debug Probe |
| Status LED (WS2812-class 1010, front) | out | one-wire RGB | VSYS-powered, switched off with 3V3 | ≤ 15 mA | — |
| Bluetooth / Wi-Fi (RM2 antenna) | wireless | 2.4 GHz BT Classic + LE, Wi-Fi 4 | — | TX bursts up to ~300 mA on VSYS | phone |
| Tactile array (5 x DPS368, on-board) | sensor | pressure through elastomer | — | 0.3 mA each | the cast rubber body |
| IMU (on-board) | sensor | accel + gyro | — | 1 mA | — |

ESD: the USB-C is user-handled; D+/D- and VBUS have the USBLC6-2 array at the receptacle. The pad rows are inside the cast body and not user-accessible after assembly.

## Power

- Input: USB 5 V through BQ24074 (power path: system runs from USB while charging; 500 mA charge (ISET), 1 A input limit (ILIM), 6 h safety timer (TMR 45.3 k; re-set once the cell capacity is known — parts/bq24074-charger.md), NTC TS pin terminated with 10 k (no thermistor in the cell: **ASK** whether the chosen cell has an NTC).
- VSYS: 3.0–4.4 V (battery, or 4.4 V regulated when USB present). Loads: RM2 Vin (300 mA peaks), two motors (up to 2 A peak), the LDO.
- 3V3_SYS (TLV75533, 500 mA): RP2350 (IOVDD, VREG_VIN for the 1.1 V core buck ~ 100 mA), flash, RM2 VDDIO, IMU, status LED. Switched by the soft power latch (**USER**): a press of the power button enables the LDO, firmware holds it on (GPIO19) and switches it off; the button stays readable on GPIO8. USB power also holds the LDO on (**USER**, option 1), so the board always runs while plugged in; BOOTSEL is a separate pad-row strap.
- 3V3_SENS (TPS22918 switched from 3V3_SYS, GPIO4): the DPS368 array. Can be powered down in sleep.
- 1V1: RP2350's internal buck through L1 3.3 µH, up to 200 mA.
- Sequencing: none required beyond the RP2350's own (RUN held by 10k/100n). The IMU is on 3V3_SYS, so wake-on-motion works only while the system is on. Off-state draw ≈ 10–15 µA (charger, divider, LDO shutdown).
- No regen or backfeed: motors are low-side switched with flyback diodes to VSYS.
- Battery life target (**USER**): 4–6 h of play at 10 % vibration duty. Estimate: motors 2 × 0.2 A × 10 % = 40 mA (18 mA for the 0.09 A motors), RP2350 + flash ≈ 30 mA, RM2 in A2DP ≈ 40 mA average, LDO/charger/sensors/IMU ≈ 5 mA → ≈ 115 mA → **≥ 700 mAh for 6 h** (≈ 500 mAh for 4 h). At 500 mA charge a 700 mAh cell is ≈ 0.7 C and charges in ≈ 1.7 h, inside the 6 h safety timer.
- Peak VSYS: two 0.2 A motors + RM2 TX 0.35 A + LDO 0.25 A ≈ 1 A, well under the charger's ~2 A battery-mode ceiling (parts/bq24074-charger.md M2 closes).

## Environment

- Temperature: indoor/body use, 0–45 °C operating. **ASK** if anything beyond.
- Enclosure: the board is cast into soft elastomer (polyurethane, VytaFlex 20 or similar) with the sensor array under 4–10 mm of rubber; no airflow; sealed. The casting means **no rework after assembly**, so the board must be fully tested before casting.
- Vibration: continuous from the motors (ERM, 100–300 Hz). Fine for SMD parts; the crystal and RM2 castellations are soldered, no connectors to loosen.
- Moisture: the cast body is washed; the rubber seals the board. The USB-C opening is the one exposure. **ASK**: is the USB-C expected to be sealed with a plug/cap, or should the design add conformal coating?
- ESD: USB-C only.

## Performance targets

- Motor drive: PWM at 20–25 kHz (above audible), 1 A per channel.
- Audio: A2DP sink (SBC), decoded on the RP2350, mapped to motor intensity; USB audio device over USB-C.
- Tactile: 5 sensors (four corners and the centre) at ≥ 50 Hz each (the paper's arrays ran at 100 Hz per sensor), 10 mN resolution class after calibration.
- IMU: wake on motion, tap detection; 100 Hz data rate.
- Radio: Bluetooth Classic + LE, Wi-Fi only for provisioning/updates.
- ADC: battery voltage via 1M/1M divider into ADC0 (12-bit, ±2 % with the RP2350's internal reference).

## Mechanical

- Board 28 × 44 mm, 2 mm corner radius, no mounting holes (cast in place). Size limit TBD; minimal for now (**USER**).
- Height: RM2 2.55 mm, USB-C receptacle 3.2 mm, everything else < 1.5 mm on the front; the sensors 1.1 mm on the back plus the rubber.
- USB-C centred on the bottom (short) edge, opening flush with the edge; the top edge is the RM2's antenna, which must face the body's surface with no metal within the datasheet keep-out.
- Pad rows on the back: BAT (top), MOT (bottom-left), SWD (under the radio), all 1.6 × 2.2 mm at 2.0 mm pitch, single lines along edges.

## Manufacturing

- JLCPCB, 6-layer (JLC06161H-3313), 1 oz outer / 0.5 oz inner, ENIG (pogo pads), assembly by JLC for everything on LCSC; the RM2 consigned or hand-soldered.
- Quantity: 5 for the first run (**USER**).
- Cost target: **ASK**. Extended parts (each with a loading fee): RP2350A, BQ24074, TLV75533, TPS22918, W25Q32, DPS368 (×5), LSM6DS3TR-C, crystal, inductor, USB-C.
- Double-sided assembly: the front has every part but the five sensors, their caps, two RP2350 supply caps and the unfitted debug connector on the back (two-sided SMT at JLC). 0402 passives.
- Hand assembly: the RM2 if not consigned; the battery and motor leads.

## Serviceability

Hobby prototype; cast in rubber, so not repairable after casting. Designators: on the fab layer only; silkscreen carries the pad-row labels, LED labels and board identity. Test points: a three-pad pogo row on the back (VSYS, 3V3, 1V1) beside the right edge, GND on the SWD row (**USER**: yes).

## Compliance

None formal. Bluetooth radio is a certified module (RM2) used per its integration guide.

## Known risks and open questions

- The RM2's RF keep-out assumes the module's antenna faces free space; inside a rubber body the antenna is detuned — expected range loss, to be measured.
- The DPS368s are rated IPx8 but the elastomer must fill the port (vacuum degassing) or sensitivity is poor (paper, section II-B).
- The RP2350 ADC's internal reference is ±2 %; battery gauge is coarse.
- No cell protection on the board: the cell must bring its own.
- The charger's TS input is terminated with a fixed 10 k, so there is no cell-temperature cutoff.
- **ASK**: anything else the board must do (haptic waveform fidelity, second USB role, external LED)?
