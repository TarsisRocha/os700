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
    else:
        st.warning("Logotipo não encontrado.")
    st.markdown(
        "<h1 style='text-align: center; color: #1F2937;'>"
        "Gestão de Parque de Informática - APS ITAPIPOCA</h1>",
        unsafe_allow_html=True,
    )
st.markdown("---")

# ==================== Função build_menu ====================
def build_menu():
    if not st.session_state["logged_in"]:
        return ["Login"]
    if is_admin(st.session_state["username"]):
        return [
            "Dashboard",
            "Chamados",
            "Chamados Técnicos",
            "Inventário",
            "Estoque",
            "Administração",
            "Relatórios",
            "Sair",
        ]
    else:
        return ["Chamados", "Sair"]

# ==================== Menu horizontal ====================
menu_options = build_menu()
selected = option_menu(
    menu_title=None,
    options=menu_options,
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
    default_index=0,
    orientation="horizontal",
    styles={
        "container": {"padding": "5!important", "background-color": "#F8FAFC"},
        "icon": {"color": "black", "font-size": "18px"},
        "nav-link": {
            "font-size": "16px",
            "text-align": "center",
            "margin": "0px",
            "color": "black",
            "padding": "10px",
        },
        "nav-link-selected": {"background-color": "#0275d8", "color": "white"},
    },
)
st.markdown("---")

# ==================== 1) Página de Login ====================
def login_page():
    st.subheader("Login")
    st.markdown("Por favor, informe suas credenciais para acessar o sistema.")

    usuario = st.text_input("Usuário", placeholder="Digite seu login")
    senha = st.text_input("Senha", type="password", placeholder="Digite sua senha")

    if st.button("Entrar"):
        if not usuario or not senha:
            st.error("Preencha todos os campos.")
        elif authenticate(usuario, senha):
            st.session_state.update(logged_in=True, username=usuario)
            st.rerun()
        else:
            st.error("Usuário ou senha incorretos.")

# ==================== 2) Página de Dashboard ====================
def dashboard_page():
    st.subheader("Dashboard - Administrativo")
    agora = datetime.now(FORTALEZA_TZ)
    st.markdown(f"**Horário local (Fortaleza):** {agora.strftime('%d/%m/%Y %H:%M:%S')}")

    chamados = list_chamados() or []
    if not chamados:
        st.info("Nenhum chamado registrado.")
        return

    df = pd.DataFrame(chamados)
    df["hora_abertura_dt"] = pd.to_datetime(
        df["hora_abertura"], format="%d/%m/%Y %H:%M:%S", errors="coerce"
    )

    total = len(df)
    abertos = df["hora_fechamento"].isnull().sum()
    fechados = total - abertos

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Chamados", total)
    c2.metric("Em Aberto", abertos)
    c3.metric("Fechados", fechados)
    st.markdown("---")

    atrasados = [
        c for c in chamados
        if c.get("hora_fechamento") is None and
           calculate_working_hours(
               datetime.strptime(c["hora_abertura"], "%d/%m/%Y %H:%M:%S"), agora
           ) > timedelta(hours=24)
    ]
    if atrasados:
        st.warning(f"Atenção: {len(atrasados)} chamado(s) abertos há mais de 24h úteis!")

    df["mes"] = df["hora_abertura_dt"].dt.to_period("M").astype(str)
    tendencia_mensal = df.groupby("mes").size().reset_index(name="qtd")
    if not tendencia_mensal.empty:
        st.markdown("#### Tendência Mensal")
        st.plotly_chart(
            px.bar(tendencia_mensal, x="mes", y="qtd", title="Chamados por Mês"),
            use_container_width=True,
        )

# ==================== 3) Página de Chamados (Abrir / Buscar) ====================
def chamados_page():
    st.subheader("Chamados")
    tab1, tab2 = st.tabs(["✅ Abrir Chamado", "🔍 Buscar Chamado"])

    # --- Abrir ---
    with tab1:
        patrimonio = st.text_input("Patrimônio (opcional)")
        if patrimonio:
            info = buscar_no_inventario_por_patrimonio(patrimonio)
            if not info:
                st.error("Patrimônio não encontrado."); st.stop()
            ubs_selecionada, setor = info["localizacao"], info["setor"]
            machine_type = info["tipo"]
            st.caption(f"{info['marca']} {info['modelo']} @ {ubs_selecionada}/{setor}")
        else:
            ubs_selecionada = st.selectbox("UBS", get_ubs_list())
            setor = st.selectbox("Setor", get_setores_list())
            machine_type = st.selectbox("Tipo", ["Computador", "Impressora", "Outro"])

        tipo_defeito = st.text_input("Tipo de Defeito/Solicitação")
        problema = st.text_area("Descreva o problema")

        if st.button("Abrir Chamado") and problema.strip():
            protocolo = add_chamado(
                st.session_state["username"],
                ubs_selecionada,
                setor,
                tipo_defeito,
                problema,
                patrimonio=patrimonio,
            )
            if protocolo:
                st.success(f"Chamado aberto! Protocolo: {protocolo}")

    # --- Buscar ---
    with tab2:
        protocolo = st.text_input("Protocolo")
        if st.button("Buscar") and protocolo:
            ch = get_chamado_by_protocolo(protocolo)
            st.write(ch or "Chamado não encontrado.")

# ==================== 4) Página de Chamados Técnicos ====================
def chamados_tecnicos_page():
    st.subheader("Chamados Técnicos")
    chamados = list_chamados() or []
    if not chamados:
        st.info("Nenhum chamado técnico."); return

    agora = datetime.now(FORTALEZA_TZ)
    for c in chamados:
        if c.get("hora_fechamento") is None:
            util = calculate_working_hours(
                datetime.strptime(c["hora_abertura"], "%d/%m/%Y %H:%M:%S"), agora
            )
            c.update(
                tempo_util=f"{util.seconds//3600}h", overdue=util > timedelta(hours=24), status="Aberto"
            )
        else:
            c.update(tempo_util="-", overdue=False, status="Fechado")

    grupos = {
        "❗ Overdue": [c for c in chamados if c["overdue"]],
        "🟢 Abertos": [c for c in chamados if c["status"] == "Aberto" and not c["overdue"]],
        "⚪ Fechados": [c for c in chamados if c["status"] == "Fechado"],
    }

    def draw_clickable_card(ch):
        titulo = f"{ch['protocolo']} - {ch['tipo_defeito'][:18]}"
        texto = (
            f"UBS: {ch['ubs']} | Setor: {ch['setor']}\n"
            f"Abertura: {ch['hora_abertura']} | Tempo: {ch['tempo_util']}"
        )
        if card(title=titulo, text=texto, image=None, key=f"card_{ch['id']}"):
            st.session_state["selected_chamado"] = ch["id"]

    # --- render cards ---
    for titulo, lista in grupos.items():
        if lista:
            st.markdown(f"**{titulo}**")
            cols = st.columns(4, gap="small")
            for i, ch in enumerate(lista):
                with cols[i % 4]:
                    draw_clickable_card(ch)
            st.markdown("---")

    # --- detalhes ---
    sel_id = st.session_state.get("selected_chamado")
    if sel_id:
        cham = next((c for c in chamados if c["id"] == sel_id), None)
        if cham:
            st.markdown(f"### Chamado {cham['protocolo']}")
            st.json(cham)
            if cham["status"] == "Aberto":
                sol = st.text_area("Solução")
                if st.button("Finalizar") and sol:
                    finalizar_chamado(sel_id, sol)
                    st.session_state["selected_chamado"] = None
                    st.rerun()
            else:
                if st.button("Reabrir"):
                    reabrir_chamado(sel_id)
                    st.session_state["selected_chamado"] = None
                    st.rerun()

# ==================== 5) Página de Inventário ====================
def inventario_page():
    st.subheader("Inventário")
    tab1, tab2, tab3 = st.tabs(["📋 Lista", "➕ Cadastrar", "📊 Dashboard"])
    with tab1:
        show_inventory_list()
    with tab2:
        cadastro_maquina()
    with tab3:
        dashboard_inventario()

# ==================== 6) Página de Estoque ====================
def estoque_page():
    st.subheader("Estoque de Peças")
    tab1, tab2 = st.tabs(["🔍 Visualizar", "➕ Gerenciar"])
    with tab1:
        dados = get_estoque() or []
        st.dataframe(pd.DataFrame(dados) if dados else "Estoque vazio.")
    with tab2:
        manage_estoque()

# ==================== 7) Administração ====================
def administracao_page():
    st.subheader("Administração")
    tab1, tab2, tab3, tab4 = st.tabs(
        ["👤 Usuários", "🏥 UBSs", "🏢 Setores", "📜 Lista de Usuários"]
    )
    with tab1:
        novo = st.text_input("Username")
        senha = st.text_input("Senha", type="password")
        adm = st.checkbox("Administrador")
        if st.button("Cadastrar") and novo and senha:
            ok = add_user(novo, senha, adm)
            st.success("Cadastrado!") if ok else st.error("Erro ou usuário já existe.")
    with tab2:
        from ubs import manage_ubs; manage_ubs()
    with tab3:
        from setores import manage_setores; manage_setores()
    with tab4:
        st.table(list_users())

# ==================== 8) Relatórios ====================
def relatorios_page():
    st.subheader("Relatórios")
    col1, col2 = st.columns(2)
    start = col1.date_input("Início")
    end = col2.date_input("Fim")
    if start > end:
        st.error("Intervalo inválido."); return
    filtro = st.multiselect("UBS", get_ubs_list())
    df = pd.DataFrame(list_chamados() or [])
    if df.empty:
        st.info("Sem dados."); return
    df["data"] = pd.to_datetime(df["hora_abertura"], format="%d/%m/%Y %H:%M:%S", errors="coerce")
    df = df[(df["data"] >= pd.Timestamp(start)) & (df["data"] <= pd.Timestamp(end))]
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
    st.session_state.update(logged_in=False, username="", selected_chamado=None)
    st.success("Sessão encerrada!")
    st.rerun()
else:
    pages[selected]()
