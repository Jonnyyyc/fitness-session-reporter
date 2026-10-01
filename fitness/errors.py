"""Exception types used across the package.

Both inherit from ValueError, which is what the assignment brief suggests, and
both carry the name of the field that caused the problem so the rejection file
can report it.

The shared inheritance matters when catching them. A single `except ValueError`
would catch both and lose the difference, and Python takes the first matching
`except` clause, so InvalidIdentifierError must be listed before
InvalidRecordError wherever the two are handled differently.
"""


class InvalidIdentifierError(ValueError):
    """Raised when a participant ID or session ID has the wrong format."""

    def __init__(self, message, field=None):
        super().__init__(message)
        # Which column was wrong. The rejection file has a column for this,
        # and the message alone would mean parsing the text back apart.
        self.field = field


class InvalidRecordError(ValueError):
    """Raised when a record cannot be accepted for any other reason."""

    # The same two lines as above rather than a shared base class. Two small
    # independent exceptions are easier to read than three classes where one
    # exists only to be inherited from.
    def __init__(self, message, field=None):
        super().__init__(message)
        self.field = field
