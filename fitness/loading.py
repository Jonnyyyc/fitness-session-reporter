"""Reading the CSV files and validating the rows they contain.

The only module that opens an input file and the only one that decides whether
a row can be used. A row is checked in this order: session ID, participant ID,
is that participant known, does it match the rest of the session, then the
measurements themselves.
"""

import csv
import re
from pathlib import Path

from .errors import InvalidIdentifierError, InvalidRecordError
from .models import FIELD_UNITS, MEASUREMENT_FIELDS, Observation, Participant, Session

# Anchored with ^ and $ and used with fullmatch(), so the whole value has to
# match. Without that, 'XXP001YY' would be accepted.
PARTICIPANT_ID_PATTERN = re.compile(r"^P\d{3}$")
SESSION_ID_PATTERN = re.compile(r"^FIT-\d{4}-\d{3}$")

# The same rules in words, for error messages.
PARTICIPANT_ID_SHAPE = "P followed by three digits, like P001"
SESSION_ID_SHAPE = "FIT-YYYY-NNN, like FIT-2026-001"

# The numeric columns of participants.csv.
PROFILE_NUMBER_FIELDS = (
    "baseline_heart_rate",
    "baseline_skin_response",
    "baseline_temperature",
)

# The columns each file must have. Extra columns are ignored, so this catches
# the wrong file rather than policing the header. 'name' is optional, because
# build_participant() falls back to the ID.
PROFILE_COLUMNS = ("participant_id",) + PROFILE_NUMBER_FIELDS
SESSION_COLUMNS = ("session_id", "participant_id") + MEASUREMENT_FIELDS

# Whole numbers. Everything else numeric becomes a float, since a heart rate
# of 68.0 reads badly in a report.
INTEGER_FIELDS = ("timestamp", "heart_rate", "baseline_heart_rate")

# A value outside these is impossible rather than just poor, so the row is
# rejected. None as the upper bound means no ceiling.
VALUE_RANGES = {
    "timestamp": (0, None),
    "heart_rate": (20, 250),
    "skin_response": (0, 30),
    "temperature": (20, 45),
    "activity_level": (0.0, 1.0),
    "signal_quality": (0.0, 1.0),
}

# Below 0.50 the reading is rejected. Between 0.50 and 0.70 it is doubtful but
# still useful, so it is kept and marked.
SIGNAL_QUALITY_REJECT = 0.50
SIGNAL_QUALITY_FLAG = 0.70

# csv.DictReader puts extra columns in a list under this key. A row with too
# few columns shows up as a None value instead.
EXTRA_COLUMNS = "extra_columns"


class RejectedRow:
    """One row, or one whole file, that could not be used, and why.

    The file, row number, field and reason are kept apart so the report can use
    them separately.
    """

    def __init__(self, source_file, row_number, field, reason,
                 session_id="", kind="record", counted=False):
        self.source_file = source_file
        # None means the whole file failed rather than one row inside it.
        self.row_number = row_number
        self.field = field
        self.reason = reason
        self.session_id = session_id
        # "identifier" or "record". The rejection file groups by this.
        self.kind = kind
        # Whether the row reached a session and counts towards its totals.
        self.counted = counted

    def describe(self):
        """One readable line for rejected_records.txt."""
        if self.row_number is None:
            return f"{self.source_file}: {self.reason}"

        where = f"{self.source_file} row {self.row_number}"
        if self.session_id:
            where += f", session {self.session_id}"
            if not self.counted:
                where += " (not counted against it)"
        return f"{where}, field '{self.field}': {self.reason}"

    def __repr__(self):
        return f"RejectedRow({self.source_file!r}, row {self.row_number})"


def check_identifier(value, pattern, field, shape):
    """Check an identifier against its pattern.

    Raises InvalidIdentifierError when it does not match.
    """
    if not pattern.fullmatch(value):
        raise InvalidIdentifierError(
            f"'{value}' is not a valid {field}, expected {shape}", field=field)


def check_header(fieldnames, required):
    """Reject a file whose header is missing columns the program needs.

    One clear message about the file beats every row failing separately with a
    confusing reason.
    """
    # DictReader leaves fieldnames as None when the file is completely empty.
    present = set(fieldnames or ())
    missing = [column for column in required if column not in present]
    if missing:
        raise InvalidRecordError(
            f"header is missing the column{'' if len(missing) == 1 else 's'} "
            f"{', '.join(missing)}", field="header")


def check_row_length(row):
    """Reject a row with more columns than the header has."""
    extra = row.get(EXTRA_COLUMNS)
    if extra:
        count = len(extra)
        raise InvalidRecordError(
            f"row has {count} more column{'' if count == 1 else 's'} than the "
            f"header", field=EXTRA_COLUMNS)


def convert_value(field, text):
    """Turn one cell of text into a number.

    Raises InvalidRecordError when the cell is missing, blank, or not a number.
    """
    # DictReader leaves a missing column as None, which is how a row with too
    # few columns shows up.
    if text is None:
        raise InvalidRecordError(
            f"column '{field}' is missing from this row", field=field)

    text = text.strip()
    if not text:
        raise InvalidRecordError(f"column '{field}' is empty", field=field)

    wants_whole_number = field in INTEGER_FIELDS
    try:
        return int(text) if wants_whole_number else float(text)
    except ValueError as error:
        # This is the ValueError the brief asks to handle. It is caught here
        # rather than further out because this is the only place that knows
        # which column and which text caused it.
        expected = "whole number" if wants_whole_number else "number"
        raise InvalidRecordError(
            f"'{text}' is not a {expected}", field=field) from error


def convert_measurements(row):
    """Convert the six measurement columns of one session row."""
    return {field: convert_value(field, row.get(field))
            for field in MEASUREMENT_FIELDS}


def check_ranges(values):
    """Reject measurements that describe something that could not happen."""
    for field, (low, high) in VALUE_RANGES.items():
        value = values[field]
        if value < low or (high is not None and value > high):
            unit = f" {FIELD_UNITS[field]}".rstrip()
            if high is None:
                raise InvalidRecordError(
                    f"{value}{unit} is below the minimum {low}{unit}",
                    field=field)
            raise InvalidRecordError(
                f"{value}{unit} is outside the valid range {low} to "
                f"{high}{unit}", field=field)


def check_signal_quality(quality):
    """Apply the signal quality rule to a reading that is otherwise believable.

    Returns the warnings to attach to it, and raises when it is too noisy to
    use at all.
    """
    if quality < SIGNAL_QUALITY_REJECT:
        raise InvalidRecordError(
            f"signal quality {quality:.2f} is below the "
            f"{SIGNAL_QUALITY_REJECT:.2f} usable cutoff", field="signal_quality")

    if quality < SIGNAL_QUALITY_FLAG:
        return [f"weak signal ({quality:.2f})"]
    return []


def look_up_participant(participant_id, participants):
    """Find the participant a session row names."""
    try:
        return participants[participant_id]
    except KeyError as error:
        # The KeyError the brief asks to handle. Turned into a rejection
        # because an unknown participant is bad data, not a broken program.
        raise InvalidRecordError(
            f"participant {participant_id} is not in the profiles file",
            field="participant_id") from error


def read_participants(path):
    """Read the profiles file into {participant_id: Participant}.

    Returns (participants, rejected). A bad row is skipped and reported. A file
    that cannot be read raises, and main.py stops.
    """
    participants = {}
    rejected = []
    source_file = Path(path).name

    with open(path, encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, restkey=EXTRA_COLUMNS)
        check_header(reader.fieldnames, PROFILE_COLUMNS)
        # Row 1 is the header, so the first row of data is row 2. Counting the
        # file's own lines means a reported row number can be found by opening
        # the file and going to that line.
        for row_number, row in enumerate(reader, start=2):
            try:
                participant = build_participant(row)
            except InvalidIdentifierError as error:
                rejected.append(RejectedRow(source_file, row_number, error.field,
                                            str(error), kind="identifier"))
                continue
            except InvalidRecordError as error:
                rejected.append(RejectedRow(source_file, row_number, error.field,
                                            str(error), kind="record"))
                continue

            participants[participant.participant_id] = participant

    return participants, rejected


def build_participant(row):
    """Turn one row of the profiles file into a Participant."""
    participant_id = (row.get("participant_id") or "").strip()
    check_identifier(participant_id, PARTICIPANT_ID_PATTERN,
                     "participant_id", PARTICIPANT_ID_SHAPE)
    check_row_length(row)

    profile = {
        "participant_id": participant_id,
        "name": (row.get("name") or "").strip(),
    }
    for field in PROFILE_NUMBER_FIELDS:
        profile[field] = convert_value(field, row.get(field))

    try:
        return Participant.from_profile(profile)
    except ValueError as error:
        # Raised by the resting heart rate property when a baseline is outside
        # the range a person can have. Caught here so one impossible profile
        # becomes a reported row rather than stopping the program.
        raise InvalidRecordError(str(error), field="baseline_heart_rate") from error


def read_sessions(paths, participants):
    """Read every session file into {session_id: Session}.

    Returns (sessions, rejected). A file that cannot be read is reported and
    skipped, and the remaining files are still read.
    """
    sessions = {}
    rejected = []
    for path in paths:
        read_session_file(Path(path), participants, sessions, rejected)
    return sessions, rejected


def read_session_file(path, participants, sessions, rejected):
    """Read one session file, adding to the sessions and rejections given."""
    source_file = path.name
    try:
        with open(path, encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, restkey=EXTRA_COLUMNS)
            check_header(reader.fieldnames, SESSION_COLUMNS)
            for row_number, row in enumerate(reader, start=2):
                read_session_row(row, row_number, source_file,
                                 participants, sessions, rejected)
    except InvalidRecordError as error:
        # Only check_header() can reach here. Every row level problem is
        # caught inside read_session_row(), which never lets one escape.
        rejected.append(RejectedRow(source_file, None, error.field,
                                    f"{error}, file skipped", kind="file"))
    except FileNotFoundError:
        rejected.append(RejectedRow(source_file, None, "",
                                    "file not found, skipped", kind="file"))
    except PermissionError as error:
        rejected.append(RejectedRow(source_file, None, "",
                                    f"cannot be opened ({error.strerror}), "
                                    f"skipped", kind="file"))
    except csv.Error as error:
        # csv raises this while reading rather than while opening, for example
        # on a line containing a null byte. The rows read before it are kept,
        # since they were fine.
        rejected.append(RejectedRow(source_file, None, "",
                                    f"stopped reading after a CSV error: "
                                    f"{error}", kind="file"))


def read_session_row(row, row_number, source_file, participants, sessions,
                     rejected):
    """Validate one session row and add it to its session, or reject it."""
    source = f"{source_file} row {row_number}"
    session_id = (row.get("session_id") or "").strip()

    # Step 1. Without a readable session ID the row cannot be placed at all,
    # so the rejection cannot even name a session.
    try:
        check_identifier(session_id, SESSION_ID_PATTERN,
                         "session_id", SESSION_ID_SHAPE)
    except InvalidIdentifierError as error:
        rejected.append(RejectedRow(source_file, row_number, error.field,
                                    str(error), kind="identifier"))
        return

    # Steps 2 and 3. The session ID is readable, so the rejection can name the
    # session, but the row still does not count towards it without a
    # participant.
    try:
        participant_id = (row.get("participant_id") or "").strip()
        check_identifier(participant_id, PARTICIPANT_ID_PATTERN,
                         "participant_id", PARTICIPANT_ID_SHAPE)
        participant = look_up_participant(participant_id, participants)
    except InvalidIdentifierError as error:
        rejected.append(RejectedRow(source_file, row_number, error.field,
                                    str(error), session_id=session_id,
                                    kind="identifier"))
        return
    except InvalidRecordError as error:
        rejected.append(RejectedRow(source_file, row_number, error.field,
                                    str(error), session_id=session_id,
                                    kind="record"))
        return

    # Step 4. The first row to reach this point creates the session, which is
    # why a session always has a participant.
    if session_id not in sessions:
        sessions[session_id] = Session(session_id, participant)
    session = sessions[session_id]

    # Steps 4b and 5. The row belongs to this session now, so a failure is
    # counted against the session as well as reported.
    try:
        established = session.participant.participant_id
        if participant_id != established:
            raise InvalidRecordError(
                f"names participant {participant_id}, but session "
                f"{session_id} was established with {established}; one "
                f"session cannot mix two people's reference values",
                field="participant_id")

        check_row_length(row)
        values = convert_measurements(row)
        check_ranges(values)
        flags = check_signal_quality(values["signal_quality"])
    except InvalidRecordError as error:
        session.record_rejection(str(error), source)
        rejected.append(RejectedRow(source_file, row_number, error.field,
                                    str(error), session_id=session_id,
                                    kind="record", counted=True))
        return

    session.add_observation(Observation(**values, flags=flags), source)
