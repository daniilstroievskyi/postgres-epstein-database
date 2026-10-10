"""Check that the final input selection excludes parallel exports and missing shards."""

import unittest
from scripts.z1_source import expected_files, validate_inventory


class SourceContractTest(unittest.TestCase):
    def test_complete_prescribed_inventory(self):
        paths = list(expected_files())
        self.assertEqual(len(paths), 56)
        validate_inventory(paths)

    def test_missing_shard_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "missing"):
            validate_inventory(list(expected_files())[1:])

    def test_parallel_export_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unexpected"):
            validate_inventory(list(expected_files()) + ["data/persons/persons-00000.parquet"])

    def test_duplicate_path_is_rejected(self):
        paths = list(expected_files())
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            validate_inventory(paths + paths[:1])
