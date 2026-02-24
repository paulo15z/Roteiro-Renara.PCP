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
            id TEXT PRIMARY KEY, nome TEXT, data TEXT, total_pecas INTEGER, arquivo_out TEXT)''')
        db.commit()

def normalizar_coluna(nome):
    import unicodedata
    nfkd = unicodedata.normalize('NFKD', nome)
    sem_acento = ''.join(c for c in nfkd if not unicodedata.combining(c))
    return sem_acento.upper().strip()

# Mapeamento: nome normalizado -> nome padrão interno
MAPA_NORMALIZACAO = {
    'NOME DO CLIENTE':        'NOME DO CLIENTE',
    'ID DO PROJETO':          'ID DO PROJETO',
    'NOME DO PROJETO':        'NOME DO PROJETO',
    'REFERENCIA DA PECA':     'REFERENCIA DA PECA',
    'DESCRICAO MODULO':       'DESCRICAO MODULO',
    'QUANTIDADE':             'QUANTIDADE',
    'LARGURA DA PECA':        'LARGURA',
    'LARGURA':                'LARGURA',
    'ALTURA DA PECA':         'ALTURA',
    'ALTURA':                 'ALTURA',
    'METRO QUADRADO':         'METRO QUADRADO',
    'ESPESSURA':              'ESPESSURA',
    'CODIGO DO MATERIAL':     'CODIGO DO MATERIAL',
    'MATERIAL DA PECA':       'MATERIAL',
    'MATERIAL':               'MATERIAL',
    'VEIO':                   'VEIO',
    'BORDA_FACE_FRENTE':      'BORDA_FRENTE',
    'BORDA_FRENTE':           'BORDA_FRENTE',
    'BORDA_FACE_TRASEIRA':    'BORDA_TRASEIRA',
    'BORDA_TRASEIRA':         'BORDA_TRASEIRA',
    'BORDA_FACE_LE':          'BORDA_LE',
    'BORDA_LE':               'BORDA_LE',
    'BORDA_FACE_LD':          'BORDA_LD',
    'BORDA_LD':               'BORDA_LD',
    'LOTE':                   'LOTE',
    'OBSERVACAO':             'OBSERVACAO',
    'DESCRICAO DA PECA':      'DESCRICAO DA PECA',
    'ID DA PECA':             'ID DA PECA',
    'LOCAL':                  'LOCAL',
    'DUPLAGEM':               'DUPLAGEM',
    'FURO':                   'FURO',
    'OBS':                    'OBS',
}

def calcular_roteiro(row):
    local    = str(row.get('LOCAL', '')).strip()
    desc     = str(row.get('DESCRICAO DA PECA', '')).strip().lower()
    duplagem = str(row.get('DUPLAGEM', '')).strip().lower()
    furo     = str(row.get('FURO', '')).strip()

    b_cols = ['BORDA_FRENTE', 'BORDA_TRASEIRA', 'BORDA_LE', 'BORDA_LD']
    tem_borda = any(str(row.get(c, '')).strip() not in ('', 'nan', 'None') for c in b_cols)

    eh_perfil = 'perfil db' in desc

    rota = ['COR']
    if tem_borda:
        rota.append('XBOR' if eh_perfil else 'BOR')
    if duplagem and duplagem not in ('nan', 'none', ''):
        rota.append('DUP')
    if furo and furo not in ('nan', 'none', ''):
        rota.append('USI')
        rota.append('FUR')

    if local in ('Caixa', 'Gaveta'):
        rota.append('CAX')
    elif local == 'Porta':
        rota.append('XMAR' if eh_perfil else 'MAR')
    elif local == 'Tamponamento':
        rota.append('MAR')

    rota.append('EXP')
    return ' > '.join(rota)

COLUNAS_SAIDA = [
    'ID DO PROJETO', 'NOME DO PROJETO', 'DESCRICAO MODULO', 'DESCRICAO DA PECA',
    'ID DA PECA', 'QUANTIDADE', 'LARGURA', 'ALTURA', 'ESPESSURA', 'MATERIAL',
    'LOCAL', 'BORDA_FRENTE', 'BORDA_TRASEIRA', 'BORDA_LE', 'BORDA_LD',
    'FURO', 'OBS', 'DUPLAGEM', 'ROTEIRO'
]

def gerar_xls(df):
    wb = xlwt.Workbook(encoding='utf-8')
    ws = wb.add_sheet('Roteiro de Pecas')
    header_style = xlwt.easyxf(
        'font: bold true, colour white; pattern: pattern solid, fore_colour dark_blue; '
        'alignment: horiz centre, vert centre; borders: left thin, right thin, top thin, bottom thin;'
    )
    data_style = xlwt.easyxf(
        'font: height 180; alignment: horiz centre, vert centre; '
        'borders: left thin, right thin, top thin, bottom thin;'
    )
    for ci, col in enumerate(COLUNAS_SAIDA):
        ws.write(0, ci, col, header_style)
        ws.col(ci).width = 4500
    for ri, (_, row) in enumerate(df.iterrows(), 1):
        for ci, col in enumerate(COLUNAS_SAIDA):
            val = str(row.get(col, '')).replace('nan', '')
            ws.write(ri, ci, val, data_style)
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf

def processar_arquivo(file):
    nome = file.filename
    ext = nome.rsplit('.', 1)[-1].lower()

    if ext == 'csv':
        raw = file.read()
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError:
            text = raw.decode('latin-1')

        linhas = text.splitlines()
        corpo = []
        em_lista = False
        for l in linhas:
            if '[LISTA]' in l:
                em_lista = True
                continue
            if '[/LISTA]' in l:
                em_lista = False
                continue
            if (em_lista or not l.startswith('[')) and l.strip():
                corpo.append(l.rstrip(';'))

        df = pd.read_csv(StringIO('\n'.join(corpo)), sep=';', dtype=str).fillna('')
    else:
        df = pd.read_excel(file, dtype=str).fillna('')

    # Normaliza nomes de colunas removendo acentos
    mapa_rename = {}
    for col_original in df.columns:
        col_norm = normalizar_coluna(col_original)
        col_padrao = MAPA_NORMALIZACAO.get(col_norm)
        if col_padrao:
            mapa_rename[col_original] = col_padrao

    df = df.rename(columns=mapa_rename)

    df['ROTEIRO'] = df.apply(calcular_roteiro, axis=1)

    for c in COLUNAS_SAIDA:
        if c not in df.columns:
            df[c] = ''

    return df

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

        previa_lista = []
        for _, r in df.head(50).iterrows():
            previa_lista.append({
                'DESCRIÇÃO DA PEÇA': r.get('DESCRICAO DA PECA', ''),
                'LOCAL': r.get('LOCAL', ''),
                'OBS': r.get('OBS', ''),
                'ROTEIRO': r.get('ROTEIRO', '')
            })

        resumo = df['ROTEIRO'].value_counts().reset_index()
        resumo.columns = ['roteiro', 'qtd']
        resumo_dict = resumo.to_dict(orient='records')

        pid = str(uuid.uuid4())[:8]
        nome_saida = f"{pid}_{file.filename.rsplit('.', 1)[0]}.xls"

        xls_buf = gerar_xls(df)
        with open(os.path.join(OUTPUTS_DIR, nome_saida), 'wb') as f:
            f.write(xls_buf.read())

        db = get_db()
        db.execute('INSERT INTO pedidos VALUES (?,?,?,?,?)',
                   (pid, file.filename, datetime.now().strftime('%d/%m/%Y %H:%M'), len(df), nome_saida))
        db.commit()

        return jsonify({'pid': pid, 'total': len(df), 'previa': previa_lista, 'resumo': resumo_dict})
    except Exception as e:
        import traceback
        return jsonify({'erro': str(e), 'trace': traceback.format_exc()}), 500

@app.route('/download/<pid>')
def download(pid):
    row = get_db().execute('SELECT arquivo_out, nome FROM pedidos WHERE id=?', (pid,)).fetchone()
    if not row:
        return "404", 404
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
        try:
            os.remove(os.path.join(OUTPUTS_DIR, row['arquivo_out']))
        except Exception:
            pass
        db.execute('DELETE FROM pedidos WHERE id=?', (pid,))
        db.commit()
    return jsonify({'ok': True})

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)