from textwrap import dedent

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


def html_block(content: str) -> str:
    return dedent(content).strip()


def fmt_num(valor: float, casas: int = 1) -> str:
    return f"{valor:.{casas}f}".replace(".", ",")


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


DATA_ATUAL = {
    "peso": 91.6,
    "gordura": 29.2,
    "musculo": 61.5,
    "agua": 50.5,
    "visceral": 13,
    "proteina": 16.6,
    "score": 49,
    "delta_peso_total": -1.4,
    "dias_periodo": 108,
    "gordura_inicial": 30.1,
    "peso_inicial": 93.0,
    "musculo_inicial": 60.2,
    "meta_peso": 96.0,
    "meta_gordura": 20.0,
    "peso_min": 80.0,
    "agua_status": "Insuf.",
    "gordura_status": "Alta",
    "musculo_status": "Boa",
    "visceral_status": "Alta",
    "proteina_status": "Normal",
    "peso_status": "Em queda",
    "massa_ossea": 3.31,
}

historico = pd.DataFrame(
    {
        "data": pd.to_datetime(
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

historico_lista = [
    ("18 Dez", "93,0 kg", "início", "up"),
    ("28 Dez", "92,4 kg", "↓ 0,6", "down"),
    ("10 Jan", "92,1 kg", "↓ 0,3", "down"),
    ("22 Jan", "91,8 kg", "↓ 0,3", "down"),
    ("05 Abr", "91,6 kg", "↓ 0,2", "down"),
]

peso_prog = progresso_peso(
    DATA_ATUAL["peso"], DATA_ATUAL["peso_min"], DATA_ATUAL["meta_peso"]
)
gordura_prog = progresso_gordura(
    DATA_ATUAL["gordura_inicial"],
    DATA_ATUAL["gordura"],
    DATA_ATUAL["meta_gordura"],
)

delta_gordura = DATA_ATUAL["gordura"] - DATA_ATUAL["gordura_inicial"]
delta_musculo = DATA_ATUAL["musculo"] - DATA_ATUAL["musculo_inicial"]
ritmo_peso_sem = DATA_ATUAL["delta_peso_total"] / (DATA_ATUAL["dias_periodo"] / 7)
ritmo_gordura_sem = delta_gordura / (DATA_ATUAL["dias_periodo"] / 7)
faltam_gordura_pp = DATA_ATUAL["gordura"] - DATA_ATUAL["meta_gordura"]
semanas_para_meta = abs(faltam_gordura_pp / ritmo_gordura_sem) if ritmo_gordura_sem < 0 else None
ritmo_necessario_1_ano = faltam_gordura_pp / 52 if faltam_gordura_pp > 0 else 0
mes_abrev = "ABR 2026"

st.markdown(
    html_block("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Sans:wght@300;400;500;700&display=swap');

:root{
  --bg:#F5F2EC;
  --card:#FDFAF5;
  --teal:#4AADA0;
  --coral:#D45F50;
  --sage:#5FA04E;
  --honey:#D4A84B;
  --text:#2C2A26;
  --muted:#9A9590;
  --border:#E8E3D8;
  --goal:#B07D3A;
  --blue:#5BA8C4;
  --brown:#C4A882;
  --radius:18px;
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

.banner { background: linear-gradient(135deg, #2C2A26 0%, #3D3A34 100%); border-radius:24px; padding:22px 24px; color:#F5F2EC; display:flex; align-items:center; justify-content:space-between; gap:16px; margin-bottom:18px; }
.banner-left { display:flex; gap:14px; align-items:flex-start; }
.banner-icon { font-size:1.8rem; line-height:1; }
.banner-title { font-family:'DM Serif Display', serif; font-size:1.85rem; margin-bottom:4px; }
.banner-sub { color: rgba(245,242,236,0.68); font-size:1rem; line-height:1.5; }
.banner-chip { background: var(--honey); color: var(--text); font-weight:700; border-radius:999px; padding:8px 14px; height:fit-content; text-transform:uppercase; font-size:.8rem; }

.card, .metric-card, .meta-card, .proj-card, .insight-card, .gauge-card, .donut-card, .history-card, .score-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
}

.score-card { background: linear-gradient(135deg, #2C2A26 0%, #252320 100%); color:white; padding:22px 18px; min-height:232px; position:relative; overflow:hidden; }
.score-card::before{ content:''; position:absolute; top:-34px; right:-34px; width:120px; height:120px; background: var(--coral); opacity:.14; border-radius:50%; }
.score-label { font-size:.95rem; text-transform:uppercase; letter-spacing:.10em; opacity:.65; }
.score-num { font-family:'DM Serif Display', serif; font-size:6rem; line-height:1; margin-top:12px; }
.score-delta { color:#65d0c2; font-size:1.6rem; font-weight:600; margin-top:12px; }

.metric-card { padding:18px 18px 20px 18px; position:relative; overflow:hidden; min-height:108px; }
.metric-card::after{ content:''; position:absolute; left:0; right:0; bottom:0; height:4px; }
.metric-teal::after{background:var(--teal);}
.metric-coral::after{background:var(--coral);}
.metric-sage::after{background:var(--sage);}
.metric-honey::after{background:var(--honey);}
.metric-blue::after{background:var(--blue);}
.metric-brown::after{background:var(--brown);}
.metric-name { color: var(--muted); text-transform: uppercase; font-size:.82rem; letter-spacing:.06em; font-weight:700; }
.metric-value { font-family:'DM Serif Display', serif; color:var(--text); font-size:2.8rem; line-height:1.1; margin-top:4px; }
.metric-unit { font-family:'DM Sans', sans-serif; font-size:1.1rem; color:var(--muted); font-weight:400; }
.tag { display:inline-block; margin-top:8px; padding:5px 10px; border-radius:999px; font-size:.86rem; font-weight:700; }
.tag-ok{ background:#E6F4EC; color:#4A9A5E; }
.tag-hi{ background:#FDECEA; color:#C0503F; }
.tag-mid{ background:#FFF8E8; color:#A07830; }

.meta-card{ padding:22px; min-height:270px; }
.meta-top { display:flex; justify-content:space-between; align-items:flex-start; gap:12px; margin-bottom:16px; }
.meta-label { color:var(--muted); text-transform:uppercase; letter-spacing:.06em; font-size:.82rem; font-weight:700; }
.meta-title { font-family:'DM Serif Display', serif; font-size:1.9rem; line-height:1.2; margin-top:4px; }
.meta-chip { padding:7px 12px; border-radius:999px; font-size:.9rem; font-weight:700; white-space:nowrap; }
.chip-peso{ background:#E0F4F2; color:#2A7A72; }
.chip-gordura{ background:#FDECEA; color:#A03828; }
.meta-progress-labels { display:flex; justify-content:space-between; color:var(--muted); font-size:.95rem; margin-bottom:8px; }
.meta-progress-labels strong{ color:var(--text); }
.track { width:100%; height:14px; background: var(--border); border-radius:999px; position:relative; overflow:visible; }
.fill { height:100%; border-radius:999px; position:relative; }
.fill-teal{ background: linear-gradient(90deg,#4AADA0,#6BCFC5); }
.fill-coral{ background: linear-gradient(90deg,#D45F50,#E08070); }
.marker{ position:absolute; top:50%; right:0; transform: translate(50%, -50%); width:20px; height:20px; border-radius:50%; border:3px solid white; }
.marker-teal{ background:var(--teal); }
.marker-coral{ background:var(--coral); }
.meta-nums { display:flex; justify-content:space-between; align-items:flex-end; margin-top:18px; }
.meta-small { color:var(--muted); text-transform:uppercase; letter-spacing:.05em; font-size:.8rem; font-weight:700; }
.meta-current, .meta-goal { font-family:'DM Serif Display', serif; font-size:3rem; line-height:1.1; }
.meta-goal { color: var(--goal); }
.meta-unit { font-family:'DM Sans', sans-serif; color:var(--muted); font-size:1rem; }
.meta-arrow { color:var(--muted); font-size:1.8rem; padding-bottom:10px; }
.meta-diff { margin-top:10px; color:var(--muted); font-size:1rem; }
.meta-diff strong{ color:var(--text); }

.proj-card, .insight-card, .gauge-card, .donut-card, .history-card { padding:22px; }
.section-title { font-family:'DM Serif Display', serif; font-size:2rem; margin-bottom:16px; }
.proj-item { display:flex; gap:12px; padding:12px 0; border-bottom:1px solid var(--border); }
.proj-item:last-child { border-bottom:none; }
.dot { width:10px; height:10px; border-radius:50%; margin-top:7px; flex-shrink:0; }
.dot-teal{background:var(--teal);}
.dot-coral{background:var(--coral);}
.dot-sage{background:var(--sage);}
.dot-honey{background:var(--honey);}
.proj-label { color:var(--muted); text-transform:uppercase; letter-spacing:.05em; font-size:.82rem; }
.proj-val { color:var(--text); font-size:1.15rem; margin-top:2px; }
.proj-val em { font-style:normal; font-weight:700; }

.insight-head { display:flex; justify-content:space-between; align-items:center; gap:12px; margin-bottom:8px; }
.powered { color:var(--muted); font-size:.9rem; display:flex; align-items:center; gap:6px; }
.ai-dot { width:8px; height:8px; border-radius:50%; background:var(--teal); }
.insight-body { color:var(--text); font-size:1.1rem; line-height:1.8; font-weight:300; }
.hi-green{ color:#4A9A5E; font-weight:700; }
.hi-red{ color:#C0503F; font-weight:700; }
.hi-gold{ color:#9A6A20; font-weight:700; }

.history-row { display:flex; justify-content:space-between; align-items:center; padding:12px 0; border-bottom:1px solid var(--border); }
.history-row:last-child { border-bottom:none; }
.history-date { color:var(--muted); font-size:.98rem; }
.history-peso { font-family:'DM Serif Display', serif; font-size:1.25rem; }
.delta-up { color:var(--coral); font-weight:700; }
.delta-down { color:var(--sage); font-weight:700; }

.chart-wrap { background: var(--card); border:1px solid var(--border); border-radius:var(--radius); padding:12px 14px 6px 14px; margin-top:14px; margin-bottom:14px; }
.fake-button { width:100%; background: var(--text); color:white; text-align:center; padding:12px 14px; border-radius:12px; font-weight:700; margin-top:16px; }

@media (max-width: 900px){
  .score-card { min-height: 180px; }
  .score-num { font-size: 4.6rem; }
  .metric-value { font-size: 2.1rem; }
  .meta-title { font-size: 1.5rem; }
  .meta-current, .meta-goal { font-size: 2.2rem; }
  .section-title { font-size: 1.6rem; }
}
</style>
"""),
    unsafe_allow_html=True,
)

st.markdown(
    html_block(f"""
<div class="top-header">
    <div>
        <div class="page-title">Corpo em <em>evolução</em></div>
        <div class="subtitle">Composição corporal · Zepp Life · Acompanhamento de metas</div>
    </div>
    <div class="date-badge">{mes_abrev}</div>
</div>
"""),
    unsafe_allow_html=True,
)

st.markdown(
    html_block(f"""
<div class="banner">
    <div class="banner-left">
        <div class="banner-icon">⚡</div>
        <div>
            <div class="banner-title">Recomposição corporal em andamento</div>
            <div class="banner-sub">
                Meta simultânea: ganhar +{fmt_num(DATA_ATUAL["meta_peso"] - DATA_ATUAL["peso"], 1)} kg
                e reduzir −{fmt_num(DATA_ATUAL["gordura"] - DATA_ATUAL["meta_gordura"], 1)} pp de gordura.
                Exige ganho muscular com déficit calórico preciso.
            </div>
        </div>
    </div>
    <div class="banner-chip">Avançado</div>
</div>
"""),
    unsafe_allow_html=True,
)

col_score, col_stats = st.columns([1.1, 4.2], gap="medium")

with col_score:
    st.markdown(
        html_block(f"""
<div class="score-card">
    <div class="score-label">Score</div>
    <div class="score-num">{DATA_ATUAL["score"]}</div>
    <div class="score-delta">↓ {fmt_num(abs(DATA_ATUAL["delta_peso_total"]), 2)} kg</div>
</div>
"""),
        unsafe_allow_html=True,
    )

with col_stats:
    r1c1, r1c2, r1c3 = st.columns(3, gap="small")
    r2c1, r2c2, r2c3 = st.columns(3, gap="small")

    cards = [
        (r1c1, "Peso", DATA_ATUAL["peso"], "kg", DATA_ATUAL["peso_status"], "metric-teal"),
        (r1c2, "Gordura", DATA_ATUAL["gordura"], "%", DATA_ATUAL["gordura_status"], "metric-coral"),
        (r1c3, "Músculo", DATA_ATUAL["musculo"], "kg", DATA_ATUAL["musculo_status"], "metric-sage"),
        (r2c1, "Água", DATA_ATUAL["agua"], "%", DATA_ATUAL["agua_status"], "metric-honey"),
        (r2c2, "Visceral", DATA_ATUAL["visceral"], "", DATA_ATUAL["visceral_status"], "metric-blue"),
        (r2c3, "Proteína", DATA_ATUAL["proteina"], "%", DATA_ATUAL["proteina_status"], "metric-brown"),
    ]

    for col, nome, valor, unidade, status, klass in cards:
        with col:
            valor_txt = fmt_num(valor, 1) if isinstance(valor, float) else str(valor)
            st.markdown(
                html_block(f"""
<div class="metric-card {klass}">
    <div class="metric-name">{nome}</div>
    <div class="metric-value">{valor_txt}<span class="metric-unit">{unidade}</span></div>
    <span class="tag {status_class(status)}">{status}</span>
</div>
"""),
                unsafe_allow_html=True,
            )

m1, m2 = st.columns(2, gap="medium")

with m1:
    st.info(f"Mín: {fmt_num(DATA_ATUAL['peso_min'],0)} kg | Meta: {fmt_num(DATA_ATUAL['meta_peso'],0)} kg")
    st.progress(peso_prog)
    st.markdown(
        html_block(f"""
<div class="meta-card">
    <div class="meta-top">
        <div>
            <div class="meta-label">Meta de peso</div>
            <div class="meta-title">Ganhar massa total</div>
        </div>
        <div class="meta-chip chip-peso">+{fmt_num(DATA_ATUAL["meta_peso"] - DATA_ATUAL["peso"], 1)} kg</div>
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
"""),
        unsafe_allow_html=True,
    )

with m2:
    st.info(f"Meta: {fmt_num(DATA_ATUAL['meta_gordura'],0)}% | Início: {fmt_num(DATA_ATUAL['gordura_inicial'],1)}%")
    st.progress(gordura_prog)
    st.markdown(
        html_block(f"""
<div class="meta-card">
    <div class="meta-top">
        <div>
            <div class="meta-label">Meta de gordura</div>
            <div class="meta-title">Reduzir % corporal</div>
        </div>
        <div class="meta-chip chip-gordura">−{fmt_num(DATA_ATUAL["gordura"] - DATA_ATUAL["meta_gordura"], 1)} pp</div>
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
"""),
        unsafe_allow_html=True,
    )

p1, p2 = st.columns(2, gap="medium")

with p1:
    semanas_txt = f"≈ {round(semanas_para_meta):,} semanas".replace(",", ".") if semanas_para_meta else "Sem projeção"
    st.markdown(
        html_block(f"""
<div class="proj-card">
    <div class="section-title">Ritmo atual & projeção</div>

    <div class="proj-item">
        <div class="dot dot-teal"></div>
        <div>
            <div class="proj-label">Variação peso ({DATA_ATUAL["dias_periodo"]} dias)</div>
            <div class="proj-val">{fmt_num(DATA_ATUAL["delta_peso_total"], 1)} kg · <em>{fmt_num(ritmo_peso_sem, 2)} kg/semana</em></div>
        </div>
    </div>

    <div class="proj-item">
        <div class="dot dot-coral"></div>
        <div>
            <div class="proj-label">Variação gordura ({DATA_ATUAL["dias_periodo"]} dias)</div>
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
"""),
        unsafe_allow_html=True,
    )

with p2:
    st.markdown(
        html_block(f"""
<div class="insight-card">
    <div class="insight-head">
        <div class="section-title" style="margin-bottom:0">Análise do período</div>
        <div class="powered"><span class="ai-dot"></span> Claude</div>
    </div>
    <div class="insight-body">
        Em {DATA_ATUAL["dias_periodo"]} dias, você perdeu
        <span class="hi-green">{fmt_num(abs(DATA_ATUAL["delta_peso_total"]), 1)} kg</span> e reduziu gordura em
        <span class="hi-green">{fmt_num(abs(delta_gordura), 1)} pp</span>.
        Músculo subiu <span class="hi-green">+{fmt_num(delta_musculo, 1)} kg</span> — recomposição real acontecendo.
        <br><br>
        <span class="hi-red">Ritmo de gordura está lento</span>: no ritmo atual, a meta ainda está distante.
        <br><br>
        <span class="hi-gold">Foco:</span> treino intenso, proteína alta e constância calórica.
    </div>
    <div class="fake-button">✦ Analisar agora com Claude</div>
</div>
"""),
        unsafe_allow_html=True,
    )

fig = make_subplots(specs=[[{"secondary_y": True}]])
fig.add_trace(go.Scatter(x=historico["data"], y=historico["peso"], name="Peso", mode="lines+markers", line=dict(color="#4AADA0", width=3)))
fig.add_trace(go.Scatter(x=historico["data"], y=[DATA_ATUAL["meta_peso"]] * len(historico), name="Meta Peso", mode="lines", line=dict(color="#B07D3A", width=2, dash="dash")), secondary_y=False)
fig.add_trace(go.Scatter(x=historico["data"], y=historico["gordura"], name="Gordura", mode="lines+markers", line=dict(color="#D45F50", width=3)), secondary_y=True)
fig.add_trace(go.Scatter(x=historico["data"], y=[DATA_ATUAL["meta_gordura"]] * len(historico), name="Meta Gordura", mode="lines", line=dict(color="#B07D3A", width=2, dash="dash")), secondary_y=True)
fig.add_trace(go.Scatter(x=historico["data"], y=historico["musculo"], name="Músculo", mode="lines+markers", line=dict(color="#5FA04E", width=3)), secondary_y=False)
fig.update_layout(title="Evolução da composição", height=440, paper_bgcolor="#FDFAF5", plot_bgcolor="#FDFAF5")
st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
