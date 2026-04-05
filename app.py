from __future__ import annotations

import os
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.data_store import MeasurementRepository

try:
    from anthropic import Anthropic
except Exception:  # pacote opcional em runtime
    Anthropic = None


st.set_page_config(page_title="Composição Corporal · Alfred", layout="wide")

repo = MeasurementRepository()
rows = repo.list_measurements()
df = pd.DataFrame([r.__dict__ for r in rows])
df["measured_at"] = pd.to_datetime(df["measured_at"])

current = df.iloc[-1]
first = df.iloc[0]

weight_goal = 96.0
fat_goal = 20.0

progress_weight = ((current.weight_kg - 80) / (weight_goal - 80)) * 100
progress_fat = ((first.body_fat_pct - current.body_fat_pct) / (first.body_fat_pct - fat_goal)) * 100

st.title("Corpo em evolução")
st.caption("Composição corporal · Zepp Life · Acompanhamento de metas")

k1, k2, k3, k4 = st.columns(4)
k1.metric("Peso", f"{current.weight_kg:.1f} kg", f"{current.weight_kg - first.weight_kg:.1f} kg")
k2.metric("Gordura", f"{current.body_fat_pct:.1f}%", f"{current.body_fat_pct - first.body_fat_pct:.1f} pp")
k3.metric("Músculo", f"{current.muscle_kg:.1f} kg", f"{current.muscle_kg - first.muscle_kg:.1f} kg")
k4.metric("Score", "49", f"{current.weight_kg - first.weight_kg:.1f} kg")

m1, m2 = st.columns(2)
with m1:
    st.subheader("Meta de peso")
    st.progress(max(0, min(100, int(progress_weight))) / 100)
    st.write(f"Atual: **{current.weight_kg:.1f} kg** · Meta: **{weight_goal:.1f} kg**")
with m2:
    st.subheader("Meta de gordura")
    st.progress(max(0, min(100, int(progress_fat))) / 100)
    st.write(f"Atual: **{current.body_fat_pct:.1f}%** · Meta: **{fat_goal:.1f}%**")

fig = go.Figure()
fig.add_trace(go.Scatter(x=df["measured_at"], y=df["weight_kg"], name="Peso (kg)", mode="lines+markers"))
fig.add_trace(go.Scatter(x=df["measured_at"], y=df["body_fat_pct"], name="Gordura (%)", mode="lines+markers", yaxis="y2"))
fig.add_trace(go.Scatter(x=df["measured_at"], y=df["muscle_kg"], name="Músculo (kg)", mode="lines+markers"))
fig.add_hline(y=weight_goal, line_dash="dash", annotation_text="Meta Peso")
fig.update_layout(
    height=430,
    legend=dict(orientation="h"),
    yaxis=dict(title="kg"),
    yaxis2=dict(title="% gordura", overlaying="y", side="right"),
)
st.plotly_chart(fig, use_container_width=True)

c1, c2 = st.columns(2)
with c1:
    st.subheader("Composição hoje")
    fat_kg = current.weight_kg * (current.body_fat_pct / 100)
    other_kg = current.weight_kg - current.muscle_kg - fat_kg
    donut = go.Figure(
        go.Pie(
            labels=["Músculo", "Gordura", "Outros"],
            values=[current.muscle_kg, fat_kg, max(other_kg, 0)],
            hole=0.65,
        )
    )
    donut.update_layout(height=350)
    st.plotly_chart(donut, use_container_width=True)
with c2:
    st.subheader("Histórico")
    st.dataframe(
        df.sort_values("measured_at", ascending=False).assign(
            measured_at=lambda x: x["measured_at"].dt.strftime("%d/%m/%Y")
        ),
        use_container_width=True,
        hide_index=True,
    )

st.divider()
st.subheader("Inserir nova medição")

with st.form("new_measurement"):
    d_col, w_col, f_col, m_col = st.columns(4)
    with d_col:
        measured_at = st.date_input("Data", value=date.today())
    with w_col:
        weight = st.number_input("Peso (kg)", min_value=20.0, max_value=300.0, value=91.6, step=0.1)
    with f_col:
        body_fat = st.number_input("Gordura (%)", min_value=1.0, max_value=70.0, value=29.2, step=0.1)
    with m_col:
        muscle = st.number_input("Músculo (kg)", min_value=10.0, max_value=200.0, value=61.5, step=0.1)

    save = st.form_submit_button("Salvar medição")
    if save:
        repo.add_measurement(measured_at, weight, body_fat, muscle)
        st.success("Medição salva com sucesso. Recarregue a página para ver no gráfico.")

st.divider()
st.subheader("Análise com Claude (insight + comparação de upload)")
api_key = os.getenv("ANTHROPIC_API_KEY")
can_call = Anthropic is not None and bool(api_key)

if not can_call:
    st.info(
        "Para habilitar análise com Claude, instale dependências e defina ANTHROPIC_API_KEY no ambiente."
    )

prompt = st.text_area(
    "Prompt de insight",
    value="Analise meu progresso de composição corporal e destaque gargalo principal e foco prático para as próximas 2 semanas.",
)
if st.button("Gerar insight"):
    if not can_call:
        st.warning("Claude indisponível: faltando pacote anthropic e/ou ANTHROPIC_API_KEY.")
    else:
        client = Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        st.write(msg.content[0].text)

uploaded = st.file_uploader("Upload de print Zepp Life para comparação", type=["png", "jpg", "jpeg"])
if st.button("Comparar upload"):
    if uploaded is None:
        st.warning("Envie uma imagem primeiro.")
    elif not can_call:
        st.warning("Claude indisponível: faltando pacote anthropic e/ou ANTHROPIC_API_KEY.")
    else:
        client = Anthropic(api_key=api_key)
        img_bytes = uploaded.read()
        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=700,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": uploaded.type,
                                "data": __import__("base64").b64encode(img_bytes).decode("utf-8"),
                            },
                        },
                        {
                            "type": "text",
                            "text": "Extraia os dados da medição da imagem e compare com a última medição já salva no banco."
                            f" Última medição atual: peso {current.weight_kg:.1f}kg, gordura {current.body_fat_pct:.1f}%, músculo {current.muscle_kg:.1f}kg.",
                        },
                    ],
                }
            ],
        )
        st.write(msg.content[0].text)

st.caption("Turso: configure TURSO_DATABASE_URL/TURSO_AUTH_TOKEN e adapte o repositório para libsql em produção.")
