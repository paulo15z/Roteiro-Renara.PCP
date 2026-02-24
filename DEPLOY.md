# Roteiro PCP — Implantação no Proxmox

## 1. Criar o CT no Proxmox

No shell do **nó Proxmox** (não dentro de um CT):

```bash
# Baixa template Ubuntu 22.04 se não tiver
pveam update
pveam download local ubuntu-22.04-standard_22.04-1_amd64.tar.zst

# Cria o CT
pct create 200 local:vztmpl/ubuntu-22.04-standard_22.04-1_amd64.tar.zst \
  --hostname roteiro-pcp \
  --memory 1024 \
  --cores 2 \
  --rootfs local-lvm:8 \
  --net0 name=eth0,bridge=vmbr0,ip=dhcp \
  --unprivileged 1 \
  --features nesting=1

# nesting=1 é obrigatório para Docker dentro de LXC

pct start 200
pct enter 200
```

---

## 2. Instalar Docker dentro do CT

```bash
apt update && apt install -y curl git

# Instala Docker via script oficial
curl -fsSL https://get.docker.com | sh

# Verifica
docker --version
docker compose version
```

---

## 3. Criar estrutura de diretórios

```bash
mkdir -p /opt/roteiro-pcp/data/outputs
mkdir -p /opt/roteiro-pcp/data/uploads
```

---

## 4. Criar repositório no GitHub e fazer push do código

No seu PC (onde está o projeto):

```bash
cd roteiro_pcp_local

# Inicializa o repositório local
git init
git add .
git commit -m "primeiro commit — Roteiro PCP"

# Cria o repo no GitHub (precisa do GitHub CLI instalado)
# OU crie manualmente em github.com e use:
git remote add origin https://github.com/SEU_USUARIO/roteiro-pcp.git
git branch -M main
git push -u origin main
```

---

## 5. Clonar no servidor e fazer primeiro deploy

De volta no CT (via `pct enter 200` ou SSH):

```bash
cd /opt/roteiro-pcp
git clone https://github.com/SEU_USUARIO/roteiro-pcp.git .

# Dá permissão de execução ao script de deploy
chmod +x deploy.sh

# Cria a pasta de dados persistentes
mkdir -p data/outputs data/uploads

# Primeiro build e start
docker compose up -d --build

# Verifica que está rodando
docker compose ps
docker compose logs -f
```

---

## 6. Acessar

```bash
# Descobre o IP do CT
ip addr show eth0 | grep 'inet '
```

Acesse no navegador: **http://\<IP_DO_CT\>:5000**

---

## 7. Atualizar o código no futuro

No seu PC, faça as alterações e:

```bash
git add .
git commit -m "descrição da mudança"
git push
```

No servidor (CT):

```bash
cd /opt/roteiro-pcp
./deploy.sh
```

Ou manualmente:

```bash
git pull
docker compose up -d --build
```

---

## Estrutura final no servidor

```
/opt/roteiro-pcp/
├── app.py
├── Dockerfile
├── docker-compose.yml
├── deploy.sh
├── requirements.txt
├── templates/
│   └── index.html
├── template_dinabox_pcp.txt
├── .gitignore
└── data/                     ← volume persistente (NÃO vai pro GitHub)
    ├── historico.db          ← criado automaticamente
    └── outputs/              ← XLSXs gerados
```

---

## Comandos úteis no dia a dia

```bash
# Ver logs em tempo real
docker compose logs -f

# Reiniciar sem rebuild
docker compose restart

# Parar
docker compose down

# Ver uso de disco dos outputs
du -sh /opt/roteiro-pcp/data/outputs/

# Backup dos dados
tar -czf backup-pcp-$(date +%Y%m%d).tar.gz /opt/roteiro-pcp/data/
```

---

## Sobre o deploy automático (GitHub Actions)

Quando quiser evoluir para deploy automático a cada `git push`,
é só adicionar o arquivo `.github/workflows/deploy.yml` com uma
action que faz SSH no servidor e roda `./deploy.sh`.
Avise que preparo esse arquivo quando chegar a hora.
