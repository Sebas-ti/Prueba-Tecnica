.PHONY: install ingest run test lint eval eval-holdout docker-build docker-run deploy

install:
	python -m pip install -r requirements-dev.txt

ingest:
	python -m scripts.ingest

run:
	uvicorn app.main:app --reload --port 8000

test:
	python -m pytest

lint:
	ruff check .

eval:
	python -m eval.run_eval

eval-holdout:
	python -m eval.run_eval --dataset eval/dataset_holdout.json --out eval/results/holdout

docker-build:
	docker build -t ic7-rag-agent:local .

docker-run:
	docker compose up --build

deploy:
	bash scripts/deploy_azure.sh
