FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY stale_branch_mr_handler.py .

# Create directory for database persistence
RUN mkdir -p /app/data

# Default command
CMD ["python", "stale_branch_mr_handler.py", "-c", "/app/config.yaml"]
