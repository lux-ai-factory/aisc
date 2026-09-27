"""Names people type, turned into what URLs and engine secret keys accept."""
import re


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40].strip("_")
    if not slug:
        return "connector"
    if slug[0].isdigit():
        # The "c_" prefix pushes the 40-char cutoff earlier and can land on an
        # underscore that survived the strip above; strip it again.
        return f"c_{slug}"[:40].rstrip("_")
    return slug


def secret_key(slug: str) -> str:
    # engine ProjectConfig keys must match ^[A-Za-z][A-Za-z0-9_]*$
    return f"CONNECTOR_{slug.upper()}_TOKEN"
