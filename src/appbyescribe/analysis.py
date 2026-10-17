#!/usr/bin/env python3
"""Complete local byte audit, candidate statistics and coverage-aware period reports."""

from __future__ import annotations
import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from .decoder import run, write_csv, parse_records

METRICS = {
    "ipap_probable_cmH2O": "IPAP",
    "epap_probable_cmH2O": "EPAP",
    "pressure_support_probable_cmH2O": "Pressure support",
    "leak_probable_L_min": "Leak",
    "respiratory_rate_probable_breaths_min": "Respiratory rate",
    "tidal_volume_probable_mL": "Tidal volume",
    "minute_ventilation_probable_L_min": "Minute ventilation",
    "ie_ratio_probable_percent": "I/E ratio",
}


def csv_rows(path: Path):
    if not path.exists():
        return []
    with path.open() as f:
        return list(csv.DictReader(f))


def percentile(values, weights, q):
    """Weighted inverse empirical CDF (nearest rank for equal-duration bins)."""
    pairs = sorted(zip(values, weights))
    total = sum(w for _, w in pairs)
    if total <= 0:
        return None
    target = q * total
    accumulated = 0
    for value, weight in pairs:
        accumulated += weight
        if accumulated >= target - 1e-9:
            return value
    return pairs[-1][0]


def stats(values, weights):
    pairs = [(float(v), float(w)) for v, w in zip(values, weights) if w > 0]
    if not pairs:
        return dict(mean=None, minimum=None, median=None, p90=None, p95=None, maximum=None)
    v, w = zip(*pairs)
    return dict(
        mean=sum(a * b for a, b in pairs) / sum(w),
        minimum=min(v),
        median=percentile(v, w, 0.5),
        p90=percentile(v, w, 0.9),
        p95=percentile(v, w, 0.95),
        maximum=max(v),
    )


def period_bounds(t, frequency):
    start = t.replace(hour=0, minute=0, second=0, microsecond=0)
    if frequency == "daily":
        return start, start + timedelta(days=1)
    if frequency == "weekly":
        start -= timedelta(days=start.weekday())
        return start, start + timedelta(days=7)
    if frequency == "monthly":
        start = start.replace(day=1)
        return start, datetime(start.year + (start.month == 12), start.month % 12 + 1, 1)
    raise ValueError(frequency)


def union_seconds(intervals):
    merged = []
    for a, b in sorted(intervals):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return sum((b - a).total_seconds() for a, b in merged)


def period_rows(sessions, rows, frequency, suppress_metric_aggregates=False):
    periods = {}
    for s in sessions:
        cursor, end = datetime.fromisoformat(s["start_time"]), datetime.fromisoformat(s["end_time"])
        while cursor < end:
            start, stop = period_bounds(cursor, frequency)
            periods[start] = stop
            cursor = min(stop, end)
    result = []
    for a, b in sorted(periods.items()):
        affected = False
        if suppress_metric_aggregates:
            spans = [
                (
                    max(a, datetime.fromisoformat(s["start_time"])),
                    min(b, datetime.fromisoformat(s["end_time"])),
                )
                for s in sessions
            ]
            spans = sorted((x, y) for x, y in spans if x < y)
            latest = None
            for x, y in spans:
                if latest is not None and x < latest:
                    affected = True
                latest = max(latest, y) if latest else y
        clipped, ids, starts, dates = [], set(), 0, set()
        for s in sessions:
            start, end = (
                datetime.fromisoformat(s["start_time"]),
                datetime.fromisoformat(s["end_time"]),
            )
            if a <= start < b:
                starts += 1
            c, d = max(a, start), min(b, end)
            if c < d:
                ids.add(s["session_id"])
                clipped.append((c, d))
                day = c.replace(hour=0, minute=0, second=0)
                while day < d:
                    dates.add(day.date().isoformat())
                    day += timedelta(days=1)
        selected, weights = [], []
        for row in rows:
            start = datetime.fromisoformat(row["timestamp"])
            seconds = (min(b, start + timedelta(minutes=1)) - max(a, start)).total_seconds()
            if seconds > 0 and row["confidence"].startswith("probable"):
                selected.append(row)
                weights.append(seconds)
        item = {
            "period_type": frequency,
            "period_start": a.date().isoformat(),
            "period_end_exclusive": b.date().isoformat(),
            "calendar_days_in_period": (b - a).days,
            "dates_with_records": len(dates),
            "observed_dates": ";".join(sorted(dates)),
            "session_ids": ";".join(sorted(ids)),
            "unique_sessions_touching_period": len(ids),
            "sessions_starting_in_period": starts,
            "recorded_elapsed_seconds": union_seconds(clipped),
            "recorded_elapsed_hours": union_seconds(clipped) / 3600,
            "minute_data_weight_seconds": None if affected else sum(weights),
            "coverage_status": "partial export; full-period recording completeness unknown",
            "missing_dates_policy": "unknown, never treated as zero use; no adherence denominator",
            "time_basis": "device wall clock; calendar boundaries are analytical, not verified manufacturer therapy-day",
            "ahi": None,
            "metric_aggregation": "suppressed due to overlapping sessions"
            if affected
            else "duration-weighted overlapping minute bins; probable physical mappings",
        }
        for name in METRICS:
            metric = stats([r[name] for r in selected], weights) if not affected else stats([], [])
            item.update({name + "_" + k: v for k, v in metric.items()})
        result.append(item)
    return result


def enrich(root: Path):
    output = root / "output"
    report = json.loads((output / "analysis.json").read_text())
    raw_files = json.loads((root / "raw/source_files.json").read_text())
    source = {x["source_file"]: bytes.fromhex(x["raw_hex"]) for x in raw_files}
    integrity = [
        {
            "source_file": r["source_file"],
            "byte_length": len(source[r["source_file"]]),
            "sha256_roundtrip_matches": hashlib.sha256(source[r["source_file"]]).hexdigest()
            == r["sha256"],
        }
        for r in raw_files
    ]
    if not all(r["sha256_roundtrip_matches"] for r in integrity):
        raise ValueError("Raw archive SHA-256 integrity failure")
    minutes = csv_rows(output / "timeseries.csv")
    raw_minutes = csv_rows(output / "raw_minute_records.csv")
    statistics, hypotheses = [], []
    for s in report["sessions"]:
        sid = s["session_id"]
        valid = [
            r for r in minutes if r["session_id"] == sid and r["confidence"].startswith("probable")
        ]
        for metric, label in METRICS.items():
            statistics.append(
                {
                    "session_id": sid,
                    "metric": metric,
                    "label": label,
                    "records_used": len(valid),
                    "sampled_seconds": 60 * len(valid),
                    **stats([r[metric] for r in valid], [60] * len(valid)),
                    "percentile_method": "weighted inverse empirical CDF; equal 60s bins = nearest rank",
                    "confidence": "derived from probable channels; not validated device display algorithm",
                }
            )
        checks = next(v for v in report["validations"] if v["session_id"] == sid)
        words = checks["summary"]["summary_words"]
        elapsed = s["duration_minutes"]
        alt = words["42"]
        runs = checks.get("rising_edge_candidates", {})
        has_full = (
            checks.get("minute_complete", False)
            and checks.get("minute_count_matches_summary", False)
            and checks.get("minute_start_matches", False)
            and checks.get("summary_minutes_match_elapsed", False)
        )
        total = words["14"]
        hypotheses.append(
            {
                "session_id": sid,
                "summary_total_raw": total,
                "candidate_oa_counter_sum": words["16"],
                "candidate_ca_counter_sum": words["18"],
                "candidate_h_counter_sum": words["20"],
                "unknown_byte8_sum": words["22"],
                "unknown_byte9_sum": words["24"],
                "elapsed_minutes": elapsed,
                "unexplained_duration_word42": alt,
                "minute_record_set_complete": has_full,
                "nonzero_run_total": sum(runs.values()) if has_full else None,
                "counter_sum_per_elapsed_hour_hypothesis": total * 60 / elapsed
                if elapsed
                else None,
                "counter_sum_per_word42_hour_hypothesis": total * 60 / alt if alt else None,
                "run_count_per_elapsed_hour_hypothesis": sum(runs.values()) * 60 / elapsed
                if has_full and elapsed
                else None,
                "accepted_ahi": None,
                "confidence": "unvalidated event-rate hypotheses only; raw counters not proven individual events",
            }
        )
    write_csv(output / "session_statistics.csv", statistics)
    write_csv(output / "event_rate_hypotheses.csv", hypotheses)

    # Expand every raw minute counter, including nonzero fields with unknown meanings.
    counter_rows = []
    for row in raw_minutes:
        for off in range(4, 12):
            counter_rows.append(
                {
                    "session_id": row["session_id"],
                    "source_file": row["source_file"],
                    "source_offset": int(row["source_offset"]) + off,
                    "minute_index": row["record_index"],
                    "byte_offset_in_record": off,
                    "value_raw": int(row[f"byte_{off}"]),
                    "candidate_label": {5: "OA", 6: "CA", 7: "H"}.get(off, "unknown"),
                    "interpretation": "raw observation; candidate labels unvalidated",
                }
            )
    write_csv(output / "all_minute_counters.csv", counter_rows)
    profiles = []
    for off in range(22):
        values = [int(r[f"byte_{off}"]) for r in raw_minutes]
        if values:
            profiles.append(
                {
                    "byte_offset": off,
                    "observations": len(values),
                    "zero_count": values.count(0),
                    "nonzero_count": sum(v != 0 for v in values),
                    "minimum_raw": min(values),
                    "maximum_raw": max(values),
                    "sum_raw": sum(values),
                    "value_histogram_json": json.dumps(dict(sorted(Counter(values).items()))),
                }
            )
    write_csv(output / "minute_byte_profiles.csv", profiles)

    # Audit all source regions without dropping unknown bytes or reinterpreting them.
    segments, summary_bytes, history_bytes, blocks = [], [], [], []
    wave_count, trusted_blocks = 0, 0
    wave_fields = [
        "source_file",
        "block_index",
        "sample_in_block",
        "channel_a_source_offset",
        "channel_b_source_offset",
        "channel_a_raw",
        "channel_b_raw",
        "elapsed_seconds_candidate_10Hz",
        "time_confidence",
    ]
    # Stream high-frequency samples: a month of detail must not create millions of dictionaries in RAM.
    wave_handle = (output / "waveform_samples.csv").open("w", newline="")
    wave_writer = csv.DictWriter(wave_handle, fieldnames=wave_fields)
    wave_writer.writeheader()
    recognized = {v["summary_source"] for v in report["validations"]}
    recognized.update(r["source_file"] for r in raw_minutes)
    recognized.update(
        r["source_file"] for r in json.loads((output / "raw_detail_blocks.json").read_text())
    )
    recognized.update(
        i["source_file"]
        for i in report["index_checks"]
        if i["exact_multiset_match_to_session_bases"]
    )
    flawed = {d["source_file"] for d in report["diagnostics"] if "source_file" in d}

    def segment(rel, start, end, label, confidence):
        b = source[rel][start:end]
        if b:
            segments.append(
                {
                    "source_file": rel,
                    "start_offset": start,
                    "end_offset_exclusive": end,
                    "length": len(b),
                    "label": label,
                    "semantic_confidence": confidence
                    if rel in recognized and rel not in flawed
                    else "unvalidated_layout_or_metadata",
                    "sha256": hashlib.sha256(b).hexdigest(),
                }
            )

    for rel, b in source.items():
        lower = rel.lower()
        if lower.endswith("s.bys") or Path(rel).name.lower() == "summer.bys":
            starts = (
                list(range(0, len(b) // 62 * 62, 62))
                if Path(rel).name.lower() == "summer.bys"
                else ([0] if len(b) >= 62 else [])
            )
            if not starts:
                segment(rel, 0, len(b), "unparsed_summary", "unknown")
                continue
            for start in starts:
                for off in range(62):
                    summary_bytes.append(
                        {
                            "source_file": rel,
                            "base_offset": start,
                            "byte_offset": off,
                            "source_offset": start + off,
                            "value_raw": b[start + off],
                        }
                    )
                for a, z, label, confidence in [
                    (0, 2, "signature", "confirmed_structure"),
                    (2, 14, "calendar_times", "confirmed_structure"),
                    (14, 22, "event_counter_summaries", "probable_semantics"),
                    (22, 32, "other_raw_words", "unknown_semantics"),
                    (32, 36, "mean_pressure_candidates", "probable_semantics"),
                    (36, 40, "unknown_words", "unknown_semantics"),
                    (40, 42, "minute_count", "confirmed_structure"),
                    (42, 44, "duration_like_word", "unknown_semantics"),
                    (44, 60, "model_serial", "confirmed_structure"),
                    (60, 62, "history_count", "confirmed_structure"),
                ]:
                    segment(rel, start + a, start + z, label, confidence)
            tail_start = starts[-1] + 62
            if Path(rel).name.lower() == "summer.bys":
                segment(rel, tail_start, len(b), "index_tail", "unknown")
            else:
                cursor = 62
                while cursor + 36 <= len(b):
                    for off in range(36):
                        history_bytes.append(
                            {
                                "source_file": rel,
                                "block_offset": cursor,
                                "byte_offset": off,
                                "source_offset": cursor + off,
                                "value_raw": b[cursor + off],
                            }
                        )
                    for a, z, label, confidence in [
                        (0, 6, "history_time", "confirmed_structure"),
                        (6, 7, "mode_candidate", "probable_semantics"),
                        (7, 10, "unknown_settings", "unknown_semantics"),
                        (10, 14, "pressure_limit_candidates", "probable_semantics"),
                        (14, 21, "unknown_settings", "unknown_semantics"),
                        (21, 22, "pressure_support_candidate", "probable_semantics"),
                        (22, 35, "unknown_settings", "unknown_semantics"),
                        (35, 36, "terminator", "confirmed_structure"),
                    ]:
                        segment(rel, cursor + a, cursor + z, label, confidence)
                    cursor += 36
                segment(rel, cursor, len(b), "history_tail", "unknown")
        elif lower.endswith("m.bys") or lower.endswith("d.bys"):
            is_minute = lower.endswith("m.bys")
            size = 22 if is_minute else 1201
            accepted_indices = set()
            trusted_time = False
            if not is_minute:
                try:
                    stamp, count, accepted, issues = parse_records(b, size)
                    accepted_indices = {i for i, _ in accepted}
                    linked = [
                        v
                        for v in report["validations"]
                        if v["summary_source"][:-5].lower() + "d.bys" == lower
                    ]
                    trusted_time = bool(
                        len(linked) == 1
                        and not issues
                        and linked[0].get("detail_start_matches")
                        and linked[0].get("detail_count_matches_summary")
                        and linked[0].get("summary_minutes_match_elapsed")
                    )
                except ValueError:
                    pass
            segment(rel, 0, min(8, len(b)), "calendar_and_count_header", "confirmed_structure")
            cursor = 8
            while cursor + size <= len(b):
                if is_minute:
                    for a, z, label, confidence in [
                        (0, 4, "pressure_candidates", "probable_semantics"),
                        (4, 5, "unknown_byte4", "unknown_semantics"),
                        (5, 8, "event_counter_candidates", "probable_semantics"),
                        (8, 12, "unknown_counters", "unknown_semantics"),
                        (12, 19, "leak_respiratory_candidates", "probable_semantics"),
                        (19, 21, "oximetry_slots_unavailable", "unknown_semantics"),
                        (21, 22, "terminator", "confirmed_structure"),
                    ]:
                        segment(rel, cursor + a, cursor + z, label, confidence)
                else:
                    segment(rel, cursor, cursor + 600, "raw_channel_a", "unknown_semantics")
                    segment(rel, cursor + 600, cursor + 1200, "raw_channel_b", "unknown_semantics")
                    segment(rel, cursor + 1200, cursor + 1201, "terminator", "confirmed_structure")
                    index = (cursor - 8) // size
                    if index not in accepted_indices:
                        cursor += size
                        continue
                    a, bchan = list(b[cursor : cursor + 600]), list(b[cursor + 600 : cursor + 1200])
                    blocks.append(
                        {
                            "source_file": rel,
                            "block_index": index,
                            "source_offset": cursor,
                            "channel_a_min_raw": min(a),
                            "channel_a_max_raw": max(a),
                            "channel_a_mean_raw": sum(a) / 600,
                            "channel_b_min_raw": min(bchan),
                            "channel_b_max_raw": max(bchan),
                            "channel_b_mean_raw": sum(bchan) / 600,
                            "terminator_raw": b[cursor + 1200],
                            "session_time_validated": trusted_time,
                        }
                    )
                    trusted_blocks += int(trusted_time)
                    for j in range(600):
                        wave_writer.writerow(
                            {
                                "source_file": rel,
                                "block_index": index,
                                "sample_in_block": j,
                                "channel_a_source_offset": cursor + j,
                                "channel_b_source_offset": cursor + 600 + j,
                                "channel_a_raw": a[j],
                                "channel_b_raw": bchan[j],
                                "elapsed_seconds_candidate_10Hz": index * 60 + j / 10
                                if trusted_time
                                else None,
                                "time_confidence": "tentative 10Hz; physical gain/baseline unvalidated"
                                if trusted_time
                                else "structural samples only; session timing unvalidated",
                            }
                        )
                        wave_count += 1
                cursor += size
            segment(rel, min(cursor, len(b)), len(b), "unparsed_tail", "unknown")
        else:
            segment(rel, 0, len(b), "nontherapy_or_unknown_file", "unknown")
    coverage = []
    for rel, b in source.items():
        pieces = sorted(
            (r for r in segments if r["source_file"] == rel), key=lambda r: r["start_offset"]
        )
        cursor = 0
        for p in pieces:
            if p["start_offset"] != cursor:
                raise ValueError(f"Byte ledger overlap/gap: {rel} at {cursor}")
            cursor = p["end_offset_exclusive"]
        if cursor != len(b):
            raise ValueError(f"Byte ledger incomplete: {rel}")
        c = Counter()
        for p in pieces:
            c[p["semantic_confidence"]] += p["length"]
        coverage.append(
            {
                "source_file": rel,
                "source_bytes": len(b),
                "accounted_bytes": cursor,
                "unaccounted_bytes": len(b) - cursor,
                "raw_roundtrip_exact": True,
                "semantic_categories": dict(c),
            }
        )
    wave_handle.close()
    for name, rows in [
        ("byte_segments.csv", segments),
        ("summary_raw_bytes.csv", summary_bytes),
        ("history_raw_bytes.csv", history_bytes),
        ("waveform_block_statistics.csv", blocks),
    ]:
        write_csv(output / name, rows)
    totals = Counter()
    for c in coverage:
        if c["source_file"].lower().endswith(".bys"):
            totals.update(c["semantic_categories"])
    coverage_report = {
        "files": coverage,
        "input_roundtrip": integrity,
        "bys_bytes": sum(
            c["source_bytes"] for c in coverage if c["source_file"].lower().endswith(".bys")
        ),
        "semantic_byte_totals": dict(totals),
        "interpretation": "Raw accounting is complete; byte categories are hypotheses, not percentage of medical knowledge decoded.",
    }
    (output / "byte_coverage.json").write_text(json.dumps(coverage_report, indent=2))
    periods = {}
    for frequency in ("daily", "weekly", "monthly"):
        periods[frequency] = period_rows(
            report["sessions"], minutes, frequency, bool(report["overlap_pairs"])
        )
        write_csv(output / f"{frequency}_coverage_summary.csv", periods[frequency])
    review = {
        "base_parser_version": report["parser_version"],
        "coverage": coverage_report,
        "session_statistics": statistics,
        "event_rate_hypotheses": hypotheses,
        "periods": periods,
        "high_frequency_sample_pairs": wave_count,
        "structural_detail_blocks": len(blocks),
        "waveform_coverage_minutes": trusted_blocks,
        "minute_coverage_minutes": len(minutes),
        "photo_policy": "Screen observations are joined by serial and exact session start/end in ahi_sessions.csv; no association from numerical resemblance alone.",
        "reporting_policy": "Observed intervals only. Daily/weekly/monthly tables are partial-export summaries; no unobserved day is zero use.",
    }
    (output / "review_analysis.json").write_text(json.dumps(review, indent=2, allow_nan=False))
    return review


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("input", type=Path)
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()
    run(args.input, args.output)
    result = enrich(args.output)
    print(
        json.dumps(
            {
                "bys_bytes_accounted": result["coverage"]["bys_bytes"],
                "semantic_categories": result["coverage"]["semantic_byte_totals"],
                "waveform_sample_pairs": result["high_frequency_sample_pairs"],
            },
            indent=2,
        )
    )
