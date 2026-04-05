from textwrap import dedent
import base64
import html
import json
import mimetypes
from datetime import date

import anthropic
import libsql
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots


st.set_page_config(
    page_title="Corpo em evolução",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# -----------------------------------------------------------------------------
# HELPERS
# -----------------------------------------------------------------------------
def html_block(content: str) -> str:
    return dedent(content).strip()


def fmt_num(valor: float | int, casas: int = 1) -> str:
    return f"{valor:.{casas}f}".replace(".", ",")


def safe_html_text(text: str) -> str:
    return html.escape(text).replace("\n", "<br>")


def progresso_peso(atual: float, minimo: float, meta: float) -> float:
    if meta <= minimo:
        return 0.0
    return max(0.0, min(1.0, (atual - minimo) / (meta - minimo)))


def progresso_gordura(inicial: float, atual: float, meta: float) -> float:
    total = inicial - meta
    feito = inicial - atual
    if total <= 0:
        return 0.0
    return max(0.0, min(1.0, feito / total))


def status_class(status: str) -> str:
    s = status.lower().strip()
    if s in ["boa", "bom", "normal", "ok"]:
        return "tag-ok"
    if s in ["alta", "insuf.", "insuficiente", "ruim"]:
        return "tag-hi"
    return "tag-mid"


def num_or_none(value):
    if value in [None, "", "null"]:
        return None
    try:
        return float(value)
    except Exception:
        return None


# -----------------------------------------------------------------------------
# CLAUDE
# -----------------------------------------------------------------------------
@st.cache_resource
def get_claude_client():
    return anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])


def ask_claude_analysis(prompt: str) -> str:
    client = get_claude_client()
    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=700,
        messages=[{"role": "user", "content": prompt}],
    )
    parts = []
    for block in response.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return safe_html_text("\n".join(parts).strip())


def extract_zepp_structured(uploaded_file):
    client = get_claude_client()

    file_bytes = uploaded_file.getvalue()
    mime_type = uploaded_file.type or mimetypes.guess_type(uploaded_file.name)[0] or "image/png"
    image_b64 = base64.b64encode(file_bytes).decode("utf-8")

    extraction_prompt = """
Você vai ler uma imagem do app Zepp Life.

Extraia SOMENTE o que estiver visível com confiança.
Não invente números.
Retorne APENAS JSON válido, sem markdown, sem comentários, sem texto extra.

Formato esperado:
{
  "data_medicao": "YYYY-MM-DD ou null",
  "peso": number ou null,
  "gordura": number ou null,
  "musculo": number ou null,
  "agua": number ou null,
  "visceral": number ou null,
  "proteina": number ou null,
  "massa_ossea": number ou null,
  "imc": number ou null,
  "basal": number ou null,
  "score": number ou null,
  "observacoes": "string curta"
}

Regras:
- Use ponto decimal, nunca vírgula.
- Se não conseguir ler um campo, use null.
- Se a data exata não aparecer, use null.
"""

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=700,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime_type,
                            "data": image_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": extraction_prompt,
                    },
                ],
            }
        ],
    )

    parts = []
    for block in response.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)

    raw_text = "\n".join(parts).strip()

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        start = raw_text.find("{")
        end = raw_text.rfind("}")
        if start != -1 and end != -1 and end > start:
            data = json.loads(raw_text[start:end + 1])
        else:
            raise

    normalized = {
        "data_medicao": data.get("data_medicao"),
        "peso": num_or_none(data.get("peso")),
        "gordura": num_or_none(data.get("gordura")),
        "musculo": num_or_none(data.get("musculo")),
        "agua": num_or_none(data.get("agua")),
        "visceral": num_or_none(data.get("visceral")),
        "proteina": num_or_none(data.get("proteina")),
        "massa_ossea": num_or_none(data.get("massa_ossea")),
        "imc": num_or_none(data.get("imc")),
        "basal": num_or_none(data.get("basal")),
        "score": num_or_none(data.get("score")),
        "observacoes": str(data.get("observacoes") or "").strip(),
    }
    return normalized


def analyze_extracted_measurement(extracted: dict, current_data: dict) -> str:
    prompt = f"""
Analise esta nova medição corporal comparando com os dados atuais.

Dados atuais:
- Peso: {current_data.get("peso")}
- Gordura: {current_data.get("gordura")}
- Músculo: {current_data.get("musculo")}
- Água: {current_data.get("agua")}
- Visceral: {current_data.get("visceral")}
- Proteína: {current_data.get("proteina")}
- Massa óssea: {current_data.get("massa_ossea")}
- IMC: {current_data.get("imc")}
- Basal: {current_data.get("basal")}
- Score: {current_data.get("score")}

Nova medição extraída:
- Data: {extracted.get("data_medicao")}
- Peso: {extracted.get("peso")}
- Gordura: {extracted.get("gordura")}
- Músculo: {extracted.get("musculo")}
- Água: {extracted.get("agua")}
- Visceral: {extracted.get("visceral")}
- Proteína: {extracted.get("proteina")}
- Massa óssea: {extracted.get("massa_ossea")}
- IMC: {extracted.get("imc")}
- Basal: {extracted.get("basal")}
- Score: {extracted.get("score")}
- Observações da leitura: {extracted.get("observacoes")}

Responda em português do Brasil.
Seja direto.
Traga:
1. O que melhorou
2. O que piorou ou merece atenção
3. O foco principal agora

Máximo de 3 blocos curtos.
"""
    return ask_claude_analysis(prompt)


# -----------------------------------------------------------------------------
# TURSO
# -----------------------------------------------------------------------------
@st.cache_resource
def get_turso_conn():
    return libsql.connect(
        database=st.secrets["TURSO_DATABASE_URL"],
        auth_token=st.secrets["TURSO_AUTH_TOKEN"],
    )


def init_db():
    conn = get_turso_conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS medicoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_medicao TEXT,
            peso REAL,
            gordura REAL,
            musculo REAL,
            agua REAL,
            visceral REAL,
            proteina REAL,
            massa_ossea REAL,
            imc REAL,
            basal REAL,
            score REAL,
            origem TEXT,
            imagem_nome TEXT,
            observacoes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()


def save_measurement_turso(
    data_medicao,
    peso,
    gordura,
    musculo,
    agua,
    visceral,
    proteina,
    massa_ossea,
    imc,
    basal,
    score,
    origem,
    imagem_nome,
    observacoes,
):
    conn = get_turso_conn()
    conn.execute(
        """
        INSERT INTO medicoes (
            data_medicao, peso, gordura, musculo, agua, visceral, proteina,
            massa_ossea, imc, basal, score, origem, imagem_nome, observacoes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            data_medicao,
            peso,
            gordura,
            musculo,
            agua,
            visceral,
            proteina,
            massa_ossea,
            imc,
            basal,
            score,
            origem,
            imagem_nome,
            observacoes,
        ],
    )
    conn.commit()


def load_measurements_df() -> pd.DataFrame:
    conn = get_turso_conn()
    rows = conn.execute(
        """
        SELECT
            data_medicao, peso, gordura, musculo, agua, visceral,
            proteina, massa_ossea, imc, basal, score, origem, imagem_nome, observacoes
        FROM medicoes
        ORDER BY date(data_medicao) ASC, id ASC
        """
    ).fetchall()

    if not rows:
        return pd.DataFrame()

    cols = [
        "data_medicao", "peso", "gordura", "musculo", "agua", "visceral",
        "proteina", "massa_ossea", "imc", "basal", "score", "origem",
        "imagem_nome", "observacoes"
    ]
    df = pd.DataFrame(rows, columns=cols)
    df["data_medicao"] = pd.to_datetime(df["data_medicao"], errors="coerce")
    return df


# -----------------------------------------------------------------------------
# INIT
# -----------------------------------------------------------------------------
init_db()

if "claude_analysis_html" not in st.session_state:
    st.session_state["claude_analysis_html"] = "Clique no botão para gerar uma análise com o Claude."

if "zepp_upload_analysis_html" not in st.session_state:
    st.session_state["zepp_upload_analysis_html"] = "Envie um print do Zepp Life para analisar."

if "extracted_measurement" not in st.session_state:
    st.session_state["extracted_measurement"] = None


# -----------------------------------------------------------------------------
# LOAD DATA
# -----------------------------------------------------------------------------
df_db = load_measurements_df()

if not df_db.empty:
    current_row = df_db.sort_values("data_medicao").iloc[-1].to_dict()
    historico = df_db[["data_medicao", "peso", "gordura", "musculo"]].dropna(subset=["data_medicao"]).copy()
else:
    historico = pd.DataFrame(
        {
            "data_medicao": pd.to_datetime(
                [
                    "2025-12-18", "2025-12-22", "2025-12-26", "2025-12-30",
                    "2026-01-03", "2026-01-07", "2026-01-11", "2026-01-15",
                    "2026-01-19", "2026-01-23", "2026-01-27", "2026-01-31",
                    "2026-02-04", "2026-02-08", "2026-02-12", "2026-02-16",
                    "2026-02-20", "2026-02-24", "2026-02-28", "2026-03-04",
                    "2026-03-08", "2026-03-12", "2026-03-16", "2026-03-20",
                    "2026-03-24", "2026-03-28", "2026-04-01", "2026-04-05",
                ]
            ),
            "peso": [
                93.0, 92.8, 92.6, 92.5, 92.4, 92.3, 92.1, 92.0,
                91.9, 91.8, 91.8, 91.7, 91.7, 91.6, 91.6, 91.7,
                91.6, 91.5, 91.5, 91.6, 91.5, 91.5, 91.4, 91.5,
                91.4, 91.4, 91.6, 91.6
            ],
            "gordura": [
                30.1, 30.0, 29.9, 29.9, 29.8, 29.7, 29.6, 29.6,
                29.5, 29.5, 29.5, 29.4, 29.4, 29.3, 29.3, 29.4,
                29.3, 29.3, 29.2, 29.3, 29.2, 29.2, 29.2, 29.2,
                29.2, 29.2, 29.2, 29.2
            ],
            "musculo": [
                60.2, 60.3, 60.4, 60.4, 60.5, 60.6, 60.7, 60.8,
                60.9, 60.9, 61.0, 61.1, 61.1, 61.2, 61.3, 61.2,
                61.3, 61.3, 61.4, 61.3, 61.4, 61.4, 61.5, 61.4,
                61.5, 61.5, 61.5, 61.5
            ],
        }
    )
    current_row = {
        "data_medicao": pd.to_datetime("2026-04-05"),
        "peso": 91.6,
        "gordura": 29.2,
        "musculo": 61.5,
        "agua": 50.5,
        "visceral": 13,
        "proteina": 16.6,
        "massa_ossea": 3.31,
        "imc": 27.3,
        "basal": 1752,
        "score": 49,
    }

# Valores padrão / metas
DATA_ATUAL = {
    "peso": float(current_row.get("peso") or 0),
    "gordura": float(current_row.get("gordura") or 0),
    "musculo": float(current_row.get("musculo") or 0),
    "agua": float(current_row.get("agua") or 0),
    "visceral": float(current_row.get("visceral") or 0),
    "proteina": float(current_row.get("proteina") or 0),
    "massa_ossea": float(current_row.get("massa_ossea") or 0),
    "imc": float(current_row.get("imc") or 0),
    "basal": float(current_row.get("basal") or 0),
    "score": float(current_row.get("score") or 0),
    "meta_peso": 96.0,
    "meta_gordura": 20.0,
    "peso_min": 80.0,
}

# Derivados
first_row = historico.iloc[0]
peso_inicial = float(first_row["peso"])
gordura_inicial = float(first_row["gordura"])
musculo_inicial = float(first_row["musculo"])

delta_peso_total = DATA_ATUAL["peso"] - peso_inicial
delta_gordura = DATA_ATUAL["gordura"] - gordura_inicial
delta_musculo = DATA_ATUAL["musculo"] - musculo_inicial
dias_periodo = max(1, (historico["data_medicao"].max() - historico["data_medicao"].min()).days)
ritmo_peso_sem = delta_peso_total / (dias_periodo / 7)
ritmo_gordura_sem = delta_gordura / (dias_periodo / 7)
faltam_gordura_pp = DATA_ATUAL["gordura"] - DATA_ATUAL["meta_gordura"]
semanas_para_meta = abs(faltam_gordura_pp / ritmo_gordura_sem) if ritmo_gordura_sem < 0 else None
ritmo_necessario_1_ano = faltam_gordura_pp / 52 if faltam_gordura_pp > 0 else 0
peso_prog = progresso_peso(DATA_ATUAL["peso"], DATA_ATUAL["peso_min"], DATA_ATUAL["meta_peso"])
gordura_prog = progresso_gordura(gordura_inicial, DATA_ATUAL["gordura"], DATA_ATUAL["meta_gordura"])

mes_abrev = pd.to_datetime(historico["data_medicao"].max()).strftime("%b %Y").upper()

# Tags simples
peso_status = "Em queda" if delta_peso_total < 0 else "Em alta"
gordura_status = "Alta" if DATA_ATUAL["gordura"] >= 25 else "Boa"
musculo_status = "Boa" if DATA_ATUAL["musculo"] >= musculo_inicial else "Baixa"
agua_status = "Insuf." if DATA_ATUAL["agua"] < 52 else "Boa"
visceral_status = "Alta" if DATA_ATUAL["visceral"] >= 13 else "Boa"
proteina_status = "Normal" if DATA_ATUAL["proteina"] >= 16 else "Baixa"


# -----------------------------------------------------------------------------
# CSS
# -----------------------------------------------------------------------------
st.html(
    html_block("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Sans:wght@300;400;500;700&display=swap');
:root{
  --bg:#F5F2EC; --card:#FDFAF5; --teal:#4AADA0; --coral:#D45F50; --sage:#5FA04E;
  --honey:#D4A84B; --text:#2C2A26; --muted:#9A9590; --border:#E8E3D8; --goal:#B07D3A;
  --blue:#5BA8C4; --brown:#C4A882; --radius:18px;
}
html, body, .stApp { background: var(--bg); }
body, .stApp { font-family: 'DM Sans', sans-serif; color: var(--text); }
.block-container { padding-top: 0.6rem; padding-bottom: 3rem; max-width: 1180px; }
[data-testid="stHeader"]{ background: transparent; }

/* ── HEADER COMPACTO ────────────────────────────────────────────────────── */
.top-header { display:flex; justify-content:space-between; align-items:center; gap:16px; margin-bottom:4px; }
.page-title { font-family:'DM Serif Display', serif; font-size: clamp(1.6rem, 2.5vw, 2.8rem); line-height:1.1; color: var(--text); margin:0; }
.page-title em { color: var(--coral); font-style: italic; }
.date-badge { font-size:.78rem; font-weight:700; color:var(--muted); background:#ECE7DE; border-radius:999px; padding:6px 12px; white-space:nowrap; text-transform:uppercase; letter-spacing:.06em; }
.subtitle { color:var(--muted); font-size:.88rem; font-weight:300; margin-top:2px; margin-bottom:10px; }

/* ── BANNER COMPACTO (barra fina) ───────────────────────────────────────── */
.banner-compact {
  background: linear-gradient(135deg, #2C2A26 0%, #3D3A34 100%);
  border-radius: 14px;
  padding: 12px 18px;
  color: #F5F2EC;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
  box-shadow: 0 4px 14px rgba(44,42,38,.10);
}
.banner-compact .b-left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.banner-compact .b-icon { font-size: 1.15rem; flex-shrink: 0; }
.banner-compact .b-title {
  font-family: 'DM Serif Display', serif;
  font-size: 1.05rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.banner-compact .b-sub {
  color: rgba(245,242,236,0.55);
  font-size: .82rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-left: 6px;
}
.banner-compact .b-chip {
  background: var(--honey);
  color: var(--text);
  font-weight: 700;
  border-radius: 999px;
  padding: 5px 11px;
  text-transform: uppercase;
  font-size: .72rem;
  letter-spacing: .04em;
  flex-shrink: 0;
}

/* ── CARDS ───────────────────────────────────────────────────────────────── */
.metric-card, .meta-card, .proj-card, .insight-card, .score-card, .upload-card, .history-card {
  background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: 0 2px 12px rgba(44,42,38,.03);
}

/* Score card — mesmo estilo visual dos metric cards */
.score-card {
  background: var(--card);
  border: 1px solid var(--border);
  padding: 18px 18px 20px 18px;
  position: relative;
  overflow: hidden;
  min-height: 108px;
}
.score-card::after {
  content: '';
  position: absolute;
  left: 0; right: 0; bottom: 0;
  height: 4px;
  background: linear-gradient(90deg, var(--coral), var(--honey));
}
.score-label { color: var(--muted); text-transform: uppercase; font-size: .82rem; letter-spacing: .06em; font-weight: 700; }
.score-num { font-family: 'DM Serif Display', serif; color: var(--text); font-size: 2.8rem; line-height: 1.1; margin-top: 4px; }
.score-delta { font-size: 1rem; font-weight: 600; margin-top: 8px; }
.score-delta-up { color: var(--coral); }
.score-delta-down { color: var(--sage); }

.metric-card { padding:18px 18px 20px 18px; position:relative; overflow:hidden; min-height:108px; }
.metric-card::after{ content:''; position:absolute; left:0; right:0; bottom:0; height:4px; }
.metric-teal::after{background:var(--teal);} .metric-coral::after{background:var(--coral);}
.metric-sage::after{background:var(--sage);} .metric-honey::after{background:var(--honey);}
.metric-blue::after{background:var(--blue);} .metric-brown::after{background:var(--brown);}
.metric-name { color: var(--muted); text-transform: uppercase; font-size:.82rem; letter-spacing:.06em; font-weight:700; }
.metric-value { font-family:'DM Serif Display', serif; color:var(--text); font-size:2.8rem; line-height:1.1; margin-top:4px; }
.metric-unit { font-family:'DM Sans', sans-serif; font-size:1.1rem; color:var(--muted); font-weight:400; }
.tag { display:inline-block; margin-top:8px; padding:5px 10px; border-radius:999px; font-size:.86rem; font-weight:700; }
.tag-ok{ background:#E6F4EC; color:#4A9A5E; } .tag-hi{ background:#FDECEA; color:#C0503F; } .tag-mid{ background:#FFF8E8; color:#A07830; }

.meta-card{ padding:22px; min-height:270px; }
.meta-top { display:flex; justify-content:space-between; align-items:flex-start; gap:12px; margin-bottom:16px; }
.meta-label { color:var(--muted); text-transform:uppercase; letter-spacing:.06em; font-size:.82rem; font-weight:700; }
.meta-title { font-family:'DM Serif Display', serif; font-size:1.9rem; line-height:1.2; margin-top:4px; }
.meta-chip { padding:7px 12px; border-radius:999px; font-size:.9rem; font-weight:700; white-space:nowrap; }
.chip-peso{ background:#E0F4F2; color:#2A7A72; } .chip-gordura{ background:#FDECEA; color:#A03828; }
.meta-progress-labels { display:flex; justify-content:space-between; color:var(--muted); font-size:.95rem; margin-bottom:8px; }
.meta-progress-labels strong{ color:var(--text); }
.track { width:100%; height:14px; background: var(--border); border-radius:999px; position:relative; overflow:visible; }
.fill { height:100%; border-radius:999px; position:relative; }
.fill-teal{ background: linear-gradient(90deg,#4AADA0,#6BCFC5); } .fill-coral{ background: linear-gradient(90deg,#D45F50,#E08070); }
.marker{ position:absolute; top:50%; right:0; transform: translate(50%, -50%); width:20px; height:20px; border-radius:50%; border:3px solid white; box-shadow:0 2px 8px rgba(0,0,0,.15); }
.marker-teal{ background:var(--teal); } .marker-coral{ background:var(--coral); }
.meta-nums { display:flex; justify-content:space-between; align-items:flex-end; margin-top:18px; }
.meta-small { color:var(--muted); text-transform:uppercase; letter-spacing:.05em; font-size:.8rem; font-weight:700; }
.meta-current, .meta-goal { font-family:'DM Serif Display', serif; font-size:3rem; line-height:1.1; }
.meta-goal { color: var(--goal); }
.meta-unit { font-family:'DM Sans', sans-serif; color:var(--muted); font-size:1rem; }
.meta-arrow { color:var(--muted); font-size:1.8rem; padding-bottom:10px; }
.meta-diff { margin-top:10px; color:var(--muted); font-size:1rem; } .meta-diff strong{ color:var(--text); }

.proj-card, .insight-card, .upload-card, .history-card { padding:22px; }
.section-title { font-family:'DM Serif Display', serif; font-size:2rem; margin-bottom:16px; }
.proj-item { display:flex; gap:12px; padding:12px 0; border-bottom:1px solid var(--border); }
.proj-item:last-child { border-bottom:none; }
.dot { width:10px; height:10px; border-radius:50%; margin-top:7px; flex-shrink:0; }
.dot-teal{background:var(--teal);} .dot-coral{background:var(--coral);} .dot-sage{background:var(--sage);} .dot-honey{background:var(--honey);}
.proj-label { color:var(--muted); text-transform:uppercase; letter-spacing:.05em; font-size:.82rem; }
.proj-val { color:var(--text); font-size:1.15rem; margin-top:2px; } .proj-val em { font-style:normal; font-weight:700; }

.insight-head { display:flex; justify-content:space-between; align-items:center; gap:12px; margin-bottom:8px; }
.powered { color:var(--muted); font-size:.9rem; display:flex; align-items:center; gap:6px; }
.ai-dot { width:8px; height:8px; border-radius:50%; background:var(--teal); }
.insight-body, .upload-result { color:var(--text); font-size:1.05rem; line-height:1.8; font-weight:300; }
.hi-green{ color:#4A9A5E; font-weight:700; } .hi-red{ color:#C0503F; font-weight:700; } .hi-gold{ color:#9A6A20; font-weight:700; }

.history-row { display:flex; justify-content:space-between; align-items:center; padding:12px 0; border-bottom:1px solid var(--border); }
.history-row:last-child { border-bottom:none; }
.history-date { color:var(--muted); font-size:.98rem; }
.history-peso { font-family:'DM Serif Display', serif; font-size:1.25rem; }
.delta-up { color:var(--coral); font-weight:700; } .delta-down { color:var(--sage); font-weight:700; }

@media (max-width: 900px){
  .score-card { min-height: auto; }
  .score-num { font-size: 2.1rem; }
  .metric-value { font-size: 2.1rem; }
  .meta-title { font-size: 1.5rem; }
  .meta-current, .meta-goal { font-size: 2.2rem; }
  .section-title { font-size: 1.6rem; }
  .banner-compact { flex-wrap: wrap; }
  .banner-compact .b-sub { display: none; }
}
</style>
""")
)

# -----------------------------------------------------------------------------
# HEADER (compacto)
# -----------------------------------------------------------------------------
st.html(
    html_block(f"""
<div class="top-header">
    <div>
        <div class="page-title">Corpo em <em>evolução</em></div>
        <div class="subtitle">Composição corporal · Zepp Life · Turso + Claude</div>
    </div>
    <div class="date-badge">{mes_abrev}</div>
</div>
""")
)

# Banner compacto — uma linha só
st.html(
    html_block(f"""
<div class="banner-compact">
    <div class="b-left">
        <span class="b-icon">⚡</span>
        <span class="b-title">Recomposição corporal em andamento</span>
        <span class="b-sub">
            +{fmt_num(DATA_ATUAL["meta_peso"] - DATA_ATUAL["peso"], 1)} kg · −{fmt_num(DATA_ATUAL["gordura"] - DATA_ATUAL["meta_gordura"], 1)} pp gordura
        </span>
    </div>
    <div class="b-chip">Avançado</div>
</div>
""")
)

# -----------------------------------------------------------------------------
# GRID DE MÉTRICAS — 4 colunas (score integrado ao grid)
# -----------------------------------------------------------------------------
g1, g2, g3, g4 = st.columns(4, gap="small")

with g1:
    delta_class = "score-delta-down" if delta_peso_total < 0 else "score-delta-up"
    delta_arrow = "↓" if delta_peso_total < 0 else "↑"
    st.html(
        html_block(f"""
<div class="score-card">
    <div class="score-label">Score</div>
    <div class="score-num">{int(round(DATA_ATUAL["score"]))}</div>
    <div class="score-delta {delta_class}">{delta_arrow} {fmt_num(abs(delta_peso_total), 2)} kg</div>
</div>
""")
    )

with g2:
    st.html(
        html_block(f"""
<div class="metric-card metric-teal">
    <div class="metric-name">Peso</div>
    <div class="metric-value">{fmt_num(DATA_ATUAL["peso"], 1)}<span class="metric-unit">kg</span></div>
    <span class="tag {status_class(peso_status)}">{peso_status}</span>
</div>
""")
    )

with g3:
    st.html(
        html_block(f"""
<div class="metric-card metric-coral">
    <div class="metric-name">Gordura</div>
    <div class="metric-value">{fmt_num(DATA_ATUAL["gordura"], 1)}<span class="metric-unit">%</span></div>
    <span class="tag {status_class(gordura_status)}">{gordura_status}</span>
</div>
""")
    )

with g4:
    st.html(
        html_block(f"""
<div class="metric-card metric-sage">
    <div class="metric-name">Músculo</div>
    <div class="metric-value">{fmt_num(DATA_ATUAL["musculo"], 1)}<span class="metric-unit">kg</span></div>
    <span class="tag {status_class(musculo_status)}">{musculo_status}</span>
</div>
""")
    )

# Segunda linha de métricas — 3 colunas
r2c1, r2c2, r2c3 = st.columns(3, gap="small")

with r2c1:
    st.html(
        html_block(f"""
<div class="metric-card metric-honey">
    <div class="metric-name">Água</div>
    <div class="metric-value">{fmt_num(DATA_ATUAL["agua"], 1)}<span class="metric-unit">%</span></div>
    <span class="tag {status_class(agua_status)}">{agua_status}</span>
</div>
""")
    )

with r2c2:
    st.html(
        html_block(f"""
<div class="metric-card metric-blue">
    <div class="metric-name">Visceral</div>
    <div class="metric-value">{fmt_num(DATA_ATUAL["visceral"], 1)}<span class="metric-unit"></span></div>
    <span class="tag {status_class(visceral_status)}">{visceral_status}</span>
</div>
""")
    )

with r2c3:
    st.html(
        html_block(f"""
<div class="metric-card metric-brown">
    <div class="metric-name">Proteína</div>
    <div class="metric-value">{fmt_num(DATA_ATUAL["proteina"], 1)}<span class="metric-unit">%</span></div>
    <span class="tag {status_class(proteina_status)}">{proteina_status}</span>
</div>
""")
    )

# -----------------------------------------------------------------------------
# METAS
# -----------------------------------------------------------------------------
m1, m2 = st.columns(2, gap="medium")

with m1:
    st.html(
        html_block(f"""
<div class="meta-card">
    <div class="meta-top">
        <div>
            <div class="meta-label">Meta de peso</div>
            <div class="meta-title">Ganhar massa total</div>
        </div>
        <div class="meta-chip chip-peso">+{fmt_num(DATA_ATUAL["meta_peso"] - DATA_ATUAL["peso"], 1)} kg</div>
    </div>
    <div class="meta-progress-labels">
        <span>Mín: <strong>{fmt_num(DATA_ATUAL["peso_min"], 0)} kg</strong></span>
        <span>Meta: <strong>{fmt_num(DATA_ATUAL["meta_peso"], 0)} kg</strong></span>
    </div>
    <div class="track">
        <div class="fill fill-teal" style="width:{peso_prog * 100:.1f}%">
            <div class="marker marker-teal"></div>
        </div>
    </div>
    <div class="meta-nums">
        <div>
            <div class="meta-small">Atual</div>
            <div class="meta-current">{fmt_num(DATA_ATUAL["peso"], 1)}<span class="meta-unit"> kg</span></div>
        </div>
        <div class="meta-arrow">→</div>
        <div style="text-align:right">
            <div class="meta-small" style="color:var(--goal)">Meta</div>
            <div class="meta-goal">{fmt_num(DATA_ATUAL["meta_peso"], 0)}<span class="meta-unit"> kg</span></div>
        </div>
    </div>
    <div class="meta-diff">
        Faltam <strong>+{fmt_num(DATA_ATUAL["meta_peso"] - DATA_ATUAL["peso"], 1)} kg</strong> · {peso_prog * 100:.1f}% concluído
    </div>
</div>
""")
    )

with m2:
    st.html(
        html_block(f"""
<div class="meta-card">
    <div class="meta-top">
        <div>
            <div class="meta-label">Meta de gordura</div>
            <div class="meta-title">Reduzir % corporal</div>
        </div>
        <div class="meta-chip chip-gordura">−{fmt_num(DATA_ATUAL["gordura"] - DATA_ATUAL["meta_gordura"], 1)} pp</div>
    </div>
    <div class="meta-progress-labels">
        <span>Meta: <strong>{fmt_num(DATA_ATUAL["meta_gordura"], 0)}%</strong></span>
        <span>Início: <strong>{fmt_num(gordura_inicial, 1)}%</strong></span>
    </div>
    <div class="track">
        <div class="fill fill-coral" style="width:{gordura_prog * 100:.1f}%">
            <div class="marker marker-coral"></div>
        </div>
    </div>
    <div class="meta-nums">
        <div>
            <div class="meta-small">Atual</div>
            <div class="meta-current">{fmt_num(DATA_ATUAL["gordura"], 1)}<span class="meta-unit"> %</span></div>
        </div>
        <div class="meta-arrow">→</div>
        <div style="text-align:right">
            <div class="meta-small" style="color:var(--goal)">Meta</div>
            <div class="meta-goal">{fmt_num(DATA_ATUAL["meta_gordura"], 0)}<span class="meta-unit"> %</span></div>
        </div>
    </div>
    <div class="meta-diff">
        Faltam <strong>−{fmt_num(DATA_ATUAL["gordura"] - DATA_ATUAL["meta_gordura"], 1)} pp</strong> · {gordura_prog * 100:.1f}% concluído
    </div>
</div>
""")
    )

# -----------------------------------------------------------------------------
# PROJEÇÃO + ANÁLISE
# -----------------------------------------------------------------------------
p1, p2 = st.columns(2, gap="medium")

with p1:
    semanas_txt = f"≈ {round(semanas_para_meta):,} semanas".replace(",", ".") if semanas_para_meta else "Sem projeção"
    st.html(
        html_block(f"""
<div class="proj-card">
    <div class="section-title">Ritmo atual & projeção</div>
    <div class="proj-item">
        <div class="dot dot-teal"></div>
        <div>
            <div class="proj-label">Variação peso ({dias_periodo} dias)</div>
            <div class="proj-val">{fmt_num(delta_peso_total, 1)} kg · <em>{fmt_num(ritmo_peso_sem, 2)} kg/semana</em></div>
        </div>
    </div>
    <div class="proj-item">
        <div class="dot dot-coral"></div>
        <div>
            <div class="proj-label">Variação gordura ({dias_periodo} dias)</div>
            <div class="proj-val">{fmt_num(delta_gordura, 1)} pp · <em>{fmt_num(ritmo_gordura_sem, 2)} pp/semana</em></div>
        </div>
    </div>
    <div class="proj-item">
        <div class="dot dot-sage"></div>
        <div>
            <div class="proj-label">Projeção meta 20% gordura</div>
            <div class="proj-val">{semanas_txt} <em>no ritmo atual</em></div>
        </div>
    </div>
    <div class="proj-item">
        <div class="dot dot-honey"></div>
        <div>
            <div class="proj-label">Ritmo necessário p/ 1 ano</div>
            <div class="proj-val"><em>−{fmt_num(ritmo_necessario_1_ano, 2)} pp/semana</em> de gordura</div>
        </div>
    </div>
</div>
""")
    )

with p2:
    st.html(
        html_block(f"""
<div class="insight-card">
    <div class="insight-head">
        <div class="section-title" style="margin-bottom:0">Análise do período</div>
        <div class="powered"><span class="ai-dot"></span> Claude</div>
    </div>
    <div class="insight-body">{st.session_state["claude_analysis_html"]}</div>
</div>
""")
    )

if st.button("✦ Analisar agora com Claude", use_container_width=True):
    prompt = f"""
Analise estes dados de composição corporal em português do Brasil.

Peso atual: {DATA_ATUAL["peso"]} kg
Gordura atual: {DATA_ATUAL["gordura"]} %
Músculo atual: {DATA_ATUAL["musculo"]} kg
Água: {DATA_ATUAL["agua"]} %
Visceral: {DATA_ATUAL["visceral"]}
Proteína: {DATA_ATUAL["proteina"]} %
Massa óssea: {DATA_ATUAL["massa_ossea"]} kg
IMC: {DATA_ATUAL["imc"]}
Basal: {DATA_ATUAL["basal"]}
Meta de peso: {DATA_ATUAL["meta_peso"]} kg
Meta de gordura: {DATA_ATUAL["meta_gordura"]} %
Delta de peso: {delta_peso_total:.1f} kg
Delta de gordura: {delta_gordura:.1f} pp
Delta de músculo: {delta_musculo:.1f} kg
Dias avaliados: {dias_periodo}

Quero:
1. O que melhorou
2. Principal gargalo
3. O que priorizar agora

Máximo 3 blocos curtos.
"""
    try:
        with st.spinner("Claude analisando..."):
            st.session_state["claude_analysis_html"] = ask_claude_analysis(prompt)
        st.rerun()
    except Exception as e:
        st.error(f"Erro ao chamar Claude: {e}")

# -----------------------------------------------------------------------------
# CHART
# -----------------------------------------------------------------------------
fig = make_subplots(specs=[[{"secondary_y": True}]])
fig.add_trace(
    go.Scatter(
        x=historico["data_medicao"],
        y=historico["peso"],
        name="Peso",
        mode="lines+markers",
        line=dict(color="#4AADA0", width=3, shape="spline", smoothing=1.1),
        marker=dict(size=6, color="#4AADA0"),
    ),
    secondary_y=False,
)
fig.add_trace(
    go.Scatter(
        x=historico["data_medicao"],
        y=[DATA_ATUAL["meta_peso"]] * len(historico),
        name="Meta Peso",
        mode="lines",
        line=dict(color="#B07D3A", width=2, dash="dash"),
        opacity=0.9,
    ),
    secondary_y=False,
)
fig.add_trace(
    go.Scatter(
        x=historico["data_medicao"],
        y=historico["gordura"],
        name="Gordura",
        mode="lines+markers",
        line=dict(color="#D45F50", width=3, shape="spline", smoothing=1.1),
        marker=dict(size=6, color="#D45F50"),
    ),
    secondary_y=True,
)
fig.add_trace(
    go.Scatter(
        x=historico["data_medicao"],
        y=[DATA_ATUAL["meta_gordura"]] * len(historico),
        name="Meta Gordura",
        mode="lines",
        line=dict(color="#B07D3A", width=2, dash="dash"),
        opacity=0.9,
    ),
    secondary_y=True,
)
fig.add_trace(
    go.Scatter(
        x=historico["data_medicao"],
        y=historico["musculo"],
        name="Músculo",
        mode="lines+markers",
        line=dict(color="#5FA04E", width=3, shape="spline", smoothing=1.1),
        marker=dict(size=6, color="#5FA04E"),
    ),
    secondary_y=False,
)

fig.update_layout(
    title=dict(text="Evolução da composição", x=0.01, xanchor="left", font=dict(size=28)),
    height=440,
    paper_bgcolor="#FDFAF5",
    plot_bgcolor="#FDFAF5",
    margin=dict(l=20, r=20, t=70, b=20),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1.0),
    font=dict(color="#2C2A26"),
)
fig.update_xaxes(showgrid=False, tickformat="%d/%m", color="#9A9590", zeroline=False)
fig.update_yaxes(title_text="Peso / Músculo (kg)", color="#9A9590", secondary_y=False)
fig.update_yaxes(title_text="Gordura (%)", color="#D45F50", secondary_y=True)

st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

# -----------------------------------------------------------------------------
# HISTÓRICO CURTO
# -----------------------------------------------------------------------------
if not df_db.empty:
    hist_short = df_db.sort_values("data_medicao", ascending=False).head(5).copy()
    rows_html = ""
    prev_vals = hist_short["peso"].tolist()
    for i, (_, row) in enumerate(hist_short.iterrows()):
        dt = row["data_medicao"].strftime("%d %b") if pd.notna(row["data_medicao"]) else "Sem data"
        peso_txt = f"{fmt_num(row['peso'],1)} kg" if pd.notna(row["peso"]) else "—"
        if i == len(hist_short) - 1:
            delta_txt = "início"
            klass = "delta-up"
        else:
            try:
                diff = row["peso"] - hist_short.iloc[i + 1]["peso"]
                delta_txt = ("↑ " if diff > 0 else "↓ ") + fmt_num(abs(diff), 1)
                klass = "delta-up" if diff > 0 else "delta-down"
            except Exception:
                delta_txt = "—"
                klass = "delta-down"
        rows_html += f"""
<div class="history-row">
    <span class="history-date">{dt}</span>
    <span class="history-peso">{peso_txt}</span>
    <span class="{klass}">{delta_txt}</span>
</div>
"""
    st.html(
        html_block(f"""
<div class="history-card">
    <div class="section-title" style="font-size:1.8rem">Últimas medições salvas</div>
    {rows_html}
</div>
""")
    )

# -----------------------------------------------------------------------------
# UPLOAD + EXTRAÇÃO + SAVE
# -----------------------------------------------------------------------------
st.html(
    html_block("""
<div class="upload-card">
    <div class="section-title" style="margin-bottom:8px">Upload Zepp Life</div>
    <div style="color:#9A9590;font-size:1rem">
        Envie um print do Zepp Life. O Claude lê a imagem, extrai os números e você confere antes de salvar no Turso.
    </div>
</div>
""")
)

upload = st.file_uploader(
    "Enviar print do Zepp Life",
    type=["png", "jpg", "jpeg", "webp"],
    label_visibility="collapsed",
)

if upload is not None:
    st.image(upload, caption="Imagem enviada", use_container_width=True)

    c_extract, c_clear = st.columns([1, 1], gap="small")
    with c_extract:
        if st.button("✦ Extrair dados da imagem", use_container_width=True):
            try:
                with st.spinner("Claude lendo a imagem..."):
                    extracted = extract_zepp_structured(upload)
                    st.session_state["extracted_measurement"] = extracted
                    st.session_state["zepp_upload_analysis_html"] = analyze_extracted_measurement(extracted, DATA_ATUAL)
                st.rerun()
            except Exception as e:
                st.error(f"Erro ao extrair dados da imagem: {e}")

    with c_clear:
        if st.button("Limpar leitura", use_container_width=True):
            st.session_state["extracted_measurement"] = None
            st.session_state["zepp_upload_analysis_html"] = "Envie um print do Zepp Life para analisar."
            st.rerun()

    st.html(
        html_block(f"""
<div class="upload-card">
    <div class="section-title" style="margin-bottom:8px">Análise multimodal</div>
    <div class="upload-result">{st.session_state["zepp_upload_analysis_html"]}</div>
</div>
""")
    )

    extracted = st.session_state.get("extracted_measurement")
    if extracted:
        st.subheader("Conferir dados antes de salvar")

        with st.form("save_extracted_measurement"):
            data_medicao = st.text_input(
                "Data da medição (YYYY-MM-DD)",
                value=extracted.get("data_medicao") or str(date.today()),
            )

            fc1, fc2, fc3 = st.columns(3)
            with fc1:
                peso = st.number_input("Peso", value=float(extracted.get("peso") or 0.0), step=0.1)
                agua = st.number_input("Água", value=float(extracted.get("agua") or 0.0), step=0.1)
                massa_ossea = st.number_input("Massa óssea", value=float(extracted.get("massa_ossea") or 0.0), step=0.1)
            with fc2:
                gordura = st.number_input("Gordura", value=float(extracted.get("gordura") or 0.0), step=0.1)
                visceral = st.number_input("Visceral", value=float(extracted.get("visceral") or 0.0), step=0.1)
                imc = st.number_input("IMC", value=float(extracted.get("imc") or 0.0), step=0.1)
            with fc3:
                musculo = st.number_input("Músculo", value=float(extracted.get("musculo") or 0.0), step=0.1)
                proteina = st.number_input("Proteína", value=float(extracted.get("proteina") or 0.0), step=0.1)
                basal = st.number_input("Basal", value=float(extracted.get("basal") or 0.0), step=1.0)

            score = st.number_input("Score", value=float(extracted.get("score") or 0.0), step=1.0)
            observacoes = st.text_area(
                "Observações",
                value=extracted.get("observacoes") or "",
                height=80,
            )

            submitted = st.form_submit_button("Salvar medição no Turso", use_container_width=True)

        if submitted:
            try:
                save_measurement_turso(
                    data_medicao=data_medicao,
                    peso=peso,
                    gordura=gordura,
                    musculo=musculo,
                    agua=agua,
                    visceral=visceral,
                    proteina=proteina,
                    massa_ossea=massa_ossea,
                    imc=imc,
                    basal=basal,
                    score=score,
                    origem="zepp_upload",
                    imagem_nome=upload.name,
                    observacoes=observacoes,
                )
                st.success("Medição salva no Turso com sucesso.")
                st.session_state["extracted_measurement"] = None
                st.rerun()
            except Exception as e:
                st.error(f"Erro ao salvar no Turso: {e}")
