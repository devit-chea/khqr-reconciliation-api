#!/bin/sh
set -e

echo "Waiting for PostgreSQL..."
until python -c "
import os, psycopg2, sys
try:
    psycopg2.connect(os.environ['DATABASE_URL'])
    sys.exit(0)
except Exception:
    sys.exit(1)
"; do
  sleep 1
done
echo "PostgreSQL is up."

python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py setup_superuser

exec "$@"
