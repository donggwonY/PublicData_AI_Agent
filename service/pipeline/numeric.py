"""Numeric parsing for permit fields, preserving invalid/missing values."""
import pandas as pd


def parse_area(values: pd.Series) -> pd.Series:
    """Accept standard thousands grouping; malformed comma values remain missing."""
    text = values.astype('string').str.strip()
    grouped = text.str.fullmatch(r'[+-]?[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?', na=False)
    normalized = text.where(~grouped, text.str.replace(',', '', regex=False))
    return pd.to_numeric(normalized, errors='coerce')
