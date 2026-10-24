"""What an installed test declares it assesses, and its helper models: does it follow the plugin interface?

verify-plugins.sh gives `check` one entry of the engine's GET /api/v1/plugins/declarations (what the
plugin interface reads from the plugin class: target_kinds, adopted, helper_roles, config_fields) and
the names of the config fields its form asks a person for. It answers a list of (level, message), empty
when the test conforms:

  FAIL  a test that adopted @assesses declares no target kind
  FAIL  a helper role the interface does not know (HELPER_ROLES of aisc_plugin_interface.helpers)
  FAIL  a test that adopted @assesses and declares an AI card target asks a person for that target in
        its config form (a field named like target_model, target_credential, target_endpoint or
        model_under_test): the platform reaches the target, so the person never gives it there
  WARN  a test that has not adopted @assesses: what it is missing

Field names only: the route never sends a value, and nothing here prints one.
"""
import re

#: as aisc_plugin_interface.helpers.HELPER_ROLES (the interface is not installed where the check runs)
HELPER_ROLES = ("judge", "attacker", "grader", "embedder", "generator")
#: config field names that select or key the model under test
TARGET_FIELDS = ("target_model", "target_credential", "target_endpoint", "model_under_test")
CARD = "card"
#: what the engine adds to each declaration for this check
CHECKED_KEYS = ("adopted", "helper_roles", "config_fields")


def _target_fields(config_fields):
    """The fields whose name, lowercased with dots and dashes read as underscores, holds a TARGET_FIELDS name."""
    def norm(name):
        return re.sub(r"[^a-z0-9]+", "_", name.lower())
    return [f for f in config_fields if any(t in norm(f) for t in TARGET_FIELDS)]


def check(declaration: dict, config_fields: list[str]) -> list[tuple[str, str]]:
    missing = [k for k in CHECKED_KEYS if k not in declaration]
    if missing:
        return [("WARN", f"the engine's declarations do not say {', '.join(missing)}: an engine older than the"
                         " check, so the test is not checked")]
    kinds = list(declaration.get("target_kinds") or [])
    findings = []
    unknown = [r for r in declaration["helper_roles"] if r not in HELPER_ROLES]
    if unknown:
        findings.append(("FAIL", f"declares the helper role {', '.join(unknown)}, which the interface does not know"
                                 f" (known: {', '.join(HELPER_ROLES)})"))
    asked = _target_fields(config_fields)
    if declaration["adopted"]:
        if not kinds:
            findings.append(("FAIL", "adopted @assesses but declares no target kind: declare card=, local_model="
                                     " or both"))
        if CARD in kinds and asked:
            findings.append(("FAIL", f"declares an AI card target and still asks for it in its config form"
                                     f" ({', '.join(asked)}): the platform reaches the target; fill such fields"
                                     " through @assesses(card=...) and hide them"))
    elif kinds:
        findings.append(("WARN", "reads as an AI card target through an older declaration: it has not adopted"
                                 " @assesses (card=, local_model=)"))
    else:
        findings.append(("WARN", "declares nothing it assesses: no @assesses (card=, local_model=), so the form"
                                 " asks for a target as before"))
    return findings
