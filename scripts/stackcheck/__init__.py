"""Checks against the running stack, in Python: one harness for what each scripts/verify-*.sh repeats in bash.

    cd scripts && python3 -m stackcheck <group> [--only NAME ...]

A group is a list of named checks (harness.Check). The harness parses the arguments strictly (an unknown group,
option or check name stops it), runs every check on its own (one that raises fails alone, with its error), and
prints each failure's whole detail. A denial counts only after a positive control succeeded (harness.deny), and
secrets never go on a command line: psql takes its password from the environment and its SQL on stdin, a token
request carries the password in its body (stack.Stack). Paths are the repository's, whatever the current folder.

The bash scripts become groups one at a time; each keeps running until its group has been proven on a live stack.
"""
