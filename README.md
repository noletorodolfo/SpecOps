# SpecOps

SpecOps é um sistema de **engenharia assistida por IA com governança cognitiva**: **spec → plan → work → review → apply → doc**.

**Propósito**  
Transformar especificações em planos, gerar artefatos (código, IaC, docs), validar com validators automáticos e aplicar mudanças somente após revisão humana.

**Stack (MVP)**  
- CLI: Python  
- Neovim plugin: Lua  
- Adapters: mock / OpenAI / Ollama (pluggable)  
- RAG: index de notas operacionais (FAISS)  
- Validators: terraform validate, kubeval, linters, pytest  
- Processo: Scrumban (sprints 1–2 semanas)

## Quick start (Arch Linux)

```bash
# pré-requisitos
sudo pacman -Syu python neovim git

# preparar ambiente
git clone <repo-url> SpecOps
cd SpecOps
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# indexar RAG (se tiver rags/)
python tools/rag_ingest.py

# abrir Neovim e testar
nvim
# dentro do Neovim: :SpecOpsBrainstorm

