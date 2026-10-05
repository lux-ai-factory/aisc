"""The live data move: python -m platform_service.isolate.

Moves an install from the shared layout (every project's rows in the `platform` database) to one
database per project. Reads the shared layout in `platform` in one read-only snapshot, places every row in
its project by the catalog's foreign keys, and copies each project's rows into its own
database, one project and one transaction at a time, verified by count and checksum.
Never writes to the shared module schemas; the only write to `platform` is the library.
"""
from .cli import main

__all__ = ["main"]
