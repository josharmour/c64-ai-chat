FROM python:3.12-slim

# Scripts live in /app; working directory is /data (for log + saved config).
WORKDIR /app
COPY c64_ai_proxy.py c64_ai_proxy_headless.py /app/

RUN mkdir -p /data
WORKDIR /data

EXPOSE 6464

ENV PYTHONUNBUFFERED=1

CMD ["python3", "/app/c64_ai_proxy_headless.py"]
