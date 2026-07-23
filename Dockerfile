FROM python:3.10-slim-bookworm

# Install system dependencies (with retries, minimal recommends)
RUN apt-get update -o Acquire::Retries=3 && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    ccache \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt requirements-ml.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Optional ML profile (trained field detectors): torch-cpu + ultralytics.
# Build with:  docker build --build-arg INSTALL_ML=true .
ARG INSTALL_ML=false
RUN if [ "$INSTALL_ML" = "true" ]; then         pip install --no-cache-dir -r requirements-ml.txt;     fi

# Copy application code
COPY . .

# Bake the OCR weights into the image.
#
# Without this the image ships no models at all: PaddleX downloads them on first
# request. Its default host (paddle-model-ecology.bj.bcebos.com) answers 403 from
# here, PaddleX reports "No available model hosting platforms detected", and the
# container crash-loops on boot — a rebuild that looks clean and produces a broken
# image. Pin the source to HuggingFace (reachable, verified) and pull the weights
# now, so a built image starts offline and identically on any machine.
#
# The warmup instantiates the app's own OCRService, so it downloads exactly the
# models the runtime asks for (PPOCR_LANG=multi coerces to 'en' on the v3 pipeline)
# rather than a set we guessed at and have to keep in sync.
ENV PADDLE_PDX_MODEL_SOURCE=huggingface
RUN python -c "from app.services.paddle_ocr import OCRService; OCRService()"

# Create necessary directories
RUN mkdir -p /app/logs

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Expose the port the app runs on
EXPOSE 8000

# Command to run the application (no reload in container)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]