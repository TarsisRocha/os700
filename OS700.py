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

if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
    st.session_state["username"] = ""

# ==================== Configuração da página ====================
st.set_page_config(
    page_title="Gestão de Parque de Informática",
    page_icon="infocustec.png",
    layout="wide",
)

# ==================== Cabeçalho (logo + título) centralizado ====================
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
            st.success(f"Bem-vindo, {usuario}!")
            st.session_state["logged_in"] = True
            st.session_state["username"] = usuario
            st.experimental_rerun()
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

    atrasados = []
    for c in chamados:
        if c.get("hora_fechamento") is None:
            try:
                abertura = datetime.strptime(c["hora_abertura"], "%d/%m/%Y %H:%M:%S")
                util = calculate_working_hours(abertura, agora)
                if util > timedelta(hours=24):
                    atrasados.append(c)
            except:
                pass
    if atrasados:
        st.warning(f"Atenção: {len(atrasados)} chamados abertos há mais de 24h úteis!")

    df["mes"] = df["hora_abertura_dt"].dt.to_period("M").astype(str)
    tendencia_mensal = df.groupby("mes").size().reset_index(name="qtd_mensal")
    st.markdown("### Tendência de Chamados por Mês")
    if not tendencia_mensal.empty:
        fig_mensal = px.line(
            tendencia_mensal, x="mes", y="qtd_mensal", markers=True, title="Chamados por Mês"
        )
        st.plotly_chart(fig_mensal, use_container_width=True)
    else:
        st.info("Sem dados suficientes para tendência mensal.")

    df["semana"] = df["hora_abertura_dt"].dt.to_period("W").astype(str)
    tendencia_semanal = df.groupby("semana").size().reset_index(name="qtd_semanal")

    def parse_ano_semana(sem):
        try:
            ano, wk = sem.split("-")
            return (int(ano), int(wk))
        except:
            return (9999, 9999)

    tendencia_semanal["ano_semana"] = tendencia_semanal["semana"].apply(parse_ano_semana)
    tendencia_semanal.sort_values("ano_semana", inplace=True)
    st.markdown("### Tendência de Chamados por Semana")
    if not tendencia_semanal.empty:
        fig_semanal = px.line(
            tendencia_semanal, x="semana", y="qtd_semanal", markers=True, title="Chamados por Semana"
        )
        st.plotly_chart(fig_semanal, use_container_width=True)
    else:
        st.info("Sem dados suficientes para tendência semanal.")


# ==================== 3) Página de Chamados (Abrir / Buscar) ====================
def chamados_page():
    st.subheader("Chamados")
    st.markdown("Gerencie a abertura e a busca de chamados.")

    tab1, tab2 = st.tabs(["✅ Abrir Chamado", "🔍 Buscar Chamado"])

    with tab1:
        st.markdown("### Abrir Chamado Técnico")
        col1, col2 = st.columns(2)
        with col1:
            patrimonio = st.text_input(
                "Número de Patrimônio (opcional)", placeholder="Ex.: 12345"
            )
            if patrimonio:
                info = buscar_no_inventario_por_patrimonio(patrimonio)
                if info:
                    st.write(f"Máquina: {info['tipo']} - {info['marca']} {info['modelo']}")
                    st.write(f"UBS: {info['localizacao']} | Setor: {info['setor']}")
                    ubs_selecionada = info["localizacao"]
                    setor = info["setor"]
                    machine_type = info["tipo"]
                else:
                    st.error("Patrimônio não encontrado.")
                    st.stop()
            else:
                ubs_selecionada = st.selectbox("UBS", get_ubs_list())
                setor = st.selectbox("Setor", get_setores_list())
                machine_type = st.selectbox("Tipo de Máquina", ["Computador", "Impressora", "Outro"])

        with col2:
            data_agendada = st.date_input("Data Agendada (opcional)")
            st.write("")

        if machine_type == "Computador":
            defect_options = [
                "Computador não liga",
                "Computador lento",
                "Tela azul",
                "Sistema travando",
                "Erro de disco",
                "Problema com atualização",
                "Desligamento inesperado",
                "Problema com internet",
                "Problema com Wi-Fi",
                "Sem conexão de rede",
                "Mouse não funciona",
                "Teclado não funciona",
            ]
        elif machine_type == "Impressora":
            defect_options = [
                "Impressora não imprime",
                "Impressão borrada",
                "Toner vazio",
                "Troca de toner",
                "Papel enroscado",
                "Erro de conexão com a impressora",
            ]
        else:
            defect_options = ["Solicitação geral de suporte", "Outro"]

        tipo_defeito = st.selectbox("Tipo de Defeito/Solicitação", defect_options)
        problema = st.text_area(
            "Descreva o problema ou solicitação",
            placeholder="Explique em detalhes...",
            height=120,
        )

        if st.button("Abrir Chamado"):
            if problema.strip() == "":
                st.error("Descreva o problema antes de enviar.")
            else:
                agendamento_str = data_agendada.strftime("%d/%m/%Y") if data_agendada else None
                protocolo = add_chamado(
                    st.session_state["username"],
                    ubs_selecionada,
                    setor,
                    tipo_defeito,
                    problema + (f" | Agendamento: {agendamento_str}" if agendamento_str else ""),
                    patrimonio=patrimonio,
                )
                if protocolo:
                    st.success(f"Chamado aberto com sucesso! Protocolo: {protocolo}")
                else:
                    st.error("Erro ao abrir chamado.")

    with tab2:
        st.markdown("### Buscar Chamado")
        protocolo = st.text_input(
            "Número do Protocolo", placeholder="Digite o protocolo ex.: 1024"
        )
        if st.button("Buscar"):
            if not protocolo.strip():
                st.warning("Informe um protocolo válido.")
            else:
                chamado = get_chamado_by_protocolo(protocolo)
                if chamado:
                    st.write("Chamado encontrado:")
                    exibir_chamado(chamado)
                else:
                    st.error("Chamado não encontrado.")


def exibir_chamado(chamado: dict):
    st.markdown("#### Detalhes do Chamado")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**ID:** {chamado.get('id', 'N/A')}")
        st.markdown(f"**Usuário:** {chamado.get('username', 'N/A')}")
        st.markdown(f"**UBS:** {chamado.get('ubs', 'N/A')}")
        st.markdown(f"**Setor:** {chamado.get('setor', 'N/A')}")
        st.markdown(f"**Protocolo:** {chamado.get('protocolo', 'N/A')}")
    with col2:
        st.markdown(f"**Tipo de Defeito:** {chamado.get('tipo_defeito', 'N/A')}")
        st.markdown(f"**Problema:** {chamado.get('problema', 'N/A')}")
        st.markdown(f"**Hora de Abertura:** {chamado.get('hora_abertura', 'Em aberto')}")
        st.markdown(f"**Hora de Fechamento:** {chamado.get('hora_fechamento', 'Em aberto')}")
    if chamado.get("solucao"):
        st.markdown("### Solução")
        st.markdown(chamado["solucao"])


# ==================== 4) Página de Chamados Técnicos (expanders) ====================
def chamados_tecnicos_page():
    st.subheader("Chamados Técnicos")
    st.markdown("Painel para visualizar, finalizar ou reabrir chamados técnicos.")

    with st.spinner("Carregando chamados..."):
        chamados = list_chamados() or []

    if not chamados:
        st.info("Nenhum chamado registrado.")
        return

    # Monta DataFrame para status
    df = pd.DataFrame(chamados)
    df["hora_abertura_dt"] = pd.to_datetime(
        df["hora_abertura"], format="%d/%m/%Y %H:%M:%S", errors="coerce"
    )
    df["aberto"] = df["hora_fechamento"].isnull()

    # Calcula tempo útil e marca overdue
    agora = datetime.now(FORTALEZA_TZ)
    overdue, abertos, fechados = [], [], []
    for c in chamados:
        if c.get("hora_fechamento") is None:
            try:
                abertura = datetime.strptime(c["hora_abertura"], "%d/%m/%Y %H:%M:%S")
                util = calculate_working_hours(abertura, agora)
                c["tempo_util"] = (
                    f"{util.seconds // 3600}h {(util.seconds % 3600) // 60}m"
                    if util.total_seconds() > 0
                    else "0m"
                )
                c["overdue"] = util > timedelta(hours=24)
            except:
                c["tempo_util"] = "-"
                c["overdue"] = False
            c["status"] = "Aberto"
        else:
            c["tempo_util"] = "-"
            c["status"] = "Fechado"
            c["overdue"] = False

        if c["status"] == "Fechado":
            fechados.append(c)
        elif c["overdue"]:
            overdue.append(c)
        else:
            abertos.append(c)

    # Mostra métricas
    total = len(chamados)
    qt_abertos = len(abertos) + len(overdue)
    qt_fechados = len(fechados)
    c1, c2, c3 = st.columns(3)
    c1.metric("Total de Chamados", total)
    c2.metric("Aberto (incl. overdue)", qt_abertos)
    c3.metric("Fechados", qt_fechados)
    st.markdown("---")

    # Seção Overdue (vermelho)
    if overdue:
        st.markdown(
            "<div style='background-color:#f8d7da; padding:8px; border-radius:4px;'>"
            "<strong>❗ Chamados Overdue (abertos há mais de 24h úteis)</strong></div>",
            unsafe_allow_html=True,
        )
        for c in overdue:
            with st.expander(f"🔴 {c['protocolo']} – {c['tipo_defeito']} (Overdue)"):
                st.write(f"UBS: {c['ubs']}  |  Setor: {c['setor']}")
                st.write(f"Abertura: {c['hora_abertura']}  |  Tempo: {c['tempo_util']}")
        st.markdown("---")

    # Seção Abertos (verde)
    if abertos:
        st.markdown(
            "<div style='background-color:#d1e7dd; padding:8px; border-radius:4px;'>"
            "<strong>🟢 Chamados Abertos (até 24h úteis)</strong></div>",
            unsafe_allow_html=True,
        )
        for c in abertos:
            with st.expander(f"🟢 {c['protocolo']} – {c['tipo_defeito']}"):
                st.write(f"UBS: {c['ubs']}  |  Setor: {c['setor']}")
                st.write(f"Abertura: {c['hora_abertura']}  |  Tempo: {c['tempo_util']}")
        st.markdown("---")

    # Seção Fechados (cinza)
    if fechados:
        st.markdown(
            "<div style='background-color:#e2e3e5; padding:8px; border-radius:4px;'>"
            "<strong>⚪ Chamados Fechados</strong></div>",
            unsafe_allow_html=True,
        )
        for c in fechados:
            with st.expander(f"⚪ {c['protocolo']} – {c['tipo_defeito']}"):
                st.write(f"UBS: {c['ubs']}  |  Setor: {c['setor']}")
                st.write(f"Abertura: {c['hora_abertura']}  |  Fechamento: {c['hora_fechamento']}")
                if c.get("solucao"):
                    st.write(f"Solução: {c['solucao']}")
        st.markdown("---")

    # Submenu Finalizar/Reabrir
    st.markdown("### Ação nos Chamados")
    tab1, tab2 = st.tabs(["✅ Finalizar Chamado", "🔄 Reabrir Chamado"])

    with tab1:
        df_abertos = df[df["aberto"]].copy()
        if df_abertos.empty:
            st.info("Nenhum chamado aberto para finalizar.")
        else:
            sel = st.selectbox("Protocolo para finalizar", df_abertos["protocolo"].tolist())
            cham = df_abertos[df_abertos["protocolo"] == sel].iloc[0]
            cA, cB = st.columns(2)
            with cA:
                st.write(f"**ID:** {cham['id']}")
                st.write(f"**UBS:** {cham['ubs']}")
                st.write(f"**Setor:** {cham['setor']}")
            with cB:
                st.write(f"**Tipo:** {cham['tipo_defeito']}")
                st.write(f"**Abertura:** {cham['hora_abertura']}")
            st.markdown("---")
            sol = st.text_area("Solução", placeholder="Descreva a solução", height=100)
            estoque_data = get_estoque() or []
            pieces_list = [item["nome"] for item in estoque_data]
            pecas_selecionadas = st.multiselect(
                "Selecione peças utilizadas (se houver)", pieces_list
            )
            if st.button("Finalizar Chamado"):
                if not sol.strip():
                    st.error("Informe a solução.")
                else:
                    finalizar_chamado(cham["id"], sol, pecas_usadas=pecas_selecionadas)
                    st.success(f"Chamado {cham['protocolo']} finalizado!")
                    st.experimental_rerun()

    with tab2:
        df_fechados = df[~df["aberto"]].copy()
        if df_fechados.empty:
            st.info("Nenhum chamado fechado para reabrir.")
        else:
            sel = st.selectbox("Protocolo para reabrir", df_fechados["protocolo"].tolist())
            cham = df_fechados[df_fechados["protocolo"] == sel].iloc[0]
            cA, cB = st.columns(2)
            with cA:
                st.write(f"**ID:** {cham['id']}")
                st.write(f"**UBS:** {cham['ubs']}")
                st.write(f"**Setor:** {cham['setor']}")
            with cB:
                st.write(f"**Tipo:** {cham['tipo_defeito']}")
                st.write(f"**Abertura:** {cham['hora_abertura']}")
                st.write(f"**Fechamento:** {cham['hora_fechamento']}")
            remover = st.checkbox("Remover histórico associado?", value=False)
            if st.button("Reabrir Chamado"):
                reabrir_chamado(cham["id"], remover_historico=remover)
                st.success(f"Chamado {cham['protocolo']} reaberto!")
                st.experimental_rerun()


# ==================== 5) Página de Inventário ====================
def inventario_page():
    st.subheader("Inventário")
    st.markdown("Selecione um item abaixo para ver detalhes e editar.")

    tab1, tab2, tab3 = st.tabs(
        ["📋 Listar Inventário", "➕ Cadastrar Máquina", "📊 Dashboard Inventário"]
    )
    with tab1:
        show_inventory_list()
    with tab2:
        cadastro_maquina()
    with tab3:
        dashboard_inventario()


# ==================== 6) Página de Estoque ====================
def estoque_page():
    st.subheader("Estoque de Peças")
    st.markdown("Controle o estoque de peças de informática.")

    tab1, tab2 = st.tabs(["🔍 Visualizar Estoque", "➕ Gerenciar Estoque"])
    with tab1:
        estoque_data = get_estoque() or []
        if estoque_data:
            st.dataframe(pd.DataFrame(estoque_data))
        else:
            st.info("Estoque vazio.")
    with tab2:
        manage_estoque()


# ==================== 7) Página de Administração ====================
def administracao_page():
    st.subheader("Administração")
    st.markdown("Gerencie usuários, UBSs e setores.")

    tab1, tab2, tab3, tab4 = st.tabs(
        ["👤 Cadastro de Usuário", "🏥 Gerenciar UBSs", "🏢 Gerenciar Setores", "📜 Lista de Usuários"]
    )

    with tab1:
        st.markdown("### Cadastro de Usuário")
        novo_user = st.text_input("Novo Usuário", placeholder="Digite o username")
        nova_senha = st.text_input("Senha", type="password", placeholder="Digite a senha")
        admin_flag = st.checkbox("Administrador")
        if st.button("Cadastrar Usuário"):
            if novo_user and nova_senha:
                if add_user(novo_user, nova_senha, admin_flag):
                    st.success("Usuário cadastrado com sucesso!")
                else:
                    st.error("Erro ao cadastrar usuário ou usuário já existe.")
            else:
                st.error("Preencha username e senha.")

    with tab2:
        st.markdown("### Gerenciar UBSs")
        from ubs import manage_ubs

        manage_ubs()

    with tab3:
        st.markdown("### Gerenciar Setores")
        from setores import manage_setores

        manage_setores()

    with tab4:
        st.markdown("### Lista de Usuários")
        usuarios = list_users()
        if usuarios:
            st.table(usuarios)
        else:
            st.info("Nenhum usuário cadastrado.")


# ==================== 8) Página de Relatórios ====================
def relatorios_page():
    st.subheader("Relatórios Completos")
    st.markdown("Filtre os chamados por período e UBS para ver estatísticas e gráficos.")

    c1, c2, c3 = st.columns(3)
    with c1:
        start_date = st.date_input("Data Início")
    with c2:
        end_date = st.date_input("Data Fim")
    with c3:
        filtro_ubs = st.multiselect("Filtrar por UBS", get_ubs_list())

    if start_date > end_date:
        st.error("Data Início não pode ser maior que Data Fim.")
        return

    agora = datetime.now(FORTALEZA_TZ)
    st.markdown(f"**Horário local (Fortaleza):** {agora.strftime('%d/%m/%Y %H:%M:%S')}")

    chamados = list_chamados() or []
    if not chamados:
        st.info("Nenhum chamado técnico encontrado.")
        return

    df = pd.DataFrame(chamados)
    df["hora_abertura_dt"] = pd.to_datetime(
        df["hora_abertura"], format="%d/%m/%Y %H:%M:%S", errors="coerce"
    )

    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date, datetime.max.time())
    df_period = df[(df["hora_abertura_dt"] >= start_dt) & (df["hora_abertura_dt"] <= end_dt)]
    if filtro_ubs:
        df_period = df_period[df_period["ubs"].isin(filtro_ubs)]

    st.markdown("### Chamados Técnicos no Período")
    if not df_period.empty:
        st.dataframe(df_period)
    else:
        st.info("Sem chamados neste período.")

    abertos = df_period["hora_fechamento"].isnull().sum()
    fechados = df_period["hora_fechamento"].notnull().sum()
    st.markdown(f"**Chamados Abertos (período):** {abertos}")
    st.markdown(f"**Chamados Fechados (período):** {fechados}")

    def tempo_resolucao(row):
        if pd.notnull(row["hora_fechamento"]):
            try:
                ab = datetime.strptime(row["hora_abertura"], "%d/%m/%Y %H:%M:%S")
                fe = datetime.strptime(row["hora_fechamento"], "%d/%m/%Y %H:%M:%S")
                delta = calculate_working_hours(ab, fe)
                return delta.total_seconds()
            except:
                return None
        return None

    df_period["tempo_resolucao_seg"] = df_period.apply(tempo_resolucao, axis=1)
    df_resolvidos = df_period.dropna(subset=["tempo_resolucao_seg"])
    if not df_resolvidos.empty:
        media_seg = df_resolvidos["tempo_resolucao_seg"].mean()
        horas = int(media_seg // 3600)
        minutos = int((media_seg % 3600) // 60)
        st.markdown(f"**Tempo Médio de Resolução (horas úteis):** {horas}h {minutos}m")
    else:
        st.write("Nenhum chamado finalizado no período para calcular tempo médio.")

    st.markdown("---")
    if "tipo_defeito" in df_period.columns:
        chamados_tipo = df_period.groupby("tipo_defeito").size().reset_index(name="qtd")
        st.markdown("#### Chamados por Tipo de Defeito")
        st.dataframe(chamados_tipo)
        fig_tipo = px.bar(
            chamados_tipo,
            x="tipo_defeito",
            y="qtd",
            title="Chamados por Tipo de Defeito",
            labels={"tipo_defeito": "Tipo de Defeito", "qtd": "Quantidade"},
        )
        st.plotly_chart(fig_tipo, use_container_width=True)

    st.markdown("---")
    if "ubs" in df_period.columns and "setor" in df_period.columns:
        chamados_ubs_setor = df_period.groupby(["ubs", "setor"]).size().reset_index(name="qtd_chamados")
        st.markdown("#### Chamados por UBS e Setor")
        st.dataframe(chamados_ubs_setor)

    st.markdown("---")
    if not df_period.empty:
        df_period["dia_semana_en"] = df_period["hora_abertura_dt"].dt.day_name()
        day_map = {
            "Monday": "Segunda-feira",
            "Tuesday": "Terça-feira",
            "Wednesday": "Quarta-feira",
            "Thursday": "Quinta-feira",
            "Friday": "Sexta-feira",
            "Saturday": "Sábado",
            "Sunday": "Domingo",
        }
        df_period["dia_semana_pt"] = df_period["dia_semana_en"].map(day_map)
        chamados_dia = df_period.groupby("dia_semana_pt").size().reset_index(name="qtd")
        st.markdown("#### Chamados por Dia da Semana")
        st.table(chamados_dia)
        fig_dia = px.bar(
            chamados_dia,
            x="dia_semana_pt",
            y="qtd",
            title="Chamados por Dia da Semana",
            labels={"dia_semana_pt": "Dia da Semana", "qtd": "Quantidade"},
        )
        st.plotly_chart(fig_dia, use_container_width=True)


# ==================== Roteamento das páginas ====================
if selected == "Login":
    login_page()

elif selected == "Dashboard":
    dashboard_page()

elif selected == "Chamados":
    chamados_page()

elif selected == "Chamados Técnicos":
    chamados_tecnicos_page()

elif selected == "Inventário":
    inventario_page()

elif selected == "Estoque":
    estoque_page()

elif selected == "Administração":
    administracao_page()

elif selected == "Relatórios":
    relatorios_page()

elif selected == "Sair":
    st.session_state["logged_in"] = False
    st.session_state["username"] = ""
    st.success("Você saiu com sucesso. Até breve!")
    st.experimental_rerun()

else:
    st.info("Selecione uma opção no menu acima.")
