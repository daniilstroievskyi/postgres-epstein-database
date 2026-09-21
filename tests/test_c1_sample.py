import unittest

from scripts.c1_sample import (
    EXPECTED_CHUNK_COUNT,
    EXPECTED_CHUNKED_DOCUMENT_COUNT,
    EXPECTED_DOCUMENT_COUNT,
    load_c1_sample,
)


class C1SampleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sample = load_c1_sample()

    def test_expected_counts(self) -> None:
        self.assertEqual(len(self.sample.documents), EXPECTED_DOCUMENT_COUNT)
        self.assertEqual(len(self.sample.chunks), EXPECTED_CHUNK_COUNT)
        self.assertEqual(
            len({row[1] for row in self.sample.chunks}),
            EXPECTED_CHUNKED_DOCUMENT_COUNT,
        )

    def test_document_selection_is_explicit_and_deterministic(self) -> None:
        self.assertEqual(
            [row[0] for row in self.sample.documents], list(range(1, 1001))
        )

    def test_keys_and_relationships(self) -> None:
        document_ids = {row[0] for row in self.sample.documents}
        chunk_ids = [row[0] for row in self.sample.chunks]
        chunk_positions = [(row[1], row[2]) for row in self.sample.chunks]
        self.assertEqual(len(chunk_ids), len(set(chunk_ids)))
        self.assertEqual(len(chunk_positions), len(set(chunk_positions)))
        self.assertTrue(
            {row[1] for row in self.sample.chunks}.issubset(document_ids)
        )


if __name__ == "__main__":
    unittest.main()
