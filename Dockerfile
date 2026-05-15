# Vortex Bot — Docker image
# Python 3.11 + ffmpeg + project dependencies

FROM python:3.11-slim

# System packages: ffmpeg (media conversion), postgresql-client (pg_dump/pg_restore for backup/restore)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# App directory
WORKDIR /app

# Install Python dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Create volume directories
RUN mkdir -p /app/downloads /app/cache /app/cookies /app/backups

# Smoke-check entrypoint (no paid APIs, no large downloads)
# For the actual bot, override CMD: python bot.py
CMD ["python", "-c", "print('Vortex container ready. Run: python bot.py')"]
