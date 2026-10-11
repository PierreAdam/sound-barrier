"""Shoutcast metadata in the server player's stream: the title internet radio clients show."""

from collections.abc import AsyncIterator

from app.services.server_player import ICY_MAX_BLOCK, icy_block, with_icy


def test_a_block_is_its_length_then_the_padded_title() -> None:
    block = icy_block("Band - Don't Stop!")
    meta = b"StreamTitle='Band - Don't Stop!';"  # 33 bytes
    assert block[0] == 3  # 48 bytes
    assert block[1:] == meta + bytes(48 - len(meta))
    assert icy_block(None) == b"\0"  # nothing new
    assert icy_block("") == bytes([1]) + b"StreamTitle='';" + b"\0"


def test_a_long_title_is_cut_on_a_character() -> None:
    block = icy_block("é" * 5000)
    assert len(block) == 1 + ICY_MAX_BLOCK
    assert block[1:].rstrip(b"\0").decode().endswith("é';")


async def test_blocks_every_metaint_bytes_only_when_the_title_changes() -> None:
    titles = iter(["One", "One", "Two"])

    async def chunks() -> AsyncIterator[bytes]:
        for size in (3, 9, 1, 7):  # across the blocks' places
            yield b"a" * size

    out = b"".join([c async for c in with_icy(chunks(), lambda: next(titles), metaint=6)])
    one, two = icy_block("One"), icy_block("Two")
    assert out == b"a" * 6 + one + b"a" * 6 + b"\0" + b"a" * 6 + two + b"a" * 2
