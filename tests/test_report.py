"""Report presentation must retain uncertainty, coverage and usable export links."""

import re
from html import unescape
from pathlib import Path

from appbyscribe.report import interval, number, plot
from appbyscribe.workflow import execute
from test_decoder import make_source
from test_workflow import observation, prepare


def test_report_keeps_ahi_and_periods_visible_with_detail_collapsed(tmp_path):
    src = make_source(tmp_path)
    prepare(src)
    result = execute(src, tmp_path / "library")
    report = Path(result["report"])
    page = report.read_text()
    assert "60.0" in page
    assert "AHI is provisional" in page
    assert "Calendar hours" in page and "Session hours" in page
    assert all(f"<h3>{period}</h3>" in page for period in ["Daily", "Weekly", "Monthly"])
    assert "<summary>Minute charts</summary>" in page
    assert "<summary>Exports and data completeness</summary>" in page
    assert "Zero oxygen/pulse slots mean unavailable" in page
    # All links resolve, including runs without a waveform export.
    for link in re.findall(r'href="([^"]+)"', page):
        assert (report.parent / unescape(link)).is_file(), link


def test_report_does_not_hide_withheld_ahi_reason(tmp_path):
    src = make_source(tmp_path)
    prepare(src)
    target = next(src.rglob("*m.bys"))
    data = bytearray(target.read_bytes())
    data[8 + 21] = 0
    target.write_bytes(data)
    result = execute(src, tmp_path / "library")
    page = Path(result["report"]).read_text()
    visible_summary = page.split("<details>", 1)[0]
    assert "1 session AHI estimate(s) withheld" in visible_summary
    assert "minute_complete" in visible_summary
    assert "Withheld; check failed" in visible_summary


def test_screen_disagreement_and_unmatched_observation_stay_visible(tmp_path):
    import csv

    src = make_source(tmp_path)
    prepare(src)
    row = observation()
    row["displayed_ahi"] = "59.9"
    other = dict(row, start_time="2024-01-03T00:00:00", end_time="2024-01-03T00:02:00")
    observations = tmp_path / "observations.csv"
    with observations.open("w") as f:
        writer = csv.DictWriter(f, fieldnames=list(row))
        writer.writeheader()
        writer.writerows([row, other])
    result = execute(src, tmp_path / "library", observations)
    page = Path(result["report"]).read_text().split("<details>", 1)[0]
    assert "1 screen disagreement(s)" in page
    assert "1 unmatched observation(s)" in page
    assert "60.0" in page and "59.9" in page


def test_conflict_only_report_is_readable(tmp_path):
    src = make_source(tmp_path)
    lib = tmp_path / "library"
    execute(src, lib)
    target = next(src.rglob("*m.bys"))
    data = bytearray(target.read_bytes())
    data[8 + 8] += 1
    target.write_bytes(data)
    result = execute(src, lib)
    page = Path(result["report"]).read_text()
    assert "1 conflicting session(s) excluded" in page
    assert "No sessions available" in page


def test_step_chart_retains_final_minute_without_drawing_across_gap():
    page = plot("Synthetic", [("channel", [(0, 1), (2, 1)])])
    bins = re.findall(r'<path d="M([\d.]+) [\d.]+ H([\d.]+)" stroke="#12657c"', page)
    assert len(bins) == 2
    assert float(bins[0][1]) < float(bins[1][0])
    assert float(bins[1][1]) == 885
    assert 'text-anchor="end">3</text>' in page


def test_compact_display_retains_overnight_date_and_half_up_rounding():
    assert number(2.05) == "2.1"
    assert number(None) is None
    assert (
        interval("2024-01-01T23:59:00", "2024-01-02T00:01:00")
        == "2024-01-01 23:59:00 → 2024-01-02 00:01:00"
    )
    assert (
        interval("2024-01-01T10:00:00", "2024-01-01T11:00:00") == "2024-01-01 10:00:00 → 11:00:00"
    )
