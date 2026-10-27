FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN useradd --create-home --uid 1000 app

FROM base AS build
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --prefix=/install .

FROM base AS runtime
COPY --from=build /install /usr/local
COPY alembic.ini ./
COPY migrations ./migrations
RUN chown -R app:app /app
USER app
EXPOSE 8000
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" || exit 1
CMD ["uvicorn", "hungry_hunt.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
