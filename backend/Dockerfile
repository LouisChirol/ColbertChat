# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files (uv.lock pins exact versions so rebuilds are
# reproducible instead of re-resolving loose ">=" constraints every time)
COPY pyproject.toml uv.lock ./

# Install uv for faster dependency management
RUN pip install uv

# Install exactly the versions pinned in uv.lock, without re-resolving
RUN uv export --frozen --no-hashes --no-emit-project -o requirements.lock.txt \
    && uv pip install --system --no-cache -r requirements.lock.txt

# Copy application code
COPY app/ ./app/
COPY scripts/ ./scripts/

# Register the local package itself without touching already-installed deps
RUN uv pip install --system --no-cache --no-deps -e .

# Create logs directory
RUN mkdir -p logs

# Expose port
EXPOSE 8000

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Run the application with Gunicorn + Uvicorn workers for resilience under load
CMD ["gunicorn", "app.api.main:app", "-k", "uvicorn.workers.UvicornWorker", "-w", "2", "-b", "0.0.0.0:8000", "--timeout", "180"]