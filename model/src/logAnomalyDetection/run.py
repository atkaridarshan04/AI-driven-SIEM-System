#!/usr/bin/env python3
"""
AI-driven SIEM — Log Anomaly Detection entry point.
Usage: python run.py --input Linux_test.log [options]
"""

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

# Ensure project root is on the path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Pre-import pickled classes so unpickling works regardless of call site
from src.logAnomalyDetection.LSTM_AE.severity   import EnhancedSeverityManager
from src.logAnomalyDetection.LSTM_AE.classifier  import LabeledLDAClassifier
from src.logAnomalyDetection.LSTM_AE.autoencoder import SequentialLSTMAutoencoder
from src.logAnomalyDetection.LSTM_AE.detector    import EnsembleDetector
from src.logAnomalyDetection.LSTM_AE.preprocessor import DataPreprocessor

from src.logAnomalyDetection.parse import parse_and_process
from src.logAnomalyDetection.pipeline import AnomalyDetectionPipeline
from src.utils.config_loader import load_config
from src.utils.express_exporter import ExpressExporter


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_arguments():
    p = argparse.ArgumentParser(description='AI-driven SIEM Log Anomaly Detection')
    p.add_argument('--config', '-c',  default='configs/log-anomaly-detection.yml')
    p.add_argument('--input',  '-i',  help='Raw log file name (e.g. Linux_test.log)')
    p.add_argument('--dataset', '-d', default='Linux')
    p.add_argument('--input-dir',     default='data/logs/raw/')
    p.add_argument('--output-dir',    default='data/logs/processed/')
    p.add_argument('--reports-dir',   default='reports/logAnomalyDetection/')
    p.add_argument('--mode', '-m',    choices=['parse', 'detect', 'full'], default='full')
    p.add_argument('--use-existing-csv', help='Skip parsing; use this structured CSV directly')
    p.add_argument('--export-to-express', action='store_true')
    p.add_argument('--express-url',   help='Override Express backend URL')
    p.add_argument('--test-express-connection', action='store_true')
    p.add_argument('--verbose', '-v', action='store_true')
    return p.parse_args()


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------

def stage_parse(args, config) -> str | None:
    print("\n📄 STAGE 1: Log Parsing")
    print("-" * 40)
    parsed = parse_and_process(
        dataset=args.dataset,
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        log_file=args.input,
        verbose=args.verbose,
    )
    if not parsed:
        print("❌ Parsing failed")
    return parsed


def stage_detect(config, csv_path, verbose=False) -> dict | None:
    print("\n🤖 STAGE 2: Anomaly Detection")
    print("-" * 40)

    detection_cfg = config.get('detection', {})
    pipeline = AnomalyDetectionPipeline(detection_cfg)

    if not pipeline.load():
        print("❌ Pipeline initialisation failed")
        return None

    results = pipeline.run(csv_path)
    pipeline.save(results)
    return results


def stage_export(results, config):
    print("\n📤 Exporting to Express backend...")
    exporter = ExpressExporter(config)
    if not exporter.test_connection():
        print("⚠️  Express backend unreachable — skipping export")
        return
    anomalies = results.get('anomalies', [])
    if anomalies:
        exporter.export_anomalies(anomalies)
    else:
        print("   • No anomalies to export")


# ---------------------------------------------------------------------------
# Summary display
# ---------------------------------------------------------------------------

def print_summary(results: dict):
    anomalies = results.get('anomalies', [])
    meta      = results.get('metadata', {})

    print(f"\n{'=' * 55}")
    print(f"  DETECTION SUMMARY")
    print(f"{'=' * 55}")
    print(f"  Logs processed : {meta.get('total_logs', '?')}")
    print(f"  Threshold (p{meta.get('threshold_percentile', 95)}) : {meta.get('threshold', 0):.6f}")
    print(f"  Anomalies found: {len(anomalies)}")

    if anomalies:
        severity_counts = Counter(a['severity'] for a in anomalies)
        type_counts     = Counter(a['anomaly_type'] for a in anomalies)
        print(f"\n  Severity breakdown:")
        for level in ['Critical', 'High', 'Medium', 'Low']:
            n = severity_counts.get(level, 0)
            if n:
                icon = '🚨' if level == 'Critical' else '⚠️ ' if level == 'High' else '🔵'
                print(f"    {icon} {level}: {n}")
        print(f"\n  Top anomaly types:")
        for atype, n in type_counts.most_common(5):
            print(f"    • {atype}: {n}")
    print(f"{'=' * 55}\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args   = parse_arguments()
    config = load_config(args.config)

    # Apply CLI overrides
    if args.reports_dir:
        config.setdefault('detection', {})['output_path'] = args.reports_dir
    if args.export_to_express:
        config.setdefault('express_backend', {})['enabled'] = True
    if args.express_url:
        config.setdefault('express_backend', {})['base_url'] = args.express_url

    # Test-only mode
    if args.test_express_connection:
        ok = ExpressExporter(config).test_connection()
        sys.exit(0 if ok else 1)

    # ---- parse only ----
    if args.mode == 'parse':
        if not stage_parse(args, config):
            sys.exit(1)
        return

    # ---- detect only ----
    if args.mode == 'detect':
        csv_path = args.use_existing_csv
        if not csv_path or not os.path.exists(csv_path):
            print(f"❌ --use-existing-csv required for detect mode")
            sys.exit(1)
        results = stage_detect(config, csv_path, args.verbose)
        if not results:
            sys.exit(1)
        print_summary(results)
        if config.get('express_backend', {}).get('enabled'):
            stage_export(results, config)
        return

    # ---- full pipeline ----
    if args.use_existing_csv:
        csv_path = args.use_existing_csv
    else:
        csv_path = stage_parse(args, config)
        if not csv_path:
            sys.exit(1)

    if not os.path.exists(csv_path):
        print(f"❌ Structured CSV not found: {csv_path}")
        sys.exit(1)

    results = stage_detect(config, csv_path, args.verbose)
    if not results:
        sys.exit(1)

    print_summary(results)

    if config.get('express_backend', {}).get('enabled'):
        stage_export(results, config)


if __name__ == '__main__':
    main()
