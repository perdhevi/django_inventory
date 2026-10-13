ARG PYTHON_VERSION=3.14
FROM python:${PYTHON_VERSION}-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.22 /uv /uvx /bin/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY . .
RUN mkdir -p /app/staticfiles && chown -R 10001:10001 /app
ENV PATH="/app/.venv/bin:$PATH" HOME=/app
USER 10001
EXPOSE 8000
CMD ["sh", "-c", "python manage.py collectstatic --noinput && exec gunicorn django_inventory.wsgi:application --bind 0.0.0.0:8000 --workers 2 --access-logfile - --error-logfile -"]