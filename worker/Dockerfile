FROM python:3.11-slim
WORKDIR /app

# LibreOffice + UNO
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libreoffice-calc \
        libreoffice-script-provider-python \
    && rm -rf /var/lib/apt/lists/*

# PATH для UNO Python bridge
ENV PYTHONPATH="/usr/lib/libreoffice/program:${PYTHONPATH}"
ENV LD_LIBRARY_PATH="/usr/lib/libreoffice/program:${LD_LIBRARY_PATH}"

# Копируем startup-скрипт
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./src/

ENTRYPOINT ["/entrypoint.sh"]