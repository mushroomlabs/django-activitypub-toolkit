# This docker image is mostly used for development
# Start with a Python image.
FROM python:3.11

ENV PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_CACHE_DIR='/var/cache/pypoetry'

RUN pip install poetry

WORKDIR /app
COPY pyproject.toml poetry.lock /app

# Copy all relevant files into the image.
COPY ./activitypub /app/activitypub
COPY ./README.md /app
COPY ./LICENSE /app
COPY ./pytest.ini /app
COPY ./project /app/project

RUN poetry install --no-root
