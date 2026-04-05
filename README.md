# Dashboard de Composição Corporal (Streamlit)

Aplicação em Python/Streamlit baseada no layout enviado, preservando comportamento funcional:
- KPIs principais (peso, gordura, músculo, score)
- metas com progresso
- gráfico temporal com metas
- donut de composição
- tabela de histórico
- cadastro real de nova medição em banco
- análise textual com Claude + upload de imagem para comparação

## Stack
- Streamlit
- Pandas + Plotly
- SQLite (persistência local)
- Anthropic API (opcional)

## Como rodar localmente
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Variáveis de ambiente
- `ANTHROPIC_API_KEY`: habilita os blocos de insight e comparação por imagem com Claude.
- `SQLITE_DB_PATH` (opcional): caminho do banco SQLite; default `data/health.db`.

## Streamlit Cloud
1. Suba este repositório no GitHub.
2. Crie app no Streamlit Cloud apontando para `app.py`.
3. Em **Secrets**, adicione:
   - `ANTHROPIC_API_KEY = "..."` (opcional)
4. Deploy.

## Turso
Atualmente a persistência está implementada em SQLite local via `sqlite3`.
Para produção em Turso, o próximo passo é trocar o repositório de dados por cliente libSQL/Turso usando `TURSO_DATABASE_URL` + `TURSO_AUTH_TOKEN` sem alterar a camada de UI do Streamlit.
