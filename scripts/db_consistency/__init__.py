"""A read-only consistency check of the AISC platform's databases.

Each check is a small function taking a `Cluster` and returning findings (FAIL or WARN, with
the check's id and a message). Nothing here writes: every connection is opened with
default_transaction_read_only=on and only SELECTs are sent. The catalogue is out of scope.

    python -m db_consistency            # from scripts/, libpq PG* environment
"""
