"""
Work out which FDC2214 input reaches which physical sensor on the plate.

The schematic says which chip input goes to which connector pin, but not which
pad on the plate that pin ends up at. So we measure it: press one sensor, see
which channel moves, and record that.

    python fdc_identify.py              # press sensors 1..8 when prompted

Writes forceplate_map.json, which fdc_plot.py then uses for its labels.
Close the live plot first -- only one program can hold the COM port.
"""
import argparse
import json
import math
import statistics
import sys
import time

import matplotlib
matplotlib.use("Agg")           # no window needed; this is a console tool

from fdc_plot import CHANNELS, CH_NAMES, MAP_FILE, Stream, find_port

SETTLE_S = 1.0          # ignore the first moment after a prompt
MEASURE_S = 2.0         # how long to watch while the sensor is pressed
MIN_SHIFT_PF = 0.05     # smaller than this is not a real press


def mean_of(values):
    clean = [v for v in values if not math.isnan(v)]
    return statistics.fmean(clean) if clean else math.nan


def collect(stream, seconds):
    """Average each channel over a window, returning one value per channel."""
    time.sleep(seconds)
    _, pf = stream.snapshot()
    n = max(1, int(seconds * 80))           # roughly the samples in that window
    return [mean_of(series[-n:]) for series in pf]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port")
    ap.add_argument("--baud", type=int, default=460800)
    ap.add_argument("--sensors", type=int, default=CHANNELS,
                    help="how many sensors to identify")
    args = ap.parse_args()

    stream = Stream(find_port(args.port), args.baud, 10, 100, "identify_log.csv")
    print("Connecting...")
    time.sleep(2.0)
    if not stream.snapshot()[0]:
        sys.exit("No data from the board. Is the live plot still holding the port?")

    raw_names = list(stream.names)
    names = list(raw_names)
    taken = {}

    print("\nPress and HOLD one sensor at a time when prompted, then release.\n")
    for sensor in range(1, args.sensors + 1):
        input(f"  Sensor {sensor}: release everything, then press Enter...")
        baseline = collect(stream, SETTLE_S)

        input(f"  Now press and HOLD sensor {sensor}, then press Enter...")
        pressed = collect(stream, MEASURE_S)

        shifts = []
        for i in range(CHANNELS):
            if math.isnan(baseline[i]) or math.isnan(pressed[i]):
                shifts.append(0.0)
            else:
                shifts.append(abs(pressed[i] - baseline[i]))

        order = sorted(range(CHANNELS), key=lambda i: shifts[i], reverse=True)
        best = order[0]
        runner_up = order[1]

        if shifts[best] < MIN_SHIFT_PF:
            print(f"    no channel moved more than {MIN_SHIFT_PF} pF - skipping. "
                  f"Press harder, or check that sensor's wiring.\n")
            continue
        if best in taken:
            print(f"    {raw_names[best]} already mapped to sensor {taken[best]}; "
                  f"skipping. Two sensors reading the same channel means a "
                  f"wiring or connector problem.\n")
            continue

        # A clear winner matters: if second place is close, the press probably
        # loaded two pads at once and the mapping would be a guess.
        margin = shifts[best] / shifts[runner_up] if shifts[runner_up] > 0 else math.inf
        confidence = "clear" if margin >= 3 else "WEAK - press only one pad"
        print(f"    sensor {sensor} -> {raw_names[best]} "
              f"({shifts[best]:.3f} pF, {confidence})\n")

        names[best] = f"S{sensor}"
        taken[best] = sensor

    stream.close()

    with open(MAP_FILE, "w") as fh:
        json.dump({"names": names,
                   "raw": raw_names,
                   "made": time.strftime("%Y-%m-%d %H:%M:%S")}, fh, indent=2)

    print(f"Saved {MAP_FILE}:")
    for raw, shown in zip(raw_names, names):
        print(f"  {raw:8s} -> {shown}")
    print("\nRestart fdc_plot.py to see the new labels.")


if __name__ == "__main__":
    main()
