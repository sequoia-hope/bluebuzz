#!/usr/bin/env python3
"""Circuit definition: components + nets for the bluebuzz-rm2 board.

The electrical source of truth. gen_schematic.py and gen_board.py consume
build_circuit(); nothing else decides connectivity.

The nRF52840 board's toy (archive/nrf52840/scripts/circuit.py) with the host and radio
changed: an RP2350A runs the show and a Raspberry Pi Radio Module 2
(CYW43439) is the radio, so the toy can be a Bluetooth A2DP audio sink and
a USB audio device as well as a BLE-controlled one. Every external lead
but USB is an SMT pad row on the back; USB-C is the one connector.

Decisions (the nRF board's Z1..Z5 still hold; new ones here):
  R1  The RM2 runs from VSYS (Vin 3.0-4.8 V), not the LDO: its 271 mA TX
      peaks are the biggest load after the motors and the TLV75533 is a
      500 mA part feeding the RP2350. VDDIO is 3V3_SYS. (RM2 datasheet 2.6)
  R2  gSPI: CS 25 as the Pico W, WL_ON on GPIO27 (pin 41, the right-column
      pin nearest the RM2's pads 12/13: the RP2350 regulator block, laid as
      Raspberry Pi's, now sits under those pads and GPIO23 could not reach
      them, 2026-10-18; the header overrides CYW43_DEFAULT_PIN_WL_REG_ON),
      DATA on GPIO2 and CLK on
      GPIO3 -- the RM2's DIN/DOUT/SCLK pads are on its LEFT column, which
      faces the top-left of the RP2350, where GPIO2/3 are; GPIO24/29 are on
      the chip's right side and the run around its top could not be
      closed. The board header overrides CYW43_DEFAULT_PIN_WL_DATA_OUT /
      _DATA_IN / _HOST_WAKE (all GPIO2) and _WL_CLOCK (GPIO3); the PIO
      program takes any two pins. DOUT and nIRQ join DATA through 470 R and
      10 k as the datasheet's table 1.
  R3  The RP2350 core follows RP-006440: 3.3 uH on VREG_LX, 4.7 u on the
      1.1 V output and at DVDD, 100 n at the third DVDD, 4.7 u on VREG_VIN,
      VREG_AVDD through 33 R + 4.7 u, ADC_AVDD through 10 R + 1 u, 27 R in
      each USB line, 12 MHz crystal with 1 k in series with XOUT, 10 k + 100 n
      on RUN, QSPI_SS to a BOOT pad through 1 k.
  R4  The crystal is the reference design's ABM8-272-T3 (CL 10 pF, 50 ohm)
      with its 15 pF loads and 1 k in XOUT: the only validated circuit.
  R5  USB presence comes from the charger's /PGOOD on GPIO9: the RP2350 has
      no VBUS detect, and GPIO24 (the Pico's VBUS divider) is the RM2 data.
  R6  BOOTSEL is a pad (QSPI_SS via 1 k): bridge it to the GND pad beside it
      while applying power to enter the UF2 bootloader; firmware can also
      reboot into it (reset_usb_boot). RUN is a pad too. No reset button.
  R7  Pad rows, back side, 1.6 x 2.2 mm at 2.0 mm pitch: SWD (pogo),
      battery, motors, load cell, pressure (soldered). USB keeps its
      USB-C receptacle (user's call), on the left edge: the top edge is
      the RM2's keep-out.
  R8  The flash is the 32 Mbit USON-8 3x4 (W25Q32JVUUIQ): the 2x3 16 Mbit
      part had no stock anywhere at LCSC, and the SOIC alternative is
      5.3 x 5.3 mm on a board that is trying to be small.

Pin data verified against: RP2350 datasheet via servodrive's control()
block, RM2 datasheet release 7 (docs/), TI SLUS810 / SBVS320D / SLVSD76C,
Infineon DPS368, ST LSM6DS3TR-C, ST USBLC6-2, AOS AO3400A, Winbond W25Q.
"""
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Component:
    ref: str
    part: str
    value: str
    footprint: str = ""
    pins: dict = field(default_factory=dict)   # pad number -> net name


@dataclass
class Circuit:
    components: dict = field(default_factory=dict)
    design: dict = field(default_factory=dict)

    def add(self, ref, part, value, pins):
        assert ref not in self.components, f"duplicate ref {ref}"
        c = Component(ref, part, value, pins={str(k): v for k, v in pins.items()})
        self.components[ref] = c
        return c

    @property
    def nets(self):
        nets = {}
        for c in self.components.values():
            for pad, net in c.pins.items():
                if net:
                    nets.setdefault(net, []).append((c.ref, pad))
        return nets


# ---------------------------------------------------------------------------
# RP2350A QFN-60 pin map (RP2350 datasheet; servodrive's control() block).
# ---------------------------------------------------------------------------
GPIO_PINS = {g: p for g, p in zip(range(26), [2, 3, 4, 5, 7, 8, 9, 10, 12, 13, 14, 15,
                                               16, 17, 18, 19, 27, 28, 29, 31, 32, 33,
                                               34, 35, 36, 37])}
GPIO_PINS.update({26: 40, 27: 41, 28: 42, 29: 43})
IOVDD_PINS = (1, 11, 20, 30, 38, 45, 54)
DVDD_PINS = (6, 23, 39)

# GPIO roles
ROLE = {
    # (2026-10-18) the motor PWMs leave from the bottom pin row, toward
    # their gates at the bottom corners, and TAC_CS1 takes GPIO0 on the top
    # left, toward its sensor: on GPIO0/1 the PWMs crossed the whole board
    # and their hop vias held two of the few via spots in the lane down the
    # chip's left side (WL_DATA then had no way out in any ordering)
    0: "TAC_CS1",         # one chip select per sensor (the DPS368 has only
                          # two I2C addresses; SPI needs no multiplexer)
    2: "WL_DATA",         # RM2 pin 5 (DIN); DOUT and nIRQ join through R80/R81
    3: "WL_CLK",          # RM2 pin 3
    4: "SENS_EN",         # -> TPS22918 ON
    6: "SDA",             # I2C1 -> the IMU
    7: "SCL",
    8: "BTN",             # user button, internal pull-up
    9: "PG_N",            # <- charger /PGOOD (R5)
    10: "TAC_SCK",        # SPI1 to the tactile array (the DPS368s' SCK)
    11: "TAC_SDI",        # SPI1 TX -> SDI
    12: "TAC_SDO",        # SPI1 RX <- SDO
    13: "MOTOR1_PWM",     # pin 17, PWM slice 6 B
    14: "TAC_CS2",
    15: "TAC_CS3",
    16: "TAC_CS4",
    5: "IMU_INT1",        # pin 8, beside SDA/SCL on the IMU's side (was GPIO17
                          # on the bottom edge: no route round the chip)
    17: "MOTOR2_PWM",     # pin 28, PWM slice 0 B
    18: "IMU_INT2",
    19: "PWR_HOLD",       # soft power latch: high keeps the LDO enabled
    20: "TAC_CS5",        # the fifth (centre) tactile sensor
    22: "LED_STAT",       # pin 34, on the side facing D2 (was GPIO5 on the far
                          # side: no route around the RP2350, 2026-10-18)
    27: "WL_ON",          # RM2 pins 12 + 13 (R2)
    25: "WL_CS",          # RM2 pin 9
    26: "VBAT_SENSE",     # ADC0
}

# the tactile array: rows x cols of DPS368 barometers on the BACK of the
# board, cast in soft elastomer (Tenzer, Jentoft & Howe 2014, "The Feel of
# MEMS Barometers"); the sensor refs and their 100n, in row-major order
# four toward the board corners and one in the centre (user, 2026-10-18)
TACTILE_COUNT, TACTILE_COLS = 5, 2
TACTILE = [(f"U{20 + k}", f"C{120 + k}") for k in range(TACTILE_COUNT)]

# RM2 pad map -- datasheet release 7, table 2
RM2 = {
    1: "GND", 2: "", 3: "WL_CLK", 4: "GND", 5: "WL_DATA", 6: "WL_DOUT", 7: "GND",
    8: "",                       # module GPIO0, unused
    9: "WL_CS", 10: "WL_IRQ", 11: "GND", 12: "WL_ON", 13: "WL_ON",
    14: "3V3_SYS",               # VDDIO
    15: "GND",
    16: "VSYS",                  # Vin 3.0-4.8 V (R1)
    17: "", 18: "",              # module GPIO2 / GPIO1, unused
    19: "", 20: "", 21: "GND",
}


def load_parts():
    return yaml.safe_load((ROOT / "bom" / "parts.yaml").read_text())


def load_design():
    return yaml.safe_load((ROOT / "design.yaml").read_text())


def build_circuit(design=None):
    design = design or load_design()
    parts = load_parts()
    c = Circuit(design=design)

    # =====================================================================
    # Block 1 -- USB-C and ESD (the one connector on the board)
    # =====================================================================
    c.add("J1", "usb_conn", "USB-C", {
        "A1": "GND", "A12": "GND", "B1": "GND", "B12": "GND",
        "A4": "VBUS", "A9": "VBUS", "B4": "VBUS", "B9": "VBUS",
        "A5": "CC1", "B5": "CC2",
        "A6": "USB_DP", "B6": "USB_DP",
        "A7": "USB_DM", "B7": "USB_DM",
        "A8": "", "B8": "",
        "S1": "GND",
    })
    c.add("R1", "r_5k1", "5.1k", {1: "CC1", 2: "GND"})
    c.add("R2", "r_5k1", "5.1k", {1: "CC2", 2: "GND"})
    c.add("U10", "usb_esd", "USBLC6-2P6", {
        1: "USB_DP", 6: "USB_DP", 3: "USB_DM", 4: "USB_DM", 5: "VBUS", 2: "GND",
    })
    c.add("C2", "c_100n", "100n", {1: "VBUS", 2: "GND"})
    c.add("R3", "r_27", "27R", {1: "USB_DP", 2: "USB_DP_C"})     # R3: at the chip
    c.add("R4", "r_27", "27R", {1: "USB_DM", 2: "USB_DM_C"})

    # =====================================================================
    # Block 2 -- BQ24074 charger with power path
    # =====================================================================
    c.add("U2", "charger", "BQ24074RGT", {
        # EN2 on VSYS (not 3V3): the system can now be switched off, and the
        # charger must keep its 1 A ILIM mode (EN1 0, EN2 1) while it is
        1: "TS", 2: "VBAT", 3: "VBAT", 4: "GND", 5: "VSYS", 6: "GND",
        7: "PG_N", 8: "GND", 9: "CHG_N", 10: "VSYS", 11: "VSYS", 12: "ILIM",
        13: "VBUS", 14: "TMR", 15: "", 16: "ISET", 17: "GND",
    })
    c.add("R10", "r_1k78", "1.78k", {1: "ISET", 2: "GND"})
    c.add("R11", "r_1k62", "1.62k", {1: "ILIM", 2: "GND"})
    c.add("R12", "r_45k3", "45.3k", {1: "TMR", 2: "GND"})
    # TS: a fixed 10 k (always in the charge window) unless the cell has a
    # 10 k NTC on the BAT pads' T pad -- then R13 is left off (DNP)
    c.add("R13", "r_10k", "10k", {1: "TS", 2: "GND"})
    c.add("C10", "c_10u", "10u", {1: "VBUS", 2: "GND"})
    c.add("C11", "c_10u", "10u", {1: "VSYS", 2: "GND"})
    c.add("C12", "c_10u", "10u", {1: "VBAT", 2: "GND"})
    c.add("C13", "c_100n", "100n", {1: "VBUS", 2: "GND"})
    c.add("C14", "c_100n", "100n", {1: "VSYS", 2: "GND"})
    c.add("C15", "c_100n", "100n", {1: "VBAT", 2: "GND"})
    c.add("D1", "led", "CHG", {1: "CHG_LED", 2: "VSYS"})      # from VSYS: lights while the system is off
    c.add("R14", "r_330", "330R", {1: "CHG_LED", 2: "CHG_N"})
    c.add("J2", "pads_bat", "BAT", {1: "VBAT", 2: "GND", 3: "TS"})

    # =====================================================================
    # Block 3 -- system LDO (always on)
    # =====================================================================
    c.add("U3", "ldo", "TLV75533PDBV", {1: "VSYS", 2: "GND", 3: "LDO_EN", 4: "", 5: "3V3_SYS"})
    c.add("C20", "c_1u", "1u", {1: "VSYS", 2: "GND"})
    c.add("C21", "c_1u", "1u", {1: "3V3_SYS", 2: "GND"})
    c.add("C22", "c_10u", "10u", {1: "3V3_SYS", 2: "GND"})

    # =====================================================================
    # Block 4 -- motors: two low-side FET channels from VSYS
    # =====================================================================
    for n, (q, rg, rpd, d, cn) in enumerate(
            (("Q1", "R40", "R41", "D3", "C41"), ("Q2", "R42", "R43", "D4", "C43")), 1):
        c.add(q, "motor_fet", "AO3400A", {1: f"MOTOR{n}_G", 2: "GND", 3: f"MOTOR{n}_SW"})
        c.add(rg, "r_100", "100R", {1: f"MOTOR{n}_PWM", 2: f"MOTOR{n}_G"})
        # 4.7 k, not 100 k: RP2350 erratum E9 lets a Bank-0 input pad leak
        # ~120 uA and float to ~2.2 V, above the AO3400A's Vgs(th); <= 8.2 k
        # holds the gate low while GPIO13/17 are inputs (boot, BOOTSEL)
        c.add(rpd, "r_4k7", "4.7k", {1: f"MOTOR{n}_G", 2: "GND"})
        c.add(d, "motor_flyback", "B5819W", {1: "VSYS", 2: f"MOTOR{n}_SW"})
        c.add(cn, "c_100n", "100n", {1: "VSYS", 2: "GND"})
    c.add("C40", "c_22u", "22u", {1: "VSYS", 2: "GND"})
    c.add("C42", "c_22u", "22u", {1: "VSYS", 2: "GND"})
    c.add("J4", "pads_3", "MOT", {1: "VSYS", 2: "MOTOR1_SW", 3: "MOTOR2_SW"})

    # =====================================================================
    # Block 5 -- switched sensor rail
    # =====================================================================
    c.add("U5", "load_switch", "TPS22918DBVR", {
        1: "3V3_SYS", 2: "GND", 3: "SENS_EN", 4: "CT_SENS", 5: "3V3_SENS", 6: "3V3_SENS",
    })
    c.add("C50", "c_470p", "470p", {1: "CT_SENS", 2: "GND"})
    c.add("R50", "r_100k", "100k", {1: "SENS_EN", 2: "GND"})
    c.add("C51", "c_1u", "1u", {1: "3V3_SYS", 2: "GND"})
    c.add("C52", "c_10u", "10u", {1: "3V3_SENS", 2: "GND"})

    # =====================================================================
    # Block 6 -- the tactile array: DPS368 barometers on the switched rail
    # =====================================================================
    # Each sensor is on SPI (CSB low at power-up selects SPI; CSB high
    # would make it I2C) with its own chip select, VDD and VDDIO on
    # 3V3_SENS, one 100n beside it. The pressure port faces away from the
    # board, into the elastomer.
    for k, (u, cap) in enumerate(TACTILE, 1):
        c.add(u, "baro", "DPS368", {
            1: "GND", 2: f"TAC_CS{k}", 3: "TAC_SDI", 4: "TAC_SCK", 5: "TAC_SDO",
            6: "3V3_SENS", 7: "GND", 8: "3V3_SENS",
        })
        c.add(cap, "c_100n", "100n", {1: "3V3_SENS", 2: "GND"})

    # =====================================================================
    # Block 7 -- IMU: LSM6DS3TR-C on I2C1, always on
    # =====================================================================
    c.add("U30", "imu", "LSM6DS3TR-C", {
        # SDx/SCx (pins 2, 3: the aux I2C, unused) to GND -- inputs with no pull
        1: "GND", 2: "GND", 3: "GND", 4: "IMU_INT1", 5: "3V3_SYS", 6: "GND", 7: "GND",
        8: "3V3_SYS", 9: "IMU_INT2", 10: "", 11: "", 12: "3V3_SYS", 13: "SCL", 14: "SDA",
    })
    c.add("C130", "c_100n", "100n", {1: "3V3_SYS", 2: "GND"})     # VDD
    c.add("C131", "c_10u", "10u", {1: "3V3_SYS", 2: "GND"})       # VDD bulk
    c.add("C132", "c_100n", "100n", {1: "3V3_SYS", 2: "GND"})     # VDDIO
    c.add("R130", "r_4k7", "4.7k", {1: "3V3_SYS", 2: "SDA"})
    c.add("R131", "r_4k7", "4.7k", {1: "3V3_SYS", 2: "SCL"})

    # =====================================================================
    # Block 8 -- RP2350A: core regulator, decoupling, crystal, flash, USB, SWD
    # =====================================================================
    u1 = {}
    for p in IOVDD_PINS:
        u1[p] = "3V3_SYS"
    for p in DVDD_PINS:
        u1[p] = "1V1"
    u1.update({
        21: "XIN", 22: "XOUT", 24: "SWCLK", 25: "SWDIO", 26: "RUN",
        44: "3V3A", 46: "VREG_AVDD", 47: "GND", 48: "VREG_LX", 49: "3V3_SYS",
        50: "1V1", 51: "USB_DM_C", 52: "USB_DP_C", 53: "3V3_SYS",
        55: "QSPI_SD3", 56: "QSPI_SCLK", 57: "QSPI_SD0", 58: "QSPI_SD2",
        59: "QSPI_SD1", 60: "QSPI_SS", 61: "GND",
    })
    for g, net in ROLE.items():
        u1[GPIO_PINS[g]] = net
    for g, p in GPIO_PINS.items():
        u1.setdefault(p, "")
    c.add("U1", "mcu", "RP2350A", u1)
    # core buck (R3)
    c.add("L1", "core_inductor", "3.3u", {1: "1V1", 2: "VREG_LX"})
    c.add("C80", "c_4u7_sp", "4.7u", {1: "1V1", 2: "GND"})      # at the inductor
    c.add("C81", "c_4u7", "4.7u", {1: "1V1", 2: "GND"})      # at DVDD 23
    c.add("C82", "c_100n", "100n", {1: "1V1", 2: "GND"})     # at DVDD 39
    c.add("C83", "c_4u7_sp", "4.7u", {1: "3V3_SYS", 2: "GND"})  # VREG_VIN 49
    c.add("R84", "r_33", "33R", {1: "3V3_SYS", 2: "VREG_AVDD"})
    c.add("C84", "c_4u7", "4.7u", {1: "VREG_AVDD", 2: "GND"})
    # IOVDD decoupling, one per corner-ish
    for k in range(1, 7):
        c.add(f"C9{k}", "c_100n", "100n", {1: "3V3_SYS", 2: "GND"})
    # host audit: a seventh 100n so each IOVDD pin has its own (53/54 share),
    # and 100n on DVDD pin 6 (datasheet: 100n on the two DVDD pins nearest
    # the regulator, 39 and 6; 4.7u on the far one, 23)
    c.add("C97", "c_100n", "100n", {1: "3V3_SYS", 2: "GND"})
    c.add("C98", "c_100n", "100n", {1: "1V1", 2: "GND"})
    # ADC supply
    c.add("R85", "r_10", "10R", {1: "3V3_SYS", 2: "3V3A"})
    c.add("C85", "c_1u", "1u", {1: "3V3A", 2: "GND"})
    # crystal (R4)
    c.add("Y1", "crystal", "12MHz", {1: "XIN", 2: "GND", 3: "XTAL2", 4: "GND"})
    c.add("R86", "r_1k", "1k", {1: "XOUT", 2: "XTAL2"})
    c.add("C86", "c_15p", "15p", {1: "XIN", 2: "GND"})
    c.add("C87", "c_15p", "15p", {1: "XTAL2", 2: "GND"})
    # QSPI flash (R8)
    c.add("U6", "flash", "W25Q32JVUUIQ", {
        1: "QSPI_SS", 2: "QSPI_SD1", 3: "QSPI_SD2", 4: "GND",
        5: "QSPI_SD0", 6: "QSPI_SCLK", 7: "QSPI_SD3", 8: "3V3_SYS",
    })
    c.add("C88", "c_100n", "100n", {1: "3V3_SYS", 2: "GND"})
    c.add("R87", "r_1k", "1k", {1: "QSPI_SS", 2: "BOOTSEL"})          # (R6)
    # reset
    c.add("R88", "r_10k", "10k", {1: "3V3_SYS", 2: "RUN"})
    c.add("C89", "c_100n", "100n", {1: "RUN", 2: "GND"})
    # SWD / boot pads (R6, R7)
    c.add("J3", "pads_swd", "SWD", {1: "SWDIO", 2: "SWCLK", 3: "RUN", 4: "BOOTSEL", 5: "GND"})
    # Raspberry Pi Debug Probe: 3-pin JST-SH, footprint only (DNP), on the back
    c.add("J6", "debug_jst", "PROBE", {1: "SWCLK", 2: "GND", 3: "SWDIO", "MP": "GND"})
    # bring-up test pads on the back (pogo): the three rails a first power-up checks
    c.add("J5", "pads_tp", "TP", {1: "VSYS", 2: "3V3_SYS", 3: "1V1"})

    # battery sense (1M/1M into ADC0)
    c.add("R60", "r_1M", "1M", {1: "VBAT", 2: "VBAT_SENSE"})
    c.add("R61", "r_1M", "1M", {1: "VBAT_SENSE", 2: "GND"})
    c.add("C64", "c_100n", "100n", {1: "VBAT_SENSE", 2: "GND"})

    # button and status LED
    # soft power: SW1 puts VSYS on BTN_RAW; D5 ORs BTN_RAW and PWR_HOLD
    # (GPIO19) onto the LDO's EN (R63 holds it off). Press -> 3V3 up -> the
    # RP2350 boots and drives PWR_HOLD high -> released, it stays on; drive
    # PWR_HOLD low to switch off. Q3 reads the button onto GPIO8 (pull-up),
    # active low, so the 4.4 V node never reaches a GPIO.
    c.add("SW1", "button", "PWR", {1: "VSYS", 2: "BTN_RAW"})
    c.add("D5", "dual_schottky", "BAT54C", {1: "BTN_RAW", 2: "PWR_HOLD", 3: "LDO_EN"})
    c.add("R63", "r_100k", "100k", {1: "LDO_EN", 2: "GND"})
    # USB keeps the board on (user): VBUS -> D6 -> R66 100k -> EN, a 2:1
    # divider with R63 so EN stays < 6.0 V abs max even at the charger's
    # 10.5 V OVP (5 V USB -> 2.35 V on EN, > 1 V VHI). Flashing and SWD
    # then work without holding the button; firmware cannot switch off
    # while USB is present (it can still sleep).
    c.add("D6", "signal_diode", "1N4148WS", {1: "VBUS_EN", 2: "VBUS"})
    c.add("R66", "r_100k", "100k", {1: "VBUS_EN", 2: "LDO_EN"})
    c.add("Q3", "sig_fet", "2N7002", {1: "BTN_RAW", 2: "GND", 3: "BTN"})
    c.add("R64", "r_100k", "100k", {1: "BTN_RAW", 2: "GND"})
    # status: a 1010 addressable LED (WS2812B type) on GPIO22. Its supply is
    # VSYS through a second TPS22918 (U11) whose ON is 3V3_SYS, so the LED's
    # 0.35 mA idle current stops when the system is off. (One part instead of
    # a P-FET + N-FET + resistor, and already on the BOM.)
    # VSYS is 3.5-4.4 V in use (firmware cuts off at 3.5 V), inside its
    # 3.5-5.5 V range; DI's 0.7 x VDD threshold is <= 3.08 V.
    c.add("D2", "rgb_led", "XL-1010RGBC", {1: "", 2: "LED_VDD", 3: "GND", 4: "LED_DIN"})
    c.add("R62", "r_330", "330R", {1: "LED_STAT", 2: "LED_DIN"})
    c.add("C133", "c_100n", "100n", {1: "LED_VDD", 2: "GND"})
    c.add("U11", "load_switch", "TPS22918DBVR", {
        1: "VSYS", 2: "GND", 3: "3V3_SYS", 4: "", 5: "LED_VDD", 6: "LED_VDD",
    })

    # =====================================================================
    # Block 9 -- RM2 radio (R1, R2)
    # =====================================================================
    c.add("U7", "radio", "RM2", dict(RM2))
    c.add("R80", "r_470", "470R", {1: "WL_DOUT", 2: "WL_DATA"})
    c.add("R81", "r_10k", "10k", {1: "WL_IRQ", 2: "WL_DATA"})
    c.add("C100", "c_10u", "10u", {1: "VSYS", 2: "GND"})       # Vin, at pin 16
    c.add("C101", "c_100n", "100n", {1: "VSYS", 2: "GND"})
    c.add("C102", "c_100n", "100n", {1: "3V3_SYS", 2: "GND"})  # VDDIO, at pin 14

    for comp in c.components.values():
        comp.footprint = parts[comp.part]["footprint"]
    return c


if __name__ == "__main__":
    cir = build_circuit()
    nets = cir.nets
    print(f"{len(cir.components)} components, {len(nets)} nets")
    for n in sorted(nets):
        print(f"  {n:<12} {' '.join(f'{r}.{p}' for r, p in sorted(nets[n]))}")
