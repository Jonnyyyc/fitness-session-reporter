"""Tests for the fitness package.

Run from the repository root:

    python3 -m unittest tests.py     (macOS / Linux)
    python -m unittest tests.py      (Windows)

Tests that need a file write their own into a temporary folder, so the suite
does not depend on data/. TestTheOfficialFiles is the exception and skips
itself when those files are missing.

Rejection tests assert on the reason text, not just that something was
rejected, so a test cannot pass for the wrong reason.
"""

import contextlib
import csv
import io
import shutil
import tempfile
import unittest
from pathlib import Path

import main
from fitness.analysis import (MINIMUM_USABLE_OBSERVATIONS, classify_session,
                              detect_recovery, summarise)
from fitness.errors import InvalidIdentifierError, InvalidRecordError
from fitness.loading import (SIGNAL_QUALITY_FLAG, SIGNAL_QUALITY_REJECT,
                             check_header, read_participants, read_sessions)
from fitness.models import Athlete, Observation, Participant, Session
from fitness.reporting import write_reports

PROFILE_HEADER = ("participant_id,name,baseline_heart_rate,"
                  "baseline_skin_response,baseline_temperature")
SESSION_HEADER = ("session_id,participant_id,timestamp,heart_rate,"
                  "skin_response,temperature,activity_level,signal_quality")

# Two real rows from the official profiles file, so the tests use the same
# reference values the program will see in a real run.
PROFILE_ROWS = ["P001,Amina Noor,68,1.20,32.4",
                "P002,Jonas Berg,74,1.45,32.7"]


class TempFileTestCase(unittest.TestCase):
    """Base class giving each test its own temporary folder."""

    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)

    def write_csv(self, name, header, rows):
        """Write a CSV and return its path."""
        path = self.folder / name
        path.write_text("\n".join([header] + list(rows)) + "\n",
                        encoding="utf-8")
        return path

    def write_profiles(self, rows=PROFILE_ROWS):
        return self.write_csv("profiles.csv", PROFILE_HEADER, rows)

    def load(self, session_rows, profile_rows=PROFILE_ROWS):
        """Write both files, read them, and return (sessions, rejected)."""
        participants, bad = self.write_profiles(profile_rows), None
        participants, bad = read_participants(participants)
        sessions_path = self.write_csv("sessions.csv", SESSION_HEADER,
                                       session_rows)
        sessions, rejected = read_sessions([sessions_path], participants)
        return sessions, bad + rejected

    def only_rejection(self, rejected):
        """Assert exactly one rejection and return it."""
        self.assertEqual(len(rejected), 1,
                         f"expected one rejection, got "
                         f"{[r.describe() for r in rejected]}")
        return rejected[0]


def session_row(timestamp, heart_rate, activity=0.5, quality=0.95,
                session="FIT-2026-001", participant="P001"):
    """Build one well-formed session row, with one field overridden at a time."""
    return (f"{session},{participant},{timestamp},{heart_rate},1.50,32.7,"
            f"{activity},{quality}")


class TestValidData(TempFileTestCase):
    """A file with nothing wrong in it."""

    def test_all_rows_are_accepted(self):
        rows = [session_row(t, 70) for t in range(6)]
        sessions, rejected = self.load(rows)

        self.assertEqual(rejected, [])
        self.assertEqual(len(sessions), 1)
        session = sessions["FIT-2026-001"]
        self.assertEqual(session.usable_count, 6)
        self.assertEqual(session.rejected_count, 0)
        self.assertEqual(session.participant.name, "Amina Noor")

    def test_values_are_converted_to_numbers(self):
        sessions, _ = self.load([session_row(0, 70)])
        observation = sessions["FIT-2026-001"].observations[0]

        # The brief asks for suitable types, not just "not a string".
        self.assertIsInstance(observation.timestamp, int)
        self.assertIsInstance(observation.heart_rate, int)
        self.assertIsInstance(observation.temperature, float)

    def test_rows_are_grouped_by_session_id(self):
        rows = ([session_row(t, 70, session="FIT-2026-001") for t in range(6)]
                + [session_row(t, 90, session="FIT-2026-002",
                               participant="P002") for t in range(6)])
        sessions, rejected = self.load(rows)

        self.assertEqual(rejected, [])
        self.assertEqual(sorted(sessions), ["FIT-2026-001", "FIT-2026-002"])
        self.assertEqual(sessions["FIT-2026-002"].participant.participant_id,
                         "P002")


class TestInvalidData(TempFileTestCase):
    """The kinds of broken row the invalid file contains."""

    def test_text_where_a_number_belongs(self):
        sessions, rejected = self.load([session_row(0, "fast")])
        entry = self.only_rejection(rejected)

        self.assertEqual(entry.field, "heart_rate")
        self.assertIn("not a whole number", entry.reason)

    def test_empty_field(self):
        row = "FIT-2026-001,P001,0,70,1.50,32.7,,0.95"
        sessions, rejected = self.load([row])
        entry = self.only_rejection(rejected)

        self.assertEqual(entry.field, "activity_level")
        self.assertIn("is empty", entry.reason)

    def test_short_row_reports_the_missing_column(self):
        row = "FIT-2026-001,P001,0,70,1.50,32.7,0.50"
        sessions, rejected = self.load([row])
        entry = self.only_rejection(rejected)

        self.assertEqual(entry.field, "signal_quality")
        self.assertIn("missing from this row", entry.reason)

    def test_extra_columns(self):
        row = session_row(0, 70) + ",extra,columns"
        sessions, rejected = self.load([row])
        entry = self.only_rejection(rejected)

        self.assertIn("more columns than the header", entry.reason)

    def test_impossible_measurement(self):
        sessions, rejected = self.load([session_row(0, -15)])
        entry = self.only_rejection(rejected)

        self.assertEqual(entry.field, "heart_rate")
        self.assertIn("outside the valid range", entry.reason)

    def test_malformed_participant_id(self):
        sessions, rejected = self.load([session_row(0, 70, participant="001")])
        entry = self.only_rejection(rejected)

        self.assertEqual(entry.kind, "identifier")
        self.assertEqual(entry.field, "participant_id")
        # The session ID was readable, so the rejection names the session even
        # though the row does not count towards it.
        self.assertEqual(entry.session_id, "FIT-2026-001")
        self.assertFalse(entry.counted)

    def test_malformed_session_id_cannot_name_a_session(self):
        sessions, rejected = self.load([session_row(0, 70, session="FIT-26-1")])
        entry = self.only_rejection(rejected)

        self.assertEqual(entry.kind, "identifier")
        self.assertEqual(entry.field, "session_id")
        self.assertEqual(entry.session_id, "")
        self.assertEqual(sessions, {})

    def test_unknown_participant(self):
        sessions, rejected = self.load([session_row(0, 70, participant="P999")])
        entry = self.only_rejection(rejected)

        self.assertIn("not in the profiles file", entry.reason)
        self.assertFalse(entry.counted)

    def test_one_bad_row_does_not_stop_the_others(self):
        rows = [session_row(0, 70), session_row(1, "fast"), session_row(2, 72)]
        sessions, rejected = self.load(rows)

        self.assertEqual(len(rejected), 1)
        self.assertEqual(sessions["FIT-2026-001"].usable_count, 2)


class TestParticipantMismatch(TempFileTestCase):
    """A row naming a different known participant from the rest of its session.

    If P002 is missing from the profiles file the row is rejected one step
    earlier instead, so these tests check the reason text.
    """

    def test_mismatched_row_is_rejected_and_counted(self):
        rows = [session_row(0, 70, participant="P001"),
                session_row(1, 72, participant="P002"),
                session_row(2, 74, participant="P001")]
        sessions, rejected = self.load(rows)
        entry = self.only_rejection(rejected)

        self.assertIn("was established with P001", entry.reason)
        self.assertTrue(entry.counted)

        session = sessions["FIT-2026-001"]
        self.assertEqual(session.participant.participant_id, "P001")
        self.assertEqual(session.usable_count, 2)
        self.assertEqual(session.rejected_count, 1)

    def test_the_mismatch_branch_is_really_reached(self):
        """Guard against the test above passing for the wrong reason."""
        rows = [session_row(0, 70, participant="P001"),
                session_row(1, 72, participant="P002")]
        # P002 removed from the profiles, so the same row now fails earlier.
        sessions, rejected = self.load(rows, profile_rows=PROFILE_ROWS[:1])
        entry = self.only_rejection(rejected)

        self.assertIn("not in the profiles file", entry.reason)
        self.assertNotIn("was established with", entry.reason)


class TestBoundaries(TempFileTestCase):
    """The exact values where a rule changes its mind."""

    def test_signal_quality_at_the_reject_cutoff_is_kept(self):
        # The rule is "below 0.50 is rejected", so 0.50 itself is usable.
        sessions, rejected = self.load(
            [session_row(0, 70, quality=SIGNAL_QUALITY_REJECT)])

        self.assertEqual(rejected, [])
        self.assertEqual(sessions["FIT-2026-001"].usable_count, 1)

    def test_just_below_the_reject_cutoff_is_rejected(self):
        sessions, rejected = self.load([session_row(0, 70, quality=0.49)])
        entry = self.only_rejection(rejected)

        self.assertEqual(entry.field, "signal_quality")
        self.assertIn("below the 0.50 usable cutoff", entry.reason)

    def test_signal_quality_at_the_flag_cutoff_is_not_flagged(self):
        # "below 0.70 is flagged", so 0.70 itself is clean.
        sessions, _ = self.load(
            [session_row(0, 70, quality=SIGNAL_QUALITY_FLAG)])
        session = sessions["FIT-2026-001"]

        self.assertEqual(session.usable_count, 1)
        self.assertEqual(session.flagged_count, 0)

    def test_the_flag_tier_keeps_the_reading_and_warns(self):
        """0.50 to 0.69, the band nothing in the official files reaches."""
        sessions, rejected = self.load([session_row(0, 70, quality=0.60)])
        session = sessions["FIT-2026-001"]

        self.assertEqual(rejected, [])
        self.assertEqual(session.usable_count, 1)
        self.assertEqual(session.flagged_count, 1)
        self.assertIn("weak signal (0.60)", session.flag_notes[0])

    def test_exactly_the_minimum_usable_rows_is_classified(self):
        rows = [session_row(t, 70) for t in range(MINIMUM_USABLE_OBSERVATIONS)]
        sessions, _ = self.load(rows)
        result = sessions["FIT-2026-001"].analyse()

        self.assertEqual(result["observations"]["usable"],
                         MINIMUM_USABLE_OBSERVATIONS)
        self.assertNotEqual(result["classification"], "insufficient data")

    def test_one_below_the_minimum_is_insufficient_data(self):
        rows = [session_row(t, 70)
                for t in range(MINIMUM_USABLE_OBSERVATIONS - 1)]
        sessions, _ = self.load(rows)
        result = sessions["FIT-2026-001"].analyse()

        self.assertEqual(result["classification"], "insufficient data")

    def test_usable_rows_but_still_too_few(self):
        """Having data and having enough data are different answers."""
        rows = [session_row(0, 70)] + [session_row(t, "fast")
                                       for t in range(1, 5)]
        sessions, _ = self.load(rows)
        result = sessions["FIT-2026-001"].analyse()

        # There are real figures, and the verdict is still insufficient data.
        self.assertEqual(result["observations"]["usable"], 1)
        self.assertTrue(result["summary"])
        self.assertEqual(result["classification"], "insufficient data")


class TestProfiles(TempFileTestCase):
    """Reading participants.csv."""

    def test_bad_profile_row_is_skipped_and_the_rest_still_load(self):
        rows = ["P001,Amina Noor,68,1.20,32.4",
                "XX9,Broken Id,70,1.30,32.5",
                "P004,No Pulse,999,1.30,32.5",
                "P005,Not A Number,seventy,1.30,32.5",
                "P002,Jonas Berg,74,1.45,32.7"]
        participants, rejected = read_participants(self.write_profiles(rows))

        self.assertEqual(sorted(participants), ["P001", "P002"])
        self.assertEqual(len(rejected), 3)

        reasons = [entry.reason for entry in rejected]
        self.assertIn("identifier", [e.kind for e in rejected])
        self.assertTrue(any("outside 20 to 120 bpm" in r for r in reasons))
        self.assertTrue(any("not a whole number" in r for r in reasons))

    def test_a_skipped_participant_rejects_their_session_rows(self):
        """One bad profile row can reject many session rows."""
        rows = [session_row(t, 90, session="FIT-2026-002", participant="P002")
                for t in range(3)]
        sessions, rejected = self.load(rows, profile_rows=PROFILE_ROWS[:1])

        self.assertEqual(sessions, {})
        self.assertEqual(len(rejected), 3)
        for entry in rejected:
            self.assertIn("not in the profiles file", entry.reason)


class TestMissingAndUnreadableFiles(TempFileTestCase):
    """Brief section 4.4: continue to the next file where that is safe."""

    def test_missing_session_file_is_reported_and_skipped(self):
        participants, _ = read_participants(self.write_profiles())
        good = self.write_csv("good.csv", SESSION_HEADER,
                              [session_row(t, 70) for t in range(6)])
        sessions, rejected = read_sessions([self.folder / "nope.csv", good],
                                           participants)

        # The good file was still read.
        self.assertEqual(sessions["FIT-2026-001"].usable_count, 6)
        entry = self.only_rejection(rejected)
        self.assertEqual(entry.kind, "file")
        self.assertIsNone(entry.row_number)
        self.assertIn("file not found", entry.reason)

    def test_missing_profiles_file_raises_to_the_caller(self):
        with self.assertRaises(FileNotFoundError):
            read_participants(self.folder / "nope.csv")


class TestHeaderCheck(TempFileTestCase):
    """One clear message beats every row failing separately."""

    def test_session_file_with_the_wrong_header_is_skipped(self):
        participants, _ = read_participants(self.write_profiles())
        wrong = self.write_csv("wrong.csv", "a,b,c", ["1,2,3"])
        good = self.write_csv("good.csv", SESSION_HEADER,
                              [session_row(t, 70) for t in range(6)])
        sessions, rejected = read_sessions([wrong, good], participants)

        self.assertEqual(sessions["FIT-2026-001"].usable_count, 6)
        entry = self.only_rejection(rejected)
        self.assertEqual(entry.kind, "file")
        self.assertIn("header is missing", entry.reason)
        self.assertIn("session_id", entry.reason)

    def test_profiles_file_with_the_wrong_header_raises(self):
        wrong = self.write_csv("wrong.csv", "a,b,c", ["1,2,3"])
        with self.assertRaises(InvalidRecordError) as caught:
            read_participants(wrong)

        self.assertIn("header is missing", str(caught.exception))

    def test_an_empty_file_has_no_header_at_all(self):
        empty = self.folder / "empty.csv"
        empty.write_text("", encoding="utf-8")
        participants, _ = read_participants(self.write_profiles())
        sessions, rejected = read_sessions([empty], participants)

        self.assertEqual(sessions, {})
        self.assertIn("header is missing",
                      self.only_rejection(rejected).reason)

    def test_extra_columns_in_the_header_are_allowed(self):
        """The check is for a file that is the wrong file, not a strict match."""
        check_header(list(SESSION_HEADER.split(",")) + ["notes"],
                     ("session_id", "participant_id"))


class TestParticipantClass(unittest.TestCase):
    """Encapsulation, inheritance and the class method."""

    PROFILE = {"participant_id": "P001", "name": "Amina Noor",
               "baseline_heart_rate": 68, "baseline_skin_response": 1.20,
               "baseline_temperature": 32.4}

    def test_from_profile_builds_a_participant(self):
        participant = Participant.from_profile(self.PROFILE)

        self.assertEqual(participant.participant_id, "P001")
        self.assertEqual(participant.name, "Amina Noor")
        self.assertEqual(participant.resting_heart_rate, 68)

    def test_from_profile_on_athlete_returns_an_athlete(self):
        """It builds with cls(), which is the point of the class method."""
        athlete = Athlete.from_profile(self.PROFILE)

        self.assertIsInstance(athlete, Athlete)
        self.assertIsInstance(athlete, Participant)

    def test_athlete_overrides_only_the_recovery_rule(self):
        participant = Participant.from_profile(self.PROFILE)
        athlete = Athlete.from_profile(self.PROFILE)

        self.assertEqual(participant.recovery_thresholds()["heart_rate_drop"],
                         0.10)
        self.assertEqual(athlete.recovery_thresholds()["heart_rate_drop"], 0.15)
        # The bands come from the reserve formula, so they are not overridden.
        self.assertEqual(participant.heart_rate_bands(),
                         athlete.heart_rate_bands())

    def test_the_override_does_not_change_the_base_class(self):
        athlete = Athlete.from_profile(self.PROFILE)
        athlete.recovery_thresholds()
        participant = Participant.from_profile(self.PROFILE)

        self.assertEqual(participant.recovery_thresholds()["heart_rate_drop"],
                         0.10)

    def test_a_boolean_is_not_a_heart_rate(self):
        # True is technically the number 1 in Python, so without the check a
        # resting heart rate of True would quietly become 1 bpm.
        with self.assertRaises(ValueError):
            Participant("P001", "Test", True)

    def test_resting_heart_rate_is_range_checked_on_construction(self):
        with self.assertRaises(ValueError):
            Participant("P001", "Test", 300)

    def test_resting_must_be_below_maximum(self):
        with self.assertRaises(ValueError):
            Participant("P001", "Test", 100, max_heart_rate=100)

    def test_from_profile_reports_a_missing_field(self):
        incomplete = dict(self.PROFILE)
        del incomplete["baseline_temperature"]

        with self.assertRaises(ValueError):
            Participant.from_profile(incomplete)


class TestAnalysis(unittest.TestCase):
    """The calculations, with observations built by hand."""

    def setUp(self):
        self.participant = Participant("P001", "Amina Noor", 68,
                                       normal_temperature=32.4,
                                       normal_skin_response=1.20)

    def observations(self, heart_rates, activities=None):
        if activities is None:
            activities = [0.5] * len(heart_rates)
        return [Observation(t, hr, 1.5, 32.7, activity, 0.95)
                for t, (hr, activity) in enumerate(zip(heart_rates,
                                                       activities))]

    def test_summarise_an_empty_list(self):
        self.assertEqual(summarise([]), {})

    def test_summarise_gives_average_minimum_and_maximum(self):
        summary = summarise(self.observations([60, 70, 80]))

        self.assertEqual(summary["heart_rate"]["avg"], 70)
        self.assertEqual(summary["heart_rate"]["min"], 60)
        self.assertEqual(summary["heart_rate"]["max"], 80)

    def test_recovery_needs_three_readings(self):
        recovery = detect_recovery(self.observations([120, 100]),
                                   self.participant)

        self.assertFalse(recovery["detected"])
        self.assertIn("too few observations", recovery["reason"])

    def test_recovery_after_real_effort(self):
        heart_rates = [70, 140, 150, 145, 100, 80]
        activities = [0.2, 0.9, 0.95, 0.8, 0.3, 0.1]
        recovery = detect_recovery(self.observations(heart_rates, activities),
                                   self.participant)

        self.assertTrue(recovery["detected"])

    def test_a_falling_heart_rate_at_rest_is_not_recovery(self):
        """Nothing to recover from if the peak never reached the band."""
        heart_rates = [75, 74, 73, 72, 70, 68]
        activities = [0.05] * 6
        recovery = detect_recovery(self.observations(heart_rates, activities),
                                   self.participant)

        self.assertFalse(recovery["detected"])
        self.assertIn("nothing to recover from", recovery["reason"])

    def test_classification_explains_itself(self):
        observations = self.observations([70] * 6, [0.05] * 6)
        summary = summarise(observations)
        recovery = detect_recovery(observations, self.participant)
        label, explanation = classify_session(summary, self.participant,
                                              len(observations), recovery)

        self.assertEqual(label, "resting")
        self.assertIn("bpm", explanation)

    def test_the_comparison_uses_the_participants_own_references(self):
        """Two people, the same readings, different answers.

        Activity is low on purpose: it means the same for everyone, so a high
        value would classify both as moderate and prove nothing.
        """
        observations = self.observations([95] * 6, [0.05] * 6)
        summary = summarise(observations)
        fit = Participant("P001", "Lower resting rate", 50)
        unfit = Participant("P002", "Higher resting rate", 90)

        self.assertEqual(classify_session(summary, fit, 6,
                                          {"detected": False})[0],
                         "moderate activity")
        self.assertEqual(classify_session(summary, unfit, 6,
                                          {"detected": False})[0],
                         "resting")


class TestOutputFiles(TempFileTestCase):
    """Brief section 4.6."""

    def analysed(self):
        sessions, rejected = self.load([session_row(t, 70) for t in range(6)])
        return [sessions[key].analyse() for key in sorted(sessions)], rejected

    def test_the_output_folder_is_created_when_missing(self):
        results, rejected = self.analysed()
        target = self.folder / "made" / "up" / "path"
        self.assertFalse(target.exists())

        written = write_reports(results, rejected, target)

        self.assertTrue(target.is_dir())
        self.assertEqual(len(written), 3)
        for path in written:
            self.assertTrue(path.is_file())

    def test_a_second_run_gives_identical_files(self):
        """The brief asks for no manual cleanup between runs."""
        results, rejected = self.analysed()
        target = self.folder / "out"

        write_reports(results, rejected, target)
        first = {path.name: path.read_bytes() for path in target.iterdir()}
        write_reports(results, rejected, target)
        second = {path.name: path.read_bytes() for path in target.iterdir()}

        self.assertEqual(first, second)

    def test_the_summary_csv_has_one_row_per_session(self):
        results, rejected = self.analysed()
        target = self.folder / "out"
        write_reports(results, rejected, target)

        with open(target / "analysis_summary.csv", encoding="utf-8",
                  newline="") as handle:
            rows = list(csv.DictReader(handle))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["session_id"], "FIT-2026-001")
        self.assertEqual(rows[0]["rows_usable"], "6")

    def test_a_session_with_nothing_usable_leaves_the_numbers_empty(self):
        rows = [session_row(t, 70, quality=0.10) for t in range(3)]
        sessions, rejected = self.load(rows)
        results = [sessions[key].analyse() for key in sorted(sessions)]
        target = self.folder / "out"
        write_reports(results, rejected, target)

        with open(target / "analysis_summary.csv", encoding="utf-8",
                  newline="") as handle:
            row = next(csv.DictReader(handle))

        self.assertEqual(row["classification"], "insufficient data")
        # Empty, not zero. Zero is a measurement.
        self.assertEqual(row["avg_heart_rate"], "")
        self.assertEqual(row["rows_usable"], "0")


class TestCommandLine(TempFileTestCase):
    """main.py, called the way the command line calls it."""

    def setUp(self):
        super().setUp()
        self.profiles = self.write_profiles()
        self.sessions = self.write_csv("sessions.csv", SESSION_HEADER,
                                       [session_row(t, 70) for t in range(6)])
        self.output = self.folder / "out"

    def run_main(self, arguments):
        """Call main() with stdout and stderr captured, so the test output
        stays readable and the messages can be asserted on.
        """
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main.main(arguments)
        return code, out.getvalue(), err.getvalue()

    def test_a_normal_run_exits_zero_and_writes_three_files(self):
        code, printed, errors = self.run_main(
            ["--profiles", str(self.profiles), "--sessions",
             str(self.sessions), "--output", str(self.output)])

        self.assertEqual(code, 0)
        self.assertEqual(errors, "")
        for expected in ("Sessions analysed", "Rows accepted",
                         "Rows rejected", "Files written"):
            self.assertIn(expected, printed)
        self.assertEqual(sorted(path.name for path in self.output.iterdir()),
                         ["analysis_report.txt", "analysis_summary.csv",
                          "rejected_records.txt"])

    def test_several_session_files_are_accepted(self):
        """nargs="+", so the brief's single file command also works."""
        second = self.write_csv("more.csv", SESSION_HEADER,
                                [session_row(t, 90, session="FIT-2026-002",
                                             participant="P002")
                                 for t in range(6)])
        code, _, _ = self.run_main(
            ["--profiles", str(self.profiles), "--sessions",
             str(self.sessions), str(second), "--output", str(self.output)])

        self.assertEqual(code, 0)
        with open(self.output / "analysis_summary.csv", encoding="utf-8",
                  newline="") as handle:
            self.assertEqual(len(list(csv.DictReader(handle))), 2)

    def test_a_missing_profiles_file_exits_one(self):
        code, _, errors = self.run_main(
            ["--profiles", str(self.folder / "nope.csv"), "--sessions",
             str(self.sessions), "--output", str(self.output)])

        self.assertEqual(code, 1)
        self.assertIn("Cannot use the profiles file", errors)

    def test_no_readable_session_file_exits_one_but_still_reports(self):
        code, _, errors = self.run_main(
            ["--profiles", str(self.profiles), "--sessions",
             str(self.folder / "nope.csv"), "--output", str(self.output)])

        self.assertEqual(code, 1)
        self.assertIn("No session could be read", errors)
        self.assertTrue((self.output / "rejected_records.txt").is_file())

    def test_the_defaults_are_the_official_files(self):
        arguments = main.parse_arguments([])

        self.assertEqual(arguments.profiles, "data/participants.csv")
        self.assertEqual(len(arguments.sessions), 2)
        self.assertEqual(arguments.output, "output")


class TestTheOfficialFiles(unittest.TestCase):
    """The only tests that read data/. Skipped if it is not there."""

    @classmethod
    def setUpClass(cls):
        cls.profiles = Path("data/participants.csv")
        cls.valid = Path("data/fitness_sessions.csv")
        cls.invalid = Path("data/fitness_sessions_invalid.csv")
        if not all(path.is_file() for path in (cls.profiles, cls.valid,
                                               cls.invalid)):
            raise unittest.SkipTest("run from the repository root to include "
                                    "the tests that read data/")

    def test_the_counts_are_what_the_notes_claim(self):
        participants, bad = read_participants(self.profiles)
        sessions, rejected = read_sessions([self.valid, self.invalid],
                                           participants)
        accepted = sum(session.usable_count for session in sessions.values())

        self.assertEqual(len(participants), 3)
        self.assertEqual(bad, [])
        self.assertEqual(len(sessions), 8)
        self.assertEqual(accepted, 25)
        self.assertEqual(len(rejected), 15)

    def test_every_classification_appears_in_the_official_data(self):
        participants, _ = read_participants(self.profiles)
        sessions, _ = read_sessions([self.valid, self.invalid], participants)
        labels = {sessions[key].analyse()["classification"]
                  for key in sessions}

        self.assertEqual(labels, {"resting", "moderate activity",
                                  "high activity", "recovering",
                                  "insufficient data"})


if __name__ == "__main__":
    unittest.main()
