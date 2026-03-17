# Use official Python 3.11 image
FROM python:3.11-slim-bookworm

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Copy requirements first (better Docker caching)
COPY requirements.txt .

# Install dependencies (numpy first to help pandas)
RUN pip install --no-cache-dir numpy==1.26.4 && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directory
RUN mkdir -p data

# Expose port
EXPOSE 8000

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=8000
ENV PYTHONDONTWRITEBYTECODE=1

# Use dashboard mode - runs both API server (for health checks) and agent monitoring
CMD ["python", "main.py", "--mode", "dashboard", "--port", "8000"]
