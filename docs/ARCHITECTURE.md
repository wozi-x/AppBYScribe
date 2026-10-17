# Architecture

| Module | Responsibility |
|---|---|
| `workflow.py` | Stable imports, library lock, deduplication and versioned publication |
| `decoder.py` | Binary parsing, raw archives, validation and byte provenance |
| `analysis.py` | Statistics, calendar coverage, byte ledger and streamed waveform CSV |
| `ahi.py` | Integrity-gated estimates, exact-session comparisons and period totals |
| `report.py` | Offline HTML/SVG: key results first, expandable details |

Imports are published only when the initial fingerprint, captured inventory and final fingerprint agree. Original files are archived with hashes; malformed and unknown bytes remain available.

Sessions are grouped by serial/start time. Shared payloads must agree; missing detail can enrich a session. Conflicting versions are retained but excluded from combined totals. Combined files reorganize unchanged bytes; `history_provenance.json` maps them to original imports.

Reports are built in a temporary directory and published as a new version. `LATEST.json` advances only after success. An import can survive a failed report build. Normal runs never overwrite completed archives or reports.

Public source and synthetic tests live outside `private/`. Each library also gets a `.gitignore` that ignores all its contents, including reports and temporary builds. No patient-specific constants or runtime network dependencies belong in the package.
