"""Portable offline HTML/SVG report. No plotting packages, network or hardcoded capture values."""

import csv
import html
import json
from decimal import Decimal, ROUND_HALF_UP
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
    xmax = (max(x for x, y in points) + (1 if step else 0)) or 1
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


def number(value, places=1):
    """Display precision only; exported values keep their original precision."""
    if value is None or value == "":
        return None
    return str(Decimal(str(value)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


def interval(start, end):
    """Keep both dates for overnight sessions; omit only a repeated end date."""
    end_label = end[11:] if start[:10] == end[:10] else end.replace("T", " ")
    return start.replace("T", " ") + " → " + end_label


def period_table(review, ahi, frequency):
    coverage = {r["period_start"]: r for r in review["periods"][frequency]}
    cohorts = {r["period_start"]: r for r in ahi["cohorts"][frequency]}
    rows = []
    for start in sorted(coverage.keys() | cohorts.keys()):
        c, a = coverage.get(start, {}), cohorts.get(start, {})
        minutes = a.get("elapsed_minutes_whole_sessions")
        rows.append(
            [
                start,
                len(c["observed_dates"].split(";")) if c.get("observed_dates") else None,
                number(c.get("recorded_elapsed_hours"), 2),
                a.get("sessions", 0),
                number(minutes / 60 if minutes is not None else None, 2),
                number(a.get("ahi_estimate")),
            ]
        )
    return table(
        [
            "Period starts",
            "Days recorded",
            "Calendar hours",
            "Sessions started",
            "Session hours",
            "AHI estimate",
        ],
        rows,
    )


def session_details(session, rows, counters, review):
    sid = session["session_id"]
    sub = [r for r in rows if r["session_id"] == sid and r["confidence"].startswith("probable")]
    raw = [r for r in counters if r["session_id"] == sid]
    stats = [r for r in review["session_statistics"] if r["session_id"] == sid]
    parts = [
        f"<details><summary>{esc(session['start_time'].replace('T', ' '))} · {session['duration_minutes']:g} min</summary>",
        table(
            ["Metric (probable units)", "Mean", "Min", "Median", "P90", "P95", "Max"],
            [
                [r["label"] + " (" + UNITS[r["metric"]] + ")"]
                + [number(r[k], 2) for k in ("mean", "minimum", "median", "p90", "p95", "maximum")]
                for r in stats
            ],
        ),
        "<details><summary>Minute charts</summary>",
    ]
    for metric, label in METRICS.items():
        data = [(float(r["elapsed_seconds"]) / 60, float(r[metric])) for r in sub]
        parts.append(plot(label + " (" + UNITS[metric] + ", probable)", [(label, data)]))
    parts.append("</details><details><summary>Event and unknown counters</summary>")
    for off, label in [
        (5, "OA candidate"),
        (6, "CA candidate"),
        (7, "H candidate"),
        (8, "Unknown byte 8"),
        (9, "Unknown byte 9"),
    ]:
        data = [(int(r["record_index"]), int(r[f"byte_{off}"])) for r in raw]
        parts.append(plot(label + " raw minute counter", [(label, data)]))
    parts.append("</details></details>")
    return "".join(parts)


def export_links(root):
    """Link only files that exist, including empty-data runs."""
    links = [
        ("output/ahi_sessions.csv", "AHI and screen checks"),
        ("output/timeseries.csv", "Minute measurements"),
        ("output/session_statistics.csv", "Full statistics"),
        ("output/waveform_samples.csv", "Raw waveforms"),
        ("output/raw_minute_records.csv", "Raw minute records"),
        ("output/settings_candidates.csv", "Settings candidates"),
        ("output/byte_coverage.json", "Byte accounting"),
        ("output/byte_segments.csv", "Byte ledger"),
        ("output/analysis.json", "Validation details"),
        ("output/unmatched_screen_observations.json", "Unmatched observations"),
        ("history_provenance.json", "Original-source provenance"),
        ("history_conflicts.json", "Excluded conflicts"),
    ]
    for frequency in ("daily", "weekly", "monthly"):
        links.extend(
            [
                (f"output/{frequency}_coverage_summary.csv", f"{frequency.title()} coverage"),
                (f"output/ahi_{frequency}_session_cohorts.csv", f"{frequency.title()} AHI"),
            ]
        )
    return (
        '<ul class="exports">'
        + "".join(
            f'<li><a href="{esc(path)}">{esc(label)}</a></li>'
            for path, label in links
            if (root / path).is_file()
        )
        + "</ul>"
    )


def generate(root, ahi, conflicts):
    report = json.loads((root / "output/analysis.json").read_text())
    review = json.loads((root / "output/review_analysis.json").read_text())
    rows = read_rows(root, "timeseries.csv")
    counters = read_rows(root, "raw_minute_records.csv")
    sessions = report["sessions"]
    withheld = [r for r in ahi["sessions"] if r["ahi_estimate"] is None]
    dates = (
        min(s["start_time"] for s in sessions)[:10]
        + " to "
        + max(s["end_time"] for s in sessions)[:10]
        if sessions
        else "No sessions available for combined reporting"
    )
    parts = [
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'; img-src data:; connect-src 'none'\">",
        "<title>AppBYScribe report</title><style>",
        "body{font:15px/1.5 system-ui,sans-serif;color:#183641;max-width:1120px;margin:28px auto;padding:0 20px;background:#f7fafb}h1{margin-bottom:4px}h2{font-size:21px;margin-top:28px}h3{font-size:17px}a{color:#12657c}table{border-collapse:collapse;width:100%;background:white}td,th{border-bottom:1px solid #cbd6da;text-align:left;padding:8px;vertical-align:top}.table{overflow:auto}.note{padding:12px;background:#fff1d8;border-left:4px solid #bd5a13}.muted{color:#46606b}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:10px;margin:18px 0}.card{background:#e4eff2;border-radius:8px;padding:12px}.card strong{display:block;font-size:24px}summary{cursor:pointer;font-weight:600;padding:11px;background:#e4eff2}details{margin:12px 0}svg{display:block;width:100%;font:12px sans-serif}figure{margin:18px 0}figcaption{font-weight:600}.exports{columns:2}.small{font-size:13px}@media(max-width:650px){.cards{grid-template-columns:repeat(2,1fr)}.exports{columns:1}body{padding:0 12px}td,th{padding:6px}}@media print{body{background:white;margin:0}.table{overflow:visible}details{break-inside:avoid}a{color:inherit}}",
        "</style></head><body><h1>AppBYScribe</h1>",
        f'<p class="muted">ET525A · {esc(dates)} · device clock; timezone unknown</p>',
        '<div class="cards">',
        f'<div class="card"><strong>{len(sessions)}</strong>recorded sessions</div>',
        f'<div class="card"><strong>{review["minute_coverage_minutes"]:g} min</strong>minute-record coverage</div>',
        f'<div class="card"><strong>{review["waveform_coverage_minutes"]:g} min</strong>waveform coverage</div>',
        f'<div class="card"><strong>{ahi["screen_matches"]}</strong>session screen matches</div></div>',
        "<p><strong>AHI is provisional:</strong> candidate event counters ÷ elapsed hours. A screen match supports that session only; event subtypes and other modes/firmware remain unvalidated. Failed integrity checks withhold the estimate.</p>",
    ]
    alerts = []
    if conflicts:
        alerts.append(
            f'{len(conflicts)} conflicting session(s) excluded; <a href="history_conflicts.json">review versions</a>.'
        )
    if withheld:
        alerts.append(f"{len(withheld)} session AHI estimate(s) withheld; see failed checks below.")
    if ahi["screen_disagreements"]:
        alerts.append(
            f"{ahi['screen_disagreements']} screen disagreement(s); estimates have not been adjusted to force a match."
        )
    if ahi["unmatched_observations"]:
        alerts.append(
            f'{ahi["unmatched_observations"]} unmatched observation(s); <a href="output/unmatched_screen_observations.json">review readings</a>.'
        )
    if alerts:
        parts.append('<div class="note">' + "<br>".join(alerts) + "</div>")
    parts.extend(
        [
            "<h2>Session AHI</h2>",
            table(
                [
                    "Start → end (device clock)",
                    "Minutes",
                    "Candidate events",
                    "AHI estimate",
                    "Screen AHI",
                    "Evidence",
                ],
                [
                    [
                        interval(r["start_time"], r["end_time"]),
                        r["elapsed_minutes"],
                        r["event_counter_total_raw"],
                        r["ahi_estimate_display_1dp"],
                        r["displayed_ahi"],
                        STATUS[r["status"]],
                    ]
                    for r in ahi["sessions"]
                ],
            )
            if sessions
            else "<p>No eligible session history. Check excluded conflicts and original imports.</p>",
        ]
    )
    if withheld:
        parts.append(
            table(
                ["Session start", "Failed checks"],
                [[r["start_time"], r["failed_checks"]] for r in withheld],
            )
        )
    parts.extend(
        [
            '<p class="small">Screen comparisons also check usage when supplied. AHI is shown to one decimal; manufacturer rounding may differ. Elapsed time is not proven sleep or mask-on time.</p>',
            "<h2>Daily, weekly and monthly summaries</h2>",
            "<p>Available records only; missing dates are unknown. <strong>Calendar hours</strong> split at midnight. <strong>Session hours and AHI</strong> assign whole sessions to their start date. AHI = total counters ÷ total session hours; it is unavailable if any included session fails its checks.</p>",
        ]
    )
    for frequency in ("daily", "weekly", "monthly"):
        parts.extend([f"<h3>{frequency.title()}</h3>", period_table(review, ahi, frequency)])
    parts.extend(
        [
            "<h2>Measurements</h2>",
            "<p>Expand a session for statistics and charts. Physical labels/units are probable; each segment represents one minute and missing bins stay blank. Zero oxygen/pulse slots mean unavailable.</p>",
        ]
    )
    parts.extend(session_details(s, rows, counters, review) for s in sessions)
    parts.extend(
        [
            "<details><summary>Exports and data completeness</summary>",
            f"<p>{review['high_frequency_sample_pairs']:,} raw waveform pairs from accepted blocks. Physical waveform units remain unresolved; only session-consistent detail files count toward coverage.</p>",
            "<p>All original bytes, including unknown/rejected data, remain in the import archives. Combined reports reorganize unchanged bytes; provenance links back to originals. A card export does not establish that every machine operation was recorded.</p>",
            export_links(root),
            "</details>",
            f"<details><summary>Diagnostics ({len(report['diagnostics'])})</summary>",
            table(
                ["Code", "File / context"],
                [
                    [d["code"], d.get("source_file", d.get("reason", "See validation details"))]
                    for d in report["diagnostics"]
                ],
            )
            if report["diagnostics"]
            else "<p>No combined-report diagnostics.</p>",
            "<p>Per-import diagnostics, including orphan records, remain in imports/&lt;hash&gt;/output/analysis.json.</p></details>",
            '<p class="small muted">Local research report; not clinically validated. Open the sections you need before printing. Full precision and evidence remain in the CSV/JSON exports.</p></body></html>',
        ]
    )
    (root / "report.html").write_text("".join(parts), encoding="utf-8")
