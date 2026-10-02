"""immudb 1.11.1 + immudb-py 1.5.0: what the ledger can rely on."""
import os, pickle, tempfile, threading, traceback
from immudb import ImmudbClient, constants
from immudb.rootService import PersistentRootService
from immudb.datatypesv2 import DatabaseSettingsV2
URL = "127.0.0.1:13322"

def step(title, fn):
    try:
        print(f"[ok]   {title}: {fn()}")
    except Exception as e:
        d = e.details() if hasattr(e, "details") else str(e).splitlines()[0]
        print(f"[fail] {title}: {getattr(e, 'code', lambda: '')()} {d[:160]}")

su = ImmudbClient(URL); su.login("immudb", "spike-admin-pw")
step("superuser creates database ledgera", lambda: su.createDatabaseV2("ledgera", DatabaseSettingsV2(), True) and "created")
step("superuser creates user aisc_ledger with RW on ledgera",
     lambda: su.createUser("aisc_ledger", "Ledger-pw-123!", constants.PERMISSION_RW, "ledgera") or "created")
step("superuser creates user aisc_admin with ADMIN on ledgera",
     lambda: su.createUser("aisc_admin", "Admin-pw-123!", constants.PERMISSION_ADMIN, "ledgera") or "created")

lw = ImmudbClient(URL); lw.login("aisc_ledger", "Ledger-pw-123!", b"ledgera")
step("aisc_ledger (RW) creates database ledgerb", lambda: lw.createDatabaseV2("ledgerb", DatabaseSettingsV2(), True) and "created")
step("aisc_ledger (RW) verifiedSet + verifiedGet in ledgera",
     lambda: (lw.verifiedSet(b"e1", b"hello"), lw.verifiedGet(b"e1").value)[1])
step("aisc_ledger (RW) SQL CREATE TABLE in ledgera",
     lambda: lw.sqlExec("CREATE TABLE IF NOT EXISTS entries(seq INTEGER AUTO_INCREMENT, body VARCHAR[4096], PRIMARY KEY seq)") and "created")
step("aisc_ledger (RW) SQL INSERT + query",
     lambda: (lw.sqlExec("INSERT INTO entries(body) VALUES (@b)", {"b": "x"}), lw.sqlQuery("SELECT seq, body FROM entries"))[1])
step("aisc_ledger (RW) grants itself ADMIN on ledgera",
     lambda: lw.changePermission(constants.PERMISSION_GRANT, "aisc_ledger", "ledgera", constants.PERMISSION_ADMIN) or "granted")
step("aisc_ledger deletes ledgera (unload first)", lambda: (lw.unloadDatabase("ledgera"), "unloaded")[1])

ad = ImmudbClient(URL); ad.login("aisc_admin", "Admin-pw-123!", b"ledgera")
step("aisc_admin (ADMIN of ledgera) creates database ledgerc", lambda: ad.createDatabaseV2("ledgerc", DatabaseSettingsV2(), True) and "created")
su.createDatabaseV2("ledgerd", DatabaseSettingsV2(), True)
step("aisc_admin (ADMIN of ledgera) grants aisc_ledger RW on ledgerd",
     lambda: ad.changePermission(constants.PERMISSION_GRANT, "aisc_ledger", "ledgerd", constants.PERMISSION_RW) or "granted")
step("superuser grants aisc_ledger RW on ledgerd",
     lambda: su.changePermission(constants.PERMISSION_GRANT, "aisc_ledger", "ledgerd", constants.PERMISSION_RW) or "granted")
step("aisc_ledger switches to ledgerd (granted after its login)", lambda: (lw.useDatabase(b"ledgerd"), lw.verifiedSet(b"k", b"v"), "wrote")[2])

# size limits
lw = ImmudbClient(URL); lw.login("aisc_ledger", "Ledger-pw-123!", b"ledgerd")
step("aisc_ledger, logged in again, writes to ledgerd", lambda: (lw.verifiedSet(b"k", b"v"), "wrote")[1])
lw.useDatabase(b"ledgera")
step("verifiedSet 256 KiB value", lambda: (lw.verifiedSet(b"big", b"x" * 262144), len(lw.verifiedGet(b"big").value))[1])
step("verifiedSet 5 MiB value", lambda: (lw.verifiedSet(b"huge", b"x" * 5 * 1024 * 1024), "stored")[1])
step("SQL VARCHAR[4096] with 5000 chars", lambda: lw.sqlExec("INSERT INTO entries(body) VALUES (@b)", {"b": "y" * 5000}) and "stored")

l2 = ImmudbClient(URL); l2.login("aisc_ledger", "Ledger-pw-123!", b"ledgera")
step("aisc_ledger logged in on ledgera: SQL INSERT", lambda: l2.sqlExec("INSERT INTO entries(body) VALUES (@b)", {"b": "z"}) and "stored")
step("... SQL INSERT 5000 chars into VARCHAR[4096]", lambda: l2.sqlExec("INSERT INTO entries(body) VALUES (@b)", {"b": "y" * 5000}) and "stored")
l2.useDatabase(b"ledgerd"); l2.useDatabase(b"ledgera")
step("... after useDatabase(ledgerd) then back to ledgera: SQL INSERT", lambda: l2.sqlExec("INSERT INTO entries(body) VALUES (@b)", {"b": "z"}) and "stored")
step("... and KV verifiedSet", lambda: (l2.verifiedSet(b"k2", b"v"), "wrote")[1])

# one client, two threads, two databases
su.createDatabaseV2("ledgerx", DatabaseSettingsV2(), True); su.createDatabaseV2("ledgery", DatabaseSettingsV2(), True)
for db in ("ledgerx", "ledgery"):
    su.changePermission(constants.PERMISSION_GRANT, "aisc_ledger", db, constants.PERMISSION_RW)
shared = ImmudbClient(URL); shared.login("aisc_ledger", "Ledger-pw-123!", b"ledgerx")
errors = []
def writer(db, n=300):
    for i in range(n):
        try:
            shared.useDatabase(db.encode()); shared.set(f"{db}-{i}".encode(), db.encode())
        except Exception as e:
            errors.append(repr(e)[:80])
ts = [threading.Thread(target=writer, args=(d,)) for d in ("ledgerx", "ledgery")]
[t.start() for t in ts]; [t.join() for t in ts]
def misplaced(db):
    shared.useDatabase(db.encode())
    keys = [k.decode() for k in shared.scan(b"", b"", False, 1000)]
    return sum(1 for k in keys if not k.startswith(db)), len(keys)
step("shared client, 2 threads x 300 sets: wrong-db entries in ledgerx (wrong, total)", lambda: misplaced("ledgerx"))
step("... and in ledgery", lambda: misplaced("ledgery"))
step("... errors during the run", lambda: (len(errors), errors[:2]))

# persisted state: format, and a database that is deleted and recreated
statefile = os.path.join(tempfile.mkdtemp(), "state")
c1 = ImmudbClient(URL, rs=PersistentRootService(statefile)); c1.login("immudb", "spike-admin-pw", b"ledgery")
su.useDatabase(b"ledgery"); su.verifiedSet(b"seed", b"y"); su.useDatabase(b"ledgerx"); su.verifiedSet(b"seed", b"x")
c1.verifiedGet(b"seed"); c1.useDatabase(b"ledgerx"); c1.verifiedGet(b"seed")
step("PersistentRootService file content", lambda: {k: type(v).__name__ for k, v in pickle.load(open(statefile, "rb")).items()})
step("superuser unloads + deletes ledgery", lambda: (su.unloadDatabase("ledgery"), su.deleteDatabase("ledgery"), "deleted")[2])
su.createDatabaseV2("ledgery", DatabaseSettingsV2(), True); su.useDatabase(b"ledgery"); su.set(b"seed", b"rewritten")
c2 = ImmudbClient(URL, rs=PersistentRootService(statefile)); c2.login("immudb", "spike-admin-pw", b"ledgery")
step("client with the old state reads the recreated ledgery (verified)", lambda: c2.verifiedGet(b"seed").value)
c3 = ImmudbClient(URL); c3.login("immudb", "spike-admin-pw", b"ledgery")
step("client with no saved state reads the recreated ledgery (verified)", lambda: c3.verifiedGet(b"seed").value)
step("server signing key configured (state signature present)", lambda: bool(c3.currentState().signature.signature) if hasattr(c3.currentState(), 'signature') and c3.currentState().signature else False)
