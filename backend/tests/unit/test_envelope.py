import json
from xml.etree import ElementTree

from app.subsonic import schemas
from app.subsonic.envelope import (
    API_VERSION,
    ResponseFormat,
    build_body,
    render,
    render_error,
    to_json,
    to_xml,
)
from app.subsonic.errors import ErrorCode, SubsonicError
from app.subsonic.schemas import SubsonicModel

NS = "{http://subsonic.org/restapi}"


class _Line(SubsonicModel):
    start: int
    value: str


class _Lyrics(SubsonicModel):
    display_artist: str
    line: list[_Line]


def _folders() -> dict[str, schemas.MusicFolders]:
    return {
        "musicFolders": schemas.MusicFolders(
            music_folder=[schemas.MusicFolder(id=1, name="Music"), schemas.MusicFolder(id=2)]
        )
    }


def test_json_envelope() -> None:
    body = json.loads(to_json(build_body(_folders())))["subsonic-response"]
    assert body["status"] == "ok"
    assert body["version"] == API_VERSION
    assert body["openSubsonic"] is True
    # None fields are omitted, lists stay lists
    assert body["musicFolders"] == {"musicFolder": [{"id": 1, "name": "Music"}, {"id": 2}]}


def test_xml_envelope() -> None:
    root = ElementTree.fromstring(to_xml(build_body(_folders())))
    assert root.tag == f"{NS}subsonic-response"
    assert root.get("status") == "ok"
    assert root.get("openSubsonic") == "true"
    folders = root.findall(f"{NS}musicFolders/{NS}musicFolder")
    assert [f.attrib for f in folders] == [{"id": "1", "name": "Music"}, {"id": "2"}]


def test_xml_scalar_lists_and_text_value() -> None:
    user = schemas.User(
        username="bob",
        scrobbling_enabled=True,
        admin_role=False,
        settings_role=True,
        download_role=True,
        upload_role=False,
        playlist_role=True,
        cover_art_role=True,
        comment_role=True,
        podcast_role=False,
        stream_role=True,
        jukebox_role=False,
        share_role=False,
        video_conversion_role=False,
        folder=[1, 3],
    )
    lyrics = _Lyrics(
        display_artist="A", line=[_Line(start=0, value="first"), _Line(start=5, value="second")]
    )
    root = ElementTree.fromstring(to_xml(build_body({"user": user, "lyrics": lyrics})))

    user_el = root.find(f"{NS}user")
    assert user_el is not None
    assert user_el.get("adminRole") == "false"
    assert [f.text for f in user_el.findall(f"{NS}folder")] == ["1", "3"]

    lines = root.findall(f"{NS}lyrics/{NS}line")
    assert [(line.get("start"), line.text) for line in lines] == [("0", "first"), ("5", "second")]
    assert root.find(f"{NS}lyrics").get("displayArtist") == "A"  # type: ignore[union-attr]


def test_top_level_list_payload() -> None:
    ext = [schemas.OpenSubsonicExtension(name="formPost", versions=[1])]
    body = build_body({"openSubsonicExtensions": ext})
    assert json.loads(to_json(body))["subsonic-response"]["openSubsonicExtensions"] == [
        {"name": "formPost", "versions": [1]}
    ]
    root = ElementTree.fromstring(to_xml(body))
    el = root.find(f"{NS}openSubsonicExtensions")
    assert el is not None and el.get("name") == "formPost"
    assert [v.text for v in el.findall(f"{NS}versions")] == ["1"]


def test_error_rendering() -> None:
    response = render_error(SubsonicError.missing("id"), ResponseFormat.JSON)
    assert response.status_code == 200
    body = json.loads(response.body)["subsonic-response"]
    assert body["status"] == "failed"
    assert body["error"] == {
        "code": ErrorCode.MISSING_PARAMETER,
        "message": "Required parameter is missing: id",
    }


def test_format_parsing_defaults_to_xml() -> None:
    assert ResponseFormat.parse(None) is ResponseFormat.XML
    assert ResponseFormat.parse("json") is ResponseFormat.JSON
    assert ResponseFormat.parse("bogus") is ResponseFormat.XML


def test_jsonp() -> None:
    response = render(None, ResponseFormat.JSONP, callback="cb")
    assert bytes(response.body).startswith(b"cb(") and bytes(response.body).endswith(b");")
    # Invalid callback names fall back to XML instead of injecting script
    response = render(None, ResponseFormat.JSONP, callback="alert(1)//")
    assert response.media_type == "application/xml"


def test_access_log_redacts_credentials() -> None:
    from app.core.logging import redact_query

    path = "/rest/stream?u=admin&t=26719a1196d2a940705a59634eb18eab&s=c19b2d&id=42&p=enc:73"
    assert redact_query(path) == "/rest/stream?u=admin&t=***&s=***&id=42&p=***"
    assert redact_query("/rest/ping?apiKey=secret&f=json") == "/rest/ping?apiKey=***&f=json"
