from dotenv import load_dotenv
import sqlite3
import re
import os
from datetime import datetime
import requests
import json

# Load .env file
load_dotenv()



# try:
#     import psycopg2
#     from psycopg2.extras import RealDictCursor
# except ImportError:
#     psycopg2 = None

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
IAGO_DB_TYPE = "sqlite" # Forçado local conforme solicitado
# IAGO_DB_URL = os.getenv("IAGO_DB_URL", "") # e.g. "postgresql://user:pass@host/db"
IA_DB_PATH = os.getenv("IAGO_DB_PATH", "ia.db")
IAGO_SERVER_URL = os.getenv("IAGO_SERVER_URL", "") # e.g. "http://localhost:5000"

print(f"[IAGO] DB Type: {IAGO_DB_TYPE}")
if IAGO_DB_TYPE == 'sqlite':
    print(f"[IAGO] Path: {os.path.abspath(IA_DB_PATH)}")

def get_ia_conn():
    # if IAGO_DB_TYPE == 'postgres':
    #     if not psycopg2:
    #         raise ImportError("psycopg2 is required for Postgres usage. pip install psycopg2-binary")
    #     return psycopg2.connect(IAGO_DB_URL)
        
    # Default SQLite
    db_dir = os.path.dirname(IA_DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(IA_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def execute_query(cur, sql, params=()):
    """Helper to handle placeholder differences (sqlite: ?, postgres: %s)"""
    # if IAGO_DB_TYPE == 'postgres':
    #     # Convert ? to %s for postgres
    #     sql = sql.replace('?', '%s')
    cur.execute(sql, params)

def init_ia_db():
    conn = get_ia_conn()
    cur = conn.cursor()
    
    # Schema adaption
    pk_def = "INTEGER PRIMARY KEY AUTOINCREMENT"
    # if IAGO_DB_TYPE == 'postgres':
    #     pk_def = "SERIAL PRIMARY KEY"
        
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

def generate_context_regex(full_text, val_str):
    """
    Generates a regex that captures val_str within its context in full_text.
    Useful for learning patterns from manual corrections.
    """
    if not val_str or not full_text:
        return None
        
    # Escape val_str for safe regex usage
    escaped_val = re.escape(str(val_str).strip())
    
    # Try to find the value in the text to extract context
    match = re.search(escaped_val, full_text, re.IGNORECASE)
    if not match:
        # If not found exactly, just return a simple escaped version with capture group
        return f"({escaped_val})"
        
    start, end = match.span()
    
    # Get some context (approx 30 chars before and after)
    prefix_raw = full_text[max(0, start-30):start]
    suffix_raw = full_text[end:min(len(full_text), end+30)]
    
    # Clean context: remove newlines, multiple spaces, and limit to a few words
    def clean_ctx(text, is_prefix=True):
        text = re.sub(r'\s+', ' ', text).strip()
        parts = text.split()
        if is_prefix:
            # Take last 2 words as anchor
            return " ".join(parts[-2:]) if parts else ""
        else:
            # Take first 2 words as anchor
            return " ".join(parts[:2]) if parts else ""
            
    prefix = clean_ctx(prefix_raw, True)
    suffix = clean_ctx(suffix_raw, False)
    
    # Build the pattern
    # We use \s+ instead of literal spaces to be flexible with OCR gaps
    parts = []
    if prefix:
        parts.append(re.escape(prefix))
    
    # The value itself in a capturing group
    parts.append(f"({escaped_val})")
    
    if suffix:
        parts.append(re.escape(suffix))
        
    # Join with flexible whitespace
    return r"\s*".join(parts)

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

def query_ollama(prompt, system_prompt=None, json_format=True):
    """
    Realiza uma chamada HTTP POST para a API local do Ollama.
    Retorna o texto de resposta ou None caso ocorra falha.
    """
    ollama_enabled = os.getenv("USE_OLLAMA", "False").lower() in ("true", "1", "yes")
    if not ollama_enabled:
        return None
        
    model = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
    api_url = os.getenv("OLLAMA_API_URL", "http://localhost:11434/api/generate")
    
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.0,
            "num_predict": 1024
        }
    }
    if json_format:
        payload["format"] = "json"
    if system_prompt:
        payload["system"] = system_prompt
        
    try:
        response = requests.post(api_url, json=payload, timeout=120)
        if response.status_code == 200:
            return response.json().get("response")
    except Exception as e:
        print(f"[IAGO OLLAMA ERROR] Connection failed: {e}")
    return None

def ensure_ollama_running():
    """
    Verifica se a API local do Ollama está respondendo.
    Caso contrário, tenta iniciar o serviço do Ollama em segundo plano.
    """
    ollama_enabled = os.getenv("USE_OLLAMA", "False").lower() in ("true", "1", "yes")
    if not ollama_enabled:
        return
        
    api_url = os.getenv("OLLAMA_API_URL", "http://localhost:11434/api/generate")
    base_url = "http://localhost:11434"
    if "localhost" in api_url or "127.0.0.1" in api_url:
        parts = api_url.split("/")
        if len(parts) >= 3:
            base_url = f"{parts[0]}//{parts[2]}"
            
    try:
        response = requests.get(base_url, timeout=2)
        if response.status_code == 200 or response.text:
            print("[IAGO] Rede neural está ativa e respondendo.")
            return
    except requests.exceptions.RequestException:
        pass

    print("[IAGO] Rede neural não está ativa. Iniciando serviço em segundo plano...")
    import subprocess
    import platform
    import time
    
    try:
        if platform.system() == "Windows":
            subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=0x08000000)
        else:
            subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            
        print("[IAGO] Comando de inicialização da rede neural enviado em segundo plano.")
        time.sleep(3)
    except Exception as e:
        print(f"[IAGO ERROR] Falha ao iniciar subprocesso da rede neural: {e}")

def analyze(full_text, bypass_ollama=False):
    """
    Applies learned patterns to text, with optional Ollama local LLM support.
    """
    if not full_text:
        return {}

    # 1. Tentativa via Ollama (Local LLM)
    if not bypass_ollama:
        prompt = f"Analise o texto da matrícula de imóveis abaixo e extraia os campos solicitados no formato JSON:\n{full_text}"
        system_prompt = (
            "Você é um assistente de IA especialista em direito notarial e registral brasileiro. "
            "Extraia os dados básicos deste imóvel. Responda apenas o objeto JSON contendo os seguintes campos: "
            "NUMERO_REGISTRO, NOME_LOGRADOURO, BAIRRO, CIDADE, LOTE, QUADRA, SETOR, TIPO_ATO, NOME_PARTE, CPF_PARTE, DT_ATO. "
            "Use null para os campos não encontrados. Nunca invente dados."
        )
        ollama_res = query_ollama(prompt, system_prompt)
        if ollama_res:
            try:
                data = json.loads(ollama_res)
                if isinstance(data, dict):
                    return {k.upper(): str(v) for k, v in data.items() if v is not None}
            except Exception as e:
                print(f"[IAGO OLLAMA] Failed to parse JSON: {e}")

    # --- API MODE (Fallback) ---
    if IAGO_SERVER_URL:
        try:
            payload = {"full_text": full_text}
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
    Extracts a list of acts (Registrations/Averbations) from OCR text, with optional Ollama support.
    Returns format:
    [{'tipo_ato': '...', 'dt_ato': '...', 'partes': [{'nome': '...', 'cpf_cnpj': '...'}, ...], 'header': '...'}, ...]
    """
    if not full_text:
        return []

    # 1. Tentativa via Ollama (Local LLM)
    prompt = f"Analise a matrícula de imóveis abaixo e extraia a lista cronológica de atos:\n{full_text}"
    system_prompt = (
        "Você é um assistente de IA especialista em direito notarial e registral brasileiro. "
        "Extraia todos os atos registrados na matrícula (ex: R-1, R-2, Av-3, etc.). Para cada ato, identifique "
        "o cabeçalho (ex: 'R-1'), o tipo do ato (ex: 'Compra e Venda', 'Hipoteca', 'Averbação'), a data (DD/MM/AAAA) "
        "e a lista de partes envolvidas contendo nome e CPF/CNPJ (caso existam no texto). "
        "Responda apenas um objeto JSON com o formato: "
        "{\"acts\": [{\"header\": \"R-1\", \"tipo_ato\": \"Compra e Venda\", \"dt_ato\": \"20/10/1995\", \"partes\": [{\"nome\": \"ODALI TAVARES SANTANA\", \"cpf_cnpj\": \"123.456.789-00\"}]}]}"
    )
    ollama_res = query_ollama(prompt, system_prompt)
    if ollama_res:
        try:
            data = json.loads(ollama_res)
            acts_list = data.get("acts", [])
            for a in acts_list:
                if 'dt_ato' not in a and 'data' in a:
                    a['dt_ato'] = a['data']
                if 'tipo_ato' not in a and 'tipo' in a:
                    a['tipo_ato'] = a['tipo']
                if 'header' not in a:
                    a['header'] = "Ato"
                a['raw_text'] = "Extraído via IAGO (LLM)."
                
                # Normalize partes
                normalized_partes = []
                for p in a.get("partes", []):
                    if isinstance(p, dict):
                        nome = p.get("nome", "").strip()
                        cpf_cnpj = p.get("cpf_cnpj", "").strip()
                        if nome or cpf_cnpj:
                            normalized_partes.append({"nome": nome, "cpf_cnpj": cpf_cnpj})
                    elif isinstance(p, str):
                        p_clean = p.strip()
                        if re.match(r"^\d{3}\.\d{3}\.\d{3}-\d{2}$|^\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}$|^\d{11}$|^\d{14}$", p_clean):
                            normalized_partes.append({"nome": "Não identificado", "cpf_cnpj": p_clean})
                        else:
                            normalized_partes.append({"nome": p_clean, "cpf_cnpj": ""})
                a["partes"] = normalized_partes
                
            return acts_list
        except Exception as e:
            print(f"[IAGO OLLAMA] Failed to parse acts JSON: {e}")

    # --- Fallback to Regex and spaCy ---
    acts = []
    
    # 1. Split text into blocks based on R-X / Av-X headers
    header_pattern = re.compile(r"(?:^|\n)\s*(R[\s.-]*\d+|Av[\s.-]*\d+)\s*[-–—:]", re.IGNORECASE | re.MULTILINE)
    
    matches = list(header_pattern.finditer(full_text))
    
    if not matches:
        return []

    for i, match in enumerate(matches):
        act_header = match.group(1).replace(" ", "").replace(".", "-").upper()
        start_pos = match.start()
        end_pos = matches[i+1].start() if i + 1 < len(matches) else len(full_text)
        
        block_text = full_text[start_pos:end_pos].strip()
        
        # Extract Date (dd/mm/yyyy)
        dt_match = re.search(r"(\d{2}/\d{2}/\d{4})", block_text)
        dt_ato = dt_match.group(1) if dt_match else ""
        
        # Extract potential names
        cpf_matches = re.findall(r"\d{3}\.\d{3}\.\d{3}-\d{2}|\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}", block_text)
        
        names = []
        if NLP_MODEL:
            doc = NLP_MODEL(block_text)
            for ent in doc.ents:
                if ent.label_ in ["PER", "ORG"] and len(ent.text) > 4:
                    if ent.text.upper() not in ["ESCRITURA", "REGISTRO", "IMOVEL", "CARTORIO"]:
                        if ent.text not in names:
                            names.append(ent.text)
        
        # Combine names and CPFs
        paired_partes = []
        if len(names) == 1 and len(cpf_matches) == 1:
            paired_partes.append({"nome": names[0], "cpf_cnpj": cpf_matches[0]})
        else:
            for name in names:
                paired_partes.append({"nome": name, "cpf_cnpj": ""})
            for cpf in cpf_matches:
                # Add CPF only if it's not already matched
                paired_partes.append({"nome": "Não identificado", "cpf_cnpj": cpf})
        
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
            "partes": paired_partes,
            "raw_text": block_text[:200] + "..."
        })
        
    return acts

def extract_acts_mapa(full_text):
    """
    Extracts acts specifically formatted for the ONR Mapa JSON export, with optional Ollama support.
    """
    if not full_text:
        return []

    # 1. Tentativa via Ollama (Local LLM)
    prompt = f"Analise a matrícula de imóveis abaixo e extraia todos os atos e partes detalhadas no formato JSON:\n{full_text}"
    system_prompt = (
        "Você é um assistente de IA especialista em direito notarial e registral brasileiro. "
        "Sua tarefa é extrair todos os atos e estruturá-los para o envio ao ONR (ITN 03/2025). "
        "Responda APENAS um objeto JSON com uma chave \"acts\" contendo uma lista de atos. "
        "Para cada ato, identifique: header (ex: 'R-1'), protocolo (string), data_protocolo (DD/MM/AAAA), "
        "tipo_ato_cod (1: Registro, 2: Averbação), numero_ato (int), ato_cod (1: Abertura de matrícula, "
        "2: Relação jurídica, 3: Transmissão, 4: Alteração do imóvel, 5: Outros), alteracao_titulariedade (int), "
        "livro (string), folha (string), area (float), unidade_area (1: m2, 2: ha) e a lista de partes em partes_detalhadas. "
        "Para cada parte, extraia: nome, cpf (apenas números), estrangeiro (0: não, 1: sim), "
        "estado_civil (1: Solteiro, 2: Casado, 3: União Estável, 4: Divorciado, 5: Viúvo), "
        "regime_bens (2: Comunhão Parcial, 3: Comunhão Universal, 6: Separação), condicao_parte (1: Transmitente, "
        "2: Adquirente), genero (1: Masculino, 2: Feminino). "
        "Formato esperado:\n"
        "{\"acts\": [{\"header\": \"R-1\", \"tipo_ato_cod\": 1, \"numero_ato\": 1, \"ato_cod\": 3, \"protocolo\": \"123\", "
        "\"data_protocolo\": \"20/10/1995\", \"partes_detalhadas\": [{\"nome\": \"ODALI TAVARES SANTANA\", \"cpf\": \"35789321400\", "
        "\"estrangeiro\": 0, \"estado_civil\": 1, \"regime_bens\": 0, \"relacao_juridica\": 1, \"condicao_parte\": 1, \"genero\": 2}]}]}"
    )
    ollama_res = query_ollama(prompt, system_prompt)
    if ollama_res:
        try:
            data = json.loads(ollama_res)
            acts_list = data.get("acts", [])
            for a in acts_list:
                # Ensure all key fields are present
                a['tipo_ato_cod'] = a.get('tipo_ato_cod', 1)
                a['numero_ato'] = a.get('numero_ato', 0)
                a['ato_cod'] = a.get('ato_cod', 5)
                a['protocolo'] = a.get('protocolo', '')
                a['data_protocolo'] = a.get('data_protocolo', '')
                a['valor_transacao'] = a.get('valor_transacao', 0.0)
                a['valor_imposto'] = a.get('valor_imposto', 0.0)
                a['alteracao_titulariedade'] = a.get('alteracao_titulariedade', 0)
                a['alteracao_imovel'] = a.get('alteracao_imovel', 0)
                a['livro'] = a.get('livro', '')
                a['folha'] = a.get('folha', '')
                a['area'] = a.get('area', 0.0)
                a['unidade_area'] = a.get('unidade_area', 2)
                
                # Partes detailing
                for p in a.get('partes_detalhadas', []):
                    p['nome'] = p.get('nome', 'Não identificado')
                    p['cpf'] = p.get('cpf', '')
                    p['estrangeiro'] = p.get('estrangeiro', 0)
                    p['nacionalidade'] = p.get('nacionalidade', 76)
                    p['estado_civil'] = p.get('estado_civil', 1)
                    p['regime_bens'] = p.get('regime_bens', 0)
                    p['relacao_juridica'] = p.get('relacao_juridica', 1)
                    p['condicao_parte'] = p.get('condicao_parte', 2)
                    p['genero'] = p.get('genero', 1)
                    p['rnm'] = p.get('rnm', '')
                    p['passaporte'] = p.get('passaporte', '')
                    p['percentual'] = p.get('percentual', 100.0)
            
            # Filtrar para retornar apenas a última transmissão de propriedade ativa (ou o último ato)
            if acts_list:
                last_trans = None
                for act in reversed(acts_list):
                    if act.get('ato_cod') == 3: # Transmissão
                        last_trans = act
                        break
                if last_trans:
                    acts_list = [last_trans]
                else:
                    acts_list = [acts_list[-1]]
                    
            return acts_list
        except Exception as e:
            print(f"[IAGO OLLAMA] Failed to parse MAPA JSON: {e}")

    # --- Fallback to Regex and spaCy ---
    acts = []
    
    # 0. Check for learned patterns (Level 3)
    learned_data = analyze(full_text, bypass_ollama=True)
    learned_protocolo = learned_data.get('PROTOCOLO_MAPA', '')
    learned_data_ato = learned_data.get('DATA_ATO_MAPA', '')
    
    header_pattern = re.compile(r"(?:^|\n)\s*(R[\s.-]*(\d+)|Av[\s.-]*(\d+))(?:\s*[\/\-]\s*\d+)?\s*[-–—:~]", re.IGNORECASE | re.MULTILINE)
    matches = list(header_pattern.finditer(full_text))
    
    if not matches:
        return []

    for i, match in enumerate(matches):
        act_header = match.group(1).replace(" ", "").replace(".", "-").upper()
        
        # 1: Registro, 2: Averbação
        tipo_ato_cod = 1 if "R-" in act_header else 2
        
        num_ato_str = match.group(2) if "R-" in act_header else match.group(3)
        numero_ato = int(num_ato_str) if num_ato_str and num_ato_str.isdigit() else 0
        
        start_pos = match.start()
        end_pos = matches[i+1].start() if i + 1 < len(matches) else len(full_text)
        block_text = full_text[start_pos:end_pos].strip()
        
        # Extract Date
        dt_match = re.search(r"(\d{2}/\d{2}/\d{4})", block_text)
        dt_ato = dt_match.group(1) if dt_match else ""
        
        # Extract Protocolo
        prot_match = re.search(r"Protocolo\s*(?:n[º°]|nr|n)?\s*[\.\:]?\s*(\d+)", block_text, re.IGNORECASE)
        protocolo = prot_match.group(1) if prot_match else ""
        
        # Apply learned fallbacks if empty
        if not dt_ato and learned_data_ato:
            dt_ato = learned_data_ato
        if not protocolo and learned_protocolo:
            protocolo = learned_protocolo
        
        # Extract Valor Transacao
        val_match = re.search(r"R\$\s*([\d\.]+,\d{2})", block_text)
        valor_transacao = 0.0
        if val_match:
            try:
                # Convert 150.000,00 to 150000.00
                v_str = val_match.group(1).replace(".", "").replace(",", ".")
                valor_transacao = float(v_str)
            except:
                pass
                
        # Determine Ato Codigo (ONR enum)
        # 1:Abertura de matrícula; 2:Alteração da relação jurídica; 3:Transmissão-Aquisição Originária; 4:Alteração do imóvel; 5:Outros
        ato_cod = 5 
        alteracao_titulariedade = 0
        if "COMPRA" in block_text.upper() and "VENDA" in block_text.upper():
            ato_cod = 3 # Transmissão
            alteracao_titulariedade = 1 # Compra e venda
        elif "DOAÇÃO" in block_text.upper() or "DOACAO" in block_text.upper():
            ato_cod = 3
            alteracao_titulariedade = 2 # Doação
        elif "USUCAPIÃO" in block_text.upper() or "USUCAPIAO" in block_text.upper():
            ato_cod = 3
            alteracao_titulariedade = 5 # Usucapião
            
        # Determine General/Fallback parameters based on block text
        # (for parties that do not have their own localized adjectives)
        general_estado_civil = 1
        if "CASADO" in block_text.upper() or "CASADA" in block_text.upper():
            general_estado_civil = 2
        elif "DIVORCIADO" in block_text.upper() or "DIVORCIADA" in block_text.upper():
            general_estado_civil = 4
        elif "VIUVO" in block_text.upper() or "VIUVA" in block_text.upper() or "VIÚVO" in block_text.upper() or "VIÚVA" in block_text.upper():
            general_estado_civil = 5
        elif "UNIAO ESTAVEL" in block_text.upper() or "UNIÃO ESTÁVEL" in block_text.upper():
            general_estado_civil = 6

        general_regime = 0
        if "COMUNHÃO PARCIAL" in block_text.upper() or "COMUNHAO PARCIAL" in block_text.upper():
            general_regime = 2
        elif "COMUNHÃO UNIVERSAL" in block_text.upper() or "COMUNHAO UNIVERSAL" in block_text.upper():
            general_regime = 3
        elif "SEPARAÇÃO" in block_text.upper() or "SEPARACAO" in block_text.upper():
            general_regime = 6

        # Parse Partes using the new context-based algorithm
        partes_detalhadas = []
        cpf_pattern = re.compile(r"\d{3}\.\d{3}\.\d{3}-\d{2}|\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}")
        name_regex = re.compile(r'\b[A-ZÀ-Ý]{3,}(?:\s+(?:de|da|do|dos|das|e|o)\s+[A-ZÀ-Ý]{2,}|\s+[A-ZÀ-Ý]{2,})+\b')

        # A. Find all CPFs and extract preceding names
        cpf_matches = list(cpf_pattern.finditer(block_text))
        for m_cpf in cpf_matches:
            cpf_val = m_cpf.group()
            cpf_start = m_cpf.start()
            
            # Substring before CPF to locate the name
            prefix = block_text[max(0, cpf_start-200):cpf_start]
            names_found = list(name_regex.finditer(prefix))
            name_val = "Identificado via CPF (Verifique)"
            p_start = cpf_start
            
            if names_found:
                # Sort from right to left (closest to CPF)
                names_found.sort(key=lambda m: m.end(), reverse=True)
                for m_name in names_found:
                    cand = m_name.group().strip()
                    cand_clean = re.sub(r'\s+', ' ', cand)
                    if cand_clean not in ["CPF", "CNPJ", "RG", "CICIMF", "CIC/MF", "CIC", "MF", "CIC-MF"]:
                        name_val = cand_clean
                        p_start = max(0, cpf_start-200) + m_name.start()
                        break
            
            partes_detalhadas.append({
                "nome": name_val,
                "cpf": cpf_val,
                "span": (p_start, m_cpf.end())
            })
            
        # B. Find uppercase names WITHOUT CPFs
        all_names = list(name_regex.finditer(block_text))
        for m_name in all_names:
            name_str = m_name.group().strip()
            name_clean = re.sub(r'\s+', ' ', name_str)
            
            # Skip if already identified or is noise
            if any(p['nome'] == name_clean for p in partes_detalhadas):
                continue
            if name_clean in ["ESCRITURA PUBLICA", "DOACAO", "MATRICULA", "REGISTROS", "AVERBACOES", "IDENTIFICAGAO DO IMOVEL", "REGISTRO ANTERIOR", "PROPRIETARIO", "LIVRO", "FICHA", "CNPJ", "CICIMF", "ESTADO DO AMAZONAS", "TERRA PRETA", "REPUBLICA", "REPÚBLICA", "MUNICIPIO", "MUNICÍPIO", "UNIAO", "UNIÃO"]:
                continue
                
            # Context check to verify if this is likely a party
            start = m_name.start()
            prefix_ctx = block_text[max(0, start-80):start].lower()
            
            is_party = False
            keywords_transmitente = ["doado pelo", "doada pelo", "transmitente", "vendedor", "vendedora", "outorgante", "doador", "doadora", "proprietario", "proprietária", "cedente"]
            keywords_adquirente = ["em favor de", "em favor da", "favor da", "doado a", "doada a", "doado para", "doada para", "adquirente", "comprador", "compradora", "outorgado", "outorgada", "donatário", "donataria", "cessionário", "cessionaria"]
            
            if any(kw in prefix_ctx for kw in keywords_transmitente) or any(kw in prefix_ctx for kw in keywords_adquirente):
                is_party = True
                
            if is_party:
                partes_detalhadas.append({
                    "nome": name_clean,
                    "cpf": "",
                    "span": (start, m_name.end())
                })
                
        # C. Detailed Context Analysis for each identified party
        for p in partes_detalhadas:
            p_start, p_end = p["span"]
            
            # Local context window
            context = block_text[max(0, p_start-100):min(len(block_text), p_end+100)]
            context_lower = context.lower()
            prefix_context = block_text[max(0, p_start-100):p_start].lower()
            
            # 1. Role / Role Condition
            role = 2 # Default to Adquirente
            keywords_transmitente = ["doado pelo", "doada pelo", "vendedor", "vendedora", "outorgante", "doador", "doadora", "transmitente", "alienante", "proprietario", "proprietária", "cedente"]
            if any(kw in prefix_context for kw in keywords_transmitente):
                role = 1
            p["relacao_juridica"] = 1 # 1: Proprietario
            p["condicao_parte"] = role # 1: Transmitente, 2: Adquirente
            
            # 2. Estado Civil
            estado_civil = general_estado_civil
            if "solteir" in context_lower:
                estado_civil = 1
            elif "casad" in context_lower:
                estado_civil = 2
            elif "união estável" in context_lower or "uniao estavel" in context_lower or "união estavel" in context_lower:
                estado_civil = 6
            elif "divorciad" in context_lower:
                estado_civil = 4
            elif "viuv" in context_lower:
                estado_civil = 5
            p["estado_civil"] = estado_civil
            
            # 3. Regime de Bens
            regime = general_regime
            if "comunhão parcial" in context_lower or "comunhao parcial" in context_lower:
                regime = 2
            elif "comunhão universal" in context_lower or "comunhao universal" in context_lower:
                regime = 3
            elif "separação" in context_lower or "separacao" in context_lower:
                regime = 6
            p["regime_bens"] = regime
            
            # 4. Gênero
            genero = 1 # Masculino default
            feminine_words = ["brasileira", "solteira", "casada", "divorciada", "viúva", "compradora", "vendedora", "outorgada", "donatária", "proprietária", "cessionária"]
            if any(w in context_lower for w in feminine_words):
                genero = 2
            p["genero"] = genero
            
            # 5. Estrangeiro and documents
            estrangeiro = 0
            if any(w in context_lower for w in ["estrangeiro", "estrangeira", "passaporte", "rnm"]):
                estrangeiro = 1
            p["estrangeiro"] = estrangeiro
            
            rnm_local = ""
            rnm_match_local = re.search(r"RNM\s*(?:n[º°]|nr|n)?\s*[\.\:]?\s*([\w\-]+)", context, re.IGNORECASE)
            if rnm_match_local:
                rnm_local = rnm_match_local.group(1)
            p["rnm"] = rnm_local
            
            passaporte_local = ""
            pass_match_local = re.search(r"Passaporte\s*(?:n[º°]|nr|n)?\s*[\.\:]?\s*([\w\-]+)", context, re.IGNORECASE)
            if pass_match_local:
                passaporte_local = pass_match_local.group(1)
            p["passaporte"] = passaporte_local
            
            p["percentual"] = 100.0 # Default percentual
            
            # Remove helper span
            del p["span"]
            
        # D. If no parties found, insert a fallback placeholder
        if not partes_detalhadas:
            partes_detalhadas.append({
                "nome": "Não identificado",
                "cpf": "",
                "estado_civil": general_estado_civil,
                "regime_bens": general_regime,
                "relacao_juridica": 1,
                "condicao_parte": 2,
                "genero": 1,
                "estrangeiro": 0,
                "rnm": "",
                "passaporte": "",
                "percentual": 100.0
            })
            
        # Extract area if mentioned in act
        area_match = re.search(r"Área\s*de\s*([\d\.,]+)\s*(ha|m2|hectares|metros)", block_text, re.IGNORECASE)
        area_val = 0.0
        area_uni = 2 # ha default
        if area_match:
            try:
                area_val = float(area_match.group(1).replace(".", "").replace(",", "."))
                if "m" in area_match.group(2).lower():
                    area_uni = 1
            except: pass
            
        # Extract Livro/Folha (usually near top)
        livro_match = re.search(r"LIVRO\s*[Nn]?[º°]?\s*([\w\d]+)", full_text[:1000], re.IGNORECASE)
        folha_match = re.search(r"FOLHA\s*[Nn]?[º°]?\s*([\w\d]+)", full_text[:1000], re.IGNORECASE)
        livro = livro_match.group(1) if livro_match else ""
        folha = folha_match.group(1) if folha_match else ""
        
        acts.append({
            "header": act_header,
            "tipo_ato_cod": tipo_ato_cod,
            "numero_ato": numero_ato,
            "ato_cod": ato_cod,
            "protocolo": protocolo,
            "data_protocolo": dt_ato,
            "valor_transacao": valor_transacao,
            "valor_imposto": 0.0,
            "alteracao_titulariedade": alteracao_titulariedade,
            "alteracao_imovel": 0,
            "partes_detalhadas": partes_detalhadas,
            "livro": livro,
            "folha": folha,
            "area": area_val,
            "unidade_area": area_uni
        })
        
    # Filtrar para retornar apenas a última transmissão de propriedade ativa (ou o último ato)
    if acts:
        last_trans = None
        for act in reversed(acts):
            if act.get('ato_cod') == 3: # Transmissão
                last_trans = act
                break
        if last_trans:
            acts = [last_trans]
        else:
            acts = [acts[-1]]
            
    return acts

def chat_with_db(user_message, history=None):
    if history is None:
        history = []
        
    msg_clean = user_message.strip().lower()
    import re
    import unicodedata
    msg_clean = unicodedata.normalize('NFKD', msg_clean).encode('ASCII', 'ignore').decode('utf-8')
    msg_clean = re.sub(r'[^\w\s]', '', msg_clean).strip()
    
    if msg_clean in ["ola", "oi", "bom dia", "boa tarde", "boa noite", "opa", "tudo bem", "ola iago", "oi iago"]:
        import datetime
        hora = datetime.datetime.now().hour
        if hora < 12: saudacao = "Bom dia!"
        elif hora < 18: saudacao = "Boa tarde!"
        else: saudacao = "Boa noite!"
        return f"{saudacao} Sou o assistente de IA do cartório. Diga-me o CPF, Nome ou Endereço que deseja buscar no acervo!"
        
    history_text = ""
    for msg in history[-5:]: # Pegar as ultimas 5 para contexto
        history_text += f"{msg['role'].upper()}: {msg['content']}\n"
        
    system_intent = (
        "Você é o IAGO, assistente de IA do Indicador Real. "
        "Sua tarefa é analisar a mensagem do usuário (junto com o histórico recente, se houver) e determinar se ele quer buscar algo no banco de dados. "
        "Responda APENAS com um objeto JSON e nada mais. Não inclua Markdown. "
        "Formato: {\"intent\": \"search_nome\", \"query\": \"Nome da pessoa\"} ou "
        "{\"intent\": \"search_cpf\", \"query\": \"123456\"} ou "
        "{\"intent\": \"search_endereco\", \"query\": \"Rua X\"} ou "
        "{\"intent\": \"general\", \"query\": \"\"} se não for uma busca específica."
    )
    
    intent_prompt = f"HISTÓRICO:\n{history_text}\n\nMENSAGEM ATUAL:\nUSER: {user_message}"
    intent_res = query_ollama(intent_prompt, system_intent)
    db_results = "Nenhum dado encontrado ou busca não solicitada."
    
    if intent_res:
        try:
            # Tentar limpar caso o Ollama retorne markdown
            clean_res = intent_res.replace('```json', '').replace('```', '').strip()
            data = json.loads(clean_res)
            intent = data.get("intent", "general")
            query = data.get("query", "")
            
            if intent != "general" and query:
                import sqlite3
                import os
                db_path = os.path.join(os.path.dirname(__file__), "imoveis.db")
                conn = sqlite3.connect(db_path)
                cur = conn.cursor()
                results = []
                
                if intent == "search_nome":
                    cur.execute("SELECT id, n_matricula, nome, cpf_cnpj, tipo_ato, dt_reg_averb FROM indicador_pessoal WHERE nome LIKE ? LIMIT 10", (f"%{query}%",))
                    for r in cur.fetchall():
                        btn = f'<br><a href=\"/indicador_pessoal?q={r[1]}\" class=\"btn btn-sm btn-outline-primary rounded-pill mt-1\">Abrir Indicador Pessoal: {r[1]}</a>'
                        results.append(f"Matrícula: {r[1]}, Nome: {r[2]}, CPF/CNPJ: {r[3]}, Ato: {r[4]} {btn}")
                        
                elif intent == "search_cpf":
                    cur.execute("SELECT id, n_matricula, nome, cpf_cnpj, tipo_ato, dt_reg_averb FROM indicador_pessoal WHERE cpf_cnpj LIKE ? LIMIT 10", (f"%{query}%",))
                    for r in cur.fetchall():
                        btn = f'<br><a href=\"/indicador_pessoal?q={r[1]}\" class=\"btn btn-sm btn-outline-primary rounded-pill mt-1\">Abrir Indicador Pessoal: {r[1]}</a>'
                        results.append(f"Matrícula: {r[1]}, Nome: {r[2]}, CPF/CNPJ: {r[3]}, Ato: {r[4]} {btn}")
                        
                elif intent == "search_endereco":
                    cur.execute("SELECT COUNT(*) FROM imoveis WHERE nome_logradouro LIKE ? OR loteamento LIKE ?", (f"%{query}%", f"%{query}%"))
                    total_count = cur.fetchone()[0]
                    
                    if total_count > 10:
                        cur.execute("SELECT bairro, COUNT(*) as qtd FROM imoveis WHERE nome_logradouro LIKE ? OR loteamento LIKE ? GROUP BY bairro ORDER BY qtd DESC LIMIT 5", (f"%{query}%", f"%{query}%"))
                        bairros = cur.fetchall()
                        bairros_list = ", ".join([f"{b[0] or 'Sem Bairro'} ({b[1]} imóveis)" for b in bairros])
                        results.append(f"INSTRUÇÃO DO SISTEMA: A busca por '{query}' retornou muitos resultados ({total_count} imóveis). "
                                     f"Não liste imóveis individuais agora. Converse com o usuário dizendo que encontrou muitas matrículas e "
                                     f"pergunte em qual bairro ele tem interesse, oferecendo as seguintes opções populares: {bairros_list}")
                    else:
                        cur.execute("SELECT id, numero_registro, nome_logradouro, numero_logradouro, bairro, cidade, loteamento FROM imoveis WHERE nome_logradouro LIKE ? OR loteamento LIKE ? LIMIT 10", (f"%{query}%", f"%{query}%"))
                        for r in cur.fetchall():
                            btn = f'<br><button onclick=\"window.open(\'/imovel/{r[0]}/popup\', \'_blank\', \'width=1200,height=800\')\" class=\"btn btn-sm btn-outline-primary rounded-pill mt-1\">Visualizar Matrícula {r[1]}</button>'
                            results.append(f"Matrícula: {r[1]}, Endereço: {r[2]} {r[3]} - {r[4]}, {r[5]}. Loteamento: {r[6]} {btn}")
                
                conn.close()
                if results:
                    db_results = "\n".join(results)
                else:
                    db_results = "Nenhum resultado encontrado na base de dados para esta busca."
                    
        except Exception as e:
            print("[IAGO CHAT] JSON Parse Error:", e, "Response was:", intent_res)
            
    system_answer = (
        "Você é o IAGO, o assistente virtual inteligente do Cartório de Imóveis. "
        "Você recebeu o histórico recente da conversa, a pergunta do usuário e resultados do banco de dados (que podem conter botões/links em HTML). "
        "Responda de forma coloquial, amigável e concisa. "
        "IMPORTANTE: Ao exibir as matrículas encontradas, SEMPRE preserve os links e botões HTML gerados no resultado (ex: <button...> ou <a href...>) exatamente como vieram do banco de dados. "
        "Se não encontrou na base, diga gentilmente. Pode fazer perguntas para refinar a busca."
    )
    
    final_prompt = f"HISTÓRICO:\n{history_text}\n\nMENSAGEM: {user_message}\n\nRESULTADOS DO BANCO:\n{db_results}"
    answer = query_ollama(final_prompt, system_answer, json_format=False)
    return answer if answer else "Desculpe, estou com dificuldades de me comunicar com meu cérebro neural no momento."
