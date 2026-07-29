import os
import csv
import io
import shutil
import sqlite3
from functools import wraps
from datetime import datetime, date, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file, Response

app = Flask(__name__)
app.secret_key = 'contabilbs_secret_key_2024'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'contabil.db')
_DB_INITIALIZED = False

def get_db():
    global _DB_INITIALIZED
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if not _DB_INITIALIZED:
        conn.close()
        create_tables()
        _DB_INITIALIZED = True
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
    return conn

def create_tables():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.executescript('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario TEXT NOT NULL UNIQUE,
            senha TEXT NOT NULL,
            nome TEXT DEFAULT '',
            admin INTEGER DEFAULT 0,
            criado_em TEXT DEFAULT (datetime('now', 'localtime'))
        );
        CREATE TABLE IF NOT EXISTS categorias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            tipo TEXT NOT NULL CHECK(tipo IN ('entrada', 'saida'))
        );
        CREATE TABLE IF NOT EXISTS meses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mes INTEGER NOT NULL,
            ano INTEGER NOT NULL,
            fechado INTEGER DEFAULT 0,
            saldo_inicial REAL DEFAULT 0,
            aberto_em TEXT,
            fechado_em TEXT,
            UNIQUE(mes, ano)
        );
        CREATE TABLE IF NOT EXISTS lancamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mes_id INTEGER NOT NULL,
            categoria_id INTEGER,
            descricao TEXT NOT NULL,
            tipo TEXT NOT NULL CHECK(tipo IN ('entrada', 'saida')),
            valor REAL NOT NULL,
            data TEXT NOT NULL,
            observacao TEXT DEFAULT '',
            criado_em TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (mes_id) REFERENCES meses(id),
            FOREIGN KEY (categoria_id) REFERENCES categorias(id)
        );
        CREATE TABLE IF NOT EXISTS auditoria (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER,
            usuario_nome TEXT,
            acao TEXT NOT NULL,
            entidade TEXT NOT NULL,
            entidade_id INTEGER,
            descricao TEXT,
            data_hora TEXT DEFAULT (datetime('now', 'localtime'))
        );
    ''')
    try:
        cursor.execute("ALTER TABLE usuarios ADD COLUMN admin INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    cursor.execute("SELECT COUNT(*) FROM usuarios")
    if cursor.fetchone()[0] == 0:
        cursor.execute(
            "INSERT INTO usuarios (usuario, senha, nome, admin) VALUES (?, ?, ?, 1)",
            ('admin', '123456', 'Administrador')
        )
    else:
        cursor.execute("UPDATE usuarios SET admin = 1 WHERE usuario = 'admin'")
    cursor.execute("SELECT COUNT(*) FROM categorias")
    if cursor.fetchone()[0] == 0:
        categorias = [
            ('Corridas', 'entrada'), ('Outras Receitas', 'entrada'),
            ('Combustível', 'saida'), ('Manutenção', 'saida'),
            ('Impostos', 'saida'), ('Alimentação', 'saida'),
            ('Despesas Diversas', 'saida')
        ]
        cursor.executemany("INSERT INTO categorias (nome, tipo) VALUES (?, ?)", categorias)
    conn.commit()
    conn.close()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logado'):
            return redirect(url_for('login'))
        ultimo = session.get('ultimo_acesso')
        if ultimo:
            diff = (datetime.now() - datetime.fromisoformat(ultimo)).total_seconds()
            if diff > 1800:
                user = session.get('usuario')
                user_id = session.get('user_id')
                if user:
                    registrar_log('saiu', 'Sessão', user_id, f"Usuário: {user} (inatividade)")
                session.clear()
                flash('Sessão expirada por inatividade.', 'info')
                return redirect(url_for('login'))
        session['ultimo_acesso'] = datetime.now().isoformat()
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logado'):
            return redirect(url_for('login'))
        if not session.get('admin'):
            flash('Acesso restrito ao administrador.', 'danger')
            return redirect(url_for('landing'))
        return f(*args, **kwargs)
    return decorated

def registrar_log(acao, entidade, entidade_id, descricao=''):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO auditoria (usuario_id, usuario_nome, acao, entidade, entidade_id, descricao) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (session.get('user_id'), session.get('usuario'), acao, entidade, entidade_id, descricao)
    )
    conn.commit()
    conn.close()

@app.context_processor
def inject_now():
    return {'now': datetime.now()}

def get_or_create_mes_atual():
    hoje = date.today()
    mes = hoje.month
    ano = hoje.year
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, fechado, saldo_inicial FROM meses WHERE mes = ? AND ano = ?", (mes, ano))
    row = cursor.fetchone()
    if row:
        if row['fechado'] == 1:
            conn.close()
            return None, None
        conn.close()
        return row['id'], row['saldo_inicial']

    saldo_inicial = 0

    cursor.execute(
        "INSERT INTO meses (mes, ano, saldo_inicial, aberto_em) VALUES (?, ?, ?, datetime('now', 'localtime'))",
        (mes, ano, saldo_inicial)
    )
    conn.commit()
    novo_id = cursor.lastrowid
    conn.close()
    return novo_id, saldo_inicial

@app.template_filter('brl')
def brl_filter(value):
    if value is None:
        value = 0
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

@app.template_filter('mes_nome')
def mes_nome_filter(m):
    meses = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
             'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro']
    return meses[m - 1] if 1 <= m <= 12 else str(m)

@app.template_filter('data_br')
def data_br_filter(d):
    if not d:
        return ''
    try:
        partes = d.split('-')
        return f"{partes[2]}/{partes[1]}/{partes[0]}"
    except (IndexError, ValueError):
        return d

def parse_data_br(data_str):
    try:
        partes = data_str.split('/')
        return f"{partes[2]}-{partes[1]}-{partes[0]}"
    except (IndexError, ValueError):
        return data_str

@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('logado'):
        return redirect(url_for('landing'))
    if request.method == 'POST':
        usuario = request.form.get('usuario', '').strip()
        senha = request.form.get('senha', '').strip()
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM usuarios WHERE LOWER(usuario) = LOWER(?) AND senha = ?", (usuario, senha))
        user = cursor.fetchone()
        conn.close()
        if user:
            session['logado'] = True
            session['ultimo_acesso'] = datetime.now().isoformat()
            session['usuario'] = user['usuario']
            session['user_id'] = user['id']
            session['user_nome'] = user['nome']
            session['admin'] = user['admin'] == 1
            registrar_log('entrou', 'Sessão', user['id'], f"Usuário: {user['usuario']} ({user['nome']})")
            index_url = url_for('landing')
            return f'''<script>sessionStorage.setItem('bs_auth','1');window.location.replace('{index_url}');</script>'''
        flash('Usuário ou senha inválidos.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    if session.get('usuario'):
        registrar_log('saiu', 'Sessão', session.get('user_id'), f"Usuário: {session.get('usuario')}")
    session.clear()
    flash('Você saiu do sistema.', 'info')
    return redirect(url_for('login'))

def get_mes_aberto():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, mes, ano, saldo_inicial FROM meses WHERE fechado = 0 ORDER BY ano, mes LIMIT 1")
    mes = cursor.fetchone()
    conn.close()
    if mes:
        return mes['id'], mes['saldo_inicial']
    return None, None

@app.route('/')
@login_required
def landing():
    return render_template('landing.html')

@app.route('/lancamentos')
@login_required
def lancamentos():
    conn = get_db()
    cursor = conn.cursor()

    mes_id, saldo_inicial = get_mes_aberto()
    if mes_id is None:
        mes_id, saldo_inicial = get_or_create_mes_atual()
        if mes_id is None:
            conn.close()
            flash('Mês atual já está fechado. Inicie um novo mês.', 'warning')
            return redirect(url_for('relatorio'))

    cursor.execute("SELECT mes, ano FROM meses WHERE id = ?", (mes_id,))
    mes_atual = cursor.fetchone()

    tipo_filtro = request.args.get('tipo', '')

    sql = ("SELECT l.*, m.mes, m.ano FROM lancamentos l "
           "JOIN meses m ON l.mes_id = m.id WHERE l.mes_id = ?")
    params = [mes_id]
    if tipo_filtro:
        sql += " AND l.tipo = ?"
        params.append(tipo_filtro)
    sql += " ORDER BY l.data DESC, l.id DESC"
    cursor.execute(sql, params)
    lancamentos = cursor.fetchall()

    cursor.execute(
        "SELECT COALESCE(SUM(CASE WHEN tipo = 'entrada' THEN valor ELSE 0 END), 0) as total_entradas, "
        "COALESCE(SUM(CASE WHEN tipo = 'saida' THEN valor ELSE 0 END), 0) as total_saidas "
        "FROM lancamentos WHERE mes_id = ?", (mes_id,)
    )
    totais = cursor.fetchone()

    cursor.execute(
        "SELECT COALESCE(SUM(CASE WHEN tipo = 'entrada' THEN valor ELSE 0 END), 0) - "
        "COALESCE(SUM(CASE WHEN tipo = 'saida' THEN valor ELSE 0 END), 0) as saldo_acumulado "
        "FROM lancamentos WHERE mes_id = ?", (mes_id,)
    )
    saldo_mes = cursor.fetchone()['saldo_acumulado']

    conn.close()

    total_entradas = totais['total_entradas']
    total_saidas = totais['total_saidas']
    saldo = total_entradas - total_saidas

    return render_template('index.html',
                         mes_atual=mes_atual,
                         lancamentos=lancamentos,
                         total_entradas=total_entradas,
                         total_saidas=total_saidas,
                         saldo_inicial=saldo_inicial,
                         saldo=saldo,
                         saldo_mes=saldo_mes,
                         today=date.today().strftime('%d/%m/%Y'),
                         filtro_tipo=tipo_filtro)

@app.route('/adicionar', methods=['POST'])
@login_required
def adicionar():
    mes_id, _ = get_mes_aberto()
    if mes_id is None:
        mes_id, _ = get_or_create_mes_atual()
        if mes_id is None:
            flash('Não há mês aberto. Inicie um novo mês.', 'warning')
            return redirect(url_for('relatorio'))

    descricao = request.form.get('descricao', '').strip()
    tipo = request.form.get('tipo')
    valor_str = request.form.get('valor', '0').strip()
    data_br = request.form.get('data', date.today().strftime('%d/%m/%Y'))
    observacao = request.form.get('observacao', '').strip()

    if not descricao:
        flash('Descrição é obrigatória.', 'danger')
        return redirect(url_for('lancamentos'))
    if tipo not in ('entrada', 'saida'):
        flash('Tipo inválido.', 'danger')
        return redirect(url_for('lancamentos'))
    try:
        valor = float(valor_str.replace(',', '.'))
        if valor <= 0:
            raise ValueError
    except ValueError:
        flash('Valor inválido.', 'danger')
        return redirect(url_for('lancamentos'))

    data = parse_data_br(data_br)

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO lancamentos (mes_id, descricao, tipo, valor, data, observacao) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (mes_id, descricao, tipo, valor, data, observacao)
    )
    conn.commit()
    novo_id = cursor.lastrowid
    conn.close()
    registrar_log('criou', 'Lançamento', novo_id, f"{descricao} - {tipo} - R$ {valor:.2f}")
    flash('Lançamento adicionado com sucesso!', 'success')
    return redirect(url_for('lancamentos'))

@app.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar(id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM lancamentos WHERE id = ?",
        (id,)
    )
    lancamento = cursor.fetchone()
    if not lancamento:
        conn.close()
        flash('Lançamento não encontrado.', 'danger')
        return redirect(url_for('lancamentos'))

    conn.close()

    if request.method == 'POST':
        descricao = request.form.get('descricao', '').strip()
        tipo = request.form.get('tipo')
        valor_str = request.form.get('valor', '0').strip()
        data_br = request.form.get('data', lancamento['data'])
        observacao = request.form.get('observacao', '').strip()

        if not descricao:
            flash('Descrição é obrigatória.', 'danger')
            return render_template('editar.html', lancamento=lancamento)
        if tipo not in ('entrada', 'saida'):
            flash('Tipo inválido.', 'danger')
            return render_template('editar.html', lancamento=lancamento)
        try:
            valor = float(valor_str.replace(',', '.'))
            if valor <= 0:
                raise ValueError
        except ValueError:
            flash('Valor inválido.', 'danger')
            return render_template('editar.html', lancamento=lancamento)

        data = parse_data_br(data_br)

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE lancamentos SET descricao = ?, tipo = ?, valor = ?, data = ?, observacao = ? WHERE id = ?",
            (descricao, tipo, valor, data, observacao, id)
        )
        conn.commit()
        conn.close()
        registrar_log('editou', 'Lançamento', id, f"{descricao} - {tipo} - R$ {valor:.2f}")
        flash('Lançamento atualizado com sucesso!', 'success')
        return redirect(url_for('lancamentos'))

    return render_template('editar.html', lancamento=lancamento)

@app.route('/excluir/<int:id>')
@login_required
def excluir(id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT descricao, tipo, valor FROM lancamentos WHERE id = ?", (id,))
    item = cursor.fetchone()
    desc = f"{item['descricao']} - {item['tipo']} - R$ {item['valor']:.2f}" if item else ''
    cursor.execute("DELETE FROM lancamentos WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    registrar_log('excluiu', 'Lançamento', id, desc)
    flash('Lançamento excluído.', 'info')
    return redirect(url_for('lancamentos'))

@app.route('/categorias', methods=['GET', 'POST'])
@login_required
def gerenciar_categorias():
    conn = get_db()
    cursor = conn.cursor()

    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        tipo = request.form.get('tipo')
        if nome and tipo in ('entrada', 'saida'):
            cursor.execute("INSERT INTO categorias (nome, tipo) VALUES (?, ?)", (nome, tipo))
            conn.commit()
            flash('Categoria adicionada!', 'success')
        else:
            flash('Preencha nome e tipo.', 'danger')

    cursor.execute("SELECT * FROM categorias ORDER BY tipo, nome")
    categorias = cursor.fetchall()

    if request.args.get('excluir'):
        cursor.execute("DELETE FROM categorias WHERE id = ?", (request.args['excluir'],))
        conn.commit()
        conn.close()
        flash('Categoria excluída.', 'info')
        return redirect(url_for('gerenciar_categorias'))

    conn.close()
    return render_template('categorias.html', categorias=categorias)

@app.route('/finalizar-mes', methods=['POST'])
@login_required
def finalizar_mes():
    mes_id, _ = get_mes_aberto()
    if mes_id is None:
        flash('Não há mês aberto para finalizar.', 'warning')
        return redirect(url_for('relatorio'))
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT mes, ano FROM meses WHERE id = ?", (mes_id,))
    m = cursor.fetchone()
    cursor.execute(
        "UPDATE meses SET fechado = 1, fechado_em = datetime('now', 'localtime') WHERE id = ?",
        (mes_id,)
    )
    conn.commit()
    conn.close()
    registrar_log('finalizou', 'Mês', mes_id, f"Mês {m['mes']:02d}/{m['ano']}")
    flash('Mês finalizado com sucesso!', 'success')
    return redirect(url_for('relatorio'))

@app.route('/novo-mes')
@login_required
def novo_mes():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT mes, ano, fechado FROM meses WHERE fechado = 0 LIMIT 1")
    aberto = cursor.fetchone()
    if aberto:
        conn.close()
        flash('Já existe um mês aberto.', 'info')
        return redirect(url_for('lancamentos'))
    cursor.execute("SELECT mes, ano FROM meses ORDER BY ano DESC, mes DESC LIMIT 1")
    ultimo = cursor.fetchone()
    if ultimo:
        mes, ano = ultimo['mes'], ultimo['ano']
        if mes == 12:
            mes, ano = 1, ano + 1
        else:
            mes += 1
        cursor.execute("SELECT id FROM meses WHERE mes = ? AND ano = ?", (mes, ano))
        if cursor.fetchone():
            conn.close()
            flash(f'Mês {mes:02d}/{ano} já existe e está fechado.', 'warning')
            return redirect(url_for('relatorio'))
    else:
        hoje = date.today()
        mes, ano = hoje.month, hoje.year
    cursor.execute(
        "INSERT INTO meses (mes, ano, saldo_inicial, aberto_em) VALUES (?, ?, 0, datetime('now', 'localtime'))",
        (mes, ano)
    )
    conn.commit()
    novo_id = cursor.lastrowid
    conn.close()
    registrar_log('criou', 'Mês', novo_id, f"Mês {mes:02d}/{ano}")
    flash(f'Novo mês ({mes:02d}/{ano}) iniciado!', 'success')
    return redirect(url_for('lancamentos'))

@app.route('/relatorio')
@login_required
def relatorio():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM meses ORDER BY ano DESC, mes DESC")
    meses = cursor.fetchall()
    dados_meses = []
    for m in meses:
        cursor.execute(
            "SELECT COALESCE(SUM(CASE WHEN tipo = 'entrada' THEN valor ELSE 0 END), 0) as total_entradas, "
            "COALESCE(SUM(CASE WHEN tipo = 'saida' THEN valor ELSE 0 END), 0) as total_saidas "
            "FROM lancamentos WHERE mes_id = ?", (m['id'],)
        )
        tot = cursor.fetchone()
        dados_meses.append({
            'id': m['id'], 'mes': m['mes'], 'ano': m['ano'],
            'fechado': m['fechado'], 'aberto_em': m['aberto_em'],
            'fechado_em': m['fechado_em'],
            'saldo_inicial': m['saldo_inicial'],
            'total_entradas': tot['total_entradas'],
            'total_saidas': tot['total_saidas'],
            'saldo': m['saldo_inicial'] + tot['total_entradas'] - tot['total_saidas']
        })
    total_geral_entradas = sum(m['total_entradas'] for m in dados_meses)
    total_geral_saidas = sum(m['total_saidas'] for m in dados_meses)
    saldo_geral = total_geral_entradas - total_geral_saidas
    tem_mes_aberto = any(not m['fechado'] for m in dados_meses)

    cursor.execute(
        "SELECT l.*, m.mes, m.ano FROM lancamentos l "
        "JOIN meses m ON l.mes_id = m.id ORDER BY l.data DESC, l.id DESC"
    )
    todos_lancamentos = cursor.fetchall()

    conn.close()
    return render_template('relatorio.html',
                         dados_meses=dados_meses,
                         total_geral_entradas=total_geral_entradas,
                         total_geral_saidas=total_geral_saidas,
                         saldo_geral=saldo_geral,
                         tem_mes_aberto=tem_mes_aberto,
                         todos_lancamentos=todos_lancamentos)

@app.route('/relatorio-saldos')
@login_required
def relatorio_saldos():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM meses WHERE fechado = 1 ORDER BY ano, mes")
    meses = cursor.fetchall()
    dados = []
    for m in meses:
        cursor.execute(
            "SELECT COALESCE(SUM(CASE WHEN tipo = 'entrada' THEN valor ELSE 0 END), 0) as te, "
            "COALESCE(SUM(CASE WHEN tipo = 'saida' THEN valor ELSE 0 END), 0) as ts "
            "FROM lancamentos WHERE mes_id = ?", (m['id'],)
        )
        t = cursor.fetchone()
        saldo = m['saldo_inicial'] + t['te'] - t['ts']
        dados.append({'mes': m['mes'], 'ano': m['ano'],
                      'saldo_inicial': m['saldo_inicial'],
                      'entradas': t['te'], 'saidas': t['ts'],
                      'saldo': saldo, 'fechado_em': m['fechado_em']})
    conn.close()
    saldo_acumulado = sum(d['saldo'] for d in dados)
    return render_template('relatorio_saldos.html', dados=dados, saldo_acumulado=saldo_acumulado)

@app.route('/relatorio-saldos-discriminados')
@login_required
def relatorio_saldos_discriminados():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM meses WHERE fechado = 1 ORDER BY ano, mes")
    meses = cursor.fetchall()
    dados = []
    for m in meses:
        cursor.execute(
            "SELECT COALESCE(SUM(CASE WHEN tipo = 'entrada' THEN valor ELSE 0 END), 0) as te, "
            "COALESCE(SUM(CASE WHEN tipo = 'saida' THEN valor ELSE 0 END), 0) as ts "
            "FROM lancamentos WHERE mes_id = ?", (m['id'],)
        )
        t = cursor.fetchone()
        entradas = t['te']
        saidas = t['ts']
        saldo = m['saldo_inicial'] + entradas - saidas
        dados.append({
            'mes': f"{m['mes']:02d}/{m['ano']}",
            'entradas': entradas,
            'saidas': saidas,
            'saldo': saldo
        })
    conn.close()
    total_entradas = sum(d['entradas'] for d in dados)
    total_saidas = sum(d['saidas'] for d in dados)
    saldo_acumulado = total_entradas - total_saidas
    return render_template('relatorio_saldos_discriminados.html', dados=dados,
                         total_entradas=total_entradas, total_saidas=total_saidas,
                         saldo_acumulado=saldo_acumulado)

@app.route('/exportar-csv-saldos-discriminados')
@login_required
def exportar_csv_saldos_discriminados():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM meses WHERE fechado = 1 ORDER BY ano, mes")
    meses = cursor.fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Mês', 'Total Entradas', 'Total Saídas', 'Saldo'])
    for m in meses:
        cursor.execute(
            "SELECT COALESCE(SUM(CASE WHEN tipo = 'entrada' THEN valor ELSE 0 END), 0) as te, "
            "COALESCE(SUM(CASE WHEN tipo = 'saida' THEN valor ELSE 0 END), 0) as ts "
            "FROM lancamentos WHERE mes_id = ?", (m['id'],)
        )
        t = cursor.fetchone()
        saldo = m['saldo_inicial'] + t['te'] - t['ts']
        writer.writerow([f"{m['mes']:02d}/{m['ano']}",
                        f"{t['te']:.2f}", f"{t['ts']:.2f}", f"{saldo:.2f}"])
    conn.close()
    return Response(
        output.getvalue().encode('utf-8-sig'),
        mimetype='text/csv',
        headers={"Content-Disposition": "attachment;filename=saldos_discriminados.csv"}
    )

@app.route('/print-saldos-discriminados')
@login_required
def print_saldos_discriminados():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM meses WHERE fechado = 1 ORDER BY ano, mes")
    meses = cursor.fetchall()
    dados = []
    for m in meses:
        cursor.execute(
            "SELECT COALESCE(SUM(CASE WHEN tipo = 'entrada' THEN valor ELSE 0 END), 0) as te, "
            "COALESCE(SUM(CASE WHEN tipo = 'saida' THEN valor ELSE 0 END), 0) as ts "
            "FROM lancamentos WHERE mes_id = ?", (m['id'],)
        )
        t = cursor.fetchone()
        saldo = m['saldo_inicial'] + t['te'] - t['ts']
        dados.append({'mes': f"{m['mes']:02d}/{m['ano']}",
                      'entradas': t['te'], 'saidas': t['ts'],
                      'saldo': saldo})
    conn.close()
    total_entradas = sum(d['entradas'] for d in dados)
    total_saidas = sum(d['saidas'] for d in dados)
    saldo_acumulado = total_entradas - total_saidas
    return render_template('print_saldos_discriminados.html', dados=dados,
                         total_entradas=total_entradas, total_saidas=total_saidas,
                         saldo_acumulado=saldo_acumulado, now=datetime.now())

@app.route('/exportar-csv-saldos')
@login_required
def exportar_csv_saldos():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM meses WHERE fechado = 1 ORDER BY ano, mes")
    meses = cursor.fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Mês', 'Ano', 'Fechado em', 'Saldo Inicial', 'Entradas', 'Saídas', 'Saldo Final'])
    for m in meses:
        cursor.execute(
            "SELECT COALESCE(SUM(CASE WHEN tipo = 'entrada' THEN valor ELSE 0 END), 0) as te, "
            "COALESCE(SUM(CASE WHEN tipo = 'saida' THEN valor ELSE 0 END), 0) as ts "
            "FROM lancamentos WHERE mes_id = ?", (m['id'],)
        )
        t = cursor.fetchone()
        saldo = m['saldo_inicial'] + t['te'] - t['ts']
        writer.writerow([f"{m['mes']:02d}", m['ano'], m['fechado_em'],
                        f"{m['saldo_inicial']:.2f}", f"{t['te']:.2f}", f"{t['ts']:.2f}", f"{saldo:.2f}"])
    conn.close()
    return Response(
        output.getvalue().encode('utf-8-sig'),
        mimetype='text/csv',
        headers={"Content-Disposition": "attachment;filename=saldos.csv"}
    )

@app.route('/print-saldos')
@login_required
def print_saldos():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM meses WHERE fechado = 1 ORDER BY ano, mes")
    meses = cursor.fetchall()
    dados = []
    for m in meses:
        cursor.execute(
            "SELECT COALESCE(SUM(CASE WHEN tipo = 'entrada' THEN valor ELSE 0 END), 0) as te, "
            "COALESCE(SUM(CASE WHEN tipo = 'saida' THEN valor ELSE 0 END), 0) as ts "
            "FROM lancamentos WHERE mes_id = ?", (m['id'],)
        )
        t = cursor.fetchone()
        saldo = m['saldo_inicial'] + t['te'] - t['ts']
        dados.append({'mes': m['mes'], 'ano': m['ano'],
                      'saldo': saldo, 'fechado_em': m['fechado_em']})
    conn.close()
    saldo_acumulado = sum(d['saldo'] for d in dados)
    return render_template('print_saldos.html', dados=dados, saldo_acumulado=saldo_acumulado, now=datetime.now())

@app.route('/dados-grafico')
@login_required
def dados_grafico():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM meses ORDER BY ano, mes")
    meses = cursor.fetchall()
    labels = []
    entradas = []
    saidas = []
    for m in meses:
        labels.append(f"{m['mes']}/{m['ano']}")
        cursor.execute(
            "SELECT COALESCE(SUM(CASE WHEN tipo = 'entrada' THEN valor ELSE 0 END), 0) as tot "
            "FROM lancamentos WHERE mes_id = ?", (m['id'],)
        )
        entradas.append(cursor.fetchone()['tot'])
        cursor.execute(
            "SELECT COALESCE(SUM(CASE WHEN tipo = 'saida' THEN valor ELSE 0 END), 0) as tot "
            "FROM lancamentos WHERE mes_id = ?", (m['id'],)
        )
        saidas.append(cursor.fetchone()['tot'])
    conn.close()
    return {'labels': labels, 'entradas': entradas, 'saidas': saidas}

@app.route('/detalhes-mes/<int:mes_id>')
@login_required
def detalhes_mes(mes_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM meses WHERE id = ?", (mes_id,))
    mes = cursor.fetchone()
    if not mes:
        conn.close()
        flash('Mês não encontrado.', 'danger')
        return redirect(url_for('relatorio'))
    cursor.execute(
        "SELECT * FROM lancamentos WHERE mes_id = ? ORDER BY data DESC, id DESC",
        (mes_id,)
    )
    lancamentos = cursor.fetchall()
    cursor.execute(
        "SELECT COALESCE(SUM(CASE WHEN tipo = 'entrada' THEN valor ELSE 0 END), 0) as total_entradas, "
        "COALESCE(SUM(CASE WHEN tipo = 'saida' THEN valor ELSE 0 END), 0) as total_saidas "
        "FROM lancamentos WHERE mes_id = ?", (mes_id,)
    )
    totais = cursor.fetchone()
    conn.close()
    total_entradas = totais['total_entradas']
    total_saidas = totais['total_saidas']
    saldo = mes['saldo_inicial'] + total_entradas - total_saidas
    return render_template('detalhes_mes.html',
                         mes=mes, lancamentos=lancamentos,
                         total_entradas=total_entradas, total_saidas=total_saidas,
                         saldo_inicial=mes['saldo_inicial'], saldo=saldo)

@app.route('/reabrir-mes/<int:mes_id>', methods=['POST'])
@login_required
def reabrir_mes(mes_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM meses WHERE id = ?", (mes_id,))
    mes = cursor.fetchone()
    if not mes:
        conn.close()
        flash('Mês não encontrado.', 'danger')
        return redirect(url_for('relatorio'))
    if not mes['fechado']:
        conn.close()
        flash('Mês já está aberto.', 'warning')
        return redirect(url_for('detalhes_mes', mes_id=mes_id))
    cursor.execute("UPDATE meses SET fechado = 0, fechado_em = NULL WHERE id = ?", (mes_id,))
    conn.commit()
    conn.close()
    nome_mes = f"{mes['mes']:02d}/{mes['ano']}"
    registrar_log('reabriu', 'Mês', mes_id, f"Mês {nome_mes}")
    flash(f'Mês {nome_mes} reaberto. Verifique o saldo inicial do próximo mês, se houver.', 'warning')
    return redirect(url_for('detalhes_mes', mes_id=mes_id))

@app.route('/excluir-mes/<int:mes_id>')
@admin_required
def excluir_mes(mes_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT mes, ano FROM meses WHERE id = ?", (mes_id,))
    mes = cursor.fetchone()
    if not mes:
        conn.close()
        flash('Mês não encontrado.', 'danger')
        return redirect(url_for('relatorio'))
    cursor.execute("DELETE FROM lancamentos WHERE mes_id = ?", (mes_id,))
    cursor.execute("DELETE FROM meses WHERE id = ?", (mes_id,))
    conn.commit()
    conn.close()
    registrar_log('excluiu', 'Mês', mes_id, f"Mês {mes['mes']:02d}/{mes['ano']} e seus lançamentos")
    flash(f'Mês {mes["mes"]:02d}/{mes["ano"]} e seus lançamentos foram excluídos.', 'success')
    return redirect(url_for('relatorio'))

@app.route('/exportar-csv/<int:mes_id>')
@login_required
def exportar_csv(mes_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT mes, ano FROM meses WHERE id = ?", (mes_id,))
    mes = cursor.fetchone()
    if not mes:
        conn.close()
        flash('Mês não encontrado.', 'danger')
        return redirect(url_for('relatorio'))
    cursor.execute(
        "SELECT l.data, l.descricao, l.tipo, l.valor, l.observacao "
        "FROM lancamentos l WHERE l.mes_id = ? ORDER BY l.data",
        (mes_id,)
    )
    lancamentos = cursor.fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Data', 'Descrição', 'Tipo', 'Valor', 'Observação'])
    for l in lancamentos:
        writer.writerow([l['data'], l['descricao'],
                        'Entrada' if l['tipo'] == 'entrada' else 'Saída',
                        f"{l['valor']:.2f}", l['observacao'] or ''])

    nome_mes = f"{lancamentos[0]['data'][:7]}" if lancamentos else f"{mes['mes']:02d}{mes['ano']}"
    return Response(
        output.getvalue().encode('utf-8-sig'),
        mimetype='text/csv',
        headers={"Content-Disposition": f"attachment;filename=lancamentos_{nome_mes}.csv"}
    )

@app.route('/print/<int:mes_id>')
@login_required
def print_mes(mes_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM meses WHERE id = ?", (mes_id,))
    mes = cursor.fetchone()
    if not mes:
        conn.close()
        flash('Mês não encontrado.', 'danger')
        return redirect(url_for('relatorio'))
    cursor.execute(
        "SELECT * FROM lancamentos WHERE mes_id = ? ORDER BY data DESC, id DESC", (mes_id,)
    )
    lancamentos = cursor.fetchall()
    cursor.execute(
        "SELECT COALESCE(SUM(CASE WHEN tipo = 'entrada' THEN valor ELSE 0 END), 0) as te, "
        "COALESCE(SUM(CASE WHEN tipo = 'saida' THEN valor ELSE 0 END), 0) as ts "
        "FROM lancamentos WHERE mes_id = ?", (mes_id,)
    )
    t = cursor.fetchone()
    conn.close()
    te, ts = t['te'], t['ts']
    return render_template('print.html', mes=mes, lancamentos=lancamentos,
                          total_entradas=te, total_saidas=ts,
                          saldo_inicial=mes['saldo_inicial'],
                          saldo=mes['saldo_inicial'] + te - ts)

@app.route('/backup')
@admin_required
def backup():
    if not os.path.exists(DB_PATH):
        flash('Banco de dados não encontrado.', 'danger')
        return redirect(url_for('relatorio'))
    registrar_log('exportou', 'Backup', 0, 'Download do backup do banco de dados')
    return send_file(DB_PATH, as_attachment=True, download_name=f'contabil_backup_{date.today().isoformat()}.db')

@app.route('/restore', methods=['POST'])
@admin_required
def restaurar_backup():
    global _DB_INITIALIZED
    if 'arquivo' not in request.files:
        flash('Nenhum arquivo enviado.', 'danger')
        return redirect(url_for('relatorio'))
    arquivo = request.files['arquivo']
    if arquivo.filename == '' or not arquivo.filename.endswith('.db'):
        flash('Envie um arquivo .db válido.', 'danger')
        return redirect(url_for('relatorio'))
    try:
        db_temp = DB_PATH + '.bak'
        if os.path.exists(DB_PATH):
            os.replace(DB_PATH, db_temp)
        arquivo.save(DB_PATH)
        if os.path.exists(db_temp):
            os.remove(db_temp)
        _DB_INITIALIZED = False
        registrar_log('restaurou', 'Backup', 0, f'Backup restaurado de: {arquivo.filename}')
        flash('Backup restaurado com sucesso!', 'success')
    except Exception as e:
        if os.path.exists(db_temp):
            os.replace(db_temp, DB_PATH)
        flash(f'Erro ao restaurar backup: {str(e)}', 'danger')
    return redirect(url_for('relatorio'))

@app.route('/logs')
@admin_required
def ver_logs():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM auditoria ORDER BY data_hora DESC LIMIT 500")
    logs = cursor.fetchall()
    conn.close()
    return render_template('logs.html', logs=logs)

@app.route('/logs/excluir/<int:log_id>', methods=['POST'])
@admin_required
def excluir_log(log_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM auditoria WHERE id = ?", (log_id,))
    conn.commit()
    conn.close()
    flash('Log excluído.', 'success')
    return redirect(url_for('ver_logs'))

@app.route('/usuarios')
@admin_required
def listar_usuarios():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM usuarios ORDER BY admin DESC, usuario")
    usuarios = cursor.fetchall()
    conn.close()
    return render_template('usuarios.html', usuarios=usuarios)

@app.route('/usuarios/adicionar', methods=['POST'])
@admin_required
def adicionar_usuario():
    usuario = request.form.get('usuario', '').strip()
    senha = request.form.get('senha', '').strip()
    nome = request.form.get('nome', '').strip()
    admin = 1 if request.form.get('admin') else 0
    if not usuario or not senha:
        flash('Usuário e senha são obrigatórios.', 'danger')
        return redirect(url_for('listar_usuarios'))
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO usuarios (usuario, senha, nome, admin) VALUES (?, ?, ?, ?)",
            (usuario, senha, nome, admin)
        )
        conn.commit()
        registrar_log('criou', 'Usuário', cursor.lastrowid, f"Usuário: {usuario}")
        flash('Usuário cadastrado com sucesso!', 'success')
    except sqlite3.IntegrityError:
        flash('Usuário já existe.', 'danger')
    conn.close()
    return redirect(url_for('listar_usuarios'))

@app.route('/usuarios/excluir/<int:id>')
@admin_required
def excluir_usuario(id):
    if id == session.get('user_id'):
        flash('Você não pode excluir seu próprio usuário.', 'danger')
        return redirect(url_for('listar_usuarios'))
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT usuario FROM usuarios WHERE id = ?", (id,))
    user = cursor.fetchone()
    if not user:
        flash('Usuário não encontrado.', 'danger')
        conn.close()
        return redirect(url_for('listar_usuarios'))
    if user['usuario'] == 'admin':
        flash('Não é possível excluir o administrador padrão.', 'danger')
        conn.close()
        return redirect(url_for('listar_usuarios'))
    cursor.execute("DELETE FROM usuarios WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    registrar_log('excluiu', 'Usuário', id, f"Usuário: {user['usuario']}")
    flash('Usuário excluído.', 'info')
    return redirect(url_for('listar_usuarios'))

@app.route('/usuarios/editar/<int:id>', methods=['GET', 'POST'])
@admin_required
def editar_usuario(id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM usuarios WHERE id = ?", (id,))
    user = cursor.fetchone()
    if not user:
        conn.close()
        flash('Usuário não encontrado.', 'danger')
        return redirect(url_for('listar_usuarios'))

    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        senha = request.form.get('senha', '').strip()
        admin = 1 if request.form.get('admin') else 0
        if senha:
            cursor.execute(
                "UPDATE usuarios SET nome = ?, senha = ?, admin = ? WHERE id = ?",
                (nome, senha, admin, id)
            )
        else:
            cursor.execute(
                "UPDATE usuarios SET nome = ?, admin = ? WHERE id = ?",
                (nome, admin, id)
            )
        conn.commit()
        conn.close()
        registrar_log('editou', 'Usuário', id, f"Usuário: {user['usuario']}")
        flash('Usuário atualizado com sucesso!', 'success')
        return redirect(url_for('listar_usuarios'))

    conn.close()
    return render_template('editar_usuario.html', user=user)

if __name__ == '__main__':
    create_tables()
    _DB_INITIALIZED = True
    app.run(debug=True, host='0.0.0.0', port=5000)
