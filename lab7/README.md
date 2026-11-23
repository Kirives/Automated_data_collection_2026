# Лабораторная работа № 7

Вшивков К. И., ПМИ-3-2025. Вариант 6.

Доработка сборщика из предыдущих лабораторных: независимая скорость для трёх доменов, повторы, предохранитель, уменьшение трафика и проверка результата. Основные опыты выполнены на локальном HTTP-стенде с 60 записями. В сохранённом внешнем прогоне от 26.10.2026 получены 35 записей и HTTP 304.

## Файлы

- `analysis.ipynb` — пояснения, таблицы, графики, сравнение и скриншот n8n.
- `src/collect.py`, `live.py` — общий HTTP-клиент и сбор с трёх сайтов.
- `src/limiter.py`, `retry.py`, `breaker.py` — скорость, повторы и предохранитель.
- `src/detector.py`, `observability.py` — проверка ответов, JSONL-журнал и оповещения.
- `src/fixtures.py`, `run_experiments.py`, `fixtures/records.json` — локальный стенд и опыты A/B/C, отказы, экономия нагрузки.
- `state/` — ETag, Last-Modified, сохранённые ответы и watermark между прогонами.
- `logs/` — журналы; `logs/incidents/` — тела и заголовки ответов при блокировке.
- `reports/` — метрики, результаты и сравнение; `live_*` и `real_responses/` — внешний контроль; `robots/` — полученные правила сайтов.
- `nocode/workflow.json` — схема n8n; `nocode_result.csv` — 60 записей; `screenshot_success.png` — выполненная схема.
- `nocode/workflow_error_test.json`, `error_log.csv` — проверка ветки ошибки; JSON-файлы — сведения о сохранённых запусках.
- `nocode/nocode_notes.md` — сравнение с Python, ограничения и стоимость; `compose.yaml` — запуск n8n.
- `legal_checklist.md` — обязательный правовой чек-лист; `report.pdf` — отчёт.
- `tests/test_resilience.py` — проверки повторов, предохранителя, детектора и блокировки домена между процессами.
- `requirements.txt` — библиотеки Python.

## Python

Нужен Python 3.14 под Windows. Из папки лабораторной:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m jupyterlab analysis.ipynb
```

В VS Code откройте `analysis.ipynb`, выберите `.venv` через Select Kernel и нажмите Run All. На подготовленном компьютере можно выбрать общее ядро Python (Labs 3-7). Ноутбук читает сохранённые результаты; Интернет и Docker для этого не нужны.

Повторить локальные опыты:

```powershell
python -m src.run_experiments
python -m unittest discover -s tests -v
python -m src.run_experiments --block-demo captcha
python -m src.run_experiments --block-demo 403
```

Используйте Python выбранного окружения. Две последние команды должны вернуть код 2: домен остановлен, инцидент сохранён. После опытов повторно выполните ноутбук. Новые журналы и отчёты заменяют текущие, прежние журналы и состояние попадают в `archive/`. Пересчитанные графики видны в ноутбуке; PDF содержит замеры, сохранённые при подготовке работы.

Внешний контроль: `python -m src.live`. Он читает robots.txt, собирает данные Books to Scrape, ScrapingCourse и World Bank. В User-Agent указан `test@mail.ru`; изменить контакт можно через переменную `LAB7_CONTACT`. Даты внешнего контроля и локальных опытов находятся в журналах.

## n8n

Запустите Docker Desktop. В первом терминале из папки работы:

```powershell
python -m src.fixtures
```

Оставьте терминал открытым: локальный стенд работает на порту 8768. Во втором терминале:

```powershell
docker compose -f nocode/compose.yaml up -d
```

Откройте http://localhost:5688, создайте локальный профиль и импортируйте `nocode/workflow.json` через Import from File. Нажмите Execute workflow. Получится `nocode/nocode_result.csv` с 60 строками. Стенд специально обрывает первые два соединения; n8n повторяет запрос и продолжает работу. Для повторения этого опыта перезапустите стенд.

`workflow_error_test.json` проверяет ответ 403. Ожидается ошибка выполнения и запись в `error_log.csv`, повторного запроса при 403 нет.

Расписание — ежедневно в 09:00 по Перми, автоматический запуск выключен до публикации workflow. Остановка n8n: `docker compose -f nocode/compose.yaml stop`; остановка стенда: Ctrl+C.

## Что показать

Откройте `analysis.ipynb`: A теряет страницу, B получает её повтором, C сохраняет все 60 записей с меньшим трафиком. Покажите переходы предохранителя, два графика, затем схему n8n и CSV. Если нужен код — откройте соответствующий файл в `src/`. Отчёт и правовой чек-лист включены в работу.
