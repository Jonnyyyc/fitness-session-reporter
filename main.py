"""Smart Fitness Session Analyzer: command line entry point.

Run from the repository root. With no arguments it reads the official files:

    python3 main.py          (macOS / Linux)
    python main.py           (Windows)

Paths can be given with --profiles, --sessions and --output. This file holds no
analysis; it reads the arguments, calls the package and prints what happened.

Author: Jonathan Christensen
"""

import argparse
import sys

from fitness.errors import InvalidRecordError
from fitness.loading import read_participants, read_sessions
from fitness.reporting import write_reports

# Defaults, so `python main.py` alone works. Relative to where the program is
# started, which is the repository root.
DEFAULT_PROFILES = "data/participants.csv"
DEFAULT_SESSIONS = ["data/fitness_sessions.csv",
                    "data/fitness_sessions_invalid.csv"]
DEFAULT_OUTPUT = "output"


def parse_arguments(argv=None):
    """Read the command line. argv is for tests; None means the real one."""
    parser = argparse.ArgumentParser(
        description="Analyse simulated wearable fitness sessions from CSV "
                    "files and write the results to an output folder.")
    parser.add_argument("--profiles", default=DEFAULT_PROFILES,
                        help=f"participant profile file "
                             f"(default: {DEFAULT_PROFILES})")
    # nargs="+" takes one path or several, so both session files can be given
    # at once.
    parser.add_argument("--sessions", nargs="+", default=DEFAULT_SESSIONS,
                        help="one or more session files (default: both "
                             "official files)")
    parser.add_argument("--output", default=DEFAULT_OUTPUT,
                        help=f"folder for the report files "
                             f"(default: {DEFAULT_OUTPUT})")
    return parser.parse_args(argv)


def print_summary(results, rejected, written):
    """Print the completion summary the brief asks for in section 7."""
    accepted = sum(result["observations"]["usable"] for result in results)
    print("Done.")
    print(f"  Sessions analysed  {len(results):>4}")
    print(f"  Rows accepted      {accepted:>4}")
    print(f"  Rows rejected      {len(rejected):>4}")
    print("  Files written:")
    for path in written:
        print(f"    {path}")


def main(argv=None):
    """Run the whole program. Returns the exit code."""
    arguments = parse_arguments(argv)

    # Without the profiles file every row would be rejected and the reports
    # would be empty, so stopping says more than writing them.
    try:
        participants, rejected = read_participants(arguments.profiles)
    except (FileNotFoundError, PermissionError, InvalidRecordError) as error:
        print(f"Cannot use the profiles file {arguments.profiles}: {error}",
              file=sys.stderr)
        return 1

    # read_sessions reports a file it cannot read and carries on, so there is
    # nothing to catch here.
    sessions, session_rejections = read_sessions(arguments.sessions,
                                                 participants)
    rejected.extend(session_rejections)

    # Sorted, so two runs over the same data produce the same file.
    results = [sessions[session_id].analyse()
               for session_id in sorted(sessions)]

    written = write_reports(results, rejected, arguments.output)
    print_summary(results, rejected, written)

    if not sessions:
        print("No session could be read. See the rejection file for why.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    # sys.exit sets the shell's exit code, so a failed run can be noticed.
    sys.exit(main())
