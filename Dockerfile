# syntax=docker/dockerfile:1.7
# Imagen multi-stage: dependencias compiladas en una capa, runtime mínimo y usuario no-root.
FROM python:3.11-slim AS builder
WORKDIR /build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt

FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ENVIRONMENT=local
WORKDIR /app
COPY --from=builder /install /usr/local
COPY app ./app
COPY scripts ./scripts
COPY data ./data
RUN useradd --create-home --uid 10001 appuser && mkdir -p storage && chown -R appuser /app/storage
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
# Un proceso por réplica: el escalado horizontal lo hace Container Apps (KEDA).
# En modo local el índice vive en memoria del proceso, por eso no se usan varios workers.
