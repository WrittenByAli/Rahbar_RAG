FROM python:3.12-slim

# Create a non-root system user
RUN groupadd --system app && useradd --system --gid app --no-create-home app

WORKDIR /app

# Install dependencies before copying source so this layer is cached
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY app/ app/

USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
