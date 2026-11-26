FROM python:3.11-slim

# LibreOffice để đổi PPTX -> PDF; font Noto/DejaVu để render đúng chữ tiếng Việt
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-impress fonts-noto-core fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# Mặc định PyTorch bản CPU. Máy có GPU NVIDIA: docker-compose.gpu.yml đặt TORCH_INDEX=cu121 (bản CUDA)
ARG TORCH_INDEX=cpu
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/${TORCH_INDEX}
COPY requirements/api.txt requirements/api.txt
RUN pip install --no-cache-dir -r requirements/api.txt

COPY app app
COPY config.yaml .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
