# Build context: repository root (see docker-compose.yml)
FROM python:3.13-slim

COPY lib /opt/lib
RUN pip install --no-cache-dir /opt/lib

WORKDIR /app
COPY gateway ./gateway

EXPOSE 8765
CMD ["python", "-m", "gateway"]
