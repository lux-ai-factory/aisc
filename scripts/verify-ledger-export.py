#!/usr/bin/env python3
"""Check a ledger export offline (docs/superpowers/ledger-2026-10-02/02-spec.md 6.3, 7.4).

    verify-ledger-export.py --public-key immudb-signing.pub [--check-content] export.jsonl

Trusts nothing in the file: it recomputes every hash link from the first entry, checks the head's
signature with the public key it is given, and with --check-content recomputes each frozen content's
keyed digest with the project's content key the head carries. Exit 0 only if every check passes.
Needs Python 3.10+ and the `cryptography` package; nothing from the platform.
"""
import argparse
import base64
import hashlib
import hmac
import json
import math
import re
import sys

GENESIS = "00" * 32
_DIGEST = re.compile(r"hmac:(v[1-9][0-9]*):([0-9a-f]{32})")


# RFC 8785, the same rules as platform_service/ledger/canonical.py (a test keeps the two equal) --------
_SHORT = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def canonical(value) -> bytes:
    out = []
    _write(value, out)
    return "".join(out).encode("utf-8")


def _write(value, out):
    if value is None:
        out.append("null")
    elif value is True:
        out.append("true")
    elif value is False:
        out.append("false")
    elif isinstance(value, int):
        if abs(value) > 2 ** 53:
            raise ValueError(f"integer beyond 2**53: {value}")
        out.append(str(value))
    elif isinstance(value, float):
        out.append(_number(value))
    elif isinstance(value, str):
        out.append(_string(value))
    elif isinstance(value, list):
        out.append("[" + ",".join(canonical(v).decode() for v in value) + "]")
    elif isinstance(value, dict):
        keys = sorted(value, key=lambda k: k.encode("utf-16-be", "surrogatepass"))
        out.append("{" + ",".join(_string(k) + ":" + canonical(value[k]).decode() for k in keys) + "}")
    else:
        raise TypeError(f"JSON has no form for {type(value).__name__}")


def _string(text):
    parts = ['"']
    for ch in text:
        code = ord(ch)
        if 0xD800 <= code <= 0xDFFF:
            raise ValueError("a lone surrogate has no UTF-8 form")
        parts.append(_SHORT[ch] if ch in _SHORT else f"\\u{code:04x}" if code < 0x20 else ch)
    parts.append('"')
    return "".join(parts)


def _number(x):
    if math.isnan(x) or math.isinf(x):
        raise ValueError("NaN and infinities have no JSON form")
    if x == 0:
        return "0"
    sign = "-" if x < 0 else ""
    mantissa, _, exp = repr(abs(x)).partition("e")
    whole, _, frac = mantissa.partition(".")
    digits = (whole + frac).lstrip("0")
    shift = int(exp) if exp else 0
    point = shift - (len(frac) - len(frac.lstrip("0"))) if whole == "0" else len(whole) + shift
    digits = digits.rstrip("0") or "0"
    k, n = len(digits), point
    if k <= n <= 21:
        return sign + digits + "0" * (n - k)
    if 0 < n <= 21:
        return sign + digits[:n] + "." + digits[n:]
    if -6 < n <= 0:
        return sign + "0." + "0" * (-n) + digits
    e = n - 1
    return sign + digits[0] + ("." + digits[1:] if k > 1 else "") + "e" + ("+" if e >= 0 else "-") + str(abs(e))


# the checks -----------------------------------------------------------------------------------------

def check(lines, public_key_pem: bytes, check_content: bool) -> list[str]:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    problems = []
    if not lines or "head" not in lines[-1]:
        return ["the file has no head line"]
    head, body = lines[-1]["head"], lines[:-1]
    chain = GENESIS
    for n, line in enumerate(body, 1):
        entry, proof = line.get("entry"), line.get("proof") or {}
        if not isinstance(entry, dict):
            problems.append(f"line {n}: no entry")
            continue
        if entry.get("seq") != n:
            problems.append(f"line {n}: entry seq {entry.get('seq')!r}, expected {n} (a gap or a reorder)")
        if proof.get("previous") != chain:
            problems.append(f"line {n}: its proof starts from another chain")
        chain = hashlib.sha256(bytes.fromhex(chain) + canonical(entry)).hexdigest()
        if proof.get("chain") != chain:
            problems.append(f"line {n}: the entry doesn't hash to its proof")
    if head.get("seq") != len(body) or head.get("chain") != chain:
        problems.append("the head doesn't match the entries")
    try:
        key = serialization.load_pem_public_key(public_key_pem)
        signed = canonical({"log": head.get("log"), "seq": head.get("seq"), "chain": head.get("chain")})
        key.verify(base64.b64decode(head.get("signature") or ""), signed, ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, ValueError, TypeError):
        problems.append("the head's signature is not the signing key's")
    if check_content:
        keys = (head.get("keys") or {}).get("content") or {}
        for n, line in enumerate(body, 1):
            made = (line.get("entry") or {}).get("content_sha256")
            if made is None and "content" not in line:
                continue
            m = _DIGEST.fullmatch(made or "")
            if "content" not in line:
                problems.append(f"line {n}: the entry has a content digest but the file has no content")
            elif not m or m.group(1) not in keys:
                problems.append(f"line {n}: no content key for its digest")
            else:
                mac = hmac.new(bytes.fromhex(keys[m.group(1)]), canonical(line["content"]), hashlib.sha256)
                if not hmac.compare_digest(mac.hexdigest()[:32], m.group(2)):
                    problems.append(f"line {n}: the content isn't what was logged")
    return problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--public-key", required=True, help="the immudb signing key's public half (PEM)")
    parser.add_argument("--check-content", action="store_true", help="also check each frozen content")
    parser.add_argument("export", help="the .jsonl file the platform exported")
    args = parser.parse_args(argv)
    try:
        with open(args.export, encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]
        with open(args.public_key, "rb") as f:
            pem = f.read()
    except (OSError, ValueError) as exc:
        print(f"cannot read: {exc}", file=sys.stderr)
        return 2
    problems = check(lines, pem, args.check_content)
    for p in problems:
        print(p)
    if problems:
        return 1
    print(f"ok: {len(lines) - 1} entries, head {lines[-1]['head'].get('seq')}, signed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
