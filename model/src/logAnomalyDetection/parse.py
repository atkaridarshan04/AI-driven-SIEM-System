import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.logAnomalyDetection.Brain import LogParser
from src.logAnomalyDetection.parse_validator import validate


def parse_and_process(
    log_file:  str  = None,
    dataset:   str  = 'Linux',
    input_dir: str  = 'data/logs/raw/',
    output_dir: str = 'data/logs/processed/',
    log_format: str = None,
    regex:     list = None,
    threshold: int  = None,
    delimeter: list = None,
    config:    dict = None,
    verbose:   bool = False,
) -> str | None:
    """
    Parse a raw log file with the Brain algorithm.
    Returns path to the structured CSV, or None on failure.
    """
    # Config overrides
    if config:
        pc = config.get('parsing', {})
        dp = config.get('data_paths', {})
        dataset    = dataset    or pc.get('dataset',    'Linux')
        input_dir  = input_dir  or dp.get('input_dir',  'data/logs/raw/')
        output_dir = output_dir or dp.get('output_dir', 'data/logs/processed/')
        log_format = log_format or pc.get('log_format')
        threshold  = threshold  or pc.get('parameters', {}).get('threshold', 4)
        regex      = regex      or pc.get('parameters', {}).get('regex',     [r'(\d+\.){3}\d+', r'\d{2}:\d{2}:\d{2}', r'J([a-z]{2})'])
        delimeter  = delimeter  or pc.get('parameters', {}).get('delimeter', [''])

    log_format = log_format or '<Month> <Date> <Time> <Level> <Component>(\\[<PID>\\])?: <Content>'
    threshold  = threshold  or 4
    regex      = regex      or [r'(\d+\.){3}\d+', r'\d{2}:\d{2}:\d{2}', r'J([a-z]{2})']
    delimeter  = delimeter  or ['']
    log_file   = log_file   or f'{dataset}_test.log'

    input_path = os.path.join(input_dir, log_file)
    if not os.path.exists(input_path):
        print(f"❌ Log file not found: {input_path}")
        return None

    os.makedirs(output_dir, exist_ok=True)

    if verbose:
        print(f"   • Dataset: {dataset}  |  File: {log_file}  |  Threshold: {threshold}")

    try:
        parser = LogParser(
            logname=dataset,
            log_format=log_format,
            indir=input_dir,
            outdir=output_dir,
            threshold=threshold,
            delimeter=delimeter,
            rex=regex,
        )
        parser.parse(log_file)
    except Exception as e:
        print(f"❌ Brain parser failed: {e}")
        if verbose:
            import traceback; traceback.print_exc()
        return None

    csv_path = _find_output(output_dir, log_file, dataset)
    if not csv_path:
        print(f"❌ No structured CSV found in {output_dir}")
        return None

    result = validate(csv_path)
    if not result['valid']:
        print(f"⚠️  Parsed CSV failed validation: {result.get('missing')}")
    else:
        print(f"✅ Parsed {result['total']} entries → {csv_path}")
        if result['warnings'] and verbose:
            for w in result['warnings']:
                print(f"   ⚠️  {w}")

    return csv_path


def _find_output(output_dir: str, log_file: str, dataset: str) -> str | None:
    """Probe the naming conventions Brain uses for its output CSV."""
    base = os.path.splitext(log_file)[0]
    candidates = [
        f"{log_file}_structured.csv",
        f"{base}.log_structured.csv",
        f"{dataset}.log_structured.csv",
        f"{dataset}_structured.csv",
        f"{base}_structured.csv",
    ]
    for name in candidates:
        path = os.path.join(output_dir, name)
        if os.path.isfile(path):
            return path
    return None
