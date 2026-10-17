#!/usr/bin/env python3
"""Repeatable, local-only ET525A import and history workflow (Python 3.10+)."""

import argparse
import csv
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .decoder import run, scan_source_tree
from .analysis import enrich
from .ahi import build as build_ahi, load_observations, FIELDS
from .report import generate

from . import __version__

VERSION = __version__


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")


def fingerprint(source):
    entries, issues = scan_source_tree(source, capture=False)
    if issues:
        raise ValueError("Input could not be read stably: " + json.dumps(issues))
    if any(v["kind"] in {"symlink", "special"} for v in entries.values()):
        raise ValueError("Symlink or non-regular entry in input; use a plain device-folder copy")
    files = [(name, v["size"], v["sha256"]) for name, v in entries.items() if v["kind"] == "file"]
    if sum(n for _, n, _ in files) > 512 * 1024 * 1024:
        raise ValueError(
            "Input exceeds 512 MiB. Use a smaller dated device-folder copy; no files were imported."
        )
    return sorted(files)


def select_source(path):
    path = path.expanduser().resolve()
    if not path.is_dir():
        raise ValueError("Input must be an existing device folder or mounted card root")
    children = [
        p
        for p in path.iterdir()
        if p.is_dir() and not p.is_symlink() and p.name.startswith("ET525A-")
    ]
    if len(children) > 1:
        raise ValueError("Multiple ET525A folders found; specify one device folder explicitly")
    if len(children) == 1 and not list(path.glob("*.bys")):
        path = children[0]
    return path


def validate_library(library):
    # Library directories are agent-owned data; refuse symlinks before any read/write.
    if library.exists():
        for folder, dirs, names in os.walk(library, followlinks=False):
            for name in dirs + names:
                if (Path(folder) / name).is_symlink():
                    raise ValueError("Library contains a symlink; refusing mutation")


def complete_imports(library):
    for folder in sorted((library / "imports").glob("*")):
        if folder.is_dir() and (folder / "complete.json").is_file():
            yield folder


def merged_observations(library, provided):
    # Keep prior observations immutable; identical repeats are harmless, conflicts require correction upstream.
    rows = []
    for folder in sorted((library / "observations").glob("*.csv")):
        rows.extend(load_observations(folder))
    if provided:
        rows.extend(load_observations(provided))
    unique = {}
    for r in rows:
        key = tuple(r[f] for f in FIELDS[:3])
        if key in unique and any(unique[key][f] != r[f] for f in FIELDS[3:5]):
            raise ValueError(
                "Observation conflicts with saved history. Preserve the old file and correct the observation CSV before rebuilding."
            )
        unique[key] = r
    return list(unique.values())


def canonical_sessions(library):
    groups = {}
    for folder in complete_imports(library):
        a = json.loads((folder / "output/analysis.json").read_text())
        archive = json.loads((folder / "raw/source_files.json").read_text())
        raw = {r["source_file"]: bytes.fromhex(r["raw_hex"]) for r in archive}
        for r in archive:
            if digest(raw[r["source_file"]]) != r["sha256"]:
                raise ValueError(f"Saved import archive is damaged: {folder.name}")
        for c in a["validations"]:
            s = c["summary"]
            rel = c["summary_source"]
            off = c.get("source_offset", 0)
            summary = raw[rel][off : off + 62] if c.get("index_only_recovery") else raw[rel]
            payload = {"s": summary}
            if not c.get("index_only_recovery"):
                for suffix in ["m", "d"]:
                    names = [k for k in raw if k.lower() == (rel[:-5] + suffix + ".bys").lower()]
                    if len(names) == 1:
                        payload[suffix] = raw[names[0]]
            groups.setdefault((s["model_serial"], s["start_time"]), []).append(
                {
                    "import_id": folder.name,
                    "session_id": c["session_id"],
                    "source_summary": rel,
                    "summary_conflict": c.get("summary_conflict", False),
                    "payload": payload,
                    "index_only": c.get("index_only_recovery", False),
                }
            )
    canonical, conflicts = [], []
    for key, items in sorted(groups.items()):
        identity = digest(json.dumps(key).encode())[:24]
        evidence = [{k: v for k, v in item.items() if k != "payload"} for item in items]
        reasons = []
        if any(i["summary_conflict"] for i in items):
            reasons.append("conflicting index summary")
        # End time, counters, pressure summaries must agree even if index lacks history payload.
        if len({i["payload"]["s"][:60] for i in items}) != 1:
            reasons.append("summary values or end times differ")
        payload = {}
        full = {i["payload"]["s"] for i in items if not i["index_only"]}
        if len(full) > 1:
            reasons.append("summary/history payloads differ")
        payload["s"] = next(iter(full)) if full else items[0]["payload"]["s"]
        for suffix in ["m", "d"]:
            values = {i["payload"][suffix] for i in items if suffix in i["payload"]}
            if len(values) > 1:
                reasons.append(f"{suffix}.bys payloads differ")
            if values:
                payload[suffix] = next(iter(values))
        info = {
            "canonical_id": identity,
            "model_serial": key[0],
            "start_time": key[1],
            "sources": evidence,
        }
        if reasons:
            conflicts.append(
                {
                    **info,
                    "reasons": reasons,
                    "policy": "excluded from combined totals; all versions retained in imports",
                }
            )
        else:
            canonical.append({**info, "payload": payload})
    return canonical, conflicts


def rebuild(library, observations):
    canonical, conflicts = canonical_sessions(library)
    # Versioned reports are never overwritten. LATEST.json is replaced atomically after success.
    reports = library / "reports"
    reports.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".build-", dir=library) as temp:
        temp = Path(temp)
        combined = temp / "source"
        combined.mkdir()
        provenance = []
        for s in canonical:
            sub = combined / s["canonical_id"]
            sub.mkdir()
            for suffix, data in s["payload"].items():
                p = sub / f"record{suffix}.bys"
                p.write_bytes(data)
                provenance.append(
                    {
                        "combined_source_file": str(p.relative_to(combined)),
                        "sha256": digest(data),
                        "original_sources": s["sources"],
                    }
                )
        # No synthesized summer index: every imported original index remains in its raw archive.
        result = temp / "result"
        run(combined, result)
        enrich(result)
        save(result / "history_provenance.json", provenance)
        save(result / "history_conflicts.json", conflicts)
        save(result / "observations.json", observations)
        ahi = build_ahi(result, observations)
        # Single-device libraries keep calendar unions and physiological rollups meaningful.
        if len({s["model_serial"] for s in canonical}) > 1:
            raise ValueError(
                "Multiple device serials in library; use a separate library for each device"
            )
        generate(result, ahi, conflicts)
        save(
            result / "complete.json",
            {
                "toolkit_version": VERSION,
                "imports": len(list(complete_imports(library))),
                "sessions": len(canonical),
                "conflicts": len(conflicts),
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "input_policy": "combined source reorganizes unchanged bytes; history_provenance.json maps to immutable original imports",
            },
        )
        report_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        dest = reports / report_id
        result.rename(dest)
        pointer = library / ".LATEST.tmp"
        save(
            pointer,
            {
                "report": str(dest.relative_to(library)),
                "dashboard": str((dest / "report.html").relative_to(library)),
                "conflicts": len(conflicts),
            },
        )
        pointer.replace(library / "LATEST.json")
        # Stable entry page only links to versioned report; no JavaScript or network redirect.
        index = library / ".index.tmp"
        index.write_text(
            f'<!doctype html><meta charset="utf-8"><title>ET525A reports</title>'
            f'<h1>AppByeScribe local reports</h1><p><a href="reports/{report_id}/report.html">Open latest report</a></p>'
            f"<p>{len(canonical)} unique sessions; {len(conflicts)} conflicts excluded. Previous reports remain in reports/.</p>"
        )
        index.replace(library / "index.html")
        return dest


def execute(source, library, observations_path=None):
    source = select_source(source) if source else None
    library = library.expanduser().resolve()
    if source and (library == source or source in library.parents or library in source.parents):
        raise ValueError("Library and input must not contain one another")
    validate_library(library)
    if library.exists() and any(library.iterdir()) and not (library / "library.json").exists():
        raise ValueError(
            "Use a new empty library directory; this directory is not an ET525A library"
        )
    library.mkdir(parents=True, exist_ok=True)
    lock = library / ".import.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ValueError(
            "Library is locked. Wait for the other run; after a crash see README recovery instructions."
        )
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        (library / "imports").mkdir(exist_ok=True)
        (library / "observations").mkdir(exist_ok=True)
        if not (library / "library.json").exists():
            save(library / "library.json", {"format": 1, "toolkit_version": VERSION})
        observations = merged_observations(library, observations_path)
        imported = None
        already = False
        if source:
            before = fingerprint(source)
            if not any(r[0].lower().endswith(".bys") for r in before):
                raise ValueError("No BYS files found in the selected input")
            imported = digest(json.dumps(before, separators=(",", ":")).encode())
            dest = library / "imports" / imported
            already = (dest / "complete.json").exists()
            if not already:
                with tempfile.TemporaryDirectory(prefix=".import-", dir=library) as tmp:
                    stage = Path(tmp) / "result"
                    report = run(source, stage)
                    inventory = json.loads((stage / "inventory.json").read_text())
                    captured = sorted((r["path"], r["size"], r["sha256"]) for r in inventory)
                    if (
                        not report["source_hashes_unchanged"]
                        or captured != before
                        or fingerprint(source) != before
                    ):
                        raise ValueError(
                            "Input changed during import. No completed import published; retry from a stopped, stable card copy."
                        )
                    serials = {c["summary"]["model_serial"] for c in report["validations"]}
                    for old in complete_imports(library):
                        old_report = json.loads((old / "output/analysis.json").read_text())
                        serials.update(
                            c["summary"]["model_serial"] for c in old_report["validations"]
                        )
                    if len(serials) > 1:
                        raise ValueError("Use a separate library for each device serial")
                    enrich(stage)
                    save(
                        stage / "complete.json",
                        {
                            "import_id": imported,
                            "toolkit_version": VERSION,
                            "original_source": str(source),
                            "created_utc": datetime.now(timezone.utc).isoformat(),
                            "source_files": len(before),
                        },
                    )
                    stage.rename(dest)
        if observations_path:
            data = Path(observations_path).read_bytes()
            target = library / "observations" / (digest(data) + ".csv")
            if not target.exists():
                target.write_bytes(data)
        if not list(complete_imports(library)):
            raise ValueError("Library has no completed imports; supply an input folder first")
        dest = rebuild(library, observations)
        return {
            "import_id": imported,
            "already_imported": already,
            "report": str(dest / "report.html"),
            "library_index": str(library / "index.html"),
        }
    finally:
        lock.unlink(missing_ok=True)


def main():
    p = argparse.ArgumentParser(prog="appbyescribe", description=__doc__)
    p.add_argument("--version", action="version", version="AppByeScribe " + VERSION)
    p.add_argument(
        "input", nargs="?", type=Path, help="device folder/card root; omit to rebuild saved imports"
    )
    p.add_argument(
        "--library", required=True, type=Path, help="persistent local folder outside the card/input"
    )
    p.add_argument(
        "--observations", type=Path, help="CSV of exact-session machine-screen observations"
    )
    args = p.parse_args()
    try:
        print(json.dumps(execute(args.input, args.library, args.observations), indent=2))
    except (ValueError, OSError, csv.Error) as exc:
        p.exit(2, f"ERROR: {exc}\n")


if __name__ == "__main__":
    main()
