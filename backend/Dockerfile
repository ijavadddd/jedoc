FROM python:3.12-slim

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY backend /app/backend
COPY bundled_skills /app/bundled_skills

ENV PYTHONUNBUFFERED=1 \
    JEDOC_DATA_DIR=/app/data \
    JEDOC_BUNDLED_SKILLS=/app/bundled_skills

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "backend.api.server:app", "--host", "0.0.0.0", "--port", "8000"]
