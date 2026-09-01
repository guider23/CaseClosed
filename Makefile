.PHONY: install run test clean generate train metrics

install:
	python -m pip install -r requirements.txt

run:
	python -m src.chargeback.api

generate:
	python -m src.chargeback.generator

train:
	python -c "from src.chargeback.model import train_and_save; train_and_save()"

metrics:
	python -m src.chargeback.metrics_report

test:
	pytest -v

clean:
	rm -rf __pycache__ .pytest_cache .mypy_cache .ruff_cache *.db logs/ data/
