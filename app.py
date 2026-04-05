from textwrap import dedent
import base64
import html
import json
import mimetypes
import re
import requests
from datetime import date, timedelta

import anthropic
import libsql
import numpy as np
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


def treino_chip_html(tipo: str) -> str:
    TREINO_CHIPS = {
        "Musculação": "chip-musculacao",
        "Cardio": "chip-cardio",
        "HIIT": "chip-hiit",
        "Descanso": "chip-descanso",
        "Outro": "chip-outro",
    }
    cls = TREINO_CHIPS.get(tipo, "chip-outro")
    return f'<span class="treino-chip {cls}">{tipo}</span>'


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


def ask_claude_stagnation(tipo: str) -> str:
    prompt = f"""
Sou um atleta em recomposição corporal.
Minhas últimas 3+ medições mostram estagnação em: {tipo}.
Peso ~90 kg, gordura ~28%, músculo ~61 kg.
Treino às 20h, uso whey como principal fonte proteica, apetite baixo.

Dê 3 sugestões práticas e diretas para quebrar essa estagnação.
Cada sugestão em 1 frase curta.
Responda em português do Brasil. Sem introdução, sem listas longas.
"""
    return ask_claude_analysis(prompt)


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
                    {"type": "text", "text": extraction_prompt},
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
            data = json.loads(raw_text[start : end + 1])
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
# PROJEÇÃO LINEAR
# -----------------------------------------------------------------------------
def calcular_projecao(
    historico: pd.DataFrame,
    coluna: str,
    meta: float,
    dias_max: int = 730,
) -> tuple[list, list]:
    df = historico[["data_medicao", coluna]].dropna().copy()
    if len(df) < 2:
        return [], []

    df = df.sort_values("data_medicao")
    x = (df["data_medicao"] - df["data_medicao"].min()).dt.days.values
    y = df[coluna].values

    # Se todos os x são iguais (1 único dia de dado), polyfit explode
    if len(set(x)) < 2:
        return [], []

    try:
        coeffs = np.polyfit(x, y, 1)
    except np.linalg.LinAlgError:
        return [], []

    slope = coeffs[0]

    if slope == 0:
        return [], []

    atingivel = (meta < y[-1] and slope < 0) or (meta > y[-1] and slope > 0)
    if not atingivel:
        return [], []

    dias_para_meta = int((meta - coeffs[1]) / slope)
    dias_para_meta = min(max(dias_para_meta, 0), dias_max)

    data_inicio_proj = df["data_medicao"].max()
    datas = [
        data_inicio_proj + timedelta(days=d)
        for d in range(0, dias_para_meta + 1, 7)
    ]
    x_proj = [(d - df["data_medicao"].min()).days for d in datas]
    valores = [float(np.polyval(coeffs, xi)) for xi in x_proj]

    return datas, valores


# -----------------------------------------------------------------------------
# DETECÇÃO DE ESTAGNAÇÃO
# -----------------------------------------------------------------------------
def detectar_estagnacao(
    df: pd.DataFrame,
    n: int = 3,
    tol_gordura: float = 0.15,
    tol_musculo: float = 0.1,
) -> dict:
    result = {"gordura": False, "musculo": False, "n": n}
    if df.empty or len(df) < n:
        return result

    ultimas = df.sort_values("data_medicao").tail(n)

    gordura_vals = ultimas["gordura"].dropna().tolist()
    musculo_vals = ultimas["musculo"].dropna().tolist()

    if len(gordura_vals) >= n:
        amplitude_g = max(gordura_vals) - min(gordura_vals)
        result["gordura"] = amplitude_g <= tol_gordura

    if len(musculo_vals) >= n:
        amplitude_m = max(musculo_vals) - min(musculo_vals)
        result["musculo"] = amplitude_m <= tol_musculo

    return result


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


def init_nutri_db():
    conn = get_turso_conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS nutricao_diaria (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_log TEXT,
            proteina_g REAL,
            calorias_kcal REAL,
            whey_doses INTEGER,
            tipo_treino TEXT,
            hora_treino TEXT,
            notas TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()


def init_atividade_db():
    conn = get_turso_conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS atividade_diaria (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_log TEXT,
            calorias_ativas REAL,
            passos INTEGER,
            minutos_movimento INTEGER,
            origem TEXT DEFAULT 'manual',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()


def save_atividade_log(data_log, calorias_ativas, passos, minutos_movimento, origem="ocr"):
    conn = get_turso_conn()
    conn.execute(
        """
        INSERT INTO atividade_diaria
            (data_log, calorias_ativas, passos, minutos_movimento, origem)
        VALUES (?, ?, ?, ?, ?)
        """,
        [data_log, calorias_ativas, passos, minutos_movimento, origem],
    )
    conn.commit()


def load_atividade_df() -> pd.DataFrame:
    conn = get_turso_conn()
    rows = conn.execute(
        """
        SELECT data_log, calorias_ativas, passos, minutos_movimento, origem
        FROM atividade_diaria
        ORDER BY date(data_log) DESC
        LIMIT 30
        """
    ).fetchall()
    if not rows:
        return pd.DataFrame()
    cols = ["data_log", "calorias_ativas", "passos", "minutos_movimento", "origem"]
    df = pd.DataFrame(rows, columns=cols)
    df["data_log"] = pd.to_datetime(df["data_log"], errors="coerce")
    return df


# ── OCR.space ─────────────────────────────────────────────────────────────────
def extrair_mifitness_ocr(uploaded_file) -> dict:
    """
    Envia imagem para OCR.space e extrai calorias, passos e minutos de movimento
    do Mi Fitness via regex no texto retornado.
    """
    api_key = st.secrets["OCR_SPACE_API_KEY"]
    file_bytes = uploaded_file.getvalue()

    response = requests.post(
        "https://api.ocr.space/parse/image",
        files={"file": (uploaded_file.name, file_bytes, uploaded_file.type or "image/jpeg")},
        data={
            "apikey": api_key,
            "language": "por",
            "isOverlayRequired": False,
            "detectOrientation": True,
            "scale": True,
            "OCREngine": 2,
        },
        timeout=20,
    )
    response.raise_for_status()
    result = response.json()

    if result.get("IsErroredOnProcessing"):
        raise ValueError(result.get("ErrorMessage", "OCR falhou"))

    texto = " ".join(
        p.get("ParsedText", "")
        for p in result.get("ParsedResults", [])
    )

    def extrair_numero(patterns: list[str], texto: str) -> float | None:
        for pat in patterns:
            m = re.search(pat, texto, re.IGNORECASE)
            if m:
                try:
                    return float(m.group(1).replace(",", "."))
                except Exception:
                    pass
        return None

    calorias = extrair_numero(
        [r"(\d+[\.,]?\d*)\s*kcal", r"Calorias\D{0,10}(\d+)"],
        texto,
    )
    passos = extrair_numero(
        [r"(\d[\d\.]*)\s*passos", r"Passos\D{0,10}([\d\.]+)"],
        texto,
    )
    movimento = extrair_numero(
        [r"(\d+)\s*min", r"Movimento\D{0,10}(\d+)"],
        texto,
    )

    # limpar separador de milhar em passos (ex: "1.221" → 1221)
    if passos and passos < 10 and "." in str(passos):
        passos = passos * 1000

    return {
        "calorias_ativas": calorias,
        "passos": int(passos) if passos else None,
        "minutos_movimento": int(movimento) if movimento else None,
        "texto_ocr": texto[:300],
    }


def save_measurement_turso(
    data_medicao, peso, gordura, musculo, agua, visceral, proteina,
    massa_ossea, imc, basal, score, origem, imagem_nome, observacoes,
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
            data_medicao, peso, gordura, musculo, agua, visceral, proteina,
            massa_ossea, imc, basal, score, origem, imagem_nome, observacoes,
        ],
    )
    conn.commit()


def save_nutri_log(
    data_log, proteina_g, calorias_kcal, whey_doses,
    tipo_treino, hora_treino, notas,
):
    conn = get_turso_conn()
    conn.execute(
        """
        INSERT INTO nutricao_diaria
            (data_log, proteina_g, calorias_kcal, whey_doses, tipo_treino, hora_treino, notas)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [data_log, proteina_g, calorias_kcal, whey_doses, tipo_treino, hora_treino, notas],
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
        "imagem_nome", "observacoes",
    ]
    df = pd.DataFrame(rows, columns=cols)
    df["data_medicao"] = pd.to_datetime(df["data_medicao"], errors="coerce")
    return df


def load_nutri_df() -> pd.DataFrame:
    conn = get_turso_conn()
    rows = conn.execute(
        """
        SELECT data_log, proteina_g, calorias_kcal, whey_doses,
               tipo_treino, hora_treino, notas
        FROM nutricao_diaria
        ORDER BY date(data_log) DESC
        LIMIT 30
        """
    ).fetchall()
    if not rows:
        return pd.DataFrame()
    cols = [
        "data_log", "proteina_g", "calorias_kcal", "whey_doses",
        "tipo_treino", "hora_treino", "notas",
    ]
    df = pd.DataFrame(rows, columns=cols)
    df["data_log"] = pd.to_datetime(df["data_log"], errors="coerce")
    return df


# -----------------------------------------------------------------------------
# INIT
# -----------------------------------------------------------------------------
init_db()
init_nutri_db()
init_atividade_db()

if "claude_analysis_html" not in st.session_state:
    st.session_state["claude_analysis_html"] = "Clique no botão para gerar uma análise com o Claude."

if "zepp_upload_analysis_html" not in st.session_state:
    st.session_state["zepp_upload_analysis_html"] = "Envie um print do Zepp Life para analisar."

if "extracted_measurement" not in st.session_state:
    st.session_state["extracted_measurement"] = None

if "claude_stagnation_html" not in st.session_state:
    st.session_state["claude_stagnation_html"] = None

if "mifitness_ocr" not in st.session_state:
    st.session_state["mifitness_ocr"] = None


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
                91.4, 91.4, 91.6, 91.6,
            ],
            "gordura": [
                30.1, 30.0, 29.9, 29.9, 29.8, 29.7, 29.6, 29.6,
                29.5, 29.5, 29.5, 29.4, 29.4, 29.3, 29.3, 29.4,
                29.3, 29.3, 29.2, 29.3, 29.2, 29.2, 29.2, 29.2,
                29.2, 29.2, 29.2, 29.2,
            ],
            "musculo": [
                60.2, 60.3, 60.4, 60.4, 60.5, 60.6, 60.7, 60.8,
                60.9, 60.9, 61.0, 61.1, 61.1, 61.2, 61.3, 61.2,
                61.3, 61.3, 61.4, 61.3, 61.4, 61.4, 61.5, 61.4,
                61.5, 61.5, 61.5, 61.5,
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

peso_status = "Em queda" if delta_peso_total < 0 else "Em alta"
gordura_status = "Alta" if DATA_ATUAL["gordura"] >= 25 else "Boa"
musculo_status = "Boa" if DATA_ATUAL["musculo"] >= musculo_inicial else "Baixa"
agua_status = "Insuf." if DATA_ATUAL["agua"] < 52 else "Boa"
visceral_status = "Alta" if DATA_ATUAL["visceral"] >= 13 else "Boa"
proteina_status = "Normal" if DATA_ATUAL["proteina"] >= 16 else "Baixa"

# ── Estagnação ────────────────────────────────────────────────────────────────
estag = detectar_estagnacao(df_db, n=3) if not df_db.empty else {"gordura": False, "musculo": False, "n": 3}
estag_ativa = estag["gordura"] or estag["musculo"]

# ── Projeções ─────────────────────────────────────────────────────────────────
datas_proj_peso, vals_proj_peso = calcular_projecao(historico, "peso", DATA_ATUAL["meta_peso"])
datas_proj_gord, vals_proj_gord = calcular_projecao(historico, "gordura", DATA_ATUAL["meta_gordura"])


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
.block-container { padding-top: 1.8rem; padding-bottom: 3rem; max-width: 1180px; }
[data-testid="stHeader"]{ background: transparent; }

.top-header { display:flex; justify-content:space-between; align-items:flex-start; gap:16px; margin-bottom:8px; }
.page-title { font-family:'DM Serif Display', serif; font-size: clamp(2rem, 3vw, 3.5rem); line-height:1.05; color: var(--text); margin:0; }
.page-title em { color: var(--coral); font-style: italic; }
.date-badge { font-size:.85rem; font-weight:700; color:var(--muted); background:#ECE7DE; border-radius:999px; padding:8px 14px; white-space:nowrap; text-transform:uppercase; letter-spacing:.06em; }
.subtitle { color:var(--muted); font-size:1rem; font-weight:300; margin-top:4px; margin-bottom:20px; }

.banner { border-radius:24px; padding:22px 24px; color:#F5F2EC; display:flex; align-items:center; justify-content:space-between; gap:16px; margin-bottom:18px; box-shadow: 0 10px 24px rgba(44,42,38,.12); }
.banner-ok  { background: linear-gradient(135deg, #2C2A26 0%, #3D3A34 100%); }
.banner-stall { background: linear-gradient(135deg, #5C2A20 0%, #7A3828 100%); }
.banner-left { display:flex; gap:14px; align-items:flex-start; }
.banner-icon { font-size:1.8rem; line-height:1; }
.banner-title { font-family:'DM Serif Display', serif; font-size:1.85rem; margin-bottom:4px; }
.banner-sub { color: rgba(245,242,236,0.68); font-size:1rem; line-height:1.5; }
.banner-chip { color: var(--text); font-weight:700; border-radius:999px; padding:8px 14px; height:fit-content; text-transform:uppercase; font-size:.8rem; }

.metric-card, .meta-card, .proj-card, .insight-card, .score-card, .upload-card, .history-card, .nutri-card {
  background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: 0 2px 12px rgba(44,42,38,.03);
}
.score-card { background: linear-gradient(135deg, #2C2A26 0%, #252320 100%); color:white; padding:22px 18px; min-height:232px; position:relative; overflow:hidden; }
.score-card::before{ content:''; position:absolute; top:-34px; right:-34px; width:120px; height:120px; background: var(--coral); opacity:.14; border-radius:50%; }
.score-label { font-size:.95rem; text-transform:uppercase; letter-spacing:.10em; opacity:.65; }
.score-num { font-family:'DM Serif Display', serif; font-size:6rem; line-height:1; margin-top:12px; }
.score-delta { color:#65d0c2; font-size:1.6rem; font-weight:600; margin-top:12px; }

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

/* ── Nutrição ── */
.nutri-card { padding: 20px; }
.nutri-label { color:var(--muted); text-transform:uppercase; letter-spacing:.06em; font-size:.82rem; font-weight:700; margin-bottom:4px; }
.nutri-val { font-family:'DM Serif Display', serif; font-size:2.4rem; line-height:1.1; color:var(--text); }
.nutri-unit { font-family:'DM Sans', sans-serif; font-size:1rem; color:var(--muted); font-weight:400; }
.nutri-meta { color:var(--muted); font-size:.95rem; margin-top:6px; }
.prot-bar-wrap { width:100%; height:10px; background:var(--border); border-radius:999px; margin-top:10px; overflow:hidden; }
.prot-bar-fill { height:100%; border-radius:999px; background: linear-gradient(90deg,var(--teal),#6BCFC5); transition: width .4s ease; }
.treino-chip { display:inline-block; padding:6px 14px; border-radius:999px; font-size:.88rem; font-weight:700; margin:3px 3px 0 0; }
.chip-musculacao { background:#E0F0FE; color:#2A6A9E; }
.chip-cardio     { background:#FEF0E0; color:#9E6A2A; }
.chip-hiit       { background:#FDE8E8; color:#9E3A2A; }
.chip-descanso   { background:#F0F0F0; color:#6A6A6A; }
.chip-outro      { background:#EEE8FE; color:#5A3A9E; }
.log-row { display:flex; justify-content:space-between; align-items:center; padding:11px 0; border-bottom:1px solid var(--border); font-size:.97rem; }
.log-row:last-child { border-bottom:none; }
.log-date { color:var(--muted); min-width:60px; }
.log-prot { font-weight:700; color:var(--teal); }
.log-cal  { color:var(--text); }
.log-whey { font-size:.85rem; color:var(--muted); }

/* ── Stagnation insight ── */
.stag-insight { border-left: 4px solid #D45F50; }

/* ── Tab Gráficos ── */
.chart-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 6px;
}
.chart-title {
  font-family: 'DM Serif Display', serif;
  font-size: 1.55rem;
  color: var(--text);
  margin: 0;
}
.chart-sub {
  color: var(--muted);
  font-size: .88rem;
}
.chart-wrap {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px 18px 10px 18px;
  margin-bottom: 18px;
  box-shadow: 0 2px 12px rgba(44,42,38,.03);
}
.stat-row {
  display: flex;
  gap: 20px;
  flex-wrap: wrap;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--border);
}
.stat-pill {
  font-size: .88rem;
  color: var(--muted);
}
.stat-pill strong { color: var(--text); }

/* ── Mi Fitness OCR ── */
.mifitness-card {
  background: linear-gradient(135deg, #1A1A2E 0%, #16213E 100%);
  border: 1px solid #2A2A4A;
  border-radius: var(--radius);
  padding: 22px;
  color: #F0F0FF;
  margin-bottom: 16px;
}
.mifitness-title {
  font-family: 'DM Serif Display', serif;
  font-size: 1.6rem;
  margin-bottom: 4px;
  color: #F0F0FF;
}
.mifitness-sub {
  color: rgba(240,240,255,.55);
  font-size: .9rem;
  margin-bottom: 20px;
}
.mifitness-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
}
.mifitness-metric {
  background: rgba(255,255,255,.06);
  border-radius: 14px;
  padding: 14px 16px;
  text-align: center;
}
.mifitness-metric-icon { font-size: 1.4rem; margin-bottom: 6px; }
.mifitness-metric-label {
  color: rgba(240,240,255,.55);
  text-transform: uppercase;
  letter-spacing: .06em;
  font-size: .75rem;
  font-weight: 700;
}
.mifitness-metric-val {
  font-family: 'DM Serif Display', serif;
  font-size: 2rem;
  line-height: 1.1;
  color: #F0F0FF;
}
.mifitness-metric-unit {
  font-family: 'DM Sans', sans-serif;
  font-size: .85rem;
  color: rgba(240,240,255,.5);
}
.ocr-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: rgba(255,255,255,.08);
  border-radius: 999px;
  padding: 4px 10px;
  font-size: .8rem;
  color: rgba(240,240,255,.6);
  margin-top: 14px;
}
.ocr-dot { width: 7px; height: 7px; border-radius: 50%; background: #6BCFC5; }

@media (max-width: 900px){
  .score-card { min-height: 180px; }
  .score-num { font-size: 4.6rem; }
  .metric-value { font-size: 2.1rem; }
  .meta-title { font-size: 1.5rem; }
  .meta-current, .meta-goal { font-size: 2.2rem; }
  .section-title { font-size: 1.6rem; }
}
</style>
""")
)

# -----------------------------------------------------------------------------
# HEADER
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

# ── Banner com detecção de estagnação ─────────────────────────────────────────
if estag_ativa:
    tipo_estag = []
    if estag["gordura"]:
        tipo_estag.append("gordura")
    if estag["musculo"]:
        tipo_estag.append("músculo")
    tipo_str = " e ".join(tipo_estag)

    st.html(html_block(f"""
<div class="banner banner-stall">
    <div class="banner-left">
        <div class="banner-icon">⚠️</div>
        <div>
            <div class="banner-title">Estagnação detectada em {tipo_str}</div>
            <div class="banner-sub">
                As últimas {estag['n']} medições não mostram variação significativa.
                Hora de revisar estratégia.
            </div>
        </div>
    </div>
    <div class="banner-chip" style="background:#E08070">Atenção</div>
</div>
"""))

    col_stag_btn, _ = st.columns([1, 2])
    with col_stag_btn:
        if st.button("✦ Claude: como quebrar a estagnação?", use_container_width=True):
            with st.spinner("Analisando..."):
                st.session_state["claude_stagnation_html"] = ask_claude_stagnation(tipo_str)

    if st.session_state.get("claude_stagnation_html"):
        st.html(html_block(f"""
<div class="insight-card stag-insight" style="margin-bottom:18px">
    <div class="insight-head">
        <div class="section-title" style="margin-bottom:0;font-size:1.4rem">
            Sugestões para romper a estagnação
        </div>
        <div class="powered"><span class="ai-dot" style="background:#E08070"></span> Claude</div>
    </div>
    <div class="insight-body">{st.session_state["claude_stagnation_html"]}</div>
</div>
"""))

else:
    st.html(html_block(f"""
<div class="banner banner-ok">
    <div class="banner-left">
        <div class="banner-icon">⚡</div>
        <div>
            <div class="banner-title">Recomposição corporal em andamento</div>
            <div class="banner-sub">
                Meta simultânea: ganhar +{fmt_num(DATA_ATUAL["meta_peso"] - DATA_ATUAL["peso"], 1)} kg
                e reduzir −{fmt_num(DATA_ATUAL["gordura"] - DATA_ATUAL["meta_gordura"], 1)} pp de gordura.
                Corpo mais corpulento, não mais leve.
            </div>
        </div>
    </div>
    <div class="banner-chip" style="background:var(--honey)">Avançado</div>
</div>
"""))


# -----------------------------------------------------------------------------
# TABS PRINCIPAIS
# -----------------------------------------------------------------------------
tab_corpo, tab_nutri, tab_graficos = st.tabs(["📊  Composição Corporal", "🥩  Nutrição & Treino", "📈  Gráficos"])


# ═════════════════════════════════════════════════════════════════════════════
# TAB 1 — COMPOSIÇÃO CORPORAL
# ═════════════════════════════════════════════════════════════════════════════
with tab_corpo:

    # ── Score + Stats ──────────────────────────────────────────────────────────
    col_score, col_stats = st.columns([1.1, 4.2], gap="medium")

    with col_score:
        st.html(html_block(f"""
<div class="score-card">
    <div class="score-label">Score Recomposição</div>
    <div class="score-num">{int(round(DATA_ATUAL["score"]))}</div>
    <div class="score-delta">{'↓' if delta_peso_total < 0 else '↑'} {fmt_num(abs(delta_peso_total), 2)} kg</div>
</div>
"""))

    with col_stats:
        r1c1, r1c2, r1c3 = st.columns(3, gap="small")
        r2c1, r2c2, r2c3 = st.columns(3, gap="small")
        cards = [
            (r1c1, "Peso",     DATA_ATUAL["peso"],     "kg", peso_status,     "metric-teal"),
            (r1c2, "Gordura",  DATA_ATUAL["gordura"],  "%",  gordura_status,   "metric-coral"),
            (r1c3, "Músculo",  DATA_ATUAL["musculo"],  "kg", musculo_status,   "metric-sage"),
            (r2c1, "Água",     DATA_ATUAL["agua"],     "%",  agua_status,      "metric-honey"),
            (r2c2, "Visceral", DATA_ATUAL["visceral"], "",   visceral_status,  "metric-blue"),
            (r2c3, "Proteína", DATA_ATUAL["proteina"], "%",  proteina_status,  "metric-brown"),
        ]
        for col, nome, valor, unidade, status, klass in cards:
            with col:
                valor_txt = fmt_num(valor, 1) if isinstance(valor, float) else str(valor)
                st.html(html_block(f"""
<div class="metric-card {klass}">
    <div class="metric-name">{nome}</div>
    <div class="metric-value">{valor_txt}<span class="metric-unit">{unidade}</span></div>
    <span class="tag {status_class(status)}">{status}</span>
</div>
"""))

    # ── Metas ──────────────────────────────────────────────────────────────────
    m1, m2 = st.columns(2, gap="medium")

    with m1:
        st.html(html_block(f"""
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
        Faltam <strong>+{fmt_num(DATA_ATUAL["meta_peso"] - DATA_ATUAL["peso"], 1)} kg</strong>
        · {peso_prog * 100:.1f}% concluído
    </div>
</div>
"""))

    with m2:
        st.html(html_block(f"""
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
        Faltam <strong>−{fmt_num(DATA_ATUAL["gordura"] - DATA_ATUAL["meta_gordura"], 1)} pp</strong>
        · {gordura_prog * 100:.1f}% concluído
    </div>
</div>
"""))

    # ── Projeção + Análise ─────────────────────────────────────────────────────
    p1, p2 = st.columns(2, gap="medium")

    with p1:
        # ETAs das projeções
        eta_peso_txt = datas_proj_peso[-1].strftime("%d/%m/%Y") if datas_proj_peso else "sem ritmo claro"
        eta_gord_txt = datas_proj_gord[-1].strftime("%d/%m/%Y") if datas_proj_gord else "sem ritmo claro"
        semanas_txt = f"≈ {round(semanas_para_meta):,} semanas".replace(",", ".") if semanas_para_meta else "Sem projeção"

        st.html(html_block(f"""
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
            <div class="proj-label">ETA meta gordura 20%</div>
            <div class="proj-val"><em>{eta_gord_txt}</em> no ritmo atual</div>
        </div>
    </div>
    <div class="proj-item">
        <div class="dot dot-teal"></div>
        <div>
            <div class="proj-label">ETA meta peso 96 kg</div>
            <div class="proj-val"><em>{eta_peso_txt}</em> no ritmo atual</div>
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
"""))

    with p2:
        st.html(html_block(f"""
<div class="insight-card">
    <div class="insight-head">
        <div class="section-title" style="margin-bottom:0">Análise do período</div>
        <div class="powered"><span class="ai-dot"></span> Claude</div>
    </div>
    <div class="insight-body">{st.session_state["claude_analysis_html"]}</div>
</div>
"""))

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

    # ── Gráfico com projeção ───────────────────────────────────────────────────
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # Peso real
    fig.add_trace(
        go.Scatter(
            x=historico["data_medicao"], y=historico["peso"],
            name="Peso", mode="lines+markers",
            line=dict(color="#4AADA0", width=3, shape="spline", smoothing=1.1),
            marker=dict(size=7, color="#4AADA0"),
        ), secondary_y=False,
    )
    # Meta peso
    fig.add_trace(
        go.Scatter(
            x=historico["data_medicao"],
            y=[DATA_ATUAL["meta_peso"]] * len(historico),
            name="Meta Peso", mode="lines",
            line=dict(color="#B07D3A", width=2, dash="dash"), opacity=0.9,
        ), secondary_y=False,
    )
    # Projeção peso
    if datas_proj_peso:
        eta_peso_label = datas_proj_peso[-1].strftime("%d/%m/%Y")
        fig.add_trace(
            go.Scatter(
                x=datas_proj_peso, y=vals_proj_peso,
                name=f"Projeção Peso → {eta_peso_label}",
                mode="lines",
                line=dict(color="#4AADA0", width=2, dash="dot"),
                opacity=0.50,
            ), secondary_y=False,
        )
        fig.add_annotation(
            x=datas_proj_peso[-1], y=DATA_ATUAL["meta_peso"],
            text=f"Meta Peso<br>{eta_peso_label}",
            showarrow=True, arrowhead=2, arrowcolor="#4AADA0",
            font=dict(size=11, color="#4AADA0"),
            bgcolor="rgba(253,250,245,.92)", bordercolor="#4AADA0",
            borderwidth=1.5, borderpad=5, ax=50, ay=-40,
        )

    # Gordura real
    fig.add_trace(
        go.Scatter(
            x=historico["data_medicao"], y=historico["gordura"],
            name="Gordura %", mode="lines+markers",
            line=dict(color="#D45F50", width=3, shape="spline", smoothing=1.1),
            marker=dict(size=7, color="#D45F50"),
        ), secondary_y=True,
    )
    # Meta gordura
    fig.add_trace(
        go.Scatter(
            x=historico["data_medicao"],
            y=[DATA_ATUAL["meta_gordura"]] * len(historico),
            name="Meta Gordura", mode="lines",
            line=dict(color="#B07D3A", width=2, dash="dash"), opacity=0.9,
        ), secondary_y=True,
    )
    # Projeção gordura
    if datas_proj_gord:
        eta_gord_label = datas_proj_gord[-1].strftime("%d/%m/%Y")
        fig.add_trace(
            go.Scatter(
                x=datas_proj_gord, y=vals_proj_gord,
                name=f"Projeção Gordura → {eta_gord_label}",
                mode="lines",
                line=dict(color="#D45F50", width=2, dash="dot"),
                opacity=0.50,
            ), secondary_y=True,
        )
        fig.add_annotation(
            x=datas_proj_gord[-1], y=DATA_ATUAL["meta_gordura"],
            text=f"Meta Gordura<br>{eta_gord_label}",
            showarrow=True, arrowhead=2, arrowcolor="#D45F50",
            font=dict(size=11, color="#D45F50"),
            bgcolor="rgba(253,250,245,.92)", bordercolor="#D45F50",
            borderwidth=1.5, borderpad=5, ax=50, ay=40,
            secondary_y=True,
        )

    # Músculo real
    fig.add_trace(
        go.Scatter(
            x=historico["data_medicao"], y=historico["musculo"],
            name="Músculo", mode="lines+markers",
            line=dict(color="#5FA04E", width=3, shape="spline", smoothing=1.1),
            marker=dict(size=7, color="#5FA04E"),
        ), secondary_y=False,
    )

    fig.update_layout(
        title=dict(
            text="Evolução da composição & Score Recomposição",
            x=0.01, xanchor="left", font=dict(size=26),
        ),
        height=500,
        paper_bgcolor="#FDFAF5", plot_bgcolor="#FDFAF5",
        margin=dict(l=20, r=20, t=70, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1.0),
        font=dict(color="#2C2A26"),
        hovermode="x unified",
    )
    fig.update_xaxes(showgrid=False, tickformat="%d/%m", color="#9A9590", zeroline=False)
    fig.update_yaxes(
        title_text="Peso / Músculo (kg)", color="#9A9590",
        secondary_y=False, showgrid=True, gridcolor="#EEE9DF",
    )
    fig.update_yaxes(
        title_text="Gordura (%)", color="#D45F50",
        secondary_y=True, showgrid=False,
    )

    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    # ── Histórico curto ────────────────────────────────────────────────────────
    if not df_db.empty:
        hist_short = df_db.sort_values("data_medicao", ascending=False).head(5).copy()
        rows_html = ""
        for i, (_, row) in enumerate(hist_short.iterrows()):
            dt = row["data_medicao"].strftime("%d %b") if pd.notna(row["data_medicao"]) else "Sem data"
            peso_txt = f"{fmt_num(row['peso'], 1)} kg" if pd.notna(row["peso"]) else "—"
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
        st.html(html_block(f"""
<div class="history-card">
    <div class="section-title" style="font-size:1.8rem">Últimas medições salvas</div>
    {rows_html}
</div>
"""))

    # ── Upload Zepp ────────────────────────────────────────────────────────────
    st.html(html_block("""
<div class="upload-card">
    <div class="section-title" style="margin-bottom:8px">Upload Zepp Life</div>
    <div style="color:#9A9590;font-size:1rem">
        Envie um print do Zepp Life. O Claude lê a imagem, extrai os números
        e você confere antes de salvar no Turso.
    </div>
</div>
"""))

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
                        st.session_state["zepp_upload_analysis_html"] = analyze_extracted_measurement(
                            extracted, DATA_ATUAL
                        )
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao extrair dados da imagem: {e}")

        with c_clear:
            if st.button("Limpar leitura", use_container_width=True):
                st.session_state["extracted_measurement"] = None
                st.session_state["zepp_upload_analysis_html"] = "Envie um print do Zepp Life para analisar."
                st.rerun()

        st.html(html_block(f"""
<div class="upload-card">
    <div class="section-title" style="margin-bottom:8px">Análise multimodal</div>
    <div class="upload-result">{st.session_state["zepp_upload_analysis_html"]}</div>
</div>
"""))

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
                    peso_form = st.number_input("Peso", value=float(extracted.get("peso") or 0.0), step=0.1)
                    agua_form = st.number_input("Água", value=float(extracted.get("agua") or 0.0), step=0.1)
                    massa_ossea_form = st.number_input("Massa óssea", value=float(extracted.get("massa_ossea") or 0.0), step=0.1)
                with fc2:
                    gordura_form = st.number_input("Gordura", value=float(extracted.get("gordura") or 0.0), step=0.1)
                    visceral_form = st.number_input("Visceral", value=float(extracted.get("visceral") or 0.0), step=0.1)
                    imc_form = st.number_input("IMC", value=float(extracted.get("imc") or 0.0), step=0.1)
                with fc3:
                    musculo_form = st.number_input("Músculo", value=float(extracted.get("musculo") or 0.0), step=0.1)
                    proteina_form = st.number_input("Proteína", value=float(extracted.get("proteina") or 0.0), step=0.1)
                    basal_form = st.number_input("Basal", value=float(extracted.get("basal") or 0.0), step=1.0)

                score_form = st.number_input("Score", value=float(extracted.get("score") or 0.0), step=1.0)
                observacoes_form = st.text_area(
                    "Observações", value=extracted.get("observacoes") or "", height=80,
                )
                submitted_zepp = st.form_submit_button("Salvar medição no Turso", use_container_width=True)

            if submitted_zepp:
                try:
                    save_measurement_turso(
                        data_medicao=data_medicao,
                        peso=peso_form, gordura=gordura_form, musculo=musculo_form,
                        agua=agua_form, visceral=visceral_form, proteina=proteina_form,
                        massa_ossea=massa_ossea_form, imc=imc_form, basal=basal_form,
                        score=score_form, origem="zepp_upload",
                        imagem_nome=upload.name, observacoes=observacoes_form,
                    )
                    st.success("Medição salva no Turso com sucesso.")
                    st.session_state["extracted_measurement"] = None
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao salvar no Turso: {e}")


# ═════════════════════════════════════════════════════════════════════════════
# TAB 2 — NUTRIÇÃO & TREINO
# ═════════════════════════════════════════════════════════════════════════════
with tab_nutri:

    META_PROT_G = round(DATA_ATUAL["peso"] * 2)   # 2 g/kg — ganho muscular
    META_CAL    = 2800                              # kcal estimado (ajustar)

    df_nutri = load_nutri_df()

    # ── Dados de hoje ──────────────────────────────────────────────────────────
    nutri_hoje: dict = {}
    if not df_nutri.empty:
        hoje_rows = df_nutri[df_nutri["data_log"].dt.date == date.today()]
        if not hoje_rows.empty:
            r = hoje_rows.iloc[0]
            nutri_hoje = {
                "proteina_g":    float(r.get("proteina_g") or 0),
                "calorias_kcal": float(r.get("calorias_kcal") or 0),
                "whey_doses":    int(r.get("whey_doses") or 0),
                "tipo_treino":   str(r.get("tipo_treino") or "—"),
            }

    prot_hoje   = nutri_hoje.get("proteina_g", 0)
    cal_hoje    = nutri_hoje.get("calorias_kcal", 0)
    whey_hoje   = nutri_hoje.get("whey_doses", 0)
    treino_hoje = nutri_hoje.get("tipo_treino", "—")
    prot_pct    = min(prot_hoje / META_PROT_G, 1.0) if META_PROT_G > 0 else 0

    chip_html_hoje = treino_chip_html(treino_hoje) if treino_hoje != "—" else "—"

    # ── Cards resumo hoje ──────────────────────────────────────────────────────
    nc1, nc2, nc3, nc4 = st.columns(4, gap="small")

    with nc1:
        st.html(html_block(f"""
<div class="nutri-card">
    <div class="nutri-label">Proteína hoje</div>
    <div class="nutri-val">{int(prot_hoje)}<span class="nutri-unit"> g</span></div>
    <div class="prot-bar-wrap">
        <div class="prot-bar-fill" style="width:{prot_pct * 100:.1f}%"></div>
    </div>
    <div class="nutri-meta">Meta: {META_PROT_G} g · {prot_pct * 100:.0f}%</div>
</div>
"""))

    with nc2:
        cal_pct = min(cal_hoje / META_CAL, 1.0) if META_CAL > 0 else 0
        st.html(html_block(f"""
<div class="nutri-card">
    <div class="nutri-label">Calorias hoje</div>
    <div class="nutri-val">{int(cal_hoje)}<span class="nutri-unit"> kcal</span></div>
    <div class="prot-bar-wrap">
        <div class="prot-bar-fill" style="width:{cal_pct * 100:.1f}%;background:linear-gradient(90deg,#D4A84B,#E8C26A)"></div>
    </div>
    <div class="nutri-meta">Meta: ~{META_CAL} kcal</div>
</div>
"""))

    with nc3:
        st.html(html_block(f"""
<div class="nutri-card">
    <div class="nutri-label">Doses Whey</div>
    <div class="nutri-val">{whey_hoje}<span class="nutri-unit"> doses</span></div>
    <div class="nutri-meta">≈ {whey_hoje * 25} g proteína</div>
</div>
"""))

    with nc4:
        st.html(html_block(f"""
<div class="nutri-card">
    <div class="nutri-label">Treino hoje</div>
    <div style="margin-top:12px">{chip_html_hoje}</div>
    <div class="nutri-meta">20h · Turno noturno</div>
</div>
"""))

    st.markdown("---")

    # ── Mi Fitness OCR ────────────────────────────────────────────────────────
    st.markdown("### 🏃 Atividade física — Mi Fitness")

    df_ativ = load_atividade_df()

    # Cards de atividade de hoje
    ativ_hoje: dict = {}
    if not df_ativ.empty:
        ativ_hoje_rows = df_ativ[df_ativ["data_log"].dt.date == date.today()]
        if not ativ_hoje_rows.empty:
            r2 = ativ_hoje_rows.iloc[0]
            ativ_hoje = {
                "calorias_ativas": float(r2.get("calorias_ativas") or 0),
                "passos":          int(r2.get("passos") or 0),
                "minutos_movimento": int(r2.get("minutos_movimento") or 0),
            }

    cal_ativas_hoje = ativ_hoje.get("calorias_ativas", 0)
    passos_hoje     = ativ_hoje.get("passos", 0)
    mov_hoje        = ativ_hoje.get("minutos_movimento", 0)

    META_PASSOS = 8000
    META_MOV    = 30
    passos_pct  = min(passos_hoje / META_PASSOS, 1.0)
    mov_pct     = min(mov_hoje / META_MOV, 1.0)

    ac1, ac2, ac3 = st.columns(3, gap="small")
    with ac1:
        st.html(html_block(f"""
<div class="nutri-card">
    <div class="nutri-label">🔥 Calorias ativas</div>
    <div class="nutri-val">{int(cal_ativas_hoje)}<span class="nutri-unit"> kcal</span></div>
    <div class="nutri-meta">Queima do dia</div>
</div>
"""))
    with ac2:
        st.html(html_block(f"""
<div class="nutri-card">
    <div class="nutri-label">👟 Passos</div>
    <div class="nutri-val">{passos_hoje:,}<span class="nutri-unit"> passos</span></div>
    <div class="prot-bar-wrap">
        <div class="prot-bar-fill" style="width:{passos_pct*100:.1f}%;background:linear-gradient(90deg,#D4A84B,#E8C26A)"></div>
    </div>
    <div class="nutri-meta">Meta: {META_PASSOS:,} · {passos_pct*100:.0f}%</div>
</div>
"""))
    with ac3:
        st.html(html_block(f"""
<div class="nutri-card">
    <div class="nutri-label">⏱ Movimento</div>
    <div class="nutri-val">{mov_hoje}<span class="nutri-unit"> min</span></div>
    <div class="prot-bar-wrap">
        <div class="prot-bar-fill" style="width:{mov_pct*100:.1f}%;background:linear-gradient(90deg,#5FA04E,#7EC86E)"></div>
    </div>
    <div class="nutri-meta">Meta: {META_MOV} min · {mov_pct*100:.0f}%</div>
</div>
"""))

    # Upload Mi Fitness
    st.markdown("**Importar do Mi Fitness via OCR**")
    col_up_mif, col_clr_mif = st.columns([3, 1], gap="small")

    with col_up_mif:
        upload_mif = st.file_uploader(
            "Print do Mi Fitness",
            type=["png", "jpg", "jpeg", "webp"],
            label_visibility="collapsed",
            key="mifitness_uploader",
        )

    with col_clr_mif:
        if st.button("Limpar", key="clear_mif", use_container_width=True):
            st.session_state["mifitness_ocr"] = None
            st.rerun()

    if upload_mif is not None:
        col_prev, col_ocr_result = st.columns([1, 2], gap="medium")
        with col_prev:
            st.image(upload_mif, caption="Preview", use_container_width=True)

        with col_ocr_result:
            if st.button("✦ Extrair via OCR.space", use_container_width=True, key="btn_ocr"):
                try:
                    with st.spinner("OCR processando..."):
                        ocr_result = extrair_mifitness_ocr(upload_mif)
                    st.session_state["mifitness_ocr"] = ocr_result
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro no OCR: {e}")

            ocr = st.session_state.get("mifitness_ocr")
            if ocr:
                cal_ocr = ocr.get("calorias_ativas")
                pas_ocr = ocr.get("passos")
                mov_ocr = ocr.get("minutos_movimento")

                # Card de resultado
                cal_str = f'{int(cal_ocr)} kcal' if cal_ocr is not None else "—"
                pas_str = f'{pas_ocr:,} passos' if pas_ocr is not None else "—"
                mov_str = f'{mov_ocr} min' if mov_ocr is not None else "—"

                st.html(html_block(f"""
<div class="mifitness-card">
    <div class="mifitness-title">Mi Fitness — leitura OCR</div>
    <div class="mifitness-sub">Extraído de {upload_mif.name}</div>
    <div class="mifitness-grid">
        <div class="mifitness-metric">
            <div class="mifitness-metric-icon">🔥</div>
            <div class="mifitness-metric-label">Calorias</div>
            <div class="mifitness-metric-val">{int(cal_ocr) if cal_ocr else '—'}<span class="mifitness-metric-unit"> kcal</span></div>
        </div>
        <div class="mifitness-metric">
            <div class="mifitness-metric-icon">👟</div>
            <div class="mifitness-metric-label">Passos</div>
            <div class="mifitness-metric-val">{f"{pas_ocr:,}" if pas_ocr else '—'}<span class="mifitness-metric-unit"> passos</span></div>
        </div>
        <div class="mifitness-metric">
            <div class="mifitness-metric-icon">⏱</div>
            <div class="mifitness-metric-label">Movimento</div>
            <div class="mifitness-metric-val">{mov_ocr if mov_ocr else '—'}<span class="mifitness-metric-unit"> min</span></div>
        </div>
    </div>
    <div class="ocr-badge"><span class="ocr-dot"></span> OCR.space Engine 2</div>
</div>
"""))

                # Formulário de confirmação e salvar
                with st.form("form_salvar_atividade"):
                    fs1, fs2, fs3 = st.columns(3)
                    with fs1:
                        data_ativ = st.date_input("Data", value=date.today(), key="data_ativ")
                    with fs2:
                        cal_conf = st.number_input(
                            "Calorias ativas (kcal)",
                            value=float(cal_ocr or 0), step=1.0, key="cal_conf",
                        )
                        pas_conf = st.number_input(
                            "Passos",
                            value=float(pas_ocr or 0), step=1.0, key="pas_conf",
                        )
                    with fs3:
                        mov_conf = st.number_input(
                            "Movimento (min)",
                            value=float(mov_ocr or 0), step=1.0, key="mov_conf",
                        )

                    submitted_ativ = st.form_submit_button(
                        "Salvar atividade no Turso", use_container_width=True
                    )

                if submitted_ativ:
                    try:
                        save_atividade_log(
                            data_log=str(data_ativ),
                            calorias_ativas=float(cal_conf),
                            passos=int(pas_conf),
                            minutos_movimento=int(mov_conf),
                            origem="ocr_mifitness",
                        )
                        st.success("Atividade salva no Turso!")
                        st.session_state["mifitness_ocr"] = None
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao salvar: {e}")

    # Histórico de atividade
    if not df_ativ.empty and len(df_ativ) >= 2:
        st.markdown("---")
        df_ativ_chart = df_ativ.sort_values("data_log").tail(14).copy()
        x_ativ = df_ativ_chart["data_log"].dt.strftime("%d/%m").tolist()

        fig_ativ = go.Figure()
        fig_ativ.add_trace(go.Bar(
            x=x_ativ, y=df_ativ_chart["passos"].tolist(),
            name="Passos", marker_color="#D4A84B",
            yaxis="y",
        ))
        fig_ativ.add_trace(go.Scatter(
            x=x_ativ,
            y=[META_PASSOS] * len(df_ativ_chart),
            mode="lines", name=f"Meta passos ({META_PASSOS:,})",
            line=dict(color="#B07D3A", dash="dash", width=2),
            yaxis="y",
        ))
        fig_ativ.add_trace(go.Scatter(
            x=x_ativ, y=df_ativ_chart["calorias_ativas"].tolist(),
            mode="lines+markers", name="Cal. ativas",
            line=dict(color="#D45F50", width=2),
            marker=dict(size=6), yaxis="y2",
        ))
        fig_ativ.update_layout(
            title="Atividade física — últimos 14 dias",
            height=300,
            paper_bgcolor="#FDFAF5", plot_bgcolor="#FDFAF5",
            margin=dict(l=10, r=10, t=50, b=10),
            legend=dict(orientation="h", y=1.12),
            font=dict(color="#2C2A26"),
            bargap=0.35,
            yaxis=dict(title="Passos", color="#D4A84B", showgrid=True, gridcolor="#EEE9DF"),
            yaxis2=dict(title="Kcal", overlaying="y", side="right", color="#D45F50", showgrid=False),
        )
        fig_ativ.update_xaxes(showgrid=False, color="#9A9590")
        st.plotly_chart(fig_ativ, use_container_width=True, config={"displayModeBar": False})

    st.markdown("---")

    # ── Formulário ─────────────────────────────────────────────────────────────
    st.markdown("### Registrar dia")

    with st.form("form_nutricao"):
        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            data_log = st.date_input("Data", value=date.today())
            proteina_g = st.number_input(
                "Proteína total (g)", min_value=0, max_value=600,
                value=int(prot_hoje) if prot_hoje else 0, step=5,
                help=f"Meta: {META_PROT_G} g  (2 g × kg corporal)",
            )
        with fc2:
            calorias_kcal = st.number_input(
                "Calorias (kcal)", min_value=0, max_value=6000,
                value=int(cal_hoje) if cal_hoje else 0, step=50,
            )
            whey_doses = st.number_input(
                "Doses de whey", min_value=0, max_value=10,
                value=whey_hoje, step=1,
                help="Cada dose ≈ 25 g de proteína",
            )
        with fc3:
            tipo_treino = st.selectbox(
                "Tipo de treino",
                options=["Musculação", "Cardio", "HIIT", "Descanso", "Outro"],
                index=0,
            )
            hora_treino = st.text_input("Horário treino", value="20:00")

        notas_nutri = st.text_area(
            "Notas do dia (opcional)", height=68,
            placeholder="Ex: treino pesado, comi mal, dormiu pouco...",
        )
        submitted_nutri = st.form_submit_button("Salvar registro", use_container_width=True)

    if submitted_nutri:
        try:
            save_nutri_log(
                data_log=str(data_log),
                proteina_g=float(proteina_g),
                calorias_kcal=float(calorias_kcal),
                whey_doses=int(whey_doses),
                tipo_treino=tipo_treino,
                hora_treino=hora_treino,
                notas=notas_nutri,
            )
            st.success("Registro salvo!")
            st.rerun()
        except Exception as e:
            st.error(f"Erro ao salvar: {e}")

    st.markdown("---")

    # ── Histórico + chart ──────────────────────────────────────────────────────
    if not df_nutri.empty:
        st.markdown("### Histórico recente")

        rows_html_nutri = ""
        for _, row in df_nutri.head(10).iterrows():
            dt   = row["data_log"].strftime("%d/%m") if pd.notna(row["data_log"]) else "—"
            prot = f'{int(row["proteina_g"] or 0)} g'     if pd.notna(row["proteina_g"])    else "—"
            cal  = f'{int(row["calorias_kcal"] or 0)} kcal' if pd.notna(row["calorias_kcal"]) else "—"
            wh   = f'{int(row["whey_doses"] or 0)}× whey'  if pd.notna(row["whey_doses"])    else ""
            tp   = str(row["tipo_treino"] or "—")
            chip = treino_chip_html(tp) if tp not in ["—", ""] else ""
            rows_html_nutri += f"""
<div class="log-row">
    <span class="log-date">{dt}</span>
    <span class="log-prot">{prot}</span>
    <span class="log-cal">{cal}</span>
    <span>{chip}</span>
    <span class="log-whey">{wh}</span>
</div>"""

        st.html(html_block(f"""
<div class="nutri-card" style="margin-bottom:20px">
    <div class="nutri-label" style="margin-bottom:12px">Últimos 10 registros</div>
    {rows_html_nutri}
</div>
"""))

        # Mini-chart proteína diária
        if len(df_nutri) >= 2:
            df_chart = df_nutri.sort_values("data_log").tail(14).copy()
            x_labels = df_chart["data_log"].dt.strftime("%d/%m").tolist()

            fig_prot = go.Figure()
            fig_prot.add_trace(go.Bar(
                x=x_labels,
                y=df_chart["proteina_g"].tolist(),
                marker_color="#4AADA0",
                name="Proteína",
                text=[f"{int(v)}g" if pd.notna(v) else "" for v in df_chart["proteina_g"]],
                textposition="outside",
            ))
            fig_prot.add_trace(go.Scatter(
                x=x_labels,
                y=[META_PROT_G] * len(df_chart),
                mode="lines",
                name=f"Meta ({META_PROT_G} g)",
                line=dict(color="#B07D3A", dash="dash", width=2),
            ))
            fig_prot.update_layout(
                title="Proteína diária (g) — últimos 14 dias",
                height=300,
                paper_bgcolor="#FDFAF5", plot_bgcolor="#FDFAF5",
                margin=dict(l=10, r=10, t=50, b=10),
                legend=dict(orientation="h", y=1.12),
                font=dict(color="#2C2A26"),
                bargap=0.35,
            )
            fig_prot.update_xaxes(showgrid=False, color="#9A9590")
            fig_prot.update_yaxes(showgrid=True, gridcolor="#EEE9DF", color="#9A9590")
            st.plotly_chart(fig_prot, use_container_width=True, config={"displayModeBar": False})

    else:
        st.info("Nenhum registro de nutrição ainda. Use o formulário acima para começar.")


# ═════════════════════════════════════════════════════════════════════════════
# TAB 3 — GRÁFICOS
# ═════════════════════════════════════════════════════════════════════════════
with tab_graficos:

    # Paleta e config base reutilizável
    BG     = "#FDFAF5"
    GRID   = "#EEE9DF"
    MUTED  = "#9A9590"
    TEXT   = "#2C2A26"
    TEAL   = "#4AADA0"
    CORAL  = "#D45F50"
    SAGE   = "#5FA04E"
    HONEY  = "#D4A84B"
    BLUE   = "#5BA8C4"
    BROWN  = "#C4A882"
    VIOLET = "#9B72CF"

    NO_ZOOM = {
        "displayModeBar": False,
        "scrollZoom": False,
        "doubleClick": False,
        "showTips": False,
    }

    def base_layout(title="", height=320, show_legend=True):
        return dict(
            title=dict(text=title, x=0.01, xanchor="left", font=dict(size=20, color=TEXT, family="DM Serif Display")),
            height=height,
            paper_bgcolor=BG, plot_bgcolor=BG,
            margin=dict(l=10, r=10, t=title and 52 or 20, b=10),
            font=dict(color=TEXT, family="DM Sans"),
            showlegend=show_legend,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1.0, font=dict(size=12)),
            hovermode="x unified",
            dragmode=False,
        )

    def base_xaxis():
        return dict(showgrid=False, tickformat="%d/%m", color=MUTED, zeroline=False, fixedrange=True)

    def base_yaxis(**kwargs):
        defaults = dict(showgrid=True, gridcolor=GRID, color=MUTED, zeroline=False, fixedrange=True)
        defaults.update(kwargs)
        return defaults

    # ── Dados disponíveis ──────────────────────────────────────────────────────
    df_graf = df_db.copy() if not df_db.empty else historico.copy()
    # garante que historico tem colunas extras se vier do mock
    for col in ["agua", "visceral", "proteina", "massa_ossea", "imc", "basal", "score"]:
        if col not in df_graf.columns:
            df_graf[col] = None

    df_graf = df_graf.sort_values("data_medicao")
    df_ativ_g = load_atividade_df().sort_values("data_log") if True else pd.DataFrame()
    df_nutri_g = load_nutri_df().sort_values("data_log") if True else pd.DataFrame()

    x_comp = df_graf["data_medicao"]
    x_ativ = df_ativ_g["data_log"] if not df_ativ_g.empty else pd.Series([], dtype="datetime64[ns]")
    x_nutr = df_nutri_g["data_log"] if not df_nutri_g.empty else pd.Series([], dtype="datetime64[ns]")

    tem_comp   = not df_graf.empty
    tem_ativ   = not df_ativ_g.empty
    tem_nutri  = not df_nutri_g.empty

    # ─────────────────────────────────────────────────────────────────────────
    # LINHA 1 — Peso | Gordura + Músculo
    # ─────────────────────────────────────────────────────────────────────────
    g1, g2 = st.columns(2, gap="medium")

    # G1 — Peso
    with g1:
        fig = go.Figure()
        if tem_comp:
            fig.add_trace(go.Scatter(
                x=x_comp, y=df_graf["peso"],
                name="Peso", mode="lines+markers",
                line=dict(color=TEAL, width=3, shape="spline", smoothing=1.2),
                marker=dict(size=6, color=TEAL, line=dict(width=2, color=BG)),
                fill="tozeroy", fillcolor="rgba(74,173,160,.08)",
            ))
            fig.add_trace(go.Scatter(
                x=x_comp, y=[DATA_ATUAL["meta_peso"]] * len(x_comp),
                name="Meta", mode="lines",
                line=dict(color=HONEY, width=2, dash="dash"), opacity=.8,
            ))
            if datas_proj_peso:
                fig.add_trace(go.Scatter(
                    x=datas_proj_peso, y=vals_proj_peso,
                    name="Projeção", mode="lines",
                    line=dict(color=TEAL, width=2, dash="dot"), opacity=.45,
                ))
        fig.update_layout(**base_layout("Peso corporal", 300))
        fig.update_xaxes(**base_xaxis())
        fig.update_yaxes(**base_yaxis(title_text="kg"))

        delta_str = f"+{fmt_num(delta_peso_total,1)}" if delta_peso_total > 0 else fmt_num(delta_peso_total,1)
        st.html(html_block(f"""
<div class="chart-wrap">
  <div class="chart-header">
    <span class="chart-title">⚖️ Peso</span>
    <span class="chart-sub">{fmt_num(DATA_ATUAL['peso'],1)} kg</span>
  </div>
"""))
        st.plotly_chart(fig, use_container_width=True, config=NO_ZOOM)
        st.html(html_block(f"""
  <div class="stat-row">
    <span class="stat-pill">Δ total <strong>{delta_str} kg</strong></span>
    <span class="stat-pill">Meta <strong>{fmt_num(DATA_ATUAL['meta_peso'],0)} kg</strong></span>
    <span class="stat-pill">Faltam <strong>+{fmt_num(DATA_ATUAL['meta_peso']-DATA_ATUAL['peso'],1)} kg</strong></span>
  </div>
</div>
"""))

    # G2 — Gordura + Músculo eixo duplo
    with g2:
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        if tem_comp:
            fig.add_trace(go.Scatter(
                x=x_comp, y=df_graf["gordura"],
                name="Gordura %", mode="lines+markers",
                line=dict(color=CORAL, width=3, shape="spline", smoothing=1.2),
                marker=dict(size=6, color=CORAL, line=dict(width=2, color=BG)),
                fill="tozeroy", fillcolor="rgba(212,95,80,.07)",
            ), secondary_y=False)
            fig.add_trace(go.Scatter(
                x=x_comp, y=[DATA_ATUAL["meta_gordura"]] * len(x_comp),
                name="Meta gord.", mode="lines",
                line=dict(color=HONEY, width=2, dash="dash"), opacity=.8,
            ), secondary_y=False)
            fig.add_trace(go.Scatter(
                x=x_comp, y=df_graf["musculo"],
                name="Músculo kg", mode="lines+markers",
                line=dict(color=SAGE, width=3, shape="spline", smoothing=1.2),
                marker=dict(size=6, color=SAGE, line=dict(width=2, color=BG)),
            ), secondary_y=True)
        fig.update_layout(**base_layout("Gordura & Músculo", 300))
        fig.update_xaxes(**base_xaxis())
        fig.update_yaxes(**base_yaxis(title_text="Gordura (%)"), secondary_y=False)
        fig.update_yaxes(**base_yaxis(title_text="Músculo (kg)", showgrid=False), secondary_y=True)

        delta_g = f"{fmt_num(delta_gordura,1)} pp"
        delta_m = f"+{fmt_num(delta_musculo,1)} kg" if delta_musculo > 0 else f"{fmt_num(delta_musculo,1)} kg"
        st.html(html_block(f"""
<div class="chart-wrap">
  <div class="chart-header">
    <span class="chart-title">🔬 Composição</span>
    <span class="chart-sub">{fmt_num(DATA_ATUAL['gordura'],1)}% gord · {fmt_num(DATA_ATUAL['musculo'],1)} kg musc</span>
  </div>
"""))
        st.plotly_chart(fig, use_container_width=True, config=NO_ZOOM)
        st.html(html_block(f"""
  <div class="stat-row">
    <span class="stat-pill">Δ gordura <strong>{delta_g}</strong></span>
    <span class="stat-pill">Δ músculo <strong>{delta_m}</strong></span>
    <span class="stat-pill">Meta <strong>{fmt_num(DATA_ATUAL['meta_gordura'],0)}%</strong></span>
  </div>
</div>
"""))

    # ─────────────────────────────────────────────────────────────────────────
    # LINHA 2 — Água & Visceral | Proteína & IMC
    # ─────────────────────────────────────────────────────────────────────────
    g3, g4 = st.columns(2, gap="medium")

    with g3:
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        if tem_comp and "agua" in df_graf.columns:
            agua_vals = pd.to_numeric(df_graf["agua"], errors="coerce")
            visc_vals = pd.to_numeric(df_graf["visceral"], errors="coerce")
            fig.add_trace(go.Scatter(
                x=x_comp, y=agua_vals,
                name="Água %", mode="lines+markers",
                line=dict(color=BLUE, width=3, shape="spline", smoothing=1.2),
                marker=dict(size=6, color=BLUE, line=dict(width=2, color=BG)),
                fill="tozeroy", fillcolor="rgba(91,168,196,.09)",
            ), secondary_y=False)
            fig.add_trace(go.Scatter(
                x=x_comp, y=visc_vals,
                name="Visceral", mode="lines+markers",
                line=dict(color=CORAL, width=2.5, shape="spline", smoothing=1.2),
                marker=dict(size=5, color=CORAL),
            ), secondary_y=True)
        fig.update_layout(**base_layout("Hidratação & Visceral", 280))
        fig.update_xaxes(**base_xaxis())
        fig.update_yaxes(**base_yaxis(title_text="Água (%)"), secondary_y=False)
        fig.update_yaxes(**base_yaxis(title_text="Visceral", showgrid=False), secondary_y=True)

        agua_v  = fmt_num(DATA_ATUAL["agua"],1) if DATA_ATUAL["agua"] else "—"
        visc_v  = fmt_num(DATA_ATUAL["visceral"],0) if DATA_ATUAL["visceral"] else "—"
        st.html(html_block(f"""
<div class="chart-wrap">
  <div class="chart-header">
    <span class="chart-title">💧 Hidratação</span>
    <span class="chart-sub">Água {agua_v}% · Visceral {visc_v}</span>
  </div>
"""))
        st.plotly_chart(fig, use_container_width=True, config=NO_ZOOM)
        st.html(html_block(f"""
  <div class="stat-row">
    <span class="stat-pill">Água ideal <strong>≥ 52%</strong></span>
    <span class="stat-pill">Visceral ideal <strong>≤ 12</strong></span>
  </div>
</div>
"""))

    with g4:
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        if tem_comp and "proteina" in df_graf.columns:
            prot_vals = pd.to_numeric(df_graf["proteina"], errors="coerce")
            imc_vals  = pd.to_numeric(df_graf["imc"],      errors="coerce")
            fig.add_trace(go.Scatter(
                x=x_comp, y=prot_vals,
                name="Proteína %", mode="lines+markers",
                line=dict(color=BROWN, width=3, shape="spline", smoothing=1.2),
                marker=dict(size=6, color=BROWN, line=dict(width=2, color=BG)),
                fill="tozeroy", fillcolor="rgba(196,168,130,.09)",
            ), secondary_y=False)
            fig.add_trace(go.Scatter(
                x=x_comp, y=imc_vals,
                name="IMC", mode="lines+markers",
                line=dict(color=VIOLET, width=2.5, shape="spline", smoothing=1.2),
                marker=dict(size=5, color=VIOLET),
            ), secondary_y=True)
        fig.update_layout(**base_layout("Proteína corporal & IMC", 280))
        fig.update_xaxes(**base_xaxis())
        fig.update_yaxes(**base_yaxis(title_text="Proteína (%)"), secondary_y=False)
        fig.update_yaxes(**base_yaxis(title_text="IMC", showgrid=False), secondary_y=True)

        prot_v = fmt_num(DATA_ATUAL["proteina"],1) if DATA_ATUAL["proteina"] else "—"
        imc_v  = fmt_num(DATA_ATUAL["imc"],1)      if DATA_ATUAL["imc"]      else "—"
        st.html(html_block(f"""
<div class="chart-wrap">
  <div class="chart-header">
    <span class="chart-title">🧬 Proteína & IMC</span>
    <span class="chart-sub">Proteína {prot_v}% · IMC {imc_v}</span>
  </div>
"""))
        st.plotly_chart(fig, use_container_width=True, config=NO_ZOOM)
        st.html(html_block(f"""
  <div class="stat-row">
    <span class="stat-pill">Proteína ideal <strong>≥ 18%</strong></span>
    <span class="stat-pill">IMC atual <strong>{imc_v}</strong></span>
  </div>
</div>
"""))

    # ─────────────────────────────────────────────────────────────────────────
    # LINHA 3 — Score Recomposição | Metabolismo basal
    # ─────────────────────────────────────────────────────────────────────────
    g5, g6 = st.columns(2, gap="medium")

    with g5:
        fig = go.Figure()
        if tem_comp and "score" in df_graf.columns:
            score_vals = pd.to_numeric(df_graf["score"], errors="coerce").dropna()
            score_x    = df_graf.loc[score_vals.index, "data_medicao"]
            if not score_vals.empty:
                fig.add_trace(go.Scatter(
                    x=score_x, y=score_vals,
                    name="Score", mode="lines+markers",
                    line=dict(color=HONEY, width=3, shape="spline", smoothing=1.2),
                    marker=dict(size=7, color=HONEY, line=dict(width=2, color=BG)),
                    fill="tozeroy", fillcolor="rgba(212,168,75,.10)",
                ))
                # banda de referência 60-80
                fig.add_hrect(y0=60, y1=80, fillcolor="rgba(95,160,78,.08)",
                              line_width=0, annotation_text="Ótimo",
                              annotation_position="top right",
                              annotation_font=dict(color=SAGE, size=11))
        fig.update_layout(**base_layout("Score de recomposição", 280))
        fig.update_xaxes(**base_xaxis())
        fig.update_yaxes(**base_yaxis(range=[0, 100], title_text="Score (0-100)"))

        score_v = int(round(DATA_ATUAL["score"])) if DATA_ATUAL["score"] else "—"
        st.html(html_block(f"""
<div class="chart-wrap">
  <div class="chart-header">
    <span class="chart-title">🏆 Score Recomp.</span>
    <span class="chart-sub">Atual: {score_v} / 100</span>
  </div>
"""))
        st.plotly_chart(fig, use_container_width=True, config=NO_ZOOM)
        st.html(html_block(f"""
  <div class="stat-row">
    <span class="stat-pill">Zona ideal <strong>60–80</strong></span>
    <span class="stat-pill">Componentes: gordura · visceral · músculo</span>
  </div>
</div>
"""))

    with g6:
        fig = go.Figure()
        if tem_comp and "basal" in df_graf.columns:
            basal_vals = pd.to_numeric(df_graf["basal"], errors="coerce").dropna()
            basal_x    = df_graf.loc[basal_vals.index, "data_medicao"]
            if not basal_vals.empty:
                fig.add_trace(go.Scatter(
                    x=basal_x, y=basal_vals,
                    name="TMB", mode="lines+markers",
                    line=dict(color=VIOLET, width=3, shape="spline", smoothing=1.2),
                    marker=dict(size=6, color=VIOLET, line=dict(width=2, color=BG)),
                    fill="tozeroy", fillcolor="rgba(155,114,207,.09)",
                ))
        fig.update_layout(**base_layout("Metabolismo basal (TMB)", 280))
        fig.update_xaxes(**base_xaxis())
        fig.update_yaxes(**base_yaxis(title_text="kcal/dia"))

        basal_v = int(DATA_ATUAL["basal"]) if DATA_ATUAL["basal"] else "—"
        st.html(html_block(f"""
<div class="chart-wrap">
  <div class="chart-header">
    <span class="chart-title">🔋 Metabolismo basal</span>
    <span class="chart-sub">{basal_v} kcal/dia</span>
  </div>
"""))
        st.plotly_chart(fig, use_container_width=True, config=NO_ZOOM)
        st.html(html_block(f"""
  <div class="stat-row">
    <span class="stat-pill">Sobe com músculo, cai com gordura</span>
  </div>
</div>
"""))

    # ─────────────────────────────────────────────────────────────────────────
    # LINHA 4 — Calorias ativas | Passos diários
    # ─────────────────────────────────────────────────────────────────────────
    if tem_ativ:
        g7, g8 = st.columns(2, gap="medium")

        with g7:
            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=df_ativ_g["data_log"],
                y=df_ativ_g["calorias_ativas"],
                name="Cal. ativas",
                marker=dict(
                    color=df_ativ_g["calorias_ativas"],
                    colorscale=[[0, "rgba(212,95,80,.4)"], [1, CORAL]],
                    showscale=False,
                    line=dict(width=0),
                ),
            ))
            fig.update_layout(**base_layout("Calorias ativas diárias", 280, show_legend=False))
            fig.update_xaxes(**base_xaxis())
            fig.update_yaxes(**base_yaxis(title_text="kcal"))
            fig.update_traces(marker_cornerradius=4)

            cal_media = df_ativ_g["calorias_ativas"].mean()
            cal_max   = df_ativ_g["calorias_ativas"].max()
            st.html(html_block(f"""
<div class="chart-wrap">
  <div class="chart-header">
    <span class="chart-title">🔥 Calorias ativas</span>
    <span class="chart-sub">Hoje: {int(cal_ativas_hoje)} kcal</span>
  </div>
"""))
            st.plotly_chart(fig, use_container_width=True, config=NO_ZOOM)
            st.html(html_block(f"""
  <div class="stat-row">
    <span class="stat-pill">Média <strong>{int(cal_media)} kcal</strong></span>
    <span class="stat-pill">Máx <strong>{int(cal_max)} kcal</strong></span>
  </div>
</div>
"""))

        with g8:
            fig = go.Figure()
            cores_passos = [
                SAGE if (v or 0) >= 8000 else HONEY if (v or 0) >= 5000 else CORAL
                for v in df_ativ_g["passos"]
            ]
            fig.add_trace(go.Bar(
                x=df_ativ_g["data_log"],
                y=df_ativ_g["passos"],
                name="Passos",
                marker=dict(color=cores_passos, line=dict(width=0)),
            ))
            fig.add_trace(go.Scatter(
                x=df_ativ_g["data_log"],
                y=[8000] * len(df_ativ_g),
                name="Meta 8.000", mode="lines",
                line=dict(color=HONEY, dash="dash", width=2), opacity=.8,
            ))
            fig.update_layout(**base_layout("Passos diários", 280))
            fig.update_xaxes(**base_xaxis())
            fig.update_yaxes(**base_yaxis(title_text="passos"))
            fig.update_traces(marker_cornerradius=4, selector=dict(type="bar"))

            media_passos = df_ativ_g["passos"].mean()
            dias_meta    = (df_ativ_g["passos"] >= 8000).sum()
            st.html(html_block(f"""
<div class="chart-wrap">
  <div class="chart-header">
    <span class="chart-title">👟 Passos diários</span>
    <span class="chart-sub">Hoje: {passos_hoje:,}</span>
  </div>
"""))
            st.plotly_chart(fig, use_container_width=True, config=NO_ZOOM)
            st.html(html_block(f"""
  <div class="stat-row">
    <span class="stat-pill">Média <strong>{int(media_passos):,}</strong></span>
    <span class="stat-pill">Dias acima da meta <strong>{dias_meta}</strong></span>
  </div>
</div>
"""))

    # ─────────────────────────────────────────────────────────────────────────
    # LINHA 5 — Proteína ingerida | Calorias nutrição (full width)
    # ─────────────────────────────────────────────────────────────────────────
    if tem_nutri:
        META_PROT_G2 = round(DATA_ATUAL["peso"] * 2)

        fig_np = go.Figure()
        fig_np.add_trace(go.Bar(
            x=df_nutri_g["data_log"],
            y=df_nutri_g["proteina_g"],
            name="Proteína",
            marker=dict(
                color=df_nutri_g["proteina_g"],
                colorscale=[[0, "rgba(74,173,160,.35)"], [1, TEAL]],
                showscale=False, line=dict(width=0),
            ),
        ))
        fig_np.add_trace(go.Scatter(
            x=df_nutri_g["data_log"],
            y=[META_PROT_G2] * len(df_nutri_g),
            name=f"Meta {META_PROT_G2} g", mode="lines",
            line=dict(color=HONEY, dash="dash", width=2), opacity=.8,
        ))
        fig_np.add_trace(go.Scatter(
            x=df_nutri_g["data_log"],
            y=df_nutri_g["calorias_kcal"],
            name="Calorias (kcal)", mode="lines+markers",
            line=dict(color=CORAL, width=2.5),
            marker=dict(size=5, color=CORAL),
            yaxis="y2",
        ))
        fig_np.update_layout(
            **base_layout("Proteína ingerida & Calorias nutricionais", 320),
            yaxis=dict(title_text="Proteína (g)", color=TEAL, showgrid=True,
                       gridcolor=GRID, fixedrange=True),
            yaxis2=dict(title_text="Calorias (kcal)", overlaying="y", side="right",
                        color=CORAL, showgrid=False, fixedrange=True),
        )
        fig_np.update_xaxes(**base_xaxis())
        fig_np.update_traces(marker_cornerradius=4, selector=dict(type="bar"))

        prot_media = df_nutri_g["proteina_g"].mean()
        cal_media_n = df_nutri_g["calorias_kcal"].mean()
        dias_ok_prot = (df_nutri_g["proteina_g"] >= META_PROT_G2).sum()

        st.html(html_block(f"""
<div class="chart-wrap">
  <div class="chart-header">
    <span class="chart-title">🥩 Nutrição — Proteína & Calorias</span>
    <span class="chart-sub">Meta {META_PROT_G2} g/dia</span>
  </div>
"""))
        st.plotly_chart(fig_np, use_container_width=True, config=NO_ZOOM)
        st.html(html_block(f"""
  <div class="stat-row">
    <span class="stat-pill">Média proteína <strong>{int(prot_media)} g</strong></span>
    <span class="stat-pill">Média calorias <strong>{int(cal_media_n)} kcal</strong></span>
    <span class="stat-pill">Dias na meta <strong>{dias_ok_prot}</strong></span>
  </div>
</div>
"""))

    # ─────────────────────────────────────────────────────────────────────────
    # LINHA 6 — Movimento (min) — full width
    # ─────────────────────────────────────────────────────────────────────────
    if tem_ativ and not df_ativ_g["minutos_movimento"].isna().all():
        fig_mov = go.Figure()
        fig_mov.add_trace(go.Scatter(
            x=df_ativ_g["data_log"],
            y=df_ativ_g["minutos_movimento"],
            name="Movimento", mode="lines+markers",
            line=dict(color=SAGE, width=3, shape="spline", smoothing=1.2),
            marker=dict(size=7, color=SAGE, line=dict(width=2, color=BG)),
            fill="tozeroy", fillcolor="rgba(95,160,78,.10)",
        ))
        fig_mov.add_trace(go.Scatter(
            x=df_ativ_g["data_log"],
            y=[30] * len(df_ativ_g),
            name="Meta 30 min", mode="lines",
            line=dict(color=HONEY, dash="dash", width=2), opacity=.8,
        ))
        fig_mov.update_layout(**base_layout("Minutos de movimento diário", 260))
        fig_mov.update_xaxes(**base_xaxis())
        fig_mov.update_yaxes(**base_yaxis(title_text="min"))

        media_mov = df_ativ_g["minutos_movimento"].mean()
        dias_ok_mov = (df_ativ_g["minutos_movimento"] >= 30).sum()

        st.html(html_block(f"""
<div class="chart-wrap">
  <div class="chart-header">
    <span class="chart-title">⏱ Minutos de movimento</span>
    <span class="chart-sub">Meta: 30 min/dia</span>
  </div>
"""))
        st.plotly_chart(fig_mov, use_container_width=True, config=NO_ZOOM)
        st.html(html_block(f"""
  <div class="stat-row">
    <span class="stat-pill">Média <strong>{int(media_mov)} min</strong></span>
    <span class="stat-pill">Dias na meta <strong>{dias_ok_mov}</strong></span>
  </div>
</div>
"""))

    # Fallback quando não há dados de atividade/nutrição
    if not tem_ativ and not tem_nutri:
        st.info("Registre atividade no Mi Fitness e nutrição na aba Nutrição & Treino para ver os gráficos completos.")

