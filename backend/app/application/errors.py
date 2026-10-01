"""Errors safe for transport adapters to present to clients."""


class ApplicationError(ValueError):
    """A user-facing use-case or validation failure."""


class RepositoryError(ApplicationError):
    """A persistence failure translated into a stable application error."""


class RevisionConflictError(ApplicationError):
    """The document changed after the caller read it."""


class StorageNotInstalledError(RepositoryError):
    """A specific optional store is missing from the database schema."""

    def __init__(self, feature: str):
        self.feature = feature
        super().__init__(
            f"{feature.capitalize()} storage is not installed. "
            "Apply the checked-in Supabase migrations before using this feature."
        )
