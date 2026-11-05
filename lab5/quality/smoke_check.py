"""Предупреждение: падение объёма >20% или пустые обязательные поля >5%."""
import argparse
import json
from pathlib import Path


def compare(current, previous=None):
    warnings = []
    if previous and previous['records'] > 0:
        decrease = 100 * (previous['records'] - current['records']) / previous['records']
        if decrease > 20:
            warnings.append(f"Число записей упало на {decrease:.1f}%")
    if current['empty_required_pct'] > 5:
        warnings.append(f"Пустые обязательные поля: {current['empty_required_pct']:.1f}% записей")
    return {'status': 'WARNING' if warnings else 'OK', 'warnings': warnings,
            'has_previous_run': previous is not None}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('current', type=Path)
    parser.add_argument('previous', type=Path, nargs='?')
    args = parser.parse_args()
    current = json.loads(args.current.read_text(encoding='utf-8'))
    previous = json.loads(args.previous.read_text(encoding='utf-8')) if args.previous else None
    result = compare(current, previous)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(1 if result['warnings'] else 0)
