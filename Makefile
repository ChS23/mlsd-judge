.PHONY: check eda data

check:
	uv run pre-commit run --all-files

eda:
	uv sync --group eda
	cd notebooks && uv run python -m nbconvert --to notebook --execute --inplace eda.ipynb

# нужна закрытая выгрузка из платформы, у ревьюеров её нет
data:
	uv run python scripts/anonymize_eda.py data/raw/eda/export.json data/eda
