import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def utcnow():
    return datetime.now(timezone.utc).isoformat()

def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)

def save(path, value):
    path = Path(path)
    if path.parent.name in {'clean', 'mart'} and path.suffix == '.json':
        result_file = ROOT / 'results.json'
        results = json.loads(result_file.read_text(encoding='utf-8')) if result_file.exists() else {}
        results[path.relative_to(ROOT).as_posix()] = value
        path, value = result_file, results
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def read_result(name, default=None):
    path = ROOT / name
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    results = json.loads((ROOT / 'results.json').read_text(encoding='utf-8'))
    return results.get(name, default)

def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]

def write_jsonl(path, rows):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(''.join(dumps(row)+'\n' for row in rows),encoding='utf-8')

def raw_hashes():
    return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'raw').glob('*.jsonl'))}
