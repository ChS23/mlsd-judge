# Данные для EDA

Обезличенная выгрузка проверок на потоке 4 курса, срез на 1 ноября 2026 года. Собирается скриптом `scripts/anonymize_eda.py`. Авторы сдач согласились на использование работ для оценки качества.

Вместо команд здесь номера `T01`–`T08`, вместо прогонов случайные метки, вместо дат недели курса. Имён, репозиториев, коммитов, текстов обоснований и цитат нет. Соль для меток хранится вне репозитория. Отметки приёмки есть только сводкой, без команд.

| Файл | Строка | Поля |
|---|---|---|
| `verdicts.csv` | вердикт | `run`, `team`, `work`, `criterion`, `role`, `check_type`, `weight`, `state`, `answers`, `votes_split`, `evidence`, `evidence_kinds`, `reason_len`, `has_question` |
| `runs.csv` | прогон | `run`, `team`, `week`, `trigger`, `status`, `agent`, `minutes`, `tokens_in`, `tokens_out`, `tokens_cached`, `attempts` |
| `reviews.csv` | закрытая приёмка | `team`, `week`, `minutes`, `by_hand` |
| `questions_summary.csv` | сочетание значений | `source`, `mark`, `dispute`, `verdict_state`, `count` |
| `rechecks_summary.csv` | вид запроса | `kind`, `count` |

Значения: `state` это `closed`, `open` или `unsure`. `answers` это ответы модели по порядку. `trigger` это `submit`, `recheck` или `import`. У прогонов `import`, перенесённых со старой платформы, нет времени и типа проверки. `mark` это ответ студента на вопрос приёмки, а не оценка вердикта. Цен здесь нет.
