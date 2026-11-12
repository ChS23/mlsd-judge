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
# Коды вместо ключей потоков: ключ потока виден на платформе
COURSES = {"stream-5": "c4", "practice-2026-3-1": "c3"}
# Практику публикуем только сводками: её репозитории закрытые
ROWS = {"c4"}
MINUTE_BIN = 2
HOLDOUT_TEAMS = 2
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


def split_rows(salt: bytes, teams: list[str]) -> list[dict[str, str]]:
    """Отложенные команды выбираются солью, а не руками: так их не подгонишь."""
    ordered = sorted(teams, key=lambda t: tag(salt, "split:" + t))
    held = set(ordered[:HOLDOUT_TEAMS])
    rows = [
        {"course": "c4", "team": t, "part": "holdout" if t in held else "work"}
        for t in sorted(teams)
    ]
    # практика целиком отложенный курс, команды по ней не публикуем
    return [*rows, {"course": "c3", "team": "all", "part": "holdout"}]


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
                "course": COURSES[v["course"]],
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
                "course": COURSES[e["course"]],
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
            "course": COURSES[r["course"]],
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
            COURSES[q["course"]],
            q["source"],
            q["mark"] or "none",
            q["dispute"] or "none",
            states.get(q["verdict"], "none"),
        )
        for q in data["questions"]
    )
    return [
        {
            "course": c,
            "source": s,
            "mark": m,
            "dispute": d,
            "verdict_state": v,
            "count": n,
        }
        for (c, s, m, d, v), n in sorted(counted.items())
    ]


def recheck_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    counted = Counter((COURSES[r["course"]], r["kind"]) for r in data["rechecks"])
    return [
        {"course": c, "kind": kind, "count": n}
        for (c, kind), n in sorted(counted.items())
    ]


def quantile(values: list[int] | list[float], q: float) -> float:
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (pos - low), 1)


def aggregates(
    verdicts: list[dict[str, Any]],
    runs: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    failed: int,
) -> tuple[
    list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]
]:
    """Сводки курса без построчных данных: только счётчики и квантили."""
    counted = Counter(
        (v["work"], v["criterion"], v["check_type"], v["state"]) for v in verdicts
    )
    split = Counter((v["criterion"], v["state"]) for v in verdicts if v["votes_split"])
    voted = Counter((v["criterion"], v["state"]) for v in verdicts if v["answers"])
    asked = Counter((v["criterion"], v["state"]) for v in verdicts if v["has_question"])
    states = [
        {
            "work": w,
            "criterion": c,
            "check_type": t,
            "state": st,
            "count": n,
            "with_answers": voted[(c, st)],
            "votes_split": split[(c, st)],
            "has_question": asked[(c, st)],
        }
        for (w, c, t, st), n in sorted(counted.items())
    ]
    by_week = Counter((r["week"], r["trigger"], r["status"]) for r in runs)
    weeks = [
        {"week": w, "trigger": t, "status": st, "count": n}
        for (w, t, st), n in sorted(by_week.items())
    ]
    done = [r for r in runs if r["status"] == "done" and r["minutes"] != ""]
    bins = Counter(int(r["minutes"] // MINUTE_BIN) * MINUTE_BIN for r in done)
    hist = [{"from_minute": b, "count": n} for b, n in sorted(bins.items())]
    minutes = [r["minutes"] for r in done]
    used = [r for r in done if r["tokens_in"] != ""]
    tokens = [r["tokens_in"] + r["tokens_out"] for r in used]
    chains: dict[tuple[str, str, str], set[str]] = {}
    sizes: Counter[tuple[str, str, str]] = Counter()
    for v in verdicts:
        key = (v["team"], v["role"], v["criterion"])
        chains.setdefault(key, set()).add(v["state"])
        sizes[key] += 1
    repeated = [k for k, n in sizes.items() if n > 1]
    per_team = list(Counter(v["team"] for v in verdicts).values())
    unsure = [v for v in verdicts if v["state"] == "unsure"]
    review_minutes = [r["minutes"] for r in reviews if r["minutes"] is not None]
    summary = {
        "runs_failed": failed,
        "teams": len(per_team),
        "verdicts_per_team": {
            "min": min(per_team),
            "median": quantile(per_team, 0.5),
            "max": max(per_team),
        },
        "runs": len(runs),
        "runs_done": len(done),
        "verdicts": len(verdicts),
        "minutes": {
            "median": quantile(minutes, 0.5),
            "p95": quantile(minutes, 0.95),
            "max": max(minutes),
        },
        "tokens_per_run": {
            "median": quantile(tokens, 0.5),
            "p95": quantile(tokens, 0.95),
        },
        "cache_share": round(
            sum(r["tokens_cached"] for r in used) / sum(r["tokens_in"] for r in used), 3
        ),
        "unsure_unanimous": sum(
            1 for v in unsure if v["answers"] and not v["votes_split"]
        ),
        "criteria_checked_twice": len(repeated),
        "criteria_changed_share": round(
            sum(1 for k in repeated if len(chains[k]) > 1) / len(repeated), 3
        ),
        "reviews": len(reviews),
        "review_minutes_median": quantile(review_minutes, 0.5)
        if review_minutes
        else None,
    }
    return states, weeks, hist, summary


def write(out: Path, name: str, rows: list[dict[str, Any]]) -> None:
    with (out / name).open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def scan(out: Path) -> list[str]:
    found = []
    for path in sorted([*out.glob("*.csv"), *out.glob("*.json")]):
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
    verdicts = verdict_rows(data, salt, teams)
    runs = run_rows(data, salt, teams)
    reviews = review_rows(data, teams)
    write(args.out, "verdicts.csv", [v for v in verdicts if v["course"] in ROWS])
    write(args.out, "runs.csv", [r for r in runs if r["course"] in ROWS])
    write(args.out, "reviews.csv", [r for r in reviews if r["course"] in ROWS])
    c4_teams = sorted(
        {v["team"] for v in verdicts if v["course"] == "c4" and v["team"]}
    )
    write(args.out, "split.csv", split_rows(salt, c4_teams))
    for code in sorted(set(COURSES.values()) - ROWS):
        new_runs = {
            r["run"] for r in runs if r["course"] == code and r["agent"] == "0.1.0"
        }
        states, weeks, hist, summary = aggregates(
            [v for v in verdicts if v["course"] == code and v["run"] in new_runs],
            [r for r in runs if r["course"] == code and r["agent"] == "0.1.0"],
            [r for r in reviews if r["course"] == code],
            sum(1 for r in runs if r["course"] == code and r["status"] == "failed"),
        )
        write(args.out, f"{code}_verdict_counts.csv", states)
        write(args.out, f"{code}_runs_by_week.csv", weeks)
        write(args.out, f"{code}_minutes_hist.csv", hist)
        (args.out / f"{code}_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
    write(args.out, "questions_summary.csv", summary_rows(data))
    write(args.out, "rechecks_summary.csv", recheck_rows(data))

    leaks = scan(args.out)
    if leaks:
        raise SystemExit("Найдены следы данных: " + "; ".join(leaks))
    print("Следов данных нет, таблицы в", args.out)


if __name__ == "__main__":
    main()
