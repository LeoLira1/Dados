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
- Anthropic API (opcional, dependência separada)

## Como rodar localmente
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# opcional para IA com Claude:
pip install anthropic==0.52.0
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

## Troubleshooting no Streamlit Cloud
Se o app ficar preso em **"Your app is in the oven"**, abra os logs de build/runtime no Streamlit Cloud.
Um erro comum é permissão de escrita no banco SQLite em diretório do repositório.
Outro erro comum é `ModuleNotFoundError` de libs opcionais/não instaladas no runtime.

A aplicação já tenta automaticamente:
1. `SQLITE_DB_PATH` (quando definido);
2. `data/health.db`;
3. fallback para `/tmp/health.db` (compatível com ambiente read-only).

Se quiser forçar explicitamente no Cloud, adicione em **Secrets**:
```toml
SQLITE_DB_PATH = "/tmp/health.db"
```

Se aparecer erro de `plotly`, confirme que o build instalou `requirements.txt` da branch publicada e faça **Reboot app**.

## Turso
Atualmente a persistência está implementada em SQLite local via `sqlite3`.
Para produção em Turso, o próximo passo é trocar o repositório de dados por cliente libSQL/Turso usando `TURSO_DATABASE_URL` + `TURSO_AUTH_TOKEN` sem alterar a camada de UI do Streamlit.
