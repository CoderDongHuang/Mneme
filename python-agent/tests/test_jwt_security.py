import base64

import jwt
import pytest


def test_recursive_unsigned_payload_raises_documented_decode_error():
    def encode(value):
        return base64.urlsafe_b64encode(value).rstrip(b"=")

    token = b".".join([
        encode(b'{"alg":"HS256","typ":"JWT"}'),
        encode(b"[" * 20000 + b"]" * 20000),
        encode(b"forged-signature"),
    ]).decode("ascii")
    with pytest.raises(jwt.DecodeError):
        jwt.decode(token, options={"verify_signature": False})
