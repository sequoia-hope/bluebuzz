# Architecture — bluebuzz-rm2

```mermaid
flowchart LR
  USB[USB-C J1<br/>bottom edge] -->|VBUS 5 V| ESD[USBLC6-2 U10<br/>C2 100n]
  ESD -->|VBUS| CHG[BQ24074 U2<br/>charger + power path<br/>ISET 500 mA, ILIM 1 A]
  USB -->|D+ D-| ESD
  ESD -->|D+ D- via R3 R4 27 R| MCU
  BAT[BAT pads J2<br/>1-cell LiPo] <-->|VBAT| CHG
  CHG -->|VSYS 3.0-4.4 V<br/>In3 pour| LDO[TLV75533 U3<br/>3V3_SYS 500 mA]
  CHG -->|VSYS| MOT[2 x AO3400A Q1 Q2<br/>B5819W D3 D4<br/>22u + 100n each]
  CHG -->|VSYS| RM2[RM2 U7<br/>CYW43439<br/>antenna at top edge]
  CHG -->|/PGOOD| MCU
  CHG -->|/CHG| LED1[CHG LED D1]
  LDO -->|3V3_SYS| MCU[RP2350A U1<br/>1V1 buck via L1<br/>12 MHz Y1<br/>W25Q32 U6]
  LDO -->|3V3_SYS| RM2
  LDO -->|3V3_SYS| IMU[LSM6DS3TR-C U30<br/>I2C1, INT1/2]
  LDO -->|3V3_SYS| SW[TPS22918 U5<br/>switched rail]
  SW -->|3V3_SENS| TAC[4 x DPS368 U20-U23<br/>on the back, SPI1<br/>one CS each]
  MCU -->|SENS_EN GPIO4| SW
  MCU -->|PWM GPIO13/17| MOT
  MOT -->|VSYS M1 M2| MOTP[MOT pads J4]
  MCU <-->|gSPI GPIO2/3/23/25| RM2
  MCU <-->|SPI1 GPIO10-16| TAC
  MCU <-->|I2C1 GPIO6/7, INT 17/18| IMU
  MCU -->|LED GPIO22| LED2[STAT LED D2]
  BTN[Button SW1] -->|GPIO8| MCU
  MCU <-->|SWDIO SWCLK RUN BOOT| SWD[SWD pogo pads J3<br/>back, under the RM2]
  VBAT -.->|1M/1M -> ADC0| MCU
```

Every block is one region of the single generated schematic sheet (`scripts/gen_schematic.py` `blk_*`) and one placement region (`scripts/place.py`):

| Block | Parts | Schematic block | Board region |
|---|---|---|---|
| USB-C + ESD | J1, U10, C2, R1, R2, R3, R4 | blk_usb | bottom-right (R3/R4 at the MCU's USB pins) |
| Charger | U2, R10-R13, C10-C15, D1, R14, J2 | blk_charger | top-left |
| LDO | U3, C20-C22 | blk_ldo | left, below the charger |
| Switched rail | U5, C50-C52, R50 | blk_sense | left, below the LDO |
| Motors | Q1, Q2, R40-R43, D3, D4, C40-C43, J4 | blk_motor | bottom-left |
| Tactile array | U20-U23, C120-C123 | blk_tactile | back, left of centre |
| IMU | U30, C130-C132, R130, R131 | blk_imu | left edge, middle |
| Host | U1, L1, C80-C96, R84, R85, Y1, C86, C87, R86, U6, C88, R87, R88, C89, R60, R61, C64, J3 | blk_mcu, blk_flash, blk_swd | centre-right |
| Radio | U7, R80, R81, C100-C102 | blk_radio | top-right |
| UI | SW1, D2, R62 | blk_ui | left edge, bottom |
