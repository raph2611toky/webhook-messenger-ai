FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/logs \
    && touch /app/logs/endpoints.log \
    && chmod -R 777 /app/logs

ENV LOG_FILE=/app/logs/endpoints.log
ENV PORT=5487

EXPOSE 5487

CMD ["sh", "-c", "gunicorn -b 0.0.0.0:${PORT} --workers 2 --threads 4 --timeout 120 --access-logfile ${LOG_FILE} --error-logfile ${LOG_FILE} --capture-output --log-level info app:app"]