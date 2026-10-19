# Gate 1 — architecture and parts

Status: **PASSED with open items** (2026-10-18). Every BLOCKER fixed; every MAJOR fixed or logged in decisions.md; five datasheets the fetcher could not download are open items for the user.

## Checklist
- [x] Block diagram: architecture.md (13 blocks, each mapped to parts, schematic block and board region)
- [x] Audit file per non-trivial part, datasheet in datasheets/: parts/bq24074-charger.md, tlv75533-ldo.md, tps22918-switch.md, rp2350-host.md (RP2350, flash, inductor, crystal network, decoupling), rm2-radio.md, dps368-tactile-array.md, lsm6ds3tr-c-imu.md, motor-channels.md, usb-front-end.md
- [x] Abs max vs worst case in every file
- [x] Every chosen value calculated (ISET/ILIM/TMR, LDO dropout and dissipation, load-switch slew, crystal loads, divider, gate drive, ripple, flyback, CC pull-downs)
- [x] MLCC DC-bias derating (estimates; Samsung curves to confirm — open)
- [x] Footprints vs package drawings: DPS368 corrected to fig. 18; RM2 side pads corrected to fig. 6; flash USON 4×3 confirmed; IMU land vs LSM6DSO fig. 25
- [x] Sourcing with date (JLC API, 2026-10-17/18)
- [x] Independent reviewer per part (one subagent per audit, each read its datasheet and recomputed)

## Findings and resolutions
| Part | Finding | Severity | Resolution |
|---|---|---|---|
| DPS368 | land pattern 0.6×0.4 NSMD + 1:1 paste vs datasheet 0.35×0.35 SMD | BLOCKER | fixed in gen_footprints.dps368() |
| DPS368 | vacuum degassing forbidden for the vent hole | MAJOR | casting method changed to pressure pot (decisions.md) |
| DPS368 | I2C at power-up until CS seen low | MAJOR | firmware rule (decisions.md) |
| DPS368 | one 100 n per sensor, 2.3 mm away | MINOR | moved to within 1 mm of pins 6/8 |
| RM2 | side pads 0.2 mm toward the antenna | BLOCKER | fixed in gen_footprints.rm2_pads() |
| RM2 | Vin floor 3.0 V, RF degrades < 3.2 V | MAJOR | firmware cutoff 3.5 V |
| RM2 | 10 µF 15 mm from Vin pad | MINOR | C100 moved to the right edge, 3 mm from pad 16's column |
| RP2350 | no 100 n on DVDD pin 6; 6 caps for 8 pins | MAJOR | C98, C97 added |
| RP2350 | crystal deviates from the validated circuit | MAJOR | ABM8-272-T3 + 15 pF |
| RP2350 | inductor without polarity dot / sat spec | MAJOR | kept (Abracon 3 in stock); consign option for the user |
| RP2350 | LX pre-routed on B.Cu | MAJOR | L1 over pins 47–49, LX on F.Cu |
| Motors | 100 k gate pull-down vs RP2350-E9 leakage | MAJOR | 4.7 k |
| Motors | ripple / flyback heat at 1 A | MAJOR | closed: motors are 0.09–0.2 A (user) |
| Charger | timer 6 h not 10 h; thermal 1.6 W worst case | MAJOR | intent corrected; PowerPad vias are pre-routed (4) |
| LDO | out of regulation below 3.4 V VSYS | MAJOR | firmware cutoff 3.5 V |
| Switch | QOD + high SPI lines back-power sensors | MAJOR | firmware: park lines low first |
| IMU | SDx/SCx floating; body 0.3 mm from edge | MAJOR | tied to GND; moved 1.6 mm in |
| USB | receptacle/ESD datasheets missing | MAJOR | open item for the user |

## Open items (need the user)
- Attach datasheets: LSM6DS3TR-C, USBLC6-2, B5819W, TYPE-C-31-M-12 (and Abracon ABM8-272-T3, which the fetcher also could not get).
- Inductor: consign the Abracon AOTA-B201610S3R3-101-T, or accept the Sunlord part.
