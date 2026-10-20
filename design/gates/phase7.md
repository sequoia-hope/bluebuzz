# Gate 7 — routing

Status: **PASS WITH CONDITIONS** (independent review of submission 2, 2026-10-19; conditions below, open). Submission 1 failed review (5 BLOCKER, 7 MAJOR; kept below). The generator was reworked to its fix plan and the board rerouted. DRC is 0/0, every current path passes, and all three planes are single solid pieces. What fails is the return-via and stitching checks in the RP2350's pin-escape lanes, plus three decisions left to the user (open questions at the end).

Board: `out/bluebuzz-rm2.kicad_pcb` at commit `d37b88d`, from the ordering `design.yaml` names (`routing: ordering: 42`). A plain `build.py` reproduces it: the run was repeated from scratch, with the same result.
Note: phases 2, 4, 5 and 6 still have no gate files in `design/gates/`, so this gate sits on unreviewed placement and rules.

## Checklist

- [x] DRC 0 errors, 0 unrouted. `drc.rpt`: 9 violations, all silkscreen warnings (the same 9 as submission 1, deferred to phase 9); 0 unconnected pads.
- [ ] Parity. Connectivity: **0 differences** (`check_parity.txt`). KiCad's own parity (`drc_parity.rpt`): the 24 name-only nets and unconnected-pin placeholders as before. Waiver, or labelling the nets, is the user's call (open question 1).
- [x] Current capacity: **0 FAIL** (`check_current.txt`). Pours are now rated by their fill, and the fill necks are listed.
- [ ] Plane integrity:
  - [x] In1 GND, In3 VSYS and In4 GND are each one piece, with no wire of another net.
  - [x] No fast track leaves its reference plane.
  - [ ] **14 return-via FAILs**: 3 fast-net vias over 1.0 mm, 11 slow-net vias over 1.5 mm, all in the RP2350's pin-escape lanes (see residuals).
  - [ ] Edge fence: one 0.4 mm overshoot.
  - [ ] Interior stitching: worst 3.23 mm against 3.0, in the same lane.
- [x] Every warning explained: the 9 silk warnings (below, phase 9). The 12 GND↔VSYS reference changes on fast nets are listed in the residuals.
- [x] Per-layer renders reviewed (`copper_*.png`, regenerated).
- [x] PCB view regenerated (`build.py --only site`).

## Evidence

Commands (from the project root):

```
python3 build.py                      # ordering 42; or ROUTE_FIRST=k ROUTE_TRIES=1 to search
kicad-cli pcb drc --severity-all --all-track-errors --format report -o design/gates/phase7/drc.rpt out/bluebuzz-rm2.kicad_pcb
kicad-cli pcb drc --schematic-parity --severity-all --format report -o design/gates/phase7/drc_parity.rpt out/bluebuzz-rm2.kicad_pcb
python3 scripts/check_parity.py   > design/gates/phase7/check_parity.txt    # exit 0
python3 scripts/check_current.py  > design/gates/phase7/check_current.txt   # exit 0
python3 scripts/check_planes.py   > design/gates/phase7/check_planes.txt    # exit 1
python3 scripts/audit.py          > design/gates/phase7/audit.txt           # exit 0
kicad-cli sch erc --severity-all -o design/gates/phase7/erc.rpt out/bluebuzz-rm2.kicad_sch   # 0 errors, 0 warnings
```

```
** Found 9 DRC violations **        ** Found 0 unconnected pads **      (all 9: silkscreen warnings)
ok VBUS      USB-C -> U2 IN        1.06 A of 1.00   neck In2.Cu 0.65 mm
ok VBAT      U2 BAT -> cell pad    2.76 A of 2.00   neck F.Cu fill pwr_vbat 1.40 mm
ok VSYS      U2 OUT -> J4.1 (MOT)  2.13 A of 2.00   neck J4.1's 4 vias
ok VSYS      U2 OUT -> RM2 VIN     1.07 A of 0.35   neck U7.16's 2 vias (C100 under it on the back)
ok MOTOR1_SW / MOTOR2_SW           1.23 A of 1.00 each (FET and diode)   neck 0.4 mm F.Cu
ok 3V3_SYS   LDO -> RP2350 / RM2   0.45 / 0.39 A of 0.25 / 0.05
planes: In1 GND 1 piece, In3 VSYS 1 piece (0 foreign wires), In4 GND 1 piece; no fast track off its reference
return vias In1<->In4: 21 within 1.0 mm, 9 within 1.5 mm (slow nets), 14 FAIL
edge fence: worst 1.99 mm (limit 1.6), one stretch at (87.20,114.8-115.1)
interior: 6 % of via-allowed area > 2 mm from a GND via; worst 3.23 mm (limit 3.0) at (100.20,104.20)
audit: clean        parity: 0 connectivity differences        ERC: 0
```

Method, in short (decisions.md parts 1–3 carry the reasoning):
- In3 is a solid VSYS plane, and VSYS is a plane net like GND.
- Every power transfer is a via array sized by the check's rating, or an F.Cu power zone with its vias.
- The motor nets are F.Cu only; VBUS is 0.65 mm with 0.7/0.4 vias.
- The nets freerouting kept stranding are routed first by the grid router (`finish.preroute`): VBUS, WL_DATA, TAC_CS1/2, WL_IRQ, the motor nodes, IMU_INT1.
- `stitch.py` adds return vias, the edge fence and interior stitching. The finish stage has transactional rip-up.
- 48 orderings were searched in slim copies. Ordering 42 closed fully.

## Submission-1 findings: status

| # | Finding | Status |
|---|---|---|
| B1 | In3 VSYS pour in 2 pieces under 312 mm of wiring | **fixed**: In3 has no wires; one piece |
| B2 | Motor VSYS feed through single vias | **fixed**: charger OUT zone + 4 × 0.6/0.3; J4.1 4 vias; 2.13 A |
| B3 | MOTORx_SW one via into J4 | **fixed**: 3 vias in each pad + F.Cu bar, F.Cu-only class; 1.23 A |
| B4 | VBUS through one 0.2 via, 33 mm on In3 | **fixed**: Vbus class 0.65 mm / 0.7/0.4 vias, trunk grid-routed on In2 over VSYS; 1.06 A |
| B5 | VBAT one 0.25 via, 0.3 mm | **fixed**: F.Cu VBAT zone + 4 × 0.5/0.25 in the cell pad; 2.76 A |
| M6 | LX cut-out 1.7 × 5.4 mm; VBAT_SENSE under it | **fixed**: cut-out follows the LX copper (+0.25 mm); In2 keep-out under it |
| M7 | Return vias missing | **partly**: 21 + 9 now meet the rule; 14 do not (residuals) |
| M8 | WL_CLK on In3 under In2 traffic | **fixed**: WL_CLK on B.Cu over In4, WL_DATA beside it |
| M9 | In2 references the cut-up In3 | **fixed**: In3 solid, so In2's reference is continuous. GND↔VSYS reference changes listed (open question 2) |
| M10 | Stitching far below "2 mm" | **mostly**: edge fence and interior stitching added (45 vias); stackup.md now states the real targets; 1 edge stretch and the escape lane remain |
| M11 | RM2 VIN one via; C100 6 mm away | **fixed**: U7.16 2 vias; C100 on the back directly under pad 16 |
| M12 | Check-script gaps | **fixed**: fill-rated pours, VSYS plane checked, In2 → In3 reference, all return vias, stitching density |
| m13 | Right-angle bends | finish mitres them where there is room. Pre-routes are laid at 45° |
| m14 | B.Cu GND pour pieces | island removal is on; DRC finds no unconnected pour |
| m15 | USB_DM through 4 vias + In3 hop | **partly**: no In3. The ESD taps run 5–9 mm on In2 over VSYS (freerouting's) |
| m16 | XIN 5.2 mm against 5 mm | open: 5.2 mm includes the load-cap stub to C86. Placement, phase 6 |
| m17 | C12 6.6 mm from U2.2; C100 6 mm | C100 fixed. C12 open: it is fed by a 0.3 mm track and an In2 hop from the zone corner (the review corrected an earlier claim here that it shares the zone with C15; only C15 does) |
| m18 | Silk warnings not explained | explained, phase 9 |
| m19 | MOTOR1_SW under the USB-C body | accepted: J4 is directly under J1, so the motor bars and arrays cannot avoid the body |

## Residuals (open)

1. **Return vias in the pin-escape lanes.** 14 signal vias move the return between In1 and In4 with no GND via within the limit.
   - Fast nets (limit 1.0 mm): WL_CLK's lower via at 2.91 mm, USB_DM at the receptacle at 1.18 mm, WL_DATA at 1.45 mm.
   - Slow nets (limit 1.5 mm): BTN, CHG_N, IMU_INT1, MOTOR1_PWM, PWR_HOLD, RUN ×2, SDA, TAC_CS1, TAC_CS2 and TAC_CS4, between 1.58 and 3.14 mm.

   Every one sits in the lane between the flash and the RP2350's left pin column, or under its bottom row. `stitch.py` finds no legal spot for a via there: the escapes' own vias and wires fill it. WL_CLK's via, for example, sits in a 0.65 mm band between WL_DATA (F.Cu) and WL_CLK (B.Cu). Closing these needs more room around U1's escape lanes, which is a placement change (phase 6), or a waiver.
2. **Stitching**:
   - Interior: 17 grid points between 3.0 and 3.23 mm from a GND via, in the same lane.
   - Edge fence: one stretch of 0.3 mm at the left edge by SW1, 1.99 mm from a GND via against 1.6 mm.
3. **Fast nets that change reference between GND and VSYS**: the QSPI lanes on In2, USB's ESD taps on In2, and WL_DATA's fallback hop. 12 vias, with the nearest VSYS–GND cap 9–14 mm away. A 100 nF VSYS–GND cap by the flash (the QSPI and WL_DATA ones) is a schematic change: open question 2.

## Follow-ups (generator; each changes routing, so each needs a new ordering search)

- `relayer` re-layers locked wires: it moved part of WL_CS's In2 pre-route onto B.Cu. It should skip locked groups. `stitch.py` now sweeps the dangling via this leaves.
- A `USB` entry in `LAYER_RULES` (F.Cu, B.Cu) would keep the ESD taps off In2.

## Open questions for the user

1. Parity names: label the 24 block-internal nets in the schematic (`SCH_NAME_LOCAL_NETS`, reverses an earlier schematic decision) or keep the waiver?
2. Add a 100 nF VSYS–GND cap by the flash for the In2 QSPI lanes' reference change?
3. The return-via and stitching residuals: waive them for slow nets in the escape lanes, or reopen placement (phase 6) to free room around U1?

## Submission 2: independent review (fresh context; artifacts and checklist only)

The reviewer re-ran DRC and every check, and measured the copper with pcbnew. Their measurements match the gate:
- DRC 0 errors / 0 unconnected.
- In1, In3 and In4 each one piece with no tracks.
- Every power transfer is a via array, with the counts and drills verified.
- PGND single-point; the 1V1 ring and 3V3 band one piece each.
- Return-via distances match to 0.01 mm, and the residual list is complete.

They judged the 1.0 / 1.5 mm limits reasonable. Verdict: **pass with conditions**.

| # | Finding | Status |
|---|---|---|
| M1 | WL_CLK via (100.45,102.30) 2.91 mm from GND. It is in a 6-via chain (TAC_CS1, WL_DATA, WL_CLK, SENS_EN, IMU_INT1, SDA) whose anti-pads merge into a ~1.0 × 3.8 mm slot on In1/In3/In4 at (99.96–100.95, 100.77–104.53). U24's no-via box ends 0.2 mm west; the pin column starts 0.6 mm east. Fix: shift U24 ~1 mm (phase 6) to free a GND via spot near (99.9,102.3), or a user waiver | open: user decision |
| M2 | QSPI_SCLK/SD0/SD3 (8–13 mm on In2) and WL_DATA's In2 hop change reference GND↔VSYS at both ends, with no VSYS–GND cap within 11.5–14.4 mm and no GND via within 1.3–2.5 mm. Fix: **two** 100 nF VSYS–GND caps, one at each end (near (101.6,97.3) by C91 and near (94.6,101.5) west of U6), or move the three lanes to B.Cu | open: user decision (schematic change, or a re-route) |
| m1 | VBUS entry via (86.56,85.88) 0.205 mm copper-to-edge, at the 0.2 mm fab limit | open: pull ≥ 0.1 mm inboard with the next re-route |
| m2 | RP2350 pin 1 IOVDD stub touches the 3V3 band over 0.026 mm² (pin 11: 0.055 mm²) | open: extend the stubs ≥ 0.3 mm into the band (next re-route) |
| m3 | check_current.py exempts tracks ≤ 1 mm on ANY pad, not only fine-pitch ones. Without it: VBUS 0.88 A, VBAT 0.79 A, VSYS-OUT 1.18 A, all at the 0.25 mm QFN pin tips; the pwr_ zones overlap the pins by only 0.12–0.15 mm | open: tighten the exemption to FINE_PAD and extend the zones over the full pins (next re-route) |
| m4 | C12 6.6 mm from U2.2 (m17) | open, phase 6 |
| m5 | 71 right-angle joints; hairpin RUN (106.87,108.23); doubled stubs VBUS (93.90,106.80), VBAT (94.00,86.50), (94.88,84.36) | open: clean-up pass |
| m6 | USB ESD taps 5.5 / 9.1 mm on In2 over VSYS | open: USB LAYER_RULES (follow-up) |
| N | TAC_CS5 8.3 mm on In2 at x 113.65, outside the planes, 0.275 mm from the edge; XIN 5.2 mm; stitching residuals waivable; motor bars under USB-C acceptable; parity names cheap to label; outer GND pours have no orphans | noted |

Reviewer's conditions before fab:
1. Two VSYS–GND 100 nF caps at the ends of the In2 QSPI lanes, or the lanes moved to B.Cu.
2. A GND via spot beside WL_CLK's via, freed by a small U24 shift, or a user-signed waiver.
3. The pin-1 / pin-11 3V3 stubs extended into the band.
4. The VBUS entry via moved off the 0.2 mm edge limit, and the pad-entry exemption tightened.

Items 1–3 change routing: re-run DRC and the three checks after them, but no full re-review is needed.

## Submission 1: independent review (fresh context; artifacts and checklist only)

Findings as reported, each with its status. B = BLOCKER, M = MAJOR, m = MINOR.

| # | Finding | Status |
|---|---|---|
| B1 | In3 VSYS pour fills as 2 pieces (583 + 176 mm², confirmed), joined to the charger by 0.24–0.32 mm necks. 312 mm of signal wire on In3 (TAC_SDO 37.6, VBUS 33.2, TAC_SDI 32.7, WL_CS 22.8, TAC_SCK 18.5, TAC_CS4 16.4, WL_CLK 15.6, RUN 15.4 mm …). | open |
| B2 | Motor VSYS feed to J4.1 (2 A) through single vias at each transfer. | open |
| B3 | MOTOR1_SW / MOTOR2_SW: one via each into J4 (on the back) for 1 A. | open |
| B4 | VBUS (1 A) reaches U2.13 through one 0.2 via; 33 mm on In3 at 0.4 mm (≈0.75 A), 8 vias along the way. | open |
| B5 | VBAT cell path: one 0.25 via (stackup.md itself asks for 2); 0.3 mm on F.Cu. | open |
| M6 | In1 LX cut-out 1.7 × 5.4 mm, larger than LX + L1's pad; the In2 VBAT sense trace (to R60/R61, 500 kΩ source) crosses it 0.65 mm under the switch node; VREG_AVDD on F.Cu crosses its edge. | open |
| M7 | Return vias missing at fast-net layer changes (above). Also 63 of 69 signal vias that move the return between In1 and In4 have no GND via within 1 mm. | open |
| M8 | WL_CLK (gSPI, ≤ 50 MHz) runs 15.6 mm on In3, 0.109 mm under In2 traffic. | open |
| M9 | In2 ↔ In3 are 0.109 mm apart (0.55 mm cores to In1 / In4), so In2 signals reference the cut-up In3 pour, not In1. QSPI SCLK/SD0/SD3 on In2 are over VSYS copper for only 28–36 % of their length, with broadside parallel runs at 0.109 mm. `check_planes.py`'s reference map is wrong for In2/In3. | open |
| M10 | GND stitching far below stackup.md's "2 mm": 102 GND vias, edge gaps up to 15 mm, 26 % of the board > 2 mm from a GND via (worst 5.2 mm at (86.2,111.5)). | open |
| M11 | RM2 VIN (U7.16) on one 0.2 via; its 10 µF (C100) 6 mm away. | open |
| M12 | Check-script gaps: pours counted as unlimited capacity; VSYS fill pieces not checked; voids informational only; wrong In2/In3 references; return-via test only on fast nets; no stitching-density check. | open |
| m13 | 36 right-angle bends and 7 acute or doubled joints (U2 pad stubs, MOTOR1_SW at (100.0,120.31), QSPI_SS at (98.55,103.2)). | open |
| m14 | B.Cu GND pour in 23 pieces, 4 unconnected around U22/U20; F.Cu sliver at (113.2–113.6,107.3–108.9). | open |
| m15 | USB_DM joins J1 A7/B7 through 4 vias and a 2.9 mm In3 hop (DP uses 2). | open |
| m16 | XIN 5.2 mm against the 5 mm limit in nets.csv. | open |
| m17 | C12 6.6 mm from U2.2; C100 6 mm from U7.16. | open |
| m18 | Silk warnings not explained in the gate file. | explained above, phase 9 |
| m19 | MOTOR1_SW runs 4.6 mm under the USB-C body, 0.2 mm from a shell pad: legal but uninspectable. | open |

Reviewer's notes (no action): parity differences are name-only; RF keep-out clean on all six layers; RM2 body has a GND pour with a 3 × 3 via grid and no F.Cu tracks under it; PGND single return point verified; crystal block clean apart from m16; DRC 0/0, ERC 0/0.

Verdict (reviewer): **fail**. In3 must become a power layer again, every power transition needs a via array, and the check methods must be corrected before resubmission.

### Fix plan (submission 1)

1. **In3 carries VSYS only** (B1, M8, M9, part of B4): forbid signal routing on In3 in the DSN. In2 then takes the overflow over In1, and the In3 pour becomes a solid VSYS plane. WL_CLK's In3 pre-route moves to In2 or F.Cu.
2. **Via arrays at every power transition** (B2–B5, M11), sized from stackup.md (0.2 mm drill ≈ 0.8 A, × 1.5 margin):
   - in the pads: J4.1 (≥ 4), J4.2 / J4.3 (≥ 3 each), J2.1 (≥ 3), U7.16 (2)
   - beside U2's VBUS / VBAT / VSYS pins
   - locked before freerouting, as pre-routes
3. **VBUS** (B4): a pour or a ≥ 0.6 mm outer-layer trace from the receptacle up the left edge to the charger, with ≥ 2 vias at every transfer. It is no longer on In3.
4. **Return vias** (M7): a GND via within 1 mm of every signal via that moves between In1 and In4; first the USB pair's four and WL_CLK's two.
5. **LX cut-out** (M6): shrink to LX + L1's pad as the chip notes say; keep VBAT_SENSE and VREG_AVDD over solid GND.
6. **Stitching** (M10): an edge ring at ≤ 3 mm pitch plus stitching around the crystal, motor block and RM2 pad row.
7. **Checks** (M12): `check_current.py` rates pours by their fill (a neck width from the deflated fill); `check_planes.py` gets the true In2/In3 references, checks the VSYS fill is one piece, and flags all return vias; `audit.py` checks stitching density.
8. **Minor** (m13–m17, m19): cleanup pass after re-routing; the right-angle bends are mostly freerouting's.
9. **Parity names**: label the 24 nets in the schematic (`SCH_NAME_LOCAL_NETS`) so KiCad's parity is also clean, or keep the waiver; user's call (it reverses an earlier schematic-review decision to keep block-internal nets unlabelled).

Then re-route, re-run every check, and re-review.
