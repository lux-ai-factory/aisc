import sys
from immudb import ImmudbClient
from immudb.rootService import PersistentRootService
from immudb.datatypesv2 import DatabaseSettingsV2
sf, n = sys.argv[1], int(sys.argv[2])
su = ImmudbClient("127.0.0.1:13322"); su.login("immudb", "spike-admin-pw"); su.createDatabaseV2("ledgerr", DatabaseSettingsV2(), True)
su.useDatabase(b"ledgerr")
if n:
    for i in range(n): su.verifiedSet(f"k{i}".encode(), f"v{i}".encode())
c = ImmudbClient("127.0.0.1:13322", rs=PersistentRootService(sf)); c.login("immudb", "spike-admin-pw", b"ledgerr")
try:
    print("verifiedGet k1 ->", c.verifiedGet(b"k1").value)
    c.verifiedSet(b"after", b"x"); print("verifiedSet after -> ok")
except Exception as e:
    print("->", type(e).__name__, str(e)[:160])
