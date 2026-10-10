"""Verify that profiling preserves ambiguity instead of multiplying child counts."""

import unittest
import duckdb
from scripts.profile_z1 import reference_check


class ReferenceProfileTest(unittest.TestCase):
    def test_missing_unmatched_and_ambiguous_are_separate(self):
        with duckdb.connect() as connection:
            connection.execute("CREATE TABLE documents(id INTEGER)")
            connection.execute("INSERT INTO documents VALUES (1),(2),(2)")
            connection.execute("CREATE TABLE chunks(document_id VARCHAR)")
            connection.execute("INSERT INTO chunks VALUES ('1'),('2'),('3'),(NULL),('')")
            counts = reference_check(connection, "chunks", "document_id", "documents", "id")
        self.assertEqual(counts, {
            "read": 5, "missing": 1, "unmatched": 2,
            "single_equal_key": 1, "ambiguous_equal_key": 1,
        })
        self.assertEqual(counts["read"], sum(counts[key] for key in (
            "missing", "unmatched", "single_equal_key", "ambiguous_equal_key"
        )))

    def test_repeat_processing_is_counted_as_occurrences(self):
        with duckdb.connect() as connection:
            connection.execute("CREATE TABLE provenance_runs(run_id VARCHAR)")
            connection.execute("INSERT INTO provenance_runs VALUES ('run-1')")
            connection.execute("CREATE TABLE provenance_files(run_id VARCHAR)")
            connection.execute("INSERT INTO provenance_files VALUES ('run-1'),('run-1')")
            counts = reference_check(connection, "provenance/files", "run_id", "provenance/runs", "run_id")
        self.assertEqual(counts["read"], 2)
        self.assertEqual(counts["single_equal_key"], 2)
