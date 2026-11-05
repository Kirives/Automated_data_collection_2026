# Лабораторная работа № 3

Вшивков К. И., ПМИ-3-2025. Вариант 6.

Сбор населения и ВВП стран через World Bank API, добавление столиц из CountriesNow, проверка данных и сравнение с n8n. Период: 2020–2022 годы.

## Файлы

- `lab3.ipynb` — код, пояснения, результаты, графики и сравнение.
- `data_raw.jsonl` — исходные ответы API.
- `data_clean.csv` — итоговая таблица из 651 строки.
- `collection_log.csv` — журнал запросов: страницы, статусы, параметры и время.
- `state.json` — последний полученный год, накопленные наблюдения и результаты запусков.
- `nocode/workflow.json` — схема n8n; `nocode_result.csv` — её результат из 30 строк.
- `nocode/screenshot_*.png` — схема и успешное выполнение.
- `nocode/compose.yaml` — настройки локального запуска n8n.
- `report.pdf` — отчёт с контрольными замерами от 25.10.2026.
- `requirements.txt` — библиотеки Python.

## Python

Нужен Python 3.14. Из папки лабораторной:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m jupyterlab lab3.ipynb
```

В VS Code откройте `lab3.ipynb`, выберите эту `.venv` через Select Kernel и нажмите Run All. Рабочая папка — папка блокнота. Для запуска нужен Интернет; ключи API и переменные с секретами не требуются.

Блокнот обновляет CSV, журнал и состояние, затем выполняет повторный сбор. Совпавшие записи обновляются по ключу, дубликаты не добавляются. Для полного сбора в отдельную папку можно вызвать `run_collection("fresh_run")` после определения функций.

## n8n

Установите и запустите Docker Desktop. Из папки лабораторной выполните:

```powershell
docker compose -f nocode/compose.yaml up -d
```

Откройте http://localhost:5684, создайте локальный профиль и импортируйте `nocode/workflow.json` через Import from File. Нажмите Execute workflow. Результат сохраняется в `nocode/nocode_result.csv`, ошибка — в `nocode/error_log.csv`.

Расписание настроено на 09:00 по Перми, автоматический запуск выключен до публикации workflow. Для остановки:

```powershell
docker compose -f nocode/compose.yaml stop
```
