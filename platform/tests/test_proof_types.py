"""What a proof file may be: the type read from its bytes, and a name whose extension agrees with it.

Pure functions, no database and no storage."""
import io
import zipfile

import pytest

from platform_service.proof_types import (MAX_BYTES, Refused, clean_name, sniff)


def _zip(entries: dict[str, bytes], *, first: str | None = None) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        names = list(entries)
        if first:
            names.remove(first)
            names.insert(0, first)
        for name in names:
            z.writestr(name, entries[name])
    return out.getvalue()


def ooxml(part: str) -> bytes:
    return _zip({"[Content_Types].xml": b"<Types/>", "_rels/.rels": b"<Relationships/>",
                 f"{part}/document.xml": b"<x/>"})


def odf(kind: str) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), f"application/vnd.oasis.opendocument.{kind}")
        z.writestr("content.xml", b"<office:document-content/>")
    return out.getvalue()


OLE = bytes.fromhex("d0cf11e0a1b11ae1") + b"\0" * 504
PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 24
JPEG = b"\xff\xd8\xff\xe0" + b"\0" * 24
WEBP = b"RIFF\x24\0\0\0WEBPVP8 " + b"\0" * 24


@pytest.mark.parametrize("data, name, mime", [
    (PDF, "policy.pdf", "application/pdf"),
    (PNG, "screen.png", "image/png"),
    (JPEG, "photo.jpg", "image/jpeg"),
    (JPEG, "photo.JPEG", "image/jpeg"),
    (WEBP, "shot.webp", "image/webp"),
    (ooxml("word"), "plan.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    (ooxml("xl"), "register.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    (ooxml("ppt"), "deck.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    (odf("text"), "plan.odt", "application/vnd.oasis.opendocument.text"),
    (odf("spreadsheet"), "register.ods", "application/vnd.oasis.opendocument.spreadsheet"),
    (odf("presentation"), "deck.odp", "application/vnd.oasis.opendocument.presentation"),
    (OLE, "old.doc", "application/msword"),
    (OLE, "old.xls", "application/vnd.ms-excel"),
    (OLE, "old.ppt", "application/vnd.ms-powerpoint"),
    (b"name,score\nlog kept,4\n", "answers.csv", "text/csv"),
    ("Résumé of the review\n".encode(), "notes.txt", "text/plain"),
    (b"\xef\xbb\xbfwith a byte order mark\n", "bom.txt", "text/plain"),
])
def test_each_allowed_type_is_read_from_its_bytes(data, name, mime):
    assert sniff(data, name) == mime


@pytest.mark.parametrize("data, name", [
    (b"MZ\x90\0\x03\0\0\0" + b"\0" * 64, "invoice.pdf"),          # a Windows program renamed
    (b"MZ\x90\0\x03\0\0\0" + b"\0" * 64, "setup.exe"),
    (b"<!DOCTYPE html><html><script>alert(1)</script></html>", "report.pdf"),
    (_zip({"readme.txt": b"hello"}), "plan.docx"),               # a zip that is not OOXML
    (_zip({"readme.txt": b"hello"}), "archive.zip"),
    (ooxml("word"), "register.xlsx"),                            # OOXML, but a document named as a sheet
    (odf("text"), "plan.docx"),
    (PDF, "policy.docx"),
    (PNG, "screen.jpg"),
    (b"a\0b", "nul.txt"),                                        # text with a NUL
    (b"\xff\xfe\xfa not utf-8", "bad.csv"),
    (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "logo.svg"),
    (PDF, "policy"),                                             # no extension
    (b"", "empty.txt"),
])
def test_a_file_whose_bytes_or_name_do_not_agree_is_refused(data, name):
    with pytest.raises(Refused):
        sniff(data, name)


def test_a_zip_that_cannot_be_read_is_refused():
    with pytest.raises(Refused):
        sniff(b"PK\x03\x04" + b"\0" * 40, "plan.docx")


def test_the_cap_is_25_megabytes():
    assert MAX_BYTES == 25 * 1024 * 1024


@pytest.mark.parametrize("given, kept", [
    ("policy.pdf", "policy.pdf"),
    ("C:\\Users\\me\\policy.pdf", "policy.pdf"),
    ("../../etc/policy.pdf", "policy.pdf"),
    ("  spaced name.pdf  ", "spaced name.pdf"),
    ("tab\tand\nnewline.pdf", "tab and newline.pdf"),
])
def test_a_name_is_kept_without_its_folders_or_control_characters(given, kept):
    assert clean_name(given) == kept


@pytest.mark.parametrize("given", ["", "   ", "/", "..", "a" * 300 + ".pdf"])
def test_a_name_that_is_empty_or_too_long_is_refused(given):
    with pytest.raises(Refused):
        clean_name(given)


def test_an_odf_whose_mimetype_entry_unpacks_to_much_more_is_refused_without_unpacking_it():
    import tracemalloc

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", b"application/vnd.oasis.opendocument.text" + b" " * (200 * 1024 * 1024))
        z.writestr("content.xml", b"<office:document-content/>")
    data = out.getvalue()
    assert len(data) < MAX_BYTES
    tracemalloc.start()
    try:
        with pytest.raises(Refused):
            sniff(data, "plan.odt")
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak < 10 * 1024 * 1024
