"""Classes for a participant, a single reading and a whole session.

Composition is Session holding a Participant and a list of Observations.
Encapsulation is the two heart rates behind properties. Inheritance is Athlete.

Nothing here reads a file or validates a row; loading.py does that first.
"""

from .analysis import (classify_session, compare_to_reference, detect_recovery,
                       summarise)

# Every reading has these six fields. The CSV uses the same column names, so
# no translation is needed.
MEASUREMENT_FIELDS = (
    "timestamp",
    "heart_rate",
    "skin_response",
    "temperature",
    "activity_level",
    "signal_quality",
)

# Units, used by the report and by rejection messages.
FIELD_UNITS = {
    "timestamp": "s",
    "heart_rate": "bpm",
    "skin_response": "uS",
    "temperature": "C",
    "activity_level": "",
    "signal_quality": "",
}

# participants.csv has no maximum heart rate and no age to estimate one from,
# so everyone gets the same assumed maximum. 190 is roughly what 220 minus age
# gives at thirty. Both heart rate bands depend on it.
DEFAULT_MAX_HEART_RATE = 190


def require_number(label, value):
    """Raise ValueError unless value is a real number."""
    # True is technically the number 1 in Python, so without the bool check a
    # heart rate of True would be read as 1 bpm.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number, got {type(value).__name__}")
    return value


class Participant:
    """A person and the reference measurements their session is judged against.

    The resting and maximum heart rates are private, behind properties, because
    the two have to stay consistent with each other.
    """

    # What a profile must supply. 'name' is optional, reference values are not.
    PROFILE_FIELDS = ("participant_id", "baseline_heart_rate",
                      "baseline_temperature", "baseline_skin_response")

    def __init__(self, participant_id, name, resting_heart_rate,
                 max_heart_rate=DEFAULT_MAX_HEART_RATE,
                 normal_temperature=33.0, normal_skin_response=None):
        self.participant_id = participant_id
        self.name = name
        self.normal_temperature = normal_temperature
        self.normal_skin_response = normal_skin_response
        # Set before the resting rate, so the resting setter can tell there is
        # no maximum to cross-check against yet.
        self._max_heart_rate = None
        # Assigning without the underscore runs the setters, so the checks
        # apply when the object is built, not only when a value is changed.
        self.resting_heart_rate = resting_heart_rate
        self.max_heart_rate = max_heart_rate

    @classmethod
    def from_profile(cls, profile):
        """Build a participant from one converted row of participants.csv.

        The values must already be numbers; loading.py converts them.
        """
        # Built with cls() rather than Participant(), so
        # Athlete.from_profile() returns an Athlete.
        missing = [field for field in cls.PROFILE_FIELDS if field not in profile]
        if missing:
            raise ValueError("profile is missing " + ", ".join(missing))

        return cls(
            participant_id=profile["participant_id"],
            # Falls back to the ID so the report always has something to print.
            name=profile.get("name") or profile["participant_id"],
            resting_heart_rate=profile["baseline_heart_rate"],
            normal_temperature=profile["baseline_temperature"],
            normal_skin_response=profile["baseline_skin_response"],
        )

    @property
    def resting_heart_rate(self):
        return self._resting_heart_rate

    @resting_heart_rate.setter
    def resting_heart_rate(self, value):
        require_number("resting heart rate", value)
        if not 20 <= value <= 120:
            raise ValueError(f"resting heart rate {value} is outside 20 to 120 bpm")
        if self._max_heart_rate is not None and value >= self._max_heart_rate:
            raise ValueError(
                f"resting heart rate {value} is not below the maximum "
                f"{self._max_heart_rate}"
            )
        self._resting_heart_rate = value

    @property
    def max_heart_rate(self):
        return self._max_heart_rate

    @max_heart_rate.setter
    def max_heart_rate(self, value):
        require_number("maximum heart rate", value)
        if not 100 <= value <= 230:
            raise ValueError(f"maximum heart rate {value} is outside 100 to 230 bpm")
        if value <= self._resting_heart_rate:
            raise ValueError(
                f"maximum heart rate {value} is not above the resting rate "
                f"{self._resting_heart_rate}"
            )
        self._max_heart_rate = value

    def heart_rate_bands(self):
        """The bpm at which this person counts as elevated or high.

        Uses heart rate reserve, the span between resting and maximum, so that
        a low resting rate does not by itself make a session look easy.
        """
        reserve = self.max_heart_rate - self.resting_heart_rate
        return {
            "elevated": self.resting_heart_rate + 0.20 * reserve,
            "high": self.resting_heart_rate + 0.50 * reserve,
        }

    def recovery_thresholds(self):
        """How far heart rate and activity must fall to count as recovery.

        Fractions of the session's peak third, not absolute values.
        """
        # detect_recovery() reads this rather than holding the numbers itself,
        # which is what lets a subclass change the rule by overriding here.
        return {"heart_rate_drop": 0.10, "activity_drop": 0.30}

    def describe(self):
        return (f"{self.name} ({self.participant_id}, resting HR "
                f"{self.resting_heart_rate} bpm, max {self.max_heart_rate} bpm)")


class Athlete(Participant):
    """A trained participant, whose heart rate falls faster after effort.

    Only the recovery rule differs. The reserve formula already handles the
    bands, so those do not need overriding.
    """

    def recovery_thresholds(self):
        thresholds = super().recovery_thresholds()
        thresholds["heart_rate_drop"] = 0.15
        return thresholds

    def describe(self):
        return (f"{self.name} ({self.participant_id}, trained, resting HR "
                f"{self.resting_heart_rate} bpm, max {self.max_heart_rate} bpm)")


class Observation:
    """A single sensor reading taken at one moment in a session."""

    def __init__(self, timestamp, heart_rate, skin_response,
                 temperature, activity_level, signal_quality, flags=None):
        self.timestamp = timestamp
        self.heart_rate = heart_rate
        self.skin_response = skin_response
        self.temperature = temperature
        self.activity_level = activity_level
        self.signal_quality = signal_quality
        # Warnings about a reading that was kept in spite of being imperfect.
        # An empty list, not None, so callers can loop over it without asking.
        self.flags = list(flags) if flags else []

    def __repr__(self):
        return (f"Observation(t={self.timestamp}, hr={self.heart_rate}, "
                f"activity={self.activity_level})")


class Session:
    """One recording: a participant, and the readings taken from them.

    A Session is only built once a row names a participant who exists, so
    self.participant is never None.
    """

    def __init__(self, session_id, participant):
        self.session_id = session_id
        self.participant = participant
        self.observations = []
        # Two lists rather than one, so the report can group them. Each note
        # names the file and row it came from.
        self.flag_notes = []
        self.rejection_notes = []

    def add_observation(self, observation, source):
        """Add a reading that loading.py has already checked.

        'source' is where the row came from, like "fitness_sessions.csv row 7".
        """
        self.observations.append(observation)
        for flag in observation.flags:
            self.flag_notes.append(f"{source}: {flag}")

    def record_rejection(self, reason, source):
        """Note a row that belonged to this session but could not be used."""
        self.rejection_notes.append(f"{source}: {reason}")

    def ordered_observations(self):
        """Accepted readings in time order."""
        return sorted(self.observations, key=lambda obs: obs.timestamp)

    @property
    def usable_count(self):
        return len(self.observations)

    @property
    def flagged_count(self):
        """Usable readings carrying a warning. A subset of usable, not an extra."""
        return sum(1 for obs in self.observations if obs.flags)

    @property
    def rejected_count(self):
        return len(self.rejection_notes)

    @property
    def total_count(self):
        """Rows that belonged to this session, whether they survived or not."""
        return self.usable_count + self.rejected_count

    def analyse(self):
        """Run the analysis and return the result as a dictionary.

        Both output files are written from this, so neither calculates
        anything itself.
        """
        observations = self.ordered_observations()
        summary = summarise(observations)
        comparison = compare_to_reference(summary, self.participant)
        recovery = detect_recovery(observations, self.participant)
        classification, explanation = classify_session(
            summary, self.participant, self.usable_count, recovery
        )

        return {
            "session_id": self.session_id,
            "participant_id": self.participant.participant_id,
            "participant_name": self.participant.name,
            "participant": self.participant.describe(),
            "classification": classification,
            "explanation": explanation,
            "observations": {
                "total": self.total_count,
                "usable": self.usable_count,
                "flagged": self.flagged_count,
                "rejected": self.rejected_count,
            },
            "summary": summary,
            "comparison": comparison,
            "recovery": recovery,
            # Copies, so the caller cannot change the session's own record.
            "flag_notes": list(self.flag_notes),
            "rejection_notes": list(self.rejection_notes),
        }

    def __repr__(self):
        return (f"Session({self.session_id!r}, {self.usable_count} usable "
                f"of {self.total_count})")
