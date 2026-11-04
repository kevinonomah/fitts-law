# Fitts's Law Project

CIS 582 (Human-Computer Interaction) project on Fitts's law.

Fitts's law models pointing time as `MT = a + b · log2(D/W + 1)`, where `D` is
the distance to the target, `W` is the target width, and the log term is the
index of difficulty (ID) in bits.

## Running the experiment

```
python3 fitts_app.py                 # fullscreen, 10 blocks x 32 trials
python3 fitts_app.py --blocks 1 --windowed   # quick test
```

Data is appended to `data/participants.csv` and `data/trials.csv` (one row per
trial: time, distance travelled from 0.5 s pointer samples, clicks, errors =
clicks - 1). Press Esc to quit; data collected so far is kept.
