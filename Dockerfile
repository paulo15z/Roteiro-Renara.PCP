FROM python:3.11-slim

# Evita prompts interativos durante apt
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Dependências do sistema (mínimas)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Instala dependências Python primeiro (camada cacheável)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o código
COPY app.py .
COPY templates/ templates/

# Diretórios de dados — serão montados como volume
# mas criamos aqui como fallback
RUN mkdir -p /data/outputs /data/uploads

# Usuário não-root por segurança
RUN useradd -r -u 1001 appuser && chown -R appuser /app /data
USER appuser

EXPOSE 5000

CMD ["python", "app.py"]
