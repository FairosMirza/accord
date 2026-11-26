class DomainError(Exception):
    """A business-rule violation that should be shown to the user."""

    status_code = 400

    def __init__(self, message: str, code: str = "invalid"):
        super().__init__(message)
        self.message = message
        self.code = code


class NotAllowed(DomainError):
    status_code = 403

    def __init__(self, message: str = "You don't have permission to do that.", code: str = "forbidden"):
        super().__init__(message, code)


class NotFound(DomainError):
    status_code = 404

    def __init__(self, message: str = "Not found.", code: str = "not_found"):
        super().__init__(message, code)


class Conflict(DomainError):
    status_code = 409

    def __init__(self, message: str, code: str = "conflict"):
        super().__init__(message, code)
