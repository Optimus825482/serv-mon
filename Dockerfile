FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

EXPOSE 8000

# Docker socket'e erişim için container'ı şu şekilde çalıştır:
# docker run -v /var/run/docker.sock:/var/run/docker.sock -p 8000:8000 monitor-api
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
