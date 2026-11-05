"""Запуск основного сбора и опытов отдельными процессами Scrapy."""
import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def crawl(spider, label, pages, database, **settings):
    run_id = f"{STAMP}_{label}"
    (ROOT / "data/logs").mkdir(parents=True, exist_ok=True)
    feed = f"data/items_{run_id}.jsonl"
    command = [sys.executable, "-m", "scrapy", "crawl", spider,
               "-a", f"run_id={run_id}", "-a", f"max_pages={pages}", "-O", feed]
    options = {"DATABASE_PATH": database, "LOG_FILE": f"data/logs/{run_id}.log", **settings}
    for key, value in options.items():
        command += ["-s", f"{key}={value}"]
    print(f"Запуск {label}...", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)
    stats = json.loads((ROOT / f"data/stats_{run_id}.json").read_text(encoding="utf-8"))
    if any(stats.get(key, 0) for key in ["log_count/ERROR", "network/errbacks", "database/errors", "scheduler/unserializable"]):
        raise RuntimeError(f"В запуске {run_id} есть ошибки. См. журнал.")
    print(f"{label}: {stats.get('item_scraped_count', 0)} записей, {stats['elapsed_time_seconds']:.1f} с", flush=True)
    return stats


def main_collection():
    books = crawl("books", "books", 15, "data/crawl.db")
    quotes = crawl("quotes", "quotes", 10, "data/crawl.db")
    with (ROOT / "data/items.jsonl").open("w", encoding="utf-8") as target:
        for stats in (books, quotes):
            target.write((ROOT / f"data/items_{stats['run_id']}.jsonl").read_text(encoding="utf-8"))
    save(ROOT / "data/run_manifest.json", {"books": books["run_id"], "quotes": quotes["run_id"]})


def experiments():
    job = ROOT / "jobstate" / f"books_{STAMP}"
    db = f"data/resume_{STAMP}.db"
    first = crawl("books", "resume_stop", 5, db, JOBDIR=job, CLOSESPIDER_ITEMCOUNT=25)
    paused = job.with_name(job.name + "_paused")
    shutil.copytree(job, paused)
    files = [{"name": str(p.relative_to(paused)), "bytes": p.stat().st_size}
             for p in paused.rglob("*") if p.is_file()]
    second = crawl("books", "resume_continue", 5, db, JOBDIR=job, CLOSESPIDER_ITEMCOUNT=350)
    repeated = sorted(set(first["parsed_urls"]) & set(second["parsed_urls"]))
    with sqlite3.connect(ROOT / db) as connection:
        total = connection.execute("SELECT count(*) FROM books").fetchone()[0]
    if repeated or total != 100:
        raise RuntimeError(f"Неожиданный результат JOBDIR: {total} записей, повторные URL: {repeated}")
    cache = ROOT / "data" / f"httpcache_{STAMP}"
    cold = crawl("books", "cache_cold", 1, f"data/cache_{STAMP}.db", HTTPCACHE_ENABLED=1, HTTPCACHE_DIR=cache)
    warm = crawl("books", "cache_warm", 1, f"data/cache_{STAMP}.db", HTTPCACHE_ENABLED=1, HTTPCACHE_DIR=cache)
    if not warm.get("httpcache/hit"):
        raise RuntimeError("Второй запуск не использовал кэш")
    save(ROOT / "data/experiments.json", {
        "resume": {"first": first["run_id"], "second": second["run_id"], "database": db,
                   "jobdir": str(job.relative_to(ROOT)), "paused_files": files,
                   "total_records": total, "repeated_parsed_urls": repeated},
        "cache": {"cold": cold["run_id"], "warm": warm["run_id"], "path": str(cache.relative_to(ROOT))}})


def benchmark():
    stats = crawl("books", "benchmark40", 2, f"data/benchmark_{STAMP}.db")
    save(ROOT / "data/benchmark.json", {"run_id": stats["run_id"],
        "records": stats.get("item_scraped_count", 0), "seconds": stats["elapsed_time_seconds"],
        "network_requests": stats.get("downloader/request_count", 0),
        "content_requests": stats.get("source/list_pages", 0) + stats.get("source/detail_pages", 0),
        "body_bytes": stats.get("traffic/body_bytes", 0), "database": stats["database_path"]})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["main", "experiments", "benchmark", "all"], nargs="?", default="main")
    mode = parser.parse_args().mode
    if mode in ("main", "all"):
        main_collection()
    if mode in ("experiments", "all"):
        experiments()
    if mode in ("benchmark", "all"):
        benchmark()
