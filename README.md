# Smart Fitness Session Analyzer

Python Programming Assignment II, Option A.

Jonathan Christensen, student number jonathan4495.

## What it does

This continues the program from Assignment I, which analysed fitness
measurements held in Python lists and dictionaries. This version reads the same
kind of data from CSV files instead.

It loads a file of participants and one or more files of sensor readings,
checks every row, groups the good rows into sessions, and works out averages.
Those are compared against the participant's own reference values, and each
session gets a classification with a reason. Unusable rows are reported rather
than dropped silently, and the program carries on. Results go into three files
in an output folder.

Python 3.10 or newer. Standard library only, so there is nothing to install.

## How to run it

```
git clone https://github.com/Jonnyyyc/fitness-session-reporter.git
cd fitness-session-reporter
python3 main.py
```

On Windows the command is `python` rather than `python3`:

```
python main.py
```

With no arguments it reads `data/participants.csv` and both session files and
writes to `output/`. You can give the paths instead:

```
python3 main.py --profiles data/participants.csv --sessions data/fitness_sessions.csv --output output
```

`--sessions` takes one path or several. The output folder is created if missing
and each run replaces the files, so there is nothing to clean up between runs.

Tests:

```
python3 -m unittest tests.py
```

## Project structure

Assignment I suggested a flat list of files. This assignment asks for a package,
so the code is split into five modules:

```
fitness-session-reporter/
├── main.py                 command line and program order
├── tests.py                55 tests
├── requirements.txt        standard library only
├── data/                   the official CSV files
└── fitness/
    ├── errors.py           the two custom exceptions
    ├── models.py           participants, readings and sessions
    ├── analysis.py         the calculations and classification
    ├── loading.py          reading and checking the CSV files
    └── reporting.py        writing the output files
```

## Class design

**`Participant`** holds one person and the reference values their sessions are
compared against: resting heart rate, maximum heart rate, normal temperature and
normal skin response. It works out that person's heart rate bands and recovery
thresholds.

**`Athlete`** is a trained participant, whose heart rate falls faster after
effort.

**`Observation`** is one sensor reading taken at one moment.

**`Session`** is one recording: a participant and their readings. Its
`analyse()` method returns the result as a dictionary.

**`RejectedRow`** records a row that could not be used, with the file name, row
number, field and reason.

### Where the OOP ideas are shown

| Idea | Where |
| --- | --- |
| Composition | `Session` holds a `Participant` and a list of `Observation` objects |
| Encapsulation | `Participant._resting_heart_rate` and `._max_heart_rate` sit behind properties that check each value |
| Inheritance | `Athlete(Participant)` |
| Overriding | `Athlete.recovery_thresholds()` and `Athlete.describe()` |
| Class method | `Participant.from_profile()`, which uses `cls()` so `Athlete.from_profile()` returns an `Athlete` |

All of these are in `models.py`. `Athlete` only overrides the recovery rule,
since the bands already adapt to each person through the reserve formula below.
No `Athlete` is built from the supplied data, because `participants.csv` has no
column for who is trained, so the class is covered by the tests instead.

## Validation rules

Each session row is checked in this order:

1. The session ID matches `^FIT-\d{4}-\d{3}$`.
2. The participant ID matches `^P\d{3}$`.
3. That participant exists in the profiles file.
4. The row names the same participant as the rest of its session.
5. The row is usable: right number of columns, no blanks, numbers that convert,
   values in range.

Both patterns are anchored and used with `fullmatch()`, and the participant one
also runs on `participants.csv`. Ranges use normal comparisons, not patterns. A
value outside these is impossible rather than poor, so the row is rejected:

| Field | Allowed |
| --- | --- |
| `timestamp` | 0 or more |
| `heart_rate` | 20 to 250 bpm |
| `skin_response` | 0 to 30 |
| `temperature` | 20 to 45 C |
| `activity_level` | 0.0 to 1.0 |
| `signal_quality` | 0.0 to 1.0 |

### Signal quality

- below 0.50: mostly noise, so the row is rejected
- 0.50 to 0.69: doubtful but still useful, so it is kept and marked
- 0.70 and above: used normally

The middle tier exists because throwing away a doubtful reading can push a
session under the minimum. All five rows of `FIT-2026-005` fall between 0.25 and
0.34, so that session is reported as insufficient data.

## Classification

A session gets the first label that applies:

1. **insufficient data**, if fewer than five readings were usable
2. **recovering**, if heart rate and activity both fell enough towards the end
3. **high activity**, if average heart rate reached the high band **or** average
   activity reached 0.60
4. **moderate activity**, if average heart rate reached the elevated band **or**
   average activity reached 0.20
5. **resting**, if neither test was met

Either half of a test is enough on its own. The bands are worked out per person
from heart rate reserve:

```
reserve       = max heart rate - resting heart rate
elevated band = resting heart rate + 20% of reserve
high band     = resting heart rate + 50% of reserve
```

For Amina Noor, resting 68 and maximum 190, the reserve is 122, giving an
elevated band of 92.4 bpm and a high band of 129.0 bpm. Activity level needs no
such adjustment, since it already means the same for everyone.

Recovery is checked first because a hard session ending in a cooldown passes
both tests and recovering says more. It compares the final third against the
**peak** third, since a session that starts calm and works hard peaks in the
middle. Heart rate must fall at least 10 percent (15 for an `Athlete`), activity
at least 30 percent, and the peak third must have reached the elevated band.

## Assumptions

**Maximum heart rate is 190 bpm for everyone.** The data has no maximum and no
age to work one out from; 190 is roughly what 220 minus age gives at thirty.

**Five usable readings are the minimum for a verdict.** A third of four readings
is one reading, too little to call a trend.

**A session belongs to one person**, so a row naming someone else is rejected.

**Timestamps order a session but are not measured**, so neither timestamp nor
signal quality is averaged.

## Example output

Running `python main.py` prints:

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

The start of `output/analysis_summary.csv`, which has one row per session:

```
session_id,participant_id,participant_name,classification,rows_attributed,rows_usable
FIT-2026-001,P001,Amina Noor,resting,6,6
FIT-2026-002,P002,Jonas Berg,moderate activity,6,6
FIT-2026-003,P003,Maya Chen,high activity,6,6
FIT-2026-004,P001,Amina Noor,recovering,6,6
FIT-2026-005,P002,Jonas Berg,insufficient data,5,0
```

Part of one session from `output/analysis_report.txt`:

```
  Session:     FIT-2026-004
  Participant: Amina Noor (P001, resting HR 68 bpm, max 190 bpm)

SUMMARY  (usable observations only)
  Measurement        Average   Minimum   Maximum   Unit
  Heart rate           113.2      72.0     151.0   bpm
  Activity level        0.55      0.18      0.92

RECOVERY
  Detected.
    Heart rate  141.5 -> 93.0 bpm  (34% fall, 10% required)
    Activity    0.81 -> 0.30       (63% fall, 30% required)

CLASSIFICATION:  RECOVERING
```

## Known limitations

The 190 bpm maximum is a guess applied to everyone, so the bands are only
approximate. The signal quality cutoffs, the five reading minimum and the
recovery percentages are my own judgement rather than measured values.

Nothing checks that timestamps are unique or evenly spaced, and thirds are split
by position rather than elapsed time.

The header check only looks for the columns the program needs, so a file with
the right headings but nonsense underneath is still checked row by row.

Each file is read into memory in full, which is fine at this size.

## Submission

Repository: https://github.com/Jonnyyyc/fitness-session-reporter
