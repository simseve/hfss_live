FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy only necessary modules from parent directory
COPY config.py .
COPY database/ ./database/
COPY redis_queue_system/ ./redis_queue_system/
COPY tcp_server/ ./tcp_server/

# Set Python path to include app directory
ENV PYTHONPATH=/app

# Create logs directory
RUN mkdir -p /app/logs

# Run as non-root user
RUN useradd -m -u 1000 gpsserver && chown -R gpsserver:gpsserver /app
USER gpsserver

# Expose GPS TCP port (will be set via environment variable)
EXPOSE ${GPS_TCP_PORT:-9999}

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import socket; s=socket.socket(); s.settimeout(5); s.connect(('localhost', ${GPS_TCP_PORT:-9999})); s.close()"

# Run the standalone server
CMD ["python", "-u", "tcp_server/standalone_server.py"]