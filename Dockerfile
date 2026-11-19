FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    GOOGLE_CLOUD_PROJECT=your-gcp-project-id \
    GOOGLE_CLOUD_LOCATION=global \
    GCS_BUCKET=your-gcs-bucket-name

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY portal/ ./portal/
COPY templates/ ./templates/
COPY static/ ./static/

EXPOSE 8080

CMD ["uvicorn", "portal.app:app", "--host", "0.0.0.0", "--port", "8080"]
