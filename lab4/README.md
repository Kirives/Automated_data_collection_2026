# Лабораторная работа № 4

Вшивков К. И., ПМИ-3-2025. Вариант 6.

Сбор динамических страниц через Playwright и прямые HTTP-запросы, проверка качества и сравнение с n8n. В сохранённом наборе 207 товаров: 147 из ScrapingCourse и 60 из Web Scraper.

## Файлы

- `lab4.ipynb` — пояснения, проверки, график и сравнение способов.
- `collect.py`, `webscraper_source.py` — код сбора двух каталогов.
- `diagnose.py` — проверка HTML, JavaScript, AJAX и обработки таймаута.
- `data_browser.csv`, `data_light.csv` — совпадающие результаты двух способов сбора.
- `collection_log.csv` — журнал запросов и нажатий кнопок.
- `results.json` — диагностика, метрики, проверки качества и контрольные замеры.
- `artifacts/` — исходный HTML, robots.txt и снимки диагностики и сбоя.
- `render_api.py` — локальный браузерный рендерер для n8n.
- `nocode/workflow.json` — схема n8n; `nocode_result.csv` — её результат из 22 строк.
- `nocode/screenshot_*.png` — схема и успешное выполнение.
- `nocode/compose.yaml` — настройки локального запуска n8n.
- `report.pdf` — краткий отчёт.
- `requirements.txt` — библиотеки Python.

## Python

Нужен Python 3.14. Из папки лабораторной:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe -m jupyterlab lab4.ipynb
```

В VS Code откройте `lab4.ipynb`, выберите установленную `.venv` через Select Kernel и нажмите Run All. Рабочая папка - папка блокнота. По умолчанию анализируются сохранённые результаты, Интернет не нужен.

Чтобы повторить сбор, установите `RUN_COLLECTION = True` в первой ячейке или выполните:

```powershell
.\.venv\Scripts\python.exe diagnose.py
.\.venv\Scripts\python.exe collect.py browser
.\.venv\Scripts\python.exe collect.py light
.\.venv\Scripts\python.exe collect.py benchmark
```

Для сбора нужен Интернет. CSV и соответствующие метрики в `results.json` обновляются, журнал дополняется. Сводная таблица сравнения хранит контрольные замеры от 25.10.2026; после нового сбора её значения автоматически не пересчитываются.

## n8n

Запустите Docker Desktop. В первом терминале из папки лабораторной запустите рендерер и оставьте терминал открытым:

```powershell
.\.venv\Scripts\python.exe render_api.py
```

Во втором терминале из той же папки:

```powershell
docker compose -f nocode/compose.yaml up -d
```

Откройте http://localhost:5685, создайте локальный профиль и импортируйте `nocode/workflow.json` через Import from File. Нажмите Execute workflow. Workflow обращается к рендереру на порту 8766. Результат сохраняется в `nocode/nocode_result.csv`, ошибки — в `nocode/error_log.csv`.

Расписание настроено на 09:00 по Перми, автоматический запуск выключен до публикации workflow. Для остановки n8n выполните `docker compose -f nocode/compose.yaml stop`; рендерер остановите сочетанием Ctrl+C.
