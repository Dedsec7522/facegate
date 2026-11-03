FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
# OpenCV headless runtime deps
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
# opencv-python-headless avoids pulling X11 libraries into the image
RUN sed -i 's/^opencv-python<5/opencv-python-headless<5/' requirements.txt && pip install -r requirements.txt
COPY . .
RUN useradd -r -u 10001 facegate && chown -R facegate:facegate /app
USER facegate
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*", "--workers", "1"]
