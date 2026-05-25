# Use official lightweight Python image
FROM python:3.11-slim as builder

# Set build-time env variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies (needed for compiling certain native packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies in a virtual env
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Final runner stage
FROM python:3.11-slim

ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Copy virtual environment from builder stage
COPY --from=builder /opt/venv /opt/venv

# Copy bot application source code
COPY . .

# Create persistent storage mounts for SQLite bot.db and application logs
RUN mkdir -p /app/data
ENV DATABASE_PATH=/app/data/bot.db

# Add a non-privileged system user for secure container execution
RUN useradd -u 8888 appuser && chown -R appuser:appuser /app
USER appuser

# Define volume mapping for state retention
VOLUME ["/app/data"]

# Run the Telegram bot application
CMD ["python", "main.py"]
