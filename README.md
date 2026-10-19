# bluebuzz-rm2

A Bluetooth vibrator controller: RP2350A + Raspberry Pi Radio Module 2
(the first board, an nRF52840 module, is abandoned and kept in
`archive/nrf52840/`):
Wi-Fi 4 and Bluetooth 5.2 Classic + LE (CYW43439), so the toy can be a
Bluetooth **A2DP audio sink** (BTstack, in the Pico SDK) as well as a
BLE-controlled device, and a **USB audio device** (TinyUSB) over its USB-C.
**28 x 44 mm, 6 layers.** Every component is on the front except the
sensing array; USB-C on the bottom (short) edge is the one connector (the
top edge is the RM2's RF keep-out); every other lead is an SMT pad row on
the back, each row a single line along an edge so a soldering iron
reaches one pad without bridging the next.

Sensing is a **2 x 2 array of Infineon DPS368 barometers on the back**,
6 x 8 mm pitch, meant to be cast in soft elastomer after Tenzer, Jentoft
& Howe, *The Feel of MEMS Barometers* (IEEE RAM 2014): rubber poured over
the array and vacuum degassed so it fills the pressure ports, after which
a load on the surface reads as pressure, linear to under 1 %, with 10 mN
resolution. Each sensor is on SPI1 with its own chip select (CSB low at
power-up selects SPI; the part has only two I2C addresses), on the
switched 3.3 V rail, 100n beside it. The array size is a table in
`design.yaml` (`tactile:` rows, cols, pitch) and `circuit.py`'s
`TACTILE`; the schematic, placement and firmware pin map follow it. An
**LSM6DS3TR-C IMU** on I2C1 sits at the left edge on the always-on rail,
with both interrupts on GPIOs for wake-on-motion.

Same pipeline as the parent (`python3 build.py` here; the `site` stage
rebuilds board `b` of the parent's `pcbview.toml`), with additions this
denser board forced: `route.py` hands freerouting a tamed DSN (GND
removed from its netlist since planes and pours carry it, the plane
layers marked unroutable, its fixed GND copper turned into keepouts),
lays the nets freerouting never closed by hand (the six QSPI lines, VBAT,
PG_N, the PWM and SWD hops, the USB climb, LX, WL_CS, the RP2350's lone
GND pin), draws every hand-laid bend at 45 degrees, and after routing
puts a via in every GND pad it can (cutting freerouting's wires from
under the ones it walled off; the finish stage re-closes them). The
stackup is six layers (GND / signal / VSYS pour / GND inside) because
four left 40-55 connections open. `ROUTE_DRY=1 python3 scripts/route.py`
lays only the locked pre-routes, for a quick DRC of them.

## What it is

| | |
|---|---|
| Host | RP2350A (QFN-60), Raspberry Pi's minimal design: 3.3 µH core buck, 12 MHz crystal (12 pF CL, 18 pF loads), W25Q32JVUUIQ 32 Mbit QSPI flash (3 x 4 USON), 27 R USB series, 10k/100n on RUN |
| Radio | RM2 (RMC20452T): gSPI with CS 25 as the Pico W, WL_ON on GPIO27, DATA on GPIO2 and CLK on GPIO3 (the board header overrides the SDK's defaults), DOUT via 470 R and nIRQ via 10 k into DATA. Vin from **VSYS** (3.0–4.8 V), VDDIO 3.3 V. Antenna end at the top board edge; the datasheet's RF keep-out is the top 5 mm of the board on every layer |
| Power | BQ24074 charger with power path (VBUS from the USB-C), TLV75533 3.3 V, TPS22918 switched sensor rail (GPIO4). /PGOOD → GPIO9 (the RP2350 has no VBUS detect) |
| Motors | two AO3400A low-side channels (GPIO13, GPIO17), 100 R gate / 100k pull-down, B5819W flybacks, 2 x 22 µF; pads VSYS M1 M2; 1 A per channel, fine for 3.7 V vibration motors |
| Touch | 4 x DPS368 on the back (SPI1: GPIO10 SCK, 11 SDI, 12 SDO; CS GPIO13-16), switched rail |
| Motion | LSM6DS3TR-C on I2C1 (GPIO6/7, 4.7k pull-ups), INT1/INT2 on GPIO5/18, CS high (I2C), SA0 low (0x6A), always on |
| UI | side button GPIO8, status LED GPIO22, charge LED on /CHG; battery 1M/1M into ADC0 = GPIO26 |
| USB | USB-C receptacle on the bottom edge, 5.1k on each CC, USBLC6-2P6 ESD, 27 R series at the chip |
| Pads (back, 1.6 x 2.2 mm at 2.0 mm) | top: **BAT** + - · bottom-left: **MOT** VSYS M1 M2 · under the radio: **SWD** SWDIO SWCLK RUN BOOT GND (pogo) |

## Programming

Bridge the **BOOT** pad to the **GND** pad beside it while applying
power (or call `reset_usb_boot()` from firmware) and the RP2350
enumerates as a UF2 drive on the USB-C. SWD on the same pad row for
debugging. Firmware: Pico SDK with `PICO_CYW43_SUPPORTED` and a board file
setting `CYW43_DEFAULT_PIN_WL_DATA_OUT/_IN/_HOST_WAKE = 2` and
`CYW43_DEFAULT_PIN_WL_CLOCK = 3`; BTstack's A2DP sink example is the
starting point for sound-to-vibration; the DPS368s through `spi1`, one
chip select at a time, in background mode at the rate the elastomer
response needs (the paper sampled at 100 Hz per sensor).

## Casting the array

Per the paper: a two-part room-temperature polyurethane (they used
VytaFlex 20, E ≈ 280 kPa) poured over the back of the board to 4-10 mm
over the sensors, then the mould placed in a vacuum chamber immediately
so the air trapped in the sensor ports is pulled out and the rubber
fills them; thinner rubber is more sensitive (1380 counts/N at 4 mm vs
165 at 10 mm for their sensor), thicker spreads the response. Solder the
BAT and MOT leads before casting; the SWD pads under the radio can stay
outside the cast area.

## Before ordering

- The **RM2 is not an LCSC part**: Raspberry Pi approved resellers; consign
  it at JLCPCB or solder it by hand (castellated, 1.5 mm pitch).
- The RM2 footprint was drawn from the datasheet's figure 6 (release 7,
  2026-02, `docs/RM2-datasheet.pdf`); check it against a module in hand.
- The DPS368 footprint is the LCSC/EasyEDA land for C3232508 (two
  columns of four 0.6 x 0.4 mm pads, 0.65 mm pitch, 1.45 mm apart);
  check it against Infineon's drawing. Pin 1 is the top-right pad.
- The DPS368 and the LSM6DS3TR-C are JLCPCB "extended" parts (a loading
  fee each per order). DPS368: $4.21 at 1-9, $3.60 at 10+ (2026-10).
- The flash is the 3 x 4 mm W25Q32JVUUIQ because the 2 x 3 mm 16 Mbit
  part had no stock; its KiCad land is by package name, check it against
  Winbond's drawing.
- No 3D models for the RM2 (not on LCSC) and the core inductor (LCSC
  land differs from KiCad's); the viewer draws boxes for them.
