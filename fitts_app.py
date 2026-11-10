"""Fitts's law testing suite (tkinter).

Run:  python3 fitts_app.py [--blocks N] [--windowed] [--data-dir DIR]

Design (see Fitts Law Project Instructions.pdf):
  * 4 diameters x 4 distances x 2 directions = 32 tasks per block, shuffled
    within each block; 10 blocks = 320 trials per participant.
  * Distance is measured edge to edge: from the side of the start square to
    the nearest edge of the target circle.
  * A trial starts when the participant clicks the start marker at the screen
    centre (first click, sample 0). The target circle appears at that moment.
  * Pointer position is sampled every 0.5 s from the first click until the
    final click inside the circle; distance travelled = sum of the straight
    segments between consecutive samples (final click position is the last
    sample).
  * errors = number of clicks on the target screen - 1 (the last click is the
    successful one inside the circle).
  * Data is appended to CSV files after every trial.
"""

import argparse
import csv
import itertools
import math
import os
import random
import time
import tkinter as tk
from datetime import datetime
from tkinter import messagebox

DIAMETERS = (32, 64, 128, 256)
DISTANCES = (100, 200, 300, 400)
DIRECTIONS = ("L", "R")
HOURS_RANGES = ("0-5", "6-10", "11-20", "21-30", "31-40", "41+")
SAMPLE_MS = 500
START_HALF = 25   # half-side of the square start icon (px)

CONSENT_TEXT = (
    "INFORMED CONSENT\n\n"
    "This study measures how quickly and accurately you can point and click on\n"
    "circles of different sizes and distances using a mouse.\n\n"
    "- You must be 18 years or older.\n"
    "- The session takes about 15-20 minutes (320 clicking trials).\n"
    "- We record your handedness, weekly computer use, and the timing,\n"
    "  clicks and pointer positions during the trials. No names are recorded.\n"
    "- Participation is voluntary and you may stop at any time (press Esc).\n\n"
    "By clicking \"I agree\" you confirm that you have read this statement and\n"
    "consent to take part."
)

PARTICIPANT_FIELDS = [
    "participant_id", "consent", "consent_timestamp", "handedness",
    "hours_per_week", "screen_w", "screen_h",
]
TRIAL_FIELDS = [
    "participant_id", "block", "trial_in_block", "trial_overall", "diameter",
    "distance", "direction", "index_of_difficulty", "time_ms",
    "distance_travelled_px", "n_clicks", "errors", "target_x", "target_y",
    "timestamp", "pointer_samples",
]


def index_of_difficulty(distance, width):
    return math.log2(distance / width + 1)


def append_row(path, fields, row):
    new = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if new:
            w.writeheader()
        w.writerow(row)
        f.flush()


def next_participant_id(path):
    if not os.path.exists(path):
        return 1
    with open(path, newline="") as f:
        ids = [int(r["participant_id"]) for r in csv.DictReader(f)
               if r.get("participant_id", "").isdigit()]
    return max(ids, default=0) + 1


class FittsApp:
    def __init__(self, root, blocks, data_dir):
        self.root = root
        self.blocks = blocks
        os.makedirs(data_dir, exist_ok=True)
        self.participants_csv = os.path.join(data_dir, "participants.csv")
        self.trials_csv = os.path.join(data_dir, "trials.csv")
        self.canvas = tk.Canvas(root, bg="white", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.frame = None          # current non-canvas screen
        self.participant = {}
        self.sampler_job = None
        self.trial_active = False
        root.bind("<Escape>", lambda e: self.abort())
        self.show_consent()

    # ---------- helpers ----------
    def clear(self):
        self.cancel_sampler()
        self.trial_active = False
        self.canvas.delete("all")
        self.canvas.unbind("<Button-1>")
        if self.frame is not None:
            self.frame.destroy()
            self.frame = None

    def new_frame(self):
        self.clear()
        self.frame = tk.Frame(self.canvas, bg="white")
        # Anchor to the middle of the window; stays centred if the window resizes.
        self.frame.place(relx=0.5, rely=0.5, anchor="center")
        return self.frame

    def cancel_sampler(self):
        if self.sampler_job is not None:
            self.root.after_cancel(self.sampler_job)
            self.sampler_job = None

    def abort(self):
        if messagebox.askyesno("Quit", "Stop the experiment? Data collected so far is kept."):
            self.root.destroy()

    # ---------- screens ----------
    def show_consent(self):
        f = self.new_frame()
        tk.Label(f, text="Fitts's Law Experiment", font=("Helvetica", 28, "bold"),
                 bg="white").pack(pady=10)
        tk.Label(f, text=CONSENT_TEXT, font=("Helvetica", 15), bg="white",
                 justify="left").pack(pady=10)
        row = tk.Frame(f, bg="white")
        row.pack(pady=10)
        tk.Button(row, text="I agree", font=("Helvetica", 16), width=12,
                  command=self.consent_given).pack(side="left", padx=10)
        tk.Button(row, text="I do not agree", font=("Helvetica", 16), width=12,
                  command=self.root.destroy).pack(side="left", padx=10)

    def consent_given(self):
        self.participant["consent"] = "yes"
        self.participant["consent_timestamp"] = datetime.now().isoformat(timespec="seconds")
        self.show_form()

    def show_form(self):
        f = self.new_frame()
        tk.Label(f, text="Participant information", font=("Helvetica", 24, "bold"),
                 bg="white").grid(row=0, column=0, columnspan=2, pady=15)
        hours = tk.StringVar(value="Select...")
        hand = tk.StringVar(value="right")
        font = ("Helvetica", 15)
        tk.Label(f, text="Handedness:", font=font, bg="white").grid(row=1, column=0, sticky="e", pady=6)
        tk.OptionMenu(f, hand, "right", "left", "ambidextrous").grid(row=1, column=1, sticky="w")
        tk.Label(f, text="Computer use (hours/week):", font=font, bg="white").grid(row=2, column=0, sticky="e", pady=6)
        tk.OptionMenu(f, hours, *HOURS_RANGES).grid(row=2, column=1, sticky="w")

        def submit():
            h = hours.get()
            if h not in HOURS_RANGES:
                messagebox.showerror("Missing input", "Please select your computer use per week.")
                return
            self.participant.update(handedness=hand.get(), hours_per_week=h)
            self.show_instructions()

        tk.Button(f, text="Continue", font=("Helvetica", 16), width=12,
                  command=submit).grid(row=3, column=0, columnspan=2, pady=20)

    def show_instructions(self):
        self.root.update_idletasks()
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        needed = 2 * (START_HALF + max(DISTANCES) + max(DIAMETERS)) + 20
        if w < needed:
            messagebox.showerror(
                "Screen too small",
                f"The window is {w}px wide but at least {needed}px is needed.\n"
                "Use a larger display or fullscreen.")
            self.root.destroy()
            return
        self.participant.update(screen_w=w, screen_h=h)
        f = self.new_frame()
        tk.Label(f, text="Instructions", font=("Helvetica", 24, "bold"), bg="white").pack(pady=10)
        tk.Label(f, justify="left", font=("Helvetica", 15), bg="white", text=(
            "1. Click the blue square in the centre of the screen.\n"
            "2. A circle appears on the left or right. Click inside it as fast\n"
            "   and as accurately as you can.\n"
            "3. Click the square again for the next circle, until all %d trials\n"
            "   are done.\n\n"
            "Press Esc at any time to stop." % (self.blocks * 32))).pack(pady=10)
        tk.Button(f, text="Begin", font=("Helvetica", 16), width=12,
                  command=self.start_experiment).pack(pady=10)

    def start_experiment(self):
        self.participant["participant_id"] = next_participant_id(self.participants_csv)
        append_row(self.participants_csv, PARTICIPANT_FIELDS,
                   {k: self.participant.get(k, "") for k in PARTICIPANT_FIELDS})
        # Build the full trial list: each block holds all 32 tasks in random order.
        self.trials = []
        for b in range(1, self.blocks + 1):
            tasks = list(itertools.product(DIAMETERS, DISTANCES, DIRECTIONS))
            random.shuffle(tasks)
            self.trials += [(b, i + 1, t) for i, t in enumerate(tasks)]
        self.index = 0
        # Defer drawing so the Begin button's click has finished before the
        # trial page (and its click binding) exists.
        self.root.after(50, self.show_trial_page)

    # ---------- trials ----------
    def show_trial_page(self):
        self.clear()
        self.root.update_idletasks()
        self.cx = self.canvas.winfo_width() // 2
        self.cy = self.canvas.winfo_height() // 2
        cx, cy = self.cx, self.cy
        self.canvas.create_rectangle(cx - START_HALF, cy - START_HALF,
                                     cx + START_HALF, cy + START_HALF,
                                     fill="steelblue", outline="black", width=2)
        self.status = self.canvas.create_text(cx, 40, font=("Helvetica", 16), fill="grey30")
        self.feedback = self.canvas.create_text(cx, cy + START_HALF + 30,
                                                font=("Helvetica", 16), fill="green4")
        self.update_status()
        self.canvas.bind("<Button-1>", self.on_click)

    def update_status(self):
        self.canvas.itemconfigure(self.status, text="Trial %d of %d   -   click the square" % (
            self.index + 1, len(self.trials)))

    def on_click(self, e):
        if self.trial_active:
            self.on_target_click(e)
        elif abs(e.x - self.cx) <= START_HALF and abs(e.y - self.cy) <= START_HALF:
            self.on_start_click(e)

    def on_start_click(self, e):
        # First click of the trial (on the square): timing and sampling start here.
        self.t0 = time.perf_counter()
        self.block, self.trial_in_block, (self.diameter, self.distance, self.direction) = \
            self.trials[self.index]
        sign = -1 if self.direction == "L" else 1
        r = self.diameter / 2
        # Edge to edge: square edge -> gap of `distance` px -> near edge of circle.
        self.tx = self.cx + sign * (START_HALF + self.distance + self.diameter // 2)
        self.ty = self.cy
        self.canvas.create_oval(self.tx - r, self.ty - r, self.tx + r, self.ty + r,
                                fill="tomato", outline="", tags="target")
        self.canvas.itemconfigure(self.feedback, text="")
        self.canvas.itemconfigure(self.status, text="Trial %d of %d   -   click the circle" % (
            self.index + 1, len(self.trials)))
        self.samples = [(e.x_root, e.y_root)]   # sample 0 = first click
        self.n_clicks = 0
        self.trial_active = True
        self.sampler_job = self.root.after(SAMPLE_MS, self.sample)

    def sample(self):
        if not self.trial_active:
            return
        self.samples.append(self.root.winfo_pointerxy())
        self.sampler_job = self.root.after(SAMPLE_MS, self.sample)

    def on_target_click(self, e):
        self.n_clicks += 1
        if math.hypot(e.x - self.tx, e.y - self.ty) > self.diameter / 2:
            return  # miss: counted as a click, trial continues
        # Duration = start click on the square -> first click inside the circle.
        t_ms = (time.perf_counter() - self.t0) * 1000
        self.trial_active = False
        self.cancel_sampler()
        self.samples.append((e.x_root, e.y_root))   # final click position
        dist = sum(math.dist(a, b) for a, b in zip(self.samples, self.samples[1:]))
        errors = self.n_clicks - 1
        append_row(self.trials_csv, TRIAL_FIELDS, {
            "participant_id": self.participant["participant_id"],
            "block": self.block,
            "trial_in_block": self.trial_in_block,
            "trial_overall": self.index + 1,
            "diameter": self.diameter,
            "distance": self.distance,
            "direction": self.direction,
            "index_of_difficulty": round(index_of_difficulty(self.distance, self.diameter), 4),
            "time_ms": round(t_ms, 1),
            "distance_travelled_px": round(dist, 1),
            "n_clicks": self.n_clicks,
            "errors": errors,
            "target_x": self.tx,
            "target_y": self.ty,
            "timestamp": datetime.now().isoformat(timespec="milliseconds"),
            "pointer_samples": ";".join("%d,%d" % p for p in self.samples),
        })
        self.canvas.delete("target")
        self.index += 1
        if self.index >= len(self.trials):
            self.show_done()
            return
        self.canvas.itemconfigure(self.feedback, text="Done - %.2f s" % (t_ms / 1000))
        self.update_status()

    # ---------- end screens ----------
    def show_done(self):
        f = self.new_frame()
        tk.Label(f, text="All done - thank you!", font=("Helvetica", 28, "bold"),
                 bg="white").pack(pady=10)
        tk.Label(f, text="Your data has been saved (participant %d)." %
                 self.participant["participant_id"], font=("Helvetica", 16),
                 bg="white").pack(pady=10)
        tk.Button(f, text="Close", font=("Helvetica", 16), width=12,
                  command=self.root.destroy).pack(pady=10)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blocks", type=int, default=10, help="testing blocks (default 10)")
    ap.add_argument("--windowed", action="store_true", help="do not use fullscreen (testing)")
    ap.add_argument("--data-dir", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
    args = ap.parse_args()
    root = tk.Tk()
    # The screens use a white background; without this, macOS Dark Mode makes
    # label text white too, so it disappears.
    root.option_add("*Label.foreground", "black")
    root.title("Fitts's Law Experiment")
    if args.windowed:
        root.geometry("1400x800")
    else:
        root.attributes("-fullscreen", True)
    root.update()
    FittsApp(root, args.blocks, args.data_dir)
    root.mainloop()


if __name__ == "__main__":
    main()
