# Observed ET525A BYS layout

Offsets are zero-based decimal. Structure is distinguished from semantic confidence. This describes one observed format family, not every Yuwell model or firmware.

| File | Layout |
|---|---|
| `summer.bys` | Concatenated 62-byte session summary bases |
| `*s.bys` | 62-byte summary plus a declared number of 36-byte history blocks |
| `*m.bys` | 8-byte header plus declared 22-byte minute records |
| `*d.bys` | 8-byte header plus declared 1,201-byte detail blocks |

Calendar fields are six numeric bytes: year minus 2000, month, day, hour, minute, second. They are not BCD or Unix timestamps. Header record counts and most words are unsigned little-endian. History pressure limits are probable big-endian fields. There is no established checksum algorithm; constant record markers are not checksums.

## Summary base

| Offset | Length | Interpretation |
|---|---|---|
| 0 | 2 | Observed signature `31 02` |
| 2, 8 | 6 each | Start and end device calendar times |
| 14 | 2 | Raw total; checked against words 16/18/20 |
| 16, 18, 20 | 2 each | Candidate OA/CA/H totals; checked against minute bytes 5/6/7 |
| 22, 24 | 2 each | Unknown totals; checked against minute bytes 8/9 |
| 26, 28, 30 | 2 each | Unknown words |
| 32, 34 | 2 each | Probable mean IPAP/EPAP, divided by 10 |
| 36, 38 | 2 each | Unknown words |
| 40 | 2 | Minute count |
| 42 | 2 | Unexplained duration-like value; not assumed mask-on time |
| 44 | 16 | ASCII device identifier |
| 60 | 2 | Following history-block count |

History block relative offsets: calendar at 0–5; probable mode code at 6; probable maximum IPAP and minimum EPAP at 10–11 and 12–13 (BE/10); probable pressure support at 21 (/10); `A5` terminator at 35. Other bytes stay unknown. Repeated history entries do not necessarily indicate a setting change.

## Minute record

Header: calendar at 0–5 and count at 6–7. Record `i` begins at `8 + 22*i`.

| Relative offset | Length | Meaning / scale |
|---|---|---|
| 0, 2 | 2 each | Probable IPAP/EPAP, LE/10 cmH2O |
| 4 | 1 | Unknown |
| 5, 6, 7 | 1 each | Candidate OA/CA/H counters |
| 8–11 | 1 each | Unknown counters/fields |
| 12 | 2 | Probable leak, LE/10 L/min; total vs excess unresolved |
| 14 | 2 | Probable tidal volume, LE mL |
| 16 | 1 | Probable minute ventilation, L/min |
| 17 | 1 | Probable I/E ratio percentage |
| 18 | 1 | Probable respiratory rate, breaths/min |
| 19, 20 | 1 each | Candidate oxygen/pulse slots, retained raw |
| 21 | 1 | `FE` marker |

Consecutive 60-second bins are assigned only when their header and session timing agree. Within-bin sample convention is unknown; exact event onset and duration cannot be recovered. Mean/percentile statistics use valid probable channels. Percentiles use the weighted inverse empirical distribution, not a verified manufacturer algorithm.

## AHI and events

The working estimate is candidate counter total divided by elapsed hours. Publication requires complete minute records, matching counts/timestamps/duration, reconciled counters and no conflicting or overlapping session. Screen observations join on exact serial/start/end and compare at one decimal place. Alternative run-count and duration-word hypotheses remain exported.

This does not establish clinical scoring accuracy, all event subtypes or all firmware behavior. A matched displayed total is supporting evidence for that session. Daily AHI cohorts use whole sessions by start date; calendar coverage is separately split at midnight.

## Detail blocks

Each 1,201-byte block contains 600 channel-A bytes, 600 channel-B bytes, then `FE`. A 10 Hz cadence is tentative when the block corresponds to a minute. Raw bytes are authoritative; no physical-unit conversion is asserted. Invalid headers, markers and excess blocks are preserved raw instead of counted as valid samples. Orphan or inconsistent files do not acquire validated session coverage.

All source bytes, including unknown files and malformed tails, are retained in the raw archive. See the decoder tests for synthetic examples of each accepted/rejected structure.
