"""Exception types used across the package.

Both inherit from ValueError and carry the field that caused the problem. Where
they are handled differently, InvalidIdentifierError must be the first except
clause, since Python takes the first one that matches.
"""


class InvalidIdentifierError(ValueError):
    """Raised when a participant ID or session ID has the wrong format."""

    def __init__(self, message, field=None):
        super().__init__(message)
        # Which column was wrong, for the rejection file.
        self.field = field


class InvalidRecordError(ValueError):
    """Raised when a record cannot be accepted for any other reason."""

    # Repeated rather than using a shared base class, which would add a third
    # class with no behaviour of its own.
    def __init__(self, message, field=None):
        super().__init__(message)
        self.field = field
