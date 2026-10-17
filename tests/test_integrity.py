"""Filesystem snapshot integrity and index identity regressions (synthetic only)."""

import json
import struct

import pytest
from test_decoder import decoder, make_source, summary


def archive(out):
    return {
        r["source_file"]: bytes.fromhex(r["raw_hex"])
        for r in json.loads((out / "raw/source_files.json").read_text())
    }


def after_capture(monkeypatch, action):
    original = decoder.scan_source_tree

    def scan(source, capture):
        result = original(source, capture)
        if capture:
            action()
        return result

    monkeypatch.setattr(decoder, "scan_source_tree", scan)


def test_initial_file_and_directory_symlinks_are_not_followed(tmp_path):
    src = make_source(tmp_path)
    outside = tmp_path / "external"
    outside.mkdir()
    (outside / "private.bys").write_bytes(b"not part of this snapshot")
    (src / "link.bys").symlink_to(outside / "private.bys")
    (src / "linked_directory").symlink_to(outside, target_is_directory=True)
    out = tmp_path / "out"
    result = decoder.run(src, out)
    assert result["source_hashes_unchanged"]
    assert {
        d["source_file"] for d in result["diagnostics"] if d["code"] == "symlink_not_followed"
    } == {"link.bys", "linked_directory"}
    assert all("link" not in name for name in archive(out))


@pytest.mark.parametrize(
    "mutation",
    [
        "addition",
        "deletion",
        "content",
        "same_bytes_replacement",
        "replacement_symlink",
        "added_symlink",
        "directory_symlink",
    ],
)
def test_changes_after_capture_are_reported_without_losing_snapshot(
    tmp_path, monkeypatch, mutation
):
    src = make_source(tmp_path)
    victim = next(src.rglob("*m.bys"))
    before = victim.read_bytes()
    rel = str(victim.relative_to(src))
    external = tmp_path / "external.bys"
    external.write_bytes(before)

    def change():
        if mutation == "addition":
            (src / "added.bys").write_bytes(b"new")
        elif mutation == "deletion":
            victim.unlink()
        elif mutation == "content":
            victim.write_bytes(before + b"changed")
        elif mutation == "same_bytes_replacement":
            replacement = tmp_path / "replacement"
            replacement.write_bytes(before)
            replacement.replace(victim)
        elif mutation == "replacement_symlink":
            victim.unlink()
            victim.symlink_to(external)
        elif mutation == "added_symlink":
            (src / "newlink.bys").symlink_to(external)
        else:
            folder = victim.parent
            saved = tmp_path / "moved_directory"
            folder.rename(saved)
            folder.symlink_to(saved, target_is_directory=True)

    after_capture(monkeypatch, change)
    out = tmp_path / "out"
    result = decoder.run(src, out)
    assert not result["source_hashes_unchanged"]
    assert any(d["code"] == "source_changed_during_analysis" for d in result["diagnostics"])
    assert archive(out)[rel] == before


def test_leaf_swapped_to_symlink_between_stat_and_open_is_not_read(tmp_path, monkeypatch):
    src = make_source(tmp_path)
    victim = next(src.rglob("*m.bys"))
    external = tmp_path / "external"
    external.write_bytes(b"must not be archived")
    original_open = decoder.os.open
    swapped = False

    def opening(path, flags, *args, **kwargs):
        nonlocal swapped
        if path == victim.name and not swapped:
            swapped = True
            victim.unlink()
            victim.symlink_to(external)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(decoder.os, "open", opening)
    out = tmp_path / "out"
    result = decoder.run(src, out)
    assert not result["source_hashes_unchanged"]
    assert any(d["code"] == "source_read_failed" for d in result["diagnostics"])
    assert str(victim.relative_to(src)) not in archive(out)


def test_parent_swapped_to_symlink_between_stat_and_open_is_not_traversed(tmp_path, monkeypatch):
    src = make_source(tmp_path)
    folder = next(src.rglob("*m.bys")).parent
    saved = tmp_path / "moved"
    original_open = decoder.os.open
    swapped = False

    def opening(path, flags, *args, **kwargs):
        nonlocal swapped
        if path == folder.name and not swapped:
            swapped = True
            folder.rename(saved)
            folder.symlink_to(saved, target_is_directory=True)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(decoder.os, "open", opening)
    out = tmp_path / "out"
    result = decoder.run(src, out)
    assert not result["source_hashes_unchanged"]
    assert any(d["code"] == "source_read_failed" for d in result["diagnostics"])
    assert all(not name.startswith(folder.name + "/") for name in archive(out))


def test_read_error_is_diagnostic_and_cannot_report_unchanged(tmp_path, monkeypatch):
    src = make_source(tmp_path)

    def unreadable(fd, length):
        raise OSError("synthetic interrupted read")

    monkeypatch.setattr(decoder.os, "read", unreadable)
    result = decoder.run(src, tmp_path / "out")
    assert not result["source_hashes_unchanged"]
    assert any(d["code"] == "source_read_failed" for d in result["diagnostics"])


def test_changed_during_read_is_detected_even_before_final_scan(tmp_path, monkeypatch):
    src = make_source(tmp_path)
    victim = next(src.rglob("*m.bys"))
    original_read = decoder.os.read
    changed = False

    def reading(fd, length):
        nonlocal changed
        data = original_read(fd, length)
        if data and not changed:
            changed = True
            victim.write_bytes(victim.read_bytes() + b"x")
        return data

    monkeypatch.setattr(decoder.os, "read", reading)
    result = decoder.run(src, tmp_path / "out")
    assert not result["source_hashes_unchanged"]
    assert any(d["code"] == "source_changed_during_read" for d in result["diagnostics"])


def test_completed_read_is_preserved_if_leaf_unlinked_while_open(tmp_path, monkeypatch):
    src = make_source(tmp_path)
    victim = next(src.rglob("*m.bys"))
    original_bytes = victim.read_bytes()
    original_read = decoder.os.read
    removed = False

    def reading(fd, length):
        nonlocal removed
        data = original_read(fd, length)
        if data and not removed:
            removed = True
            victim.unlink()
        return data

    monkeypatch.setattr(decoder.os, "read", reading)
    out = tmp_path / "out"
    result = decoder.run(src, out)
    assert not result["source_hashes_unchanged"]
    assert archive(out)[str(victim.relative_to(src))] == original_bytes


def test_conflicting_index_is_one_session_and_all_raw_versions_survive(tmp_path):
    src = make_source(tmp_path)
    altered = bytearray(summary()[:62])
    struct.pack_into("<H", altered, 14, 9)
    (src / "summer.bys").write_bytes(altered)
    out = tmp_path / "out"
    result = decoder.run(src, out)
    assert result["counts"]["sessions"] == 1
    assert result["sessions"][0]["summary_conflict"]
    assert result["validations"][0]["summary_conflict"]
    conflict = next(d for d in result["diagnostics"] if d["code"] == "index_session_conflict")
    assert conflict["session_ids"] == [result["sessions"][0]["session_id"]]
    assert bytes.fromhex(conflict["raw_base_hex"]) == altered
    assert archive(out)["summer.bys"] == altered
    assert result["source_hashes_unchanged"]


def test_index_only_conflicting_and_duplicate_rows_do_not_multiply_sessions(tmp_path):
    src = tmp_path / "source"
    src.mkdir()
    base = summary()[:62]
    altered = bytearray(base)
    struct.pack_into("<H", altered, 14, 9)
    (src / "summer.bys").write_bytes(base + base + altered)
    result = decoder.run(src, tmp_path / "out")
    assert result["counts"]["sessions"] == 1
    assert result["sessions"][0]["summary_conflict"]
    codes = {d["code"] for d in result["diagnostics"]}
    assert {"duplicate_index_representation", "index_session_conflict"} <= codes


def test_distinct_serial_or_time_index_entries_remain_distinct_sessions(tmp_path):
    src = make_source(tmp_path)
    other_device = bytearray(summary()[:62])
    other_device[44:60] = b"ET525A-TEST00002"
    other_time = bytearray(summary()[:62])
    other_time[2] += 1
    other_time[8] += 1
    (src / "summer.bys").write_bytes(summary()[:62] + other_device + other_time)
    result = decoder.run(src, tmp_path / "out")
    assert result["counts"]["sessions"] == 3
    assert not any(d["code"] == "index_session_conflict" for d in result["diagnostics"])
