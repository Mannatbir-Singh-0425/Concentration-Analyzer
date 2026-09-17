# Production Dockerfile for Concentration Analyzer
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=10000 \
    DATABASE_PATH=database.db \
    MODEL_DIR=model

# Install Linux system dependencies for OpenCV and image operations
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Create storage directories
RUN mkdir -p /app/model /data/model && chmod -R 777 /app /data

# Expose Render standard port
EXPOSE 10000

# Start production WSGI server: pre-initialize DB once in single process, then boot gunicorn with preload
CMD ["sh", "-c", "python -c 'from app import init_db; init_db()' && gunicorn --bind 0.0.0.0:${PORT:-10000} --workers 2 --threads 4 --preload --timeout 120 app:app"]
