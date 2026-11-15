
import unittest
import pandas as pd

from app.profiling import profile_dataframe


class TestDatasetProfiling(unittest.TestCase):

    def test_missing_values(self):
        df = pd.DataFrame({
            "name": ["A", "B", None],
            "marks": [80, 90, None]
        })

        result = profile_dataframe(df)

        self.assertEqual(result["total_missing_values"], 2)
        self.assertEqual(result["columns"][0]["missing_values"], 1)
        self.assertEqual(result["columns"][1]["missing_values"], 1)

    def test_duplicate_rows(self):
        df = pd.DataFrame({
            "name": ["A", "B", "A"],
            "marks": [80, 90, 80]
        })

        result = profile_dataframe(df)

        self.assertEqual(result["duplicate_rows"], 1)

    def test_numeric_statistics(self):
        df = pd.DataFrame({
            "marks": [60, 70, 80, 90]
        })

        result = profile_dataframe(df)

        stats = result["columns"][0]["statistics"]

        self.assertEqual(stats["count"], 4)
        self.assertEqual(stats["mean"], 75.0)
        self.assertEqual(stats["median"], 75.0)
        self.assertEqual(stats["min"], 60)
        self.assertEqual(stats["max"], 90)

    def test_unique_values(self):
        df = pd.DataFrame({
            "city": ["Pune", "Mumbai", "Pune", None]
        })

        result = profile_dataframe(df)

        self.assertEqual(result["columns"][0]["unique_values"], 2)

    def test_empty_dataframe_with_columns(self):
        df = pd.DataFrame({
            "marks": pd.Series(dtype="float64")
        })

        result = profile_dataframe(df)

        self.assertEqual(result["total_missing_values"], 0)
        self.assertEqual(result["duplicate_rows"], 0)
        self.assertEqual(
            result["columns"][0]["statistics"]["count"], 0
        )


if __name__ == "__main__":
    unittest.main()
