FROM apache/superset:6.1.0
USER root
# Trino driver (ES via Trino) + Postgres driver for the metadata DB
RUN . /app/.venv/bin/activate && (uv pip install --no-cache trino psycopg2-binary || pip install --no-cache-dir trino psycopg2-binary)
USER superset
