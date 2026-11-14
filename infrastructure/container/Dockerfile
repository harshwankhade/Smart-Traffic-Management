FROM python:3.14-slim

ARG SERVICE_DIR
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/contracts/python:/app/${SERVICE_DIR}

WORKDIR /app
COPY requirements-lock.txt ./
RUN pip install --no-cache-dir -r requirements-lock.txt
COPY contracts ./contracts
COPY services ./services

WORKDIR /app/${SERVICE_DIR}
EXPOSE 8000 50051
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}"]
