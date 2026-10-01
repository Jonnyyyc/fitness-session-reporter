"""Summary calculations and the rules that classify a session.

Nothing here reads a file or prints. Per-person thresholds are read from the
participant passed in, so two people with the same readings can get different
answers.
"""

import statistics

# timestamp orders the session and signal_quality describes the sensor, so
# averaging either would mean nothing.
SUMMARY_FIELDS = (
    "heart_rate",
    "skin_response",
    "temperature",
    "activity_level",
)

# How far temperature must differ from normal before the report says so.
# Wording only; no classification reads this.
TEMPERATURE_TOLERANCE = 0.5

# Below this many usable readings, no verdict is given. A third of four
# readings is one reading, which is too little to call a trend.
MINIMUM_USABLE_OBSERVATIONS = 5

# Activity level is already a 0 to 1 scale that means the same for everyone, so
# unlike heart rate it needs no per-person reference.
MODERATE_ACTIVITY_LEVEL = 0.20
HIGH_ACTIVITY_LEVEL = 0.60


def summarise(observations):
    """Average, minimum and maximum for each measured field.

    Returns {field: {"avg", "min", "max"}}, or {} for an empty list.
    """
    # {} rather than raising, so an empty session follows the normal path and
    # gets labelled further down.
    if not observations:
        return {}

    summary = {}
    for field in SUMMARY_FIELDS:
        values = [getattr(observation, field) for observation in observations]
        summary[field] = {
            "avg": statistics.mean(values),
            "min": min(values),
            "max": max(values),
        }
    return summary


def heart_rate_zone(average_heart_rate, bands):
    """Which of the participant's bands an average heart rate falls into.

    The bands are passed in, so this function holds no thresholds of its own.
    """
    if average_heart_rate >= bands["high"]:
        return "high"
    if average_heart_rate >= bands["elevated"]:
        return "elevated"
    return "below elevated"


def compare_to_reference(summary, participant):
    """Measure the session against the participant's own reference values.

    Every threshold is read from the participant. Returns {} for an empty
    summary.
    """
    if not summary:
        return {}

    bands = participant.heart_rate_bands()
    average_heart_rate = summary["heart_rate"]["avg"]

    average_temperature = summary["temperature"]["avg"]
    temperature_difference = average_temperature - participant.normal_temperature
    if abs(temperature_difference) < TEMPERATURE_TOLERANCE:
        direction = "normal"
    elif temperature_difference > 0:
        direction = "above normal"
    else:
        direction = "below normal"

    comparison = {
        "heart_rate": {
            "average": average_heart_rate,
            "zone": heart_rate_zone(average_heart_rate, bands),
            "elevated_band": bands["elevated"],
            "high_band": bands["high"],
            "above_resting": average_heart_rate - participant.resting_heart_rate,
        },
        "temperature": {
            "average": average_temperature,
            "reference": participant.normal_temperature,
            "difference": temperature_difference,
            "direction": direction,
        },
    }

    # Always true in a real run, since the CSV supplies one for everyone. The
    # check is for participants built by hand in tests.
    if participant.normal_skin_response is not None:
        average_skin_response = summary["skin_response"]["avg"]
        comparison["skin_response"] = {
            "average": average_skin_response,
            "reference": participant.normal_skin_response,
            "difference": average_skin_response - participant.normal_skin_response,
        }

    return comparison


def split_into_thirds(observations):
    """Split time-ordered observations into three consecutive parts."""
    # Uneven counts put the remainder in the later parts, so the final third,
    # which recovery is judged on, is never the smallest.
    count = len(observations)
    first_boundary = count // 3
    second_boundary = 2 * count // 3
    return (
        observations[:first_boundary],
        observations[first_boundary:second_boundary],
        observations[second_boundary:],
    )


def detect_recovery(observations, participant):
    """Did heart rate and activity both fall towards the end of the session?

    Returns a dict where 'detected' is the verdict and the rest is the evidence
    behind it, so the report can explain itself either way.
    """
    # From the participant, so an Athlete is judged by a stricter number.
    thresholds = participant.recovery_thresholds()
    bands = participant.heart_rate_bands()

    not_detected = {
        "detected": False,
        "heart_rate_drop": 0.0,
        "activity_drop": 0.0,
        "required": thresholds,
    }

    # Three non-empty parts need at least three readings.
    if len(observations) < 3:
        return {**not_detected,
                "reason": "too few observations to compare start and end"}

    # Against the peak third, not the first, because a session that starts
    # calm and works hard has its peak in the middle.
    thirds = split_into_thirds(observations)
    heart_rates = [statistics.mean([obs.heart_rate for obs in part])
                   for part in thirds]
    activities = [statistics.mean([obs.activity_level for obs in part])
                  for part in thirds]

    peak_index = heart_rates.index(max(heart_rates))
    peak_heart_rate = heart_rates[peak_index]
    peak_activity = activities[peak_index]
    final_heart_rate = heart_rates[-1]
    final_activity = activities[-1]

    heart_rate_drop = (peak_heart_rate - final_heart_rate) / peak_heart_rate
    # Activity can be 0.0 at the peak for someone at rest throughout, so the
    # drop is zero rather than a division by zero.
    if peak_activity > 0:
        activity_drop = (peak_activity - final_activity) / peak_activity
    else:
        activity_drop = 0.0

    peak_reached_elevated = peak_heart_rate >= bands["elevated"]

    evidence = {
        "heart_rate_drop": heart_rate_drop,
        "activity_drop": activity_drop,
        "peak_heart_rate": peak_heart_rate,
        "final_heart_rate": final_heart_rate,
        "peak_activity": peak_activity,
        "final_activity": final_activity,
        "peak_reached_elevated": peak_reached_elevated,
        "elevated_band": bands["elevated"],
        "required": thresholds,
    }

    # All three must hold, or someone sitting still whose heart rate drifts
    # down would count as recovering.
    detected = (
        heart_rate_drop >= thresholds["heart_rate_drop"]
        and activity_drop >= thresholds["activity_drop"]
        and peak_reached_elevated
    )

    if detected:
        return {**evidence, "detected": True, "reason": None}

    if not peak_reached_elevated:
        reason = (f"peak third averaged {peak_heart_rate:.1f} bpm, which never "
                  f"reached the elevated band ({bands['elevated']:.1f} bpm), "
                  f"so there was nothing to recover from")
    elif heart_rate_drop < thresholds["heart_rate_drop"]:
        reason = (f"heart rate fell {heart_rate_drop:.0%}, short of the "
                  f"{thresholds['heart_rate_drop']:.0%} required")
    else:
        reason = (f"activity fell {activity_drop:.0%}, short of the "
                  f"{thresholds['activity_drop']:.0%} required")

    return {**evidence, "detected": False, "reason": reason}


def classify_session(summary, participant, usable_count, recovery):
    """Label the session and explain the label in the same breath.

    Checks run in this order: insufficient data, recovering, high, moderate,
    resting.
    """
    # First, because everything below is calculated from readings that may not
    # exist. Too little data is not the same answer as a normal result.
    if usable_count < MINIMUM_USABLE_OBSERVATIONS:
        return ("insufficient data",
                f"Only {usable_count} usable observation"
                f"{'' if usable_count == 1 else 's'}; at least "
                f"{MINIMUM_USABLE_OBSERVATIONS} are needed before a session "
                f"can be classified.")

    bands = participant.heart_rate_bands()
    average_heart_rate = summary["heart_rate"]["avg"]
    average_activity = summary["activity_level"]["avg"]
    zone = heart_rate_zone(average_heart_rate, bands)

    # Before high activity, because a hard session ending in a cooldown meets
    # both tests and 'recovering' says more.
    if recovery["detected"]:
        explanation = (
            f"Recovering: between the session's peak third and its final "
            f"third, heart rate fell {recovery['heart_rate_drop']:.0%} "
            f"({recovery['peak_heart_rate']:.1f} to "
            f"{recovery['final_heart_rate']:.1f} bpm) and activity fell "
            f"{recovery['activity_drop']:.0%} "
            f"({recovery['peak_activity']:.2f} to "
            f"{recovery['final_activity']:.2f}), meeting the "
            f"{recovery['required']['heart_rate_drop']:.0%} and "
            f"{recovery['required']['activity_drop']:.0%} required. The peak "
            f"third averaged {recovery['peak_heart_rate']:.1f} bpm, at or "
            f"above the elevated band ({recovery['elevated_band']:.1f} bpm), "
            f"so there was real effort to recover from."
        )
        # Say when the intensity tests also passed, so the effort is not
        # left looking unnoticed.
        if zone == "high" or average_activity >= HIGH_ACTIVITY_LEVEL:
            explanation += (" The session also met the high-activity test; "
                            "'recovering' is reported because it is the more "
                            "specific finding.")
        elif zone == "elevated" or average_activity >= MODERATE_ACTIVITY_LEVEL:
            explanation += (" The session also met the moderate-activity test; "
                            "'recovering' is reported because it is the more "
                            "specific finding.")
        return "recovering", explanation

    if zone == "high" or average_activity >= HIGH_ACTIVITY_LEVEL:
        reasons = []
        if zone == "high":
            reasons.append(f"average heart rate {average_heart_rate:.1f} bpm "
                           f"reached the high band ({bands['high']:.1f} bpm)")
        if average_activity >= HIGH_ACTIVITY_LEVEL:
            reasons.append(f"average activity {average_activity:.2f} reached "
                           f"{HIGH_ACTIVITY_LEVEL:.2f}")
        return "high activity", "High activity: " + " and ".join(reasons) + "."

    if zone == "elevated" or average_activity >= MODERATE_ACTIVITY_LEVEL:
        reasons = []
        if zone == "elevated":
            reasons.append(f"average heart rate {average_heart_rate:.1f} bpm "
                           f"reached the elevated band "
                           f"({bands['elevated']:.1f} bpm)")
        if average_activity >= MODERATE_ACTIVITY_LEVEL:
            reasons.append(f"average activity {average_activity:.2f} reached "
                           f"{MODERATE_ACTIVITY_LEVEL:.2f}")
        return ("moderate activity",
                "Moderate activity: " + " and ".join(reasons) + ".")

    return ("resting",
            f"Resting: average heart rate {average_heart_rate:.1f} bpm stayed "
            f"below the elevated band ({bands['elevated']:.1f} bpm) and "
            f"average activity {average_activity:.2f} stayed below "
            f"{MODERATE_ACTIVITY_LEVEL:.2f}.")
