# One service: the API, and the website it serves from web/dist.
# The site is built on the host first (npm --prefix web run build) because its
# Google Maps browser key is compiled into the bundle at build time. See
# docs/DEPLOYMENT.md, "Deploying the hackathon demo".
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt

COPY api/ api/
COPY ingestion/ ingestion/
COPY ml/ ml/
COPY spec/ spec/
COPY infra/tenants.yaml infra/tenants.yaml
COPY web/dist/ web/dist/

# Cloud Run supplies PORT. No .env is copied (see .dockerignore): configuration and
# secrets come from the service definition and Secret Manager.
CMD exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8080}
