"""RFC 8785 JSON canonicalisation (JCS), so the same content always gives the same bytes and digest.

- Object keys sorted by their UTF-16 code units; no insignificant whitespace; UTF-8 out.
- Strings escape only what JSON requires: `"` and `\\`, the short escapes \\b \\f \\n \\r \\t, other
  controls as \\u00xx (lowercase hex). `/` and DEL stay as they are.
- Numbers in the ECMAScript Number.prototype.toString form.

Stricter than JSON on purpose: integers beyond +-2**53 (a TypeScript twin couldn't hold
them), lone surrogates, NaN and infinities, and every type JSON has no form for are refused.
"""
from __future__ import annotations

import hashlib
import math

_MAX_SAFE = 2 ** 53
_SHORT = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def canonical(value) -> bytes:
    """The canonical bytes of a JSON value (dict, list or tuple, str, int, float, bool, None)."""
    out: list[str] = []
    _write(value, out)
    return "".join(out).encode("utf-8")


def sha256_hex(value) -> str:
    """The plain SHA-256 of the canonical bytes (integrity, not secrecy: see `secrets`)."""
    return hashlib.sha256(canonical(value)).hexdigest()


def _write(value, out: list[str]) -> None:
    if value is None:
        out.append("null")
    elif value is True:
        out.append("true")
    elif value is False:
        out.append("false")
    elif isinstance(value, int):
        if abs(value) > _MAX_SAFE:
            raise ValueError(f"integer beyond 2**53: {value}")
        out.append(str(value))
    elif isinstance(value, float):
        out.append(_number(value))
    elif isinstance(value, str):
        out.append(_string(value))
    elif isinstance(value, (list, tuple)):
        out.append("[")
        for i, item in enumerate(value):
            if i:
                out.append(",")
            _write(item, out)
        out.append("]")
    elif isinstance(value, dict):
        for key in value:
            if not isinstance(key, str):
                raise TypeError(f"object keys must be text, not {type(key).__name__}")
        out.append("{")
        for i, key in enumerate(sorted(value, key=_utf16)):
            if i:
                out.append(",")
            out.append(_string(key))
            out.append(":")
            _write(value[key], out)
        out.append("}")
    else:
        raise TypeError(f"JSON has no form for {type(value).__name__}")


def _utf16(key: str) -> bytes:
    return key.encode("utf-16-be", "surrogatepass")


def _string(text: str) -> str:
    parts = ['"']
    for ch in text:
        code = ord(ch)
        if 0xD800 <= code <= 0xDFFF:
            raise ValueError("a lone surrogate has no UTF-8 form")
        if ch in _SHORT:
            parts.append(_SHORT[ch])
        elif code < 0x20:
            parts.append(f"\\u{code:04x}")
        else:
            parts.append(ch)
    parts.append('"')
    return "".join(parts)


def _number(x: float) -> str:
    """ECMAScript Number::toString for a finite double (ECMA-262 6.1.6.1.20)."""
    if math.isnan(x) or math.isinf(x):
        raise ValueError("NaN and infinities have no JSON form")
    if x == 0:
        return "0"                                                  # -0 too
    sign = "-" if x < 0 else ""
    # repr gives the shortest digits that round-trip, which is what ECMAScript asks for
    mantissa, _, exp = repr(abs(x)).partition("e")
    whole, _, frac = mantissa.partition(".")
    digits = (whole + frac).lstrip("0")
    shift = int(exp) if exp else 0
    if whole == "0":                                                # 0.00ddd = 0.ddd * 10**-(zeros skipped)
        point = shift - (len(frac) - len(frac.lstrip("0")))
    else:                                                           # value = 0.digits... * 10**point
        point = len(whole) + shift
    digits = digits.rstrip("0") or "0"
    k, n = len(digits), point
    if k <= n <= 21:
        return sign + digits + "0" * (n - k)
    if 0 < n <= 21:
        return sign + digits[:n] + "." + digits[n:]
    if -6 < n <= 0:
        return sign + "0." + "0" * (-n) + digits
    e = n - 1
    exp_text = ("+" if e >= 0 else "-") + str(abs(e))
    return sign + digits[0] + ("." + digits[1:] if k > 1 else "") + "e" + exp_text
