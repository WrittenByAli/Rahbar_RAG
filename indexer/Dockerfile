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

# ENTRYPOINT, not CMD: indexer-job.yaml sets `args: ["--dummy"]`. Kubernetes
# `args` replaces CMD but APPENDS to ENTRYPOINT - with CMD here, that args
# field previously replaced the whole command, so the container tried to
# exec the literal string "--dummy" and failed with "executable file not
# found in $PATH". ENTRYPOINT makes --dummy arrive as a real argument.
ENTRYPOINT ["python", "-m", "pipeline.run"]
