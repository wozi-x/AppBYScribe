# Daily workflow

1. Finish therapy and let the machine finish writing before removing the card, following its instructions. Photograph the session AHI and usage display before another session replaces it.
2. Copy the whole device folder into a dated directory under `private/card-copies/`. Do not rename internal files. A stable copy is preferable to a card still being written.
3. Run `appbyescribe INPUT --library private/library` from the project directory.
4. Open `private/library/index.html`. Keep the same library for subsequent imports and back up the whole `private/` directory separately from Git.

An input can be a device folder, or a card root containing exactly one `ET525A-*` folder. If multiple folders exist, select one explicitly. The library and input must not contain each other. No input files or machine settings are modified.

## Machine-screen observations

The empty public template is `examples/observations_template.csv`. Save filled copies under `private/`. Required columns:

| Column | Content |
|---|---|
| `model_serial` | Exact device serial |
| `start_time`, `end_time` | Exact device wall-clock timestamps, `YYYY-MM-DDTHH:MM:SS`, no timezone suffix |
| `displayed_ahi` | AHI shown for that exact session |
| `displayed_usage_hours` | Session usage shown; may be blank |
| `notes` | Screen scope, interruptions, photo filename and uncertainties |

Use start/end timestamps from the extracted report. Do not guess session identity from a matching AHI or rounded duration. A daily-total screen must not be assigned to one interval when several sessions contribute to it.

`appbyescribe --library private/library --observations private/observations.csv` adds observations and rebuilds without reading the card. Saved observations are reused on later runs. Unmatched rows remain unmatched; disagreements are displayed without tuning the formula. Conflicting values for the same session are rejected. If correcting a saved observation, retain the old CSV outside the library, remove that old observation source from `private/library/observations/`, and rebuild with the corrected CSV. Previous reports remain unchanged.

## Output locations

| Path inside the library | Content |
|---|---|
| `imports/<hash>/raw/source_files.json` | Every original file as hex, with path, length and SHA-256 |
| `imports/<hash>/inventory.json` | Original file inventory |
| `imports/<hash>/output/` | Per-import extraction and diagnostics, including orphan records |
| `reports/<timestamp>/report.html` | Combined offline report |
| `reports/<timestamp>/output/ahi_sessions.csv` | Estimates, evidence, failed checks and screen comparisons |
| `reports/<timestamp>/output/timeseries.csv` | Time-valid minute records and probable physical fields |
| `reports/<timestamp>/output/session_statistics.csv` | Mean, minimum, median, P90, P95 and maximum |
| `reports/<timestamp>/output/*coverage_summary.csv` | Midnight-split calendar coverage and metric statistics |
| `reports/<timestamp>/output/ahi_*_session_cohorts.csv` | Whole-session AHI grouped by start date/week/month |
| `reports/<timestamp>/output/waveform_samples.csv` | Structurally accepted sample pairs and original offsets |
| `reports/<timestamp>/output/settings_candidates.csv` | History/settings candidates, when present |
| `reports/<timestamp>/output/byte_segments.csv` | Complete combined-source byte ledger |
| `reports/<timestamp>/history_provenance.json` | Combined files mapped to original imports |
| `reports/<timestamp>/history_conflicts.json` | Conflicting versions excluded from combined totals |

Combined reports reorganize unchanged bytes and deduplicate sessions. Original index files, metadata, rejected bytes and unpaired data remain in the immutable per-import archives. Raw preservation does not mean every byte's meaning is understood. Core legacy `ahi` fields remain empty; the estimate fields are in `ahi_sessions.csv`.

## Deduplication and recovery

Exact imports are identified by paths, sizes and hashes. Sessions are grouped by serial and start time, and shared data must agree before merging. New detail can enrich an existing session. Differing end times, summary/history or minute/detail payloads create a conflict; all versions remain archived and the session is excluded from combined totals. This may happen when an in-progress session is later exported as complete. Review both versions instead of automatically trusting the newest one.

Unstable inputs are not published as completed imports. Report versions are preserved and `LATEST.json` advances only after a successful rebuild. If reporting fails after an import succeeds, retry with only `--library`.

Only one process may write a library. After a crash, inspect `.import.lock` and verify its process is no longer running before removing only the stale lock. Once no process is active, leftover `.import-*` and `.build-*` temporary directories can be removed. Do not manually edit completed import archives or reports.

## Limits

- Unknown device timezone and clock accuracy; no implicit UTC conversion.
- Elapsed session time is not proven sleep time or mask-on time.
- Missing dates are unknown, not zero use. No adherence denominator is invented.
- Waveform channel names, gain and baseline remain unresolved.
- Oxygen/pulse slots stay raw; zero is not a measured physiological value.
- Input over 512 MiB is rejected. Raw archives still use memory; waveform CSVs are streamed but can be much larger than binary files. Retained reports also consume disk space.
- A card export does not establish that every internal machine operation was recorded.
