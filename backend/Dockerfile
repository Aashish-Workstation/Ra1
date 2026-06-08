FROM docker.io/library/python:3.11-slim

WORKDIR /app

COPY . .

RUN pip install uv && uv pip install --system .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]