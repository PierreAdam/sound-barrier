import pytest

from app.core.crypto import PasswordCipher, generate_secret_key, subsonic_token
from app.subsonic.auth import check_password, decode_password_param
from app.subsonic.errors import ErrorCode, SubsonicError
from app.subsonic.params import SubsonicParams


def params(**kwargs: str) -> SubsonicParams:
    return SubsonicParams(list(kwargs.items()))


def test_token_auth() -> None:
    token = subsonic_token("sesame", "c19b2d")
    assert check_password("sesame", params(t=token, s="c19b2d"))
    assert check_password("sesame", params(t=token.upper(), s="c19b2d"))
    assert not check_password("wrong", params(t=token, s="c19b2d"))


def test_known_token_vector() -> None:
    # Example from the Subsonic API documentation.
    assert subsonic_token("sesame", "c19b2d") == "26719a1196d2a940705a59634eb18eab"


def test_plain_and_hex_password() -> None:
    assert check_password("sesame", params(p="sesame"))
    assert check_password("sesame", params(p="enc:" + b"sesame".hex()))
    assert not check_password("sesame", params(p="enc:" + b"other".hex()))


def test_invalid_hex_password() -> None:
    with pytest.raises(SubsonicError) as exc:
        decode_password_param("enc:zz")
    assert exc.value.code is ErrorCode.WRONG_CREDENTIALS


def test_missing_credentials() -> None:
    with pytest.raises(SubsonicError) as exc:
        check_password("sesame", params(u="bob"))
    assert exc.value.code is ErrorCode.MISSING_PARAMETER


def test_password_cipher_roundtrip() -> None:
    cipher = PasswordCipher(generate_secret_key())
    encrypted = cipher.encrypt("sésame")
    assert b"s\xc3\xa9same" not in encrypted
    assert cipher.decrypt(encrypted) == "sésame"


def test_params_multi_values() -> None:
    p = SubsonicParams([("id", "1"), ("id", "2"), ("count", "10")])
    assert p.get("id") == "1"
    assert p.get_all("id") == ["1", "2"]
    assert p.get_int("count") == 10
    assert p.get_int("offset", 0) == 0
    with pytest.raises(SubsonicError):
        SubsonicParams([("count", "ten")]).get_int("count")
