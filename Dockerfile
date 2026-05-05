FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

COPY pyproject.toml README.md ./
COPY dragun ./dragun

RUN pip install --no-cache-dir .

EXPOSE 8080

CMD ["sh", "-c", "uvicorn dragun.app:app --host 0.0.0.0 --port ${PORT:-8080}"]
