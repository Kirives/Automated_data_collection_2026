# Лабораторная работа № 5

Вшивков К. И., ПМИ-3-2025. Вариант 6.

Сбор книг и цитат в одном проекте Scrapy, проверка продолжения сбора и HTTP-кэша, сравнение с n8n. Сохранены 299 книг и 97 цитат.

## Файлы

- `quality/quality_report.ipynb` — пояснения, анализ, графики и сравнение.
- `lab5_crawler/spiders/books.py`, `quotes.py` — пауки для книг и цитат.
- `lab5_crawler/items.py` — поля записей; `pipelines.py` — проверка, очистка, дубли и запись в SQLite.
- `lab5_crawler/settings.py`, `common.py`, `scrapy.cfg` — настройки и общие функции проекта.
- `run_lab.py` — запуск сбора, опытов и контрольного замера.
- `data/crawl.db`, `items.jsonl` — база и выгрузка 396 записей.
- `data/run_manifest.json`, `stats_*.json` — номера запусков и статистика пауков.
- `data/experiments.json`, `benchmark.json`, `items_*_benchmark40.jsonl` — опыты JOBDIR, кэш и контрольные 40 книг.
- `jobstate/` — состояние очереди до и после продолжения сбора.
- `quality/analyze.py`, `smoke_check.py`, `current_snapshot.json` — анализ и проверка изменений относительно предыдущего сбора.
- `results.json` — сравнение и метрики n8n.
- `nocode/workflow.json` — схема n8n; `nocode_result.csv` — её результат из 40 строк.
- `nocode/screenshot_*.png` — схема и успешное выполнение.
- `nocode/compose.yaml` — настройки локального запуска n8n.
- `report.pdf` — краткий отчёт; `requirements.txt` — библиотеки Python.

## Python

Нужен Python 3.14. Из папки лабораторной:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m jupyterlab quality/quality_report.ipynb
```

В VS Code откройте `quality/quality_report.ipynb`, выберите установленную `.venv` через Select Kernel и нажмите Run All. Рабочая папка — папка блокнота или корень лабораторной. По умолчанию анализируется готовая база, Интернет не нужен.

Для нового сбора из корня лабораторной:

```powershell
.\.venv\Scripts\python.exe run_lab.py all
.\.venv\Scripts\python.exe -m quality.analyze
```

Для этого нужен Интернет. Режим `main` запускает только основной сбор, `experiments` — опыты JOBDIR и кэша, `benchmark` — контрольные 40 книг. Новые запуски создают журналы, кэш и промежуточные базы; их не требуется добавлять в Git. В `results.json` сохранена сравнительная таблица контрольного запуска от 26.10.2026, её значения автоматически не пересчитываются.

## n8n

Запустите Docker Desktop. Из папки лабораторной:

```powershell
docker compose -f nocode/compose.yaml up -d
```

Откройте http://localhost:5686, создайте локальный профиль и импортируйте `nocode/workflow.json` через Import from File. Нажмите Execute workflow. Сценарий загружает две страницы каталога и 40 карточек книг; результат сохраняется в `nocode/nocode_result.csv`, ошибки — в `nocode/error_log.csv`.

Расписание настроено на 09:00 по Перми, автоматический запуск выключен до публикации workflow. Для остановки: `docker compose -f nocode/compose.yaml stop`.
