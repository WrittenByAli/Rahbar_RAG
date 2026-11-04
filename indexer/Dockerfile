FROM python:3.12-slim

# System packages needed for PDF extraction and OCR
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root system user
RUN groupadd --system app && useradd --system --gid app --no-create-home app

WORKDIR /app

# Install dependencies before copying source so this layer is cached
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy pipeline source
COPY pipeline/ pipeline/

USER app

CMD ["python", "-m", "pipeline.run"]
