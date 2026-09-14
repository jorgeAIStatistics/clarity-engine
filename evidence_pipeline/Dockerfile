FROM python:3.12-slim
WORKDIR /app
COPY evidence_pipeline/requirements.lock.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
RUN useradd --create-home --uid 10001 pipeline && mkdir /state && chown pipeline:pipeline /state
COPY evidence_pipeline /app/evidence_pipeline
USER pipeline
ENV PYTHONUNBUFFERED=1 PIPELINE_STATE_PATH=/state/pico.sqlite3
CMD ["python", "-m", "evidence_pipeline.worker"]
