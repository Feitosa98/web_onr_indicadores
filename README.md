# ONR Web - Sistema de Indicadores (Real e Pessoal)

Este projeto é um sistema web desenvolvido em Python (Flask) para gestão de indicadores cartorários (Indicador Real e Pessoal), com suporte a visualização de matrículas, linhas do tempo de registros e integração com OCR e IA (IAGO).

## 🚀 Funcionalidades Principais

*   **Indicador Real**: Cadastro e visualização de imóveis, com suporte a upload de imagens (TIFF) e visualização web.
*   **Indicador Pessoal**:
    *   **Master-Detail View**: Visualização em lista com filtro rápido e detalhe expandido.
    *   **Timeline Interativa**: Histórico cronológico de atos (Registros/Averbações) para cada matrícula.
    *   **Integração Visual**: Consulta de endereço e características do imóvel puxadas diretamente da base do Indicador Real.
*   **IAGO (Inteligência Artificial)**: Módulo de aprendizado para extração automática de dados (Atos, Datas, Partes) a partir de documentos OCR.
*   **Exportação ONR**: Geração de arquivos JSON conforme padrões do ONR.

## 🛠️ Tecnologias Utilizadas

*   **Backend**: Python 3.12, Flask, SQLite / PostgreSQL.
*   **Frontend**: HTML5, Bootstrap 5, JavaScript (Vanilla).
*   **IA/OCR**: spaCy, Regex Heuristics (Módulo `iago.py`).
*   **Outros**: Pillow (Imagens), OpenPyXL (Excel), APScheduler (Tarefas agendadas).

## 📦 Instalação e Execução

### 1. Pré-requisitos
*   Python 3.10 ou superior instalado.
*   Git instalado.

### 2. Clonar o Repositório
```bash
git clone https://github.com/Feitosa98/web_onr_indicadores.git
cd web_onr_indicadores
```

### 3. Criar Ambiente Virtual (Recomendado)
```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# Linux/Mac
python3 -m venv .venv
source .venv/bin/activate
```

### 4. Instalar Dependências
```bash
pip install -r requirements.txt
```

### 5. Configuração (.env)
O sistema usa variáveis de ambiente. Crie um arquivo `.env` na raiz (se não existir) ou ajuste as variáveis padrão no código se preferir.
Exemplo de `.env`:
```env
FLASK_APP=imoveis_web.py
FLASK_DEBUG=1
SECRET_KEY=sua_chave_secreta_aqui
```

### 6. Executar o Sistema
```bash
python imoveis_web.py
```
O servidor iniciará em `http://localhost:5000` (ou no IP da sua rede local listado no terminal).

## 🤝 Contribuição
1.  Faça um Fork do projeto.
2.  Crie uma Branch para sua Feature (`git checkout -b feature/NovaFeature`).
3.  Faça o Commit (`git commit -m 'Add some NovaFeature'`).
4.  Push para a Branch (`git push origin feature/NovaFeature`).
5.  Abra um Pull Request.

---
Desenvolvido por Iagos Feitosa.
