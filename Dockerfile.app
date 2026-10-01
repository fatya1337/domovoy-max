FROM python:3.12.12-slim
WORKDIR /app
COPY miniapp.py max_auth.py bot.py connected_bot.py incidents.py worker.py register_webhook.py backup.py /app/
COPY web /app/web
COPY certs /app/certs
RUN useradd --uid 10001 --create-home bot && mkdir /app/data /backups && chown bot:bot /app/data /backups
USER bot
ENV PYTHONUNBUFFERED=1
CMD ["python", "miniapp.py"]
