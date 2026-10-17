#!/usr/bin/env python3
"""Read-only, evidence-conservative ET525A BYS decoder. Python >=3.10; stdlib only.

Confirmed structure is exported separately from probable physiological mappings.
No network access, device writes, settings changes, or automatic AHI diagnosis.
See docs/FORMAT.md for the evidence and limits.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import stat
import struct
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import __version__

VERSION = __version__


class FormatError(ValueError):
    pass


def u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def device_time(data: bytes) -> datetime:
    if len(data) != 6 or data[0] > 99:
        raise FormatError("expected six numeric calendar bytes with year 00..99")
    try:
        return datetime(2000 + data[0], *data[1:])
    except ValueError as exc:
        raise FormatError(f"invalid calendar bytes: {data.hex()}") from exc


def parse_summary_base(data: bytes) -> dict:
    if len(data) < 62 or data[:2] != b"\x31\x02":
        raise FormatError("unknown summary layout: requires 31 02 and 62-byte base")
    model = data[44:60].decode("ascii", errors="replace")
    if not re.fullmatch(r"ET525A-[A-Za-z0-9]{9}", model):
        raise FormatError("unsupported model identifier (decoder restricted to ET525A)")
    start, end = device_time(data[2:8]), device_time(data[8:14])
    if end <= start:
        raise FormatError("session end must be later than start")
    return {
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
        "duration_minutes": (end - start).total_seconds() / 60,
        "model_serial": model,
        "record_count": u16(data, 40),
        "duration_field_42_raw": u16(data, 42),
        "summary_words": {str(i): u16(data, i) for i in range(14, 44, 2)},
        "settings": [],
    }


def parse_summary(data: bytes) -> dict:
    result = parse_summary_base(data)
    start, end = (
        datetime.fromisoformat(result["start_time"]),
        datetime.fromisoformat(result["end_time"]),
    )
    count = u16(data, 60)
    if len(data) != 62 + count * 36:
        raise FormatError("settings count/length mismatch: expected 62 + count * 36")
    settings = []
    for i in range(count):
        offset = 62 + i * 36
        b = data[offset : offset + 36]
        if b[-1] != 0xA5:
            raise FormatError(f"settings record {i} missing A5 terminator")
        stamp = device_time(b[:6])
        if not start <= stamp <= end:
            raise FormatError(f"settings timestamp {i} outside session")
        settings.append(
            {
                "source_offset": offset,
                "device_time": stamp.isoformat(),
                "raw_hex": b.hex(),
                "mode_code_raw": b[6],
                "max_ipap_candidate_cmH2O": int.from_bytes(b[10:12], "big") / 10,
                "min_epap_candidate_cmH2O": int.from_bytes(b[12:14], "big") / 10,
                "pressure_support_candidate_cmH2O": b[21] / 10,
                "confidence": "probable (Format E analogy); other settings unknown",
            }
        )
    if settings and settings[0]["device_time"] != start.isoformat():
        raise FormatError("first settings timestamp does not match session start")
    if [s["device_time"] for s in settings] != sorted(s["device_time"] for s in settings):
        raise FormatError("settings timestamps are not chronological")
    result["settings"] = settings
    return result


def session_row(summary: dict, sid: str, rel: str, offset: int = 0) -> dict:
    return {
        "session_id": sid,
        "start_time": summary["start_time"],
        "end_time": summary["end_time"],
        "duration_minutes": summary["duration_minutes"],
        "ahi": None,
        "obstructive_apnea_count": None,
        "central_apnea_count": None,
        "hypopnea_count": None,
        "ipap_mean": None,
        "epap_mean": None,
        "leak_mean": None,
        "source_file": rel,
        "source_offset": offset,
        "time_basis": "device wall clock; timezone unknown",
        "duration_basis": "end minus start; not verified mask-on or sleep time",
        "confidence": "confirmed structure; device clock accuracy unverified",
    }


def parse_records(
    data: bytes, size: int
) -> tuple[datetime, int, list[tuple[int, bytes]], list[dict]]:
    """Keep record positions after corruption; report every invalid/trailing region."""
    if len(data) < 8:
        raise FormatError("truncated 8-byte record-file header")
    start, count = device_time(data[:6]), u16(data, 6)
    available, remainder = divmod(len(data) - 8, size)
    issues, records = [], []
    if available != count or remainder:
        issues.append(
            {
                "code": "length_count_mismatch",
                "declared": count,
                "complete_records": available,
                "trailing_bytes": remainder,
            }
        )
    for i in range(min(count, available)):
        offset = 8 + i * size
        b = data[offset : offset + size]
        if b[-1] != 0xFE:
            issues.append(
                {
                    "code": "invalid_record_marker",
                    "index": i,
                    "source_offset": offset,
                    "raw_hex": b.hex(),
                }
            )
        else:
            records.append((i, b))
    if available < count:
        issues.append(
            {"code": "missing_records", "first_index": available, "count": count - available}
        )
    tail_offset = 8 + min(count, available) * size
    if tail_offset < len(data):
        issues.append(
            {
                "code": "unparsed_tail",
                "source_offset": tail_offset,
                "length": len(data) - tail_offset,
                "raw_hex": data[tail_offset:].hex(),
            }
        )
    return start, count, records, issues


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return  # No fabricated or empty dataset for unsupported measurements.
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def scan_source_tree(source: Path, capture: bool) -> tuple[dict, list[dict]]:
    """Read through directory descriptors; never follow a record or parent symlink.

    The final scan hashes incrementally without retaining another copy of the input.
    Changes during either scan remain failures even if later restored.
    """
    entries, issues = {}, []
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW

    def identity(st):
        return (st.st_dev, st.st_ino, stat.S_IFMT(st.st_mode))

    def fingerprint(st):
        return (*identity(st), st.st_size, st.st_mtime_ns, st.st_ctime_ns)

    def walk(fd, prefix):
        try:
            names = sorted(os.listdir(fd))
        except OSError as exc:
            issues.append(
                {"source_file": prefix or ".", "code": "source_scan_failed", "reason": str(exc)}
            )
            return
        for name in names:
            rel = f"{prefix}/{name}" if prefix else name
            child = None
            try:
                before = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if stat.S_ISLNK(before.st_mode):
                    entries[rel] = {
                        "kind": "symlink",
                        "identity": identity(before),
                        "target": os.readlink(name, dir_fd=fd),
                    }
                elif stat.S_ISDIR(before.st_mode):
                    child = os.open(name, directory_flags, dir_fd=fd)
                    opened = os.fstat(child)
                    entries[rel] = {"kind": "directory", "identity": identity(opened)}
                    if identity(before) != identity(opened):
                        issues.append({"source_file": rel, "code": "source_changed_during_read"})
                    walk(child, rel)
                    after = os.stat(name, dir_fd=fd, follow_symlinks=False)
                    if identity(opened) != identity(after):
                        issues.append({"source_file": rel, "code": "source_changed_during_read"})
                elif stat.S_ISREG(before.st_mode):
                    # NONBLOCK avoids hanging if a regular file becomes a FIFO before open.
                    child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                    opened = os.fstat(child)
                    if not stat.S_ISREG(opened.st_mode):
                        raise OSError("source entry is no longer a regular file")
                    digest, chunks, length = hashlib.sha256(), [], 0
                    while True:
                        block = os.read(child, 1024 * 1024)
                        if not block:
                            break
                        digest.update(block)
                        length += len(block)
                        if capture:
                            chunks.append(block)
                    closed = os.fstat(child)
                    entries[rel] = {
                        "kind": "file",
                        "fingerprint": fingerprint(closed),
                        "size": length,
                        "sha256": digest.hexdigest(),
                        "mtime_utc": datetime.fromtimestamp(
                            closed.st_mtime, timezone.utc
                        ).isoformat(),
                    }
                    if capture:
                        entries[rel]["data"] = b"".join(chunks)
                    # Retain completed reads even if the directory entry then vanishes.
                    named = os.stat(name, dir_fd=fd, follow_symlinks=False)
                    stable = (
                        fingerprint(before)
                        == fingerprint(opened)
                        == fingerprint(closed)
                        == fingerprint(named)
                    )
                    if not stable:
                        issues.append({"source_file": rel, "code": "source_changed_during_read"})
                else:
                    entries[rel] = {"kind": "special", "identity": identity(before)}
            except OSError as exc:
                issues.append(
                    {"source_file": rel, "code": "source_read_failed", "reason": str(exc)}
                )
            finally:
                if child is not None:
                    os.close(child)

    fd = None
    try:
        fd = os.open(source, directory_flags)
        entries["."] = {"kind": "directory", "identity": identity(os.fstat(fd))}
        walk(fd, "")
    except OSError as exc:
        issues.append({"source_file": ".", "code": "source_scan_failed", "reason": str(exc)})
    finally:
        if fd is not None:
            os.close(fd)
    return entries, issues


def run(source: Path, destination: Path) -> dict:
    source, destination = source.resolve(), destination.resolve()
    if not source.is_dir():
        raise ValueError("input directory does not exist")
    if destination == source or source in destination.parents or destination in source.parents:
        raise ValueError("input and output directories must not contain one another")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("use an empty output directory to prevent stale/overwritten analysis")
    # Hash every original regular file before decoding; never follow symlink records.
    snapshots, inventory, warnings = {}, [], []
    initial_entries, scan_issues = scan_source_tree(source, capture=True)
    warnings.extend(scan_issues)
    for rel, entry in initial_entries.items():
        if entry["kind"] == "symlink":
            warnings.append({"source_file": rel, "code": "symlink_not_followed"})
        elif entry["kind"] == "special":
            warnings.append({"source_file": rel, "code": "special_file_not_read"})
        elif entry["kind"] == "file":
            data = entry.pop("data")
            snapshots[rel] = data
            inventory.append(
                {
                    "path": rel,
                    "size": len(data),
                    "sha256": entry["sha256"],
                    "mtime_utc": entry["mtime_utc"],
                    "header_hex": data[:64].hex(),
                    "tail_hex": data[-32:].hex(),
                    "preliminary_type": "BYS"
                    if Path(rel).suffix.lower() == ".bys"
                    else "unclassified non-BYS",
                }
            )
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "inventory.json").write_text(json.dumps(inventory, indent=2))
    outputs = destination / "output"
    outputs.mkdir()
    # Preserve every byte, even unknown files/headers and malformed regions.
    raw_dir = destination / "raw"
    raw_dir.mkdir()
    (raw_dir / "source_files.json").write_text(
        json.dumps(
            [
                {
                    "source_file": rel,
                    "byte_length": len(b),
                    "sha256": hashlib.sha256(b).hexdigest(),
                    "raw_hex": b.hex(),
                }
                for rel, b in snapshots.items()
            ],
            indent=2,
        )
    )
    sessions, timeseries, events, candidates, validations, raw_records, raw_details = (
        [],
        [],
        [],
        [],
        [],
        [],
        [],
    )
    settings_rows = []
    processed = set()
    accepted_bases = []
    known_identities = defaultdict(list)

    def summary_identity(summary):
        return (summary["model_serial"], summary["start_time"], summary["end_time"])

    by_lower = defaultdict(list)
    for rel in snapshots:
        by_lower[rel.lower()].append(rel)
    for key, names in by_lower.items():
        if len(names) > 1:
            warnings.append({"code": "case_colliding_paths", "paths": names})

    def peer(rel: str, suffix: str) -> str | None:
        names = by_lower.get((rel[:-5] + suffix + ".bys").lower(), [])
        return names[0] if len(names) == 1 else None

    for rel, data in snapshots.items():
        if not rel.lower().endswith("s.bys"):
            continue
        processed.add(rel)
        sid = str(Path(rel).with_suffix(""))[:-1]
        try:
            summary = parse_summary(data)
        except (FormatError, struct.error) as exc:
            try:
                summary = parse_summary_base(data)
            except (FormatError, struct.error):
                warnings.append(
                    {"source_file": rel, "code": "rejected_summary", "reason": str(exc)}
                )
                continue
            warnings.append(
                {"source_file": rel, "code": "settings_rejected_base_salvaged", "reason": str(exc)}
            )
        accepted_bases.append(data[:62])
        known_identities[summary_identity(summary)].append((sid, data[:62]))
        summary["session_id"] = sid
        settings_rows.extend(
            {"session_id": sid, "source_file": rel, **s} for s in summary.pop("settings")
        )
        start = datetime.fromisoformat(summary["start_time"])
        end = datetime.fromisoformat(summary["end_time"])
        session = session_row(summary, sid, rel)
        sessions.append(session)
        check = {
            "session_id": sid,
            "summary_source": rel,
            "summary": summary,
            "summary_minutes_match_elapsed": summary["record_count"] == summary["duration_minutes"],
        }
        mrel = peer(rel, "m")
        if not mrel:
            warnings.append({"source_file": rel, "code": "missing_or_ambiguous_minute_file"})
        else:
            processed.add(mrel)
            try:
                mstart, declared, records, issues = parse_records(snapshots[mrel], 22)
                warnings.extend({"source_file": mrel, **issue} for issue in issues)
                check.update(
                    minute_declared=declared,
                    minute_decoded=len(records),
                    minute_start_matches=mstart == start,
                    minute_count_matches_summary=declared == summary["record_count"],
                    minute_complete=not issues,
                )
                if mstart != start or declared != summary["record_count"]:
                    warnings.append({"source_file": mrel, "code": "minute_summary_mismatch"})
                sums = {i: sum(b[i] for _, b in records) for i in range(5, 10)}
                check["counter_sums"] = {str(i): v for i, v in sums.items()}
                check["counter_summary_equalities"] = {
                    str(i): sums[i] == u16(data, 16 + 2 * (i - 5)) for i in range(5, 10)
                }
                check["summary_total_equals_three_counters"] = u16(data, 14) == sum(
                    u16(data, i) for i in (16, 18, 20)
                )
                check["ipap_ge_epap"] = all(u16(b, 0) >= u16(b, 2) for _, b in records)
                check["pressure_support_raw_values"] = sorted(
                    {u16(b, 0) - u16(b, 2) for _, b in records}
                )
                valid = []
                previous, rising = {}, Counter()
                for i, b in records:
                    stamp = mstart + timedelta(minutes=i)
                    provenance = {
                        "session_id": sid,
                        "source_file": mrel,
                        "source_offset": 8 + 22 * i,
                        "record_index": i,
                    }
                    raw_records.append(
                        {**provenance, "raw_hex": b.hex(), **{f"byte_{j}": b[j] for j in range(22)}}
                    )
                    # Timing is an interval assignment, not an observed exact event time.
                    time_valid = (
                        mstart == start and start <= stamp and stamp + timedelta(minutes=1) <= end
                    )
                    if not time_valid:
                        warnings.append({**provenance, "code": "minute_time_not_validated"})
                        continue
                    row = {
                        **provenance,
                        "timestamp": stamp.isoformat(),
                        "elapsed_seconds": i * 60,
                        "ipap_probable_cmH2O": u16(b, 0) / 10,
                        "epap_probable_cmH2O": u16(b, 2) / 10,
                        "pressure_support_probable_cmH2O": (u16(b, 0) - u16(b, 2)) / 10,
                        "leak_probable_L_min": u16(b, 12) / 10,
                        "tidal_volume_probable_mL": u16(b, 14),
                        "minute_ventilation_probable_L_min": b[16],
                        "ie_ratio_probable_percent": b[17],
                        "respiratory_rate_probable_breaths_min": b[18],
                        "spo2": None,
                        "pulse_rate": None,
                        "spo2_slot_raw": b[19],
                        "pulse_slot_raw": b[20],
                        "confidence": "probable: Format E mapping; not verified on ET525A screen",
                        "time_basis": "assumed consecutive 60-second bins; device timezone unknown",
                    }
                    if not 4 <= row["epap_probable_cmH2O"] <= row["ipap_probable_cmH2O"] <= 25:
                        warnings.append(
                            {**provenance, "code": "pressure_mapping_outside_candidate_range"}
                        )
                        row["confidence"] = "tentative: pressure plausibility check failed"
                    if b[19] or b[20]:
                        warnings.append(
                            {**provenance, "code": "nonzero_oximetry_slots_require_validation"}
                        )
                    timeseries.append(row)
                    if row["confidence"].startswith("probable"):
                        valid.append(row)
                    for offset, label in (
                        (5, "obstructive_apnea"),
                        (6, "central_apnea"),
                        (7, "hypopnea"),
                    ):
                        prior_index, prior_value = previous.get(offset, (-1, 0))
                        # Never merge across a missing/corrupt minute.
                        onset = bool(b[offset] and prior_index == i - 1 and not prior_value)
                        if onset:
                            rising[label] += 1
                        if b[offset]:
                            events.append(
                                {
                                    **provenance,
                                    "timestamp": stamp.isoformat(),
                                    "interval_end": (stamp + timedelta(minutes=1)).isoformat(),
                                    "event_type": "candidate_" + label + "_minute_counter",
                                    "value_raw": b[offset],
                                    "byte_offset_in_record": offset,
                                    "duration_seconds": None,
                                    "rising_edge_candidate": onset,
                                    "confidence": "probable label; individual event counts/durations unconfirmed",
                                }
                            )
                        previous[offset] = (i, b[offset])
                check["rising_edge_candidates"] = dict(rising)
                if valid:
                    c = {
                        "session_id": sid,
                        "minute_records_used": len(valid),
                        "source_summary": rel,
                        "source_minutes": mrel,
                        "event_total_raw": u16(data, 14),
                        "oa_counter_raw": u16(data, 16),
                        "ca_counter_raw": u16(data, 18),
                        "h_counter_raw": u16(data, 20),
                        "summary_ipap_raw": u16(data, 32),
                        "summary_epap_raw": u16(data, 34),
                        "unexplained_duration_field_42_raw": u16(data, 42),
                        "ahi": None,
                        "confidence": "probable physiological mapping; counters are not validated event counts",
                    }
                    for name in (
                        "ipap_probable_cmH2O",
                        "epap_probable_cmH2O",
                        "leak_probable_L_min",
                        "tidal_volume_probable_mL",
                        "respiratory_rate_probable_breaths_min",
                        "minute_ventilation_probable_L_min",
                    ):
                        c["mean_" + name] = sum(r[name] for r in valid) / len(valid)
                    check["summary_ipap_equals_floor_minute_mean"] = u16(data, 32) == int(
                        c["mean_ipap_probable_cmH2O"] * 10 + 1e-9
                    )
                    check["summary_epap_equals_floor_minute_mean"] = u16(data, 34) == int(
                        c["mean_epap_probable_cmH2O"] * 10 + 1e-9
                    )
                    check["ventilation_identity_mean_absolute_error_L_min"] = sum(
                        abs(
                            r["minute_ventilation_probable_L_min"]
                            - r["tidal_volume_probable_mL"]
                            * r["respiratory_rate_probable_breaths_min"]
                            / 1000
                        )
                        for r in valid
                    ) / len(valid)
                    candidates.append(c)
            except (FormatError, struct.error) as exc:
                warnings.append(
                    {"source_file": mrel, "code": "rejected_minute_file", "reason": str(exc)}
                )
        drel = peer(rel, "d")
        if drel:
            processed.add(drel)
            try:
                dstart, declared, records, issues = parse_records(snapshots[drel], 1201)
                warnings.extend({"source_file": drel, **issue} for issue in issues)
                check.update(
                    detail_declared=declared,
                    detail_decoded=len(records),
                    detail_start_matches=dstart == start,
                    detail_count_matches_summary=declared == summary["record_count"],
                )
                if dstart != start or declared != summary["record_count"]:
                    warnings.append({"source_file": drel, "code": "detail_summary_mismatch"})
                for i, b in records:
                    raw_details.append(
                        {
                            "session_id": sid,
                            "source_file": drel,
                            "source_offset": 8 + 1201 * i,
                            "record_index": i,
                            "channel_a_hex": b[:600].hex(),
                            "channel_b_hex": b[600:1200].hex(),
                            "channel_meaning": "unknown; no physical-unit conversion",
                        }
                    )
            except (FormatError, struct.error) as exc:
                warnings.append(
                    {"source_file": drel, "code": "rejected_detail_file", "reason": str(exc)}
                )
        else:
            check["detail_present"] = False
        validations.append(check)

    index_checks = []
    for rel, data in snapshots.items():
        if Path(rel).name.lower() == "summer.bys":
            processed.add(rel)
            chunks = [data[i : i + 62] for i in range(0, len(data), 62)]
            exact = Counter(chunks) == Counter(accepted_bases)
            index_checks.append(
                {
                    "source_file": rel,
                    "record_size": 62,
                    "complete_record_count": len(data) // 62,
                    "tail_bytes": len(data) % 62,
                    "exact_multiset_match_to_session_bases": exact,
                }
            )
            if not exact:
                warnings.append({"source_file": rel, "code": "index_summary_mismatch"})
            remaining = Counter(accepted_bases)
            for i, chunk in enumerate(chunks):
                if remaining[chunk]:
                    remaining[chunk] -= 1
                    continue
                try:
                    base = parse_summary_base(chunk)
                except (FormatError, struct.error) as exc:
                    warnings.append(
                        {
                            "source_file": rel,
                            "source_offset": i * 62,
                            "code": "invalid_index_base",
                            "reason": str(exc),
                        }
                    )
                    continue
                existing = known_identities[summary_identity(base)]
                if existing:
                    conflict = any(chunk != old_base for _, old_base in existing)
                    ids = [old_sid for old_sid, _ in existing]
                    warnings.append(
                        {
                            "source_file": rel,
                            "source_offset": i * 62,
                            "code": "index_session_conflict"
                            if conflict
                            else "duplicate_index_representation",
                            "session_ids": ids,
                            "raw_base_hex": chunk.hex(),
                        }
                    )
                    if conflict:
                        for row in sessions:
                            if row["session_id"] in ids:
                                row["summary_conflict"] = True
                        for row in validations:
                            if row["session_id"] in ids:
                                row["summary_conflict"] = True
                    continue
                sid = f"index:{rel}:{i * 62}"
                sessions.append(session_row(base, sid, rel, i * 62))
                known_identities[summary_identity(base)].append((sid, chunk))
                validations.append(
                    {
                        "session_id": sid,
                        "summary": base,
                        "summary_source": rel,
                        "index_only_recovery": True,
                        "source_offset": i * 62,
                    }
                )
                warnings.append(
                    {
                        "source_file": rel,
                        "source_offset": i * 62,
                        "code": "index_only_session_recovered",
                        "session_id": sid,
                    }
                )
    unpaired_records = []
    for rel in snapshots:
        if rel not in processed and rel.lower().endswith(".bys"):
            warnings.append({"source_file": rel, "code": "unrecognized_or_unpaired_bys"})
            size = (
                22
                if rel.lower().endswith("m.bys")
                else 1201
                if rel.lower().endswith("d.bys")
                else None
            )
            if size:
                try:
                    stamp, declared, records, issues = parse_records(snapshots[rel], size)
                    warnings.extend({"source_file": rel, **i} for i in issues)
                    for i, b in records:
                        unpaired_records.append(
                            {
                                "source_file": rel,
                                "source_offset": 8 + i * size,
                                "record_index": i,
                                "record_length": size,
                                "header_start": stamp.isoformat(),
                                "raw_hex": b.hex(),
                                "confidence": "structural candidate only; model/association unverified",
                            }
                        )
                except (FormatError, struct.error) as exc:
                    warnings.append(
                        {
                            "source_file": rel,
                            "code": "unpaired_record_header_rejected",
                            "reason": str(exc),
                        }
                    )
    sessions.sort(key=lambda s: s["start_time"])
    duplicate_pairs, overlap_pairs = [], []
    for i, row in enumerate(sessions):
        for other in sessions[:i]:
            pair = [other["session_id"], row["session_id"]]
            if row["start_time"] == other["start_time"] and row["end_time"] == other["end_time"]:
                duplicate_pairs.append(pair)
            if row["start_time"] < other["end_time"]:
                overlap_pairs.append(pair)
    if overlap_pairs:
        warnings.append({"code": "overlapping_sessions", "pairs": overlap_pairs})
    # Calendar-day splitting; intervals are unioned so overlapping exports don't inflate duration.
    spans = defaultdict(list)
    for row in sessions:
        cursor, end = (
            datetime.fromisoformat(row["start_time"]),
            datetime.fromisoformat(row["end_time"]),
        )
        while cursor < end:
            stop = min(end, cursor.replace(hour=0, minute=0, second=0) + timedelta(days=1))
            spans[cursor.date().isoformat()].append((cursor, stop, row["session_id"]))
            cursor = stop
    daily = []
    for day, chunks in sorted(spans.items()):
        merged = []
        for a, b, _ in sorted(chunks):
            if merged and a <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        daily.append(
            {
                "date": day,
                "total_session_elapsed_hours": sum(
                    (b - a).total_seconds() / 3600 for a, b in merged
                ),
                "session_count_touching_day": len({sid for _, _, sid in chunks}),
                "ahi": None,
                "basis": "calendar-day split of device wall-clock intervals; not verified sleep/mask-on hours",
            }
        )
    final_entries, final_issues = scan_source_tree(source, capture=False)
    warnings.extend(final_issues)
    changed = set(initial_entries).symmetric_difference(final_entries)
    changed.update(
        rel
        for rel in initial_entries.keys() & final_entries.keys()
        if initial_entries[rel] != final_entries[rel]
    )
    changed.update(issue["source_file"] for issue in scan_issues + final_issues)
    changed = sorted(changed)
    if changed:
        warnings.append({"code": "source_changed_during_analysis", "paths": changed})
    report = {
        "parser_version": VERSION,
        "input": str(source),
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "counts": {
            "input_files": len(inventory),
            "bys_files": sum(r["path"].lower().endswith(".bys") for r in inventory),
            "sessions": len(sessions),
            "minute_records": len(raw_records),
            "detail_blocks": len(raw_details),
            "flagged_minute_rows": len(events),
        },
        "sessions": sessions,
        "candidate_summaries": candidates,
        "daily_summary": daily,
        "validations": validations,
        "index_checks": index_checks,
        "duplicate_pairs": duplicate_pairs,
        "overlap_pairs": overlap_pairs,
        "source_hashes_unchanged": not changed,
        "diagnostics": warnings,
        "limitations": [
            "ET525A physiological mappings are probable, not screen-verified.",
            "Core AHI fields remain null; the workflow adds separately labeled estimates and screen comparisons in ahi_sessions.csv.",
            "Device timezone and clock accuracy unknown; timestamps are not converted to UTC.",
            "Session duration is elapsed time, not demonstrated sleep or mask-on time.",
            "SpO2/pulse slots are raw only; zero is not a physiological measurement.",
            "No validated checksum algorithm; marker/length checks are not checksums.",
            "Waveform channels exported raw; units/sign/scale unresolved.",
        ],
    }
    for filename, rows in (
        ("sessions.csv", sessions),
        ("daily_summary.csv", daily),
        ("timeseries.csv", timeseries),
        ("events.csv", events),
        ("candidate_session_metrics.csv", candidates),
        ("raw_minute_records.csv", raw_records),
        ("settings_candidates.csv", settings_rows),
    ):
        write_csv(outputs / filename, rows)
    (outputs / "raw_detail_blocks.json").write_text(json.dumps(raw_details, indent=2))
    (outputs / "unpaired_raw_records.json").write_text(json.dumps(unpaired_records, indent=2))
    (outputs / "analysis.json").write_text(json.dumps(report, indent=2, allow_nan=False))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument(
        "--output", required=True, type=Path, help="new or empty output directory outside input"
    )
    args = parser.parse_args()
    try:
        result = run(args.input, args.output)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")
    print(
        json.dumps(
            {
                "counts": result["counts"],
                "diagnostics": result["diagnostics"],
                "source_hashes_unchanged": result["source_hashes_unchanged"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
