from datetime import datetime
import pytest

from appbyscribe.analysis import percentile, stats, period_rows, period_bounds, METRICS, enrich
from test_decoder import make_source, decoder


def session(sid, start, end):
    return {"session_id": sid, "start_time": start, "end_time": end}


def row(sid, stamp, value):
    return {
        "session_id": sid,
        "timestamp": stamp,
        "confidence": "probable",
        **{k: value for k in METRICS},
    }


def test_midnight_bin_split_is_seconds_weighted():
    sessions = [session("s", "2024-01-01T23:59:26", "2024-01-02T00:01:26")]
    rows = [row("s", "2024-01-01T23:59:26", 10), row("s", "2024-01-02T00:00:26", 20)]
    out = period_rows(sessions, rows, "daily")
    assert out[0]["recorded_elapsed_seconds"] == 34
    assert out[1]["recorded_elapsed_seconds"] == 86
    assert out[1]["ipap_probable_cmH2O_mean"] == pytest.approx((26 * 10 + 60 * 20) / 86)
    assert sum(r["minute_data_weight_seconds"] for r in out) == 120


def test_week_counts_unique_sessions_not_daily_touches():
    sessions = [session("s", "2024-01-01T23:59:00", "2024-01-02T00:01:00")]
    out = period_rows(sessions, [], "weekly")
    assert len(out) == 1 and out[0]["unique_sessions_touching_period"] == 1
    assert out[0]["dates_with_records"] == 2 and out[0]["calendar_days_in_period"] == 7


def test_no_zero_use_rows_for_unobserved_dates():
    sessions = [
        session("a", "2024-01-01T10:00:00", "2024-01-01T11:00:00"),
        session("b", "2024-01-03T10:00:00", "2024-01-03T11:00:00"),
    ]
    out = period_rows(sessions, [], "daily")
    assert [r["period_start"] for r in out] == ["2024-01-01", "2024-01-03"]
    assert all(r["ahi"] is None for r in out)


def test_inverse_cdf_does_not_interpolate_unobserved_pressure():
    assert percentile([4, 12], [60, 60], 0.9) == 12
    assert stats([0, 4], [60, 60])["mean"] == 2
    assert stats([], [])["mean"] is None


def test_calendar_year_boundary():
    a, b = period_bounds(datetime(2024, 12, 30), "monthly")
    assert a.isoformat() == "2024-12-01T00:00:00"
    assert b.isoformat() == "2025-01-01T00:00:00"


def test_overlap_union_and_metric_suppression():
    s = [
        session("a", "2024-01-01T10:00:00", "2024-01-01T11:00:00"),
        session("b", "2024-01-01T10:30:00", "2024-01-01T11:30:00"),
    ]
    out = period_rows(s, [row("a", "2024-01-01T10:00:00", 6)], "daily", True)
    assert out[0]["recorded_elapsed_seconds"] == 5400
    assert out[0]["ipap_probable_cmH2O_mean"] is None


def test_byte_audit_covers_unknown_and_truncated_files(tmp_path):
    src = make_source(tmp_path)
    (src / "unknown.bys").write_bytes(bytes(range(256)))
    (src / "orphanm.bys").write_bytes(bytes(7))
    out = tmp_path / "output"
    decoder.run(src, out)
    result = enrich(out)
    coverage = result["coverage"]["files"]
    assert all(r["unaccounted_bytes"] == 0 and r["raw_roundtrip_exact"] for r in coverage)
    assert sum(r["source_bytes"] for r in coverage) == sum(
        p.stat().st_size for p in src.rglob("*") if p.is_file()
    )
