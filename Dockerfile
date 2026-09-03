FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements.lock pyproject.toml ./
RUN pip install --upgrade pip \
    && pip install -r requirements.lock

COPY . .

RUN DJANGO_SETTINGS_MODULE=config.settings.production \
    TAKEBOARD_ENVIRONMENT=production \
    DJANGO_SECRET_KEY=build-placeholder-not-runtime-secret \
    MODERATION_HASH_SECRET=build-placeholder-not-runtime-secret \
    DJANGO_ALLOWED_HOSTS=example.com \
    DATABASE_URL=postgres://placeholder:placeholder@localhost:5432/placeholder \
    REDIS_URL=redis://localhost:6379/0 \
    python manage.py collectstatic --noinput

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
