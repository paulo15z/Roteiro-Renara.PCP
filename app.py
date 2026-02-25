import os, sqlite3, uuid
from datetime import datetime
from flask import Flask, request, jsonify, send_file, render_template, g
import pandas as pd
from io import StringIO, BytesIO
import xlwt

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

DATA_DIR    = os.environ.get('DATA_DIR', os.path.dirname(os.path.abspath(__file__)))
DB_PATH     = os.path.join(DATA_DIR, 'historico.db')
OUTPUTS_DIR = os.path.join(DATA_DIR, 'outputs')
os.makedirs(OUTPUTS_DIR, exist_ok=True)

# ─── BANCO DE DADOS ───────────────────────────────────────────────────────────
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
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
            id TEXT PRIMARY KEY, nome TEXT, data TEXT,
            total_pecas INTEGER, arquivo_out TEXT)''')
        db.commit()

# ─── LÓGICA DE ROTEIRO ────────────────────────────────────────────────────────
# Colunas de borda — nomes exatos do Dinabox
BORDA_COLS = ['BORDA_FACE_FRENTE', 'BORDA_FACE_TRASEIRA', 'BORDA_FACE_LE', 'BORDA_FACE_LD']

def calcular_roteiro(row):
    """
    Organiza o fluxo de cada peça pelos setores da marcenaria:
    COR → BOR → USI/FUR → DUP → MCX → MPE → MAR → PIN/TAP/LED → CQL → EXP
        - COR [...] - CQL - EXP são obrigatórios para todas as peças!!
    Serviços especiais detectados por tags na coluna OBSERVAÇÃO: #pin, #tap, #led [verificar implantação no dinabox]
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
    eh_gaveta    = 'gaveta' in desc or 'gaveteiro' in desc or 'gaveta' in local
    eh_caixa     = 'caixa' in local
    eh_frontal   = 'frontal' in local or 'frontal' in desc
    eh_tamponamento = 'tamponamento' in local
    
    # Detectar serviços especiais por OBS - apenas tags específicas
    # Procura por tags: _pin_, _tap_, _led_ [ implantando mudanças no dinabox ]
    tem_pintura  = '_pin_' in obs
    tem_tapecar  = '_tap_' in obs
    tem_eletrica = '_led_' in obs
    
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
        rota.append('MAR')  # Após MPE, vai para marceneiro revisar e encaixar porta
    
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

# ─── GERAÇÃO DO XLS ───────────────────────────────────────────────────────────
def gerar_xls(df):
    wb = xlwt.Workbook(encoding='utf-8')
    ws = wb.add_sheet('Roteiro de Pecas')

    st_header = xlwt.easyxf(
        'font: bold true, colour white, height 200;'
        'pattern: pattern solid, fore_colour dark_blue;'
        'alignment: horiz centre, vert centre, wrap true;'
        'borders: left thin, right thin, top thin, bottom thin;'
    )
    st_header_rot = xlwt.easyxf(
        'font: bold true, colour white, height 200;'
        'pattern: pattern solid, fore_colour dark_yellow;'
        'alignment: horiz centre, vert centre;'
        'borders: left thin, right thin, top thin, bottom thin;'
    )
    st_data = xlwt.easyxf(
        'font: height 180; alignment: horiz centre, vert centre;'
        'borders: left thin, right thin, top thin, bottom thin;'
    )
    st_data_alt = xlwt.easyxf(
        'font: height 180; pattern: pattern solid, fore_colour ice_blue;'
        'alignment: horiz centre, vert centre;'
        'borders: left thin, right thin, top thin, bottom thin;'
    )
    st_rot = xlwt.easyxf(
        'font: bold true, height 180;'
        'pattern: pattern solid, fore_colour light_yellow;'
        'alignment: horiz centre, vert centre;'
        'borders: left thin, right thin, top thin, bottom thin;'
    )

    cols = list(df.columns)
    ws.row(0).height_mismatch = True
    ws.row(0).height = 600

    for ci, col in enumerate(cols):
        st = st_header_rot if col == 'ROTEIRO' else st_header
        ws.write(0, ci, col, st)
        ws.col(ci).width = 5000 if col == 'ROTEIRO' else 3800

    for ri, (_, row) in enumerate(df.iterrows(), 1):
        st_base = st_data_alt if ri % 2 == 0 else st_data
        for ci, col in enumerate(cols):
            val = str(row.get(col, '')).replace('nan', '').strip()
            ws.write(ri, ci, val, st_rot if col == 'ROTEIRO' else st_base)

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf

# ─── PROCESSAMENTO ────────────────────────────────────────────────────────────
def processar_arquivo(file):
    ext = file.filename.rsplit('.', 1)[-1].lower()

    if ext == 'csv':
        raw = file.read()
        text = None
        for enc in ('utf-8-sig', 'utf-8', 'cp1252', 'latin-1'):
            try: text = raw.decode(enc); break
            except: continue
        if text is None:
            raise ValueError("Não foi possível decodificar o arquivo.")

        linhas = text.splitlines()
        corpo = []
        em_lista = False
        for l in linhas:
            if '[LISTA]' in l:    em_lista = True;  continue
            if '[/LISTA]' in l:   em_lista = False; continue
            if (em_lista or not l.startswith('[')) and l.strip():
                corpo.append(l.rstrip(';'))

        df = pd.read_csv(StringIO('\n'.join(corpo)), sep=';', dtype=str).fillna('')

    elif ext == 'xlsx':
        df = pd.read_excel(file, dtype=str, engine='openpyxl').fillna('')
    elif ext == 'xls':
        import tempfile, os as _os
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.xls')
        try:
            file.save(tmp.name); tmp.close()
            df = pd.read_excel(tmp.name, dtype=str, engine='xlrd').fillna('')
        finally:
            _os.unlink(tmp.name)
    else:
        raise ValueError("Formato não suportado. Use CSV, XLS ou XLSX.")

    # Remove coluna vazia (gerada pelo ; extra do Dinabox)
    df.columns = [c.strip() for c in df.columns]
    df = df[[c for c in df.columns if c]]

    # Remove linha de rodapé
    if 'NOME DO CLIENTE' in df.columns:
        df = df[~df['NOME DO CLIENTE'].str.strip().isin(['RODAPÉ', ''])]

    # Verifica colunas mínimas
    obrigatorias = ['LOCAL', 'FURO', 'DUPLAGEM', 'DESCRIÇÃO DA PEÇA']
    faltando = [c for c in obrigatorias if c not in df.columns]
    if faltando:
        raise ValueError(f"Colunas não encontradas: {', '.join(faltando)}")

    # Adiciona ROTEIRO — mantém tudo mais na ordem original do Dinabox
    df['ROTEIRO'] = df.apply(calcular_roteiro, axis=1)
    
    # Remove tags de serviços especiais da coluna OBSERVAÇÃO para limpeza da etiqueta
    if 'OBSERVAÇÃO' in df.columns:
        df['OBSERVAÇÃO'] = df['OBSERVAÇÃO'].str.replace(r' *_(pin|tap|led)_ *', ' ', case=False, regex=True).str.strip()
    
    return df

# ─── ROTAS ────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/processar', methods=['POST'])
def processar():
    try:
        if 'arquivo' not in request.files:
            return jsonify({'erro': 'Arquivo não enviado'}), 400
        file = request.files['arquivo']
        df = processar_arquivo(file)

        # Inclui OBS na prévia se a coluna existir
        cols_previa = ['DESCRIÇÃO DA PEÇA', 'LOCAL', 'ROTEIRO']
        if 'OBS' in df.columns: cols_previa.insert(2, 'OBS')
        previa = df[cols_previa].head(50).to_dict(orient='records')
        resumo = df['ROTEIRO'].value_counts().reset_index()
        resumo.columns = ['roteiro', 'qtd']

        pid = str(uuid.uuid4())[:8]
        nome_saida = f"{pid}_{file.filename.rsplit('.', 1)[0]}.xls"
        xls_buf = gerar_xls(df)
        with open(os.path.join(OUTPUTS_DIR, nome_saida), 'wb') as f:
            f.write(xls_buf.read())

        db = get_db()
        db.execute('INSERT INTO pedidos VALUES (?,?,?,?,?)',
                   (pid, file.filename, datetime.now().strftime('%d/%m/%Y %H:%M'),
                    len(df), nome_saida))
        db.commit()

        return jsonify({
            'pid': pid, 'total': len(df),
            'previa': previa,
            'resumo': resumo.to_dict(orient='records')
        })
    except Exception as e:
        import traceback
        return jsonify({'erro': str(e), 'trace': traceback.format_exc()}), 500

@app.route('/download/<pid>')
def download(pid):
    row = get_db().execute('SELECT arquivo_out, nome FROM pedidos WHERE id=?', (pid,)).fetchone()
    if not row: return "Não encontrado", 404
    return send_file(
        os.path.join(OUTPUTS_DIR, row['arquivo_out']),
        as_attachment=True,
        download_name=f"ROTEIRO_{row['nome']}.xls"
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
        try: os.remove(os.path.join(OUTPUTS_DIR, row['arquivo_out']))
        except: pass
        db.execute('DELETE FROM pedidos WHERE id=?', (pid,))
        db.commit()
    return jsonify({'ok': True})

if __name__ == '__main__':
    with app.app_context():
        init_db()
    debug = os.environ.get('FLASK_DEBUG', '0') == '1'
    host  = '127.0.0.1' if debug else '0.0.0.0'
    app.run(host=host, port=5000, debug=debug)