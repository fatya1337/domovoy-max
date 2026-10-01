FROM python:3.12.12-slim
WORKDIR /app
COPY bot.py connected_bot.py incidents.py miniapp.py max_auth.py worker.py /app/
COPY certs /app/certs
RUN useradd --uid 10001 --create-home bot && mkdir /app/data && chown bot:bot /app/data
USER bot
ENV PYTHONUNBUFFERED=1
CMD ["python", "bot.py", "poll"]
