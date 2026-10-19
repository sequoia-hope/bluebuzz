# Gate 3 — net classification

Status: PASSED (author check); user to glance at `nets.csv` in PCB view.

## Checklist

- [x] Every named net in the schematic is in `nets.csv` (both directions): `python3` check in this gate's evidence below — 65 nets, 65 classified, 0 missing, 0 stale.
- [x] Every row has a class and a reason.
- [x] Currents trace back to `intent.md` (motor 1 A per channel, charger 500 mA / 1 A, radio 300 mA peak) or part audits (`parts/*.md`).
- [x] Derived widths and via counts computed: `stackup.md`, "Current-carrying widths" and "Impedance".
- [ ] User has glanced at the table.

## Evidence

```
$ python3 (classification script, 2026-10-17)
nets: 65 classified: 65 missing: [] stale: []
```

Class counts: POWER 6 (GND, VBUS, 3V3_SYS, 3V3_SENS, 1V1 + ANALOG supplies counted separately), POWER_HI 2 (VBAT, VSYS), SWITCH 1 (VREG_LX), SWITCH_HI 2 (MOTOR1_SW, MOTOR2_SW), GATE 4, DIFF_HS 4 (USB pairs), SE_HS 9 (QSPI ×6, gSPI ×3), CLOCK 3, ANALOG 8 (3V3A, VREG_AVDD, TS, ISET, ILIM, TMR, CT_SENS, VBAT_SENSE), SIGNAL 26.

Derived (see stackup.md): VSYS as the In3 pour with ≥ 4 vias per transfer; VBAT 0.3 mm, 2 vias; MOTORx_SW 0.4 mm on F.Cu only; 3V3 rails 0.2 mm; USB 0.15 / 0.15 for ≈ 90 Ω differential.

Simulation triggers from the classes (phase 8): DIFF_HS (USB, 20 mm, full-speed: waive with reasoning), SE_HS (QSPI ≤ 10 mm, gSPI ≤ 25 mm over solid GND: waive), SWITCH_HI near ANALOG (motor switch nodes vs VBAT_SENSE and the crystal: aggressor/victim check in phase 8).

## Review

Main model (per review-protocol: nets gate). Findings: none blocking. NOTE: GND's current column is nominal; the planes carry it.
