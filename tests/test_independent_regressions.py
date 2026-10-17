"""Independent regression expectations for the revised decoder."""

import csv
import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path
from independent_fixtures import STAMP, summary, minutes, fixture

from appbyscribe import decoder


class RevisedDecoderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.out = self.root / "out"

    def tearDown(self):
        self.tmp.cleanup()

    def codes(self, result):
        return {x["code"] for x in result["diagnostics"]}

    def rows(self, name):
        with (self.out / "output" / name).open() as f:
            return list(csv.DictReader(f))

    def test_raw_archive_roundtrips_unknown_and_malformed_files(self):
        source = fixture(self.root)
        (source / "unknown.dat").write_bytes(bytes(range(256)) * 3)
        (source / "broken.bys").write_bytes(b"\x00\xfe\xa5\xff")
        decoder.run(source, self.out)
        archive = json.loads((self.out / "raw/source_files.json").read_text())
        self.assertEqual(len(archive), 4)
        for r in archive:
            b = (source / r["source_file"]).read_bytes()
            self.assertEqual(bytes.fromhex(r["raw_hex"]), b)
            self.assertEqual(r["byte_length"], len(b))
            self.assertEqual(r["sha256"], hashlib.sha256(b).hexdigest())

    def test_bad_settings_retains_base_and_all_minutes(self):
        source = fixture(self.root)
        b = bytearray(summary())
        b[-1] = 0
        (source / "0000001s.bys").write_bytes(b)
        result = decoder.run(source, self.out)
        self.assertIn("settings_rejected_base_salvaged", self.codes(result))
        self.assertEqual(result["counts"]["sessions"], 1)
        self.assertEqual(result["counts"]["minute_records"], 2)
        self.assertEqual(len(self.rows("timeseries.csv")), 2)
        self.assertFalse((self.out / "output/settings_candidates.csv").exists())

    def test_bad_base_is_not_salvaged_and_minute_bytes_are_recovered(self):
        source = fixture(self.root)
        b = bytearray(summary())
        b[3] = 255
        (source / "0000001s.bys").write_bytes(b)
        result = decoder.run(source, self.out)
        self.assertEqual(result["counts"]["sessions"], 0)
        self.assertIn("rejected_summary", self.codes(result))
        orphan = json.loads((self.out / "output/unpaired_raw_records.json").read_text())
        self.assertEqual(len(orphan), 2)
        self.assertEqual(b"".join(bytes.fromhex(r["raw_hex"]) for r in orphan), minutes()[8:])

    def test_index_only_recovery_with_explicit_provenance_and_no_settings(self):
        source = self.root / "s"
        source.mkdir()
        (source / "summer.bys").write_bytes(summary()[:62])
        result = decoder.run(source, self.out)
        self.assertEqual(result["counts"]["sessions"], 1)
        self.assertEqual(result["sessions"][0]["source_file"], "summer.bys")
        self.assertEqual(result["sessions"][0]["source_offset"], 0)
        self.assertIsNone(result["sessions"][0]["ahi"])
        self.assertIn("index_only_session_recovered", self.codes(result))
        self.assertEqual(
            sum(d["total_session_elapsed_hours"] for d in result["daily_summary"]), 2 / 60
        )
        self.assertFalse((self.out / "output/settings_candidates.csv").exists())

    def test_matching_index_does_not_duplicate_summary(self):
        source = fixture(self.root)
        (source / "summer.bys").write_bytes(summary()[:62])
        result = decoder.run(source, self.out)
        self.assertEqual(result["counts"]["sessions"], 1)
        self.assertTrue(result["index_checks"][0]["exact_multiset_match_to_session_bases"])
        self.assertNotIn("index_only_session_recovered", self.codes(result))

    def test_index_trailing_garbage_is_preserved_and_reported(self):
        source = self.root / "s"
        source.mkdir()
        (source / "summer.bys").write_bytes(summary()[:62] + b"bad")
        result = decoder.run(source, self.out)
        self.assertEqual(result["counts"]["sessions"], 1)
        self.assertEqual(result["index_checks"][0]["tail_bytes"], 3)
        self.assertIn("invalid_index_base", self.codes(result))

    def test_orphan_detail_and_minutes_export_without_fabricated_session(self):
        source = self.root / "s"
        source.mkdir()
        (source / "0000001m.bys").write_bytes(minutes())
        detail = STAMP + struct.pack("<H", 1) + bytes(range(200)) * 6 + b"\xfe"
        (source / "0000001d.bys").write_bytes(detail)
        result = decoder.run(source, self.out)
        orphan = json.loads((self.out / "output/unpaired_raw_records.json").read_text())
        self.assertEqual(len(orphan), 3)
        self.assertEqual(result["counts"]["sessions"], 0)
        self.assertFalse((self.out / "output/timeseries.csv").exists())
        for r in orphan:
            original = (source / r["source_file"]).read_bytes()
            self.assertEqual(
                bytes.fromhex(r["raw_hex"]),
                original[r["source_offset"] : r["source_offset"] + r["record_length"]],
            )

    def test_detail_start_mismatch_is_reported_and_raw_retained(self):
        source = fixture(self.root)
        (source / "0000001d.bys").write_bytes(
            bytes([26, 10, 17, 10, 0, 0]) + struct.pack("<H", 2) + (bytes(1200) + b"\xfe") * 2
        )
        result = decoder.run(source, self.out)
        self.assertIn("detail_summary_mismatch", self.codes(result))
        self.assertFalse(result["validations"][0]["detail_start_matches"])
        self.assertEqual(result["counts"]["detail_blocks"], 2)

    def test_implausible_pressure_excluded_but_raw_preserved(self):
        source = fixture(self.root)
        b = bytearray(minutes())
        struct.pack_into("<HH", b, 8, 999, 40)
        (source / "0000001m.bys").write_bytes(b)
        result = decoder.run(source, self.out)
        self.assertIn("pressure_mapping_outside_candidate_range", self.codes(result))
        self.assertEqual(result["counts"]["minute_records"], 2)
        c = result["candidate_summaries"][0]
        self.assertEqual(c["minute_records_used"], 1)
        self.assertEqual(c["mean_ipap_probable_cmH2O"], 6)
        self.assertTrue(self.rows("timeseries.csv")[0]["confidence"].startswith("tentative"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
