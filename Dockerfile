FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render.com sets PORT env variable
ENV PORT=8080
EXPOSE $PORT

CMD gunicorn --bind 0.0.0.0:$PORT --timeout 480 --workers 2 main:app
