# Лабораторная работа № 6

Вшивков К. И., ПМИ-3-2025. Вариант 6.

Хранение и очистка данных World Bank и Books to Scrape: raw → clean → SQLite и mart. В чистом наборе 661 строка, в n8n — 40 корректных и 4 ошибочные строки.

## Файлы

- `quality_report.ipynb` — пояснения, проверки, таблицы, графики и сравнение с n8n.
- `src/clean.py`, `contract.py`, `quality.py` — очистка, контракт Pydantic и пороги качества.
- `src/common.py`, `rebuild.py` — общие функции и пересборка из raw.
- `raw/` — исходные JSONL, отдельные тестовые копии и контрольные суммы. Этот слой не перезаписывается при обработке.
- `clean/dataset.parquet` — чистый набор; `rejects.jsonl` — отбракованные строки с причинами.
- `clean/cleaning_protocol.csv` — количество строк на каждом шаге очистки.
- `clean/formats/`, `format_benchmark.csv` — один набор в трёх форматах и замеры чтения.
- `db/schema.sql`, `load.py` — схема SQLite и пакетный UPSERT.
- `db/warehouse.db` — рабочая база; `idempotency_demo.db` и `clean/history_demo.csv` — опыт с повторной загрузкой и изменением двух цен.
- `mart/` — три витрины и снимок, разделённый по дате получения данных.
- `results.json` — проверки контракта и БД, метрики качества и результаты опытов.
- `nocode/workflow.json`, `input.csv` — схема n8n и входная таблица.
- `nocode/nocode_result.csv`, `rejects.csv` — корректные и ошибочные строки.
- `nocode/screenshot_*.png`, `compose.yaml` — схема, успешный запуск и настройки n8n.
- `report.pdf` — краткий отчёт; `requirements.txt` — библиотеки Python.

## Python

Нужен Python 3.14. Из папки лабораторной:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m jupyterlab quality_report.ipynb
```

В VS Code откройте блокнот, выберите установленную `.venv` через Select Kernel и нажмите Run All. Рабочая папка — папка блокнота. По умолчанию анализируются сохранённые результаты. Все исходные данные находятся в `raw`, соседние лабораторные и Интернет не нужны.

Чтобы повторить обработку и три загрузки в демонстрационную БД:

```powershell
.\.venv\Scripts\python.exe -m src.rebuild --demo-db
```

Команда обновляет clean, рабочую базу, витрины и метрики. Предыдущая демонстрационная БД переносится в `db/archive`. Для обработки без повторения опыта достаточно `python -m src.rebuild`. Из блокнота обработку можно включить параметром `RUN_REBUILD = True`.

Проверяется возраст данных: до 7 дней — зелёный статус, до 30 — жёлтый, старше — красный. При красном статусе загрузка mart останавливается. Сохранённый отчёт содержит результаты от 25–26.10.2026; при более поздней пересборке статус давности может измениться.

## n8n

Запустите Docker Desktop. Из папки лабораторной:

```powershell
docker compose -f nocode/compose.yaml up -d
```

Откройте http://localhost:5687, создайте локальный профиль и импортируйте `nocode/workflow.json` через Import from File. Нажмите Execute workflow. Сценарий читает `nocode/input.csv`, сохраняет корректные строки в `nocode/nocode_result.csv`, ошибки в данных — в `nocode/rejects.csv`.

n8n выполняет нормализацию, удаление дублей и разделение строк. UPSERT, полная проверка контракта, история и пороги качества реализованы в Python.

Расписание настроено на 09:00 по Перми, автоматический запуск выключен до публикации workflow. Для остановки: `docker compose -f nocode/compose.yaml stop`.
