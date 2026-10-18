"""The errors CARA raises for its callers; the API turns each into an HTTP status (see `cara.api.main`)."""


class NotFound(LookupError):
    """Something asked for doesn't exist: a study, a query, a user, an image (HTTP 404)."""


class Forbidden(PermissionError):
    """The person may not do this: not a member, not an annotator, not a superuser (HTTP 403)."""


class Conflict(ValueError):
    """The request clashes with the current state, such as changing pools after judging started (HTTP 409)."""


class Invalid(ValueError):
    """The request itself is wrong, such as too many queries or a malformed qrels line (HTTP 422)."""
