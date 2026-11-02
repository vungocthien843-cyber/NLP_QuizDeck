FROM python:3.11-slim

# LibreOffice để đổi PPTX -> PDF; font Noto/DejaVu để render đúng chữ tiếng Việt
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-impress fonts-noto-core fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
COPY requirements/api.txt requirements/api.txt
RUN pip install --no-cache-dir -r requirements/api.txt

COPY app app
COPY config.yaml .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
