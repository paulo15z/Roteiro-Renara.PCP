#!/bin/bash
# deploy.sh — atualiza e reinicia o Roteiro PCP no servidor
# Uso: ./deploy.sh
# Ou com branch específico: ./deploy.sh main

set -e

BRANCH=${1:-main}
APP_DIR="/opt/roteiro-pcp"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Deploy Roteiro PCP  |  branch: $BRANCH"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

cd "$APP_DIR"

echo "► Buscando atualizações do GitHub..."
git fetch origin
git checkout "$BRANCH"
git pull origin "$BRANCH"

echo "► Rebuild da imagem Docker..."
docker compose build --no-cache

echo "► Reiniciando container..."
docker compose up -d

echo "► Aguardando healthcheck..."
sleep 5
docker compose ps

echo ""
echo "✅ Deploy concluído!"
echo "   Acesse: http://$(hostname -I | awk '{print $1}'):5000"
