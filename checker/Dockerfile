FROM python:3.11-slim

# системные зависимости для Chromium без ttf‑пакетов
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libx11-xcb1 libxcb1 libxcomposite1 libxcursor1 libxdamage1 libxext6 \
        libxi6 libxrandr2 libxrender1 libdbus-1-3 libxtst6 libnss3 libglib2.0-0 \
        libxshmfence1 libasound2 libatk1.0-0 libatk-bridge2.0-0 libdrm2 \
        libgbm1 libgtk-3-0 libpango-1.0-0 libcairo2 libexpat1 libuuid1 \
        libharfbuzz0b fonts-liberation fonts-unifont fonts-dejavu-core \
        wget ca-certificates && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# установим только браузер, без опции --with-deps
RUN playwright install chromium

WORKDIR /app
COPY . .

CMD ["python", "checker.py"]