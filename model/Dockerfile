FROM python:3.10-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir fastapi uvicorn prometheus-client confluent-kafka elasticsearch
COPY . .
CMD ["uvicorn", "serving.main:app", "--host", "0.0.0.0", "--port", "8000"]
