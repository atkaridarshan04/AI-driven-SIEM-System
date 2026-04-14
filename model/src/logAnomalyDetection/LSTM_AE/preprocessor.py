import pickle

import numpy as np


class DataPreprocessor:
    """
    Applies the same feature engineering used during training:
    drop metadata columns → extract content features → OHE/TF-IDF → scale.
    Requires a pre-saved artifacts .pkl produced at training time.
    """

    def __init__(self):
        self.artifacts = None
        self.is_loaded = False

    def load(self, artifacts_path: str) -> bool:
        try:
            with open(artifacts_path, 'rb') as f:
                self.artifacts = pickle.load(f)
            self.is_loaded = True
            print("✅ Loaded preprocessing artifacts")
            return True
        except Exception as e:
            print(f"❌ Failed to load preprocessing artifacts: {e}")
            return False

    def preprocess(self, df):
        """
        Returns (scaled_array, original_df).
        scaled_array shape: (n_rows, n_features)
        """
        if not self.is_loaded:
            raise RuntimeError("Call load() before preprocess()")

        original_df = df.copy()
        df = df.drop(columns=[c for c in ['LineId', 'Time', 'Date', 'PID', 'Month'] if c in df.columns])

        cat_cols = [c for c in ['Level', 'Component', 'EventId'] if c in df.columns]

        if 'EventTemplate' in df.columns:
            if df['EventTemplate'].nunique() < 1000:
                cat_cols.append('EventTemplate')
            else:
                df = df.drop(columns=['EventTemplate'])

        if 'Content' in df.columns:
            c = df['Content']
            df['content_length']            = c.str.len()
            df['content_word_count']        = c.str.split().str.len()
            df['content_has_error']         = c.str.contains(r'\b(?:error|fail|exception|crash|abort|fault)\b',       case=False, na=False).astype(int)
            df['content_has_warning']       = c.str.contains(r'\b(?:warn|alert|caution)\b',                           case=False, na=False).astype(int)
            df['content_has_large_numbers'] = c.str.contains(r'\b\d{4,}\b',                                         na=False).astype(int)
            df['content_has_critical']      = c.str.contains(r'\b(?:critical|fatal|panic|segfault|timeout|killed)\b', case=False, na=False).astype(int)
            df['content_has_network']       = c.str.contains(r'\b(?:connection|socket|port|network|tcp|udp)\b',       case=False, na=False).astype(int)
            df['content_has_memory']        = c.str.contains(r'\b(?:memory|malloc|free|leak|oom|out of memory)\b',    case=False, na=False).astype(int)
            df = df.drop(columns=['Content'])

        cat_cols = [c for c in cat_cols if c in df.columns]
        if cat_cols:
            ohe = self.artifacts['ohe']
            if isinstance(ohe, tuple):
                tfidf, other_ohe = ohe
                if 'EventTemplate' in cat_cols and tfidf:
                    tmpl = tfidf.transform(df['EventTemplate'].astype(str)).toarray()
                    df   = df.drop(columns=['EventTemplate'])
                    cat_cols.remove('EventTemplate')
                    rest = other_ohe.transform(df[cat_cols].astype(str)) if cat_cols and other_ohe else np.empty((len(df), 0))
                    cat_features = np.hstack([tmpl, rest])
                else:
                    cat_features = other_ohe.transform(df[cat_cols].astype(str))
            else:
                cat_features = ohe.transform(df[cat_cols].astype(str))
            df = df.drop(columns=cat_cols)
        else:
            cat_features = np.empty((len(df), 0))

        num_cols     = list(df.columns)
        num_features = self.artifacts['imputer'].transform(df[num_cols]) if num_cols else np.empty((len(df), 0))

        parts = [p for p in [cat_features, num_features] if p.shape[1] > 0]
        if not parts:
            raise ValueError("No features remaining after preprocessing")

        return self.artifacts['scaler'].transform(np.hstack(parts)), original_df
