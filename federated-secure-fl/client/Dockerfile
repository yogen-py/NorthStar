FROM python:3.10-slim

WORKDIR /app

COPY client/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY client/ .
COPY shared/ ./shared/

CMD ["python", "client.py"]
