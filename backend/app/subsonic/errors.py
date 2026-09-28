from enum import IntEnum


class ErrorCode(IntEnum):
    GENERIC = 0
    MISSING_PARAMETER = 10
    CLIENT_TOO_OLD = 20
    SERVER_TOO_OLD = 30
    WRONG_CREDENTIALS = 40
    TOKEN_AUTH_NOT_SUPPORTED = 41
    AUTH_MECHANISM_NOT_SUPPORTED = 42  # OpenSubsonic
    MULTIPLE_AUTH_MECHANISMS = 43  # OpenSubsonic
    INVALID_API_KEY = 44  # OpenSubsonic
    NOT_AUTHORIZED = 50
    TRIAL_EXPIRED = 60
    NOT_FOUND = 70


class SubsonicError(Exception):
    """Returned to the client as HTTP 200 with status="failed"."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    @classmethod
    def missing(cls, param: str) -> "SubsonicError":
        return cls(ErrorCode.MISSING_PARAMETER, f"Required parameter is missing: {param}")

    @classmethod
    def not_found(cls, what: str) -> "SubsonicError":
        return cls(ErrorCode.NOT_FOUND, f"{what} not found")

    @classmethod
    def not_authorized(cls, message: str = "Not authorized for this operation") -> "SubsonicError":
        return cls(ErrorCode.NOT_AUTHORIZED, message)
