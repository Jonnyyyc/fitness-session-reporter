# Smart Fitness Session Analyzer

Python Programming Assignment II, Option A.

Jonathan Christensen, student number jonathan4495.

This continues the object-oriented program from Assignment I. That version
analysed fitness measurements held in Python lists and dictionaries. This one
reads the same kind of data from CSV files, checks every row, writes the results
to three report files, and keeps going when a row or a whole file turns out to
be unusable.

Standard library only, no third-party packages, so there is nothing to install.

**Python 3.10 or newer.** It was written and run on 3.14, and nothing in it
needs anything newer than 3.10: every file parses under the 3.10 grammar, and
the only modules used are `argparse`, `contextlib`, `csv`, `io`, `pathlib`,
`re`, `shutil`, `statistics`, `sys`, `tempfile`, `textwrap` and `unittest`.
It has only been run on 3.14.

## Running it

```
git clone https://github.com/Jonnyyyc/fitness-session-reporter.git
cd fitness-session-reporter
python3 main.py
```

On Windows the command is `python` rather than `python3`:

```
python main.py
```

That is the normal way to run it. With no arguments the program reads
`data/participants.csv` and **both** official session files, the valid one and
the deliberately invalid one, and writes its results to `output/`.

The paths can also be given on the command line:

```
python3 main.py --profiles data/participants.csv --sessions data/fitness_sessions.csv --output output
```

That is the exact command printed in the assignment brief, and it works, but
note that it loads only the valid session file. It reports 5 sessions rather
than 8, because the three sessions in `fitness_sessions_invalid.csv` are not
read at all.

`--sessions` takes one path or several, so both files can be passed explicitly:

```
python3 main.py --profiles data/participants.csv --sessions data/fitness_sessions.csv data/fitness_sessions_invalid.csv --output output
```

which does the same thing as running with no arguments.

The output folder is created if it does not exist, and running the program again
replaces the files rather than adding to them, so there is nothing to clean up
in between.

Tests:

```
python3 -m unittest tests.py
```

## Project structure

Assignment I's suggested layout is a flat list of files. This assignment asks
for a package, so the code is split into five modules, each answering a
different question:

```
fitness-session-reporter/
├── main.py                 command line, calls the package in order
├── tests.py                unittest tests
├── requirements.txt        standard library only
├── data/                   the official CSV files, unchanged
└── fitness/
    ├── errors.py           what can go wrong in a way the program expects
    ├── models.py           what things exist: participants, readings, sessions
    ├── analysis.py         what the numbers mean
    ├── loading.py          can this row from the file be trusted
    └── reporting.py        how the result gets written down
```

Imports run one way only, so there are no circular imports: `errors`, then
`analysis`, then `models`, then `loading` and `reporting`, with `main.py` on
top.

## Class design

**`Participant`** holds one person and the reference values their sessions are
judged against: resting heart rate, maximum heart rate, normal skin temperature
and normal skin response. It works out the heart rate bands and the recovery
thresholds that apply to that person.

**`Athlete`** is a trained participant, whose heart rate falls faster after
effort.

**`Observation`** is one sensor reading taken at one moment, plus any warnings
attached to it.

**`Session`** is one recording: a participant and the readings taken from them.
It keeps the readings it accepted, notes about readings kept with a warning, and
notes about rows that were rejected. `analyse()` runs the whole analysis and
returns the result as a dictionary.

**`RejectedRow`** is one row, or one whole file, that could not be used, holding
the source file, row number, field and reason the brief asks to record.

### Where the object-oriented ideas appear

| Idea | Where |
| --- | --- |
| Composition | `Session` holds a `Participant` and a list of `Observation` objects, in `models.py` |
| Encapsulation | `Participant._resting_heart_rate` and `._max_heart_rate`, behind properties that check every assignment, in `models.py` |
| Inheritance | `Athlete(Participant)` in `models.py` |
| Overriding | `Athlete.recovery_thresholds()` and `Athlete.describe()` in `models.py` |
| Class method | `Participant.from_profile()`, which builds with `cls()` so `Athlete.from_profile()` returns an `Athlete`, in `models.py` |

Inheritance is used sparingly on purpose. `Athlete` only overrides the recovery
rule, because the heart rate bands are worked out from heart rate reserve, which
already adapts to the individual without needing a subclass.

`participants.csv` has no column saying who is trained, so no participant in the
official data is built as an `Athlete`. The class is covered by the tests in
`TestParticipantClass`.

## Validation rules

Checks on a session row run in this order:

1. The session ID matches `^FIT-\d{4}-\d{3}$`.
2. The participant ID matches `^P\d{3}$`.
3. That participant exists in the profiles file.
4. The row names the same participant as the rest of its session.
5. The row itself is usable: right number of columns, no blanks, numbers that
   convert, values in range, signal quality above the cutoff.

Both patterns are anchored and used with `fullmatch()`. The participant pattern
also runs on every row of `participants.csv`. Number ranges are checked with
ordinary comparisons, never with a pattern.

A row that fails steps 1 to 3 cannot be attributed to any session, so it is
reported without counting towards one. A row that gets past step 3 has
established a session, so a later failure counts against that session as well.
Both output files explain this, because it means a session's row count can be
lower than the number of rows carrying its ID in the file.

A measurement outside these ranges is not a poor reading, it is an impossible
one, so the row is rejected:

| Field | Allowed |
| --- | --- |
| `timestamp` | 0 or more |
| `heart_rate` | 20 to 250 bpm |
| `skin_response` | 0 to 30 |
| `temperature` | 20 to 45 C |
| `activity_level` | 0.0 to 1.0 |
| `signal_quality` | 0.0 to 1.0 |

### The signal quality rule

Three tiers:

- below 0.50, the reading is closer to noise than signal, so the row is rejected
- 0.50 to 0.69, the reading is doubtful but still evidence, so it is kept and
  marked with a warning
- 0.70 and above, the reading is used normally

The middle tier exists because discarding a doubtful reading can push a session
below the minimum number of readings for no good reason. A warning says more
than a missing row does.

Worth knowing: every row of `FIT-2026-005` in the valid file has a signal
quality between 0.25 and 0.34, so all five are rejected and that session is
reported as insufficient data. Nothing in either official file falls in the
middle tier, so that band is only reached by the tests.

## Classification

A session gets the first of these labels that applies:

1. **insufficient data**, if fewer than five readings were usable
2. **recovering**, if heart rate and activity both fell enough towards the end
3. **high activity**, if average heart rate reached the high band **or** average
   activity level reached 0.60
4. **moderate activity**, if average heart rate reached the elevated band **or**
   average activity level reached 0.20
5. **resting**, if neither test was met

Either half of a test is enough on its own, so a session with a low heart rate
but a lot of movement still counts, and so does the other way round.

### The two heart rate bands

The bands are worked out per person from **heart rate reserve**, which is
maximum heart rate minus resting heart rate:

```
reserve       = max heart rate - resting heart rate
elevated band = resting heart rate + 20% of reserve
high band     = resting heart rate + 50% of reserve
```

For Amina Noor, with a resting rate of 68 and the assumed maximum of 190, the
reserve is 122, so her elevated band is 92.4 bpm and her high band is 129.0 bpm.
Someone with a different resting rate gets different bands from the same
formula, which is the point: the same reading is not the same effort for two
different people.

Activity level needs no such adjustment. It is already a 0 to 1 scale that means
the same for everyone, so 0.20 and 0.60 are used directly.

One thing that catches the eye: 20% turns up in the elevated band and 0.20 turns
up as the moderate activity level. They are unrelated, one is a share of a heart
rate range and the other is a point on a fixed scale. The matching number is a
coincidence.

Recovery is checked before high activity because a hard session ending in a
cooldown satisfies both tests, and recovering is the more specific statement.
The report says so when both applied.

Recovery compares the final third of a session against its **peak** third rather
than its first, because a session that starts calm, works hard and then eases
off has its peak in the middle. Three things must all hold: heart rate fell by
at least 10 percent (15 for an `Athlete`), activity fell by at least 30 percent,
and the peak third actually reached the elevated band. Without that third test,
someone sitting still whose heart rate drifts down would be reported as
recovering from nothing.

## Assumptions

**Maximum heart rate is assumed to be 190 bpm for everyone.**
`participants.csv` has no maximum heart rate column and no age to estimate one
from. 190 is roughly what the usual 220 minus age rule gives for a thirty year
old. Both heart rate bands are fractions of the span between resting and this
number, so every band in the report rests on this assumption.

**Five usable readings are the minimum for a verdict.** Four readings split into
thirds leaves one reading per third, which is too little to call a trend either
way.

**A session belongs to one person.** The analysis compares every reading against
one participant's reference values, so a row naming a different participant is
rejected rather than averaged in.

**Timestamps order a session but are not measured.** Neither timestamp nor
signal quality is averaged, since one orders the readings and the other
describes the sensor rather than the person.

## Example output

The console summary from `python main.py` with no arguments:

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

`output/analysis_summary.csv`:

```
session_id,participant_id,participant_name,classification,rows_attributed,rows_usable,rows_flagged,rows_rejected,avg_heart_rate,min_heart_rate,max_heart_rate,avg_skin_response,avg_temperature,avg_activity_level,heart_rate_zone,recovery_detected
FIT-2026-001,P001,Amina Noor,resting,6,6,0,0,68.8,68.0,70.0,1.2,32.4,0.09,below elevated,no
FIT-2026-002,P002,Jonas Berg,moderate activity,6,6,0,0,102.0,78.0,118.0,2.0,33.1,0.49,elevated,no
FIT-2026-003,P003,Maya Chen,high activity,6,6,0,0,132.5,72.0,162.0,3.2,33.5,0.75,high,no
FIT-2026-004,P001,Amina Noor,recovering,6,6,0,0,113.2,72.0,151.0,2.6,33.3,0.55,elevated,yes
FIT-2026-005,P002,Jonas Berg,insufficient data,5,0,0,5,,,,,,,,
FIT-2026-101,P001,Amina Noor,insufficient data,4,1,0,3,72.0,72.0,72.0,1.3,32.5,0.10,below elevated,no
FIT-2026-102,P002,Jonas Berg,insufficient data,3,0,0,3,,,,,,,,
FIT-2026-103,P003,Maya Chen,insufficient data,1,0,0,1,,,,,,,,
```

The five sessions in the valid file happen to cover every classification the
program can produce.

`FIT-2026-101` is the row worth looking at. It has one usable reading out of
four, so there are real figures in the measurement columns, and it is still
classified as insufficient data because one reading is below the minimum of
five. Having data and having enough data are different answers.

One session from `output/analysis_report.txt`:

```
================================================================
  Session:     FIT-2026-004
  Participant: Amina Noor (P001, resting HR 68 bpm, max 190 bpm)
================================================================

OBSERVATIONS
  Rows attributed        6
  Usable                 6
    of which flagged     0  (kept)
  Rejected               0

SUMMARY  (usable observations only)
  Measurement        Average   Minimum   Maximum   Unit
  Heart rate           113.2      72.0     151.0   bpm
  Skin response          2.6       1.4       3.9   uS
  Temperature           33.3      32.6      33.9   C
  Activity level        0.55      0.18      0.92

COMPARISON WITH REFERENCE VALUES
  Heart rate    113.2 bpm  ->  elevated
                bands: elevated 92.4 bpm, high 129.0 bpm
                +45.2 bpm relative to resting
  Temperature   33.3 C  ->  above normal
                reference 32.4 C, difference +0.9 C
  Skin response 2.6 uS
                reference 1.2 uS, difference +1.4 uS

RECOVERY
  Detected.
    Heart rate  141.5 -> 93.0 bpm  (34% fall, 10% required)
    Activity    0.81 -> 0.30       (63% fall, 30% required)

CLASSIFICATION:  RECOVERING
  Recovering: between the session's peak third and its final
  third, heart rate fell 34% (141.5 to 93.0 bpm) and activity
  fell 63% (0.81 to 0.30), meeting the 10% and 30% required. The
  peak third averaged 141.5 bpm, at or above the elevated band
  (92.4 bpm), so there was real effort to recover from. The
  session also met the moderate-activity test; 'recovering' is
  reported because it is the more specific finding.

FLAGGED READINGS  (0 kept)
  None.

REJECTED READINGS  (0 discarded)
  None.
```

The start of `output/rejected_records.txt`:

```
REJECTED RECORDS
15 records rejected in total.

A row counts towards a session's own totals only once its
session ID and participant ID have both been read and the
participant is known. A row rejected before that point still
names its session where the session ID was readable, marked
'not counted against it'.

FILES THAT COULD NOT BE READ  (0)
  None.

MALFORMED IDENTIFIERS  (2)
  - fitness_sessions_invalid.csv row 4, session FIT-2026-101 (not counted against it), field 'participant_id': '001' is not a valid participant_id, expected P followed by three digits, like P001
  - fitness_sessions_invalid.csv row 7, field 'session_id': 'FIT-26-102' is not a valid session_id, expected FIT-YYYY-NNN, like FIT-2026-001

UNUSABLE DATA  (13)
  - fitness_sessions.csv row 26, session FIT-2026-005, field 'signal_quality': signal quality 0.34 is below the 0.50 usable cutoff
```

## Known limitations

The 190 bpm maximum heart rate is a guess applied to everyone, so the elevated
and high bands are approximate. Real reference values, or an age column to
estimate from, would fix this.

The signal quality cutoffs of 0.50 and 0.70, the five reading minimum, and the
10, 15 and 30 percent recovery thresholds are judgements rather than
measurements. They are reasonable, but they are not derived from anything.

Nothing checks whether timestamps are unique or evenly spaced. Two readings with
the same timestamp are both accepted, and a session is split into thirds by
position rather than by elapsed time.

The header check only looks for the columns the program needs. A file with the
right column names but nonsense underneath them would be read row by row and
rejected row by row.

Each session file is read into memory in full. The official files are small so
this is fine, but a very large file would not stream.

`Athlete` is never built from the official data, because `participants.csv` has
no column for it.

## Submission

Repository: https://github.com/Jonnyyyc/fitness-session-reporter
