"""
Live force vs time for one sensor (default Cap 7), using its weight calibration.

    python live_force.py
    python live_force.py --sensor "Cap 7" --window 60

Keys in the window:
    t  tare: treat the current reading as zero force (plate must be unloaded)
    r  reset to the calibration's own baseline
    p  reset the peak
    s  save a PNG snapshot
    q  quit

Every channel is still logged to a forceplate_*.csv, exactly as fdc_plot.py does.
"""
import argparse
import math
import time

import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

from fdc_plot import THEME_LIGHT, Stream, find_port, mean_tail
from force_vs_time import G, load_calibration, to_force

SMOOTH_S = 0.05        # line: 5-sample average, trims noise without hiding impacts
READOUT_S = 0.2        # big number: steadier 0.2 s average


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sensor", default="Cap 7")
    ap.add_argument("--window", type=float, default=60.0, help="seconds shown")
    ap.add_argument("--port")
    ap.add_argument("--baud", type=int, default=460800)
    ap.add_argument("--csv", default=time.strftime("forceplate_%Y%m%d_%H%M%S.csv"))
    args = ap.parse_args()

    theme = THEME_LIGHT
    colour = theme["series"][0]             # Cap 7 is channel 0: same blue as the 8-channel view
    cal_base, table, points = load_calibration(args.sensor)

    stream = Stream(find_port(args.port), args.baud, args.window, 100, args.csv)
    deadline = time.time() + 3.0
    while not stream.snapshot()[0] and time.time() < deadline:
        time.sleep(0.05)
    if args.sensor not in stream.names:
        raise SystemExit(f"{args.sensor} is not one of {stream.names}")
    ch = stream.names.index(args.sensor)
    colour = theme["series"][ch]
    print(f"{args.sensor} is column {ch}; logging to {args.csv}")

    fig = plt.figure(figsize=(12, 6.8))
    fig.canvas.manager.set_window_title(f"{args.sensor} - live force")
    fig.patch.set_facecolor(theme["surface"])
    ax = fig.add_axes([0.08, 0.12, 0.64, 0.76])
    ax.set_facecolor(theme["surface"])

    (line,) = ax.plot([], [], color=colour, lw=2)

    # Calibration weights as quiet reference lines, labelled at the right edge.
    refs = []
    for p in points:
        f = p["weight_kg"] * G
        ax.axhline(f, color=theme["grid"], lw=1, ls="--", zorder=0)
        refs.append(ax.text(1.0, f, f" {p['weight_kg']:g} kg", transform=ax.get_yaxis_transform(),
                            va="center", ha="left", fontsize=8.5, color=theme["secondary"]))

    ax.set_title(f"{args.sensor} - live force", loc="left", fontsize=15, color=theme["primary"])
    ax.set_xlabel("time (s)", color=theme["secondary"])
    ax.set_ylabel("force (N)", color=theme["secondary"])
    ax.grid(True, axis="y", color=theme["grid"], lw=0.8)
    ax.tick_params(colors=theme["secondary"])
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(theme["grid"])

    # Readout panel: the number you actually want, big; supporting numbers small.
    def label(y, text, size, colour_, weight="normal"):
        return fig.text(0.80, y, text, fontsize=size, color=colour_, weight=weight,
                        linespacing=1.7)

    label(0.84, "Force now", 11, theme["secondary"])
    big_n = label(0.74, "-", 34, theme["primary"], "bold")
    big_kg = label(0.69, "", 14, theme["secondary"])
    label(0.58, "Peak", 11, theme["secondary"])
    peak_txt = label(0.53, "-", 18, theme["primary"])
    label(0.43, "Capacitance", 11, theme["secondary"])
    cap_txt = label(0.38, "-", 14, theme["primary"])
    zero_txt = label(0.34, "", 10, theme["secondary"])
    label(0.22, "[t] tare (unloaded)   [r] reset zero\n[p] reset peak   [s] save   [q] quit",
          9, theme["secondary"])
    status = fig.text(0.08, 0.02, "", fontsize=9, color=theme["secondary"])

    state = {"base": cal_base, "tared": False, "peak": 0.0}

    def on_key(event):
        _, pf = stream.snapshot()
        if event.key == "t":
            now = mean_tail(pf[ch], 1.0)
            if not math.isnan(now):
                state["base"], state["tared"], state["peak"] = now, True, 0.0
        elif event.key == "r":
            state["base"], state["tared"] = cal_base, False
        elif event.key == "p":
            state["peak"] = 0.0
        elif event.key == "s":
            name = time.strftime(f"live_force_{args.sensor.replace(' ', '')}_%H%M%S.png")
            fig.savefig(name, dpi=150, facecolor=theme["surface"])
            print("saved", name)
        elif event.key == "q":
            plt.close(fig)

    fig.canvas.mpl_connect("key_press_event", on_key)

    def update(_frame):
        t, pf = stream.snapshot()
        series = pf[ch]
        if not t:
            status.set_text(stream.status)
            return

        base = state["base"]
        t_end = t[-1]
        t_start = t_end - args.window
        n = max(1, int(SMOOTH_S * 100))

        xs, ys, acc, window = [], [], 0.0, []
        for x, v in zip(t, series):
            if math.isnan(v):
                continue
            window.append(v)
            acc += v
            if len(window) > n:
                acc -= window.pop(0)
            if x >= t_start:
                xs.append(x - t_end)             # 0 = now, negative = seconds ago
                ys.append(to_force(acc / len(window) - base, table))
        line.set_data(xs, ys)

        top = max(ys) if ys else 0.0
        ax.set_xlim(-args.window, 0)
        ax.set_ylim(0, max(100.0, top * 1.15))
        ymax = ax.get_ylim()[1]
        for txt, p in zip(refs, points):
            txt.set_visible(p["weight_kg"] * G <= ymax)

        cap_now = mean_tail(series, READOUT_S)
        if not math.isnan(cap_now):
            f_now = to_force(cap_now - base, table)
            state["peak"] = max(state["peak"], f_now)
            big_n.set_text(f"{f_now:,.0f} N")
            big_kg.set_text(f"= {f_now / G:.1f} kg")
            peak_txt.set_text(f"{state['peak']:,.0f} N  ({state['peak'] / G:.1f} kg)")
            cap_txt.set_text(f"{cap_now:.3f} pF  ({cap_now - base:+.3f})")
        zero_txt.set_text(f"zero at {base:.3f} pF " + ("(tared)" if state["tared"] else "(calibration)"))
        status.set_text(f"{stream.status}    log: {args.csv}    "
                        f"below {min(p['weight_kg'] for p in points):g} kg and above "
                        f"{max(p['weight_kg'] for p in points):g} kg are estimates")

    anim = FuncAnimation(fig, update, interval=50, cache_frame_data=False)
    fig._keep = anim
    try:
        plt.show()
    finally:
        stream.close()
        print(f"Saved {args.csv}")


if __name__ == "__main__":
    main()
