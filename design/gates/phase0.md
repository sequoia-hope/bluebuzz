# Gate 0 — design intent

Status: **awaiting user sign-off** (intent.md). The user answered the open questions on 2026-10-18 (marked USER in intent.md).

## Checklist
- [x] Purpose, open-source status, every external interface with voltages and currents
- [x] Power: input, rails, loads, battery, sequencing (none), backfeed (none)
- [x] Environment (cast in elastomer, 0–45 °C), performance targets, mechanical (28 × 44, size TBD), manufacturing (JLC, 5 boards), serviceability (pogo pads + test pads), compliance (none)
- [x] Every requirement has a number or "don't care"; open items: the cell model (≥ 700 mAh recommended), the body's size limit (TBD by the user)
- [ ] User sign-off

## Review
Independent review is folded into the part audits (each re-derived operating conditions from intent.md): the charger audit corrected the safety timer (6 h, not 10 h) and the motor audit's findings closed with the user's 0.09/0.2 A motors.
