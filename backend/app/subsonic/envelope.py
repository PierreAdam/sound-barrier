"""The `subsonic-response` envelope, serialized as XML (default), JSON or JSONP.

Payloads are Pydantic models dumped to plain dicts. The XML mapping follows the
Subsonic conventions:
- scalar values become attributes,
- dicts become child elements,
- lists become repeated child elements (scalars in a list become element text),
- a key named `value` becomes the element text (e.g. lyrics).
"""

import json
import re
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring

from pydantic import BaseModel
from starlette.responses import Response

from app import __version__
from app.subsonic.errors import SubsonicError

API_VERSION = "1.16.1"
SERVER_TYPE = "sound-barrier"
XML_NAMESPACE = "http://subsonic.org/restapi"

_JSONP_CALLBACK = re.compile(r"^[A-Za-z_$][\w$.]*$")

Payload = Mapping[str, BaseModel | Sequence[BaseModel]] | None


class ResponseFormat(StrEnum):
    XML = "xml"
    JSON = "json"
    JSONP = "jsonp"

    @classmethod
    def parse(cls, value: str | None) -> "ResponseFormat":
        try:
            return cls(value) if value else cls.XML
        except ValueError:
            return cls.XML


def _dump(value: BaseModel | Sequence[BaseModel]) -> Any:
    if not isinstance(value, BaseModel):
        return [item.model_dump(mode="json", by_alias=True, exclude_none=True) for item in value]
    return value.model_dump(mode="json", by_alias=True, exclude_none=True)


def build_body(payload: Payload, *, status: str = "ok") -> dict[str, Any]:
    body: dict[str, Any] = {
        "status": status,
        "version": API_VERSION,
        "type": SERVER_TYPE,
        "serverVersion": __version__,
        "openSubsonic": True,
    }
    for key, value in (payload or {}).items():
        body[key] = _dump(value)
    return body


def _xml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _fill_element(element: Element, data: Mapping[str, Any]) -> None:
    for key, value in data.items():
        if isinstance(value, Mapping):
            _fill_element(SubElement(element, key), value)  # pyright: ignore[reportUnknownArgumentType]
        elif isinstance(value, list):
            for item in value:  # pyright: ignore[reportUnknownVariableType]
                child = SubElement(element, key)
                if isinstance(item, Mapping):
                    _fill_element(child, item)  # pyright: ignore[reportUnknownArgumentType]
                else:
                    child.text = _xml_scalar(item)
        elif key == "value":
            element.text = _xml_scalar(value)
        else:
            element.set(key, _xml_scalar(value))


def to_xml(body: Mapping[str, Any]) -> bytes:
    root = Element("subsonic-response", {"xmlns": XML_NAMESPACE})
    _fill_element(root, body)
    return tostring(root, encoding="utf-8", xml_declaration=True)


def to_json(body: Mapping[str, Any]) -> bytes:
    return json.dumps({"subsonic-response": body}, ensure_ascii=False).encode()


def render(
    payload: Payload,
    fmt: ResponseFormat,
    *,
    callback: str | None = None,
    status: str = "ok",
) -> Response:
    body = build_body(payload, status=status)
    if fmt is ResponseFormat.JSON:
        return Response(to_json(body), media_type="application/json")
    if fmt is ResponseFormat.JSONP and callback and _JSONP_CALLBACK.match(callback):
        content = callback.encode() + b"(" + to_json(body) + b");"
        return Response(content, media_type="application/javascript")
    return Response(to_xml(body), media_type="application/xml")


class _Error(BaseModel):
    code: int
    message: str


def render_error(
    error: SubsonicError, fmt: ResponseFormat, *, callback: str | None = None
) -> Response:
    payload = {"error": _Error(code=int(error.code), message=error.message)}
    return render(payload, fmt, callback=callback, status="failed")
