# Build context: repository root (see docker-compose.yml)
FROM python:3.15-slim

COPY lib /opt/lib
RUN pip install --no-cache-dir /opt/lib

WORKDIR /app
COPY cloud ./cloud

EXPOSE 8443 8444
CMD ["python", "-m", "cloud"]
