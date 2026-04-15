import os

import pandas as pd


REQUIRED_COLUMNS    = ['EventTemplate', 'EventId']
RECOMMENDED_COLUMNS = ['Content', 'Level', 'Component', 'Date', 'Time']


def validate(csv_path: str) -> dict:
    """
    Validate a Brain-parsed structured CSV for pipeline compatibility.
    Returns a result dict with 'valid' bool and diagnostic fields.
    """
    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        return {'valid': False, 'error': str(e)}

    missing   = [c for c in REQUIRED_COLUMNS    if c not in df.columns]
    available = [c for c in RECOMMENDED_COLUMNS if c in df.columns]
    n         = len(df)

    warnings = []
    if 'EventTemplate' in df.columns and df['EventTemplate'].isna().sum():
        warnings.append(f"{df['EventTemplate'].isna().sum()} empty EventTemplate entries")
    if 'EventId' in df.columns and df['EventId'].nunique() < n * 0.1:
        warnings.append(f"Low template diversity: {df['EventId'].nunique()} unique for {n} logs")

    return {
        'valid':    len(missing) == 0,
        'total':    n,
        'columns':  list(df.columns),
        'missing':  missing,
        'available_recommended': available,
        'warnings': warnings,
    }

