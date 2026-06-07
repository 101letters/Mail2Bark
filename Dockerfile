FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mail_bark_forwarder ./mail_bark_forwarder
COPY README.md config.example.yaml ./

RUN mkdir -p /data
VOLUME ["/data"]

CMD ["python", "-m", "mail_bark_forwarder", "--config", "/app/config.yaml"]
