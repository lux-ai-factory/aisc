"""This install's run-uid pools: the uids its eval workers run plugin tests and installs as (PLUGIN_RUN_UIDS, the
declarations worker's PLUGIN_DECLARATIONS_RUN_UIDS). The kernel counts a uid's processes across every container on
the host, so two installs that leased the same uid would share one process cap. start chooses the pools once,
from the install's id, away from the pools other installs' workers on this host carry, and keeps them in
env.local; compose reads them from there."""
from __future__ import annotations

#: where the pools begin: an install without an id keeps the pools it always had (10100-10199 and 10200-10209)
FIRST_UID = 10100
#: the uids one install takes: its run worker's 100, then its declarations worker's 10
BLOCK = 128
RUN_SIZE, DECLARATIONS_SIZE = 100, 10
#: blocks below 60000, well under the kernel's overflow uid (65534)
BLOCKS = (60000 - FIRST_UID) // BLOCK
RUN_NAME, DECLARATIONS_NAME = "PLUGIN_RUN_UIDS", "PLUGIN_DECLARATIONS_RUN_UIDS"
#: the label the run worker carries its pool in, read by another install's start
LABEL = "aisc.run-uids"
#: the pool of a worker made before installs had pools of their own
OLD_DEFAULT = "10100-10199"


def _block_of(pool: str) -> int | None:
    first, _, _last = pool.partition("-")
    try:
        return (int(first) - FIRST_UID) // BLOCK
    except ValueError:
        return None


def _pools(block: int) -> dict[str, str]:
    run = FIRST_UID + block * BLOCK
    declarations = run + RUN_SIZE
    return {RUN_NAME: f"{run}-{run + RUN_SIZE - 1}",
            DECLARATIONS_NAME: f"{declarations}-{declarations + DECLARATIONS_SIZE - 1}"}


def run_uid_settings(kept: dict[str, str], install: str, others: list[str]) -> dict[str, str]:
    """The pool settings start writes into env.local: none when env.local has both already (they are kept).
    Otherwise the block the install's id names (block 0, the old pools, for an install without an id), or, when
    another install's worker (others: their run pools) holds it, the next free one."""
    if kept.get(RUN_NAME) and kept.get(DECLARATIONS_NAME):
        return {}
    taken = {block for block in map(_block_of, others) if block is not None}
    try:
        preferred = int(install, 16) % BLOCKS if install else 0
    except ValueError:
        preferred = 0
    for step in range(BLOCKS):
        block = (preferred + step) % BLOCKS
        if block not in taken:
            return _pools(block)
    raise RuntimeError("every run-uid pool on this host is taken by another install")


def other_installs_run_uids(listing: str, own: str) -> list[str]:
    """The run pools of other installs' workers, from `project<TAB>label` lines (docker ps -a): a worker with
    no label leases the old default pool."""
    found: list[str] = []
    for line in listing.splitlines():
        project, _, pool = line.partition("\t")
        pool = pool.strip() or OLD_DEFAULT
        if project and project != own and pool not in found:
            found.append(pool)
    return found
