"""A stand-in for docker in the install tests: appends its arguments to the log and succeeds. `docker ps` prints
the folders in <scratch>/stack-folders and fails while <scratch>/ps-fails exists.

Run by a launcher on PATH (`docker` for sh, `docker.cmd` for Windows) as: fake_docker.py <log> <scratch> <args>."""
import sys
from pathlib import Path

log, scratch, args = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3:]
with log.open("a") as f:
    f.write(" ".join(args) + "\n")
if args[:1] == ["ps"]:
    if (scratch / "ps-fails").exists():
        sys.exit(1)
    folders = scratch / "stack-folders"
    if folders.exists():
        sys.stdout.write(folders.read_text())
sys.exit(0)
