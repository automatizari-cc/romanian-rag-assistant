FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/data \
    HUGGINGFACE_HUB_CACHE=/data \
    TRANSFORMERS_CACHE=/data \
    SENTENCE_TRANSFORMERS_HOME=/data

WORKDIR /app

# Pin torch to the last release verified to run on pre-AVX2 x86_64 (silver = Westmere X5650).
# Newer wheels ship AVX2-only kernels in some ops and SIGILL on Westmere.
COPY requirements.txt .
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu \
        torch==2.2.2 \
 && pip install --no-cache-dir -r requirements.txt

RUN groupadd --system --gid 10001 app \
 && useradd  --system --uid 10001 --gid app --home /app --shell /usr/sbin/nologin app \
 && mkdir -p /data \
 && chown -R app:app /app /data

COPY --chown=app:app app.py ./

USER app

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=600s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1/health').status==200 else 1)"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "80", "--workers", "1"]
