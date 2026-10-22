"""Curated scorer caveats plus live prerequisite checks.

Two sources feed profile operability:

  * caveats -- curated, endpoint-conditional knowledge from
    scripts/profile_caveats.json (the team-maintained source of truth).
  * requirements -- live-checkable preconditions declared in the same file
    (e.g. the latency predictor sidecars), evaluated against the EPP
    Deployment. When the cluster cannot be read, requirements report
    "unknown" -- never "missing" -- so an unavailable cluster is never
    mistaken for a broken one.

Severity ranking (worst first): bad (unsupported / not-useful / broken),
warn (limited), unknown (prerequisites not verified), ok.
"""

import json
import re
from pathlib import Path
from typing import Optional

from paths import SCRIPTS_DIR

CAVEATS_FILE = SCRIPTS_DIR / "profile_caveats.json"

SEVERITY_ORDER = {"bad": 0, "warn": 1, "unknown": 2, "ok": 3}
STATUS_SEVERITY = {
    "unsupported": "bad",
    "not-useful": "bad",
    "broken": "bad",
    "limited": "warn",
    "unknown": "unknown",
    "ok": "ok",
}

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


def _worst(severities: list[str]) -> str:
    if not severities:
        return "ok"
    return min(severities, key=lambda severity: SEVERITY_ORDER.get(severity, 3))


def evaluate_scorer(entry: dict, endpoint: str, deployment: Optional[dict]) -> dict:
    """Curated caveats for one endpoint plus live requirement checks."""
    statuses: list[str] = []
    reasons: list[str] = []

    for caveat in entry.get("caveats") or []:
        if not isinstance(caveat, dict) or endpoint not in (caveat.get("endpoints") or []):
            continue
        status = str(caveat.get("status") or "limited")
        statuses.append(status)
        reasons.append(str(caveat.get("reason") or status))

    for requirement in entry.get("requirements") or []:
        if not isinstance(requirement, dict):
            continue
        components = requirement.get("components") or []
        if deployment is None:
            names = ", ".join(
                str(component.get("name") or component.get("match") or "component")
                for component in components
            )
            statuses.append("unknown")
            reasons.append(f"prerequisites not verified (cluster state unavailable): {names}")
            continue
        missing = [
            str(component.get("name") or component.get("match") or "component")
            for component in components
            if not _component_present(deployment, str(component.get("match") or ""))
        ]
        if missing:
            statuses.append("broken")
            reasons.append("missing required components: " + ", ".join(missing))

    severity = _worst([STATUS_SEVERITY.get(status, "ok") for status in statuses])
    status_word = next(
        (status for status in statuses if STATUS_SEVERITY.get(status) == severity), "ok"
    )
    return {"severity": severity, "status": status_word, "statuses": statuses, "reasons": reasons}


def evaluate_types(scorer_types: list[str], endpoint: str, caveats: dict, deployment: Optional[dict]) -> dict:
    """Evaluate operability for a profile defined by the given scorer types."""
    statuses: list[str] = []
    reasons: list[str] = []
    for scorer_type in scorer_types:
        entry = (caveats.get("scorers") or {}).get(scorer_type)
        if not isinstance(entry, dict):
            continue
        evaluation = evaluate_scorer(entry, endpoint, deployment)
        for status, reason in zip(evaluation["statuses"], evaluation["reasons"]):
            statuses.append(f"{scorer_type}: {status}")
            reasons.append(f"{scorer_type} — {reason}")
    severity = _worst([STATUS_SEVERITY.get(status.split(": ")[-1], "ok") for status in statuses])
    status_word = next(
        (status for status in statuses if STATUS_SEVERITY.get(status.split(": ")[-1]) == severity),
        "ok",
    )
    return {
        "severity": severity,
        "status": status_word.split(": ")[-1] if status_word != "ok" else "ok",
        "statuses": statuses,
        "reasons": reasons,
        "scorer_types": list(scorer_types),
    }


def evaluate_scorer_across_endpoints(entry: dict, endpoints: list[str], deployment: Optional[dict]) -> dict:
    """Endpoint-agnostic view for the Builder: worst severity, endpoint-prefixed reasons."""
    reasons: list[str] = []
    severities: list[str] = []
    for endpoint in endpoints:
        evaluation = evaluate_scorer(entry, endpoint, deployment)
        severities.append(evaluation["severity"])
        reasons.extend(f"{endpoint}: {reason}" for reason in evaluation["reasons"])
    return {"severity": _worst(severities), "reasons": reasons}
