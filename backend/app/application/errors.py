"""Errors safe for transport adapters to present to clients."""


class ApplicationError(ValueError):
    """A user-facing use-case or validation failure."""


class RepositoryError(ApplicationError):
    """A persistence failure translated into a stable application error."""
