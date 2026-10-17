# Security and privacy

Store personal data under `private/` and back it up separately from Git. Report libraries contain device identifiers and health data. Ignore rules and the staged-file audit reduce accidental publication; they are not encryption and cannot remove previously committed data.

Processing is local. Inputs are read-only, checked for stability, and rejected if they contain symlinks or special entries. Library writes are locked. Never execute binary input; large exports and retained report versions can consume substantial storage.

Report bugs with a minimal synthetic reproducer. No private vulnerability-reporting channel is configured yet; do not post sensitive details publicly. Maintainers should configure private reporting when the repository is hosted.
