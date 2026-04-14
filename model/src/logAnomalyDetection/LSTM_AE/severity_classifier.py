# Re-export shim — import from here for backward compatibility.
from .severity   import EnhancedSeverityManager
from .classifier import LabeledLDAClassifier, RuleBasedLogClassifier, DEFAULT_LABEL_SEEDS

__all__ = [
    'EnhancedSeverityManager',
    'LabeledLDAClassifier', 'RuleBasedLogClassifier',
    'DEFAULT_LABEL_SEEDS',
]
