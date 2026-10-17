"""Evidence-qualified AHI estimates, screen comparisons and session-cohort rollups."""

import csv
import json
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from .decoder import write_csv
from .analysis import period_bounds

FIELDS = [
    "model_serial",
    "start_time",
    "end_time",
    "displayed_ahi",
    "displayed_usage_hours",
    "notes",
]


def rounded(value):
    return Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def load_observations(path):
    if path is None:
        return []
    with Path(path).open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not set(FIELDS).issubset(reader.fieldnames or []):
            raise ValueError("Observation CSV requires columns: " + ",".join(FIELDS))
        rows = list(reader)
    unique = {}
    for r in rows:
        if not any(r.values()):
            continue
        for field in ["start_time", "end_time"]:
            t = datetime.fromisoformat(r[field])
            if t.tzinfo is not None:
                raise ValueError("Use device wall-clock times without timezone offsets")
            r[field] = t.isoformat()
        if r["end_time"] <= r["start_time"]:
            raise ValueError("Observation end must follow start")
        for field in ["displayed_ahi", "displayed_usage_hours"]:
            if r[field] != "":
                v = Decimal(r[field])
                if not v.is_finite() or v < 0:
                    raise ValueError("Screen numbers must be finite and nonnegative")
        if r["displayed_ahi"] == "":
            raise ValueError("Every observation requires displayed_ahi")
        key = tuple(r[f] for f in FIELDS[:3])
        if key in unique and any(unique[key][f] != r[f] for f in FIELDS[3:5]):
            raise ValueError("Conflicting screen observations for the same session")
        unique[key] = {f: r[f] for f in FIELDS}
    return list(unique.values())


def build(root, observations):
    out = root / "output"
    report = json.loads((out / "analysis.json").read_text())
    checks = {v["session_id"]: v for v in report["validations"]}
    overlapping = {sid for pair in report["overlap_pairs"] for sid in pair}
    obs = {tuple(r[f] for f in FIELDS[:3]): r for r in observations}
    seen, rows = set(), []
    for s in report["sessions"]:
        c = checks[s["session_id"]]
        summary, words = c["summary"], c["summary"]["summary_words"]
        key = (summary["model_serial"], s["start_time"], s["end_time"])
        seen.add(key)
        reasons = []
        if not report["source_hashes_unchanged"]:
            reasons.append("source_changed")
        if c.get("summary_conflict"):
            reasons.append("summary_conflict")
        for name in [
            "minute_complete",
            "minute_count_matches_summary",
            "minute_start_matches",
            "summary_minutes_match_elapsed",
            "summary_total_equals_three_counters",
        ]:
            if not c.get(name):
                reasons.append(name)
        if not all(c.get("counter_summary_equalities", {}).get(str(i), False) for i in (5, 6, 7)):
            reasons.append("event_counter_summary_mismatch")
        if s["session_id"] in overlapping:
            reasons.append("overlapping_session")
        eligible = not reasons
        minutes = s["duration_minutes"]
        value = words["14"] * 60 / minutes if eligible else None
        o = obs.get(key)
        match = None
        usage_match = None
        if o and value is not None:
            match = rounded(value) == Decimal(o["displayed_ahi"])
            if o["displayed_usage_hours"]:
                usage_match = rounded(minutes / 60) == Decimal(o["displayed_usage_hours"])
        status = (
            "screen_match"
            if match and usage_match is not False
            else "screen_disagreement"
            if o and value is not None
            else "estimate_not_screen_checked"
            if eligible
            else "withheld_integrity_check"
        )
        rows.append(
            {
                "session_id": s["session_id"],
                "model_serial": key[0],
                "start_time": s["start_time"],
                "end_time": s["end_time"],
                "elapsed_minutes": minutes,
                "event_counter_total_raw": words["14"],
                "oa_counter_raw": words["16"],
                "ca_counter_raw": words["18"],
                "h_counter_raw": words["20"],
                "ahi_estimate": value,
                "ahi_estimate_display_1dp": str(rounded(value)) if value is not None else None,
                "formula": "sum of candidate OA+CA+H counters / elapsed session hours",
                "status": status,
                "failed_checks": ";".join(reasons),
                "displayed_ahi": o["displayed_ahi"] if o else None,
                "displayed_usage_hours": o["displayed_usage_hours"] if o else None,
                "ahi_matches_1dp": match,
                "usage_matches_1dp": usage_match,
                "observation_notes": o["notes"] if o else None,
                "alternative_rate_word42": words["14"] * 60 / words["42"] if words["42"] else None,
                "alternative_rate_nonzero_runs": sum(c.get("rising_edge_candidates", {}).values())
                * 60
                / minutes
                if eligible
                else None,
                "confidence": "estimated; matching a displayed total does not validate event subtypes or all firmware/modes",
            }
        )
    matched = sum(r["status"] == "screen_match" for r in rows)
    disagreements = sum(r["status"] == "screen_disagreement" for r in rows)
    # A mismatch remains visible and weakens the rule; do not silently tune to the display.
    for r in rows:
        r["rule_evidence"] = (
            f"{matched} matching session(s), {disagreements} disagreement(s) in this report; provisional rule"
        )
    write_csv(out / "ahi_sessions.csv", rows)
    unmatched = [r for k, r in obs.items() if k not in seen]
    (out / "unmatched_screen_observations.json").write_text(json.dumps(unmatched, indent=2))
    cohorts = {}
    for frequency in ("daily", "weekly", "monthly"):
        groups = {}
        for r in rows:
            a, b = period_bounds(datetime.fromisoformat(r["start_time"]), frequency)
            groups.setdefault((r["model_serial"], a, b), []).append(r)
        result = []
        for (serial, a, b), group in sorted(groups.items()):
            usable = all(r["ahi_estimate"] is not None for r in group)
            total = sum(r["event_counter_total_raw"] for r in group)
            minutes = sum(r["elapsed_minutes"] for r in group)
            result.append(
                {
                    "model_serial": serial,
                    "period_start": a.date().isoformat(),
                    "period_end_exclusive": b.date().isoformat(),
                    "sessions": len(group),
                    "sessions_with_estimates": sum(r["ahi_estimate"] is not None for r in group),
                    "elapsed_minutes_whole_sessions": minutes,
                    "counter_total": total if usable else None,
                    "ahi_estimate": total * 60 / minutes if usable else None,
                    "basis": "whole sessions assigned by start date; weighted counters/hours, not mean of AHIs",
                    "coverage": "available sessions only; unknown missing dates; not a midnight-split or manufacturer daily AHI",
                }
            )
        write_csv(out / f"ahi_{frequency}_session_cohorts.csv", result)
        cohorts[frequency] = result
    summary = {
        "rule": "candidate counter sum / elapsed hours",
        "screen_matches": matched,
        "screen_disagreements": disagreements,
        "unmatched_observations": len(unmatched),
        "status": "provisional; exact-session screen matches support but do not universally validate the formula",
        "sessions": rows,
        "cohorts": cohorts,
    }
    (out / "ahi_analysis.json").write_text(json.dumps(summary, indent=2, allow_nan=False))
    return summary
