FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir opencv-python scipy stegano numpy

WORKDIR /workspace

EXPOSE 8501

CMD ["python", "-m", "http.server", "8501", "--bind", "0.0.0.0"]
