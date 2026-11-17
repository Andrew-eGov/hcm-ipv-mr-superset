FROM apache/superset:6.1.0
USER root
# Trino driver (ES via Trino) + Postgres driver for the metadata DB
RUN . /app/.venv/bin/activate && (uv pip install --no-cache trino psycopg2-binary || pip install --no-cache-dir trino psycopg2-binary)
# Mobile: Superset's page template has no viewport tag, so phones render it as a ~980px desktop page.
# Add one so the dashboard's phone CSS (tools/build_superset.py, CSS) applies at real device width.
RUN sed -i 's#{% block head_meta %}#{% block head_meta %}\n      <meta name="viewport" content="width=device-width, initial-scale=1">#' \
      /app/superset/templates/superset/spa.html \
 && grep -q 'name="viewport"' /app/superset/templates/superset/spa.html
USER superset
