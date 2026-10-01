# Smart Fitness Session Analyzer

Python Programming Assignment II, Option A.

Jonathan Christensen, student number jonathan4495.

## What it does

Reads participant profiles and wearable sensor readings from CSV files, checks
every row, and groups the usable rows into sessions. Each session is compared
against that participant's own reference values and given a classification with
a reason. Rows that cannot be used are reported instead of dropped, and the
program carries on.

Python 3.10 or newer, standard library only.

## How to run it

```
git clone https://github.com/Jonnyyyc/fitness-session-reporter.git
cd fitness-session-reporter
python3 main.py
```

On Windows use `python` instead of `python3`:

```
python main.py
```

With no arguments it reads both session files and writes to `output/`. The paths
can be given instead:

```
python3 main.py --profiles data/participants.csv --sessions data/fitness_sessions.csv --output output
```

Tests:

```
python3 -m unittest tests.py
```

## Project structure

```
fitness-session-reporter/
├── main.py                 command line and program order
├── tests.py                55 tests
├── requirements.txt        standard library only
├── data/                   the official CSV files
└── fitness/
    ├── errors.py           the two custom exceptions
    ├── models.py           participants, readings and sessions
    ├── analysis.py         calculations and classification
    ├── loading.py          reading and checking the CSV files
    └── reporting.py        writing the output files
```

## Classes

All in `models.py`, except `RejectedRow` which is in `loading.py`.

- **`Participant`** holds one person and their reference values.
- **`Athlete`** is a trained participant who recovers faster.
- **`Observation`** is one sensor reading.
- **`Session`** is a participant plus their readings, and runs the analysis.
- **`RejectedRow`** records a row that could not be used.

| Idea | Where |
| --- | --- |
| Composition | `Session` holds a `Participant` and a list of `Observation` |
| Encapsulation | `Participant._resting_heart_rate` and `._max_heart_rate` behind properties |
| Inheritance | `Athlete(Participant)` |
| Overriding | `Athlete.recovery_thresholds()` and `Athlete.describe()` |
| Class method | `Participant.from_profile()`, so `Athlete.from_profile()` returns an `Athlete` |

No `Athlete` is built from the supplied data, since there is no column for it.
The class is covered by the tests.

## Validation

A row is rejected unless:

- the session ID matches `^FIT-\d{4}-\d{3}$` and the participant ID matches
  `^P\d{3}$`, both anchored and checked with `fullmatch()`
- the participant exists in the profiles file
- it names the same participant as the rest of its session
- it has the right number of columns, no blank fields, and all values convert to
  numbers and fall in realistic ranges

Signal quality:

- below 0.50: rejected as noise
- 0.50 to 0.69: kept but marked as doubtful
- 0.70 and above: used normally

## Classification

A session gets the first label that applies:

1. **insufficient data**: fewer than five usable readings
2. **recovering**: heart rate fell 10% or more (15% for an `Athlete`) and
   activity fell 30% or more between the peak third and the final third
3. **high activity**: average heart rate at or above the high band, or average
   activity at or above 0.60
4. **moderate activity**: average heart rate at or above the elevated band, or
   average activity at or above 0.20
5. **resting**: neither test met

The bands are per person: `reserve = max - resting`, elevated is resting plus
20% of reserve, high is resting plus 50%. The data gives no maximum heart rate,
so 190 bpm is assumed for everyone.

## Example output

```
Done.
  Sessions analysed     8
  Rows accepted        25
  Rows rejected        15
  Files written:
    output\analysis_summary.csv
    output\analysis_report.txt
    output\rejected_records.txt
```

## Known limitations

- The 190 bpm maximum is a guess, so the heart rate bands are approximate.
- The signal quality cutoffs, the five reading minimum and the recovery
  percentages are my own judgement.
- Timestamps are not checked for gaps, and thirds are split by position rather
  than elapsed time.
- Each file is read into memory in full.

## Submission

Repository: https://github.com/Jonnyyyc/fitness-session-reporter
