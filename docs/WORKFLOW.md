# Daily workflow

1. End therapy and let the machine finish writing before removing the card, following its instructions. Photograph session AHI and usage before another session replaces the display.
2. Copy the complete device folder to `private/card-copies/YYYY-MM-DD/`; preserve internal names.
3. Run `appbyscribe INPUT --library private/library` and open `private/library/index.html`.
4. Reuse the library for future imports. Back up `private/` separately; Git intentionally excludes it.

`INPUT` may be a device folder or a card root with exactly one `ET525A-*` folder. Select explicitly if there are several. Input and library must not contain each other. Inputs and machine settings are never changed. Run `appbyscribe --library private/library` to rebuild saved data without the card.

## Screen observations

Copy `examples/observations_template.csv` to `private/observations.csv`. Keep all columns:

| Column | Value |
|---|---|
| `model_serial` | Exact device serial |
| `start_time`, `end_time` | Exact report timestamps: `YYYY-MM-DDTHH:MM:SS`, no timezone suffix |
| `displayed_ahi` | AHI for that exact session |
| `displayed_usage_hours` | Displayed session hours; may be blank |
| `notes` | Optional screen scope, photo filename or uncertainty |

```sh
appbyscribe --library private/library --observations private/observations.csv
```

Observations persist across runs. Match the actual session; rounded usage or matching AHI alone cannot identify it. Do not assign a daily-total screen to one interval if several sessions contributed. Disagreements and unmatched rows remain visible; conflicting readings are rejected.

To correct a saved reading, preserve the old CSV outside `library/observations/`, remove that source from `library/observations/`, and rebuild with the corrected CSV. Previous reports remain unchanged.

## Library structure

```text
private/
  card-copies/YYYY-MM-DD/DEVICE_FOLDER/
  observations.csv
  photos/
  library/
    .gitignore                    Ignores all library contents
    index.html                    Link to latest report
    LATEST.json                   Latest successful version
    observations/                 Saved screen readings
    imports/<hash>/               Original archives, inventory, extraction
    reports/<timestamp>/          Combined report and exports
```

Inside each report version:

| File | Content |
|---|---|
| `report.html` | Session AHI, daily/weekly/monthly summaries and expandable charts |
| `output/ahi_sessions.csv` | Estimates, screen comparisons, failed checks and alternatives |
| `output/ahi_*_session_cohorts.csv` | Whole-session AHI grouped by start date/week/month |
| `output/*coverage_summary.csv` | Midnight-split time coverage and metric statistics |
| `output/timeseries.csv`, `output/session_statistics.csv` | Valid minute measurements; mean, min, median, P90, P95, max |
| `output/waveform_samples.csv`, `output/raw_minute_records.csv` | Accepted raw samples and minute records |
| `output/settings_candidates.csv` | Probable settings/history, when present |
| `output/byte_segments.csv`, `output/byte_coverage.json` | Byte accounting |
| `history_provenance.json`, `history_conflicts.json` | Original-source links and excluded conflicting versions |

Original files, indexes, metadata and rejected/unpaired records remain under `imports/<hash>/`: `raw/source_files.json` stores exact bytes as hex with hashes; `inventory.json` lists files; `output/` holds extraction and diagnostics. Core legacy `ahi` fields are empty; use `ahi_sessions.csv` for estimates.

## Recovery and limits

- **Duplicate import:** harmless. Identical content is reused. Missing detail can enrich an existing session; differing shared data creates an excluded conflict. Review both versions, including incomplete vs completed sessions, rather than assuming the newest is correct.
- **Unstable input:** retry from a stopped, stable card copy. No completed import is published for a failed stability check.
- **Failed report:** retry with `--library` only. The previous successful report stays available.
- **Stale lock after a crash:** inspect `.import.lock` and verify its process is no longer running before removing it. Only then remove leftover `.import-*` or `.build-*` directories if needed. Never edit completed imports or reports.
- **Capacity:** input is limited to 512 MiB. Raw archives use memory; streamed waveform CSVs and retained versions can require much more disk space than the card data.

Times use the device clock with unknown timezone/accuracy. Elapsed time is not proven sleep or mask-on time. Missing dates are unknown; no adherence rate is inferred. Physical labels remain probable, waveform scaling is unresolved, and zero oxygen/pulse slots are unavailable. See [FORMAT.md](FORMAT.md) for exact confidence and validation rules.
