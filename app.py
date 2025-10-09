import os
import locale
import csv
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory
from PIL import Image, ImageDraw, ImageFont
from textwrap import wrap
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

# Carrega as variáveis de ambiente (como a DATABASE_URL) do arquivo .env
load_dotenv()

# --- CONFIGURAÇÕES GERAIS ---
try:
    locale.setlocale(locale.LC_TIME, 'pt_BR.UTF-8')
except locale.Error:
    print("Locale pt_BR.UTF-8 not supported, continuing with default locale.")

app = Flask(__name__)
app.secret_key = 'minha_chave_secreta_muito_segura_12345'
app.config['CERTIFICATE_FOLDER'] = 'certificates'
ADMIN_PASSWORD = "admin" 

# --- FUNÇÃO DE CONEXÃO COM O BANCO DE DADOS ---
def get_db_connection():
    """Cria uma conexão com o banco de dados Supabase."""
    conn = psycopg2.connect(os.environ.get('DATABASE_URL'))
    return conn

# --- FUNÇÃO AUXILIAR PARA LIMPAR CPFS ---
def sanitize_cpf(cpf_string):
    """Remove pontos, hífens e espaços de uma string de CPF."""
    return str(cpf_string).replace('.', '').replace('-', '').replace(' ', '')

# ===============================================
# ROTAS PARA COOPERADOS
# ===============================================
@app.route('/')
def index(): return render_template('login.html')

@app.route('/inscrever/<int:id>', methods=['POST'])
def inscrever_treinamento(id):
    if not session.get('logged_in'): return redirect(url_for('index'))
    
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            'INSERT INTO inscricoes (id_treinamento, cpf_cooperado) VALUES (%s, %s)',
            (id, session.get('cpf'))
        )
        conn.commit()
    except psycopg2.IntegrityError:
        # Ignora o erro se o usuário tentar se inscrever duas vezes (por exemplo, clicando rápido)
        conn.rollback()
    finally:
        cur.close()
        conn.close()
        
    return redirect(url_for('dashboard'))

@app.route('/login', methods=['POST'])
def login():
    cpf_digitado = sanitize_cpf(request.form['cpf'])
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT nome, cpf, perfil_completo FROM cooperados WHERE cpf = %s', (cpf_digitado,))
    cooperado = cur.fetchone()
    cur.close()
    conn.close()
    
    if cooperado:
        nome, cpf, perfil_completo = cooperado
        session['logged_in'], session['nome'], session['cpf'], session['is_admin'] = True, nome, cpf, False
        if not perfil_completo: return redirect(url_for('completar_perfil_page'))
        else: return redirect(url_for('dashboard'))
    return "<h1>Acesso Negado.</h1>"

@app.route('/completar-perfil', methods=['GET'])
def completar_perfil_page():
    if not session.get('logged_in'): return redirect(url_for('index'))
    return render_template('completar_perfil.html', nome=session.get('nome'))

@app.route('/completar-perfil', methods=['POST'])
def completar_perfil_submit():
    if not session.get('logged_in'): return redirect(url_for('index'))
    
    cpf_logado = session.get('cpf')
    email = request.form['email']
    telefone = request.form['telefone']
    numero_conselho = request.form['numero_conselho']
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        'UPDATE cooperados SET email = %s, telefone = %s, numero_conselho = %s, perfil_completo = TRUE WHERE cpf = %s',
        (email, telefone, numero_conselho, cpf_logado)
    )
    conn.commit()
    cur.close()
    conn.close()
    
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'): return redirect(url_for('index'))
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("""
        SELECT * FROM treinamentos 
        WHERE status = 'ativo' OR (status = 'encerrado' AND data_hora > NOW() - INTERVAL '30 days')
        ORDER BY data_hora DESC
    """)
    treinamentos = cur.fetchall()
    
    cur.execute('SELECT id_treinamento FROM presencas WHERE cpf_cooperado = %s', (session.get('cpf'),))
    presencas_confirmadas = {row['id_treinamento'] for row in cur.fetchall()}
    
    cur.execute('SELECT id_treinamento FROM inscricoes WHERE cpf_cooperado = %s', (session.get('cpf'),))
    inscricoes_feitas = {row['id_treinamento'] for row in cur.fetchall()}
    
    cur.close()
    conn.close()

    # Pega a data e hora atuais UMA VEZ para otimização
    agora = datetime.now()

    for t in treinamentos:
        t['data_formatada'] = t['data_hora'].strftime('%d/%m/%Y às %H:%M')
        t['status_cooperado'] = 'futuro'
        t['is_finalizado'] = (t['status'] == 'encerrado')
        t['inscrito'] = t['id'] in inscricoes_feitas
        
        # --- NOVA LÓGICA AQUI ---
        # Adiciona a etiqueta que verifica se o treinamento já passou
        t['ja_passou'] = t['data_hora'] < agora

        if t['id'] in presencas_confirmadas:
            t['status_cooperado'] = 'confirmada'
        elif t['status'] == 'encerrado':
            t['status_cooperado'] = 'faltou'
            
    return render_template('dashboard.html', nome=session.get('nome'), treinamentos=treinamentos)

@app.route('/treinamento/<int:id>')
def detalhe_treinamento(id):
    if not session.get('logged_in'): return redirect(url_for('index'))
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute('SELECT * FROM treinamentos WHERE id = %s', (id,))
    treinamento = cur.fetchone()
    
    cur.execute('SELECT 1 FROM inscricoes WHERE id_treinamento = %s AND cpf_cooperado = %s', (id, session.get('cpf')))
    inscrito = cur.fetchone() is not None
    
    cur.execute('SELECT 1 FROM presencas WHERE id_treinamento = %s AND cpf_cooperado = %s', (id, session.get('cpf')))
    presenca_ja_confirmada = cur.fetchone() is not None
    
    cur.close()
    conn.close()

    if treinamento:
        treinamento['data_formatada'] = treinamento['data_hora'].strftime('%d/%m/%Y às %H:%M')
        mostrar_botao = inscrito and (treinamento['data_hora'] - timedelta(minutes=5)) <= datetime.now()
        
        # --- MUDANÇA PRINCIPAL AQUI ---
        # Enviamos a data em formato ISO para o JavaScript usar
        training_iso_time = treinamento['data_hora'].isoformat()
        
        return render_template(
            'treinamento_detalhe.html', 
            treinamento=treinamento, 
            mostrar_botao=mostrar_botao, 
            presenca_ja_confirmada=presenca_ja_confirmada,
            data_formatada=treinamento['data_formatada'],
            training_iso_time=training_iso_time # <-- Nova variável
        )
    else: 
        return "<h1>Treinamento não encontrado!</h1>", 404

@app.route('/confirmar-presenca/<int:id>', methods=['POST'])
def confirmar_presenca(id):
    if not session.get('logged_in'): return redirect(url_for('index'))
    
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            'INSERT INTO presencas (id_treinamento, cpf_cooperado) VALUES (%s, %s)',
            (id, session.get('cpf'))
        )
        conn.commit()
    except psycopg2.IntegrityError:
        conn.rollback()
    finally:
        cur.close()
        conn.close()
        
    return redirect(url_for('detalhe_treinamento', id=id))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# ===============================================
# ROTAS PARA O ADMINISTRADOR
# ===============================================
@app.route('/admin')
def admin_login_page(): return render_template('admin_login.html')

@app.route('/admin/login', methods=['POST'])
def admin_login_submit():
    if request.form['password'] == ADMIN_PASSWORD:
        session['logged_in'], session['is_admin'] = True, True
        return redirect(url_for('admin_dashboard'))
    else: return "<h1>Senha incorreta!</h1>"

# --- NOVA ROTA PARA O RELATÓRIO DE INSCRITOS ---
@app.route('/admin/report/inscritos')
def report_inscritos():
    if not session.get('logged_in') or not session.get('is_admin'):
        return redirect(url_for('admin_login_page'))

    # Pega o ID do treinamento selecionado na lista suspensa
    training_id = request.args.get('training_id', type=int)
    if not training_id:
        return "<h1>Erro: Nenhum treinamento selecionado.</h1>"

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # 1. Busca os detalhes do treinamento selecionado
    cur.execute('SELECT * FROM treinamentos WHERE id = %s', (training_id,))
    treinamento = cur.fetchone()

    if not treinamento:
        cur.close()
        conn.close()
        return "<h1>Erro: Treinamento não encontrado.</h1>"

    # 2. Busca todos os cooperados que se inscreveram neste treinamento
    cur.execute("""
        SELECT c.nome, c.cpf, c.email, c.telefone
        FROM inscricoes i
        JOIN cooperados c ON i.cpf_cooperado = c.cpf
        WHERE i.id_treinamento = %s
        ORDER BY c.nome
    """, (training_id,))
    inscritos = cur.fetchall()

    cur.close()
    conn.close()

    return render_template('report_inscritos.html', treinamento=treinamento, inscritos=inscritos)

# Rota para MOSTRAR a página do formulário
@app.route('/admin/cooperados/add', methods=['GET'])
def add_cooperado_page():
    if not session.get('logged_in') or not session.get('is_admin'):
        return redirect(url_for('admin_login_page'))
    return render_template('add_cooperado.html')

# Rota para PROCESSAR os dados do formulário
@app.route('/admin/cooperados/add', methods=['POST'])
def add_cooperado_submit():
    if not session.get('logged_in') or not session.get('is_admin'):
        return redirect(url_for('admin_login_page'))

    nome = request.form['nome']
    cpf = sanitize_cpf(request.form['cpf']) # Limpa o CPF

    conn = get_db_connection()
    cur = conn.cursor()

    # 1. Verifica se o CPF já existe para evitar duplicatas
    cur.execute('SELECT 1 FROM cooperados WHERE cpf = %s', (cpf,))
    if cur.fetchone():
        flash(f'Erro: O CPF {cpf} já está cadastrado no sistema.', 'danger')
        cur.close()
        conn.close()
        return redirect(url_for('view_cooperados'))

    # 2. Se não existe, insere o novo cooperado
    cur.execute('INSERT INTO cooperados (nome, cpf) VALUES (%s, %s)', (nome, cpf))
    conn.commit()
    cur.close()
    conn.close()

    flash(f'Cooperado "{nome}" adicionado com sucesso!', 'success')
    return redirect(url_for('view_cooperados'))

@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('logged_in') or not session.get('is_admin'): return redirect(url_for('admin_login_page'))
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('SELECT * FROM treinamentos ORDER BY data_hora DESC')
    treinamentos = cur.fetchall()
    cur.close()
    conn.close()

    # --- CORREÇÃO PRINCIPAL AQUI ---
    # Adicionamos este laço para formatar a data de cada treinamento
    for t in treinamentos:
        t['data_hora'] = t['data_hora'].strftime('%d/%m/%Y %H:%M')
        
    return render_template('admin_dashboard.html', treinamentos=treinamentos)

# --- NOVA ROTA PARA VER OS DETALHES DE UM COOPERADO ---
@app.route('/admin/cooperado/<cpf>')
def detalhe_cooperado(cpf):
    if not session.get('logged_in') or not session.get('is_admin'):
        return redirect(url_for('admin_login_page'))

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # 1. Busca os dados do perfil do cooperado
    cur.execute('SELECT * FROM cooperados WHERE cpf = %s', (cpf,))
    cooperado = cur.fetchone()

    if not cooperado:
        cur.close()
        conn.close()
        return "<h1>Cooperado não encontrado.</h1>"

    # 2. Busca o histórico de treinamentos do cooperado
    # Usamos um LEFT JOIN para pegar todos os treinamentos encerrados e verificar se o cooperado participou
    cur.execute("""
        SELECT 
            t.titulo, 
            t.data_hora,
            -- Verifica se existe uma entrada correspondente na tabela de presenças
            (p.cpf_cooperado IS NOT NULL) AS presenca_confirmada
        FROM treinamentos t
        LEFT JOIN presencas p ON t.id = p.id_treinamento AND p.cpf_cooperado = %s
        WHERE t.status = 'encerrado'
        ORDER BY t.data_hora DESC
    """, (cpf,))
    historico = cur.fetchall()

    cur.close()
    conn.close()

    return render_template('detalhe_cooperado.html', cooperado=cooperado, historico=historico)

@app.route('/admin/import-cooperados', methods=['POST'])
def import_cooperados():
    if not session.get('logged_in') or not session.get('is_admin'): return redirect(url_for('admin_login_page'))
    if 'csv_file' not in request.files or request.files['csv_file'].filename == '':
        flash('Nenhum arquivo selecionado.', 'danger')
        return redirect(url_for('admin_dashboard'))
    file = request.files['csv_file']
    if not file.filename.endswith('.csv'):
        flash('Formato de arquivo inválido. Por favor, envie um arquivo .csv.', 'danger')
        return redirect(url_for('admin_dashboard'))

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT cpf FROM cooperados')
        cpfs_existentes = {row[0] for row in cur.fetchall()}
        
        try:
            stream = file.stream.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            file.stream.seek(0)
            stream = file.stream.read().decode("latin-1")
        
        lines = stream.splitlines()
        novos_adicionados = 0
        duplicados_ignorados = 0
        erros_importacao = []
        
        for i, line in enumerate(lines):
            if not line.strip(): continue
            row = line.split(';')
            if len(row) == 2 and row[0].strip() and row[1].strip():
                nome_novo = row[0].strip()
                cpf_novo = sanitize_cpf(row[1].strip())
                if cpf_novo not in cpfs_existentes:
                    cur.execute('INSERT INTO cooperados (nome, cpf) VALUES (%s, %s)', (nome_novo, cpf_novo))
                    cpfs_existentes.add(cpf_novo)
                    novos_adicionados += 1
                else:
                    duplicados_ignorados += 1
            else:
                erros_importacao.append(f"Linha {i+1}")
        
        conn.commit()
        cur.close()
        conn.close()
        
        if novos_adicionados > 0: flash(f'{novos_adicionados} novos cooperados foram adicionados com sucesso.', 'success')
        if duplicados_ignorados > 0: flash(f'{duplicados_ignorados} cooperados duplicados foram ignorados.', 'info')
        if erros_importacao: flash(f'{len(erros_importacao)} linhas com formato inválido foram ignoradas: {", ".join(erros_importacao[:5])}', 'danger')

    except Exception as e:
        flash(f'Ocorreu um erro ao processar o arquivo: {e}', 'danger')
    
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/cooperados')
def view_cooperados():
    if not session.get('logged_in') or not session.get('is_admin'): return redirect(url_for('admin_login_page'))
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('SELECT * FROM cooperados ORDER BY nome')
    cooperados = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('view_cooperados.html', cooperados=cooperados)

@app.route('/admin/toggle-presenca/<int:id>', methods=['POST'])
def toggle_presenca(id):
    if not session.get('logged_in') or not session.get('is_admin'): return redirect(url_for('admin_login_page'))
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('UPDATE treinamentos SET presenca_liberada = NOT presenca_liberada WHERE id = %s', (id,))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/encerrar/<int:id>', methods=['POST'])
def encerrar_treinamento(id):
    if not session.get('logged_in') or not session.get('is_admin'): return redirect(url_for('admin_login_page'))
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE treinamentos SET status = 'encerrado', presenca_liberada = FALSE WHERE id = %s", (id,))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/presenca/<int:id>')
def ver_lista_presenca(id):
    if not session.get('logged_in') or not session.get('is_admin'): return redirect(url_for('admin_login_page'))
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('SELECT * FROM treinamentos WHERE id = %s', (id,))
    treinamento_atual = cur.fetchone()
    cur.execute('''
        SELECT c.nome, c.cpf
        FROM presencas p
        JOIN cooperados c ON p.cpf_cooperado = c.cpf
        WHERE p.id_treinamento = %s
        ORDER BY c.nome
    ''', (id,))
    participantes = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('lista_presenca.html', treinamento=treinamento_atual, participantes=participantes)

@app.route('/admin/add', methods=['GET'])
def add_training_page():
    if not session.get('logged_in') or not session.get('is_admin'): return redirect(url_for('admin_login_page'))
    return render_template('add_training.html')

@app.route('/admin/add', methods=['POST'])
def add_training_submit():
    if not session.get('logged_in') or not session.get('is_admin'): return redirect(url_for('admin_login_page'))
    data_hora_str = request.form['data_hora']
    data_hora_obj = datetime.strptime(data_hora_str, '%d/%m/%Y %H:%M')
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        'INSERT INTO treinamentos (titulo, data_hora, descricao, link_meet, instrutor, carga_horaria) VALUES (%s, %s, %s, %s, %s, %s)',
        (request.form['titulo'], data_hora_obj, request.form['descricao'], request.form['link_meet'], request.form['instrutor'], request.form['carga_horaria'])
    )
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete/<int:id>')
def delete_training(id):
    if not session.get('logged_in') or not session.get('is_admin'): return redirect(url_for('admin_login_page'))
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('DELETE FROM treinamentos WHERE id = %s', (id,))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/edit/<int:id>', methods=['GET'])
def edit_training_page(id):
    if not session.get('logged_in') or not session.get('is_admin'): return redirect(url_for('admin_login_page'))
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('SELECT * FROM treinamentos WHERE id = %s', (id,))
    treinamento = cur.fetchone()
    cur.close()
    conn.close()
    if treinamento:
        treinamento['data_hora_input'] = treinamento['data_hora'].strftime('%d/%m/%Y %H:%M')
        return render_template('edit_training.html', treinamento=treinamento)
    else: return "<h1>Treinamento não encontrado!</h1>"

@app.route('/admin/edit/<int:id>', methods=['POST'])
def edit_training_submit(id):
    if not session.get('logged_in') or not session.get('is_admin'): return redirect(url_for('admin_login_page'))
    data_hora_str = request.form['data_hora']
    data_hora_obj = datetime.strptime(data_hora_str, '%d/%m/%Y %H:%M')
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        'UPDATE treinamentos SET titulo=%s, data_hora=%s, descricao=%s, link_meet=%s, instrutor=%s, carga_horaria=%s WHERE id=%s',
        (request.form['titulo'], data_hora_obj, request.form['descricao'], request.form['link_meet'], request.form['instrutor'], request.form['carga_horaria'], id)
    )
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/generate-certificate/<int:training_id>/<cpf>')
def generate_certificate(training_id, cpf):
    if not session.get('logged_in') or not session.get('is_admin'): return redirect(url_for('admin_login_page'))
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('SELECT * FROM treinamentos WHERE id = %s', (training_id,))
    treinamento = cur.fetchone()
    cur.execute('SELECT * FROM cooperados WHERE cpf = %s', (cpf,))
    participante = cur.fetchone()
    cur.close()
    conn.close()

    if not treinamento or not participante: return "<h1>Dados não encontrados para gerar o certificado.</h1>"

    texto_principal = """Certificamos, para os devidos fins, que {NOME_COOPERADO},
portador(a) do CPF {CPF_COOPERADO}, participou com êxito do treinamento de
'{NOME_TREINAMENTO}', realizado em {DATA_TREINAMENTO},
totalizando uma carga horária de {CARGA_HORARIA} horas."""

    data_formatada = treinamento['data_hora'].strftime('%d/%m/%Y')
    texto_final = texto_principal.format(
        NOME_COOPERADO=participante['nome'],
        CPF_COOPERADO=participante['cpf'],
        NOME_TREINAMENTO=treinamento['titulo'],
        DATA_TREINAMENTO=data_formatada,
        CARGA_HORARIA=treinamento['carga_horaria']
    )

    try:
        base_path = app.root_path
        font_titulo_path = os.path.join(base_path, 'static', 'Autography.ttf')
        font_corpo_path = os.path.join(base_path, 'static', 'arial.ttf')
        background_path = os.path.join(base_path, 'static', 'certificate_assets', 'fundo_certificado.png')

        font_titulo = ImageFont.truetype(font_titulo_path, 140)
        font_corpo = ImageFont.truetype(font_corpo_path, 70)
        font_data = ImageFont.truetype(font_corpo_path, 50)
    except IOError as e:
        return f"<h1>Erro ao carregar fonte ou imagem: {e}. Verifique se o arquivo está na pasta 'static' e se o nome está correto.</h1>"

    if not os.path.exists(background_path):
        return "<h1>Erro: Imagem de fundo não encontrada.</h1>"

    img = Image.open(background_path).convert('RGB')
    largura, altura = img.size
    draw = ImageDraw.Draw(img)
    
    titulo_bbox = draw.textbbox((0, 0), participante['nome'], font=font_titulo)
    titulo_x = (largura - (titulo_bbox[2] - titulo_bbox[0])) / 2
    draw.text((titulo_x, 1150), participante['nome'], font=font_titulo, fill='#00a5b6')

    y_text = 1350
    lines = wrap(texto_final, width=60)
    for line in lines:
        line_bbox = draw.textbbox((0, 0), line, font=font_corpo)
        line_x = (largura - (line_bbox[2] - line_bbox[0])) / 2
        draw.text((line_x, y_text), line, font=font_corpo, fill='black')
        y_text += 90

    data_final = f"Salvador, {data_formatada}"
    data_bbox = draw.textbbox((0, 0), data_final, font=font_data)
    data_x = largura - (data_bbox[2] - data_bbox[0]) - 250
    draw.text((data_x, altura - 400), data_final, font=font_data, fill='black')

    temp_dir = '/tmp'
    filename = f"certificado_{training_id}_{cpf}.pdf"
    filepath = os.path.join(temp_dir, filename)
    
    img.save(filepath, "PDF", resolution=150.0)

    return send_from_directory(temp_dir, filename, as_attachment=True)

# --- NOVA ROTA PARA O COOPERADO GERAR SEU PRÓPRIO CERTIFICADO ---
@app.route('/cooperado/generate-certificate/<int:training_id>')
def generate_certificate_cooperado(training_id):
    # 1. Segurança: O usuário está logado?
    if not session.get('logged_in'):
        return redirect(url_for('index'))

    cpf_cooperado = session.get('cpf')

    # 2. Segurança: O cooperado REALMENTE confirmou presença neste treinamento?
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('SELECT 1 FROM presencas WHERE id_treinamento = %s AND cpf_cooperado = %s', (training_id, cpf_cooperado))
    presenca_confirmada = cur.fetchone() is not None
    
    if not presenca_confirmada:
        cur.close()
        conn.close()
        return "<h1>Acesso negado: Você não confirmou presença neste treinamento.</h1>"

    # 3. Se a segurança passou, busca os dados para o certificado
    cur.execute('SELECT * FROM treinamentos WHERE id = %s', (training_id,))
    treinamento = cur.fetchone()
    cur.execute('SELECT * FROM cooperados WHERE cpf = %s', (cpf_cooperado,))
    participante = cur.fetchone()
    cur.close()
    conn.close()

    if not treinamento or not participante:
        return "<h1>Dados não encontrados para gerar o certificado.</h1>"

    # O resto da lógica de geração é exatamente a mesma da função do admin
    texto_principal = """Certificamos, para os devidos fins, que {NOME_COOPERADO},
portador(a) do CPF {CPF_COOPERADO}, participou com êxito do treinamento de
'{NOME_TREINAMENTO}', realizado em {DATA_TREINAMENTO},
totalizando uma carga horária de {CARGA_HORARIA} horas."""

    data_formatada = treinamento['data_hora'].strftime('%d/%m/%Y')
    texto_final = texto_principal.format(
        NOME_COOPERADO=participante['nome'],
        CPF_COOPERADO=participante['cpf'],
        NOME_TREINAMENTO=treinamento['titulo'],
        DATA_TREINAMENTO=data_formatada,
        CARGA_HORARIA=treinamento['carga_horaria']
    )

    try:
        base_path = app.root_path
        font_titulo_path = os.path.join(base_path, 'static', 'Autography.ttf')
        font_corpo_path = os.path.join(base_path, 'static', 'arial.ttf')
        background_path = os.path.join(base_path, 'static', 'certificate_assets', 'fundo_certificado.png')

        font_titulo = ImageFont.truetype(font_titulo_path, 140)
        font_corpo = ImageFont.truetype(font_corpo_path, 70)
        font_data = ImageFont.truetype(font_corpo_path, 50)
    except IOError as e:
        return f"<h1>Erro ao carregar fonte ou imagem: {e}.</h1>"

    if not os.path.exists(background_path):
        return "<h1>Erro: Imagem de fundo não encontrada.</h1>"

    img = Image.open(background_path).convert('RGB')
    largura, altura = img.size
    draw = ImageDraw.Draw(img)
    
    titulo_bbox = draw.textbbox((0, 0), participante['nome'], font=font_titulo)
    titulo_x = (largura - (titulo_bbox[2] - titulo_bbox[0])) / 2
    draw.text((titulo_x, 1150), participante['nome'], font=font_titulo, fill='#00a5b6')

    y_text = 1350
    lines = wrap(texto_final, width=60)
    for line in lines:
        line_bbox = draw.textbbox((0, 0), line, font=font_corpo)
        line_x = (largura - (line_bbox[2] - line_bbox[0])) / 2
        draw.text((line_x, y_text), line, font=font_corpo, fill='black')
        y_text += 90

    data_final = f"Salvador, {data_formatada}"
    data_bbox = draw.textbbox((0, 0), data_final, font=font_data)
    data_x = largura - (data_bbox[2] - data_bbox[0]) - 250
    draw.text((data_x, altura - 400), data_final, font=font_data, fill='black')

    temp_dir = '/tmp'
    filename = f"certificado_{training_id}_{cpf_cooperado}.pdf"
    filepath = os.path.join(temp_dir, filename)
    
    img.save(filepath, "PDF", resolution=150.0)

    return send_from_directory(temp_dir, filename, as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)