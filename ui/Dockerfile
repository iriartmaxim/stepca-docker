FROM python:3.12-slim
RUN pip install --no-cache-dir \
      fastapi==0.115.* "uvicorn[standard]==0.32.*" httpx==0.27.* \
      docker==7.1.* cryptography==43.*
WORKDIR /app
COPY app.py /app/app.py
COPY static /app/static
EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
