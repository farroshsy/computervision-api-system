"""Document-vs-claim verification engine.

Implements the dispatch/onboarding decision logic: the caller states who
the driver / which truck SHOULD be (the claim), we compare against what
the document photo actually says, and return a three-way decision:

- ``match``        every provided claim matches and no blocking fact found
- ``no_match``     a readable value CONTRADICTS the claim, or the document
                   itself is invalid for dispatch (expired, wrong class)
- ``needs_review`` we could not read enough to decide — never punish the
                   driver for a bad photo; route to a human / retake

Field rules (per design session, see docs/LOGBOOK.md):
- exact fields   : nik, sim_number, plate, nomor_rangka (normalized)
- fuzzy fields   : names (token overlap; OCR mangles characters)
- doc-intrinsic  : SIM/KIR expiry vs today, SIM class vs required_classes —
                   these need no claim, the document alone decides
- STNK owner is NEVER scored against the driver (fleet trucks belong to
  PT companies).
"""
import re
from datetime import date, datetime
from typing import Dict, List, Optional

NAME_SIMILARITY_THRESHOLD = 0.6


def _norm_exact(value: Optional[str]) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def _norm_name(value: Optional[str]) -> str:
    return re.sub(r"[^A-Z ]", "", (value or "").upper()).strip()


def name_similarity(a: Optional[str], b: Optional[str]) -> float:
    """Token-overlap similarity, plus a no-spaces fallback because OCR
    frequently glues words ("JAKASALMAN")."""
    ta, tb = set(_norm_name(a).split()), set(_norm_name(b).split())
    if ta and tb:
        jac = len(ta & tb) / len(ta | tb)
        if jac > 0:
            return jac
    ga, gb = _norm_exact(a), _norm_exact(b)
    if ga and gb and (ga in gb or gb in ga):
        return 1.0
    return 0.0


def _parse_date(value: Optional[str]) -> Optional[date]:
    s = (value or "").strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _check(field: str, extracted: Optional[str], claimed: Optional[str], fuzzy: bool = False) -> Dict:
    """Compare one claimed field. Status: matched / mismatched / unreadable."""
    if not extracted:
        return {"field": field, "claimed": claimed, "extracted": None, "status": "unreadable"}
    if fuzzy:
        ok = name_similarity(extracted, claimed) >= NAME_SIMILARITY_THRESHOLD
    else:
        ok = _norm_exact(extracted) == _norm_exact(claimed)
    return {"field": field, "claimed": claimed, "extracted": extracted,
            "status": "matched" if ok else "mismatched"}


def verify_document(
    doc_type: str,
    values: Dict[str, Optional[str]],
    claims: Dict[str, Optional[str]],
    required_classes: Optional[List[str]] = None,
    today: Optional[date] = None,
) -> Dict:
    """Verify extracted document ``values`` against caller ``claims``.

    values: plain field->string dict (unwrapped parser output).
    claims: any of nik, name, dob, sim_number, plate, nomor_rangka.
    Returns {decision, checks, reasons}.
    """
    doc_type = (doc_type or "").upper()
    today = today or date.today()
    checks: List[Dict] = []
    reasons: List[str] = []

    def val(*keys: str) -> Optional[str]:
        for k in keys:
            v = values.get(k)
            if v:
                return str(v)
        return None

    # --- claim comparisons per document type ---
    if doc_type == "KTP":
        if claims.get("nik"):
            checks.append(_check("nik", val("nik"), claims["nik"]))
        if claims.get("name"):
            checks.append(_check("name", val("nama", "name"), claims["name"], fuzzy=True))
        if claims.get("dob"):
            ex = _parse_date(val("tanggal_lahir", "dob"))
            cl = _parse_date(claims["dob"])
            checks.append({
                "field": "dob", "claimed": claims["dob"],
                "extracted": ex.isoformat() if ex else None,
                "status": "unreadable" if ex is None else ("matched" if ex == cl else "mismatched"),
            })
    elif doc_type == "SIM":
        if claims.get("sim_number"):
            checks.append(_check("sim_number", val("sim_number", "id_number"), claims["sim_number"]))
        if claims.get("name"):
            checks.append(_check("name", val("name", "nama"), claims["name"], fuzzy=True))
    elif doc_type == "STNK":
        if claims.get("plate"):
            checks.append(_check("plate", val("nomor_polisi", "plate_number"), claims["plate"]))
        if claims.get("nomor_rangka"):
            checks.append(_check("nomor_rangka", val("nomor_rangka", "vin_chassis"), claims["nomor_rangka"]))
        # STNK owner deliberately NOT scored (fleet PT ownership)
    elif doc_type == "KIR":
        if claims.get("plate"):
            checks.append(_check("plate", val("vehicle_id"), claims["plate"]))
        if claims.get("nomor_rangka"):
            checks.append(_check("nomor_rangka", val("nomor_rangka"), claims["nomor_rangka"]))

    # --- doc-intrinsic checks (no claim needed) ---
    if doc_type == "SIM":
        exp = _parse_date(val("expiry_date", "valid_to"))
        if exp is None:
            reasons.append("sim_expiry_unreadable")
        elif exp < today:
            reasons.append("sim_expired")
        if required_classes:
            cls = val("class")
            allowed = {c.strip().upper() for c in required_classes if c.strip()}
            if cls is None:
                reasons.append("sim_class_unreadable")
            elif cls.upper() not in allowed:
                reasons.append("sim_class_not_allowed")
    elif doc_type == "KIR":
        exp = _parse_date(val("valid_until", "masa_berlaku"))
        if exp is None:
            reasons.append("kir_expiry_unreadable")
        elif exp < today:
            reasons.append("kir_expired")

    # --- decision ---
    blocking = {"sim_expired", "kir_expired", "sim_class_not_allowed"}
    unreadable_reasons = {r for r in reasons if r.endswith("_unreadable")}
    if any(c["status"] == "mismatched" for c in checks) or (set(reasons) & blocking):
        decision = "no_match"
    elif any(c["status"] == "unreadable" for c in checks) or unreadable_reasons:
        decision = "needs_review"
    elif not checks and not reasons:
        decision = "needs_review"
        reasons.append("nothing_to_verify")
    else:
        decision = "match"

    return {"decision": decision, "checks": checks, "reasons": reasons}


def aggregate_trip(doc_results: Dict[str, Dict]) -> Dict:
    """Combine per-document verifications into one dispatch answer.

    GO      every provided document decided 'match'
    NO_GO   any document decided 'no_match'
    REVIEW  otherwise (something unreadable / missing)
    """
    decisions = {name: r["decision"] for name, r in doc_results.items()}
    if any(d == "no_match" for d in decisions.values()):
        overall = "NO_GO"
    elif decisions and all(d == "match" for d in decisions.values()):
        overall = "GO"
    else:
        overall = "REVIEW"
    return {"decision": overall, "documents": decisions}
