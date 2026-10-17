import csv
import json
import struct
import subprocess
import pytest

from appbyescribe.workflow import execute
from appbyescribe.decoder import run
from appbyescribe.analysis import enrich, period_rows
from appbyescribe.ahi import build
from test_decoder import make_source, summary, minutes, stamp


def read(path):
    return json.loads(path.read_text())


def latest(lib):
    return lib / read(lib / "LATEST.json")["report"]


def prepare(src):
    # Two actual candidate events, one in each minute; update both summary copies.
    m = bytearray(minutes())
    m[8 + 5] = 1
    m[30 + 5] = 1
    s = bytearray(summary())
    struct.pack_into("<H", s, 14, 2)
    struct.pack_into("<H", s, 16, 2)
    next(src.rglob("*m.bys")).write_bytes(m)
    next(src.rglob("*s.bys")).write_bytes(s)
    (src / "summer.bys").write_bytes(s[:62])


def observation():
    return {
        "model_serial": "ET525A-TEST00001",
        "start_time": "2024-01-01T23:59:00",
        "end_time": "2024-01-02T00:01:00",
        "displayed_ahi": "60.0",
        "displayed_usage_hours": "0.0",
        "notes": "synthetic",
    }


def test_repeat_import_is_idempotent_and_html_created(tmp_path):
    src = make_source(tmp_path)
    prepare(src)
    lib = tmp_path / "library"
    original = {str(p): p.read_bytes() for p in src.rglob("*") if p.is_file()}
    a = execute(src, lib)
    b = execute(src, lib)
    assert not a["already_imported"] and b["already_imported"]
    assert len(list((lib / "imports").iterdir())) == 1
    assert read(latest(lib) / "complete.json")["sessions"] == 1
    assert "60.0" in (latest(lib) / "report.html").read_text()
    assert original == {str(p): p.read_bytes() for p in src.rglob("*") if p.is_file()}


def test_custom_library_is_ignored_and_existing_rules_are_preserved(tmp_path):
    src = make_source(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    lib = repo / "my-recordings"
    execute(src, lib)
    rule = (lib / ".gitignore").read_text()
    result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout == ""
    # Existing libraries are protected on rebuild, with prior rules retained.
    (lib / ".gitignore").write_text("# existing comment\n!important.json\n")
    execute(None, lib)
    combined = (lib / ".gitignore").read_text()
    assert combined.startswith("# existing comment") and combined.endswith(rule)
    execute(None, lib)
    assert (lib / ".gitignore").read_text() == combined
    assert (
        subprocess.run(
            ["git", "check-ignore", "-q", "my-recordings/important.json"], cwd=repo
        ).returncode
        == 0
    )


def test_overlapping_exports_deduplicate_and_enrich_detail(tmp_path):
    src = make_source(tmp_path)
    prepare(src)
    lib = tmp_path / "lib"
    execute(src, lib)
    next(src.rglob("*m.bys")).with_name("0000001d.bys").write_bytes(
        stamp() + struct.pack("<H", 2) + (bytes(1200) + b"\xfe") * 2
    )
    execute(src, lib)
    r = read(latest(lib) / "output/review_analysis.json")
    assert r["minute_coverage_minutes"] == 2 and r["high_frequency_sample_pairs"] == 1200
    assert read(latest(lib) / "complete.json")["sessions"] == 1


def test_conflicting_payload_excluded_without_overwriting(tmp_path):
    src = make_source(tmp_path)
    lib = tmp_path / "lib"
    execute(src, lib)
    p = next(src.rglob("*m.bys"))
    b = bytearray(p.read_bytes())
    b[8 + 8] = 3
    p.write_bytes(b)
    execute(src, lib)
    assert len(list((lib / "imports").iterdir())) == 2
    r = latest(lib)
    assert read(r / "complete.json")["sessions"] == 0
    assert len(read(r / "history_conflicts.json")) == 1


def test_screen_match_and_mismatch_are_not_forced(tmp_path):
    src = make_source(tmp_path)
    prepare(src)
    out = tmp_path / "out"
    run(src, out)
    enrich(out)
    a = build(out, [observation()])
    assert a["screen_matches"] == 1
    o = observation()
    o["displayed_ahi"] = "59.9"
    a = build(out, [o])
    assert a["screen_disagreements"] == 1 and a["sessions"][0]["ahi_estimate"] == 60


@pytest.mark.parametrize("mutation", ["duration", "counter", "marker", "summary_conflict"])
def test_ahi_withheld_on_integrity_failure(tmp_path, mutation):
    src = make_source(tmp_path)
    prepare(src)
    if mutation == "duration":
        p = next(src.rglob("*s.bys"))
        b = bytearray(p.read_bytes())
        b[8:14] = stamp(0, 0, 2)
        p.write_bytes(b)
        (src / "summer.bys").write_bytes(b[:62])
    elif mutation in ("counter", "marker"):
        p = next(src.rglob("*m.bys"))
        b = bytearray(p.read_bytes())
        b[8 + (5 if mutation == "counter" else 21)] = 0
        p.write_bytes(b)
    else:
        p = src / "summer.bys"
        b = bytearray(p.read_bytes())
        b[14] = 3
        p.write_bytes(b)
    out = tmp_path / "out"
    run(src, out)
    enrich(out)
    a = build(out, [])
    assert a["sessions"][0]["ahi_estimate"] is None


@pytest.mark.parametrize("mode", ["invalid_header", "invalid_marker", "extra", "orphan"])
def test_waveform_coverage_requires_valid_records_and_session(tmp_path, mode):
    src = make_source(tmp_path)
    data = stamp() + struct.pack("<H", 2) + (bytes(1200) + b"\xfe") * 2
    if mode == "invalid_header":
        data = b"\xff" * 6 + data[6:]
    if mode == "invalid_marker":
        data = data[:1208] + b"\x00" + data[1209:]
    if mode == "extra":
        data += bytes(1200) + b"\xfe"
    target = (
        src / "orphan_d.bys"
        if mode == "orphan"
        else next(src.rglob("*m.bys")).with_name("0000001d.bys")
    )
    target.write_bytes(data)
    out = tmp_path / "out"
    run(src, out)
    r = enrich(out)
    assert r["waveform_coverage_minutes"] == 0
    expected = {"invalid_header": 0, "invalid_marker": 600, "extra": 1200, "orphan": 1200}[mode]
    assert r["high_frequency_sample_pairs"] == expected


def test_bad_raw_archive_hash_raises_explicitly(tmp_path):
    src = make_source(tmp_path)
    out = tmp_path / "out"
    run(src, out)
    p = out / "raw/source_files.json"
    r = read(p)
    r[0]["sha256"] = "0" * 64
    p.write_text(json.dumps(r))
    with pytest.raises(ValueError, match="integrity"):
        enrich(out)


def test_observations_persist_on_later_import_without_csv(tmp_path):
    src = make_source(tmp_path)
    prepare(src)
    lib = tmp_path / "lib"
    p = tmp_path / "screen.csv"
    o = observation()
    with p.open("w") as f:
        w = csv.DictWriter(f, fieldnames=list(o))
        w.writeheader()
        w.writerow(o)
    execute(src, lib, p)
    execute(src, lib)
    assert read(latest(lib) / "output/ahi_analysis.json")["screen_matches"] == 1


def test_reject_input_library_nesting_and_existing_user_folder(tmp_path):
    src = make_source(tmp_path)
    with pytest.raises(ValueError, match="contain"):
        execute(src, src / "library")
    folder = tmp_path / "existing"
    folder.mkdir()
    (folder / "precious.txt").write_text("keep")
    with pytest.raises(ValueError, match="not an ET525A"):
        execute(src, folder)
    assert (folder / "precious.txt").read_text() == "keep"


def test_invalid_observation_is_rejected_before_import(tmp_path):
    src = make_source(tmp_path)
    p = tmp_path / "bad.csv"
    p.write_text("not,the,columns\n")
    with pytest.raises(ValueError, match="columns"):
        execute(src, tmp_path / "lib", p)
    assert not list((tmp_path / "lib/imports").iterdir())


def test_overlap_does_not_suppress_unrelated_day():
    sessions = [
        {"session_id": sid, "start_time": a, "end_time": b}
        for sid, a, b in [
            ("a", "2024-01-01T00:00:00", "2024-01-01T01:00:00"),
            ("b", "2024-01-01T00:30:00", "2024-01-01T01:30:00"),
            ("c", "2024-01-02T00:00:00", "2024-01-02T01:00:00"),
        ]
    ]
    result = period_rows(sessions, [], "daily", True)
    assert result[0]["metric_aggregation"].startswith("suppressed")
    assert not result[1]["metric_aggregation"].startswith("suppressed")


def test_workflow_rejects_capture_that_differs_from_initial_fingerprint(tmp_path, monkeypatch):
    from appbyescribe import workflow

    src = make_source(tmp_path)
    lib = tmp_path / "lib"
    execute(src, lib)
    pointer = (lib / "LATEST.json").read_bytes()
    # Force a new import, then simulate a stable core read of different bytes than the initial hash.
    (src / "new.dat").write_bytes(b"new")
    real = workflow.run

    def substituted(source, out):
        p = next(source.rglob("*m.bys"))
        old = p.read_bytes()
        p.write_bytes(old[:-1] + b"\x00")
        try:
            return real(source, out)
        finally:
            p.write_bytes(old)

    monkeypatch.setattr(workflow, "run", substituted)
    with pytest.raises(ValueError, match="changed during import"):
        execute(src, lib)
    assert (lib / "LATEST.json").read_bytes() == pointer
    assert len(list((lib / "imports").iterdir())) == 1


def test_workflow_rejects_symlink_swap_during_fingerprint(tmp_path, monkeypatch):
    from appbyescribe import decoder as et525a

    src = make_source(tmp_path)
    outside = tmp_path / "outside"
    outside.write_bytes(b"private")
    target = next(src.rglob("*m.bys"))
    real = et525a.os.open
    swapped = False

    def attack(path, flags, *args, **kwargs):
        nonlocal swapped
        if path == target.name and not swapped and kwargs.get("dir_fd") is not None:
            swapped = True
            target.unlink()
            target.symlink_to(outside)
        return real(path, flags, *args, **kwargs)

    monkeypatch.setattr(et525a.os, "open", attack)
    with pytest.raises(ValueError, match="read stably"):
        execute(src, tmp_path / "lib")
    assert not list((tmp_path / "lib/imports").iterdir())
