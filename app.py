import os
import sqlite3
import uuid
from datetime import datetime
from flask import Flask, request, jsonify, send_file, render_template, g
import pandas as pd
from io import BytesIO
import xlwt

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# Configuração de pastas
DATA_DIR    = os.environ.get('DATA_DIR', os.path.dirname(os.path.abspath(__file__)))
DB_PATH     = os.path.join(DATA_DIR, 'historico.db')
OUTPUTS_DIR = os.path.join(DATA_DIR, 'outputs')
os.makedirs(OUTPUTS_DIR, exist_ok=True)

# ====================== BANCO DE DADOS ======================
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH, check_same_thread=False)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db: db.close()

def init_db():
    with app.app_context():
        db = get_db()
        db.execute('''CREATE TABLE IF NOT EXISTS pedidos (
            id TEXT PRIMARY KEY,
            nome TEXT,
            data TEXT,
            total_pecas INTEGER,
            arquivo_out TEXT
        )''')
        db.commit()

# ====================== CONSOLIDAÇÃO DE RIPAS ======================
BORDA_COLS = ['BORDA_FACE_FRENTE', 'BORDA_FACE_TRASEIRA', 'BORDA_FACE_LE', 'BORDA_FACE_LD']

# ====================== CONSOLIDAÇÃO DE RIPAS (UMA POR TAMANHO) ======================
def consolidar_ripas(df):
    """
    Consolida ripas em painéis separados por tamanho de largura.
    Cada painel tem sua própria linha no roteiro com OBS curta e clara.
    """
    mask_ripa = (
        df['DESCRIÇÃO DA PEÇA'].str.upper().str.contains('RIPA', na=False) |
        df.get('OBSERVAÇÃO', pd.Series(dtype=str)).str.lower().str.contains('_ripa_', na=False) |
        df.get('OBS', pd.Series(dtype=str)).str.lower().str.contains('_ripa_', na=False)
    )

    df_ripas = df[mask_ripa].copy()
    df_resto = df[~mask_ripa].copy()

    if df_ripas.empty:
        return df

    ESPESSURA_SERRA = 4.0
    MARGEM_REFILO = 20.0

    def to_float(val):
        try:
            return float(str(val).replace(',', '.'))
        except:
            return 0.0

    df_ripas['LARGURA_NUM'] = df_ripas['LARGURA DA PEÇA'].apply(to_float)
    df_ripas['QTD_NUM'] = df_ripas['QUANTIDADE'].apply(to_float)

    novos_paineis = []

    # Agrupamento por material + espessura + altura + local + LARGURA (o mais importante)
    grupos = df_ripas.groupby(['MATERIAL DA PEÇA', 'ESPESSURA', 'ALTURA DA PEÇA', 'LOCAL', 'LARGURA_NUM'])

    for name, group in grupos:
        material, espessura, altura, local, largura_ripa = name

        total_unidades = int(group['QTD_NUM'].sum())
        largura_util = largura_ripa * total_unidades
        largura_painel = largura_util + (total_unidades * ESPESSURA_SERRA) + MARGEM_REFILO

        # Cria o painel
        nova_peca = group.iloc[0].copy()
        nova_peca['DESCRIÇÃO DA PEÇA'] = f"PAINEL PARA RIPAS ({total_unidades} un)"
        nova_peca['LARGURA DA PEÇA'] = str(round(largura_painel, 1)).replace('.', ',')
        nova_peca['QUANTIDADE'] = "1"

        # OBS curta e clara
        nova_peca['OBSERVAÇÃO'] = f"CORTAR MANUALMENTE NA ESQUADREJADEIRA — {total_unidades}×{int(largura_ripa)}mm"

        # Zera bordas (é chapa bruta)
        for col in BORDA_COLS:
            if col in nova_peca:
                nova_peca[col] = ""

        novos_paineis.append(nova_peca)

    df_paineis = pd.DataFrame(novos_paineis)
    return pd.concat([df_resto, df_paineis], ignore_index=True)


# ====================== ROTEIRO ======================
def calcular_roteiro(row):
    desc = str(row.get('DESCRIÇÃO DA PEÇA', '')).strip().lower()
    obs  = (str(row.get('OBSERVAÇÃO', '')) + ' ' + str(row.get('OBS', ''))).strip().lower()

    if 'painel para ripas' in desc:
        return 'COR > MAR > CQL > EXP'

    # ... (todo o resto da função calcular_roteiro que você já tinha - mantido igual)
    local      = str(row.get('LOCAL', '')).strip().lower()
    duplagem   = str(row.get('DUPLAGEM', '')).strip().lower()
    furo       = str(row.get('FURO', '')).strip().lower()

    tem_borda    = any(str(row.get(c, '')).strip() not in ('', 'nan') for c in BORDA_COLS)
    tem_furo     = furo not in ('', 'nan', 'none')
    tem_duplagem = duplagem not in ('', 'nan', 'none')

    tem_puxador  = 'puxador' in desc or 'tampa' in desc
    eh_porta     = 'porta' in local or 'porta' in desc
    eh_gaveta    = 'gaveta' in desc or 'gaveteiro' in desc or 'gaveta' in local
    eh_caixa     = 'caixa' in local
    eh_frontal   = 'frontal' in local or 'frontal' in desc
    eh_tamponamento = 'tamponamento' in local
    eh_painel    = '_painel_' in obs

    tem_pintura  = '_pin_' in obs
    tem_tapecar  = '_tap_' in obs
    tem_eletrica = '_led_' in obs
    tem_curvo    = '_curvo_' in obs

    rota = ['COR']

    if tem_borda:
        rota.append('BOR')
    if tem_furo:
        rota.append('USI')
        rota.append('FUR')
    if tem_duplagem:
        rota.append('DUP')
    if (eh_gaveta or eh_caixa) and not eh_painel:
        rota.append('MCX')
    elif tem_puxador or eh_porta or eh_frontal:
        rota.append('MPE')
        rota.append('MAR')
    if eh_painel or (eh_tamponamento and not eh_gaveta):
        rota.append('MAR')

    if tem_pintura: rota.append('PIN')
    if tem_tapecar: rota.append('TAP')
    if tem_eletrica: rota.append('MEL')
    if tem_curvo: rota.append('XMAR')

    rota.extend(['CQL', 'EXP'])
    return ' > '.join(rota)


# ====================== GERAÇÃO XLS ======================
def gerar_xls(df):
    wb = xlwt.Workbook(encoding='utf-8')
    ws = wb.add_sheet('Roteiro de Pecas')

    # Estilos (mantidos iguais)
    st_header = xlwt.easyxf('font: bold true, colour white, height 200; pattern: pattern solid, fore_colour dark_blue; alignment: horiz centre, vert centre, wrap true; borders: left thin, right thin, top thin, bottom thin;')
    st_header_rot = xlwt.easyxf('font: bold true, colour white, height 200; pattern: pattern solid, fore_colour dark_yellow; alignment: horiz centre, vert centre; borders: left thin, right thin, top thin, bottom thin;')
    st_data = xlwt.easyxf('font: height 180; alignment: horiz centre, vert centre; borders: left thin, right thin, top thin, bottom thin;')
    st_data_alt = xlwt.easyxf('font: height 180; pattern: pattern solid, fore_colour ice_blue; alignment: horiz centre, vert centre; borders: left thin, right thin, top thin, bottom thin;')
    st_rot = xlwt.easyxf('font: bold true, height 180; pattern: pattern solid, fore_colour light_yellow; alignment: horiz centre, vert centre; borders: left thin, right thin, top thin, bottom thin;')

    cols = list(df.columns)
    ws.row(0).height = 600

    for ci, col in enumerate(cols):
        st = st_header_rot if col == 'ROTEIRO' else st_header
        ws.write(0, ci, col, st)
        ws.col(ci).width = 6000 if col == 'ROTEIRO' else 4000

    for ri, (_, row) in enumerate(df.iterrows(), 1):
        st_base = st_data_alt if ri % 2 == 0 else st_data
        for ci, col in enumerate(cols):
            val = str(row.get(col, '')).replace('nan', '').strip()
            ws.write(ri, ci, val, st_rot if col == 'ROTEIRO' else st_base)

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


# ====================== PROCESSAMENTO ======================
def processar_arquivo(file):
    # Leitura do arquivo (CSV / XLSX / XLS) - mantida igual à versão anterior
    ext = file.filename.rsplit('.', 1)[-1].lower()

    if ext == 'csv':
        raw = file.read()
        text = None
        for enc in ('utf-8-sig', 'utf-8', 'cp1252', 'latin-1'):
            try:
                text = raw.decode(enc)
                break
            except:
                continue
        if text is None:
            raise ValueError("Não foi possível decodificar o arquivo CSV.")
        linhas = text.splitlines()
        corpo = [l.rstrip(';') for l in linhas if not l.startswith('[') or '[LISTA]' in l or '[/LISTA]' in l]
        # Simplificado - ajuste se necessário
        df = pd.read_csv(BytesIO('\n'.join(corpo).encode()), sep=';', dtype=str).fillna('')
    elif ext in ('xlsx', 'xls'):
        df = pd.read_excel(file, dtype=str, engine='openpyxl' if ext == 'xlsx' else 'xlrd').fillna('')
    else:
        raise ValueError("Formato não suportado.")

    df.columns = [c.strip() for c in df.columns]
    df = df[[c for c in df.columns if c]]

    if 'NOME DO CLIENTE' in df.columns:
        df = df[~df['NOME DO CLIENTE'].str.strip().isin(['RODAPÉ', ''])]

    obrigatorias = ['LOCAL', 'FURO', 'DUPLAGEM', 'DESCRIÇÃO DA PEÇA']
    faltando = [c for c in obrigatorias if c not in df.columns]
    if faltando:
        raise ValueError(f"Colunas obrigatórias não encontradas: {', '.join(faltando)}")

    # === CONSOLIDAÇÃO DE RIPAS ===
    df = consolidar_ripas(df)

    # === ROTEIRO ===
    df['ROTEIRO'] = df.apply(calcular_roteiro, axis=1)

    # Limpeza de tags
    for col in ['OBSERVAÇÃO', 'OBS']:
        if col in df.columns:
            df[col] = df[col].str.replace(r' *_(pin|tap|led|curvo|painel|ripa)_ *', ' ', case=False, regex=True).str.strip()

    return df


# ====================== ROTAS ======================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/processar', methods=['POST'])
def processar():
    try:
        if 'arquivo' not in request.files:
            return jsonify({'erro': 'Nenhum arquivo enviado'}), 400

        file = request.files['arquivo']
        if file.filename == '':
            return jsonify({'erro': 'Nome de arquivo inválido'}), 400

        df = processar_arquivo(file)

        pid = str(uuid.uuid4())[:8]
        nome_saida = f"{pid}_{file.filename.rsplit('.', 1)[0]}.xls"

        xls_buf = gerar_xls(df)

        caminho_arquivo = os.path.join(OUTPUTS_DIR, nome_saida)
        with open(caminho_arquivo, 'wb') as f:
            f.write(xls_buf.getvalue())   # <-- CORREÇÃO IMPORTANTE: getvalue() ao invés de read()

        # Salva no banco
        db = get_db()
        db.execute('INSERT INTO pedidos VALUES (?,?,?,?,?)',
                   (pid, file.filename, datetime.now().strftime('%d/%m/%Y %H:%M'),
                    len(df), nome_saida))
        db.commit()

        # Resposta para o front
        cols_previa = ['DESCRIÇÃO DA PEÇA', 'LOCAL', 'ROTEIRO']
        if 'OBS' in df.columns:
            cols_previa.insert(2, 'OBS')
        previa = df[cols_previa].head(50).to_dict(orient='records')

        resumo = df['ROTEIRO'].value_counts().reset_index()
        resumo.columns = ['roteiro', 'qtd']

        return jsonify({
            'pid': pid,
            'total': len(df),
            'previa': previa,
            'resumo': resumo.to_dict(orient='records')
        })

    except Exception as e:
        import traceback
        return jsonify({'erro': str(e), 'trace': traceback.format_exc()}), 500


@app.route('/download/<pid>')
def download(pid):
    row = get_db().execute('SELECT arquivo_out FROM pedidos WHERE id = ?', (pid,)).fetchone()
    if not row:
        return "Pedido não encontrado", 404

    caminho = os.path.join(OUTPUTS_DIR, row['arquivo_out'])
    if not os.path.exists(caminho):
        return "Arquivo não encontrado no servidor", 404

    return send_file(
        caminho,
        as_attachment=True,
        download_name=f"ROTEIRO_{row['arquivo_out']}"
    )


@app.route('/historico')
def historico():
    rows = get_db().execute('SELECT * FROM pedidos ORDER BY data DESC').fetchall()
    return jsonify([dict(r) for r in rows])


@app.route('/historico/<pid>', methods=['DELETE'])
def deletar(pid):
    db = get_db()
    row = db.execute('SELECT arquivo_out FROM pedidos WHERE id=?', (pid,)).fetchone()
    if row:
        try:
            os.remove(os.path.join(OUTPUTS_DIR, row['arquivo_out']))
        except:
            pass
        db.execute('DELETE FROM pedidos WHERE id=?', (pid,))
        db.commit()
    return jsonify({'ok': True})


if __name__ == '__main__':
    init_db()
    debug = os.environ.get('FLASK_DEBUG', '0') == '1'
    host = '127.0.0.1' if debug else '0.0.0.0'
    app.run(host=host, port=5000, debug=debug)