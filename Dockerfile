FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Expose port (Google Cloud Run injects $PORT, defaults to 8080 or 8000)
ENV PORT=8000
EXPOSE 8000

# Start command
CMD ["python", "run.py"]
