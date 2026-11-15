
import pandas as pd


def profile_dataframe(df: pd.DataFrame) -> dict:
    """
    Generate a statistical profile for a DataFrame.
    """

    total_rows = len(df)
    column_profiles = []

    for column in df.columns:
        series = df[column]

        missing_values = int(series.isna().sum())
        unique_values = int(series.nunique(dropna=True))

        column_profile = {
            "name": str(column),
            "data_type": str(series.dtype),
            "missing_values": missing_values,
            "missing_percentage": (
                round((missing_values / total_rows) * 100, 2)
                if total_rows > 0 else 0.0
            ),
            "unique_values": unique_values,
            "statistics": None
        }

        # Calculate statistics only for numeric columns.
        if (
            pd.api.types.is_numeric_dtype(series)
            and not pd.api.types.is_bool_dtype(series)
        ):
            numeric_values = series.dropna()

            if len(numeric_values) > 0:
                column_profile["statistics"] = {
                    "count": int(numeric_values.count()),
                    "mean": float(numeric_values.mean()),
                    "median": float(numeric_values.median()),
                    "min": numeric_values.min().item(),
                    "max": numeric_values.max().item()
                }
            else:
                column_profile["statistics"] = {
                    "count": 0,
                    "mean": None,
                    "median": None,
                    "min": None,
                    "max": None
                }

        column_profiles.append(column_profile)

    return {
        "total_missing_values": int(df.isna().sum().sum()),
        "duplicate_rows": int(df.duplicated().sum()),
        "columns": column_profiles
    }
