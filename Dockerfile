FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY stale_branch_mr_handler.py .
COPY webui/ ./webui/

# Create directory for database persistence
RUN mkdir -p /app/data

# Expose WebUI port
EXPOSE 5000

# Environment variables for WebUI
ENV WEBUI_HOST=0.0.0.0
ENV WEBUI_PORT=5000
ENV CONFIG_PATH=/app/config.yaml

# Default command (can be overridden)
# Use --webui flag to run the WebUI server instead of the CLI
CMD ["python", "stale_branch_mr_handler.py", "-c", "/app/config.yaml"]
