"""
Live capacitance graph for the force-sensing plate.

Reads the CSV stream from the NUCLEO-WB55RG (two FDC2214 chips, 8 channels),
converts the raw counts to capacitance, logs everything to a .csv file, and
draws one live graph with all 8 channels.

    python fdc_plot.py                 # auto-detects the ST-LINK COM port
    python fdc_plot.py --port COM5 --window 20

Keys in the plot window:
    z  zero the channels (show change from now on)
    u  undo zeroing (show absolute capacitance)
    s  save a PNG snapshot
    q  quit
"""
import argparse
import csv
import json
import math
import sys
import threading
import time
from collections import deque

import matplotlib
import matplotlib.pyplot as plt
import serial
import serial.tools.list_ports
from matplotlib.animation import FuncAnimation

# --- defaults, overridden by the board's own header lines -------------------
DEFAULT_FREF_HZ = 32_000_000
DEFAULT_FIN_SEL = 2
DEFAULT_L_H = 18e-6          # 18 uH tank inductor
TWO_POW_28 = 1 << 28
CHANNELS = 8

# Validated 8-slot categorical palette: fixed order, never cycled.
SERIES_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
                "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
SERIES_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500",
               "#d55181", "#008300", "#9085e9", "#e66767"]
THEME_LIGHT = dict(surface="#fcfcfb", primary="#0b0b0b", secondary="#52514e",
                   muted="#9a9994", grid="#e3e2de", series=SERIES_LIGHT)
THEME_DARK = dict(surface="#1a1a19", primary="#ffffff", secondary="#c3c2b7",
                  muted="#76756f", grid="#383835", series=SERIES_DARK)

# Column identity, in the chip/input terms the firmware announces. Overridden by
# the board's "# names=" header, and again by a map file written by
# fdc_identify.py once you have confirmed which physical pad each input reaches.
CH_NAMES = ["J1-IN0", "J1-IN1", "J1-IN2", "J1-IN3",
            "J2-IN0", "J2-IN1", "J2-IN2", "J2-IN3"]
MAP_FILE = "forceplate_map.json"


def load_map(default):
    """Physical names and dead channels from the map file, if one has been made.

    Returns (names, hidden). Hidden channels are still logged to the CSV -- a
    channel believed dead is worth recording, in case it comes back.
    """
    try:
        with open(MAP_FILE) as fh:
            data = json.load(fh)
        names = data["names"]
        hidden = {int(i) for i in data.get("hidden", [])}
        if len(names) == CHANNELS:
            return list(names), hidden
        print(f"{MAP_FILE}: expected {CHANNELS} names, ignoring it")
    except FileNotFoundError:
        pass
    except (ValueError, KeyError, TypeError) as exc:
        print(f"{MAP_FILE}: {exc}; ignoring it")
    return list(default), set()


def counts_to_pf(counts, fref_hz, fin_sel, inductance_h):
    """Convert one FDC2214 reading to the tank capacitance in picofarads.

    The chip reports the sensor's resonant frequency as a fraction of the
    reference clock; inverting the LC resonance formula gives capacitance.
    """
    if counts <= 0:
        return math.nan
    freq = fin_sel * fref_hz * counts / TWO_POW_28
    if freq <= 0:
        return math.nan
    return 1.0 / (inductance_h * (2 * math.pi * freq) ** 2) * 1e12


def find_port(explicit=None):
    """Pick the ST-LINK virtual COM port unless one was named."""
    if explicit:
        return explicit
    for p in serial.tools.list_ports.comports():
        text = f"{p.description} {p.manufacturer or ''}".lower()
        if "stlink" in text.replace("-", "") or "stmicro" in text:
            return p.device
    ports = serial.tools.list_ports.comports()
    if not ports:
        sys.exit("No serial ports found. Is the Nucleo plugged in?")
    return ports[0].device


class Stream:
    """Background reader: owns the serial port and the sample history."""

    def __init__(self, port, baud, window_s, sample_hz, csv_path):
        self.ser = serial.Serial(port, baud, timeout=1)
        self.fref_hz = DEFAULT_FREF_HZ
        self.fin_sel = DEFAULT_FIN_SEL
        self.inductance_h = DEFAULT_L_H

        depth = max(200, int(window_s * sample_hz * 1.2))
        self.t = deque(maxlen=depth)
        self.pf = [deque(maxlen=depth) for _ in range(CHANNELS)]
        self.lock = threading.Lock()
        self.status = "waiting for data..."
        self.rate = 0.0
        self.running = True

        # A map file is the operator's confirmed truth about which pad is which,
        # so it outranks whatever names the firmware announces.
        self.pinned_names = None
        mapped, self.hidden = load_map(CH_NAMES)
        if mapped != CH_NAMES:
            self.pinned_names = mapped
        self.names = list(self.pinned_names or CH_NAMES)

        self.csv_file = open(csv_path, "w", newline="")
        self.csv = csv.writer(self.csv_file)
        self.csv_header_written = False

        threading.Thread(target=self._read_loop, daemon=True).start()

    def _write_csv_header(self):
        """Written on the first sample, once the board's names have arrived."""
        self.csv.writerow(["t_ms"] + [f"{n}_counts" for n in self.names] +
                          [f"{n}_pF" for n in self.names])
        self.csv_header_written = True

    def _handle_header(self, line):
        """The board announces its clock settings; trust those over defaults."""
        for token in line.lstrip("#").split():
            if "=" not in token:
                continue
            key, _, value = token.partition("=")
            try:
                if key == "fref_hz":
                    self.fref_hz = int(value)
                elif key == "fin_sel":
                    self.fin_sel = int(value)
                elif key == "inductor_nH":
                    self.inductance_h = int(value) * 1e-9
                elif key == "names" and self.pinned_names is None:
                    parts = value.split(",")
                    if len(parts) == CHANNELS:
                        self.names = parts
            except ValueError:
                pass
        if line.startswith("# ERROR"):
            self.status = line.lstrip("# ").strip()

    def _read_loop(self):
        last_report, count = time.time(), 0
        while self.running:
            try:
                raw = self.ser.readline().decode("ascii", "replace").strip()
            except serial.SerialException as exc:
                self.status = f"serial error: {exc}"
                return
            if not raw:
                continue
            if raw.startswith("#"):
                self._handle_header(raw)
                continue
            if raw.startswith("t_ms"):
                continue

            parts = raw.split(",")
            if len(parts) != CHANNELS + 1:
                continue            # partial line, e.g. the first one after connecting
            try:
                values = [int(p) for p in parts]
            except ValueError:
                continue

            t_ms, counts = values[0], values[1:]
            pf = [counts_to_pf(c, self.fref_hz, self.fin_sel, self.inductance_h)
                  for c in counts]
            with self.lock:
                self.t.append(t_ms / 1000.0)
                for i in range(CHANNELS):
                    self.pf[i].append(pf[i])
            if not self.csv_header_written:
                self._write_csv_header()
            self.csv.writerow([t_ms] + counts + [f"{v:.4f}" for v in pf])

            count += 1
            now = time.time()
            if now - last_report >= 1.0:
                self.rate = count / (now - last_report)
                live = sum(1 for v in pf if not math.isnan(v))
                self.status = f"{self.rate:.0f} samples/s · {live}/8 channels live"
                last_report, count = now, 0

    def snapshot(self):
        with self.lock:
            return list(self.t), [list(d) for d in self.pf]

    def close(self):
        self.running = False
        time.sleep(0.2)
        self.csv_file.close()
        self.ser.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", help="COM port (default: auto-detect ST-LINK)")
    ap.add_argument("--baud", type=int, default=460800)
    ap.add_argument("--window", type=float, default=20.0, help="seconds shown")
    ap.add_argument("--rate", type=float, default=100.0, help="expected samples/s")
    ap.add_argument("--csv", default=time.strftime("forceplate_%Y%m%d_%H%M%S.csv"))
    ap.add_argument("--dark", action="store_true", help="dark theme")
    ap.add_argument("--hide", type=lambda s: [int(x) for x in s.split(",") if x != ""],
                    help="channel indices to leave off the graph, e.g. 0,3,4")
    ap.add_argument("--all", action="store_true",
                    help="ignore the map file's hidden list and plot every channel "
                         "(e.g. after swapping to a different sensor board)")
    args = ap.parse_args()

    theme = THEME_DARK if args.dark else THEME_LIGHT
    port = find_port(args.port)
    print(f"Reading {port} at {args.baud} baud; logging to {args.csv}")
    stream = Stream(port, args.baud, args.window, args.rate, args.csv)

    # Wait for the board's header so the key is built with the final names.
    deadline = time.time() + 3.0
    while not stream.snapshot()[0] and time.time() < deadline:
        time.sleep(0.05)

    hidden = (set() if args.all else set(stream.hidden)) | set(args.hide or [])
    fig = build_figure(stream, theme, args, hidden)
    try:
        plt.show()
    finally:
        stream.close()
        print(f"Saved {args.csv}")


# ---------------------------------------------------------------- the window

BASELINE_AUTO_S = 2.0     # baseline taken automatically after this much data
BASELINE_AVG_S = 1.0      # 'z' averages this long, so one noisy sample can't skew it
CURRENT_AVG_S = 0.2       # "current" reading is smoothed over this window
TABLE_EVERY = 4           # refresh the numbers every 4th frame (~5 per second)


def mean_tail(series, seconds, rate=100):
    """Average of the last `seconds` of a channel, ignoring gaps."""
    tail = [v for v in series[-max(1, int(seconds * rate)):] if not math.isnan(v)]
    return sum(tail) / len(tail) if tail else math.nan


def tint(hex_color, surface, amount=0.18):
    """A light wash of a series colour, for a table header behind dark text."""
    c, s = matplotlib.colors.to_rgb(hex_color), matplotlib.colors.to_rgb(surface)
    return tuple(s[k] + (c[k] - s[k]) * amount for k in range(3))


def save_hidden(stream, hidden):
    """Remember the key's ticks in the map file, keeping everything else in it."""
    try:
        with open(MAP_FILE) as fh:
            data = json.load(fh)
    except (FileNotFoundError, ValueError):
        data = {"names": list(stream.names)}
    data["hidden"] = sorted(hidden)
    with open(MAP_FILE, "w") as fh:
        json.dump(data, fh, indent=2)


def fmt(v, places=2, signed=False):
    if math.isnan(v):
        return "-"
    if abs(v) < 0.5 * 10 ** -places:
        v = 0.0                          # never print "-0.000"
    return f"{v:+.{places}f}" if signed else f"{v:.{places}f}"


def spread_labels(items, gap):
    """Nudge end-of-line labels apart so close traces don't print on top of
    each other. items: [(y, key)], returns {key: y_for_label}."""
    placed, out = [], {}
    for y, key in sorted(items):
        if placed and y < placed[-1] + gap:
            y = placed[-1] + gap
        placed.append(y)
        out[key] = y
    return out


def build_figure(stream, theme, args, hidden):
    from matplotlib.widgets import Button, CheckButtons

    names = list(stream.names)
    # Everything user-facing lists sensors by name (Cap 0, Cap 1, ...), even
    # though the columns underneath may be in another order.
    order = sorted(range(CHANNELS), key=lambda i: names[i])
    selected = {i for i in range(CHANNELS) if i not in hidden}

    fig = plt.figure(figsize=(13.5, 8.2))
    fig.canvas.manager.set_window_title("Force plate - live capacitance")
    fig.patch.set_facecolor(theme["surface"])

    ax = fig.add_axes([0.07, 0.37, 0.72, 0.55])
    key_ax = fig.add_axes([0.83, 0.47, 0.15, 0.45])
    all_ax = fig.add_axes([0.83, 0.39, 0.07, 0.05])
    none_ax = fig.add_axes([0.91, 0.39, 0.07, 0.05])
    table_ax = fig.add_axes([0.14, 0.06, 0.84, 0.22])   # room left for row names

    for a in (ax, key_ax, table_ax):
        a.set_facecolor(theme["surface"])

    # --- the graph: colour is tied to the channel, never to its position
    # among the visible ones, so unticking a sensor never repaints another.
    lines, end_labels = [], []
    for i in range(CHANNELS):
        (ln,) = ax.plot([], [], lw=2, color=theme["series"][i])
        ln.set_visible(i in selected)
        lines.append(ln)
        end_labels.append(ax.text(0, 0, "", color=theme["primary"], fontsize=9,
                                  va="center", ha="left", clip_on=False))

    ax.set_xlabel("time (s)", color=theme["secondary"])
    ax.set_ylabel("capacitance (pF)", color=theme["secondary"])
    ax.set_title("Force plate - live capacitance",
                 color=theme["primary"], fontsize=14, loc="left")
    ax.grid(True, color=theme["grid"], lw=0.8)
    ax.tick_params(colors=theme["secondary"])
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(theme["grid"])

    # --- the key: one coloured box per sensor, click to show or hide it.
    colours = [theme["series"][i] for i in order]
    check = CheckButtons(
        key_ax,
        labels=[names[i] for i in order],
        actives=[i in selected for i in order],
        label_props={"color": [theme["primary"]] * CHANNELS, "fontsize": [11] * CHANNELS},
        frame_props={"edgecolor": colours, "facecolor": [theme["surface"]] * CHANNELS,
                     "linewidth": [2] * CHANNELS, "sizes": [140] * CHANNELS},
        check_props={"facecolor": colours, "sizes": [140] * CHANNELS},
    )
    key_ax.set_title("Sensors - click to show/hide", color=theme["secondary"],
                     fontsize=10, loc="left")
    for spine in key_ax.spines.values():
        spine.set_color(theme["grid"])

    def set_selected(new):
        selected.clear()
        selected.update(new)
        for i in range(CHANNELS):
            lines[i].set_visible(i in selected)
            if i not in selected:
                end_labels[i].set_text("")
        save_hidden(stream, set(range(CHANNELS)) - selected)

    def on_check(label):
        i = order[[names[k] for k in order].index(label)]
        set_selected(selected ^ {i})

    check.on_clicked(on_check)

    def set_all(active):
        # CheckButtons.set_active fires on_check per box; mute that while we
        # flip them, then apply the selection once.
        check.eventson = False
        for k, i in enumerate(order):
            if (i in selected) != active:
                check.set_active(k)
        check.eventson = True
        set_selected(set(range(CHANNELS)) if active else set())

    btn_all = Button(all_ax, "All", color=theme["surface"], hovercolor=theme["grid"])
    btn_none = Button(none_ax, "None", color=theme["surface"], hovercolor=theme["grid"])
    for b in (btn_all, btn_none):
        b.label.set_color(theme["primary"])
    btn_all.on_clicked(lambda _e: set_all(True))
    btn_none.on_clicked(lambda _e: set_all(False))

    # --- the readout: every sensor, selected or not; unselected ones dimmed.
    table_ax.axis("off")
    row_labels = ["Baseline (pF)", "Current (pF)", "Change (pF)"]
    table = table_ax.table(
        cellText=[["-"] * CHANNELS for _ in row_labels],
        rowLabels=row_labels,
        colLabels=[names[i] for i in order],
        cellLoc="center", rowLoc="right", loc="upper center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(11)
    table.scale(1, 1.7)
    for (r, c), cell in table.get_celld().items():
        cell.set_edgecolor(theme["grid"])
        cell.set_facecolor(theme["surface"])
        cell.get_text().set_color(theme["primary"] if c >= 0 else theme["secondary"])
        if r == 0 and c >= 0:        # header: a wash of the sensor's colour
            cell.set_facecolor(tint(colours[c], theme["surface"]))
            cell.get_text().set_fontweight("bold")

    status_text = fig.text(0.07, 0.015, "", color=theme["secondary"], fontsize=9)
    state = {"baseline": None, "delta": False, "frame": 0}

    def take_baseline(seconds):
        _, pf = stream.snapshot()
        state["baseline"] = [mean_tail(series, seconds, args.rate) for series in pf]

    def on_key(event):
        if event.key == "z":                 # re-take baseline, show change from it
            take_baseline(BASELINE_AVG_S)
            state["delta"] = True
            ax.set_ylabel("change from baseline (pF)", color=theme["secondary"])
        elif event.key == "b":               # re-take baseline, keep the view
            take_baseline(BASELINE_AVG_S)
        elif event.key == "u":               # back to absolute capacitance
            state["delta"] = False
            ax.set_ylabel("capacitance (pF)", color=theme["secondary"])
        elif event.key == "s":
            name = time.strftime("forceplate_%Y%m%d_%H%M%S.png")
            fig.savefig(name, dpi=150, facecolor=theme["surface"])
            print("saved", name)
        elif event.key == "q":
            plt.close(fig)

    fig.canvas.mpl_connect("key_press_event", on_key)

    def update(_frame):
        t, pf = stream.snapshot()
        if not t:
            status_text.set_text(stream.status)
            return

        if state["baseline"] is None and t[-1] - t[0] >= BASELINE_AUTO_S:
            take_baseline(BASELINE_AUTO_S)

        base = state["baseline"]
        use_delta = state["delta"] and base is not None
        t_end = t[-1]
        t_start = t_end - args.window

        lo, hi = math.inf, -math.inf
        ends = []
        for i in range(CHANNELS):
            if i not in selected:
                continue
            offset = base[i] if use_delta and not math.isnan(base[i]) else 0.0
            xs, ys = [], []
            for x, y in zip(t, pf[i]):
                if x >= t_start and not math.isnan(y):
                    xs.append(x)
                    ys.append(y - offset)
            lines[i].set_data(xs, ys)
            if ys:
                lo, hi = min(lo, min(ys)), max(hi, max(ys))
                ends.append((ys[-1], i))
            else:
                end_labels[i].set_text("")

        if lo < hi:
            pad = max((hi - lo) * 0.12, 0.01)
            ax.set_ylim(lo - pad, hi + pad)
        y0, y1 = ax.get_ylim()
        for i, y in spread_labels(ends, (y1 - y0) * 0.045).items():
            end_labels[i].set_position((t_end, y))
            end_labels[i].set_text(f" {names[i]}")
        ax.set_xlim(t_start, t_end + args.window * 0.08)

        state["frame"] += 1
        if state["frame"] % TABLE_EVERY == 0:
            for c, i in enumerate(order):
                b = base[i] if base is not None else math.nan
                now = mean_tail(pf[i], CURRENT_AVG_S, args.rate)
                values = (fmt(b), fmt(now), fmt(now - b, 3, signed=True))
                ink = theme["primary"] if i in selected else theme["muted"]
                for r, text in enumerate(values, start=1):
                    cell = table[r, c]
                    cell.get_text().set_text(text)
                    cell.get_text().set_color(ink)

        if base is None:
            note = f"baseline in {BASELINE_AUTO_S - (t_end - t[0]):.0f}s"
        else:
            note = "baseline set"
        status_text.set_text(
            f"{stream.status} · {note}    [z] new baseline + show change   "
            f"[b] new baseline   [u] absolute   [s] save png   [q] quit    "
            f"log: {args.csv}")

    anim = FuncAnimation(fig, update, interval=50, cache_frame_data=False)
    # Widgets and the animation only work while something references them.
    fig._keep = (anim, check, btn_all, btn_none)
    return fig


if __name__ == "__main__":
    main()
