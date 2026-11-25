"""Curated scorer caveats plus live prerequisite checks.

Two sources feed profile operability:

  * caveats -- curated, endpoint-conditional knowledge from
    scripts/profile_caveats.json (the team-maintained source of truth).
  * requirements -- live-checkable preconditions declared in the same file
    (e.g. the latency predictor sidecars), evaluated against the EPP
    Deployment. When the cluster cannot be read, the warning says
    prerequisites could not be verified.

All applicable caveats and missing prerequisites produce a warning.
No warning does not prove that a scorer has a useful signal.
"""

import json
import re
from pathlib import Path
from typing import Optional

from paths import SCRIPTS_DIR

CAVEATS_FILE = SCRIPTS_DIR / "profile_caveats.json"

# Trailing weight suffix in profile-map descriptions: "queue-scorer (2)".
WEIGHT_SUFFIX = re.compile(r"\s*\([^)]*\)\s*$")


def load_caveats() -> dict:
    try:
        document = json.loads(CAVEATS_FILE.read_text())
    except (OSError, ValueError):
        return {"verified_as_of": None, "scorers": {}}
    if not isinstance(document, dict) or not isinstance(document.get("scorers"), dict):
        return {"verified_as_of": None, "scorers": {}}
    return document


def scorer_types_from_description(description: str) -> list[str]:
    """Parse scorer types out of a profile-map description string.

    "queue-scorer (2) + running-requests-size-scorer (1)" ->
    ["queue-scorer", "running-requests-size-scorer"]
    """
    types: list[str] = []
    for part in (description or "").split("+"):
        token = WEIGHT_SUFFIX.sub("", part.strip()).strip()
        if token and token != "no scorers":
            types.append(token)
    return types


def _containers(deployment: Optional[dict]) -> list[dict]:
    if not isinstance(deployment, dict):
        return []
    try:
        return deployment["spec"]["template"]["spec"]["containers"] or []
    except (KeyError, TypeError):
        return []


def _component_present(deployment: Optional[dict], pattern: str) -> bool:
    """A required component matches a container by name or image substring.

    Patterns name specific components (e.g. the exact predictor server
    images), so unrelated sidecars cannot satisfy a requirement.
    """
    if not pattern:
        return False
    needle = pattern.lower()
    for container in _containers(deployment):
        haystack = f"{container.get('name', '')} {container.get('image', '')}".lower()
        if needle in haystack:
            return True
    return False


def evaluate_scorer(entry: dict, endpoint: str, deployment: Optional[dict]) -> dict:
    """Curated caveats for one endpoint plus live requirement checks."""
    statuses: list[str] = []
    reasons: list[str] = []
    details: list[str] = []

    for caveat in entry.get("caveats") or []:
        if not isinstance(caveat, dict) or endpoint not in (caveat.get("endpoints") or []):
            continue
        statuses.append("warning")
        reason = str(caveat.get("reason") or "Check this scorer before interpreting results.")
        reasons.append(reason)
        details.append(str(caveat.get("details") or reason))

    for requirement in entry.get("requirements") or []:
        if not isinstance(requirement, dict):
            continue
        components = requirement.get("components") or []
        if deployment is None:
            names = ", ".join(
                str(component.get("name") or component.get("match") or "component")
                for component in components
            )
            statuses.append("warning")
            reasons.append("Predictor services have not been checked; verify readiness and training.")
            details.append(f"Prerequisites not verified: {names}")
            continue
        missing = [
            str(component.get("name") or component.get("match") or "component")
            for component in components
            if not _component_present(deployment, str(component.get("match") or ""))
        ]
        if missing:
            statuses.append("warning")
            reason = requirement.get("missing_reason") or "Check required components: " + ", ".join(missing)
            reasons.append(str(reason))
            details.append("Not found in the EPP pod: " + ", ".join(missing) + ". Components may run as separate services.")

    severity = "warning" if statuses else "ok"
    return {"severity": severity, "status": severity, "statuses": statuses, "reasons": reasons, "details": details}


def evaluate_types(scorer_types: list[str], endpoint: str, caveats: dict, deployment: Optional[dict]) -> dict:
    """Collect warnings by scorer so mixed profiles identify the affected component."""
    reasons: list[str] = []
    details: list[str] = []
    for scorer_type in scorer_types:
        entry = (caveats.get("scorers") or {}).get(scorer_type)
        if not isinstance(entry, dict):
            continue
        evaluation = evaluate_scorer(entry, endpoint, deployment)
        for reason in evaluation["reasons"]:
            value = f"{scorer_type} — {reason}"
            if value not in reasons:
                reasons.append(value)
        for detail in evaluation["details"]:
            value = f"{scorer_type} — {detail}"
            if value not in details:
                details.append(value)
    severity = "warning" if reasons else "ok"
    return {"severity": severity, "status": severity, "statuses": [severity] if reasons else [],
            "reasons": reasons, "details": details, "scorer_types": list(scorer_types)}


def evaluate_scorer_across_endpoints(entry: dict, endpoints: list[str], deployment: Optional[dict]) -> dict:
    """Builder view: short deduplicated warnings with endpoint-specific detail."""
    reasons: list[str] = []
    details: list[str] = []
    for endpoint in endpoints:
        evaluation = evaluate_scorer(entry, endpoint, deployment)
        for reason in evaluation["reasons"]:
            if reason not in reasons:
                reasons.append(reason)
        details.extend(f"{endpoint}: {detail}" for detail in evaluation["details"])
    return {"severity": "warning" if reasons else "ok", "reasons": reasons, "details": details}
