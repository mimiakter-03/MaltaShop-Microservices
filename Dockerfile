FROM python:3.12-slim AS build
WORKDIR /app
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt
FROM python:3.12-slim
WORKDIR /app
RUN useradd --create-home --uid 10001 appuser && mkdir /data && chown appuser:appuser /data
COPY --from=build /wheels /wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt && rm -rf /wheels
COPY worker.py .
USER appuser
CMD ["python","worker.py"]
