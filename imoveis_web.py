import sqlite3
import json
from datetime import datetime, timedelta, timezone
import os
import sys
import re
import pytesseract
from PIL import Image
from io import BytesIO
import random
import string
import pandas as pd
from werkzeug.utils import secure_filename
from flask import Response
import iago
from apscheduler.schedulers.background import BackgroundScheduler
import updater
import atexit
import logging
from logging.handlers import RotatingFileHandler


from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
	send_file, 
    session,
    jsonify
)
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_wtf.csrf import CSRFProtect, CSRFError
from werkzeug.security import generate_password_hash, check_password_hash

# ... (existing config)



# ==============================
# CONFIGURAÇÃO
# ==============================

def get_base_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.getcwd()

BASE_DIR = get_base_path()
DB_PATH = os.path.join(BASE_DIR, "imoveis.db")
SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-fallback-secret-key-do-not-use-in-prod")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
ALLOWED_EXTENSIONS = {'tif', 'tiff', 'png', 'jpg', 'jpeg', 'pdf'}


# Tenta importar pdf2image
# Load .env variables
from dotenv import load_dotenv
load_dotenv(os.path.join(BASE_DIR, ".env")) # Load from specific path

# Tenta importar pdf2image
try:
    from pdf2image import convert_from_path
except ImportError:
    convert_from_path = None

# Configure OCR Paths
TESSERACT_CMD = os.getenv("TESSERACT_CMD", "")
POPPLER_PATH = os.getenv("POPPLER_PATH", "")

if TESSERACT_CMD and os.path.exists(TESSERACT_CMD):
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
else:
    # Try default if not set
    # Common windows path
    default_tess = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if os.path.exists(default_tess):
        pytesseract.pytesseract.tesseract_cmd = default_tess

# Validate Poppler
if POPPLER_PATH and not os.path.exists(POPPLER_PATH):
    # Try to find it common or reset
    POPPLER_PATH = "" 

# Determine paths for PyInstaller
if getattr(sys, 'frozen', False):
    # If frozen, assets are in sys._MEIPASS
    base_dir = sys._MEIPASS
    template_folder = os.path.join(base_dir, 'templates')
    static_folder = os.path.join(base_dir, 'static')
    app = Flask(__name__, template_folder=template_folder, static_folder=static_folder)
else:
    app = Flask(__name__)

app.secret_key = SECRET_KEY
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(seconds=3600)
csrf = CSRFProtect(app)

# ==============================
# LOGGING CONFIGURATION
# ==============================

# Configure centralized logging
LOG_FILE = os.path.join(BASE_DIR, "system.log")
log_handler = RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=3)
log_handler.setLevel(logging.DEBUG)
log_formatter = logging.Formatter(
    '%(asctime)s - %(levelname)s - [%(module)s] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log_handler.setFormatter(log_formatter)

# Configure root logger explicitly to ensure handler is added
# (basicConfig does nothing if root logger already has handlers)
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
if not any(isinstance(h, RotatingFileHandler) for h in root_logger.handlers):
    root_logger.addHandler(log_handler)

logger = logging.getLogger(__name__)
logger.info("=" * 60)
logger.info("Sistema Indicador Real - Iniciando...")
logger.info("=" * 60)


def init_db():
    """Initializes the database if it doesn't exist or is empty."""
    # Use global DB_PATH which is now absolute
    
    # Always check/create tables
    needs_init = True
    
    # But only print if we actually do something?
    # For now, let's just let it run SQL (IF NOT EXISTS is safe)

    if needs_init:
        print(f"[INIT] Initializing database at {DB_PATH}...")
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()

        # 1. Users
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                whatsapp TEXT,
                is_temporary_password INTEGER DEFAULT 0,
                profile_image TEXT,
                created_at TEXT,
                email TEXT,
                nome_completo TEXT,
                cpf TEXT,
                last_seen TEXT
            )
        """)
        
        # 2. Imoveis
        cur.execute("""
            CREATE TABLE IF NOT EXISTS imoveis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                numero_registro TEXT,
                registro_tipo INTEGER,
                status_trabalho TEXT DEFAULT 'PENDENTE',
                concluded_by TEXT,
                ocr_text TEXT,
                arquivo_tiff TEXT,
                
                nome_logradouro TEXT,
                numero_logradouro TEXT,
                complemento TEXT,
                bairro TEXT,
                cep TEXT,
                cidade TEXT,
                uf INTEGER,
                
                tipo_de_imovel INTEGER,
                localizacao INTEGER,
                tipo_logradouro INTEGER,
                varios_enderecos TEXT,
                
                loteamento TEXT,
                quadra TEXT,
                conjunto TEXT,
                setor TEXT,
                lote TEXT,
                
                contribuinte TEXT,
                
                rural_car TEXT,
                rural_nirf TEXT,
                rural_ccir TEXT,
                rural_numero_incra TEXT,
                rural_sigef TEXT,
                rural_denominacaorural TEXT,
                rural_acidentegeografico TEXT,
                
                condominio_nome TEXT,
                condominio_bloco TEXT,
                condominio_conjunto TEXT,
                condominio_torre TEXT,
                condominio_apto TEXT,
                condominio_vaga TEXT,
                
                updated_at TEXT
            )
        """)

        # 3. Locks
        cur.execute("""
            CREATE TABLE IF NOT EXISTS imoveis_lock (
                imovel_id INTEGER PRIMARY KEY,
                editing_by TEXT,
                editing_since TEXT
            )
        """)

        # 4. Resets
        cur.execute("""
            CREATE TABLE IF NOT EXISTS password_resets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT,
                name TEXT,
                status TEXT DEFAULT 'PENDENTE',
                created_at TEXT
            )
        """)
        
        # 5. Config
        cur.execute("""
            CREATE TABLE IF NOT EXISTS system_config (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        # 6. Indicador Pessoal (NEW)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS indicador_pessoal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT,
                cpf_cnpj TEXT,
                n_matricula TEXT,
                tipo_ato TEXT,
                dt_reg_averb TEXT,
                dt_venda TEXT,
                observacao TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        """)

        # INSERT DEFAULT ADMIN
        # Only if users table is empty
        cur.execute("SELECT count(*) FROM users")
        if cur.fetchone()[0] == 0:
            hashed = generate_password_hash("admin") # Default password
            now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
            cur.execute("INSERT INTO users (username, password_hash, role, created_at, nome_completo) VALUES (?, ?, ?, ?, ?)", 
                        ("admin", hashed, "admin", now, "Administrador"))
            print("[INIT] Default admin user created.")
        
        # Insert Default Config
        defaults = {
            "smtp_server": "smtp.gmail.com",
            "smtp_port": "587",
            "smtp_user": "",
            "smtp_password": "",
            "smtp_tls": "1"
        }
        for key, val in defaults.items():
            cur.execute("INSERT OR IGNORE INTO system_config (key, value) VALUES (?, ?)", (key, val))

        conn.commit()
        conn.close()
        print("[INIT] Database initialization complete.")
    
    # Run Migrations (Safe to run always)
    migrate_db()

def migrate_db():
    """Checks for missing columns and adds them (Auto-Migration)."""
    db_path = "imoveis.db"
    if not os.path.exists(db_path):
        return

    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        
        # Get existing columns
        cur.execute("PRAGMA table_info(users)")
        columns = [row[1] for row in cur.fetchall()]
        
        # Check and add 'nome_completo'
        if 'nome_completo' not in columns:
            print("[MIGRATE] Adding 'nome_completo' to users...")
            cur.execute("ALTER TABLE users ADD COLUMN nome_completo TEXT")
            
        # Check and add 'cpf'
        if 'cpf' not in columns:
             print("[MIGRATE] Adding 'cpf' to users...")
             cur.execute("ALTER TABLE users ADD COLUMN cpf TEXT")

        # Check and add 'last_seen'
        if 'last_seen' not in columns:
             print("[MIGRATE] Adding 'last_seen' to users...")
             cur.execute("ALTER TABLE users ADD COLUMN last_seen TEXT")

        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[MIGRATE] Error during migration: {e}")


# Run init on module load (or app start)
init_db()

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

@login_manager.unauthorized_handler
def unauthorized():
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.form.get("mode") == "ajax":
        return jsonify({"status": "error", "message": "Sessão expirada. Faça login novamente.", "error": "unauthorized"}), 401
    return redirect(url_for('login'))


@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    # Check for AJAX or API path
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or "/api/" in request.path:
        return jsonify({
            "status": "error", 
            "message": "Sessão expirada ou token inválido. Por favor, recarregue a página.", 
            "error": "csrf_token_missing"
        }), 400
    
    # Fallback for normal requests - show a simple error message using base template if possible, or just a string
    return f"<h3>Erro de Sessão (CSRF)</h3><p>{e.description}</p><p><a href='/'>Voltar</a></p>", 400


# Load config from .env or default
CNS_CODIGO = os.getenv("CNS_CODIGO", "004879") 
CARTORIO_NAME = os.getenv("CARTORIO_NAME", "Cartório 2º Ofício de Manacapuru")

@app.context_processor
def inject_global_vars():
    return dict(
        cartorio_name=CARTORIO_NAME,
        cns_codigo=CNS_CODIGO
    )


# Scheduler Config
cron_scheduler = BackgroundScheduler()

# Notifier for admins about updates
def notify_admins_of_update(commits_behind):
    admins = get_admin_emails()
    if not admins:
        return
        
    subject = f"Nova Atualização Disponível - Indicador Real"
    body = f"<p>Uma nova atualização está disponível para o sistema (atrasado por {commits_behind} commits).</p><p>Acesse /atualizacoes para verificar.</p>"
    
    # Send to all
    import email_service
    for email in admins:
         email_service.send_email_sync(email, subject, body)

# Global state for updates
UPDATE_STATE = {
    'available': False,
    'commits_behind': 0,
    'last_check': None
}

def scheduled_update_check():
    """Daily check for updates."""
    global UPDATE_STATE
    try:
        logging.info("Verificando atualizações (Agendado)...")
        res = updater.check_for_updates()
        if res and not res.get('error'):
            UPDATE_STATE['available'] = res['update_available']
            UPDATE_STATE['commits_behind'] = res['commits_behind']
            UPDATE_STATE['last_check'] = datetime.now().isoformat()
            if res['update_available']:
                logging.info(f"Atualização disponível! Atrasado em {res['commits_behind']} commits.")
                # Notify admins
                with app.app_context():
                     notify_admins_of_update(res['commits_behind'])
    except Exception as e:
        logging.error(f"Erro na verificação agendada: {e}")

# Start Scheduler
cron_scheduler.add_job(func=scheduled_update_check, trigger="cron", hour=0, minute=0)
cron_scheduler.start()

# Shut down the scheduler when exiting the app
atexit.register(lambda: cron_scheduler.shutdown())


# ==============================
# INDICADOR PESSOAL LOGIC
# ==============================

@app.route('/indicador_pessoal')
@login_required
def indicador_pessoal():
    return render_template('indicador_pessoal.html')

@app.route('/indicador_pessoal/api/list', methods=['GET'])
@login_required
def api_list_indicador():
    conn = get_conn()
    cur = conn.cursor()
    
    # Filter params
    search = request.args.get('search', '').lower()
    
    query = "SELECT * FROM indicador_pessoal"
    params = []
    
    if search:
        query += " WHERE lower(nome) LIKE ? OR cpf_cnpj LIKE ? OR n_matricula LIKE ?"
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
        
    query += " ORDER BY dt_reg_averb DESC, created_at DESC"
    
    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()
    
    data = [dict(row) for row in rows]
    return jsonify(data)

@app.route('/indicador_pessoal/api/summary', methods=['GET'])
@login_required
def api_summary_indicador():
    search = request.args.get('search', '').strip()
    conn = get_conn()
    cur = conn.cursor()
    
    query = """
        SELECT 
            n_matricula, 
            MAX(nome) as nome_exemplo, 
            COUNT(*) as qtd_atos, 
            MAX(dt_reg_averb) as ultima_data
        FROM indicador_pessoal
    """
    
    params = []
    if search:
        query += " WHERE nome LIKE ? OR cpf_cnpj LIKE ? OR n_matricula LIKE ?"
        s_term = f"%{search}%"
        params = [s_term, s_term, s_term]
        
    query += " GROUP BY n_matricula ORDER BY ultima_data DESC"
    
    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()
    
    data = []
    for row in rows:
        data.append({
            "n_matricula": row[0],
            "nome": row[1], # Just one name to show
            "qtd_atos": row[2],
            "ultima_data": row[3]
        })
        
    return jsonify(data)

@app.route('/indicador_pessoal/api/property/<matricula>', methods=['GET'])
@login_required
def api_get_property_by_matricula(matricula):
    conn = get_conn()
    cur = conn.cursor()
    # Try to find the exact property in main table
    # Assuming numero_registro matches matricula
    cur.execute("SELECT * FROM imoveis WHERE numero_registro = ?", (matricula.strip(),))
    row = cur.fetchone()
    conn.close()
    
    if not row:
        return jsonify({"found": False})
        
    return jsonify({"found": True, "data": dict(row)})

@app.route('/indicador_pessoal/api/save', methods=['POST'])
@login_required
def api_save_indicador():
    try:
        data = request.json
        conn = get_conn()
        cur = conn.cursor()
        now = datetime.now().isoformat()
        
        if data.get('id'):
            # Update
            cur.execute("""
                UPDATE indicador_pessoal 
                SET nome=?, cpf_cnpj=?, n_matricula=?, tipo_ato=?, 
                    dt_reg_averb=?, dt_venda=?, observacao=?, updated_at=?
                WHERE id=?
            """, (
                data['nome'], data['cpf_cnpj'], data['n_matricula'], data['tipo_ato'],
                data['dt_reg_averb'], data['dt_venda'], data.get('observacao', ''), now, data['id']
            ))
        else:
            # Create
            cur.execute("""
                INSERT INTO indicador_pessoal 
                (nome, cpf_cnpj, n_matricula, tipo_ato, dt_reg_averb, dt_venda, observacao, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data['nome'], data['cpf_cnpj'], data['n_matricula'], data['tipo_ato'],
                data['dt_reg_averb'], data['dt_venda'], data.get('observacao', ''), now, now
            ))
            
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/indicador_pessoal/api/delete/<int:id>', methods=['POST'])
@login_required
def api_delete_indicador(id):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM indicador_pessoal WHERE id=?", (id,))
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/indicador_pessoal/import', methods=['POST'])
@login_required
def import_indicador_excel():
    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "Nenhum arquivo enviado"}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({"status": "error", "message": "Nenhum arquivo selecionado"}), 400

    try:
        # Read Excel
        df = pd.read_excel(file)
        
        # Expected columns mapping (or heuristic)
        # NOME, CNPJCPF, NMATRICULA, TIPODEATO, DTREGAVERB, DTVENDA
        
        conn = get_conn()
        cur = conn.cursor()
        now = datetime.now().isoformat()
        
        count = 0
        for _, row in df.iterrows():
            # Basic mapping, adjust as needed based on user excel format
            nome = str(row.get('NOME', row.get('nome', ''))).strip()
            cpf = str(row.get('CNPJCPF', row.get('cpf_cnpj', ''))).strip()
            mat = str(row.get('NMATRICULA', row.get('n_matricula', ''))).strip()
            tipo = str(row.get('TIPODEATO', row.get('tipo_ato', 'Registrado'))).strip()
            dtr = str(row.get('DTREGAVERB', row.get('dt_reg_averb', ''))).strip()
            dtv = str(row.get('DTVENDA', row.get('dt_venda', ''))).strip()
            
            if nome: # Only insert if name exists
                cur.execute("""
                    INSERT INTO indicador_pessoal 
                    (nome, cpf_cnpj, n_matricula, tipo_ato, dt_reg_averb, dt_venda, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (nome, cpf, mat, tipo, dtr, dtv, now, now))
                count += 1
                
        conn.commit()
        conn.close()
        
        return jsonify({"status": "success", "message": f"{count} registros importados com sucesso!"})
        
    except Exception as e:
        return jsonify({"status": "error", "message": f"Erro na importação: {str(e)}"}), 500

@app.route('/indicador_pessoal/extract', methods=['POST'])
@login_required
def extract_indicador_from_db():
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        # Select existing imoveis with valid Data
        cur.execute("SELECT numero_registro, contribuinte, created_at, ocr_text FROM imoveis WHERE contribuinte IS NOT NULL AND contribuinte != ''")
        rows = cur.fetchall()
        
        count = 0
        now = datetime.now().isoformat()
        
        for row in rows:
            # 1. Try to extract specific ACTS from OCR (Smarter IAGO)
            acts = []
            if row['ocr_text'] and len(row['ocr_text']) > 50:
                 acts = iago.extract_acts(row['ocr_text'])
            
            if acts:
                # Insert each found act
                for act in acts:
                    # Skip duplicate check for now or make it smart?
                    # Let's check duplicate by Matricula + Act Type + Date
                    cur.execute("SELECT id FROM indicador_pessoal WHERE n_matricula=? AND tipo_ato=? AND dt_reg_averb=?", 
                                (row['numero_registro'], act['tipo_ato'], act['dt_ato']))
                    if cur.fetchone():
                        continue
                        
                    # Join parties found
                    partes_str = ", ".join(act['partes']) if act['partes'] else "Não identificado"
                    
                    cur.execute("""
                        INSERT INTO indicador_pessoal 
                        (nome, cpf_cnpj, n_matricula, tipo_ato, dt_reg_averb, dt_venda, observacao, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        partes_str, 
                        "", # CPF is in partes_str usually
                        row['numero_registro'],
                        act['tipo_ato'],
                        act['dt_ato'],
                        "", # dt_venda could be same as dt_ato for compra e venda
                        f"Extraído via IAGO (OCR): {act['header']}",
                        now, now
                    ))
                    count += 1
            else:
                # 2. Fallback to Simple Contribuinte Extraction
                try:
                    contrib_list = json.loads(row['contribuinte'])
                except:
                    contrib_list = [row['contribuinte']]
                    
                if not contrib_list: continue

                dt_reg = row['created_at'].split('T')[0] if row['created_at'] else now.split('T')[0]
                
                for nome in contrib_list:
                    if not nome: continue
                    
                    cur.execute("SELECT id FROM indicador_pessoal WHERE n_matricula=? AND nome=?", (row['numero_registro'], nome))
                    if cur.fetchone(): continue
                        
                    cur.execute("""
                        INSERT INTO indicador_pessoal 
                        (nome, cpf_cnpj, n_matricula, tipo_ato, dt_reg_averb, dt_venda, observacao, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        nome, "", row['numero_registro'], "Proprietário Atual", dt_reg, "", 
                        "Extraído automaticamente (Fallback).", now, now
                    ))
                    count += 1
                
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "message": f"{count} registros extraídos do acervo."})
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/indicador_pessoal/learn', methods=['POST'])
@login_required
def train_iago():
    """
    Level 3: Active Learning.
    User sends corrected data for a specific Matricula, and we tell IAGO to learn.
    """
    try:
        data = request.json
        n_matricula = data.get('n_matricula')
        
        if not n_matricula:
             return jsonify({"status": "error", "message": "Matricula não informada"}), 400
             
        # Fetch original OCR text from imoveis table
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT ocr_text FROM imoveis WHERE numero_registro = ?", (n_matricula,))
        row = cur.fetchone()
        conn.close()
        
        if not row or not row['ocr_text']:
             return jsonify({"status": "error", "message": "Texto OCR original não encontrado para esta matrícula."}), 404
             
        # Map frontend fields to IAGO learning fields
        # user data: {nome, cpf_cnpj, tipo_ato, dt_reg_averb}
        # iago fields: NOME_PARTE, CPF_PARTE, TIPO_ATO, DT_ATO
        
        learning_data = {
            "NOME_PARTE": data.get('nome'),
            "CPF_PARTE": data.get('cpf_cnpj'),
            "TIPO_ATO": data.get('tipo_ato'),
            "DT_ATO": data.get('dt_reg_averb')
        }
        
        # Remove empty
        learning_data = {k:v for k,v in learning_data.items() if v}
        
        learned_count = iago.learn(row['ocr_text'], learning_data)
        
        return jsonify({
            "status": "success", 
            "message": f"IAGO aprendeu {learned_count} novos padrões com sucesso!"
        })
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ==============================
# ROUTE UPDATES START HERE
# I will replace specific functions instead of whole file content for safety.
# But allow_multiple=True helps.

# Let's replace PERMANENT_SESSION_LIFETIME


# Mesmas tabelas de código usadas no desktop
REGISTRO_TIPO_OPCOES = {
    1: "Matrícula",
    2: "Matrícula Mãe",
    4: "Transcrição",
}

LOCALIZACAO_OPCOES = {
    0: "URBANO",
    1: "RURAL",
}

TIPO_IMOVEL_OPCOES = {
    1: "Casa",
    2: "Apartamento",
    3: "Loja",
    4: "Sala/Conjunto",
    5: "Terreno/Fração",
    6: "Galpão",
    7: "Prédio comercial",
    8: "Prédio residencial",
    9: "Fazenda/Sítio/Chácara",
    10: "Vaga",
    11: "Depósito",
    12: "Públicos",
    13: "Outros",
}

UF_OPCOES = {
    11: "RO", 12: "AC", 13: "AM", 14: "RR", 15: "PA", 16: "AP", 17: "TO",
    21: "MA", 22: "PI", 23: "CE", 24: "RN", 25: "PB", 26: "PE", 27: "AL", 28: "SE", 29: "BA",
    31: "MG", 32: "ES", 33: "RJ", 35: "SP",
    41: "PR", 42: "SC", 43: "RS",
    50: "MS", 51: "MT", 52: "GO", 53: "DF",
}

TIPO_LOGRADOURO_OPCOES = {
    1: "Acampamento", 2: "Acesso", 3: "Açude", 4: "Adro", 5: "Aeroporto", 6: "Afluente",
    7: "Aglomerado", 8: "Agrovila", 9: "Alagado", 10: "Alameda", 11: "Aldeia", 12: "Aleia",
    13: "Alto", 14: "Anel", 15: "Antiga", 16: "Antigo", 17: "Área", 18: "Areal",
    19: "Arraial", 20: "Arroio", 21: "Artéria", 22: "Assentamento", 23: "Atalho", 24: "Aterro",
    25: "Autódromo", 26: "Avenida", 27: "Baia", 28: "Bairro", 29: "Baixa", 30: "Baixada",
    31: "Baixadão", 32: "Baixão", 33: "Baixo", 34: "Balão", 35: "Balneário", 36: "Barra",
    37: "Barragem", 38: "Barranca", 39: "Barranco", 40: "Barreiro", 41: "Barro", 42: "Beco",
    43: "Beira", 44: "Beirada", 45: "Belvedere", 46: "Bloco", 47: "Bocaina", 48: "Boqueirão",
    49: "Bosque", 50: "Boulevard", 51: "Brejo", 52: "Buraco", 53: "Cabeceira", 54: "Cachoeira",
    55: "Cachoeirinha", 56: "Cais", 57: "Calcada", 58: "Calçadão", 59: "Caminho", 60: "Campo",
    61: "Canal", 62: "Canteiro", 63: "Capão", 64: "Capoeira", 65: "Cartódromo", 66: "Central",
    67: "Centro", 68: "Cerca", 69: "Cerrado", 70: "Cerro", 71: "Chácara", 72: "Chapada",
    73: "Chapadão", 74: "Charco", 75: "Cidade", 76: "Circular", 77: "Cohab", 78: "Colina",
    79: "Colônia", 80: "Comunidade", 81: "Condomínio", 82: "Conjunto", 83: "Continuação",
    84: "Contorno", 85: "Corredor", 86: "Córrego", 87: "Costa", 88: "Coxilha", 89: "Cruzamento",
    90: "Descida", 91: "Desvio", 92: "Dique", 93: "Distrito", 94: "Divisa", 95: "Divisão",
    96: "Divisor", 97: "Edifício", 98: "Eixo", 99: "Elevado", 100: "Encosta", 101: "Engenho",
    102: "Enseada", 103: "Entrada", 104: "Entreposto", 105: "Entroncamento", 106: "Escada",
    107: "Escadão", 108: "Escadaria", 109: "Escadinha", 110: "Espigão", 111: "Esplanada",
    112: "Esquina", 113: "Estação", 114: "Estacionamento", 115: "Estádio", 116: "Estância",
    117: "Estrada", 118: "Extensão", 119: "Faixa", 120: "Favela", 121: "Fazenda", 122: "Feira",
    123: "Ferrovia", 124: "Final", 125: "Floresta", 126: "Folha", 127: "Fonte", 128: "Fortaleza",
    129: "Freguesia", 130: "Fundos", 131: "Furo", 132: "Galeria", 133: "Gameleira", 134: "Garimpo",
    135: "Gleba", 136: "Granja", 137: "Grota", 138: "Habitacional", 139: "Haras", 140: "Hipódromo",
    141: "Horto", 142: "Igarapé", 143: "Ilha", 144: "Inaplicável", 145: "Invasão", 146: "Jardim",
    147: "Jardinete", 148: "Ladeira", 149: "Lado", 150: "Lago", 151: "Lagoa", 152: "Lagoinha",
    153: "Largo", 154: "Lateral", 155: "Leito", 156: "Ligação", 157: "Limeira", 158: "Limite",
    159: "Limites", 160: "Linha", 161: "Lote", 162: "Loteamento", 163: "Lugarejo", 164: "Maloca",
    165: "Manancial", 166: "Mangue", 167: "Margem", 168: "Margens", 169: "Marginal", 170: "Marina",
    171: "Mata", 172: "Mato", 173: "Módulo", 174: "Monte", 175: "Morro", 176: "Muro",
    177: "Não Especificado", 178: "Núcleo", 179: "Oca", 180: "Oleoduto", 181: "Olho", 182: "Olhos",
    183: "Orla", 184: "Outros", 185: "Paco", 186: "Palafita", 187: "Pântano", 188: "Parada",
    189: "Paradouro", 190: "Paralela", 191: "Parque", 192: "Particular", 193: "Passagem",
    194: "Passarela", 195: "Passeio", 196: "Passo", 197: "Pasto", 198: "Pátio", 199: "Pavilhão",
    200: "Pedra", 201: "Pedras", 202: "Pedreira", 203: "Penhasco", 204: "Perimetral", 205: "Perímetro",
    206: "Perto", 207: "Planalto", 208: "Plataforma", 209: "Ponta", 210: "Ponte", 211: "Ponto",
    212: "Porto", 213: "Posto", 214: "Povoado", 215: "Praça", 216: "Praia", 217: "Projeção",
    218: "Projetada", 219: "Projeto", 220: "Prolongamento", 221: "Propriedade", 222: "Próximo",
    223: "Quadra", 224: "Quarteirão", 225: "Quilombo", 226: "Quilometro", 227: "Quinta",
    228: "Quintas", 229: "Rachão", 230: "Ramal", 231: "Rampa", 232: "Rancho", 233: "Recanto",
    234: "Região", 235: "Represa", 236: "Residencial", 237: "Reta", 238: "Retiro", 239: "Retorno",
    240: "Riacho", 241: "Ribanceira", 242: "Ribeirão", 243: "Rincão", 244: "Rio", 245: "Rocha",
    246: "Rochedo", 247: "Rodovia", 248: "Rotatória", 249: "Rotula", 250: "Rua", 251: "Ruela",
    252: "Saco", 253: "Saída", 254: "Sanga", 255: "Sede", 256: "Sem", 257: "Seringal",
    258: "Serra", 259: "Sertão", 260: "Servidão", 261: "Seta", 262: "Setor", 263: "Sitio",
    264: "Sopé", 265: "Subida", 266: "Superquadra", 267: "Tapera", 268: "Terminal", 269: "Terra",
    270: "Terreno", 271: "Terrenos", 272: "Transversal", 273: "Travessa", 274: "Travessão",
    275: "Travessia", 276: "Trecho", 277: "Trevo", 278: "Trilha", 279: "Trilho", 280: "Trilhos",
    281: "Trincheira", 282: "Túnel", 283: "Unidade", 284: "Usina", 285: "Vala", 286: "Valão",
    287: "Vale", 288: "Vargem", 289: "Variante", 290: "Várzea", 291: "Velódromo", 292: "Vereda",
    293: "Vertente", 294: "Via", 295: "Viaduto", 296: "Vicinal", 297: "Viela", 298: "Vila",
    299: "Vilarejo", 300: "Volta", 301: "Zona", 302: "1a Travessa da Avenida", 303: "1a Travessa da Rua",
    304: "2a Travessa da Avenida", 305: "2a Travessa da Rua", 306: "3a Travessa da Avenida",
    307: "3a Travessa da Rua", 308: "4a Travessa da Avenida", 309: "4a Travessa da Rua",
    310: "5a Travessa da Avenida", 311: "5a Travessa da Rua",
}


# ==============================
# HELPERS
# ==============================


CIDADE_NOME_TO_IBGE = {
    "MANACAPURU": 1302504,
}
UF_SIGLA_TO_COD = {sigla: cod for cod, sigla in UF_OPCOES.items()}

# ==============================
# LOGICA DE NEGOCIO (PORTADA)
# ==============================

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def ocr_file_to_text(filepath: str) -> str:
    """Extrai texto de TIFF, PNG, JPG ou PDF."""
    ext = filepath.rsplit('.', 1)[1].lower()
    text = ""
    try:
        if ext == 'pdf':
            if convert_from_path is None:
                raise Exception("Biblioteca pdf2image não disponível.")
            
            # Read 1st page
            try:
                # Use configured Poppler path if available
                kwargs = {}
                if POPPLER_PATH:
                    kwargs['poppler_path'] = POPPLER_PATH
                
                pages = convert_from_path(filepath, first_page=1, last_page=2, **kwargs)
                for page in pages:
                    text += pytesseract.image_to_string(page) + "\n"
            except Exception as e:
                print(f"[ERRO OCR] pdf2image falhou. Verifique o caminho Poppler. Detalhes: {e}")
                return ""
        else:
            img = Image.open(filepath)
            text = pytesseract.image_to_string(img)
    except Exception as e:
        print(f"Erro no OCR: {e}")
        return ""
    return text

def extract_matricula_number(text: str) -> str:
    # 1. CNM: xxxxxx.x.yyyyyyy-xx (yyyyyyy is matricula, ignore leading zeros)
    m_cnm = re.search(r"\d+\.\d\.(\d{7})-\d{2}", text)
    if m_cnm:
        return str(int(m_cnm.group(1)))
    
    # 2. Cabeçalho: MATRÍCULA Nº 5000
    m_header = re.search(r"MATR[ÍI]CULA\s*(?:N[ºo°]?)?\s*(\d+)", text, re.IGNORECASE)
    if m_header:
        # Pega a parte numérica após 'Nº'
        return str(int(m_header.group(1)))
        
    return ""

def parse_text_to_dict(text: str) -> dict:
    def find(pattern, default=""):
        m = re.search(pattern, text, flags=re.IGNORECASE)
        return m.group(1).strip() if m else default

    upper_text = text.upper()
    cidade_codigo = 1302504 
    uf_codigo = 13          

    for nome, cod in CIDADE_NOME_TO_IBGE.items():
        if nome in upper_text:
            cidade_codigo = cod
            uf_codigo = cod // 100000
            break

    m = re.search(r"/([A-Z]{2})", upper_text)
    if m:
        sigla = m.group(1)
        if sigla in UF_SIGLA_TO_COD:
            uf_codigo = UF_SIGLA_TO_COD[sigla]

    matricula = extract_matricula_number(text)
    if not matricula:
        matricula = find(r"REGISTRO[:\s]+(\S+)", "")

    data = {
        "NUMERO_REGISTRO": matricula,
        "VARIOS_ENDERECOS": find(r"VARIOS\s*ENDERECOS[:\s]+([SN])", "N"),
        "REGISTRO_TIPO": int(find(r"REGISTRO\s*TIPO[:\s]+(\d+)", "1") or 1),
        "TIPO_DE_IMOVEL": int(find(r"TIPO\s*DE\s*IMOVEL[:\s]+(\d+)", "1") or 1),
        "LOCALIZACAO": int(find(r"LOCALIZACAO[:\s]+(\d+)", "0") or 0),
        "TIPO_LOGRADOURO": int(find(r"TIPO\s*LOGRADOURO[:\s]+(\d+)", "250") or 250),
        "NOME_LOGRADOURO": find(r"NOME\s*LOGRADOURO[:\s]+(.+)", ""),
        "NUMERO_LOGRADOURO": find(r"NUMERO\s*LOGRADOURO[:\s]+(\S+)", ""),
        "UF": uf_codigo,
        "CIDADE": cidade_codigo,
        "BAIRRO": find(r"BAIRRO[:\s]+(.+)", ""),
        "CEP": find(r"CEP[:\s]+(\S+)", ""),
        "COMPLEMENTO": find(r"COMPLEMENTO[:\s]+(.+)", ""),
        "QUADRA": find(r"QUADRA[:\s]+(.+)", ""),
        "CONJUNTO": find(r"CONJUNTO[:\s]+(.+)", ""),
        "SETOR": find(r"SETOR[:\s]+(.+)", ""),
        "LOTE": find(r"LOTE[:\s]+(.+)", ""),
        "LOTEAMENTO": find(r"LOTEAMENTO[:\s]+(.+)", ""),
        "CONTRIBUINTE": [find(r"CONTRIBUINTE[:\s]+(\S+)", "")]
    }
    return data

def parse_contribuinte(text: str) -> list:
    if not text:
        return []
    # Split by comma and strip
    return [c.strip() for c in text.split(',') if c.strip()]

def save_dict_to_db_web(data: dict, tiff_path: str | None = None, ocr_text: str = "") -> int:
    conn = get_conn()
    cur = conn.cursor()
    now = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=4)).isoformat()
    cur.execute(
        """
        INSERT INTO imoveis (
            numero_registro, varios_enderecos, registro_tipo, tipo_de_imovel,
            localizacao, tipo_logradouro, nome_logradouro, numero_logradouro,
            uf, cidade, bairro, cep, complemento, quadra, conjunto,
            setor, lote, loteamento, contribuinte,
            rural_car, rural_nirf, rural_ccir, rural_numero_incra,
            rural_sigef, rural_denominacaorural, rural_acidentegeografico,
            condominio_nome, condominio_bloco, condominio_conjunto,
            condominio_torre, condominio_apto, condominio_vaga,
            arquivo_tiff, ocr_text, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            data["NUMERO_REGISTRO"], data["VARIOS_ENDERECOS"], data["REGISTRO_TIPO"],
             data["TIPO_DE_IMOVEL"], data["LOCALIZACAO"], data["TIPO_LOGRADOURO"],
             data["NOME_LOGRADOURO"], data["NUMERO_LOGRADOURO"], data["UF"],
             data["CIDADE"], data["BAIRRO"], data["CEP"], data["COMPLEMENTO"],
             data["QUADRA"], data["CONJUNTO"], data["SETOR"], data["LOTE"],
             data["LOTEAMENTO"], json.dumps(data["CONTRIBUINTE"]),
             "", "", "", "", "", "", "", "", "", "", "", "", "",
             tiff_path, ocr_text, now, now,
        ),
    )
    conn.commit()
    nid = cur.lastrowid
    conn.close()
    return nid

def row_to_indicador_item(row, tipoenvio: int) -> dict:
    r = dict(row)
    contrib = json.loads(r["contribuinte"]) if r["contribuinte"] else []
    
    return {
        "TIPOENVIO": tipoenvio,
        "NUMERO_REGISTRO": r["numero_registro"],
        "VARIOS_ENDERECOS": r["varios_enderecos"],
        "REGISTRO_TIPO": r["registro_tipo"],
        "TIPO_DE_IMOVEL": r["tipo_de_imovel"],
        "LOCALIZACAO": r["localizacao"],
        "TIPO_LOGRADOURO": r["tipo_logradouro"],
        "NOME_LOGRADOURO": r["nome_logradouro"],
        "NUMERO_LOGRADOURO": r["numero_logradouro"],
        "UF": r["uf"],
        "CIDADE": r["cidade"],
        "BAIRRO": r["bairro"],
        "CEP": (r["cep"] or "").replace("-", ""),
        "COMPLEMENTO": r["complemento"],
        "QUADRA": r["quadra"],
        "CONJUNTO": r["conjunto"],
        "SETOR": r["setor"],
        "LOTE": r["lote"],
        "LOTEAMENTO": r["loteamento"],
        "CONTRIBUINTE": contrib,
        "RURAL": {
             "CAR": r["rural_car"] or "", "NIRF": r["rural_nirf"] or "",
             "CCIR": r["rural_ccir"] or "", "NUMERO_INCRA": r["rural_numero_incra"] or "",
             "SIGEF": r["rural_sigef"] or "", "DENOMINACAORURAL": r["rural_denominacaorural"] or "",
             "ACIDENTEGEOGRAFICO": r["rural_acidentegeografico"] or "",
        },
        "CONDOMINIO": {
            "NOME_CONDOMINIO": r["condominio_nome"] or "", "BLOCO": r["condominio_bloco"] or "",
            "CONJUNTO": r["condominio_conjunto"] or "", "TORRE": r["condominio_torre"] or "",
            "APTO": r["condominio_apto"] or "", "VAGA": r["condominio_vaga"] or "",
        },
    }

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn



# ==============================
# AUTH & USER
# ==============================

import email_service  # Import the new module

# ... imports ...

# ==============================
# AUTH & USER
# ==============================

class User(UserMixin):
    # Override for creating instance with password tuple
    def __init__(self, id, username, role, password_hash=None, whatsapp=None, is_temporary_password=0, profile_image=None, email=None, nome_completo=None, cpf=None):
        self.id = id
        self.username = username
        self.role = role
        self.password_hash = password_hash
        self.whatsapp = whatsapp
        self.is_temporary_password = is_temporary_password
        self.profile_image = profile_image
        self.email = email
        self.nome_completo = nome_completo
        self.cpf = cpf
        self.last_seen = None

    @staticmethod
    def get(user_id):
        conn = get_conn()
        cur = conn.cursor()
        try:
            cur.execute("SELECT id, username, role, whatsapp, is_temporary_password, profile_image, email, nome_completo, cpf, last_seen FROM users WHERE id = ?", (user_id,))
        except sqlite3.OperationalError:
            cur.execute("SELECT id, username, role, whatsapp, is_temporary_password, profile_image, email, nome_completo, cpf, NULL as last_seen FROM users WHERE id = ?", (user_id,))
            
        user = cur.fetchone()
        conn.close()
        if not user:
            return None
        u = User(user['id'], user['username'], user['role'], whatsapp=user['whatsapp'], is_temporary_password=user['is_temporary_password'], profile_image=user['profile_image'], email=user['email'], nome_completo=user['nome_completo'], cpf=user['cpf'])
        u.last_seen = user['last_seen']
        return u

    @staticmethod
    def get_by_username(username):
        conn = get_conn()
        cur = conn.cursor()
        try:
            cur.execute("SELECT id, username, role, password_hash, whatsapp, is_temporary_password, profile_image, email, nome_completo, cpf, last_seen FROM users WHERE username = ?", (username,))
        except sqlite3.OperationalError:
            cur.execute("SELECT id, username, role, password_hash, whatsapp, is_temporary_password, profile_image, email, nome_completo, cpf, NULL as last_seen FROM users WHERE username = ?", (username,))
            
        user = cur.fetchone()
        conn.close()
        if not user:
            return None
        u = User(user['id'], user['username'], user['role'], user['password_hash'], user['whatsapp'], user['is_temporary_password'], user['profile_image'], email=user['email'], nome_completo=user['nome_completo'], cpf=user['cpf'])
        u.last_seen = user['last_seen']
        return u


@login_manager.user_loader
def load_user(user_id):
    return User.get(user_id)


def init_lock_table():
    """Cria tabela de status de edição se não existir."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS imoveis_lock (
            imovel_id INTEGER PRIMARY KEY,
            editing_by TEXT,
            editing_since TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def get_locks_dict():
    """Retorna {imovel_id: (editing_by, editing_since)}."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT imovel_id, editing_by, editing_since FROM imoveis_lock")
    rows = cur.fetchall()
    conn.close()
    locks = {}
    for r in rows:
        locks[r["imovel_id"]] = (r["editing_by"], r["editing_since"])
    return locks


def set_lock(imovel_id: int, user: str = "Web"):
    """Marca registro como 'em edição'."""
    conn = get_conn()
    cur = conn.cursor()
    now = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=4)).isoformat()
    cur.execute(
        """
        INSERT INTO imoveis_lock (imovel_id, editing_by, editing_since)
        VALUES (?, ?, ?)
        ON CONFLICT(imovel_id)
        DO UPDATE SET editing_by=excluded.editing_by, editing_since=excluded.editing_since
        """,
        (imovel_id, user, now),
    )
    conn.commit()
    conn.close()



def get_admin_emails():
    """Returns a list of emails of all admins."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT email FROM users WHERE role='admin' AND email IS NOT NULL AND email != ''")
    rows = cur.fetchall()
    conn.close()
    return [r[0] for r in rows]

def clear_lock(imovel_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM imoveis_lock WHERE imovel_id=?", (imovel_id,))
    conn.commit()
    conn.close()


def combo_label(options: dict, code: int | None) -> str:
    if code is None:
        return ""
    return options.get(code, f"{code}")


def parse_contribuinte(raw: str):
    if not raw:
        return []
    return [c.strip() for c in raw.split(",") if c.strip()]


# ==============================
# CONTEXT PROCESSORS
# ==============================

@app.context_processor
def inject_notifications():
    try:
        if not current_user.is_authenticated:
            return {}
        
        count = 0
        # Check Resets
        if current_user.role in ['admin', 'supervisor']:
            try:
                conn = get_conn()
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM password_resets WHERE status='PENDENTE'")
                r = cur.fetchone()
                if r:
                    count = r[0]
                conn.close()
            except Exception as e:
                logging.error(f"Erro ao verificar redefinições de senha: {e}")
        
        # Online Users (Active in last 5 min)
        online_users = []
        try:
            conn = get_conn()
            cur = conn.cursor()
            limit_time = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5)).isoformat()
            cur.execute("SELECT username, role, last_seen FROM users WHERE last_seen > ? ORDER BY last_seen DESC", (limit_time,))
            online_users = [dict(row) for row in cur.fetchall()]
            conn.close()
        except Exception as e:
            logging.error(f"Erro ao verificar usuários online: {e}")

        # Update status (from global)
        update_avail = False
        if current_user.role in ['admin', 'supervisor']:
            # Ensure UPDATE_STATE is read safely
            global UPDATE_STATE
            update_avail = UPDATE_STATE.get('available', False)

        return dict(
            reset_requests_count=count, 
            online_users=online_users,
            update_available=update_avail
        )
    except Exception as e:
        logging.error(f"Erro crítico no processador de contexto: {e}")
        # Return harmless empty dict to avoid 500
        return {}

@app.before_request
def update_last_seen():
    if current_user.is_authenticated:
        now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        try:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("UPDATE users SET last_seen = ? WHERE id = ?", (now, current_user.id))
            conn.commit()
            conn.close()
        except:
            pass

@app.before_request
def make_session_permanent():
    session.permanent = True
    app.permanent_session_lifetime = timedelta(seconds=300)

@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    return response

# Removed manual CSRF protection in favor of Flask-WTF
# Previous manual implementation caused conflict and "CSRF Token missing" errors
# Flask-WTF handles token generation and validation automatically.

@app.before_request
def check_temporary_password():
    if current_user.is_authenticated and current_user.is_temporary_password:
        # List of allowed endpoints when in temporary password state
        allowed_endpoints = ['alterar_senha', 'logout', 'static']
        if request.endpoint not in allowed_endpoints:
            return redirect(url_for('alterar_senha'))

# ==============================
# ROTAS
# ==============================

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        user = User.get_by_username(username)
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            logger.info(f"Login bem-sucedido: {username} (role: {user.role})")
            if user.is_temporary_password:
                return redirect(url_for("alterar_senha"))
            return redirect(url_for("index"))
        
        logger.warning(f"Tentativa de login falhou: {username}")
        flash("Usuário ou senha inválidos", "danger")

    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logger.info(f"Logout: {current_user.username}")
    logout_user()
    return redirect(url_for("login"))

@app.route("/recuperar_senha", methods=["GET", "POST"])
def recuperar_senha():
    if request.method == "POST":
        username = request.form.get("username")
        name = request.form.get("name")
        
        conn = get_conn()
        cur = conn.cursor()
        
        # Check if user exists (optional, maybe security risk to reveal? but requested flow implies it)
        # Requirement: "preenche nome e login para solicitar"
        
        now = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=4)).isoformat()
        cur.execute("INSERT INTO password_resets (username, name, status, created_at) VALUES (?, ?, 'PENDENTE', ?)",
                    (username, name, now))
        conn.commit()
        conn.close()
        
        logger.info(f"Recuperação de senha: Solicitação criada para usuário '{username}' (nome: {name})")
        flash("Solicitação enviada. Entre em contato com um administrador.", "success")
        return redirect(url_for("login"))
        
    return render_template("recuperar_senha.html")

@app.route("/privacidade")
def privacidade():
    return render_template("privacidade.html")

@app.route("/termos")
def termos():
    return render_template("termos.html")

@app.route("/importar", methods=["GET", "POST"])
@login_required
def importar_arquivo():
    if request.method == "POST":
        # Check if AJAX/API Mode
        is_ajax = request.form.get("mode") == "ajax"
        overwrite = request.form.get("overwrite") == "true"
        
        # Helper to return JSON or Flash+Redirect
        def response(status, msg, matricula=None, **kwargs):
            if is_ajax:
                return jsonify({"status": status, "message": msg, "matricula": matricula, **kwargs})
            else:
                flash(msg, "success" if status == "success" else "danger")
                return redirect(request.url)

        if 'arquivo' not in request.files:
            return response("error", "Nenhum arquivo enviado")
        
        # Logic for multiple files (Legacy/Form) or Single file (AJAX)
        files = request.files.getlist('arquivo')
        if not files or files[0].filename == '':
             return response("error", "Nenhum arquivo selecionado")

        # For AJAX, we expect 1 file per request usually, but let's handle the loop if sent multiple
        # or just process the first one if we design the frontend to send one by one.
        # Design decision: Frontend sends one by one. Backend processes list (always list).
        
        results = []
        for file in files:
            res = {'filename': file.filename, 'success': False}
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                
                try:
                    # 1. PARSE FILENAME to MATRICULA
                    # Validation: strip zeros, must be > 1
                    # Pattern: match digits at start or just digits?
                    # User said: "Vincular o nome do arquivo como numero da matricula... Remover zeros à esquerda e validar somente números > 1."
                    # Assuming filename IS the number like 00050.tif
                    basename = os.path.splitext(filename)[0] # 00050
                    matricula_from_file = None
                    
                    # Regex to find number. If strict "name IS number":
                    match = re.search(r'(\d+)', basename)
                    if match:
                        raw_num = match.group(1)
                        int_num = int(raw_num)
                        if int_num > 1:
                            matricula_from_file = str(int_num) # "50"
                        else:
                             # Should we error or continue? User said "apresentar mensagem que o campo esta incorreto"
                             # But this is auto-extraction.
                             pass
                    
                    txt = ocr_file_to_text(filepath)
                    data = parse_text_to_dict(txt)
                    
                    # IAGO ANALYSIS
                    ia_data = iago.analyze(txt)
                    for k, v in ia_data.items():
                         if v: 
                             data[k] = v
                    
                    # OVERRIDE/SET Matricula from Filename if valid
                    if matricula_from_file:
                        data["NUMERO_REGISTRO"] = matricula_from_file
                    
                    matricula = data.get("NUMERO_REGISTRO")
                    if not matricula:
                         # Fail if we can't get a matricula?
                         # Or just save as is?
                         pass

                    # DUPLICATE CHECK
                    if matricula:
                        conn = get_conn()
                        cur = conn.cursor()
                        cur.execute("SELECT id FROM imoveis WHERE numero_registro = ?", (matricula,))
                        existing = cur.fetchone()
                        conn.close()
                        
                        if existing and not overwrite:
                            return response("duplicate", f"Matrícula {matricula} já existe.", matricula=matricula)
                        
                        if existing and overwrite:
                            conn = get_conn()
                            cur = conn.cursor()
                            cur.execute("DELETE FROM imoveis WHERE id=?", (existing[0],))
                            conn.commit()
                            conn.close()

                    nid = save_dict_to_db_web(data, tiff_path=filepath, ocr_text=txt)
                    
                    logger.info(f"Importação: {current_user.username} importou arquivo '{filename}' (Matrícula: {matricula})")
                    res['success'] = True
                    res['matricula'] = matricula
                except Exception as e:
                    res['error'] = str(e)
                    print(f"Error importing {filename}: {e}")
                    if is_ajax: return response("error", str(e))
            else:
                res['error'] = "Arquivo inválido"
                if is_ajax: return response("error", "Arquivo inválido")
            
            results.append(res)

        if is_ajax:
            return response("success", "Importado com sucesso", matricula=results[0].get('matricula'))

        # Fallback for standard form (if ever used)
        success_count = sum(1 for r in results if r['success'])
        error_count = len(results) - success_count
        return render_template("import_resumo.html", total_files=len(files), success_count=success_count, error_count=error_count, details=results)

    return render_template("importar.html")

@app.route("/", methods=["GET", "POST"])
@login_required
def index():
    # Filtering
    filtro_status = request.args.get('status', 'todos') 
    q = request.args.get("q", "").strip()

    conn = get_conn()
    cur = conn.cursor()

    where_clauses = []
    params = []

    if q:
        if q.isdigit():
             where_clauses.append("(numero_registro = ? OR cep LIKE ?)")
             params.extend([q, f"%{q}%"])
        else:
             where_clauses.append("(nome_logradouro LIKE ? OR bairro LIKE ?)")
             params.extend([f"%{q}%", f"%{q}%"])
        
        # Audit Log for Search
        query_log = q
        if len(query_log) > 50: query_log = query_log[:47] + "..."
        logger.info(f"Busca: {current_user.username} buscou por '{query_log}'")
    
    if filtro_status == 'pendentes':
        where_clauses.append("(status_trabalho IS NULL OR status_trabalho != 'CONCLUIDO')")
    elif filtro_status == 'concluidos':
        where_clauses.append("status_trabalho = 'CONCLUIDO'")
    
    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)
    
    # Ordering: Non-concluded (0) first, then Concluded (1). Then Matricula Int ASC.
    sql = f"""
        SELECT 
            i.id, i.numero_registro, i.nome_logradouro, i.bairro, i.status_trabalho, i.concluded_by,
            l.editing_by, l.editing_since
        FROM imoveis i
        LEFT JOIN imoveis_lock l ON i.id = l.imovel_id
        {where_sql}
        ORDER BY 
            CASE WHEN i.status_trabalho = 'CONCLUIDO' THEN 1 ELSE 0 END ASC,
            CAST(i.numero_registro AS INTEGER) ASC
    """
    
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()

    imoveis = []
    for r in rows:
        # Determine Lock Status
        is_locked = False
        locked_by_me = False
        status_texto = "Livre"
        
        if r["editing_by"]:
            is_locked = True
            if r["editing_by"] == current_user.username:
                locked_by_me = True
            status_texto = f"Em edição por {r['editing_by']}"

        imoveis.append({
            "id": r["id"],
            "numero_registro": r["numero_registro"],
            "nome_logradouro": r["nome_logradouro"],
            "bairro": r["bairro"],
            "status": r["status_trabalho"] or "PENDENTE",
            "concluded_by": r["concluded_by"],
            "is_locked": is_locked,
            "locked_by_me": locked_by_me,
            "status_texto": status_texto,
            "status_trabalho": r["status_trabalho"] or "PENDENTE"
        })

    return render_template("index.html", imoveis=imoveis, q=q, filtro_status=filtro_status)

@app.route("/dashboard")
@login_required
def dashboard():
    if current_user.role == 'colaborador':
        flash("Acesso negado.", "danger")
        return redirect(url_for("index"))
        
    conn = get_conn()
    cur = conn.cursor()
    
    # Stats
    cur.execute("SELECT COUNT(*) FROM imoveis")
    total = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM imoveis WHERE status_trabalho='CONCLUIDO'")
    concluidos = cur.fetchone()[0]
    
    pendentes = total - concluidos
    
    # Desempenho (simulado por logs de edição, mais complexo, vamos simplificar para total por usuario)
    # Como não temos log de quem fez o que persistente além do lock, vamos deixar placeholder.
    
    conn.close()
    
    return render_template("dashboard.html", total=total, concluidos=concluidos, pendentes=pendentes)

@app.route("/configuracao/email", methods=["GET", "POST"])
@login_required
def config_email():
    if current_user.role != 'admin':
        flash("Acesso não autorizado.", "error")
        return redirect(url_for('index'))

    conn = get_conn()
    cur = conn.cursor()

    if request.method == "POST":
        action = request.form.get("action")
        settings = {
            "smtp_server": request.form.get("smtp_server"),
            "smtp_port": request.form.get("smtp_port"),
            "smtp_user": request.form.get("smtp_user"),
            "smtp_password": request.form.get("smtp_password")
        }

        # Save settings
        for key, val in settings.items():
            cur.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES (?, ?)", (key, val))
        conn.commit()

        logger.info(f"Configuração: {current_user.username} atualizou configurações de email")
        
        if action == "test":
            # Test sending email to self
            success = email_service.send_email_sync(
                settings["smtp_user"], 
                "Teste de Configuração - Sistema ONR", 
                "<p>Configuração de e-mail realizada com sucesso!</p>"
            )
            if success:
                flash("Configurações salvas e e-mail de teste enviado com sucesso!", "success")
            else:
                flash("Configurações salvas, mas FALHA ao enviar e-mail de teste. Verifique os dados.", "error")
        else:
            flash("Configurações de e-mail salvas com sucesso.", "success")
        
        conn.close()
        return redirect(url_for('config_email'))

    # Load current settings
    cur.execute("SELECT key, value FROM system_config")
    rows = cur.fetchall()
    config = {row[0]: row[1] for row in rows}
    conn.close()

    return render_template("config_email.html", config=config)


@app.route("/atualizacoes", methods=["GET", "POST"])
@login_required
def atualizacoes():
    if current_user.role not in ['admin', 'supervisor']:
        flash("Acesso não autorizado.", "error")
        return redirect(url_for('index'))
    
    global UPDATE_STATE
    
    changelog = []
    current_version = updater.get_current_version_hash()
    
    if request.method == "POST":
        action = request.form.get("action")
        
        if action == "check":
            res = updater.check_for_updates()
            if res and not res.get('error'):
                UPDATE_STATE['available'] = res['update_available']
                UPDATE_STATE['commits_behind'] = res['commits_behind']
                UPDATE_STATE['last_check'] = datetime.now().isoformat()
                
                logger.info(f"Atualização: {current_user.username} verificou atualizações (disponível: {res['update_available']})")
                
                if res['update_available']:
                    flash(f"Nova versão encontrada! {res['commits_behind']} commits atrás.", "info")
                    changelog = res.get('changelog', [])
                else:
                    flash("O sistema já está atualizado.", "success")
            else:
                flash("Erro ao verificar atualizações.", "error")
                
        elif action == "update":
            success, msg = updater.perform_update()
            if success:
                logger.info(f"Atualização: {current_user.username} aplicou atualização do sistema com sucesso")
                flash(f"Atualização realizada com sucesso! {msg}. Reinicie o servidor para aplicar.", "success")
                # Reset state
                UPDATE_STATE['available'] = False
            else:
                logger.error(f"Atualização: {current_user.username} tentou aplicar atualização mas falhou: {msg}")
                flash(f"Falha na atualização: {msg}", "error")
            return redirect(url_for('atualizacoes'))

    # If GET, try to get changelog if available
    if UPDATE_STATE['available']:
        # Fetch detailed info again to show log
        res = updater.check_for_updates()
        if res:
            changelog = res.get('changelog', [])
            
    return render_template("atualizacoes.html", 
                         state=UPDATE_STATE, 
                         current_version=current_version,
                         changelog=changelog)


@app.route("/admin/logs", methods=["GET", "POST"])
@login_required
def admin_logs():
    """Admin page to view system logs with filtering."""
    if current_user.role != 'admin':
        flash("Acesso não autorizado.", "error")
        return redirect(url_for('index'))
    
    # Handle POST actions (clear logs)
    if request.method == "POST":
        action = request.form.get("action")
        if action == "clear":
            try:
                # Clear the log file
                with open(LOG_FILE, 'w') as f:
                    f.write("")
                logger.info(f"Logs limpos por {current_user.username}")
                flash("Logs limpos com sucesso!", "success")
            except Exception as e:
                flash(f"Erro ao limpar logs: {e}", "error")
        return redirect(url_for('admin_logs'))
    
    # Get filter parameters
    num_lines = request.args.get('lines', '100', type=str)
    level_filter = request.args.get('level', 'ALL', type=str)
    search_query = request.args.get('search', '', type=str)
    
    # Validate num_lines
    try:
        num_lines_int = int(num_lines)
        if num_lines_int < 1:
            num_lines_int = 100
        elif num_lines_int > 2000: # Limit max for performance
            num_lines_int = 2000
    except ValueError:
        num_lines_int = 100
    
    # Read log file
    logs = []
    try:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, 'r', encoding='utf-8', errors='replace') as f:
                # Read all lines first to handle multiline entries correctly (reverse later)
                all_lines = f.readlines()
                
            parsed_logs = []
            current_entry = None
            
            # Regex for standard log format: YYYY-MM-DD HH:MM:SS - LEVEL - [module] - message
            # Matches: 2024-05-20 15:30:00 - INFO - [imoveis_web] - Some message
            log_pattern = re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) - (\w+) - \[(.*?)\] - (.*)$')
            
            for line in all_lines:
                line = line.rstrip()
                if not line:
                    continue
                    
                match = log_pattern.match(line)
                if match:
                    # New log entry found
                    if current_entry:
                        parsed_logs.append(current_entry)
                    
                    timestamp_str, level, module, message = match.groups()
                    current_entry = {
                        'timestamp': timestamp_str,
                        'level': level,
                        'module': module,
                        'message': message,
                        'raw': line
                    }
                else:
                    # Continuation of previous entry (e.g. stack trace)
                    if current_entry:
                        current_entry['message'] += "\n" + line
                        current_entry['raw'] += "\n" + line
                    else:
                        # Orphan line (shouldn't happen often if file starts clean)
                        current_entry = {
                            'timestamp': '',
                            'level': 'UNKNOWN',
                            'module': '?',
                            'message': line,
                            'raw': line
                        }

            # Add the last entry
            if current_entry:
                parsed_logs.append(current_entry)
            
            # Apply filters and limit
            
            # We filter FIRST, then slice, or Slice then filter?
            # It's better to filter first to ensure we get 'num_lines_int' MATCHING logs
            # But specific requirement was likely "last N lines of file" vs "last N matching logs"
            # However, usually users want to see the last N relevant events.
            
            # Let's filter first
            filtered_logs = []
            
            # Reverse to process newest first
            parsed_logs.reverse()
            
            # Log Translation Dictionary (Regex -> Replacement)
            # Order matters: Specific matches first
            TRANSLATION_MAP = [
                (r"Checking for updates.*", "Verificando atualizações de sistema..."),
                (r"Update available! Behind by (\d+) commits.*", r"Nova atualização disponível! Atrasado em \1 versões."),
                (r"Error in scheduled check: (.*)", r"Erro na verificação agendada: \1"),
                (r"Sistema Indicador Real - Iniciando.*", "Sistema Iniciado."),
                (r"OCR ERROR.*Details: (.*)", r"Erro de OCR. Detalhes: \1"),
                (r"Error checking password resets: (.*)", r"Erro ao verificar redefinições de senha: \1"),
                (r"Error checking online users: (.*)", r"Erro ao verificar usuários online: \1"),
                (r"Critical error in context_processor: (.*)", r"Erro crítico no processador de contexto: \1"),
                (r"Logs limpos por (.*)", r"Logs apagados pelo usuário: \1"),
                (r"Error converting TIFF to PDF: (.*)", r"Erro ao converter imagem TIFF para PDF: \1"),
                (r"pdf2image failed.*", "Falha na biblioteca pdf2image. Verifique se o Poppler está instalado corretamente."),
                (r"Restarting.*", "Reiniciando sistema..."),
                (r".*HTTP.* 200 .*", "Requisição HTTP com sucesso (200)"),
                (r".*HTTP.* 404 .*", "Página não encontrada (404)"),
                (r".*HTTP.* 500 .*", "Erro interno do servidor (500)"),
                (r"Visualização: (.*) visualizou imóvel ID (\d+).*", r"Acesso: \1 abriu a matrícula ID \2"),
                (r"Edição: (.*) editou imóvel ID (\d+).*", r"Edição: \1 alterou dados da matrícula ID \2"),
                (r"Conclusão: (.*) concluiu imóvel ID (\d+).*", r"Conclusão: \1 finalizou a matrícula ID \2"),
            ]

            def translate_message(msg):
                for pattern, replacement in TRANSLATION_MAP:
                    if re.match(pattern, msg, re.IGNORECASE):
                        return re.sub(pattern, replacement, msg, flags=re.IGNORECASE)
                return None

            for log in parsed_logs:
                # Filter by level
                if level_filter != 'ALL':
                    if log['level'] != level_filter:
                        continue
                
                # Filter by search query
                if search_query:
                    query = search_query.lower()
                    if (query not in log['message'].lower() and 
                        query not in log['module'].lower()):
                        continue
                
                # Apply translation
                translation = translate_message(log['message'])
                log['translated_message'] = translation
                
                filtered_logs.append(log)
                
                if len(filtered_logs) >= num_lines_int:
                    break
            
            logs = filtered_logs
            
    except Exception as e:
        flash(f"Erro ao ler logs: {e}", "error")
        # Fallback to simple error log
        logs = [{'timestamp': '', 'level': 'ERROR', 'module': 'system', 'message': f'Erro ao processar arquivo de log: {str(e)}', 'raw': str(e)}]
    
    return render_template("admin_logs.html", 
                         logs=logs,
                         num_lines=num_lines,
                         level_filter=level_filter,
                         search_query=search_query,
                         log_file_exists=os.path.exists(LOG_FILE))



# ==============================
# IAGO API (For Networked Learning)
# ==============================

@app.route("/api/iago/learn", methods=["POST"])
# No login_required for now to simplify machine-to-machine, 
# or use a shared secret if needed later. 
# Ideally: @login_required but usage is typically automated.
def api_iago_learn():
    data = request.json
    if not data:
        return {"error": "No data"}, 400
        
    full_text = data.get("full_text")
    current_data = data.get("current_data")
    
    # We call the LOCAL iago.learn logic
    # Note: On the server, iago should use local DB or IAGO_DB_PATH
    count = iago.learn(full_text, current_data)
    
    return {"status": "ok", "learned_count": count}

@app.route("/api/iago/analyze", methods=["POST"])
def api_iago_analyze():
    data = request.json
    full_text = data.get("full_text")
    
    # We call LOCAL iago.analyze
    result = iago.analyze(full_text)
    
    return result

@app.route("/usuarios", methods=["GET", "POST"])
@login_required
def usuarios():
    # Apenas admin ou supervisor pode acessar
    if current_user.role not in ['admin', 'supervisor']:
        flash("Acesso não autorizado.", "error")
        return redirect(url_for('index'))

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        role = request.form.get("role")
        whatsapp = request.form.get("whatsapp")
        email = request.form.get("email") # New field
        nome_completo = request.form.get("nome_completo")
        cpf = request.form.get("cpf")

        # Apenas admin pode criar admin/supervisor
        if role in ['admin', 'supervisor'] and current_user.role != 'admin':
            flash("Somente administradores podem criar supervisores ou outros admins.", "error")
            return redirect(url_for('usuarios'))

        password_hash = generate_password_hash(password)
        
        conn = get_conn()
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO users (username, password_hash, role, whatsapp, email, nome_completo, cpf) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (username, password_hash, role, whatsapp, email, nome_completo, cpf)
            )
            conn.commit()
            logger.info(f"Usuário criado: {current_user.username} criou novo usuário '{username}' (role: {role})")
            flash(f"Usuário {username} criado com sucesso.", "success")
            
            # Notify New User
            if email:
                email_service.notify_user_created(email, username, password)
                flash(f"E-mail de boas-vindas enviado para {email}.", "info")
            
            # Notify Admins
            try:
                admin_emails = get_admin_emails()
                if admin_emails:
                    email_service.notify_admin_new_user(admin_emails, username, current_user.username)
            except Exception as e:
                print(f"Erro ao notificar admins: {e}")
            
        except sqlite3.IntegrityError as e:
            err_msg = str(e)
            if "cpf" in err_msg.lower():
                flash("CPF já cadastrado.", "error")
            elif "username" in err_msg.lower():
                 flash("Nome de usuário já existe.", "error")
            else:
                 flash(f"Erro de integridade (duplicidade): {e}", "error")

        conn.close()
        return redirect(url_for('usuarios'))

    conn = get_conn()
    cur = conn.cursor()
    # Fetch all fields to display
    try:
        cur.execute("SELECT id, username, role, created_at, email, nome_completo, cpf FROM users") 
    except:
        cur.execute("SELECT id, username, role, created_at, email, NULL as nome_completo, NULL as cpf FROM users")

    users = cur.fetchall()
    conn.close()
    return render_template("usuarios.html", users=users)

@app.route("/usuarios/editar/<int:user_id>", methods=["GET", "POST"])
@login_required
def editar_usuario(user_id):
    # Regra: Admin edita qualquer um. Supervisor edita colab e supervisor? "quando supervisor ele pode editar" - assumindo todos ou niveis abaixo?
    # Vamos permitir supervisor editar qualquer perfil (exceto promover para admin se nao for admin)
    if current_user.role not in ['admin', 'supervisor']:
        flash("Acesso negado.", "danger")
        return redirect(url_for("index"))
        
    conn = get_conn()
    cur = conn.cursor()
    
    if request.method == "POST":
        novo_nome = request.form.get("username")
        whatsapp = request.form.get("whatsapp")
        reset_senha = request.form.get("reset_senha") # checkbox or just blank field? "resetar a senha" implies setting a new one or random
        nova_senha_manual = request.form.get("nova_senha")
        
        # Update fields
        cur.execute("UPDATE users SET username=?, whatsapp=? WHERE id=?", (novo_nome, whatsapp, user_id))
        
        if nova_senha_manual and nova_senha_manual.strip():
             hashed = generate_password_hash(nova_senha_manual.strip())
             # supervisor reset sets specific or random? User request: "resetar a senha". 
             # Lets allow manual input. If they fill it, we change it.
             # Also, should we set temporary? Request doesn't specify, but usually "reset" by admin means temporary.
             # Let's set temporary=1 to force change.
             cur.execute("UPDATE users SET password_hash=?, is_temporary_password=1 WHERE id=?", (hashed, user_id))
             logger.info(f"Usuário editado: {current_user.username} editou usuário ID {user_id} ('{novo_nome}') e resetou senha")
             flash("Dados atualizados e senha resetada.", "success")
        else:
             logger.info(f"Usuário editado: {current_user.username} editou usuário ID {user_id} ('{novo_nome}')")
             flash("Dados atualizados.", "success")
             
        conn.commit()
        conn.close()
        return redirect(url_for("usuarios"))

    cur.execute("SELECT * FROM users WHERE id=?", (user_id,))
    u = cur.fetchone()
    conn.close()
    
    if not u:
        flash("Usuário não encontrado.", "danger")
        return redirect(url_for("usuarios"))
        
    return render_template("usuario_editar.html", user=u)


@app.route("/perfil", methods=["GET", "POST"])
@login_required
def perfil():
    if request.method == "POST":
        whatsapp = request.form.get("whatsapp")
        
        file = request.files.get('foto')
        filename_db = current_user.profile_image
        
        if file and file.filename != '':
            if allowed_file(file.filename) or file.filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                 filename = secure_filename(f"user_{current_user.id}_{file.filename}")
                 filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                 file.save(filepath)
                 filename_db = filename
            else:
                 flash("Formato de imagem inválido.", "warning")

        conn = get_conn()
        cur = conn.cursor()
        cur.execute("UPDATE users SET whatsapp=?, profile_image=? WHERE id=?", (whatsapp, filename_db, current_user.id))
        conn.commit()
        conn.close()
        
        flash("Perfil atualizado.", "success")
        return redirect(url_for("index"))

    return render_template("perfil.html", user=current_user)


@app.route("/usuarios/excluir/<int:user_id>", methods=["POST"])
@login_required
def excluir_usuario(user_id):
    if current_user.role != 'admin':
        flash("Apenas administradores podem excluir usuários.", "danger")
        return redirect(url_for("usuarios"))
        
    conn = get_conn()
    cur = conn.cursor()
    # Get username before deleting
    cur.execute("SELECT username FROM users WHERE id=?", (user_id,))
    row = cur.fetchone()
    username = row['username'] if row else 'N/A'
    
    cur.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
    logger.warning(f"Usuário excluído: {current_user.username} excluiu usuário ID {user_id} ('{username}')")
    flash("Usuário excluído.", "success")
    return redirect(url_for("usuarios"))


@app.route("/imovel/<int:imovel_id>/excluir", methods=["POST"])
@login_required
def excluir_imovel(imovel_id):
    if current_user.role != 'admin':
        flash("Apenas administradores podem excluir matrículas.", "danger")
        return redirect(url_for("index"))
    
    # Get matricula number before deleting
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT numero_registro FROM imoveis WHERE id=?", (imovel_id,))
    row = cur.fetchone()
    matricula = row['numero_registro'] if row else 'N/A'
    
    # Delete file if possible? User didn't ask, but good practice.
    # However, kept simple to just db delete as requested "Admin pode exclui matricula".
    cur.execute("DELETE FROM imoveis_lock WHERE imovel_id=?", (imovel_id,))
    cur.execute("DELETE FROM imoveis WHERE id=?", (imovel_id,))
    conn.commit()
    conn.close()
    
    logger.warning(f"Exclusão: {current_user.username} excluiu imóvel ID {imovel_id} (Matrícula: {matricula})")
    flash("Matrícula excluída com sucesso.", "success")
    return redirect(url_for("index"))

@app.route("/imovel/<int:imovel_id>/concluir", methods=["POST"])
@login_required
def concluir_imovel(imovel_id):
    # 1. Save changes first (Logic copied from editar_imovel)
    form = request.form
    campos = {}
    campos["numero_registro"] = form.get("NUMERO_REGISTRO", "").strip()
    campos["nome_logradouro"] = form.get("NOME_LOGRADOURO", "").strip()
    campos["numero_logradouro"] = form.get("NUMERO_LOGRADOURO", "").strip()

    cidade_raw = form.get("CIDADE", "").strip()
    campos["cidade"] = int(cidade_raw) if cidade_raw else 0

    campos["bairro"] = form.get("BAIRRO", "").strip()
    campos["cep"] = form.get("CEP", "").strip()
    campos["complemento"] = form.get("COMPLEMENTO", "").strip()
    campos["quadra"] = form.get("QUADRA", "").strip()
    campos["conjunto"] = form.get("CONJUNTO", "").strip()
    campos["setor"] = form.get("SETOR", "").strip()
    campos["lote"] = form.get("LOTE", "").strip()
    campos["loteamento"] = form.get("LOTEAMENTO", "").strip()
    campos["varios_enderecos"] = form.get("VARIOS_ENDERECOS", "").strip().upper()

    # Rural Fields
    campos["rural_car"] = form.get("RURAL_CAR", "").strip()
    campos["rural_nirf"] = form.get("RURAL_NIRF", "").strip()
    campos["rural_ccir"] = form.get("RURAL_CCIR", "").strip()
    campos["rural_numero_incra"] = form.get("RURAL_NUMERO_INCRA", "").strip()
    campos["rural_sigef"] = form.get("RURAL_SIGEF", "").strip()
    campos["rural_denominacaorural"] = form.get("RURAL_DENOMINACAORURAL", "").strip()
    campos["rural_acidentegeografico"] = form.get("RURAL_ACIDENTEGEOGRAFICO", "").strip()

    # Condominio Fields
    campos["condominio_nome"] = form.get("CONDOMINIO_NOME", "").strip()
    campos["condominio_bloco"] = form.get("CONDOMINIO_BLOCO", "").strip()
    campos["condominio_conjunto"] = form.get("CONDOMINIO_CONJUNTO", "").strip()
    campos["condominio_torre"] = form.get("CONDOMINIO_TORRE", "").strip()
    campos["condominio_apto"] = form.get("CONDOMINIO_APTO", "").strip()
    campos["condominio_vaga"] = form.get("CONDOMINIO_VAGA", "").strip()

    contrib_raw = form.get("CONTRIBUINTE", "").strip()
    # Need parse_contribuinte (helper defined in file)
    contrib_list = parse_contribuinte(contrib_raw)
    campos["contribuinte"] = json.dumps(contrib_list)

    # combos
    def combo_int(name, default):
        raw = form.get(name, "").strip()
        return int(raw) if raw.isdigit() else default

    campos["registro_tipo"] = combo_int("REGISTRO_TIPO", 1)
    campos["localizacao"] = combo_int("LOCALIZACAO", 0)
    campos["tipo_de_imovel"] = combo_int("TIPO_DE_IMOVEL", 1)
    campos["tipo_logradouro"] = combo_int("TIPO_LOGRADOURO", 250)
    campos["uf"] = combo_int("UF", 13)

    conn = get_conn()
    cur = conn.cursor()
    
    # Save Data
    sets = []
    vals = []
    for k, v in campos.items():
        sets.append(f"{k}=?")
        vals.append(v)
    vals.append((datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=4)).isoformat())
    vals.append(imovel_id)
    
    # Update data + status + concluded_by
    # We can do it in two queries or one? One is better but 'sets' is dynamic.
    # Let's run the update of data first
    sql_update = f"UPDATE imoveis SET {', '.join(sets)}, updated_at=? WHERE id=?"
    cur.execute(sql_update, vals)

    # 2. Existing Conclude Logic
    # Fetch for learning (freshly updated data is better, or old? logic used 'row' before update previously?)
    # Logic: Read *after* update to teach AI final state.
    cur.execute("SELECT * FROM imoveis WHERE id=?", (imovel_id,))
    row = cur.fetchone()
    if row:
        current_data = dict(row)
        ocr_text = row["ocr_text"] if "ocr_text" in row.keys() else ""
        learned_count = iago.learn(ocr_text, current_data)
        if learned_count > 0:
            print(f"IAGO: Aprendeu {learned_count} novos padrões do Imóvel {imovel_id}")

    cur.execute("UPDATE imoveis SET status_trabalho='CONCLUIDO', concluded_by=? WHERE id=?", (current_user.username, imovel_id))
    conn.commit()
    conn.close()
    
    clear_lock(imovel_id)
    logger.info(f"Conclusão: {current_user.username} concluiu imóvel ID {imovel_id} (Matrícula: {campos['numero_registro']})")
    flash("Matrícula salva e marcada como concluída.", "success")
    return redirect(url_for("index"))

@app.route("/imovel/<int:imovel_id>/reabrir", methods=["POST"])
@login_required
def reabrir_imovel(imovel_id):
    if current_user.role not in ['admin', 'supervisor']:
        flash("Acesso negado.", "danger")
        return redirect(url_for("index"))

    conn = get_conn()
    cur = conn.cursor()
    # Get matricula number
    cur.execute("SELECT numero_registro FROM imoveis WHERE id=?", (imovel_id,))
    row = cur.fetchone()
    matricula = row['numero_registro'] if row else 'N/A'
    # Reset status and concluded_by
    cur.execute("UPDATE imoveis SET status_trabalho='PENDENTE', concluded_by=NULL WHERE id=?", (imovel_id,))
    conn.commit()
    conn.close()
    logger.info(f"Reabertura: {current_user.username} reabriu imóvel ID {imovel_id} (Matrícula: {matricula})")
    flash("Matrícula reaberta.", "success")
    return redirect(url_for("index"))
    
@app.route("/imovel/<int:imovel_id>/iago_reanalisar", methods=["GET"])
@login_required
def iago_reanalisar(imovel_id):
    """Reanalisa o imóvel usando padrões aprendidos pela IA."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM imoveis WHERE id=?", (imovel_id,))
    row = cur.fetchone()
    
    if not row:
        conn.close()
        flash("Imóvel não encontrado.", "danger")
        return redirect(url_for("index"))
        
    ocr_text = row["ocr_text"]
    if not ocr_text:
        conn.close()
        flash("Este imóvel não possui texto OCR salvo para análise.", "warning")
        return redirect(url_for("editar_imovel", imovel_id=imovel_id))
        
    # Analyze
    ia_data = iago.analyze(ocr_text)
    
    if not ia_data:
        conn.close()
        flash("IAGO não encontrou novas informações com os padrões atuais.", "info")
        return redirect(url_for("editar_imovel", imovel_id=imovel_id))
        
    # Update found fields
    # Only update if field is currently empty? Or overwrite? 
    # User asked to "reanalyze", implies they want the AI result.
    # Let's update and flash what changed.
    
    changes = []
    current_data = dict(row)
    
    logger.info(f"IAGO Reanálise: {current_user.username} solicitou reanálise do imóvel ID {imovel_id} (Matrícula: {row['numero_registro']})")
    
    # Construct update query dynamically? No, safer to update known fields.
    # We need to map IAGO keys to DB columns.
    # IAGO keys are uppercase usually (from patterns table 'field_name')
    # DB columns are lowercase.
    
    update_pairs = []
    params = []
    
    for k, v in ia_data.items():
        col_name = k.lower()
        # Check if this column exists in our simplified list of updateable fields
        # Ideally we should verify against schema, but let's stick to the main ones we learn
        if col_name in current_data:
            old_val = str(current_data[col_name] or "")
            new_val = str(v)
            if old_val != new_val:
                update_pairs.append(f"{col_name}=?")
                params.append(new_val)
                changes.append(f"{k}: {new_val}")
                
    if update_pairs:
        sql = f"UPDATE imoveis SET {', '.join(update_pairs)} WHERE id=?"
        params.append(imovel_id)
        cur.execute(sql, tuple(params))
        conn.commit()
        msg = f"IAGO atualizou: {', '.join(changes)}"
        cat = "success"
    else:
        msg = "IAGO analisou mas os dados atuais já conferem com os padrões."
        cat = "info"
        
    conn.close()
    flash(msg, cat)
    return redirect(url_for("editar_imovel", imovel_id=imovel_id))

@app.route("/imovel/<int:imovel_id>/popup")
@login_required
def visualizar_popup(imovel_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM imoveis WHERE id=?", (imovel_id,))
    row = cur.fetchone()
    conn.close()
    
    if not row:
        return "Imóvel não encontrado", 404
        
    return render_template("popup_imovel.html", imovel_id=imovel_id, dados=row)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM imoveis WHERE id=?", (imovel_id,))
    row = cur.fetchone()
    conn.close()
    
    if not row:
        return "Imóvel não encontrado", 404
        
    return render_template("popup_imovel.html", imovel_id=imovel_id, dados=row)

def tiff_to_pdf_bytes(path):
    img = Image.open(path)
    images = []
    try:
        while True:
            # Convert to RGB to ensure PDF compatibility
            if img.mode != 'RGB':
                images.append(img.convert('RGB'))
            else:
                images.append(img.copy())
            img.seek(img.tell() + 1)
    except EOFError:
        pass
    
    pdf_bytes = BytesIO()
    if images:
        images[0].save(pdf_bytes, save_all=True, append_images=images[1:], format="PDF")
    
    pdf_bytes.seek(0)
    return pdf_bytes

@app.route("/imovel/<int:imovel_id>/pdf")
@login_required
def ver_pdf_imovel(imovel_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT arquivo_tiff FROM imoveis WHERE id=?", (imovel_id,))
    row = cur.fetchone()
    conn.close()
    
    # Audit Log
    logger.info(f"Visualização: {current_user.username} visualizou PDF do imóvel ID {imovel_id}")
    
    if not row or not row["arquivo_tiff"]:
        return "Imagem não encontrada", 404
        
    path = row["arquivo_tiff"]
    if not os.path.exists(path):
        return "Arquivo físico não encontrado", 404
        
    # Convert and serve
    try:
        pdf_stream = tiff_to_pdf_bytes(path)
        return Response(pdf_stream, mimetype='application/pdf')
    except Exception as e:
        print(f"Erro ao converter TIFF para PDF: {e}")
        return "Erro ao processar imagem", 500

@app.route("/imovel/<int:imovel_id>/visualizar")
@login_required
def visualizar_imovel(imovel_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM imoveis WHERE id=?", (imovel_id,))
    row = cur.fetchone()
    conn.close()
    
    if not row:
        return {"error": "Not found"}, 404
    
    logger.info(f"Visualização: {current_user.username} visualizou imóvel ID {imovel_id} (Matrícula: {row['numero_registro']})")
    return dict(row)



@app.route("/imovel/<int:imovel_id>/editar", methods=["GET", "POST"])
@login_required
def editar_imovel(imovel_id):
    """Tela de edição da matrícula, com trava de edição."""
    init_lock_table()
    
    # 1. Check permissions first (Security Fix)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT status_trabalho FROM imoveis WHERE id=?", (imovel_id,))
    row_status = cur.fetchone()
    conn.close()
    
    if not row_status:
        flash("Imóvel não encontrado.", "danger")
        return redirect(url_for("index"))

    status = row_status["status_trabalho"] or "PENDENTE"
    
    # Check Locks
    locks = get_locks_dict()
    lock = locks.get(imovel_id)
    
    # Rule: Collaborators cannot edit COMPLETED or LOCKED BY OTHERS
    if current_user.role == 'colaborador':
        if status == 'CONCLUIDO':
             flash("Este imóvel já foi concluído. Apenas supervisores podem reabrir.", "warning")
             return redirect(url_for("index"))
             
        if lock:
             editing_by, _ = lock
             if editing_by != current_user.username:
                 flash(f"Este imóvel está em edição por {editing_by}. Aguarde a liberação.", "warning")
                 return redirect(url_for("index"))


    if request.method == "POST":
        # salvar alterações
        form = request.form

        campos = {}
        campos["numero_registro"] = form.get("NUMERO_REGISTRO", "").strip()
        campos["nome_logradouro"] = form.get("NOME_LOGRADOURO", "").strip()
        campos["numero_logradouro"] = form.get("NUMERO_LOGRADOURO", "").strip()

        cidade_raw = form.get("CIDADE", "").strip()
        campos["cidade"] = int(cidade_raw) if cidade_raw.isdigit() else 0

        campos["bairro"] = form.get("BAIRRO", "").strip()
        campos["cep"] = form.get("CEP", "").strip()
        campos["complemento"] = form.get("COMPLEMENTO", "").strip()
        campos["quadra"] = form.get("QUADRA", "").strip()
        campos["conjunto"] = form.get("CONJUNTO", "").strip()
        campos["setor"] = form.get("SETOR", "").strip()
        campos["lote"] = form.get("LOTE", "").strip()
        campos["loteamento"] = form.get("LOTEAMENTO", "").strip()
        campos["varios_enderecos"] = form.get("VARIOS_ENDERECOS", "").strip().upper()

        # Rural Fields
        campos["rural_car"] = form.get("RURAL_CAR", "").strip()
        campos["rural_nirf"] = form.get("RURAL_NIRF", "").strip()
        campos["rural_ccir"] = form.get("RURAL_CCIR", "").strip()
        campos["rural_numero_incra"] = form.get("RURAL_NUMERO_INCRA", "").strip()
        campos["rural_sigef"] = form.get("RURAL_SIGEF", "").strip()
        campos["rural_denominacaorural"] = form.get("RURAL_DENOMINACAORURAL", "").strip()
        campos["rural_acidentegeografico"] = form.get("RURAL_ACIDENTEGEOGRAFICO", "").strip()

        # Condominio Fields
        campos["condominio_nome"] = form.get("CONDOMINIO_NOME", "").strip()
        campos["condominio_bloco"] = form.get("CONDOMINIO_BLOCO", "").strip()
        campos["condominio_conjunto"] = form.get("CONDOMINIO_CONJUNTO", "").strip()
        campos["condominio_torre"] = form.get("CONDOMINIO_TORRE", "").strip()
        campos["condominio_apto"] = form.get("CONDOMINIO_APTO", "").strip()
        campos["condominio_vaga"] = form.get("CONDOMINIO_VAGA", "").strip()

        contrib_raw = form.get("CONTRIBUINTE", "").strip()
        contrib_list = parse_contribuinte(contrib_raw)
        campos["contribuinte"] = json.dumps(contrib_list)

        # combos
        def combo_int(name, default):
            raw = form.get(name, "").strip()
            return int(raw) if raw.isdigit() else default

        campos["registro_tipo"] = combo_int("REGISTRO_TIPO", 1)
        campos["localizacao"] = combo_int("LOCALIZACAO", 0)
        campos["tipo_de_imovel"] = combo_int("TIPO_DE_IMOVEL", 1)
        campos["tipo_logradouro"] = combo_int("TIPO_LOGRADOURO", 250)
        campos["uf"] = combo_int("UF", 13)

        # grava no banco
        conn = get_conn()
        cur = conn.cursor()
        sets = []
        vals = []
        for k, v in campos.items():
            sets.append(f"{k}=?")
            vals.append(v)
        vals.append((datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=4)).isoformat())
        vals.append(imovel_id)
        sql = f"UPDATE imoveis SET {', '.join(sets)}, updated_at=? WHERE id=?"
        cur.execute(sql, vals)
        conn.commit()
        conn.close()

        # libera trava
        clear_lock(imovel_id)
        logger.info(f"Edição: {current_user.username} editou imóvel ID {imovel_id} (Matrícula: {campos['numero_registro']})")
        flash("Matrícula atualizada com sucesso.", "success")
        return redirect(url_for("index"))

    # GET: carrega dados e cria/atualiza trava com USUARIO ATUAL
    usuario = current_user.username
    # Only set lock if not already locked by someone else (already checked above for collaborators, but good to be safe)
    # Check again if locked by other for admin info? 
    # Admin/Sup STEALS lock by design here if they proceed? Or should we warn?
    # Current behavior relies on "if allowed to be here, take the lock".
    set_lock(imovel_id, usuario)

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM imoveis WHERE id=?", (imovel_id,))
    row = cur.fetchone()
    conn.close()

    if not row:
        flash("Matrícula não encontrada.", "danger")
        return redirect(url_for("index"))

    # converte contribuinte de JSON
    contrib = []
    if row["contribuinte"]:
        try:
            contrib = json.loads(row["contribuinte"])
        except Exception:
            contrib = []

    ctx = {
        "imovel_id": imovel_id,
        "dados": row,
        "contrib_str": ", ".join(contrib),
        "registro_tipos": REGISTRO_TIPO_OPCOES,
        "localizacoes": LOCALIZACAO_OPCOES,
        "tipos_imovel": TIPO_IMOVEL_OPCOES,
        "ufs": UF_OPCOES,
        "tipos_logradouro": TIPO_LOGRADOURO_OPCOES,
        "usuario": usuario,
    }

    # Audit Log for View/Edit Screen Access
    logger.info(f"Visualização: {current_user.username} acessou tela de edição/detalhes do imóvel ID {imovel_id} (Matrícula: {row['numero_registro']})")

    return render_template("editar.html", **ctx)


@app.route("/imovel/<int:imovel_id>/liberar", methods=["POST"])
def liberar_imovel(imovel_id):
    """Libera a trava manualmente (botão na tela)."""
    clear_lock(imovel_id)
    logger.info(f"Liberação de trava: {current_user.username if current_user.is_authenticated else 'Sistema'} liberou trava do imóvel ID {imovel_id}")
    flash("Trava de edição liberada.", "info")
    return redirect(url_for("index"))




# ==============================
# BACKUP & SCHEDULER
# ==============================
import shutil
import threading
import time

def perform_backup(requester="Sistema"):
    """Creates a database backup and notifies admins."""
    try:
        backup_dir = "backups"
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)
            
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = f"imoveis_backup_{timestamp}.db"
        backup_path = os.path.join(backup_dir, backup_file)
        
        # Simple file copy backup
        shutil.copy2(DB_PATH, backup_path)
        
        # Notify
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT email FROM users WHERE role IN ('admin', 'supervisor') AND email IS NOT NULL AND email != ''")
        rows = cur.fetchall()
        conn.close()
        recipients = [r[0] for r in rows]
        
        size_mb = os.path.getsize(backup_path) / (1024 * 1024)
        msg = f"Backup Automático ({requester}) realizado.<br>Arquivo: {backup_file}<br>Tamanho: {size_mb:.2f} MB"
        
        email_service.notify_backup_status(True, msg, recipients)
        print(f"[BACKUP] Sucesso: {backup_path}")
        return True, backup_path
    
    except Exception as e:
        err_msg = f"Erro ao realizar backup: {e}"
        print(f"[BACKUP] Erro: {e}")
        
        # Notify Failure
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT email FROM users WHERE role IN ('admin', 'supervisor') AND email IS NOT NULL AND email != ''")
        rows = cur.fetchall()
        conn.close()
        recipients = [r[0] for r in rows]
        
        email_service.notify_backup_status(False, err_msg, recipients)
        return False, str(e)

@app.route("/backup")
@login_required
def backup_system():
    if current_user.role not in ['admin', 'supervisor']:
        flash("Acesso não autorizado.", "error")
        return redirect(url_for('index'))

    success, info = perform_backup(requester=f"Manual por {current_user.username}")
    
    if success:
        logger.info(f"Backup: {current_user.username} criou backup manual com sucesso")
        flash(f"Backup realizado com sucesso: {info}", "success")
    else:
        logger.error(f"Backup: {current_user.username} tentou criar backup manual mas falhou: {info}")
        flash(f"Falha no backup: {info}", "error")

    return redirect(url_for('config_email'))

def run_schedule():
    """Background thread to run tasks."""
    print(" [SCHEDULER] Iniciado. Verificando backup às 17h.")
    while True:
        now = datetime.now()
        # Check if it's 17:00 (5 PM)
        # Using a small window to ensure it runs but doesn't run multiple times if backup takes < 1 min
        # Better logic: Check if 17:00 <= time < 17:01 AND we haven't run yet? 
        # Simplest valid approach for robust app:
        # Sleep 60s. If hour=17 and minute=00, run.
        
        if now.hour == 17 and now.minute == 0:
            print(" [SCHEDULER] Executando Backup das 17h...")
            perform_backup(requester="Automático 17h")
            time.sleep(60) # Prevent multiple runs in the same minute
        else:
            time.sleep(30) # Check every 30s

# Start Scheduler
scheduler_thread = threading.Thread(target=run_schedule, daemon=True)
scheduler_thread.start()

# ==============================
# MAIN
# ==============================
from flask import send_file
from io import BytesIO
from PIL import Image
import os


@app.route("/imovel/<int:imovel_id>/ver_tiff")
def ver_tiff(imovel_id):
    """Converte o TIFF para PNG e exibe no navegador em uma nova aba."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT arquivo_tiff FROM imoveis WHERE id=?", (imovel_id,))
    row = cur.fetchone()
    conn.close()

    if not row or not row["arquivo_tiff"]:
        flash("Nenhum arquivo TIFF encontrado para esta matrícula.", "warning")
        return redirect(url_for("index"))

    # Assuming 'tif_files' would be populated here if there were multiple files.
    # For now, we use 'caminho' directly as per existing logic.
    # If the intention was to handle multiple files, more context is needed.
    tif_files = [row["arquivo_tiff"]] # Simulate a list for the new logic

    if not tif_files:
        return "Nenhuma imagem encontrada para esta matrícula.", 404

    # Notify Admins about image view/download
    try:
        ip = request.remote_addr
        location = {"city": "Unknown", "region": "Unknown", "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        file_info = f"Visualização Imagem Matrícula #{imovel_id}"
        admin_emails = get_admin_emails()
        email_service.notify_admin_download(current_user.username, ip, location, file_info, admin_emails)
    except Exception as e:
        print(f"Error sending image view notification: {e}")

    # Audit Log
    logger.info(f"Visualização: {current_user.username} visualizou arquivo TIFF do imóvel ID {imovel_id}")

    # Seleciona o primeiro (ou lógica de qual mostrar)
    caminho = tif_files[0]

    if not os.path.isfile(caminho):
        flash(f"Arquivo TIFF não encontrado:\n{caminho}", "danger")
        return redirect(url_for("index"))

    try:
        # Abre o TIFF e converte para PNG em memória
        img = Image.open(caminho)

        # Garante modo compatível
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")

        buf = BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)

        # Envia PNG para o navegador (abre direto)
        return send_file(
            buf,
            mimetype="image/png",
            as_attachment=False,
            download_name=os.path.basename(caminho).rsplit(".", 1)[0] + ".png",
        )
    except Exception as e:
        flash(f"Erro ao abrir/ converter o TIFF: {e}", "danger")
        return redirect(url_for("index"))


@app.route("/alterar_senha", methods=["GET", "POST"])
@login_required
def alterar_senha():
    if request.method == "POST":
        senha = request.form.get("senha")
        confirmacao = request.form.get("confirmacao")
        
        if senha != confirmacao:
            flash("Senhas não conferem.", "danger")
            return redirect(url_for("alterar_senha"))
            
        hashed = generate_password_hash(senha)
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("UPDATE users SET password_hash=?, is_temporary_password=0 WHERE id=?", (hashed, current_user.id))
        conn.commit()
        conn.close()
        
        logger.info(f"Alteração de senha: {current_user.username} alterou sua senha")
        flash("Senha alterada com sucesso.", "success")
        return redirect(url_for("index"))
        
    return render_template("alterar_senha.html")

@app.route("/solicitacoes")
@login_required
def solicitacoes():
    if current_user.role not in ['admin', 'supervisor']:
        flash("Acesso não autorizado.", "danger")
        return redirect(url_for("index"))
        
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM password_resets WHERE status='PENDENTE' ORDER BY created_at DESC")
    resets = cur.fetchall()
    conn.close()
    
    return render_template("solicitacoes.html", resets=resets)

@app.route("/solicitacoes/reset/<int:req_id>", methods=["GET", "POST"])
@login_required
def reset_confirm(req_id):
    if current_user.role not in ['admin', 'supervisor']:
        flash("Acesso não autorizado.", "danger")
        return redirect(url_for("index"))
        
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM password_resets WHERE id=?", (req_id,))
    req_data = cur.fetchone()
    
    if not req_data:
        conn.close()
        flash("Solicitação não encontrada.", "danger")
        return redirect(url_for("solicitacoes"))

    username_req = req_data['username']
    
    # Busca usuario real
    cur.execute("SELECT * FROM users WHERE username=?", (username_req,))
    user_data = cur.fetchone()
    conn.close()
    
    if not user_data:
        # Se usuario nao existe pode criar? O enunciado diz "resetar".
        # Assume que se o user nao existe, nao da pra resetar.
        flash(f"Usuário {username_req} não encontrado no banco de dados.", "danger")
        return redirect(url_for("solicitacoes"))

    if request.method == "POST":
        nova_senha = request.form.get("senha")
        
        # Atualiza senha
        hashed = generate_password_hash(nova_senha)
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("UPDATE users SET password_hash=?, is_temporary_password=1 WHERE id=?", (hashed, user_data['id']))
        cur.execute("UPDATE password_resets SET status='CONCLUIDO' WHERE id=?", (req_id,))
        conn.commit()
        conn.close()
        
        logger.info(f"Recuperação de senha: {current_user.username} aprovou e resetou senha para usuário '{username_req}' (solicitação ID {req_id})")
        
        # Redireciona para tela de WhatsApp
        
        # Check for email and notify
        if user_data['email']:
            email_service.notify_reset_password(user_data['email'], nova_senha)
            flash("Senha redefinida. O usuário foi notificado por e-mail.", "success")

        return render_template("reset_confirma_whatsapp.html", 
                               user=user_data, 
                               senha=nova_senha, 
                               whatsapp=user_data['whatsapp'])

    # GET: Gera senha aleatoria
    rand_pwd = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    
    return render_template("reset_form.html", req=req_data, user=user_data, random_password=rand_pwd)

@app.route("/sobre_iago")
@login_required
def sobre_iago():
    stats = {
        "patterns_count": 0,
        "processed_count": 0,
        "level": 1,
        "level_title": "Aprendiz",
        "top_patterns": []
    }
    
    # Get processed count
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM imoveis WHERE status_trabalho='CONCLUIDO'")
        row = cur.fetchone()
        stats["processed_count"] = row[0] if row else 0
        conn.close()
    except Exception as e:
        print(f"Error getting imoveis stats: {e}")

    # Get IA Stats
    try:
        conn_ia = iago.get_ia_conn()
        cur_ia = conn_ia.cursor()
        
        # Count patterns
        cur_ia.execute("SELECT COUNT(*) FROM patterns")
        row = cur_ia.fetchone()
        count = row[0] if row else 0
        stats["patterns_count"] = count
        
        # Determine Level
        if count < 10:
            stats["level"] = 1
            stats["level_title"] = "Aprendiz"
        elif count < 50:
            stats["level"] = 2
            stats["level_title"] = "Júnior"
        elif count < 100:
            stats["level"] = 3
            stats["level_title"] = "Pleno"
        else:
            stats["level"] = 4
            stats["level_title"] = "Sênior"
            
        # Get examples (Unique fields, top weighted)
        cur_ia.execute("""
            SELECT field_name, SUM(weight) as w, MAX(example_match) 
            FROM patterns 
            GROUP BY field_name 
            ORDER BY w DESC 
            LIMIT 5
        """)
        rows = cur_ia.fetchall()
        for r in rows:
            stats["top_patterns"].append({
                "field": r[0],
                "weight": r[1],
                "example": r[2] or "Padrão Regex"
            })
            
        conn_ia.close()
    except Exception as e:
        print(f"Error getting IA stats: {e}")
        # Initialize DB if table missing (first run)
        if "no such table" in str(e).lower():
             try:
                 iago.init_ia_db()
             except:
                 pass
        
    return render_template("sobre_iago.html", stats=stats)




@app.route("/exportar_json")
@login_required
def exportar_json():
    """Tela de seleção do modo de exportação."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT value FROM system_config WHERE key='last_json_export'")
    row = cur.fetchone()
    conn.close()
    
    last_export = row[0] if row else None
    
    # Format date for display if exists
    display_date = None
    if last_export:
        try:
            # Assuming format stored is ISO
            dt = datetime.fromisoformat(last_export)
            display_date = dt.strftime("%d/%m/%Y às %H:%M")
        except:
            display_date = last_export

    return render_template("exportar.html", last_export=display_date)


@app.route("/baixar_json")
@login_required
def baixar_json():
    mode = request.args.get("mode", "completo")
    
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    # Logic for filters
    if mode == "incremental":
        cur.execute("SELECT value FROM system_config WHERE key='last_json_export'")
        row_config = cur.fetchone()
        last_export_str = row_config[0] if row_config else None
        
        if last_export_str:
            cur.execute("""
                SELECT * FROM imoveis 
                WHERE status_trabalho='CONCLUIDO' 
                AND updated_at > ?
            """, (last_export_str,))
        else:
            # First time running incremental = get all completed
            cur.execute("SELECT * FROM imoveis WHERE status_trabalho='CONCLUIDO'")
    else:
        # Full export
        cur.execute("SELECT * FROM imoveis WHERE status_trabalho='CONCLUIDO'")
        
    rows = cur.fetchall()
    
    # Record current time for next incremental export
    now_iso = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    
    # Update Config
    cur.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES ('last_json_export', ?)", (now_iso,))
    conn.commit()
    conn.close()

    if not rows and mode == "incremental":
        flash("Nenhum imóvel alterado ou concluído desde a última exportação.", "info")
        return redirect(url_for("exportar_json"))

    real_list = []
    
    for row in rows:
        d = dict(row)
        
        def get_int(val, default=0):
            try:
                return int(val) if val is not None else default
            except:
                return default

        contr = []
        if d["contribuinte"]:
            try:
                contr = json.loads(d["contribuinte"])
            except:
                contr = []
        
        # Sanitize CEP (integers only)
        raw_cep = str(d.get("cep", ""))
        clean_cep = "".join(filter(str.isdigit, raw_cep))
        if not clean_cep:
            clean_cep = "69400000"

        item = {
            "TIPOENVIO": 0,
            "NUMERO_REGISTRO": str(d.get("numero_registro", "")),
            "REGISTRO_TIPO": get_int(d.get("registro_tipo"), 1),
            "TIPO_DE_IMOVEL": get_int(d.get("tipo_de_imovel"), 1),
            "LOCALIZACAO": get_int(d.get("localizacao"), 0),
            "TIPO_LOGRADOURO": get_int(d.get("tipo_logradouro"), 0),
            "NOME_LOGRADOURO": str(d.get("nome_logradouro", "")),
            "NUMERO_LOGRADOURO": str(d.get("numero_logradouro", "")),
            "UF": 13, # Force Amazonas
            "CIDADE": 1302504, # Force Manacapuru (Amazonas Standard)
            "BAIRRO": str(d.get("bairro", "")),
            "CEP": clean_cep,
            "COMPLEMENTO": str(d.get("complemento", "")),
            "QUADRA": str(d.get("quadra", "")),
            "CONJUNTO": str(d.get("conjunto", "")),
            "SETOR": str(d.get("setor", "")),
            "LOTE": str(d.get("lote", "")),
            "LOTEAMENTO": str(d.get("loteamento", "")),
            "CONTRIBUINTE": contr,
            "RURAL": {
                "CAR": str(d.get("rural_car", "")),
                "NIRF": str(d.get("rural_nirf", "")),
                "CCIR": str(d.get("rural_ccir", "")),
                "NUMERO_INCRA": str(d.get("rural_numero_incra", "")),
                "SIGEF": str(d.get("rural_sigef", "")),
                "DENOMINACAORURAL": str(d.get("rural_denominacaorural", "")),
                "ACIDENTEGEOGRAFICO": str(d.get("rural_acidentegeografico", ""))
            },
            "CONDOMINIO": {
                "NOME_CONDOMINIO": str(d.get("condominio_nome", "")),
                "BLOCO": str(d.get("condominio_bloco", "")),
                "CONJUNTO": str(d.get("condominio_conjunto", "")),
                "TORRE": str(d.get("condominio_torre", "")),
                "APTO": str(d.get("condominio_apto", "")),
                "VAGA": str(d.get("condominio_vaga", ""))
            }
        }
        real_list.append(item)

    final_structure = {
        "INDICADOR_REAL": {
            "CNS": "004879",
            "REAL": real_list
        }
    }

    # Notify Admins about download
    try:
        ip = request.remote_addr
        location = {"city": "Unknown", "region": "Unknown", "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        
        file_info = f"Exportação JSON ({mode.upper()}) - {len(final_structure['INDICADOR_REAL']['REAL'])} registros"
        admin_emails = get_admin_emails()
        email_service.notify_admin_download(current_user.username, ip, location, file_info, admin_emails)
    except Exception as e:
        print(f"Error sending download notification: {e}")
    
    logger.info(f"Exportação: {current_user.username} exportou {len(final_structure['INDICADOR_REAL']['REAL'])} registros em JSON ({mode})")

    # Filename format: CNS YYYY MM DD HH MM
    cns_envio = "004879"
    # Manaus Time (UTC-4)
    manaus_time = datetime.now(timezone.utc) - timedelta(hours=4)
    data_envio = manaus_time.strftime("%Y %m %d %H %M")
    filename_json = f"{cns_envio} {data_envio}.json"

    # Ensure UTF-8 encoding for special characters in JSON content
    # Using indent=4 and explicit separators for clear formatting
    json_bytes = json.dumps(final_structure, ensure_ascii=False, indent=4, separators=(',', ': ')).encode('utf-8')

    return Response(
        json_bytes,
        mimetype="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment;filename="{filename_json}"'}
    )

if __name__ == "__main__":
    init_db()
    init_lock_table()
    
    # Obtém IP local para facilitar acesso na rede
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip_addr = s.getsockname()[0]
        s.close()
        print(f"\n{'='*40}")
        print(f" Servidor rodando!")
        print(f" Acesse via: http://{ip_addr}:5000")
        print(f"{'='*40}\n")
    except Exception:
        print("Não foi possível detectar IP rede local. Acesse via localhost.")

    app.run(host="0.0.0.0", port=5000, debug=False)

