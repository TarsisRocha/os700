# ====================== OS700.py ======================

# ===== 1) Bibliotecas padrão =====
import os
import logging
from datetime import datetime, timedelta

# ===== 2) Bibliotecas de terceiros =====
import pandas as pd
import streamlit as st
import pytz
from streamlit_option_menu import option_menu
import plotly.express as px
from streamlit_card import card  # pip install streamlit-card>=0.0.5

# ===== 3) Módulos internos =====
from autenticacao import authenticate, add_user, is_admin, list_users
from chamados import (
    add_chamado,
    get_chamado_by_protocolo,
    list_chamados,
    buscar_no_inventario_por_patrimonio,
    finalizar_chamado,
    calculate_working_hours,
    reabrir_chamado,
)
from inventario import (
    show_inventory_list,
    cadastro_maquina,
    dashboard_inventario,
)
from ubs import get_ubs_list
from setores import get_setores_list
from estoque import manage_estoque, get_estoque

# ==================== Configurações iniciais ====================
FORTALEZA_TZ = pytz.timezone("America/Fortaleza")
logging.basicConfig(level=logging.INFO)

st.session_state.setdefault("logged_in", False)
st.session_state.setdefault("username", "")
st.session_state.setdefault("selected_chamado", None)

# ==================== Configuração da página ====================
st.set_page_config(
    page_title="Gestão de Parque de Informática",
    page_icon="infocustec.png",
    layout="wide",
)

# ==================== Cabeçalho (logo + título) ====================
logo_path = os.getenv("LOGO_PATH", "infocustec.png")
col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    if os.path.exists(logo_path):
        st.image(logo_path, width=300)
    st.markdown(
        "<h1 style='text-align:center;'>Gestão de Parque de Informática - APS ITAPIPOCA</h1>",
        unsafe_allow_html=True,
    )
st.markdown("---")

# ==================== Função build_menu ====================
def build_menu() -> list[str]:
    if not st.session_state["logged_in"]:
        return ["Login"]
    return (
        [
            "Dashboard",
            "Chamados",
            "Chamados Técnicos",
            "Inventário",
            "Estoque",
            "Administração",
            "Relatórios",
            "Sair",
        ]
        if is_admin(st.session_state["username"])
        else ["Chamados", "Sair"]
    )

# ==================== Menu ====================
selected = option_menu(
    None,
    build_menu(),
    icons=[
        "speedometer",
        "chat-left-text",
        "card-list",
        "clipboard-data",
        "box-seam",
        "gear",
        "bar-chart-line",
        "box-arrow-right",
    ],
    orientation="horizontal",
)
st.markdown("---")

# ==================== 1) Login ====================
def login_page():
    st.subheader("Login")
    usr = st.text_input("Usuário")
    pwd = st.text_input("Senha", type="password")
    if st.button("Entrar"):
        if not usr or not pwd:
            st.error("Preencha usuário e senha.")
        elif authenticate(usr, pwd):
            st.session_state.update(logged_in=True, username=usr)
            st.rerun()
        else:
            st.error("Credenciais inválidas.")

# ==================== 2) Dashboard ====================
def dashboard_page():
    st.subheader("Dashboard")
    agora = datetime.now(FORTALEZA_TZ)
    st.caption(agora.strftime("%d/%m/%Y %H:%M:%S — America/Fortaleza"))

    chamados = list_chamados() or []
    if not chamados:
        st.info("Nenhum chamado."); return

    df = pd.DataFrame(chamados)
    df["hora_abertura_dt"] = pd.to_datetime(
        df["hora_abertura"], format="%d/%m/%Y %H:%M:%S", errors="coerce"
    )

    total = len(df)
    abertos = df["hora_fechamento"].isna().sum()
    c1, c2, c3 = st.columns(3)
    c1.metric("Total", total)
    c2.metric("Abertos", abertos)
    c3.metric("Fechados", total - abertos)

    # chamados >24 h
    atrasados = []
    for c in chamados:
        if c["hora_fechamento"] is None:
            ab_naive = datetime.strptime(c["hora_abertura"], "%d/%m/%Y %H:%M:%S")
            ab = FORTALEZA_TZ.localize(ab_naive)          # ← ajuste fuso
            if calculate_working_hours(ab, agora) > timedelta(hours=24):
                atrasados.append(c)
    if atrasados:
        st.warning(f"{len(atrasados)} chamado(s) abertos há +24 h úteis!")

    # gráfico mensal
    df["mes"] = df["hora_abertura_dt"].dt.to_period("M").astype(str)
    if not df.empty:
        st.plotly_chart(
            px.bar(
                df.groupby("mes").size().reset_index(name="qtd"),
                x="mes",
                y="qtd",
                title="Chamados por Mês",
            ),
            use_container_width=True,
        )

# ==================== 3) Abrir / Buscar ====================
def chamados_page():
    st.subheader("Chamados")
    tab1, tab2 = st.tabs(["Abrir", "Buscar"])

    # ---- Abrir ----
    with tab1:
        patrimonio = st.text_input("Patrimônio (opcional)")
        if patrimonio:
            info = buscar_no_inventario_por_patrimonio(patrimonio)
            if not info:
                st.error("Patrimônio não encontrado."); st.stop()
            ubs, setor, tipo_maquina = info["localizacao"], info["setor"], info["tipo"]
            st.caption(f"{info['marca']} {info['modelo']} • {ubs} / {setor}")
        else:
            ubs = st.selectbox("UBS", get_ubs_list())
            setor = st.selectbox("Setor", get_setores_list())
            tipo_maquina = st.selectbox("Tipo", ["Computador", "Impressora", "Outro"])

        tipo_defeito = st.text_input("Tipo de Defeito")
        problema = st.text_area("Descrição")
        if st.button("Abrir Chamado") and problema.strip():
            prot = add_chamado(
                st.session_state["username"],
                ubs,
                setor,
                tipo_defeito,
                problema,
                patrimonio=patrimonio,
            )
            st.success(f"Chamado aberto! Protocolo {prot}")

    # ---- Buscar ----
    with tab2:
        prot = st.text_input("Protocolo")
        if st.button("Buscar") and prot:
            ch = get_chamado_by_protocolo(prot)
            st.write(ch or "Não encontrado.")

# ==================== 4) Painel Técnico ====================
def chamados_tecnicos_page():
    st.subheader("Chamados Técnicos")
    chamados = list_chamados() or []
    if not chamados:
        st.info("Nenhum chamado."); return

    agora = datetime.now(FORTALEZA_TZ)
    for c in chamados:
        if c["hora_fechamento"] is None:
            ab_naive = datetime.strptime(c["hora_abertura"], "%d/%m/%Y %H:%M:%S")
            ab = FORTALEZA_TZ.localize(ab_naive)          # ← ajuste fuso
            util = calculate_working_hours(ab, agora)
            c.update(status="Aberto", tempo_util=f"{util.seconds//3600}h", overdue=util>timedelta(hours=24))
        else:
            c.update(status="Fechado", tempo_util="-", overdue=False)

    grupos = {
        "❗ Overdue": [c for c in chamados if c["overdue"]],
        "🟢 Abertos": [c for c in chamados if c["status"]=="Aberto" and not c["overdue"]],
        "⚪ Fechados": [c for c in chamados if c["status"]=="Fechado"],
    }

    def draw_card(ch):
        if card(
            title=f"{ch['protocolo']} - {ch['tipo_defeito'][:18]}",
            text=f"{ch['ubs']} | {ch['setor']}\n{ch['hora_abertura']} | {ch['tempo_util']}",
            image=None,
            key=f"card_{ch['id']}",
        ):
            st.session_state["selected_chamado"] = ch["id"]

    for titulo, lista in grupos.items():
        if lista:
            st.markdown(f"**{titulo}**")
            cols = st.columns(4)
            for i, ch in enumerate(lista):
                with cols[i % 4]:
                    draw_card(ch)
            st.markdown("---")

    # Detalhes
    sel = st.session_state.get("selected_chamado")
    if sel:
        ch = next((c for c in chamados if c["id"] == sel), None)
        if ch:
            st.markdown(f"### Chamado {ch['protocolo']}")
            st.json(ch)
            if ch["status"]=="Aberto":
                sol = st.text_area("Solução")
                if st.button("Finalizar") and sol:
                    finalizar_chamado(sel, sol)
                    st.session_state["selected_chamado"]=None
                    st.rerun()
            else:
                if st.button("Reabrir"):
                    reabrir_chamado(sel)
                    st.session_state["selected_chamado"]=None
                    st.rerun()

# ==================== 5) Inventário ====================
def inventario_page():
    st.subheader("Inventário")
    tab1, tab2, tab3 = st.tabs(["Lista", "Cadastrar", "Dashboard"])
    with tab1: show_inventory_list()
    with tab2: cadastro_maquina()
    with tab3: dashboard_inventario()

# ==================== 6) Estoque ====================
def estoque_page():
    st.subheader("Estoque")
    tab1, tab2 = st.tabs(["Visualizar", "Gerenciar"])
    with tab1:
        dados = get_estoque() or []
        st.dataframe(pd.DataFrame(dados) if dados else "Estoque vazio.")
    with tab2: manage_estoque()

# ==================== 7) Administração ====================
def administracao_page():
    st.subheader("Administração")
    usr = st.text_input("Novo usuário")
    pwd = st.text_input("Senha", type="password")
    adm = st.checkbox("Administrador")
    if st.button("Cadastrar") and usr and pwd:
        ok = add_user(usr, pwd, adm)
        st.success("Cadastrado.") if ok else st.error("Erro ou usuário existe.")

# ==================== 8) Relatórios ====================
def relatorios_page():
    st.subheader("Relatórios")
    start, end = st.date_input("Período", [], format="DD/MM/YYYY")
    if start and end and start > end:
        st.error("Data início > fim."); return
    filtro = st.multiselect("UBS", get_ubs_list())
    df = pd.DataFrame(list_chamados() or [])
    if df.empty:
        st.info("Sem dados."); return
    df["abertura_dt"] = pd.to_datetime(df["hora_abertura"], format="%d/%m/%Y %H:%M:%S")
    if start and end:
        df = df[(df["abertura_dt"]>=pd.Timestamp(start)) & (df["abertura_dt"]<=pd.Timestamp(end))]
    if filtro:
        df = df[df["ubs"].isin(filtro)]
    st.dataframe(df)

# ==================== Roteamento ====================
pages = {
    "Login": login_page,
    "Dashboard": dashboard_page,
    "Chamados": chamados_page,
    "Chamados Técnicos": chamados_tecnicos_page,
    "Inventário": inventario_page,
    "Estoque": estoque_page,
    "Administração": administracao_page,
    "Relatórios": relatorios_page,
}

if selected == "Sair":
    st.session_state.update(logged_in=False, username="")
    st.rerun()
else:
    pages[selected]()
