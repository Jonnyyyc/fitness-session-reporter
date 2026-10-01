"""Smart Fitness Session Analyzer, file based version.

The package is split so that each module has one job:

    errors     the exception types the rest of the package raises
    models     the classes that hold a participant, a reading and a session
    analysis   the calculations and the classification rules
    loading    reading the CSV files and deciding which rows are usable
    reporting  writing the result files into the output folder
"""
