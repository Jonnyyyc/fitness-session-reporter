"""Command line entry point for the fitness session analyzer.

Run from the repository root:

    python main.py --profiles data/participants.csv \
        --sessions data/fitness_sessions.csv data/fitness_sessions_invalid.csv \
        --output output

The argument parsing is added in a later step. For now this file only
confirms that the package imports correctly.
"""

import fitness


def main():
    print("Fitness session analyzer, not implemented yet.")
    print(f"Package imported from: {fitness.__file__}")


# This guard means the code below only runs when the file is started
# directly. If another file imports main.py, nothing happens.
if __name__ == "__main__":
    main()
