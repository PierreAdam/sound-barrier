from starlette.requests import Request

from app.subsonic.errors import ErrorCode, SubsonicError

_FORM_CONTENT_TYPES = ("application/x-www-form-urlencoded", "multipart/form-data")


class SubsonicParams:
    """Request parameters, merged from the query string and a form-encoded POST body.

    Subsonic parameters can be repeated (e.g. `id` in `star`), so values are kept as a list.
    """

    def __init__(self, items: list[tuple[str, str]]) -> None:
        self._values: dict[str, list[str]] = {}
        for key, value in items:
            self._values.setdefault(key, []).append(value)

    @classmethod
    async def from_request(cls, request: Request) -> "SubsonicParams":
        items = list(request.query_params.multi_items())
        content_type = request.headers.get("content-type", "")
        if request.method == "POST" and content_type.startswith(_FORM_CONTENT_TYPES):
            form = await request.form()
            items.extend((k, v) for k, v in form.multi_items() if isinstance(v, str))
        return cls(items)

    def __contains__(self, name: str) -> bool:
        return name in self._values

    def get(self, name: str) -> str | None:
        values = self._values.get(name)
        return values[0] if values else None

    def get_all(self, name: str) -> list[str]:
        return list(self._values.get(name, []))

    def require(self, name: str) -> str:
        value = self.get(name)
        if value is None or value == "":
            raise SubsonicError.missing(name)
        return value

    def get_int(self, name: str, default: int | None = None) -> int | None:
        value = self.get(name)
        if value is None or value == "":
            return default
        try:
            return int(value)
        except ValueError:
            raise SubsonicError(
                ErrorCode.GENERIC, f"Invalid value for parameter {name}: {value}"
            ) from None

    def require_int(self, name: str) -> int:
        self.require(name)
        value = self.get_int(name)
        assert value is not None
        return value

    def get_bool(self, name: str, default: bool = False) -> bool:
        value = self.get(name)
        if value is None or value == "":
            return default
        return value.lower() in ("true", "1", "yes")
