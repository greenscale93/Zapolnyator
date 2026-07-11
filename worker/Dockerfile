FROM python:3.11-slim
WORKDIR /app

# LibreOffice + UNO Python bridge
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libreoffice-calc \
        libreoffice-script-provider-python \
    && rm -rf /var/lib/apt/lists/*

# Копируем startup-скрипт
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./src/

ENV PYTHONPATH="/usr/lib/libreoffice/program:${PYTHONPATH}"
ENTRYPOINT ["/entrypoint.sh"]