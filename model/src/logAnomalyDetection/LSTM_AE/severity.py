import numpy as np


class EnhancedSeverityManager:
    """
    Learns percentile-based severity thresholds from reconstruction error distributions
    and classifies individual errors with a calibrated confidence score.
    """

    def __init__(self, percentiles=None, severity_labels=None):
        self.percentiles     = percentiles     or [85, 95, 99]
        self.severity_labels = severity_labels or ['Low', 'Medium', 'High', 'Critical']
        self.threshold_values: dict = {}
        self.error_stats:     dict = {}

    def learn_thresholds(self, error_distribution):
        arr = np.array(error_distribution)
        self.threshold_values = {f'p{p}': float(np.percentile(arr, p)) for p in self.percentiles}
        self.error_stats = {
            'mean':   float(np.mean(arr)),
            'std':    float(np.std(arr)),
            'median': float(np.median(arr)),
            'iqr':    float(np.percentile(arr, 75) - np.percentile(arr, 25)),
        }
        print(f"✅ Severity thresholds learned: {self.threshold_values}")

    def load_thresholds(self, artifacts: dict):
        if 'severity_manager' in artifacts:
            sm = artifacts['severity_manager']
            self.threshold_values = sm.threshold_values
            self.error_stats      = sm.error_stats
            print("✅ Severity thresholds loaded from artifacts")
        else:
            print("⚠️  No severity thresholds in artifacts")

    def classify_with_confidence(self, error: float) -> tuple[str, float]:
        if not self.threshold_values:
            raise RuntimeError("Call learn_thresholds() or load_thresholds() first")

        idx = sum(error > self.threshold_values[f'p{p}'] for p in self.percentiles)
        severity = self.severity_labels[idx]

        if idx == 0:
            upper      = self.threshold_values[f'p{self.percentiles[0]}']
            confidence = max(0.1, 1.0 - (error / upper)) if upper > 0 else 0.5
        elif idx == len(self.percentiles):
            lower      = self.threshold_values[f'p{self.percentiles[-1]}']
            std        = self.error_stats.get('std', 1.0) or 1.0
            confidence = min(0.99, 0.7 + min((error - lower) / (3 * std), 0.29))
        else:
            lower = self.threshold_values[f'p{self.percentiles[idx - 1]}']
            upper = self.threshold_values[f'p{self.percentiles[idx]}']
            band  = upper - lower
            confidence = (0.5 + 0.49 * ((error - lower) / band)) if band > 0 else 0.75

        return severity, round(min(0.99, max(0.1, confidence)), 3)
