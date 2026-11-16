FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    CODEMIND_STORAGE_DIR=/var/lib/codemind/repositories \
    VECTOR_DB_DIR=/var/lib/codemind/vectors \
    HF_HOME=/home/codemind/.cache/huggingface

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

COPY backend/app ./app

RUN groupadd --system codemind \
    && useradd --system --gid codemind --home-dir /home/codemind --create-home codemind \
    && mkdir -p /var/lib/codemind/repositories \
        /var/lib/codemind/vectors \
        /home/codemind/.cache/huggingface \
    && chown -R codemind:codemind /var/lib/codemind /home/codemind

USER codemind:codemind

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/health', timeout=3).read()"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
