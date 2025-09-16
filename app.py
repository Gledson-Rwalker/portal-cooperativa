from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory
import csv
import locale
import os
from PIL import Image, ImageDraw, ImageFont
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, flash

# --- CONFIGURAÇÕES GERAIS ---
# Tenta configurar o local para Português do Brasil, mas não quebra se não conseguir
try:
    locale.setlocale(locale.LC_TIME, 'pt_BR.UTF-8')
except locale.Error:
    print("Locale pt_BR.UTF-8 not supported, continuing with default locale.")
app = Flask(__name__)
app.secret_key = 'minha_chave_secreta_muito_segura_12345'
app.config['CERTIFICATE_FOLDER'] = 'certificates'
ADMIN_PASSWORD = "admin"

# --- TEXTO PADRÃO DO CERTIFICADO ---
# Modifique este texto como desejar. Mantenha os {PLACEHOLDERS} intactos.
CERTIFICATE_TEXT_TEMPLATE = """Certificamos, para os devidos fins, que {NOME_COOPERADO},
portador(a) do CPF {CPF_COOPERADO}, participou com êxito do treinamento de
'{NOME_TREINAMENTO}', realizado em {DATA_TREINAMENTO},
totalizando uma carga horária de {CARGA_HORARIA} horas."""

# --- FUNÇÕES DE DADOS ---
# (As funções carregar/salvar para cooperados, treinamentos e presenças continuam as mesmas)
def carregar_treinamentos():
    try:
        with open('trainings.csv', mode='r', encoding='utf-8') as f: return list(csv.DictReader(f))
    except FileNotFoundError: return []

def sanitize_cpf(cpf_string):
    """Remove pontos, hífens e espaços de uma string de CPF."""
    return cpf_string.replace('.', '').replace('-', '').replace(' ', '')

def salvar_treinamentos(treinamentos):
    fieldnames = ['id', 'titulo', 'data_hora', 'descricao', 'link_meet', 'presenca_liberada', 'status', 'instrutor', 'carga_horaria']
    with open('trainings.csv', mode='w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(treinamentos)

def carregar_cooperados():
    try:
        with open('cooperados.csv', mode='r', encoding='utf-8') as f: return list(csv.DictReader(f))
    except FileNotFoundError: return []

def salvar_cooperados(cooperados):
    fieldnames = ['nome', 'cpf', 'email', 'telefone', 'numero_conselho', 'perfil_completo']
    with open('cooperados.csv', mode='w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(cooperados)

def carregar_presencas():
    try:
        with open('presencas.csv', mode='r', encoding='utf-8') as f: return list(csv.DictReader(f))
    except FileNotFoundError: return []

# --- NOVA FUNÇÃO AUXILIAR PARA DESENHAR TEXTO COM ESPAÇAMENTO ---
def draw_text_with_tracking(draw, position, text, font, fill, tracking=0):
    """
    Desenha um texto caractere por caractere para simular o espaçamento (tracking).
    """
    x, y = position
    for char in text:
        draw.text((x, y), char, font=font, fill=fill)
        char_width = draw.textbbox((0, 0), char, font=font)[2]
        x += char_width + tracking # Move para o próximo caractere + espaçamento extra

# (Todas as rotas de COOPERADO e as rotas de ADMIN de antes continuam as mesmas)
# ... (código do login, dashboard, etc., omitido para clareza, mas está no bloco final)

# ===============================================
# ROTAS PARA COOPERADOS
# ===============================================
@app.route('/')
def index(): return render_template('login.html')
@app.route('/login', methods=['POST'])
def login():
    # --- MUDANÇA AQUI ---
    # Sanitizamos o CPF que o usuário digitou
    cpf_digitado = sanitize_cpf(request.form['cpf'])
    
    cooperados = carregar_cooperados()
    for cooperado in cooperados:
        # --- MUDANÇA AQUI ---
        # Comparamos o CPF limpo digitado com o CPF limpo da base de dados
        if sanitize_cpf(cooperado['cpf']) == cpf_digitado:
            session['logged_in'], session['nome'], session['cpf'], session['is_admin'] = True, cooperado['nome'], cooperado['cpf'], False
            if cooperado['perfil_completo'] != 'sim': return redirect(url_for('completar_perfil_page'))
            else: return redirect(url_for('dashboard'))
            
    return "<h1>Acesso Negado.</h1>"
@app.route('/completar-perfil', methods=['GET'])
def completar_perfil_page():
    if not session.get('logged_in'): return redirect(url_for('index'))
    return render_template('completar_perfil.html', nome=session.get('nome'))
@app.route('/completar-perfil', methods=['POST'])
def completar_perfil_submit():
    if not session.get('logged_in'): return redirect(url_for('index'))
    cooperados = carregar_cooperados()
    for c in cooperados:
        if c['cpf'] == session.get('cpf'):
            c['email'], c['telefone'], c['numero_conselho'], c['perfil_completo'] = request.form['email'], request.form['telefone'], request.form['numero_conselho'], 'sim'
            break
    salvar_cooperados(cooperados)
    return redirect(url_for('dashboard'))
@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'): return redirect(url_for('index'))
    treinamentos = carregar_treinamentos()
    presencas = carregar_presencas()
    cpf_cooperado = session.get('cpf')
    for t in treinamentos:
        try:
            horario_inicio = datetime.strptime(t['data_hora'], '%Y-%m-%d %H:%M')
            t['data_formatada'] = horario_inicio.strftime('%d de %B de %Y às %H:%M')
        except (ValueError, KeyError): t['data_formatada'] = "Data a ser definida"
        presenca_confirmada = any(p for p in presencas if p['id_treinamento'] == t['id'] and p['cpf_cooperado'] == cpf_cooperado)
        if presenca_confirmada: t['status_cooperado'] = 'confirmada'
        elif t.get('status') == 'encerrado': t['status_cooperado'] = 'faltou'
        else: t['status_cooperado'] = 'futuro'
    return render_template('dashboard.html', nome=session.get('nome'), treinamentos=treinamentos)
@app.route('/treinamento/<int:id>')
def detalhe_treinamento(id):
    if not session.get('logged_in'): return redirect(url_for('index'))
    treinamentos = carregar_treinamentos()
    treinamento_encontrado = next((t for t in treinamentos if int(t['id']) == id), None)
    if treinamento_encontrado:
        presencas = carregar_presencas()
        presenca_ja_confirmada = any(p for p in presencas if p['id_treinamento'] == str(id) and p['cpf_cooperado'] == session.get('cpf'))
        agora = datetime.now()
        horario_inicio = datetime.strptime(treinamento_encontrado['data_hora'], '%Y-%m-%d %H:%M')
        mostrar_botao = (horario_inicio - timedelta(minutes=15)) <= agora
        data_formatada = horario_inicio.strftime('%d de %B de %Y às %H:%M')
        return render_template('treinamento_detalhe.html', treinamento=treinamento_encontrado, mostrar_botao=mostrar_botao, data_formatada=data_formatada, presenca_ja_confirmada=presenca_ja_confirmada)
    else: return "<h1>Treinamento não encontrado!</h1>", 404
@app.route('/confirmar-presenca/<int:id>', methods=['POST'])
def confirmar_presenca(id):
    if not session.get('logged_in'): return redirect(url_for('index'))
    cooperados = carregar_cooperados()
    cooperado_logado = next((c for c in cooperados if c['cpf'] == session.get('cpf')), None)
    if cooperado_logado:
        nova_presenca = {'id_treinamento': id, 'cpf_cooperado': cooperado_logado['cpf'], 'nome_cooperado': cooperado_logado['nome'], 'email_cooperado': cooperado_logado['email'], 'telefone_cooperado': cooperado_logado['telefone'], 'data_hora_registro': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        fieldnames = ['id_treinamento', 'cpf_cooperado', 'nome_cooperado', 'email_cooperado', 'telefone_cooperado', 'data_hora_registro']
        file_exists = os.path.isfile('presencas.csv')
        with open('presencas.csv', mode='a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists or os.path.getsize('presencas.csv') == 0: writer.writeheader()
            writer.writerow(nova_presenca)
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
@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('logged_in') or not session.get('is_admin'): return redirect(url_for('admin_login_page'))
    treinamentos = carregar_treinamentos()
    return render_template('admin_dashboard.html', treinamentos=treinamentos)
# --- NOVA ROTA PARA VISUALIZAR COOPERADOS ---
@app.route('/admin/cooperados')
def view_cooperados():
    if not session.get('logged_in') or not session.get('is_admin'):
        return redirect(url_for('admin_login_page'))

    # Carrega todos os cooperados do arquivo CSV
    cooperados = carregar_cooperados()
    
    # Envia a lista de cooperados para a nova página HTML
    return render_template('view_cooperados.html', cooperados=cooperados)
# --- ROTA DE IMPORTAÇÃO CORRIGIDA E MAIS ROBUSTA ---
@app.route('/admin/import-cooperados', methods=['POST'])
def import_cooperados():
    if not session.get('logged_in') or not session.get('is_admin'):
        return redirect(url_for('admin_login_page'))

    if 'csv_file' not in request.files or request.files['csv_file'].filename == '':
        flash('Nenhum arquivo selecionado.', 'danger')
        return redirect(url_for('admin_dashboard'))

    file = request.files['csv_file']
    if not file.filename.endswith('.csv'):
        flash('Formato de arquivo inválido. Por favor, envie um arquivo .csv.', 'danger')
        return redirect(url_for('admin_dashboard'))

    try:
        cooperados_existentes = carregar_cooperados()
        cpfs_existentes = {sanitize_cpf(c['cpf']) for c in cooperados_existentes}

        # --- MUDANÇA PRINCIPAL AQUI ---
        # Tentamos ler o arquivo com o padrão universal (UTF-8).
        # Se falhar, tentamos de novo com o padrão comum do Windows/Excel (latin-1).
        try:
            stream = file.stream.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            file.stream.seek(0) # Volta para o início do arquivo para ler de novo
            stream = file.stream.read().decode("latin-1")
        
        lines = stream.splitlines()
        
        novos_adicionados = 0
        duplicados_ignorados = 0
        erros_importacao = []
        
        for i, line in enumerate(lines):
            if not line.strip():
                continue
            row = line.split(';')
            
            if len(row) == 2 and row[0].strip() and row[1].strip():
                nome_novo = row[0].strip()
                cpf_novo = sanitize_cpf(row[1].strip())

                if cpf_novo not in cpfs_existentes:
                    cooperados_existentes.append({
                        'nome': nome_novo,
                        'cpf': cpf_novo,
                        'email': '',
                        'telefone': '',
                        'numero_conselho': '',
                        'perfil_completo': 'nao'
                    })
                    cpfs_existentes.add(cpf_novo)
                    novos_adicionados += 1
                else:
                    duplicados_ignorados += 1
            else:
                erros_importacao.append(f"Linha {i+1}")

        if novos_adicionados > 0:
            salvar_cooperados(cooperados_existentes)
        
        if novos_adicionados > 0:
            flash(f'{novos_adicionados} novos cooperados foram adicionados com sucesso.', 'success')
        if duplicados_ignorados > 0:
            flash(f'{duplicados_ignorados} cooperados duplicados (CPF já existente) foram ignorados.', 'info')
        if erros_importacao:
            erros_str = ", ".join(erros_importacao[:5])
            flash(f'{len(erros_importacao)} linhas com formato inválido ou dados faltando foram ignoradas: {erros_str}', 'danger')

    except Exception as e:
        flash(f'Ocorreu um erro ao processar o arquivo: {e}', 'danger')
    
    return redirect(url_for('admin_dashboard'))
@app.route('/admin/toggle-presenca/<int:id>', methods=['POST'])
def toggle_presenca(id):
    if not session.get('logged_in') or not session.get('is_admin'): return redirect(url_for('admin_login_page'))
    treinamentos = carregar_treinamentos()
    for t in treinamentos:
        if int(t['id']) == id:
            t['presenca_liberada'] = 'sim' if t.get('presenca_liberada') != 'sim' else 'nao'
            break
    salvar_treinamentos(treinamentos)
    return redirect(url_for('admin_dashboard'))
@app.route('/admin/encerrar/<int:id>', methods=['POST'])
def encerrar_treinamento(id):
    if not session.get('logged_in') or not session.get('is_admin'): return redirect(url_for('admin_login_page'))
    treinamentos = carregar_treinamentos()
    for t in treinamentos:
        if int(t['id']) == id:
            t['status'], t['presenca_liberada'] = 'encerrado', 'nao'
            break
    salvar_treinamentos(treinamentos)
    return redirect(url_for('admin_dashboard'))
@app.route('/admin/presenca/<int:id>')
def ver_lista_presenca(id):
    if not session.get('logged_in') or not session.get('is_admin'): return redirect(url_for('admin_login_page'))
    treinamentos = carregar_treinamentos()
    treinamento_atual = next((t for t in treinamentos if int(t['id']) == id), None)
    presencas = carregar_presencas()
    participantes = [p for p in presencas if p['id_treinamento'] == str(id)]
    return render_template('lista_presenca.html', treinamento=treinamento_atual, participantes=participantes)
@app.route('/admin/add', methods=['GET'])
def add_training_page():
    if not session.get('logged_in') or not session.get('is_admin'): return redirect(url_for('admin_login_page'))
    return render_template('add_training.html')
@app.route('/admin/add', methods=['POST'])
def add_training_submit():
    if not session.get('logged_in') or not session.get('is_admin'): return redirect(url_for('admin_login_page'))
    treinamentos = carregar_treinamentos()
    novo_id = max([int(t['id']) for t in treinamentos] + [0]) + 1
    nova_linha = {'id': novo_id, 'titulo': request.form['titulo'], 'data_hora': request.form['data_hora'], 'descricao': request.form['descricao'], 'link_meet': request.form['link_meet'], 'presenca_liberada': 'nao', 'status': 'ativo', 'instrutor': request.form['instrutor'], 'carga_horaria': request.form.get('carga_horaria', '0')}
    treinamentos.append(nova_linha)
    salvar_treinamentos(treinamentos)
    return redirect(url_for('admin_dashboard'))
@app.route('/admin/delete/<int:id>')
def delete_training(id):
    if not session.get('logged_in') or not session.get('is_admin'): return redirect(url_for('admin_login_page'))
    treinamentos = carregar_treinamentos()
    treinamentos_para_manter = [t for t in treinamentos if int(t['id']) != id]
    salvar_treinamentos(treinamentos_para_manter)
    return redirect(url_for('admin_dashboard'))
@app.route('/admin/edit/<int:id>', methods=['GET'])
def edit_training_page(id):
    if not session.get('logged_in') or not session.get('is_admin'): return redirect(url_for('admin_login_page'))
    treinamentos = carregar_treinamentos()
    treinamento_para_editar = next((t for t in treinamentos if int(t['id']) == id), None)
    if treinamento_para_editar: return render_template('edit_training.html', treinamento=treinamento_para_editar)
    else: return "<h1>Treinamento não encontrado!</h1>"
@app.route('/admin/edit/<int:id>', methods=['POST'])
def edit_training_submit(id):
    if not session.get('logged_in') or not session.get('is_admin'): return redirect(url_for('admin_login_page'))
    treinamentos = carregar_treinamentos()
    for t in treinamentos:
        if int(t['id']) == id:
            t['titulo'], t['data_hora'], t['descricao'], t['link_meet'], t['instrutor'], t['carga_horaria'] = request.form['titulo'], request.form['data_hora'], request.form['descricao'], request.form['link_meet'], request.form['instrutor'], request.form['carga_horaria']
            t['presenca_liberada'], t['status'] = t.get('presenca_liberada', 'nao'), t.get('status', 'ativo')
            break
    salvar_treinamentos(treinamentos)
    return redirect(url_for('admin_dashboard'))

# --- ROTA FINAL E CORRIGIDA PARA GERAR O CERTIFICADO ---
@app.route('/admin/generate-certificate/<int:training_id>/<cpf>')
def generate_certificate(training_id, cpf):
    if not session.get('logged_in') or not session.get('is_admin'):
        return redirect(url_for('admin_login_page'))

    treinamento = next((t for t in carregar_treinamentos() if int(t['id']) == training_id), None)
    participante = next((p for p in carregar_presencas() if p['id_treinamento'] == str(training_id) and p['cpf_cooperado'] == cpf), None)

    if not treinamento or not participante:
        return "<h1>Dados não encontrados para gerar o certificado.</h1>"

    texto_principal = """Participou com êxito do treinamento: {NOME_TREINAMENTO}, realizado em {DATA_TREINAMENTO}, Sob o CPF: {CPF_COOPERADO},
contabilizando carga horária total de {CARGA_HORARIA} horas. Este treinamento teve como objetivo capacitar de forma eficaz para
atuação no HomeCare. O participante demonstrou compromisso e dedicação ao longo do treinamento, evidenciando uma
melhoria significativa em suas habilidades e conhecimentos. Certificamos também que {NOME_COOPERADO} atendeu
aos requisitos do treinamento e está apto a aplicar os conhecimentos adquiridos."""

    data_formatada = datetime.strptime(treinamento['data_hora'], '%Y-%m-%d %H:%M').strftime('%d de %B de %Y')
    texto_final = texto_principal.format(
        NOME_COOPERADO=participante['nome_cooperado'],
        CPF_COOPERADO=participante['cpf_cooperado'],
        NOME_TREINAMENTO=treinamento['titulo'],
        DATA_TREINAMENTO=data_formatada,
        CARGA_HORARIA=treinamento['carga_horaria']
    )

    background_path = os.path.join('static', 'certificate_assets', 'fundo_certificado.png')
    if not os.path.exists(background_path):
        return "<h1>Erro: Imagem de fundo 'fundo_certificado.png' não encontrada na pasta 'static/certificate_assets'.</h1>"

    img = Image.open(background_path).convert('RGB')
    largura, altura = img.size
    draw = ImageDraw.Draw(img)
    
    try:
        font_titulo_path = os.path.join('static', 'Autography.ttf')
        font_corpo_path = os.path.join('static', 'arial.ttf')
        
        font_titulo = ImageFont.truetype(font_titulo_path, 200)
        font_corpo = ImageFont.truetype(font_corpo_path, 60)
        font_data = ImageFont.truetype(font_corpo_path, 50)
    except IOError as e:
        return f"<h1>Erro ao carregar fonte: {e}. Verifique se o nome do arquivo está correto e se ele está na pasta 'static'.</h1>"

    # Título (Nome do Cooperado) - O título geralmente não precisa de tracking
    titulo_bbox = draw.textbbox((0, 0), participante['nome_cooperado'], font=font_titulo)
    titulo_x = (largura - (titulo_bbox[2] - titulo_bbox[0])) / 2
    draw.text((titulo_x, 1150), participante['nome_cooperado'], font=font_titulo, fill='#00a5b6')

    # --- SEU PAINEL DE CONTROLE DE ESPAÇAMENTO ---
    y_text = 1350  # Posição vertical inicial do corpo do texto
    line_spacing = 50 # Espaçamento entre as linhas
    character_spacing = 7 # <-- AQUI ESTÁ O SEU CONTROLE! AUMENTE PARA MAIS ESPAÇO

    # Corpo do texto
    from textwrap import wrap
    lines = wrap(texto_final, width=80)
    for line in lines:
        # Para centralizar a linha, primeiro medimos seu tamanho total com o espaçamento
        line_width = sum(draw.textbbox((0, 0), char, font=font_corpo)[2] + character_spacing for char in line)
        line_x = (largura - line_width) / 2
        
        # Agora usamos nossa nova função para desenhar a linha
        draw_text_with_tracking(draw, (line_x, y_text), line, font_corpo, 'black', tracking=character_spacing)
        y_text += line_spacing # Move para a próxima linha

    # Data no final
    data_final = f"Salvador, {data_formatada}"
    data_bbox = draw.textbbox((0, 0), data_final, font=font_data)
    data_x = largura - (data_bbox[2] - data_bbox[0]) - 250
    draw.text((data_x, altura - 700), data_final, font=font_data, fill='black')

    if not os.path.exists(app.config['CERTIFICATE_FOLDER']):
        os.makedirs(app.config['CERTIFICATE_FOLDER'])
    
    filename = f"certificado_{training_id}_{cpf}.pdf"
    filepath = os.path.join(app.config['CERTIFICATE_FOLDER'], filename)
    img.save(filepath, "PDF", resolution=300.0)

    return send_from_directory(app.config['CERTIFICATE_FOLDER'], filename, as_attachment=False)

if __name__ == '__main__':
    app.run(debug=True)