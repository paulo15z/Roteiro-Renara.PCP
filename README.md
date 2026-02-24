# Roteiro PCP — Setup local (VS Code)

## 1. Pré-requisito
Python 3.10+ instalado. Confirme com:
```
python --version
```

## 2. Abrir no VS Code
Extraia o ZIP e abra a pasta no VS Code:
`File → Open Folder → roteiro_pcp_local`

## 3. Criar ambiente virtual e instalar dependências

No terminal integrado do VS Code (Ctrl + `):

```bash
# Windows
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 4. Rodar

Opção A — F5 no VS Code (debug completo com breakpoints)
Opção B — terminal: python app.py

Acesse: http://localhost:5000

## 5. Selecionar interpretador do venv
Ctrl+Shift+P → "Python: Select Interpreter" → escolha o que contém "venv"

## Para o Proxmox depois
Só mude a última linha do app.py:
  debug=True  →  debug=False
  host='127.0.0.1'  →  host='0.0.0.0'


## Realease
Em produção 24/02/26 - 15:38 