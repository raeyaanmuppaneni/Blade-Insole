"""
Force vs time for one sensor, from a recorded CSV and a weight calibration.

    python force_vs_time.py                      # Cap 7, latest recording
    python force_vs_time.py --sensor "Cap 7" --csv forceplate_20260921_160642.csv

Calibration points live in sensor_calibration.json (weights you applied and
the capacitance you read). Capacitance change is converted to force by
interpolating between those points, with zero change meaning zero force.
The sensor's response is strongly non-linear, so a single straight line
through the points would give nonsense near zero load.
"""
import argparse
import bisect
import csv
import glob
import json

import matplotlib.pyplot as plt

G = 9.81                    # kg -> N
BLUE = "#2a78d6"            # Cap 7's colour in the live graph (channel slot 1)
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e3e2de", "#fcfcfb"


def load_calibration(sensor, path="sensor_calibration.json"):
    with open(path) as fh:
        cal = json.load(fh)[sensor]
    base = cal["baseline_pF"]
    pts = sorted((p["current_pF"] - base, p["weight_kg"] * G) for p in cal["points"])
    return base, [(0.0, 0.0)] + pts, cal["points"]


def to_force(dc, table):
    """Piecewise-linear force (N) for a capacitance change (pF).

    Below zero change -> 0 N (drift, not pull). Beyond the heaviest weight,
    the last segment's slope is extended, which is a guess.
    """
    if dc <= 0:
        return 0.0
    xs = [p[0] for p in table]
    k = min(max(bisect.bisect_right(xs, dc), 1), len(table) - 1)
    (x0, y0), (x1, y1) = table[k - 1], table[k]
    return y0 + (y1 - y0) * (dc - x0) / (x1 - x0)


def read_recording(path, sensor):
    """Timestamps (s) and capacitance (pF) for one sensor, dropping garbled rows."""
    with open(path) as fh:
        rows = csv.reader(fh)
        head = next(rows)
        col = head.index(f"{sensor}_pF")
        t, c, last = [], [], None
        for row in rows:
            try:
                ts, val = int(row[0]) / 1000.0, float(row[col])
            except (ValueError, IndexError):
                continue
            # A partial line can glue digits together into an absurd timestamp;
            # accept only small forward steps.
            if last is not None and not (0 < ts - last < 1.0):
                continue
            t.append(ts)
            c.append(val)
            last = ts
    return t, c


def moving_average(values, n):
    out, acc = [], 0.0
    for i, v in enumerate(values):
        acc += v
        if i >= n:
            acc -= values[i - n]
        out.append(acc / min(i + 1, n))
    return out


def find_plateau(t, c, target, tol=0.02, min_s=10.0):
    """Middle of the longest stretch sitting within tol of target, or None."""
    best, start = None, None
    for i, v in enumerate(c + [None]):
        inside = v is not None and abs(v - target) <= tol
        if inside and start is None:
            start = i
        elif not inside and start is not None:
            length = t[i - 1] - t[start]
            if length >= min_s and (best is None or length > best[1]):
                best = ((t[start] + t[i - 1]) / 2, length)
            start = None
    return best[0] if best else None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sensor", default="Cap 7")
    ap.add_argument("--csv", help="recording (default: newest forceplate_*.csv)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    path = args.csv or max(glob.glob("forceplate_*.csv"))
    base, table, points = load_calibration(args.sensor)
    t, c = read_recording(path, args.sensor)
    t0 = t[0]
    minutes = [(x - t0) / 60.0 for x in t]
    smooth = moving_average(c, 50)                    # 0.5 s at 100 Hz
    force = [to_force(v - base, table) for v in smooth]

    fig = plt.figure(figsize=(13, 6.2))
    fig.patch.set_facecolor(SURFACE)
    ax = fig.add_axes([0.06, 0.16, 0.62, 0.72])
    cal_ax = fig.add_axes([0.75, 0.16, 0.23, 0.72])

    # --- force vs time
    ax.plot(minutes, force, color=BLUE, lw=1.4)
    for p in points:
        at = find_plateau(t, smooth, p["current_pF"])
        if at is None:
            continue
        m = (at - t0) / 60.0
        f = p["weight_kg"] * G
        ax.plot([m], [f], "o", ms=8, color=BLUE, mec=SURFACE, mew=2, zorder=3)
        ax.annotate(f"{p['weight_kg']:g} kg  ({f:.0f} N)", (m, f),
                    xytext=(-8, 10), textcoords="offset points", ha="right",
                    fontsize=9, color=INK)

    ax.set_title(f"{args.sensor} - force vs time", loc="left", fontsize=14, color=INK)
    ax.set_xlabel("time since recording started (min)", color=INK2)
    ax.set_ylabel("force (N)", color=INK2)
    ax.set_ylim(bottom=0)
    ax.set_xlim(0, minutes[-1])

    # --- the calibration the conversion rests on
    dcs = [x for x, _ in table]
    fine = [dcs[-1] * i / 200 for i in range(201)]
    cal_ax.plot(fine, [to_force(x, table) for x in fine], color=INK2, lw=1.2)
    cal_ax.plot(dcs[1:], [f for _, f in table[1:]], "o", ms=8, color=BLUE,
                mec=SURFACE, mew=2, zorder=3)
    for dc, f in table[1:]:
        cal_ax.annotate(f"{f / G:g} kg", (dc, f), xytext=(-8, 4),
                        textcoords="offset points", ha="right", fontsize=9, color=INK)
    cal_ax.set_title("Calibration used", loc="left", fontsize=11, color=INK)
    cal_ax.set_xlabel(f"capacitance change from {base:.2f} pF (pF)", color=INK2)
    cal_ax.set_ylabel("force (N)", color=INK2)
    cal_ax.set_xlim(0, dcs[-1] * 1.08)
    cal_ax.set_ylim(0, table[-1][1] * 1.12)

    for a in (ax, cal_ax):
        a.set_facecolor(SURFACE)
        a.grid(True, color=GRID, lw=0.8)
        a.tick_params(colors=INK2)
        for side in ("top", "right"):
            a.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            a.spines[side].set_color(GRID)

    lightest = min(p["weight_kg"] for p in points)
    heaviest = max(p["weight_kg"] for p in points)
    fig.text(0.06, 0.012,
             f"Recording: {path}. Force from 0.5 s-averaged capacitance, interpolated "
             f"between the calibration points.\n"
             f"Below {lightest:g} kg the line from zero is an assumption (no data "
             f"there); above {heaviest:g} kg it is extrapolated, so brief spikes past "
             f"that are approximate.",
             fontsize=8.5, color=INK2, va="bottom")

    out = args.out or f"force_vs_time_{args.sensor.replace(' ', '')}.png"
    fig.savefig(out, dpi=150, facecolor=SURFACE)
    print("saved", out)


if __name__ == "__main__":
    main()
