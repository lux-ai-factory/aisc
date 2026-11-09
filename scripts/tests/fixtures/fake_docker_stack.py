"""A stand-in for docker that serves a running stack to `aisc.py drift`: appends its arguments to the log and
answers `ps`, `inspect` and `diff` from <scratch>/stack.json, which maps each container's name to
{"image": name, "id": image id, "workdir": folder, "mounts": [destination, ...], "diff": ["C /app/x.py", ...]}.
Any other call fails, so a command that changes the stack shows up as a failure.

Run by a launcher on PATH (`docker` for sh, `docker.cmd` for Windows) as: fake_docker_stack.py <log> <scratch> <args>."""
import json
import sys
from pathlib import Path

log, scratch, args = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3:]
with log.open("a") as f:
    f.write(" ".join(args) + "\n")
stack = json.loads((scratch / "stack.json").read_text())
if args[:1] == ["ps"]:
    sys.stdout.write("".join(f"{name}\n" for name in stack))
elif args[:1] == ["inspect"]:
    names = [a for a in args[1:] if not a.startswith("-")]
    sys.stdout.write(json.dumps([{
        "Name": "/" + name,
        "Image": "sha256:" + stack[name]["id"],
        "Config": {"Image": stack[name]["image"], "WorkingDir": stack[name].get("workdir", "/app"),
                   "Labels": {"com.docker.compose.service": name.split("-", 2)[-1]}},
        "Mounts": [{"Type": "bind", "Destination": d} for d in stack[name].get("mounts", [])],
    } for name in names]))
elif args[:1] == ["diff"]:
    sys.stdout.write("".join(f"{line}\n" for line in stack[args[1]].get("diff", [])))
else:
    sys.exit(1)
