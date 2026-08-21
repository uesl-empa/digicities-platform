# Python 3.11 — Python 3.9 hit EOL Oct 2025. All deps (streamlit, pandas,
# numpy, rdflib, fsspec, webdav4, etc.) support 3.11; verified in the v0.3
# end-to-end test.
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy the correct requirements.txt file from your repo
COPY  requirements.txt /app/requirements.txt
# REST API deps (fastapi/uvicorn) — the same image runs both the Streamlit
# app and the `api` compose service, so bake both requirement sets in.
COPY  apps/api/requirements.txt /app/api-requirements.txt

# Install Python dependencies
RUN pip install --upgrade pip && pip install -r requirements.txt -r api-requirements.txt

# Now copy all your app code
COPY . /app

# Make the repo root importable so `from backend.* import …` works when
# Streamlit runs apps/streamlit/app.py (its sys.path only starts at
# apps/streamlit/ by default).
ENV PYTHONPATH=/app

# Expose Streamlit default port
EXPOSE 8501

# Healthcheck
HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health || exit 1

# Run your Streamlit app
ENTRYPOINT ["streamlit", "run", "apps/streamlit/app.py", "--server.port=8501", "--server.address=0.0.0.0"]
