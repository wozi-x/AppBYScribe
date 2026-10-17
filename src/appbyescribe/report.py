"""Portable offline HTML/SVG report. No plotting packages, network or hardcoded capture values."""

import csv
import html
import json
from .analysis import METRICS

UNITS = dict(zip(METRICS, ["cmH2O", "cmH2O", "cmH2O", "L/min", "breaths/min", "mL", "L/min", "%"]))
STATUS = {
    "screen_match": "Matches screen",
    "screen_disagreement": "Screen disagreement",
    "estimate_not_screen_checked": "Estimate; not yet compared",
    "withheld_integrity_check": "Withheld; check failed",
}


def esc(value):
    return html.escape(str(value))


def fmt(value):
    if value is None or value == "":
        return "Unavailable"
    return f"{value:.3f}".rstrip("0").rstrip(".") if isinstance(value, float) else esc(value)


def table(headers, rows):
    return (
        '<div class="table"><table><thead><tr>'
        + "".join("<th>" + esc(h) + "</th>" for h in headers)
        + "</tr></thead><tbody>"
        + "".join(
            "<tr>" + "".join("<td>" + fmt(v) + "</td>" for v in row) + "</tr>" for row in rows
        )
        + "</tbody></table></div>"
    )


def read_rows(root, name):
    p = root / "output" / name
    if not p.exists():
        return []
    with p.open() as f:
        return list(csv.DictReader(f))


def plot(title, series, xlabel="Elapsed minutes", step=True):
    points = [p for _, data in series for p in data]
    if not points:
        return "<p>" + esc(title) + ": no validated samples.</p>"
    xmax = max(x for x, y in points) or 1
    low, high = min(y for x, y in points), max(y for x, y in points)
    pad = max((high - low) * 0.08, 0.1)
    low -= pad
    high += pad

    def xy(x, y):
        return (65 + x / xmax * 820, 185 - (y - low) / (high - low) * 135)

    parts = [
        f'<figure><figcaption>{esc(title)}</figcaption><svg viewBox="0 0 920 230" role="img" aria-label="{esc(title)}">',
        '<rect width="920" height="230" fill="white"/>',
    ]
    for i in range(5):
        y = low + (high - low) * i / 4
        _, yy = xy(0, y)
        parts.append(
            f'<path d="M65 {yy:.2f} H885" stroke="#d9e3e7"/><text x="58" y="{yy + 4:.2f}" text-anchor="end">{y:.2f}</text>'
        )
    colors = ["#12657c", "#bd5a13", "#704ab0"]
    for k, (label, data) in enumerate(series):
        # Separate 60s bins: never draw through missing/corrupt minute indices.
        for i, (x, y) in enumerate(data):
            px, py = xy(x, y)
            if step:
                nx, _ = xy(x + 1, y)
                parts.append(
                    f'<path d="M{px:.2f} {py:.2f} H{min(nx, 885):.2f}" stroke="{colors[k % 3]}" stroke-width="2"/>'
                )
            elif i and x - data[i - 1][0] < 1:
                a, b = xy(*data[i - 1])
                parts.append(
                    f'<path d="M{a:.2f} {b:.2f} L{px:.2f} {py:.2f}" stroke="{colors[k % 3]}"/>'
                )
        parts.append(f'<text x="{65 + k * 260}" y="22" fill="{colors[k % 3]}">{esc(label)}</text>')
    parts.extend(
        [
            f'<text x="65" y="207">0</text><text x="885" y="207" text-anchor="end">{xmax:g}</text>',
            f'<text x="460" y="226" text-anchor="middle">{esc(xlabel)}</text></svg></figure>',
        ]
    )
    return "".join(parts)


def generate(root, ahi, conflicts):
    report = json.loads((root / "output/analysis.json").read_text())
    review = json.loads((root / "output/review_analysis.json").read_text())
    rows = read_rows(root, "timeseries.csv")
    counters = read_rows(root, "raw_minute_records.csv")
    sessions = report["sessions"]
    parts = [
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'; img-src data:; connect-src 'none'\">",
        "<title>AppByeScribe report</title><style>",
        "body{font:16px/1.55 system-ui,sans-serif;color:#183641;max-width:1120px;margin:32px auto;padding:0 20px;background:#f7fafb}h1{font-size:32px}h2{margin-top:32px}a{color:#12657c}table{border-collapse:collapse;width:100%;background:white}td,th{border-bottom:1px solid #cbd6da;text-align:left;padding:9px;vertical-align:top}.table{overflow:auto}.note{padding:16px;background:#fff1d8;border-left:4px solid #bd5a13}summary{cursor:pointer;font-weight:600;padding:14px;background:#dfedf2}details{margin:18px 0}svg{display:block;width:100%;font:12px sans-serif}figure{margin:18px 0}figcaption{font-weight:600}.small{font-size:13px}@media print{body{background:white}details{break-inside:avoid}.table{overflow:visible}summary{display:block}}",
        "</style></head><body><h1>AppByeScribe</h1><p>Recorded ET525A therapy data</p>",
        f"<p>{len(sessions)} unique recorded sessions · {review['minute_coverage_minutes']} minute samples · {review['waveform_coverage_minutes']} minutes with structurally consistent detail files.</p>",
        '<p class="note"><strong>AHI estimates are included.</strong> The provisional formula is candidate counter sum / elapsed session hours. Exact-session screen comparisons below test this rule; other sessions remain estimates. A matching total does not validate each event subtype or every firmware/mode. Missing or inconsistent data withhold the estimate.</p>',
        f"<p>Screen comparisons in this report: <strong>{ahi['screen_matches']} match(es), {ahi['screen_disagreements']} disagreement(s)</strong>; {ahi['unmatched_observations']} observations could not be joined to a session.</p>",
    ]
    if conflicts:
        parts.append(
            f'<p class="note"><strong>{len(conflicts)} conflicting session(s) excluded from combined totals.</strong> Review <a href="history_conflicts.json">history_conflicts.json</a>. All versions remain in the original import archives.</p>'
        )
    if ahi["screen_disagreements"]:
        parts.append(
            '<p class="note">A screen disagreement means the current AHI rule needs investigation. Estimates are retained for comparison and have not been adjusted to force a match.</p>'
        )
    parts += [
        "<h2>Session AHI</h2>",
        table(
            [
                "Start (device clock)",
                "End",
                "Minutes",
                "Raw counter total",
                "AHI estimate",
                "Screen AHI",
                "Status",
            ],
            [
                [
                    r["start_time"],
                    r["end_time"],
                    r["elapsed_minutes"],
                    r["event_counter_total_raw"],
                    r["ahi_estimate_display_1dp"],
                    r["displayed_ahi"],
                    STATUS[r["status"]],
                ]
                for r in ahi["sessions"]
            ],
        ),
        "<p>Device timezone is unknown. Elapsed time is not proven sleep time. Display comparisons use decimal rounding to one place; firmware rounding conventions may differ.</p>",
        "<h2>Calendar coverage</h2><p>Elapsed intervals are split at midnight. These tables describe available records, not complete weeks/months or adherence. Missing dates are unknown.</p>",
    ]
    for frequency in ["daily", "weekly", "monthly"]:
        parts.append("<h3>" + frequency.title() + "</h3>")
        parts.append(
            table(
                [
                    "Period starts",
                    "Observed dates",
                    "Unique sessions touching period",
                    "Recorded hours",
                ],
                [
                    [
                        r["period_start"],
                        r["observed_dates"],
                        r["unique_sessions_touching_period"],
                        r["recorded_elapsed_hours"],
                    ]
                    for r in review["periods"][frequency]
                ],
            )
        )
    parts += [
        "<h2>AHI by session-start period</h2><p>Whole sessions are assigned to their starting date. This keeps overnight events intact: these AHI cohorts differ from the midnight-split coverage above. The rate is total counters / total hours, never an average of session AHIs. A cohort with a withheld session has no aggregate estimate.</p>"
    ]
    for frequency in ["daily", "weekly", "monthly"]:
        parts.append("<h3>" + frequency.title() + " session cohort</h3>")
        parts.append(
            table(
                ["Device", "Period starts", "Sessions", "Whole-session minutes", "AHI estimate"],
                [
                    [
                        r["model_serial"],
                        r["period_start"],
                        r["sessions"],
                        r["elapsed_minutes_whole_sessions"],
                        r["ahi_estimate"],
                    ]
                    for r in ahi["cohorts"][frequency]
                ],
            )
        )
    parts.append(
        "<h2>All recorded minute metrics</h2><p>Physical labels and units remain probable. Each line segment is one recorded minute; gaps stay blank. Unknown channels are raw counters. Detailed statistics, raw bytes and provenance are available in output/.</p>"
    )
    for s in sessions:
        sid = s["session_id"]
        sub = [r for r in rows if r["session_id"] == sid and r["confidence"].startswith("probable")]
        raw = [r for r in counters if r["session_id"] == sid]
        parts.append(
            f"<details><summary>{esc(s['start_time'])} — {s['duration_minutes']:g} minutes</summary>"
        )
        stats = [r for r in review["session_statistics"] if r["session_id"] == sid]
        parts.append(
            table(
                ["Metric (probable units)", "Mean", "Minimum", "Median", "P90", "P95", "Maximum"],
                [
                    [
                        r["label"] + " (" + UNITS[r["metric"]] + ")",
                        r["mean"],
                        r["minimum"],
                        r["median"],
                        r["p90"],
                        r["p95"],
                        r["maximum"],
                    ]
                    for r in stats
                ],
            )
        )
        for metric, label in METRICS.items():
            data = [(float(r["elapsed_seconds"]) / 60, float(r[metric])) for r in sub]
            # Include a non-drawing endpoint so the final minute bin has its full width.
            if data:
                last = data[-1]
                data.append((last[0] + 1, last[1]))
            parts.append(plot(label + " (" + UNITS[metric] + ", probable)", [(label, data)]))
        for off, label in [
            (5, "OA candidate"),
            (6, "CA candidate"),
            (7, "H candidate"),
            (8, "Unknown byte 8"),
            (9, "Unknown byte 9"),
        ]:
            data = [(int(r["record_index"]), int(r[f"byte_{off}"])) for r in raw]
            if data:
                data.append((data[-1][0] + 1, data[-1][1]))
            parts.append(plot(label + " raw minute counter", [(label, data)]))
        parts.append("</details>")
    parts += [
        "<h2>Detailed signals and byte coverage</h2>",
        f"<p>{review['high_frequency_sample_pairs']:,} raw waveform pairs retained from valid structural blocks. Physical waveform units remain unresolved. Only detail files consistent with their session count and timestamps contribute to the {review['waveform_coverage_minutes']} minutes of detail coverage.</p>",
        '<p><a href="output/waveform_samples.csv">All waveform samples</a> · <a href="output/byte_coverage.json">Byte accounting</a> · <a href="output/ahi_sessions.csv">AHI comparisons</a> · <a href="output/session_statistics.csv">Full metric statistics</a></p>',
        '<p>Combined-report raw files are reorganized copies. <a href="history_provenance.json">History provenance</a> points to unchanged original import snapshots. Unknown fields remain preserved. Zero oxygen/pulse slots are unavailable values, not measured zero.</p>',
        "<h2>Diagnostics</h2>",
        table(
            ["Code", "File / context"],
            [
                [d["code"], d.get("source_file", d.get("reason", "See analysis.json"))]
                for d in report["diagnostics"]
            ],
        ),
        '<p class="small">No network requests, diagnosis, or device-setting changes. All processing is local. Expand session sections before printing if you want their graphs included.</p></body></html>',
    ]
    (root / "report.html").write_text("".join(parts))
