
from dotenv import load_dotenv
import sqlite3
import re
import os
from datetime import datetime
import requests

# Load .env file
load_dotenv()



try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    psycopg2 = None

# NLP Configuration (Level 1)
NLP_MODEL = None
try:
    import spacy
    try:
        NLP_MODEL = spacy.load("pt_core_news_sm")
        print("[IAGO] NLP Model loaded: pt_core_news_sm")
    except OSError:
        print("[IAGO] spaCy installed but model 'pt_core_news_sm' not found. Run: python -m spacy download pt_core_news_sm")
except ImportError:
    print("[IAGO] spaCy not installed. NLP features disabled.")

# DB Configuration
IAGO_DB_TYPE = os.getenv("IAGO_DB_TYPE", "sqlite") # 'sqlite' or 'postgres'
IAGO_DB_URL = os.getenv("IAGO_DB_URL", "") # e.g. "postgresql://user:pass@host/db"
IA_DB_PATH = os.getenv("IAGO_DB_PATH", "ia.db")
IAGO_SERVER_URL = os.getenv("IAGO_SERVER_URL", "") # e.g. "http://localhost:5000"

print(f"[IAGO] DB Type: {IAGO_DB_TYPE}")
if IAGO_DB_TYPE == 'sqlite':
    print(f"[IAGO] Path: {os.path.abspath(IA_DB_PATH)}")

def get_ia_conn():
    if IAGO_DB_TYPE == 'postgres':
        if not psycopg2:
            raise ImportError("psycopg2 is required for Postgres usage. pip install psycopg2-binary")
        return psycopg2.connect(IAGO_DB_URL)
        
    # Default SQLite
    db_dir = os.path.dirname(IA_DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(IA_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def execute_query(cur, sql, params=()):
    """Helper to handle placeholder differences (sqlite: ?, postgres: %s)"""
    if IAGO_DB_TYPE == 'postgres':
        # Convert ? to %s for postgres
        sql = sql.replace('?', '%s')
    cur.execute(sql, params)

def init_ia_db():
    conn = get_ia_conn()
    cur = conn.cursor()
    
    # Schema adaption
    pk_def = "INTEGER PRIMARY KEY AUTOINCREMENT"
    if IAGO_DB_TYPE == 'postgres':
        pk_def = "SERIAL PRIMARY KEY"
        
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS patterns (
            id {pk_def},
            field_name TEXT NOT NULL,
            regex_pattern TEXT NOT NULL,
            example_match TEXT,
            weight INTEGER DEFAULT 1,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()

# ... (rest of imports/helpers)

def learn(full_text, current_data):
    if not full_text:
        return 0
        
    # --- API MODE (Client) ---
    if IAGO_SERVER_URL:
        # ... (Client code unchanged) ...
        try:
            payload = {"full_text": full_text, "current_data": current_data}
            resp = requests.post(f"{IAGO_SERVER_URL}/api/iago/learn", json=payload, timeout=5)
            if resp.status_code == 200:
                return resp.json().get('learned_count', 0)
            return 0
        except Exception as e:
            print(f"[IAGO CLIENT ERROR] Learn failed: {e}")
            return 0

    # --- SERVER/LOCAL MODE (DB Access) ---
    try:
        conn = get_ia_conn()
        cur = conn.cursor()
        count = 0
        now = datetime.now().isoformat()
        
        target_fields = [
            "NUMERO_REGISTRO", "NOME_LOGRADOURO", "BAIRRO", 
            "CIDADE", "LOTE", "QUADRA", "SETOR",
            "TIPO_ATO", "NOME_PARTE", "CPF_PARTE", "DT_ATO"
        ]
        
        for field in target_fields:
            val = current_data.get(field) or current_data.get(field.lower())
            
            if val:
                val_str = str(val).strip()
                regex = generate_context_regex(full_text, val_str)
                
                if regex:
                    # Check
                    execute_query(cur, "SELECT id, weight FROM patterns WHERE field_name=? AND regex_pattern=?", (field, regex))
                    existing = None
                    if IAGO_DB_TYPE == 'postgres':
                        # Postgres cursor might behave differently depending on factory
                        # but standard psycopg2 cursor fetches tuples or RealDictRow
                        existing = cur.fetchone()
                    else:
                         existing = cur.fetchone()

                    if existing:
                        # Reinforce
                        # Handle row access difference if simple tuple
                        row_id = existing['id'] if hasattr(existing, 'keys') else existing[0]
                        execute_query(cur, "UPDATE patterns SET weight = weight + 1 WHERE id=?", (row_id,))
                    else:
                        # Learn
                        anonymized_example = f"Pattern for {field}" 
                        execute_query(cur, "INSERT INTO patterns (field_name, regex_pattern, example_match, created_at) VALUES (?, ?, ?, ?)",
                                    (field, regex, anonymized_example, now))
                        count += 1
        
        conn.commit()
        conn.close()
        return count
    except Exception as e:
        print(f"[IAGO DB ERROR] Learn: {e}")
        return 0

def analyze(full_text):
    """
    Applies learned patterns to text.
    """
    if not full_text:
        return {}

    # --- API MODE ---
    if IAGO_SERVER_URL:
        try:
            payload = {"full_text": full_text}
            # We ask server to analyze
            resp = requests.post(f"{IAGO_SERVER_URL}/api/iago/analyze", json=payload, timeout=5)
            if resp.status_code == 200:
                return resp.json()
            return {}
        except Exception as e:
            print(f"[IAGO CLIENT ERROR] Analyze failed: {e}")
            return {}
        

    # --- SERVER/LOCAL MODE (DB Access) ---
    try:
        conn = get_ia_conn()
        cur = conn.cursor()
        execute_query(cur, "SELECT field_name, regex_pattern FROM patterns ORDER BY weight DESC")
        rows = cur.fetchall()
        conn.close()
        
        results = {}
        
        for r in rows:
            # Handle row access difference
            field = r["field_name"] if hasattr(r, 'keys') else r[0]
            if field in results:
                continue
                
            pattern = r["regex_pattern"] if hasattr(r, 'keys') else r[1]
            try:
                match = re.search(pattern, full_text)
                if match:
                    val = match.group(1).strip()
                    results[field] = val
            except re.error:
                pass
                
        return results
    except Exception as e:
        print(f"[IAGO DB ERROR] Analyze: {e}")
        return {}

def extract_acts(full_text):
    """
    Extracts a list of acts (Registrations/Averbations) from OCR text.
    Returns format:
    [{'tipo': 'R-1', 'texto': '...', 'data': 'dd/mm/yyyy', 'partes': [...]}, ...]
    """
    if not full_text:
        return []
        
    acts = []
    
    # 1. Split text into blocks based on R-X / Av-X headers
    # Regex to find start of act: (R-\d+|Av-\d+)
    # We use a lookahead to split, or just find iter
    
    # Pattern to find Act Headers: R-1, Av-10, AV-3, R.5 etc.
    header_pattern = re.compile(r"(?:^|\n)\s*(R[\s.-]*\d+|Av[\s.-]*\d+)\s*[-–—:]", re.IGNORECASE | re.MULTILINE)
    
    matches = list(header_pattern.finditer(full_text))
    
    if not matches:
        return []

    for i, match in enumerate(matches):
        act_header = match.group(1).replace(" ", "").replace(".", "-").upper() # Normalize to R-1, AV-1
        start_pos = match.start()
        end_pos = matches[i+1].start() if i + 1 < len(matches) else len(full_text)
        
        block_text = full_text[start_pos:end_pos].strip()
        
        # Extract Date (dd/mm/yyyy) - usually near the end or beginning
        dt_match = re.search(r"(\d{2}/\d{2}/\d{4})", block_text)
        dt_ato = dt_match.group(1) if dt_match else ""
        
        # Extract potential names (Approximation: Capitalized words excluding common stopwords)
        # For now, let's look for "TRANSMITENTE:" or "ADQUIRENTE:" or just assume lines
        # This is hard without NER. Let's try to find CPF/CNPJ as strong indicator of a person
        
        partes = []
        
        # 1. Regex Strategy (Strong for CPF)
        cpf_matches = re.findall(r"\d{3}\.\d{3}\.\d{3}-\d{2}|\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}", block_text)
        partes.extend(cpf_matches)

        # 2. NLP Strategy (Level 1 - spaCy)
        if NLP_MODEL:
            doc = NLP_MODEL(block_text)
            for ent in doc.ents:
                if ent.label_ in ["PER", "ORG"] and len(ent.text) > 4:
                    # Filter out common false positives if needed
                    if ent.text.upper() not in ["ESCRITURA", "REGISTRO", "IMOVEL", "CARTORIO"]:
                        if ent.text not in partes:
                            partes.append(ent.text)
        
        # Refine Act Type
        tipo_real = "Registro" if "R-" in act_header else "Averbação"
        if "COMPRA" in block_text.upper() and "VENDA" in block_text.upper():
            tipo_real = "Compra e Venda"
        elif "HIPOTECA" in block_text.upper():
             tipo_real = "Hipoteca"
        elif "PENHORA" in block_text.upper():
             tipo_real = "Penhora"
        elif "CANCELAMENTO" in block_text.upper():
             tipo_real = "Cancelamento"
        
        acts.append({
            "header": act_header,
            "tipo_ato": tipo_real,
            "dt_ato": dt_ato,
            "partes": partes, # List of CPFs for now
            "raw_text": block_text[:200] + "..." # Preview
        })
        
    return acts
