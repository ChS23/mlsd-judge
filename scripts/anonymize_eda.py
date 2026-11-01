"""Обезличивает выгрузку для EDA: в репозиторий попадают только эти таблицы.

    uv run python scripts/anonymize_eda.py data/raw/eda/export.json data/eda

Соль лежит рядом с выгрузкой и в git не попадает: без неё номера команд и
прогонов не связать с платформой. Поля не из белого списка в выход не идут,
а итог проверяется на следы репозиториев, коммитов, адресов и имён.
"""

import argparse
import csv
import hashlib
import hmac
import json
import re
import secrets
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

COURSE_START = date(2026, 9, 1)
FORBIDDEN = [
    re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-"),  # UUID платформы
    re.compile(r"\b[0-9a-f]{12,}\b"),  # полный хеш коммита
    re.compile(r"github\.com|vstu|@[\w.-]+"),
    re.compile(r"[А-Яа-яЁё]"),  # в таблицах только коды, русский текст это след работы
]


def load_salt(path: Path) -> bytes:
    if not path.exists():
        path.write_text(secrets.token_hex(32), encoding="utf-8")
    return path.read_text(encoding="utf-8").encode()


def tag(salt: bytes, value: str | None) -> str:
    if not value:
        return ""
    return hmac.new(salt, value.encode(), hashlib.sha256).hexdigest()[:10]


def week_of(moment: str | None) -> int | str:
    """Неделя курса вместо даты: по точной дате сдачу легко найти в открытом PR."""
    if not moment:
        return ""
    day = datetime.fromisoformat(moment).date()
    return (day - COURSE_START).days // 7 + 1


def team_names(salt: bytes, teams: set[str]) -> dict[str, str]:
    # Порядок по соли: номер команды не выдаёт порядок записи на поток
    ordered = sorted(teams, key=lambda t: tag(salt, t))
    return {team: f"T{i:02d}" for i, team in enumerate(ordered, 1)}


def work_of(criterion_key: str) -> str:
    return criterion_key.split("-", 1)[0]


def verdict_rows(
    data: dict[str, Any], salt: bytes, teams: dict[str, str]
) -> list[dict[str, Any]]:
    asked = {q["verdict"] for q in data["questions"] if q["verdict"]}
    rows = []
    for v in data["verdicts"]:
        answers = v["samples"] or []
        rows.append(
            {
                "run": tag(salt, v["evaluation"]),
                "team": teams.get(v["team"], ""),
                "work": work_of(v["key"]),
                "criterion": v["key"],
                "role": v["role"] or "",
                "check_type": v["type"] or "",
                "weight": v["weight"] or "",
                "state": v["state"],
                "answers": ",".join(answers),
                "votes_split": len(set(answers)) > 1,
                "evidence": v["evidence"],
                "evidence_kinds": ",".join(sorted(k for k in v["kinds"] or [] if k)),
                "reason_len": v["reason_len"],
                "has_question": v["verdict"] in asked,
            }
        )
    return rows


def run_rows(
    data: dict[str, Any], salt: bytes, teams: dict[str, str]
) -> list[dict[str, Any]]:
    rows = []
    for e in data["evaluations"]:
        seconds = e["seconds"]
        rows.append(
            {
                "run": tag(salt, e["evaluation"]),
                "team": teams.get(e["team"], ""),
                "week": week_of(e["created"]),
                "trigger": e["trigger"],
                "status": e["status"],
                "agent": (e["agent"] or "").removeprefix("judge@"),
                # У импорта это время переноса со старой платформы, а не проверки
                "minutes": round(seconds / 60, 2)
                if seconds and e["trigger"] != "import"
                else "",
                "tokens_in": e["tokens_in"] or "",
                "tokens_out": e["tokens_out"] or "",
                "tokens_cached": e["tokens_cached"] or "",
                "attempts": e["attempts"],
            }
        )
    return rows


def review_rows(data: dict[str, Any], teams: dict[str, str]) -> list[dict[str, Any]]:
    closed = [r for r in data["reviews"] if r["closed"]]
    return [
        {
            "team": teams.get(r["team"], ""),
            "week": week_of(r["closed"]),
            "minutes": r["minutes"],
            "by_hand": r["by_hand"],
        }
        for r in closed
    ]


def summary_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Отметки только сводкой: по команде это уже оценка конкретных студентов."""
    states = {v["verdict"]: v["state"] for v in data["verdicts"]}
    counted = Counter(
        (
            q["source"],
            q["mark"] or "none",
            q["dispute"] or "none",
            states.get(q["verdict"], "none"),
        )
        for q in data["questions"]
    )
    return [
        {"source": s, "mark": m, "dispute": d, "verdict_state": v, "count": n}
        for (s, m, d, v), n in sorted(counted.items())
    ]


def recheck_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    counted = Counter(r["kind"] for r in data["rechecks"])
    return [{"kind": kind, "count": n} for kind, n in sorted(counted.items())]


def write(out: Path, name: str, rows: list[dict[str, Any]]) -> None:
    with (out / name).open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def scan(out: Path) -> list[str]:
    found = []
    for path in sorted(out.glob("*.csv")):
        text = path.read_text(encoding="utf-8")
        found += [f"{path.name}: {p.pattern}" for p in FORBIDDEN if p.search(text)]
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()

    data = json.loads(args.export.read_text(encoding="utf-8"))
    salt = load_salt(args.export.parent / "salt.txt")
    names = {e["team"] for e in data["evaluations"] if e["team"]}
    teams = team_names(salt, names)

    args.out.mkdir(parents=True, exist_ok=True)
    write(args.out, "verdicts.csv", verdict_rows(data, salt, teams))
    write(args.out, "runs.csv", run_rows(data, salt, teams))
    write(args.out, "reviews.csv", review_rows(data, teams))
    write(args.out, "questions_summary.csv", summary_rows(data))
    write(args.out, "rechecks_summary.csv", recheck_rows(data))

    leaks = scan(args.out)
    if leaks:
        raise SystemExit("Найдены следы данных: " + "; ".join(leaks))
    print("Следов данных нет, таблицы в", args.out)


if __name__ == "__main__":
    main()
