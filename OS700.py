# ====================== OS700.py ======================

# ===== 1) Bibliotecas padrão =====
import os
import logging
from datetime import datetime, timedelta, date

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
from inventario import show_inventory_list, cadastro_maquina, dashboard_inventario
from ubs import get_ubs_list
from setores import get_setores_list
from estoque import manage_estoque, get_estoque

# ==================== Configurações iniciais ====================
FORTALEZA_TZ = pytz.timezone("America/Fortaleza")
logging.basicConfig(level=logging.INFO)

st.session_state.setdefault("logged_in", False)
st.session_state.setdefault("username", "")
st.session_state.setdefault("selected_chamado", None)

# ==================== Config da página ====================
st.set_page_config(page_title="Gestão de Parque",
                   page_icon="infocustec.png", layout="wide")

# ==================== Cabeçalho ====================
_, col, _ = st.columns([1, 2, 1])
with col:
    if os.path.exists("infocustec.png"):
        st.image("infocustec.png", width=280)
    st.markdown("<h2 style='text-align:center'>Gestão de Parque APS Itapipoca</h2>",
                unsafe_allow_html=True)
st.markdown("---")

# ==================== Menu ====================
def menu() -> list[str]:
    if not st.session_state["logged_in"]:
        return ["Login"]
    base = ["Chamados", "Sair"]
    extra = ["Dashboard", "Chamados Técnicos", "Inventário",
             "Estoque", "Administração", "Relatórios"]
    return extra + base if is_admin(st.session_state["username"]) else base

selected = option_menu(None, menu(),
                       icons=["speedometer", "chat-left-text", "card-list",
                              "clipboard-data", "box-seam", "gear",
                              "bar-chart-line", "box-arrow-right"],
                       orientation="horizontal")
st.markdown("---")


# ==================== 1) Login ====================
def pagina_login():
    st.subheader("Login")
    usr = st.text_input("Usuário")
    pwd = st.text_input("Senha", type="password")
    if st.button("Entrar"):
        if authenticate(usr, pwd):
            st.session_state.update(logged_in=True, username=usr)
            st.rerun()
        else:
            st.error("Credenciais inválidas.")


# ==================== Helpers ====================
def agora_naive() -> datetime:
    """Retorna agora sem tz (para cálculos)"""
    return datetime.now().replace(tzinfo=None)


def parse_naive(dt_str: str) -> datetime:
    """Converte string 'dd/mm/yyyy HH:MM:SS' em datetime naive"""
    return datetime.strptime(dt_str, "%d/%m/%Y %H:%M:%S")


# ==================== 2) Dashboard ====================
def pagina_dashboard():
    st.subheader("Dashboard")
    agora_aw = datetime.now(FORTALEZA_TZ)
    st.caption(agora_aw.strftime("%d/%m/%Y %H:%M:%S  (America/Fortaleza)"))

    df = pd.DataFrame(list_chamados() or [])
    if df.empty:
        st.info("Nenhum chamado."); return

    total, abertos = len(df), df["hora_fechamento"].isna().sum()
    c1, c2, c3 = st.columns(3)
    c1.metric("Total", total)
    c2.metric("Abertos", abertos)
    c3.metric("Fechados", total - abertos)

    atrasados = 0
    now_n = agora_naive()
    for _, row in df[df["hora_fechamento"].isna()].iterrows():
        if calculate_working_hours(parse_naive(row["hora_abertura"]), now_n) > timedelta(hours=24):
            atrasados += 1
    if atrasados:
        st.warning(f"{atrasados} chamado(s) há +24 h úteis")

    # gráfico por mês
    df["mes"] = pd.to_datetime(df["hora_abertura"],
                               format="%d/%m/%Y %H:%M:%S").dt.to_period("M")
    mens = df.groupby("mes").size().reset_index(name="qtd")
    st.plotly_chart(px.line(mens, x="mes", y="qtd", title="Chamados / mês",
                            markers=True), use_container_width=True)


# ==================== 3) Abrir / Buscar Chamados ====================
def pagina_chamados():
    st.subheader("Chamados")
    tab1, tab2 = st.tabs(["Abrir", "Buscar"])

    # --- Abrir ---
    with tab1:
        patrimonio = st.text_input("Patrimônio (opcional)")
        if patrimonio:
            info = buscar_no_inventario_por_patrimonio(patrimonio)
            if not info:
                st.error("Patrimônio não encontrado."); st.stop()
            ubs, setor = info["localizacao"], info["setor"]
            st.caption(f"{info['marca']} {info['modelo']} @ {ubs}/{setor}")
        else:
            ubs = st.selectbox("UBS", get_ubs_list())
            setor = st.selectbox("Setor", get_setores_list())

        tipo_defeito = st.text_input("Tipo de Defeito")
        problema = st.text_area("Descrição do problema")
        if st.button("Abrir Chamado") and problema.strip():
            protocolo = add_chamado(st.session_state["username"], ubs, setor,
                                    tipo_defeito, problema, patrimonio=patrimonio)
            st.success(f"Chamado aberto. Protocolo: {protocolo}")

    # --- Buscar ---
    with tab2:
        prot = st.text_input("Protocolo")
        if st.button("Buscar") and prot:
            ch = get_chamado_by_protocolo(prot)
            st.write(ch or "Chamado não encontrado.")


# ==================== 4) Chamados Técnicos ====================
def pagina_tecnicos():
    st.subheader("Chamados Técnicos")
    chamados = list_chamados() or []
    if not chamados:
        st.info("Nenhum chamado."); return

    now_n = agora_naive()
    for c in chamados:
        if c["hora_fechamento"] is None:
            util = calculate_working_hours(parse_naive(c["hora_abertura"]), now_n)
            c.update(status="Aberto", tempo=f"{util.seconds//3600}h",
                     overdue=util > timedelta(hours=24))
        else:
            c.update(status="Fechado", tempo="-", overdue=False)

    grupos = {
        "❗ Overdue": [c for c in chamados if c["overdue"]],
        "🟢 Abertos": [c for c in chamados if c["status"]=="Aberto" and not c["overdue"]],
        "⚪ Fechados": [c for c in chamados if c["status"]=="Fechado"]
    }

    def card_chamado(ch: dict):
        if card(
            title=f"{ch['protocolo']} - {ch['tipo_defeito'][:18]}",
            text=f"{ch['ubs']} | {ch['setor']}\n{ch['hora_abertura']} | {ch['tempo']}",
            image=None, key=f"card_{ch['id']}"
        ):
            st.session_state["selected_chamado"] = ch["id"]

    # render cards
    for titulo, lista in grupos.items():
        if lista:
            st.markdown(f"**{titulo}**")
            cols = st.columns(4)
            for idx, ch in enumerate(lista):
                with cols[idx % 4]:
                    card_chamado(ch)
            st.markdown("---")

    sel_id = st.session_state.get("selected_chamado")
    if sel_id:
        cham = next((c for c in chamados if c["id"] == sel_id), None)
        if cham:
            st.markdown(f"### Chamado {cham['protocolo']}")
            st.json(cham)
            if cham["status"] == "Aberto":
                sol = st.text_area("Solução")
                if st.button("Finalizar") and sol.strip():
                    finalizar_chamado(sel_id, sol)
                    st.session_state["selected_chamado"] = None
                    st.rerun()
            else:
                if st.button("Reabrir"):
                    reabrir_chamado(sel_id)
                    st.session_state["selected_chamado"] = None
                    st.rerun()


# ==================== 5) Inventário ====================
def pagina_inventario():
    st.subheader("Inventário")
    tab1, tab2, tab3 = st.tabs(["Lista", "Cadastrar", "Dashboard"])
    with tab1: show_inventory_list()
    with tab2: cadastro_maquina()
    with tab3: dashboard_inventario()


# ==================== 6) Estoque ====================
def pagina_estoque():
    st.subheader("Estoque")
    tab1, tab2 = st.tabs(["Visualizar", "Gerenciar"])
    with tab1:
        dados = get_estoque() or []
        st.dataframe(pd.DataFrame(dados) if dados else "Estoque vazio")
    with tab2: manage_estoque()


# ==================== 7) Administração ====================
def pagina_admin():
    st.subheader("Administração")
    col1, col2 = st.columns(2)
    with col1:
        usr = st.text_input("Novo usuário")
        pwd = st.text_input("Senha", type="password")
        adm = st.checkbox("Administrador")
        if st.button("Criar") and usr and pwd:
            ok = add_user(usr, pwd, adm)
            st.success("Usuário criado") if ok else st.error("Erro ou já existe.")
    with col2:
        st.markdown("#### Usuários")
        st.table(list_users())


# ==================== 8) Relatórios ====================
def pagina_relatorios():
    st.subheader("Relatórios")
    col1, col2 = st.columns(2)
    start = col1.date_input("Data início", value=date.today())
    end   = col2.date_input("Data fim", value=date.today())
    if start > end:
        st.error("Data início maior que fim."); return
    filtro = st.multiselect("Filtrar UBS", get_ubs_list())

    df = pd.DataFrame(list_chamados() or [])
    if df.empty:
        st.info("Sem chamados."); return
    df["data"] = pd.to_datetime(df["hora_abertura"],
                                format="%d/%m/%Y %H:%M:%S").dt.date
    df = df[(df["data"] >= start) & (df["data"] <= end)]
    if filtro:
        df = df[df["ubs"].isin(filtro)]

    st.dataframe(df)


# ==================== Router ====================
router = {
    "Login": pagina_login,
    "Dashboard": pagina_dashboard,
    "Chamados": pagina_chamados,
    "Chamados Técnicos": pagina_tecnicos,
    "Inventário": pagina_inventario,
    "Estoque": pagina_estoque,
    "Administração": pagina_admin,
    "Relatórios": pagina_relatorios,
}

if selected == "Sair":
    st.session_state.update(logged_in=False, username="", selected_chamado=None)
    st.success("Sessão encerrada.")
    st.rerun()
else:
    router[selected]()
