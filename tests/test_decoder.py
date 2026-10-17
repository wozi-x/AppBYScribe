"""Synthetic fixtures only; no patient data."""

import json
import struct

import pytest

from appbyescribe import decoder


def stamp(hour=23, minute=59, day=1):
    return bytes([24, 1, day, hour, minute, 0])


def summary():
    b = bytearray(98)
    b[:2] = b"\x31\x02"
    b[2:8], b[8:14] = stamp(), stamp(0, 1, 2)
    b[44:60] = b"ET525A-TEST00001"
    struct.pack_into("<H", b, 40, 2)
    struct.pack_into("<H", b, 60, 1)
    b[62:68] = stamp()
    b[-1] = 0xA5
    return bytes(b)


def minutes(corrupt=False):
    records = []
    for i in range(2):
        b = bytearray(22)
        struct.pack_into("<2H", b, 0, 100, 80)
        struct.pack_into("<H", b, 14, 500)
        b[16], b[18], b[21] = 8, 16, 0xFE
        if corrupt and i == 0:
            b[21] = 0
        records.append(bytes(b))
    return stamp() + struct.pack("<H", 2) + b"".join(records)


def make_source(tmp_path):
    root = tmp_path / "input"
    folder = root / "0000001"
    folder.mkdir(parents=True)
    (folder / "0000001s.bys").write_bytes(summary())
    (folder / "0000001m.bys").write_bytes(minutes())
    (root / "summer.bys").write_bytes(summary()[:62])
    return root


def test_raw_calendar_not_bcd():
    assert decoder.device_time(bytes([26, 11, 27, 3, 14, 45])).isoformat() == "2026-11-27T03:14:45"


@pytest.mark.parametrize("data", [b"", bytes([26, 13, 1, 1, 1, 1]), bytes([255, 1, 1, 1, 1, 1])])
def test_bad_dates(data):
    with pytest.raises(decoder.FormatError):
        decoder.device_time(data)


def test_summary_reconstructs_midnight():
    assert decoder.parse_summary(summary())["duration_minutes"] == 2


@pytest.mark.parametrize(
    "mutation", ["truncate", "model", "settings_count", "end_before_start", "marker"]
)
def test_invalid_summary(mutation):
    b = bytearray(summary())
    if mutation == "truncate":
        b = b[:-1]
    elif mutation == "model":
        b[44] = ord("Z")
    elif mutation == "settings_count":
        b[60] = 2
    elif mutation == "end_before_start":
        b[8:14] = stamp(22)
    else:
        b[-1] = 0
    with pytest.raises(decoder.FormatError):
        decoder.parse_summary(bytes(b))


def test_corrupt_record_preserves_next_index():
    _, _, records, issues = decoder.parse_records(minutes(True), 22)
    assert [i for i, _ in records] == [1]
    assert issues[0]["source_offset"] == 8


def test_truncation_and_trailing_bytes_are_reported():
    _, _, records, issues = decoder.parse_records(minutes()[:-4], 22)
    assert len(records) == 1
    assert {v["code"] for v in issues} == {
        "length_count_mismatch",
        "missing_records",
        "unparsed_tail",
    }


def test_declared_count_is_unsigned():
    _, count, _, _ = decoder.parse_records(stamp() + struct.pack("<H", 40000), 22)
    assert count == 40000


def test_end_to_end_privacy_nulls_and_midnight(tmp_path):
    root = make_source(tmp_path)
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    out = tmp_path / "output"
    result = decoder.run(root, out)
    assert result["counts"]["sessions"] == 1
    assert result["counts"]["minute_records"] == 2
    assert result["sessions"][0]["ahi"] is None
    assert result["source_hashes_unchanged"]
    assert result["index_checks"][0]["exact_multiset_match_to_session_bases"]
    assert [d["total_session_elapsed_hours"] for d in result["daily_summary"]] == [1 / 60, 1 / 60]
    assert before == {p: p.read_bytes() for p in before}
    import csv

    rows = list(csv.DictReader((out / "output" / "timeseries.csv").open()))
    assert rows[0]["leak_probable_L_min"] == "0.0"
    assert rows[0]["spo2"] == ""
    assert rows[0]["spo2_slot_raw"] == "0"


def test_does_not_write_into_source(tmp_path):
    root = make_source(tmp_path)
    with pytest.raises(ValueError):
        decoder.run(root, root / "results")


def test_no_stale_output_reuse(tmp_path):
    root = make_source(tmp_path)
    decoder.run(root, tmp_path / "output")
    with pytest.raises(ValueError):
        decoder.run(root, tmp_path / "output")


def test_duplicate_sessions_do_not_double_daily_time(tmp_path):
    root = make_source(tmp_path)
    folder = root / "0000002"
    folder.mkdir()
    (folder / "0000002s.bys").write_bytes(summary())
    (folder / "0000002m.bys").write_bytes(minutes())
    result = decoder.run(root, tmp_path / "output")
    assert result["duplicate_pairs"] and result["overlap_pairs"]
    assert sum(d["total_session_elapsed_hours"] for d in result["daily_summary"]) == 2 / 60


def test_unknown_bys_reported(tmp_path):
    root = make_source(tmp_path)
    (root / "mystery.bys").write_bytes(b"unrecognized")
    result = decoder.run(root, tmp_path / "output")
    assert any(d["code"] == "unrecognized_or_unpaired_bys" for d in result["diagnostics"])


def test_missing_minute_file_preserves_summary(tmp_path):
    root = make_source(tmp_path)
    next(root.rglob("*m.bys")).unlink()
    result = decoder.run(root, tmp_path / "output")
    assert result["counts"]["sessions"] == 1
    assert result["counts"]["minute_records"] == 0
    assert any(d["code"] == "missing_or_ambiguous_minute_file" for d in result["diagnostics"])


def test_detail_channels_and_marker(tmp_path):
    root = make_source(tmp_path)
    b = bytes([1]) * 600 + bytes([2]) * 600 + b"\xfe"
    (root / "0000001" / "0000001d.bys").write_bytes(stamp() + struct.pack("<H", 2) + b * 2)
    result = decoder.run(root, tmp_path / "output")
    assert result["counts"]["detail_blocks"] == 2
    raw = json.loads((tmp_path / "output/output/raw_detail_blocks.json").read_text())
    assert raw[1]["source_offset"] == 1209
    assert bytes.fromhex(raw[1]["channel_a_hex"]) == bytes([1]) * 600
    assert bytes.fromhex(raw[1]["channel_b_hex"]) == bytes([2]) * 600


def test_extra_complete_record_is_diagnostic():
    _, count, records, issues = decoder.parse_records(minutes() + minutes()[8:30], 22)
    assert len(records) == count == 2
    tail = next(i for i in issues if i["code"] == "unparsed_tail")
    assert tail["length"] == 22


def test_minute_date_mismatch_is_not_invented_timeline(tmp_path):
    root = make_source(tmp_path)
    path = next(root.rglob("*m.bys"))
    path.write_bytes(stamp(23, 58) + minutes()[6:])
    result = decoder.run(root, tmp_path / "output")
    assert any(d["code"] == "minute_summary_mismatch" for d in result["diagnostics"])
    assert not (tmp_path / "output/output/timeseries.csv").exists()
