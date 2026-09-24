# Blade-Insole

Capacitive force-sensing plate: hardware design, firmware and data-capture tools.

## Hardware

- **`ProPrj_Shoeshem Main Board_*.epro2`** — EasyEDA Pro projects for the rigid PCB.
- The sensor board carries two **TI FDC2214** capacitance-to-digital converters
  (4 channels each, 8 sensors total). Each channel is an LC tank — 18 µH with
  33 pF — with an actively driven shield.
- A **NUCLEO-WB55RG** plugs into the Arduino headers and reads both chips.

| PCB signal | Nucleo pin | MCU pin | Purpose |
|---|---|---|---|
| SDA | D14 | PB9 | I²C data, both chips |
| SCL | D15 | PB8 | I²C clock |
| CLKIN1 + CLKIN2 | D6 | PA8 | 32 MHz reference clock out (MCO) |
| INTB1 / INTB2 | D8 / D9 | PC12 / PA9 | data-ready (unused; the firmware polls) |
| SD1 / SD2 | A0 / A4 | PC0 / PC3 | shutdown, one per chip |

U1 drives sensor connector 1 and has ADDR tied high (I²C address `0x2B`);
U2 drives connector 2 with ADDR low (`0x2A`).

## Firmware (`firmware/`)

Bare-metal C for the STM32WB55's Cortex-M4 — no HAL and no CubeMX project, so
it builds from five short files with the compiler that ships inside STM32CubeIDE.

It starts the 32 MHz crystal and feeds it to both chips' CLKIN, brings up I²C1,
finds the chips (trying 400/100/50/20 kHz in turn, since the board has no
pull-up resistors), configures all 8 channels for continuous scanning, and
streams CSV over the ST-LINK virtual COM port at **460800 baud, 100 Hz**:

```
# header lines describing the clock, the chips found and the column names
t_ms,ch0,ch1,ch2,ch3,ch4,ch5,ch6,ch7      <- raw 28-bit counts
```

Counts are converted to capacitance on the PC, so the maths can change without
reflashing.

```powershell
cd firmware
.\build.ps1 -Flash
```

## Tools (`tools/`)

```powershell
pip install -r tools/requirements.txt
```

| Script | What it does |
|---|---|
| `fdc_plot.py` | Live graph of all 8 channels in pF, with a clickable sensor key and a baseline/current/change readout. Logs every sample to `forceplate_<date>.csv`. |
| `live_force.py` | Live force for a single sensor, using its weight calibration. Tare with `t`. |
| `force_vs_time.py` | Renders force vs time from a recorded CSV, plus the calibration curve it used. |
| `fdc_identify.py` | Works out which chip input reaches which physical sensor: press each pad when prompted, and it writes `forceplate_map.json`. |

`forceplate_map.json` maps columns to sensor names and records which channels
to hide. `sensor_calibration.json` holds the weights applied to each sensor and
the capacitance they produced; force is interpolated between those points.

## Notes from bring-up

- Resting capacitance runs 95–107 pF per channel (the 33 pF tank plus the
  electrode). Noise is about 0.01–0.06 pF, roughly 1 part in 10,000.
- The response is **not linear**. On Cap 7, the first 28 kg moved it 2.04 pF,
  but each further 10 kg added only ~0.18 pF.
- The sensors show **hysteresis**: after a heavy load they read high until they
  recover. Unload and re-tare before each measurement, and calibrate with a
  consistent procedure.
- The chips are detected and configured only at reset, so **press RESET after
  swapping sensor boards**, or the new board reads zeros.
