#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Script de teste para validar a lógica de roteamento"""

import pandas as pd
from io import StringIO
import sys

# Colunas de borda — nomes exatos do Dinabox
BORDA_COLS = ['BORDA_FACE_FRENTE', 'BORDA_FACE_TRASEIRA', 'BORDA_FACE_LE', 'BORDA_FACE_LD']

def calcular_roteiro(row):
    """
    Organiza o fluxo de cada peça pelos setores da marcenaria:
    COR → BOR → USI/FUR → DUP → MCX → MPE → MAR → PIN/TAP/LED → CQL → EXP
    
    Serviços especiais detectados por tags na coluna OBSERVAÇÃO: #pin, #tap, #led
    """
    
    # Extração e normalização de dados
    local      = str(row.get('LOCAL', '')).strip().lower()
    desc       = str(row.get('DESCRIÇÃO DA PEÇA', '')).strip().lower()
    duplagem   = str(row.get('DUPLAGEM', '')).strip().lower()
    furo       = str(row.get('FURO', '')).strip().lower()
    obs        = str(row.get('OBSERVAÇÃO', '')).strip().lower()
    
    # Detectar características
    tem_borda    = any(str(row.get(c, '')).strip() not in ('', 'nan') for c in BORDA_COLS)
    eh_perfil    = 'perfil db' in desc
    tem_furo     = furo not in ('', 'nan', 'none')
    tem_duplagem = duplagem not in ('', 'nan', 'none')
    
    # Detectar tipo de peça
    tem_puxador  = 'puxador' in desc or 'tampa' in desc
    eh_porta     = 'porta' in local or 'porta' in desc
    eh_gaveta    = 'gaveta' in desc or 'gaveteiro' in desc
    eh_caixa     = 'caixa' in local
    eh_frontal   = 'frontal' in local or 'frontal' in desc
    eh_tamponamento = 'tamponamento' in local
    
    # Detectar serviços especiais por OBS - apenas tags específicas
    # Procura por tags: #pin, #tap, #led
    tem_pintura  = '#pin' in obs
    tem_tapecar  = '#tap' in obs
    tem_eletrica = '#led' in obs
    
    rota = ['COR']  # Todas as peças começam no corte
    
    # ─── ETAPA 1: BORDA ───────────────────────────────────────────────────────
    if tem_borda:
        rota.append('BOR')
    
    # ─── ETAPA 2: USINAGEM E FURAÇÃO ──────────────────────────────────────────
    if tem_furo:
        rota.append('USI')
        rota.append('FUR')
    
    # ─── ETAPA 3: DUPLAGEM ────────────────────────────────────────────────────
    if tem_duplagem:
        rota.append('DUP')
    
    # ─── ETAPA 4: MONTAGEM - Gavetas/Caixas ───────────────────────────────────
    if eh_gaveta or eh_caixa:
        rota.append('MCX')
    
    # ─── ETAPA 5: MONTAGEM - Portas/Frontais ──────────────────────────────────
    elif tem_puxador or eh_porta or eh_frontal:
        rota.append('MPE')
        rota.append('MAR')  # Após MPE, vai para marceneiro
    
    # ─── ETAPA 6: MARCENARIA - Tamponamentos e itens especiais ────────────────
    # Tamponamentos que NÃO são gavetas (como contra-frente, lateral, arremate)
    elif eh_tamponamento and not eh_gaveta:
        rota.append('MAR')
    
    # ─── ETAPA 7: SERVIÇOS ESPECIAIS ──────────────────────────────────────────
    if tem_pintura:
        rota.append('PIN')
    if tem_tapecar:
        rota.append('TAP')
    if tem_eletrica:
        rota.append('MEL')
    
    # ─── ETAPA 8: CONTROLE DE QUALIDADE (OBRIGATÓRIO) ────────────────────────
    rota.append('CQL')
    
    # ─── ETAPA 9: EXPEDIÇÃO (OBRIGATÓRIO) ──────────────────────────────────────
    rota.append('EXP')
    
    return ' > '.join(rota)

# Ler arquivo
arquivo = r'c:\Roteiro-Renara.PCP\EXEMPLOS DE INPUTS\0606504283 - COZINHA - 784 - DENISE NEVES - 25-02-2026.csv'
try:
    raw = open(arquivo, 'rb').read()
    text = None
    for enc in ('utf-8-sig', 'utf-8', 'cp1252', 'latin-1'):
        try: text = raw.decode(enc); break
        except: continue
    
    linhas = text.splitlines()
    corpo = []
    em_lista = False
    for l in linhas:
        if '[LISTA]' in l:    em_lista = True;  continue
        if '[/LISTA]' in l:   em_lista = False; continue
        if (em_lista or not l.startswith('[')) and l.strip():
            corpo.append(l.rstrip(';'))
    
    df = pd.read_csv(StringIO('\n'.join(corpo)), sep=';', dtype=str).fillna('')
    
    # Remove coluna vazia
    df.columns = [c.strip() for c in df.columns]
    df = df[[c for c in df.columns if c]]
    
    # Remove linha de rodapé
    if 'NOME DO CLIENTE' in df.columns:
        df = df[~df['NOME DO CLIENTE'].str.strip().isin(['RODAPÉ', ''])]
    
    # Calcula roteiro
    df['ROTEIRO'] = df.apply(calcular_roteiro, axis=1)
    
    # Mostra alguns exemplos
    cols_mostrar = ['DESCRIÇÃO DA PEÇA', 'LOCAL', 'FURO', 'DUPLAGEM', 'ROTEIRO']
    print("\n=== PRIMEIRAS 15 PEÇAS ===\n")
    for idx, row in df.head(15).iterrows():
        print(f"ID {row['ID DA PEÇA']}: {row['DESCRIÇÃO DA PEÇA']:<30} | LOCAL: {row['LOCAL']:<20} | Rota: {row['ROTEIRO']}")
    
    # Resumo
    print("\n=== RESUMO DE ROTAS ===\n")
    print(df['ROTEIRO'].value_counts())
    
except Exception as e:
    import traceback
    print(f"ERRO: {e}")
    print(traceback.format_exc())
