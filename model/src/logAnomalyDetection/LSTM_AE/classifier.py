import re

import numpy as np
from sklearn.feature_extraction.text import CountVectorizer


DEFAULT_LABEL_SEEDS = {
    'memory_error': [
        'out of memory', 'oom', 'page allocation failure', 'malloc failed',
        'memory leak', 'segfault', 'kernel panic', 'swap full', 'memory pressure',
    ],
    'authentication_error': [
        'authentication failure', 'invalid username', 'login failed',
        'pam_unix failed', 'ssh failed', 'password incorrect', 'access denied',
        'unauthorized', 'kerberos failed',
    ],
    'filesystem_error': [
        'no such file', 'disk full', 'quota exceeded', 'failed command',
        'status timeout', 'drive not ready', 'io error', 'filesystem corrupt',
        'bad sector', 'read error',
    ],
    'network_error': [
        'connection timed out', 'connection refused', 'peer died',
        'network unreachable', 'socket error', 'host down',
        'dns failed', 'routing error', 'packet lost',
    ],
    'permission_error': [
        'permission denied', 'operation not supported', 'access forbidden',
        'selinux denied', 'capability denied', 'privilege error',
        'sudo failed', 'su failed',
    ],
    'system_critical': [
        'critical', 'fatal', 'panic', 'emergency', 'alert',
        'system halt', 'kernel oops', 'hardware error',
        'temperature critical', 'power failure',
    ],
}


class LabeledLDAClassifier:
    """
    LogClass-style Labeled LDA classifier.

    Without fit(): uses pre-compiled seed-word patterns for soft scoring.
    With fit(texts): learns per-label word distributions via Gibbs approximation.

    Reference: LogClass (Huang et al., 2020).
    """

    def __init__(self, label_seeds=None, alpha: float = 0.1, beta: float = 0.01, n_iter: int = 30):
        self.label_seeds = label_seeds or DEFAULT_LABEL_SEEDS
        self.labels      = list(self.label_seeds.keys())
        self.alpha       = alpha
        self.beta        = beta
        self.n_iter      = n_iter
        self.is_fitted   = False
        self._vocab      = None
        self._phi        = None  # (n_labels, vocab_size)

        # Pre-compile seed patterns at init time
        self._seed_patterns = {
            label: re.compile(
                r'\b(' + '|'.join(re.escape(s) for s in seeds) + r')\b',
                re.IGNORECASE,
            )
            for label, seeds in self.label_seeds.items()
        }

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def fit(self, texts: list):
        """Fit on a list of raw log strings to learn word-topic distributions."""
        vec = CountVectorizer(min_df=2, max_features=5000, token_pattern=r'\b[a-zA-Z]\w+\b')
        X   = vec.fit_transform(texts)
        self._vocab = vec.get_feature_names_out()
        V, K, n_docs = len(self._vocab), len(self.labels), X.shape[0]

        doc_topic  = np.full((n_docs, K), self.alpha, dtype=np.float32)
        word_topic = np.full((K, V),      self.beta,  dtype=np.float32)

        for d, doc in enumerate(texts):
            for k, label in enumerate(self.labels):
                if self._seed_patterns[label].search(doc.lower()):
                    doc_topic[d, k] += 10.0

        for _ in range(self.n_iter):
            for d in range(n_docs):
                row = X[d].toarray().flatten()
                for w_idx in row.nonzero()[0]:
                    p = doc_topic[d] * word_topic[:, w_idx]
                    p /= p.sum()
                    word_topic[:, w_idx] += p * row[w_idx]
                    doc_topic[d]         += p * row[w_idx]

        self._phi      = word_topic / word_topic.sum(axis=1, keepdims=True)
        self.is_fitted = True
        print(f"✅ LabeledLDA fitted — {n_docs} docs, vocab {V}")
        return self

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def classify_log(self, event_template: str, content: str = "") -> dict:
        combined = f"{event_template} {content}"

        if self.is_fitted and self._vocab is not None:
            words        = re.findall(r'\b[a-zA-Z]\w+\b', combined.lower())
            vocab_set    = set(self._vocab)
            topic_scores = np.full(len(self.labels), self.alpha)
            for w in words:
                if w in vocab_set:
                    idx = np.where(self._vocab == w)[0]
                    if len(idx):
                        topic_scores += self._phi[:, idx[0]]
            probs = topic_scores / topic_scores.sum()
        else:
            text_lower = combined.lower()
            scores = np.array([
                len(self._seed_patterns[l].findall(text_lower)) + self.alpha
                for l in self.labels
            ], dtype=float)
            probs = scores / scores.sum()

        best_idx   = int(np.argmax(probs))
        confidence = float(probs[best_idx])
        label_probs = {l: round(float(p), 4) for l, p in zip(self.labels, probs)}

        if confidence < (1.0 / len(self.labels)) * 1.5:
            return {'log_type': 'normal', 'confidence': round(1.0 - confidence, 3),
                    'is_critical': False, 'label_probs': label_probs}

        label = self.labels[best_idx]
        return {
            'log_type':   label,
            'confidence': round(min(confidence, 0.99), 3),
            'is_critical': label in ('system_critical', 'authentication_error'),
            'label_probs': label_probs,
        }

    def batch_classify(self, log_data_list: list) -> list:
        return [self.classify_log(d.get('EventTemplate', ''), d.get('Content', ''))
                for d in log_data_list]


# Legacy alias
RuleBasedLogClassifier = LabeledLDAClassifier
