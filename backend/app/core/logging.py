import logging
import re

# Subsonic credentials travel in query strings (stream and cover URLs cannot use headers).
_SECRET_PARAMS = re.compile(r"(?i)([?&](?:p|t|s|apiKey)=)[^&\s]*")


def redact_query(path: str) -> str:
    """Hides credential parameters in a request path: `?u=bob&t=abc` -> `?u=bob&t=***`."""
    return _SECRET_PARAMS.sub(r"\1***", path)


class RedactCredentialsFilter(logging.Filter):
    """Redacts credentials from uvicorn access log lines."""

    def filter(self, record: logging.LogRecord) -> bool:
        # uvicorn.access args: (client, method, path, http_version, status)
        if isinstance(record.args, tuple) and len(record.args) >= 3:
            args = list(record.args)
            if isinstance(args[2], str):
                args[2] = redact_query(args[2])
                record.args = tuple(args)
        return True


def configure_logging(level: str) -> None:
    logging.basicConfig(level=level.upper())
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, RedactCredentialsFilter) for f in access.filters):
        access.addFilter(RedactCredentialsFilter())
    # httpx logs every request URL at INFO, API keys included (Last.fm takes its key in
    # the query string): only its warnings.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
