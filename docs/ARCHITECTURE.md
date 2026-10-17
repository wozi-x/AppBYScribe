# Architecture

`workflow.execute()` selects one device folder, obtains a no-follow fingerprint, imports into a temporary directory and publishes an immutable import only if the captured inventory matches the stable input. A lock serializes library writes.

`decoder.run()` preserves complete source bytes, parses summary/index/minute/detail structures, and records malformed regions and missing associations. `analysis.enrich()` creates byte ledgers, metric statistics, partial calendar summaries and streamed waveform CSVs. `ahi.build()` applies integrity gates and observation comparisons. `report.generate()` produces offline HTML and SVG without JavaScript or external dependencies.

History groups sessions by serial/start time. All shared payloads must agree; missing detail can be added, while conflicts are retained and excluded from combined totals. Combined files use stable internal identities and preserve a provenance map to original imports. They are not claimed to reproduce the original directory tree; each import's raw archive does that.

Build outputs are versioned and the latest pointer advances after successful reporting. Original files and completed reports are never overwritten by normal execution. A successful import can survive a failed report rebuild.

The package intentionally has no patient-specific constants. Test fixtures generate binary bytes in temporary directories and use an explicit synthetic identifier. Keep extensions to mappings and reporting independently testable and retain unknown bytes for future work.
