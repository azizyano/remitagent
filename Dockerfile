# Use official Python 3.11 image (slim for smaller size)
FROM python:3.11-slim-bookworm

# Set working directory
WORKDIR /app

# Install system dependencies for building packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip and install build tools first
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Copy requirements first (for better Docker caching)
COPY requirements.txt .

# Install Python dependencies
# Install numpy first to help with pandas build
RUN pip install --no-cache-dir numpy==1.26.4 && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Create data directory
RUN mkdir -p data

# Expose port
EXPOSE 8000

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=8000
ENV PYTHONDONTWRITEBYTECODE=1

# Run the agent
CMD ["python", "main.py", "--mode", "monitor"]
