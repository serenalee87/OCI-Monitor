FROM python:3.11-slim

WORKDIR /app

# Use Alibaba pip mirror for faster downloads in China
ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_TRUSTED_HOST=mirrors.aliyun.com

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/

# Create data directory for SQLite
RUN mkdir -p /app/data /app/config

# Expose port
EXPOSE 8199

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8199"]
