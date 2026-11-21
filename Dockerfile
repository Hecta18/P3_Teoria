FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mt_sim.py .
COPY examples ./examples

ENTRYPOINT ["python", "mt_sim.py"]
CMD ["--help"]
