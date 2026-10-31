"""Собирает пакет для слепой разметки: данные судьи без его ответов.

    uv run python scripts/build_packet.py cases.json data/raw/packets/x

`cases.json` выгружается из платформы и лежит вне репозитория: список случаев
с полями case, repo, sha, pr, evaluated_at, role, criterion, assignment.
Правила разметки: docs/labeling_protocol.md.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

# Отчёт судьи в PR раскрыл бы разметчику ответ
JUDGE_MARKER = "<!-- disputa:check -->"
JUDGE_CHECK = "Автопроверка"

GIT_ENV = {**os.environ, "GIT_LFS_SKIP_SMUDGE": "1", "GIT_TERMINAL_PROMPT": "0"}
# Репозиторий студента это данные: хуки не запускаем, ссылки не разворачиваем
GIT_SAFE = ["-c", "core.hooksPath=/dev/null", "-c", "core.symlinks=false"]


@dataclass(frozen=True)
class Commented:
    login: str
    kind: str
    body: str


def run(*cmd: str, cwd: Path | None = None) -> str:
    return subprocess.run(  # noqa: S603
        cmd, cwd=cwd, check=True, capture_output=True, text=True, env=GIT_ENV
    ).stdout


def gh(path: str) -> Any:
    return json.loads(run("gh", "api", "--paginate", "--slurp", path))


def flat(pages: Any) -> list[dict[str, Any]]:
    return [item for page in pages for item in page]


def moment(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def is_judge(comment: Commented) -> bool:
    return (
        comment.kind == "Bot"
        or comment.login.endswith("[bot]")
        or JUDGE_MARKER in comment.body
        or JUDGE_CHECK in comment.body
    )


def open_at(pull: dict[str, Any], when: datetime) -> bool:
    """Был ли PR открыт на момент проверки: сегодняшний статус этого не скажет."""
    if moment(pull["created_at"]) > when:
        return False
    closed = pull.get("closed_at")
    return closed is None or moment(closed) > when


def discussion(repo: str, number: int, until: datetime) -> list[dict[str, str]]:
    """Обсуждение на момент проверки: позже участники пересказывают вердикт."""
    pages = [f"repos/{repo}/issues/{number}/comments"]
    pages.append(f"repos/{repo}/pulls/{number}/comments")
    found = []
    for path in pages:
        for raw in flat(gh(path)):
            user = raw.get("user") or {}
            comment = Commented(
                user.get("login") or "", user.get("type") or "", raw.get("body") or ""
            )
            if not is_judge(comment) and moment(raw["created_at"]) <= until:
                found.append({"at": raw["created_at"], "body": comment.body})
    return sorted(found, key=lambda c: c["at"])


def checks(repo: str, sha: str) -> list[dict[str, Any]]:
    runs = []
    for page in gh(f"repos/{repo}/commits/{sha}/check-runs"):
        runs += page["check_runs"]
    return [
        {"name": r["name"], "status": r["status"], "conclusion": r["conclusion"]}
        for r in runs
        if r["name"] != JUDGE_CHECK
    ]


def required_checks(repo: str, branch: str) -> dict[str, Any]:
    """Настройки ветки только на сегодня: истории их изменений GitHub не отдаёт."""
    data = json.loads(run("gh", "api", f"repos/{repo}/branches/{branch}"))
    return {
        "branch": branch,
        "read_on": datetime.now().astimezone().date().isoformat(),
        "protected": data.get("protected"),
        "required_status_checks": (data.get("protection") or {}).get(
            "required_status_checks"
        ),
    }


def clone(repo: str, cache: Path) -> Path:
    target = cache / repo.replace("/", "__")
    if target.exists():
        return target
    url = f"https://github.com/{repo}.git"
    run("git", *GIT_SAFE, "clone", "--quiet", "--no-checkout", url, str(target))
    # Ветки могли удалить после слияния, ссылки на PR остаются
    run(
        "git",
        *GIT_SAFE,
        "fetch",
        "--quiet",
        "origin",
        "+refs/pull/*/head:refs/pr/*",
        cwd=target,
    )
    return target


def export_tree(source: Path, commit: str, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    archive = subprocess.Popen(  # noqa: S603
        ["git", "archive", commit],  # noqa: S607
        cwd=source,
        stdout=subprocess.PIPE,
        env=GIT_ENV,
    )
    subprocess.run(  # noqa: S603
        ["tar", "-x", "-C", str(target)],  # noqa: S607
        stdin=archive.stdout,
        check=True,
    )
    if archive.stdout:
        archive.stdout.close()
    if archive.wait() != 0:
        raise RuntimeError(f"git archive {commit} не сработал")


def commit_before(source: Path, ref: str, when: str) -> str | None:
    found = run("git", "rev-list", "-1", f"--before={when}", ref, cwd=source).strip()
    return found or None


def team_snapshots(
    source: Path, case: dict[str, Any], pulls: list[dict[str, Any]], target: Path
) -> list[dict[str, Any]]:
    when = moment(case["evaluated_at"])
    listed = []
    for pull in pulls:
        if pull["number"] == case["pr"] or not open_at(pull, when):
            continue
        ref = f"refs/pr/{pull['number']}"
        commit = commit_before(source, ref, case["evaluated_at"])
        if not commit:
            continue
        name = re.sub(r"[^\w.-]+", "_", pull["head"]["ref"])
        export_tree(source, commit, target / f"pr-{pull['number']}-{name}")
        listed.append(
            {
                "number": pull["number"],
                "title": pull["title"],
                "branch": pull["head"]["ref"],
                "commit": commit,
                "path": f"team/pr-{pull['number']}-{name}",
            }
        )
    return listed


def build(case: dict[str, Any], out: Path, cache: Path) -> None:
    repo, sha, number = case["repo"], case["sha"], case["pr"]
    root = out / case["case"]
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)

    source = clone(repo, cache)
    export_tree(source, sha, root / "work")
    # Судья видит историю до сдачи: забираем только предков коммита, иначе
    # чужие ветки и более поздние коммиты останутся в объектах копии
    history = root / "history"
    run("git", "init", "--quiet", str(history))
    run("git", "config", "uploadpack.allowAnySHA1InWant", "true", cwd=source)
    run("git", "fetch", "--quiet", str(source.resolve()), sha, cwd=history)
    run("git", "update-ref", "refs/heads/main", sha, cwd=history)
    run("git", "symbolic-ref", "HEAD", "refs/heads/main", cwd=history)

    pull = json.loads(run("gh", "api", f"repos/{repo}/pulls/{number}"))
    pulls = flat(gh(f"repos/{repo}/pulls?state=all&per_page=100"))
    team = team_snapshots(source, case, pulls, root / "team")
    base = pull["base"]["ref"]
    main = commit_before(source, f"refs/remotes/origin/{base}", case["evaluated_at"])
    if main:
        export_tree(source, main, root / "team" / f"base-{base}")

    facts = {
        "pr": {
            "number": number,
            "title": pull["title"],
            "body": pull["body"],
            "base": base,
            "head": pull["head"]["ref"],
            "created_at": pull["created_at"],
        },
        "changed_files": [
            f["filename"] for f in flat(gh(f"repos/{repo}/pulls/{number}/files"))
        ],
        "checks": checks(repo, sha),
        "required_checks": required_checks(repo, base),
        "discussion": discussion(repo, number, moment(case["evaluated_at"])),
        "team_pulls": team,
    }
    (root / "github.json").write_text(
        json.dumps(facts, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    task = {
        "case": case["case"],
        "repo": repo,
        "sha": sha,
        "evaluated_at": case["evaluated_at"],
        "role": case["role"],
        "criterion": case["criterion"],
        "assignment": case["assignment"],
    }
    (root / "task.json").write_text(
        json.dumps(task, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    cache = args.out / ".cache"
    cache.mkdir(parents=True, exist_ok=True)
    for case in cases:
        build(case, args.out, cache)
        print(case["case"], "готов")


if __name__ == "__main__":
    main()
