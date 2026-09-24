"""Names people type, turned into what URLs and engine secret keys accept."""
import re


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40].strip("_")
    if not slug:
        return "connector"
    return f"c_{slug}"[:40] if slug[0].isdigit() else slug


def secret_key(slug: str) -> str:
    # engine ProjectConfig keys must match ^[A-Za-z][A-Za-z0-9_]*$
    return f"CONNECTOR_{slug.upper()}_TOKEN"
