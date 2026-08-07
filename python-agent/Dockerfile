FROM python:3.11-slim

WORKDIR /app

# PDF layout extraction and Chinese/English OCR runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 poppler-utils tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-eng \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

COPY . .

EXPOSE 8001

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "from urllib.request import urlopen; urlopen('http://localhost:8001/health/ready')" || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
