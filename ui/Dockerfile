FROM python:3.12-slim
# CLI step para emisión segura vía la API autenticada (sin socket de Docker)
COPY --from=smallstep/step-ca:0.28.3 /usr/local/bin/step /usr/local/bin/step
RUN pip install --no-cache-dir \
      fastapi==0.115.* "uvicorn[standard]==0.32.*" httpx==0.27.* cryptography==43.*
WORKDIR /app
COPY app.py /app/app.py
COPY static /app/static
EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
