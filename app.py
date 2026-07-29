import os
import csv
import io
import shutil
import sqlite3
from functools import wraps
from datetime import datetime, date
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file, Response

app = Flask(__name__)
app.secret_key = 'contabilbs_secret_key_2024'

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'contabil.db')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.executescript('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario TEXT NOT NULL UNIQUE,
            senha TEXT NOT NULL,
            nome TEXT DEFAULT '',
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
    ''')
    cursor.execute("SELECT COUNT(*) as qtd FROM usuarios")
    if cursor.fetchone()['qtd'] == 0:
        cursor.execute(
            "INSERT INTO usuarios (usuario, senha, nome) VALUES (?, ?, ?)",
            ('admin', '123456', 'Administrador')
        )
    cursor.execute("SELECT COUNT(*) as qtd FROM categorias")
    if cursor.fetchone()['qtd'] == 0:
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
        return f(*args, **kwargs)
    return decorated

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
    if mes == 1:
        mes_ant, ano_ant = 12, ano - 1
    else:
        mes_ant, ano_ant = mes - 1, ano
    cursor.execute(
        "SELECT id, fechado FROM meses WHERE mes = ? AND ano = ?", (mes_ant, ano_ant)
    )
    mes_anterior = cursor.fetchone()
    if mes_anterior and mes_anterior['fechado']:
        mid = mes_anterior['id']
        cursor.execute(
            "SELECT COALESCE(SUM(CASE WHEN tipo = 'entrada' THEN valor ELSE 0 END), 0) - "
            "COALESCE(SUM(CASE WHEN tipo = 'saida' THEN valor ELSE 0 END), 0) as saldo "
            "FROM lancamentos WHERE mes_id = ?", (mid,)
        )
        saldo_inicial = cursor.fetchone()['saldo']

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
        return redirect(url_for('index'))
    if request.method == 'POST':
        usuario = request.form.get('usuario', '').strip()
        senha = request.form.get('senha', '').strip()
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM usuarios WHERE usuario = ? AND senha = ?", (usuario, senha))
        user = cursor.fetchone()
        conn.close()
        if user:
            session['logado'] = True
            session['usuario'] = user['usuario']
            session['user_id'] = user['id']
            session['user_nome'] = user['nome']
            flash('Login realizado com sucesso!', 'success')
            return redirect(url_for('index'))
        flash('Usuário ou senha inválidos.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Você saiu do sistema.', 'info')
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    conn = get_db()
    cursor = conn.cursor()

    mes_id, saldo_inicial = get_or_create_mes_atual()
    if mes_id is None:
        conn.close()
        flash('Mês atual já está fechado. Inicie um novo mês.', 'warning')
        return redirect(url_for('relatorio'))

    cursor.execute("SELECT mes, ano FROM meses WHERE id = ?", (mes_id,))
    mes_atual = cursor.fetchone()

    tipo_filtro = request.args.get('tipo', '')

    sql = ("SELECT l.*, m.mes, m.ano FROM lancamentos l "
           "JOIN meses m ON l.mes_id = m.id WHERE 1=1")
    params = []
    if tipo_filtro:
        sql += " AND l.tipo = ?"
        params.append(tipo_filtro)
    sql += " ORDER BY l.data DESC, l.id DESC"
    cursor.execute(sql, params)
    lancamentos = cursor.fetchall()

    cursor.execute(
        "SELECT COALESCE(SUM(CASE WHEN tipo = 'entrada' THEN valor ELSE 0 END), 0) as total_entradas, "
        "COALESCE(SUM(CASE WHEN tipo = 'saida' THEN valor ELSE 0 END), 0) as total_saidas "
        "FROM lancamentos"
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
    mes_id, _ = get_or_create_mes_atual()
    if mes_id is None:
        flash('Mês atual está fechado. Inicie um novo mês.', 'warning')
        return redirect(url_for('relatorio'))

    descricao = request.form.get('descricao', '').strip()
    tipo = request.form.get('tipo')
    valor_str = request.form.get('valor', '0').strip()
    data_br = request.form.get('data', date.today().strftime('%d/%m/%Y'))
    observacao = request.form.get('observacao', '').strip()

    if not descricao:
        flash('Descrição é obrigatória.', 'danger')
        return redirect(url_for('index'))
    if tipo not in ('entrada', 'saida'):
        flash('Tipo inválido.', 'danger')
        return redirect(url_for('index'))
    try:
        valor = float(valor_str.replace(',', '.'))
        if valor <= 0:
            raise ValueError
    except ValueError:
        flash('Valor inválido.', 'danger')
        return redirect(url_for('index'))

    data = parse_data_br(data_br)

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO lancamentos (mes_id, descricao, tipo, valor, data, observacao) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (mes_id, descricao, tipo, valor, data, observacao)
    )
    conn.commit()
    conn.close()
    flash('Lançamento adicionado com sucesso!', 'success')
    return redirect(url_for('index'))

@app.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar(id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT l.*, c.nome as categoria_nome FROM lancamentos l LEFT JOIN categorias c ON l.categoria_id = c.id WHERE l.id = ?",
        (id,)
    )
    lancamento = cursor.fetchone()
    if not lancamento:
        conn.close()
        flash('Lançamento não encontrado.', 'danger')
        return redirect(url_for('index'))

    cursor.execute("SELECT * FROM categorias ORDER BY tipo, nome")
    categorias = cursor.fetchall()
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
        flash('Lançamento atualizado com sucesso!', 'success')
        return redirect(url_for('index'))

    return render_template('editar.html', lancamento=lancamento, categorias=categorias)

@app.route('/excluir/<int:id>')
@login_required
def excluir(id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM lancamentos WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    flash('Lançamento excluído.', 'info')
    return redirect(url_for('index'))

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
    mes_id, _ = get_or_create_mes_atual()
    if mes_id is None:
        flash('Não há mês aberto para finalizar.', 'warning')
        return redirect(url_for('relatorio'))
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE meses SET fechado = 1, fechado_em = datetime('now', 'localtime') WHERE id = ?",
        (mes_id,)
    )
    conn.commit()
    conn.close()
    flash('Mês finalizado com sucesso!', 'success')
    return redirect(url_for('relatorio'))

@app.route('/novo-mes')
@login_required
def novo_mes():
    mes_id, _ = get_or_create_mes_atual()
    if mes_id is not None:
        flash('Já existe um mês aberto.', 'info')
        return redirect(url_for('index'))
    novo_id, _ = get_or_create_mes_atual()
    flash('Novo mês iniciado!', 'success')
    return redirect(url_for('index'))

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
    conn.close()
    return render_template('relatorio.html',
                         dados_meses=dados_meses,
                         total_geral_entradas=total_geral_entradas,
                         total_geral_saidas=total_geral_saidas,
                         saldo_geral=saldo_geral,
                         tem_mes_aberto=tem_mes_aberto)

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
        "SELECT l.*, c.nome as categoria_nome FROM lancamentos l LEFT JOIN categorias c ON l.categoria_id = c.id WHERE l.mes_id = ? ORDER BY l.data DESC, l.id DESC",
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
        "SELECT l.data, l.descricao, l.tipo, l.valor, c.nome as categoria, l.observacao "
        "FROM lancamentos l LEFT JOIN categorias c ON l.categoria_id = c.id WHERE l.mes_id = ? ORDER BY l.data",
        (mes_id,)
    )
    lancamentos = cursor.fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Data', 'Descrição', 'Tipo', 'Valor', 'Categoria', 'Observação'])
    for l in lancamentos:
        writer.writerow([l['data'], l['descricao'],
                        'Entrada' if l['tipo'] == 'entrada' else 'Saída',
                        f"{l['valor']:.2f}", l['categoria'] or '', l['observacao'] or ''])

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
        "SELECT l.*, c.nome as categoria_nome FROM lancamentos l LEFT JOIN categorias c ON l.categoria_id = c.id "
        "WHERE l.mes_id = ? ORDER BY l.data DESC, l.id DESC", (mes_id,)
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
@login_required
def backup():
    if not os.path.exists(DB_PATH):
        flash('Banco de dados não encontrado.', 'danger')
        return redirect(url_for('relatorio'))
    return send_file(DB_PATH, as_attachment=True, download_name=f'contabil_backup_{date.today().isoformat()}.db')

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)
