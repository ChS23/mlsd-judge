# Данные для EDA

Обезличенная выгрузка проверок на двух курсах, срез на 8 ноября 2026 года: 4 курс «Системы ИИ» (код `c4`) и практика 3 курса (код `c3`). Собирается скриптом `scripts/anonymize_eda.py`. Авторы работ обоих курсов согласились на использование данных для оценки качества.

Вместо команд здесь номера `T01`, `T02` и так далее, вместо прогонов случайные метки, вместо дат недели курса. Имён, репозиториев, коммитов, текстов обоснований и цитат нет. Соль для меток хранится вне репозитория. Отметки приёмки есть только сводкой, без команд.

Репозитории практики закрытые, поэтому по ней здесь только сводки, без построчных данных.

| Файл | Строка | Поля |
|---|---|---|
| `verdicts.csv` | вердикт 4 курса | `run`, `course`, `team`, `work`, `criterion`, `role`, `check_type`, `weight`, `state`, `answers`, `votes_split`, `evidence`, `evidence_kinds`, `reason_len`, `has_question` |
| `runs.csv` | прогон 4 курса | `run`, `course`, `team`, `week`, `trigger`, `status`, `agent`, `minutes`, `tokens_in`, `tokens_out`, `tokens_cached`, `attempts` |
| `reviews.csv` | закрытая приёмка 4 курса | `course`, `team`, `week`, `minutes`, `by_hand` |
| `c3_verdict_counts.csv` | сочетание работы, критерия и вердикта практики | `work`, `criterion`, `check_type`, `state`, `count`, `with_answers`, `votes_split`, `has_question` |
| `c3_runs_by_week.csv` | неделя практики | `week`, `trigger`, `status`, `count` |
| `c3_minutes_hist.csv` | интервал в 2 минуты | `from_minute`, `count` |
| `c3_summary.json` | итоговые числа практики | команды, прогоны, квантили времени и токенов, доля кэша, стабильность, приёмки |
| `questions_summary.csv` | сочетание значений | `course`, `source`, `mark`, `dispute`, `verdict_state`, `count` |
| `rechecks_summary.csv` | вид запроса | `course`, `kind`, `count` |

Значения: `state` это `closed`, `open` или `unsure`. `answers` это ответы модели по порядку. `trigger` это `submit`, `recheck` или `import`. У прогонов `import`, перенесённых со старой платформы, нет времени и типа проверки. `mark` это ответ студента на вопрос приёмки, а не оценка вердикта. Цен здесь нет.
