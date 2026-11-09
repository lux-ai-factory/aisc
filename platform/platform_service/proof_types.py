"""What a proof file may be: its type read from its bytes, and a name whose extension agrees.

A person answering a checklist attaches files that prove the answer. Only documents and images are
taken, and the type is never the one the browser or the name claims: it is read from the bytes. OOXML
(docx, xlsx, pptx) and OpenDocument are zip files, told apart by their entries; legacy Office files by
the OLE header (which one of the three is left to the extension); CSV and text are UTF-8 with no NUL.
The extension of the name must agree with what the bytes are, so a program renamed to .pdf, or an HTML
page named .pdf, is refused.

Standard library only.
"""
from __future__ import annotations

import io
import re
import zipfile

#: the largest file taken, in bytes
MAX_BYTES = 25 * 1024 * 1024
#: the longest name kept, in characters
MAX_NAME = 255

PDF = "application/pdf"
PNG = "image/png"
JPEG = "image/jpeg"
WEBP = "image/webp"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
ODT = "application/vnd.oasis.opendocument.text"
ODS = "application/vnd.oasis.opendocument.spreadsheet"
ODP = "application/vnd.oasis.opendocument.presentation"
DOC = "application/msword"
XLS = "application/vnd.ms-excel"
PPT = "application/vnd.ms-powerpoint"
CSV = "text/csv"
TEXT = "text/plain"

#: each extension taken, and the type its bytes must be
EXTENSIONS = {
    "pdf": PDF, "png": PNG, "jpg": JPEG, "jpeg": JPEG, "webp": WEBP,
    "docx": DOCX, "xlsx": XLSX, "pptx": PPTX, "odt": ODT, "ods": ODS, "odp": ODP,
    "doc": DOC, "xls": XLS, "ppt": PPT, "csv": CSV, "txt": TEXT,
}

#: the folder of an OOXML package that says which of the three it is
_OOXML_PARTS = {"word/": DOCX, "xl/": XLSX, "ppt/": PPTX}
_ODF_TYPES = (ODT, ODS, ODP)
_OLE = bytes.fromhex("d0cf11e0a1b11ae1")
_OLE_TYPES = (DOC, XLS, PPT)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


class Refused(ValueError):
    """The file is not one that is taken; the message says why, fit to show the person."""


class NameRefused(Refused):
    """The file's name cannot be kept (empty, or too long)."""


def clean_name(given: str) -> str:
    """The file's own name, without any folder it was sent with or control characters."""
    name = re.split(r"[\\/]", given or "")[-1]
    name = _CONTROL.sub(" ", name).strip()
    if not name or name in (".", ".."):
        raise NameRefused("the file has no name")
    if len(name) > MAX_NAME:
        raise NameRefused(f"the file's name is longer than {MAX_NAME} characters")
    return name


def _extension(name: str) -> str:
    stem, dot, ext = name.rpartition(".")
    return ext.lower() if dot and stem else ""


#: an ODF `mimetype` entry is one short type name
_MIMETYPE_MAX = 100


def _zip_type(data: bytes) -> str | None:
    """OOXML by its [Content_Types].xml and main folder, ODF by its first entry `mimetype`; else None."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            infos = z.infolist()
            if infos and infos[0].filename == "mimetype":
                # never unpacked whole: a small zip can declare gigabytes here
                if infos[0].file_size > _MIMETYPE_MAX:
                    return None
                with z.open(infos[0]) as f:
                    declared = f.read(_MIMETYPE_MAX).decode("ascii", "replace").strip()
                return declared if declared in _ODF_TYPES else None
            names = {i.filename for i in infos}
            if "[Content_Types].xml" not in names:
                return None
            found = {mime for part, mime in _OOXML_PARTS.items() if any(n.startswith(part) for n in names)}
            return found.pop() if len(found) == 1 else None
    except (zipfile.BadZipFile, KeyError, OSError, ValueError, EOFError, NotImplementedError):
        return None


def _is_text(data: bytes) -> bool:
    if b"\0" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _types_of(data: bytes) -> tuple[str, ...]:
    """What the bytes can be: one type, or the three legacy Office ones for an OLE file."""
    if data.startswith(b"%PDF-"):
        return (PDF,)
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return (PNG,)
    if data.startswith(b"\xff\xd8\xff"):
        return (JPEG,)
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return (WEBP,)
    if data.startswith(_OLE):
        return _OLE_TYPES
    if data.startswith(b"PK\x03\x04"):
        found = _zip_type(data)
        return (found,) if found else ()
    if _is_text(data):
        return (CSV, TEXT)
    return ()


def sniff(data: bytes, name: str) -> str:
    """The file's type, read from its bytes, when it is taken and its extension agrees; Refused otherwise."""
    if not data:
        raise Refused("the file is empty")
    if len(data) > MAX_BYTES:
        raise Refused(f"the file is larger than {MAX_BYTES // (1024 * 1024)} MB")
    claimed = EXTENSIONS.get(_extension(name))
    if claimed is None:
        raise Refused("only PDF, Word, Excel, PowerPoint, OpenDocument, CSV, text, PNG, JPEG and WebP files"
                      " are taken")
    found = _types_of(data)
    if not found:
        raise Refused("the file's contents are not of a type that is taken")
    if claimed not in found:
        raise Refused(f"the file's contents do not match its .{_extension(name)} extension")
    return claimed
