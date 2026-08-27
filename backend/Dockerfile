# Production image — spec Part 4.3 / Part 9 (hardened, non-root)
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv/app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    # production profile extras (spec Part 4):
    && pip install --no-cache-dir celery[redis] asyncpg "sqlalchemy[asyncio]" cryptography

COPY backend/app ./app
COPY seed /srv/seed

RUN useradd -r -u 10001 th360 && chown -R th360 /srv
USER th360

EXPOSE 8000
ENV TH360_ENV=production

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
