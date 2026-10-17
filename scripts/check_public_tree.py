#!/usr/bin/env python3
"""Reject common personal-data paths/content in the Git index before publication."""

import re
import subprocess
from pathlib import PurePosixPath


def violations(name, data):
    path = PurePosixPath(name)
    issues = []
    if set(path.parts) & {"private", "data", "library", "imports", "reports", "output", "raw"}:
        issues.append("personal/generated directory")
    if path.suffix.lower() in {".bys", ".pdf", ".png", ".jpg", ".jpeg", ".heic", ".zip", ".html"}:
        issues.append("recording, media or generated artifact")
    if path.suffix.lower() == ".csv" and name != "examples/observations_template.csv":
        issues.append("CSV not on public-template allowlist")
    if path.name in {
        "source_files.json",
        "verification.json",
        "observations.csv",
        "package_manifest.json",
    }:
        issues.append("personal archive, observation or manifest")
    text = data.decode("utf-8", errors="replace")
    for serial in re.findall(r"\bET525A-[A-Za-z0-9]{9}\b", text):
        if not re.fullmatch(r"ET525A-TEST\d{5}", serial):
            issues.append("non-fixture device serial")
    if re.search(r"/(?:Users|home)/[^/\s]+/", text):
        issues.append("absolute home-directory path")
    if re.search(r'"raw_hex"\s*:\s*"[0-9a-fA-F]{32,}"', text):
        issues.append("embedded binary archive")
    if name == "examples/observations_template.csv" and len(text.strip().splitlines()) != 1:
        issues.append("observation template contains data rows")
    return sorted(set(issues))


def main():
    root = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()
    files = subprocess.check_output(["git", "ls-files", "--cached", "-z"], cwd=root).split(b"\0")
    failed = []
    for raw_name in files:
        if not raw_name:
            continue
        name = raw_name.decode("utf-8")
        # Read the staged blob, not an un-staged working-tree replacement.
        data = subprocess.check_output(["git", "show", ":" + name], cwd=root)
        reasons = violations(name, data)
        if reasons:
            failed.append((name, reasons))
    for name, reasons in failed:
        print(name + ": " + "; ".join(reasons))
    if failed:
        raise SystemExit("Public-tree audit FAILED. Unstage personal files before committing.")
    print(f"Public-tree audit passed: {sum(bool(x) for x in files)} tracked files.")


if __name__ == "__main__":
    main()
