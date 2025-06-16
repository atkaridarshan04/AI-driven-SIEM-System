# Unified Roadmap: Evolving the Anomaly Detection System

This document outlines the comprehensive, phased plan to upgrade the current anomaly detection system. It integrates the strategy for evolving the core detection model with a sophisticated, multi-stage approach to implementing AI-native intelligence modules.

## Phase 0: Current State (V1.0) - Ensemble of Feature-Based Autoencoders

**Status:** This is the current production system.

* **Architecture:** An ensemble of three `HybridAttentionLSTMAutoencoder` models.
* **Data Pipeline:** Relies on a complex `DataPreprocessor` that performs manual feature engineering (OHE, TF-IDF, etc.).
* **Key Limitation:** The models' performance is capped by the quality of hand-crafted features. They do not learn from the raw semantic meaning of logs.
* **Intelligence Modules:** Utilizes a `RuleBasedLogClassifier` for anomaly typing and an `EnhancedSeverityManager` for severity analysis.


## Phase 1: Optimization \& Probabilistic Classification (V1.5)

**Goal:** Maximize the performance of the existing architecture and replace the rigid rule-based classifier with a more flexible, AI-native topic modeling approach.

**Tasks:**

1. **Fix Current Model Architecture:**
    * **Action:** Remove Hybrid, Single Complexity, Keep only Sequential Processor [Bi-LSTM encoder -> Attention -> LSTM decoder]
2. **Optimize Ensemble Model:**
    * **Action:** Refine the ensemble weighting strategy based on each model's F1-score or another performance metric on a validation set.
3. **Harden Intelligence Modules:**
    * **Action:** Implement performance and maintenance improvements for your existing modules (pre-compile regex, refine severity confidence, externalize rules).
4. **Implement AI native type classification:**
    * **Action:** Replace the `RuleBasedLogClassifier` with an implementation of **Labeled LDA (L-LDA) / LogClass**.

## Phase 2: Architectural Leap to a Semantic Core (V2.0)

**Goal:** Replace the entire V1.x stack with a single, more powerful `SemanticLogTransformer` that understands log meaning directly. This eliminates the need for complex feature engineering and brittle ensembles.

**Tasks:**

1. **Deprecate Legacy Data Pipeline:**
    * **Action:** Entirely remove the `DataPreprocessor` and its manual feature engineering steps.
2. **Implement Semantic Data Pipeline:**
    * **Action:** Build a new data pipeline that uses a `sentence-transformer` model (like BERT) to convert raw log messages into rich, high-dimensional semantic vectors. This aligns with state-of-the-art frameworks like LogLLM.
3. **Implement the `SemanticLogTransformer` Model:**
    * **Action:** Develop the new autoencoder model based on the Transformer architecture. This single model is designed to replace the entire V1.x LSTM ensemble. Updated Model : [Encoder(with Attention) -> Decoder].
4. **Train and Validate:**
    * **Action:** Train the `SemanticLogTransformer` on your normal log sequences. Validate that this single, semantically-aware model outperforms the entire V1.5 feature-based ensemble.