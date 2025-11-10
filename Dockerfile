FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /usr/src/app

# Dependencias Python
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Playwright + dependencias del sistema para Chromium
RUN python -m playwright install chromium && \
    python -m playwright install-deps

# Código fuente
COPY . .

CMD ["python", "main.py"]

