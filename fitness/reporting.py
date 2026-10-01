"""Writing the summary, the readable report and the rejection list.

Three files go into the output folder, which is created if it is not there.
Each run replaces them rather than adding to them, so running the program twice
gives the same result without any cleanup in between.

Nothing here calculates anything. Every number comes from the result dictionary
that Session.analyse() returns, so a figure in the CSV and the same figure in
the text report cannot disagree. Rounding happens here and nowhere else.
"""

import csv
import textwrap
from pathlib import Path

from .analysis import SUMMARY_FIELDS
from .models import FIELD_UNITS

SUMMARY_FILENAME = "analysis_summary.csv"
REPORT_FILENAME = "analysis_report.txt"
REJECTED_FILENAME = "rejected_records.txt"

# Column headings for the summary table in the text report.
FIELD_LABELS = {
    "heart_rate": "Heart rate",
    "skin_response": "Skin response",
    "temperature": "Temperature",
    "activity_level": "Activity level",
}

# Decimal places for each measurement. One suits the sensor readings, but
# activity_level is a 0 to 1 scale where one decimal leaves only ten possible
# values and anything under 0.05 collapses to zero, so it gets two.
FIELD_DECIMALS = {
    "heart_rate": 1,
    "skin_response": 1,
    "temperature": 1,
    "activity_level": 2,
}

# One row per session. The identifiers and counts always have a value. The
# measurement columns are empty when a session had nothing usable to measure.
IDENTITY_COLUMNS = (
    "session_id",
    "participant_id",
    "participant_name",
    "classification",
    "rows_attributed",
    "rows_usable",
    "rows_flagged",
    "rows_rejected",
)
MEASUREMENT_COLUMNS = (
    "avg_heart_rate",
    "min_heart_rate",
    "max_heart_rate",
    "avg_skin_response",
    "avg_temperature",
    "avg_activity_level",
    "heart_rate_zone",
    "recovery_detected",
)
SUMMARY_COLUMNS = IDENTITY_COLUMNS + MEASUREMENT_COLUMNS

REPORT_WIDTH = 64


def rounded(value, field):
    """Format one measurement at the number of decimals that field uses."""
    return f"{value:.{FIELD_DECIMALS[field]}f}"


def signed(value, places=1):
    """Format a difference with its sign, without printing a stray '-0.0'.

    A difference of -0.04 rounds to -0.0, which reads like a bug. It is zero at
    the precision being shown, so it is printed as +0.0 instead.
    """
    # -0.0 == 0 is True in Python, so this catches the negative zero as well.
    if round(value, places) == 0:
        value = 0.0
    return f"{value:+.{places}f}"


def write_reports(results, rejected, output_dir):
    """Write all three files and return the paths, in the order written."""
    directory = Path(output_dir)
    # parents=True so a nested path works, exist_ok=True so a second run does
    # not fail on a folder that is already there.
    directory.mkdir(parents=True, exist_ok=True)

    summary_path = directory / SUMMARY_FILENAME
    report_path = directory / REPORT_FILENAME
    rejected_path = directory / REJECTED_FILENAME

    write_summary_csv(results, summary_path)
    write_report_text(results, report_path)
    write_rejected_records(rejected, rejected_path)

    return [summary_path, report_path, rejected_path]


def summary_row(result):
    """Turn one analysis result into one row of analysis_summary.csv."""
    counts = result["observations"]
    summary = result["summary"]

    row = {
        "session_id": result["session_id"],
        "participant_id": result["participant_id"],
        "participant_name": result["participant_name"],
        "classification": result["classification"],
        "rows_attributed": counts["total"],
        "rows_usable": counts["usable"],
        "rows_flagged": counts["flagged"],
        "rows_rejected": counts["rejected"],
    }

    # A session with nothing usable leaves these columns empty rather than
    # writing a zero. Zero is a measurement; an empty cell is the absence of
    # one, and the two should not look the same in a spreadsheet.
    if not summary:
        for column in MEASUREMENT_COLUMNS:
            row[column] = ""
        return row

    heart_rate = summary["heart_rate"]
    row["avg_heart_rate"] = rounded(heart_rate["avg"], "heart_rate")
    row["min_heart_rate"] = rounded(heart_rate["min"], "heart_rate")
    row["max_heart_rate"] = rounded(heart_rate["max"], "heart_rate")
    row["avg_skin_response"] = rounded(summary["skin_response"]["avg"],
                                       "skin_response")
    row["avg_temperature"] = rounded(summary["temperature"]["avg"],
                                     "temperature")
    row["avg_activity_level"] = rounded(summary["activity_level"]["avg"],
                                        "activity_level")
    row["heart_rate_zone"] = result["comparison"]["heart_rate"]["zone"]
    row["recovery_detected"] = "yes" if result["recovery"]["detected"] else "no"
    return row


def write_summary_csv(results, path):
    """Write one row per session, in session ID order."""
    # newline="" is what the csv module asks for. Without it, Windows turns
    # every line ending into a blank line between rows.
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_COLUMNS)
        writer.writeheader()
        for result in results:
            writer.writerow(summary_row(result))


def format_report(result):
    """Render one analysis result as plain text.

    Returns a string rather than printing, so the caller decides where it goes
    and a test can read it directly.
    """
    width = REPORT_WIDTH
    lines = []

    # 1. Who and what.
    lines.append("=" * width)
    lines.append(f"  Session:     {result['session_id']}")
    lines.append(f"  Participant: {result['participant']}")
    lines.append("=" * width)
    lines.append("")

    # 2. What arrived and what survived.
    counts = result["observations"]
    lines.append("OBSERVATIONS")
    lines.append(f"  Rows attributed     {counts['total']:>4}")
    lines.append(f"  Usable              {counts['usable']:>4}")
    lines.append(f"    of which flagged  {counts['flagged']:>4}  (kept)")
    lines.append(f"  Rejected            {counts['rejected']:>4}")
    lines.append("")

    # 3. The figures.
    summary = result["summary"]
    lines.append("SUMMARY  (usable observations only)")
    if not summary:
        lines.append("  No usable observations to summarise.")
    else:
        lines.append(f"  {'Measurement':<16}{'Average':>10}{'Minimum':>10}"
                     f"{'Maximum':>10}   Unit")
        for field in SUMMARY_FIELDS:
            figures = summary[field]
            unit = FIELD_UNITS[field]
            places = FIELD_DECIMALS[field]
            lines.append(
                (f"  {FIELD_LABELS[field]:<16}"
                 f"{figures['avg']:>10.{places}f}"
                 f"{figures['min']:>10.{places}f}"
                 f"{figures['max']:>10.{places}f}   {unit}").rstrip()
            )
    lines.append("")

    # 4. Against this participant's own normals.
    comparison = result["comparison"]
    lines.append("COMPARISON WITH REFERENCE VALUES")
    if not comparison:
        lines.append("  Nothing to compare.")
    else:
        heart_rate = comparison["heart_rate"]
        temperature = comparison["temperature"]
        lines.append(f"  Heart rate    {heart_rate['average']:.1f} bpm  ->  "
                     f"{heart_rate['zone']}")
        lines.append(f"                bands: elevated "
                     f"{heart_rate['elevated_band']:.1f} bpm, high "
                     f"{heart_rate['high_band']:.1f} bpm")
        lines.append(f"                {signed(heart_rate['above_resting'])} "
                     f"bpm relative to resting")
        lines.append(f"  Temperature   {temperature['average']:.1f} C  ->  "
                     f"{temperature['direction']}")
        lines.append(f"                reference "
                     f"{temperature['reference']:.1f} C, difference "
                     f"{signed(temperature['difference'])} C")
        if "skin_response" in comparison:
            skin_response = comparison["skin_response"]
            lines.append(f"  Skin response {skin_response['average']:.1f} uS")
            lines.append(f"                reference "
                         f"{skin_response['reference']:.1f} uS, difference "
                         f"{signed(skin_response['difference'])} uS")
    lines.append("")

    # 5. Recovery, stated either way.
    recovery = result["recovery"]
    lines.append("RECOVERY")
    if recovery["detected"]:
        required = recovery["required"]
        lines.append("  Detected.")
        lines.append(f"    Heart rate  {recovery['peak_heart_rate']:.1f} -> "
                     f"{recovery['final_heart_rate']:.1f} bpm  "
                     f"({recovery['heart_rate_drop']:.0%} fall, "
                     f"{required['heart_rate_drop']:.0%} required)")
        lines.append(f"    Activity    {recovery['peak_activity']:.2f} -> "
                     f"{recovery['final_activity']:.2f}       "
                     f"({recovery['activity_drop']:.0%} fall, "
                     f"{required['activity_drop']:.0%} required)")
    else:
        lines.append("  Not detected.")
        # The reason can be a full sentence, so it wraps rather than running
        # off the edge of the page.
        for line in textwrap.wrap(recovery["reason"], width=width - 4):
            lines.append(f"    {line}")
    lines.append("")

    # 6. The verdict, and why.
    lines.append(f"CLASSIFICATION:  {result['classification'].upper()}")
    for line in textwrap.wrap(result["explanation"], width=width - 2):
        lines.append(f"  {line}")
    lines.append("")

    # 7. The two groups, kept apart: kept-but-imperfect, and discarded.
    lines.append(f"FLAGGED READINGS  ({counts['flagged']} kept)")
    if result["flag_notes"]:
        for note in result["flag_notes"]:
            lines.append(f"  - {note}")
    else:
        lines.append("  None.")
    lines.append("")

    lines.append(f"REJECTED READINGS  ({counts['rejected']} discarded)")
    if result["rejection_notes"]:
        for note in result["rejection_notes"]:
            lines.append(f"  - {note}")
    else:
        lines.append("  None.")

    return "\n".join(lines)


def write_report_text(results, path):
    """Write the readable explanation of every session into one file."""
    blocks = [
        "SMART FITNESS SESSION ANALYZER",
        f"{len(results)} session{'' if len(results) == 1 else 's'} analysed.",
        "",
        "A row is attributed to a session once its session ID and participant",
        "ID have both been read and the participant is known. Rows rejected",
        "before that point are not counted here; they are listed in",
        "rejected_records.txt instead.",
        "",
    ]
    for result in results:
        blocks.append(format_report(result))
        blocks.append("")

    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(blocks))


def write_rejected_records(rejected, path):
    """Write every rejected row, grouped by what kind of problem it was."""
    # Grouped rather than listed in arrival order, because the three kinds have
    # different causes: a file that could not be read is a setup problem, a
    # malformed identifier is a typo, and unusable data is a sensor or entry
    # problem. The 'kind' on each RejectedRow is what makes this possible.
    groups = [
        ("file", "FILES THAT COULD NOT BE READ"),
        ("identifier", "MALFORMED IDENTIFIERS"),
        ("record", "UNUSABLE DATA"),
    ]

    lines = ["REJECTED RECORDS",
             f"{len(rejected)} record{'' if len(rejected) == 1 else 's'} "
             f"rejected in total.",
             "",
             "A row counts towards a session's own totals only once its",
             "session ID and participant ID have both been read and the",
             "participant is known. A row rejected before that point still",
             "names its session where the session ID was readable, marked",
             "'not counted against it'.",
             ""]

    for kind, heading in groups:
        entries = [entry for entry in rejected if entry.kind == kind]
        lines.append(f"{heading}  ({len(entries)})")
        if entries:
            for entry in entries:
                lines.append(f"  - {entry.describe()}")
        else:
            lines.append("  None.")
        lines.append("")

    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
