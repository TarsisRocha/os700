# ====================== OS700.py ======================

# ===== 1) Bibliotecas padrão =====
import os
import logging
from datetime import datetime, timedelta

# ===== 2) Bibliotecas de terceiros =====
import pandas as pd
import streamlit as st
import pytz
from PIL import Image
from st_aggrid import AgGrid, GridOptionsBuilder
from streamlit_option_menu import option_menu
import plotly.express as px

# ===== 3) Módulos internos =====
from autenticacao import authenticate, add_user, is_admin, list_users
from chamados import (
    add_chamado,
    get_chamado_by_protocolo,
    list_chamados,
    list_chamados_em_aberto,
    buscar_no_inventario_por_patrimonio,
    finalizar_chamado,
    calculate_working_hours,
    reabrir_chamado,
)
from inventario import (
    show_inventory_list,
    cadastro_maquina,
    get_machines_from_inventory,
    dashboard_inventario,
)
from ubs import get_ubs_list
from setores import get_setores_list
from estoque import manage_estoque, get_estoque

# ==================== Configurações iniciais ====================
# Fuso horário de Fortaleza (UTC−3)
FORTALEZA_TZ = pytz.timezone("America/Fortaleza")

# Configuração de logging
logging.basicConfig(level=logging.INFO)

# Inicialização do estado de sessão (login)
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
    st.session_state["username"] = ""

# ==================== Configuração da página ====================
st.set_page_config(
    page_title="Gestão de Parque de Informática",
    page_icon="infocustec.png",
    layout="wide",
)

# ==================== Cabeçalho centralizado ====================
logo_path = os.getenv("LOGO_PATH", "infocustec.png")
col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    if os.path.exists(logo_path):
        st.image(logo_path, width=120)
    else:
        st.warning("Logotipo não encontrado.")
    st.markdown(
        "<h1 style='text-align: center; color: #1F2937;'>Gestão de Parque de Informática - APS ITAPIPOCA</h1>",
        unsafe_allow_html=True,
    )
st.markdown("---")


# ==================== Função build_menu ====================
def build_menu():
    """
    Monta a lista de opções do menu com base no estado de login e permissão.
    """
    if not st.session_state["logged_in"]:
        return ["Login"]
    if is_admin(st.session_state["username"]):
        return [
            "Dashboard",
            "Abrir Chamado",
            "Buscar Chamado",
            "Chamados Técnicos",
            "Inventário",
            "Estoque",
            "Administração",
            "Relatórios",
            "Sair",
        ]
    else:
        return ["Abrir Chamado", "Buscar Chamado", "Sair"]


# ==================== Renderização do menu horizontal ====================
menu_options = build_menu()
selected = option_menu(
    menu_title=None,
    options=menu_options,
    icons=[
        "speedometer",
        "chat-left-text",
        "search",
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

    # Identifica chamados atrasados (> 24h úteis)
    atrasados = []
    for c in chamados:
        if c.get("hora_fechamento") is None:
            try:
                abertura = datetime.strptime(c["hora_abertura"], "%d/%m/%Y %H:%M:%S")
                util = calculate_working_hours(abertura, datetime.now(FORTALEZA_TZ))
                if util > timedelta(hours=24):
                    atrasados.append(c)
            except:
                pass
    if atrasados:
        st.warning(f"Atenção: {len(atrasados)} chamados abertos há mais de 24h úteis!")

    # Tendência Mensal
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

    # Tendência Semanal
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


# ==================== 3) Página de Abrir Chamado ====================
def abrir_chamado_page():
    st.subheader("Abrir Chamado Técnico")
    st.markdown("Preencha os dados abaixo para abrir um novo chamado.")

    col1, col2 = st.columns(2)
    with col1:
        patrimonio = st.text_input("Número de Patrimônio (opcional)", placeholder="Ex.: 12345")
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
        st.write("")  # Espaço para balancear layout

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


# ==================== 4) Página de Buscar Chamado ====================
def buscar_chamado_page():
    st.subheader("Buscar Chamado")
    st.markdown("Informe o número de protocolo para localizar o chamado.")

    protocolo = st.text_input("Número do Protocolo", placeholder="Digite o protocolo ex.: 1024")
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
    """
    Exibe detalhes do chamado de forma organizada.
    """
    st.markdown("### Detalhes do Chamado")
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


# ==================== 5) Página de Chamados Técnicos ====================
def chamados_tecnicos_page():
    st.subheader("Chamados Técnicos")
    st.markdown("Painel para visualizar, finalizar ou reabrir chamados.")

    with st.spinner("Carregando chamados..."):
        chamados = list_chamados() or []

    if not chamados:
        st.info("Não há chamados registrados.")
        return

    df = pd.DataFrame(chamados)
    df["hora_abertura_dt"] = pd.to_datetime(
        df["hora_abertura"], format="%d/%m/%Y %H:%M:%S", errors="coerce"
    )
    df["aberto"] = df["hora_fechamento"].isnull()

    # 1) Adiciona coluna "Tempo Desde Abertura" e indicador de atraso
    now = datetime.now(FORTALEZA_TZ)
    tempos = []
    atrasados = []
    protocolos_display = []
    for idx, row in df.iterrows():
        if row["aberto"]:
            try:
                abertura = row["hora_abertura_dt"]
                # Cálculo do tempo útil até agora
                util = calculate_working_hours(abertura, now)
                seg_total = int(util.total_seconds())
                dias = seg_total // 86400
                horas = (seg_total % 86400) // 3600
                minutos = (seg_total % 3600) // 60
                if dias > 0:
                    tempo_str = f"{dias}d {horas}h"
                elif horas > 0:
                    tempo_str = f"{horas}h {minutos}m"
                else:
                    tempo_str = f"{minutos}m"
                tempos.append(tempo_str)
                # Verifica atraso (>24h úteis)
                if util > timedelta(hours=24):
                    atrasados.append(True)
                    protocolos_display.append(f"⚠️ {row['protocolo']}")
                else:
                    atrasados.append(False)
                    protocolos_display.append(str(row["protocolo"]))
            except:
                tempos.append("Erro")
                atrasados.append(False)
                protocolos_display.append(str(row["protocolo"]))
        else:
            tempos.append("-")
            atrasados.append(False)
            protocolos_display.append(str(row["protocolo"]))

    df["Tempo Desde Abertura"] = tempos
    df["Atrasado"] = atrasados
    df["Protocolo Exibido"] = protocolos_display

    # 2) Métricas resumidas
    total = len(df)
    abertos = int(df["aberto"].sum())
    fechados = total - abertos
    c1, c2, c3 = st.columns([1, 1, 1])
    c1.metric("Total de Chamados", total)
    c2.metric("Chamados Abertos", abertos)
    c3.metric("Chamados Fechados", fechados)
    st.markdown("---")

    # 3) Separação em painéis: Chamados Abertos / Chamados Fechados
    st.markdown("## Chamados Abertos")
    df_abertos = df[df["aberto"]].copy()
    if not df_abertos.empty:
        _render_tabela_abertos(df_abertos)
    else:
        st.info("Nenhum chamado em aberto.")

    st.markdown("---")
    st.markdown("## Chamados Fechados")
    df_fechados = df[~df["aberto"]].copy()
    if not df_fechados.empty:
        _render_tabela_fechados(df_fechados)
    else:
        st.info("Nenhum chamado fechado.")

    # 4) Formulário para finalizar ou reabrir dentro de cada painel – exemplo de controles rápidos
    st.markdown("---")
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        st.markdown("### Finalizar Chamado")
        _form_finalizar_chamado(df_abertos)
    with col_f2:
        st.markdown("### Reabrir Chamado")
        _form_reabrir_chamado(df_fechados)


def _render_tabela_abertos(df_abertos: pd.DataFrame):
    """
    Exibe a tabela de chamados abertos com destaque para 'Protocolo Exibido', 'UBS', 'Setor',
    'Tipo Defeito' e 'Tempo Desde Abertura'.
    """
    gb = GridOptionsBuilder.from_dataframe(df_abertos)
    # Define colunas visíveis e cabeçalhos
    gb.configure_column(
        "Protocolo Exibido", header_name="Protocolo", width=120, tooltipField="protocolo"
    )
    gb.configure_column("ubs", header_name="UBS", width=150)
    gb.configure_column("setor", header_name="Setor", width=150)
    gb.configure_column("tipo_defeito", header_name="Tipo de Defeito", width=200)
    gb.configure_column(
        "Tempo Desde Abertura", header_name="Tempo Desde Abertura", width=150
    )
    # Destacar linhas atrasadas com fundo vermelho-claro
    gb.configure_column(
        "Atrasado",
        hide=True
    )
    gb.configure_default_column(filter=True, sortable=True, resizable=True, wrapText=True)
    gb.configure_pagination(paginationAutoPageSize=False, paginationPageSize=10)
    gb.configure_grid_options(
        domLayout="normal",
        getRowStyle="""
        function(params) {
            if (params.data.Atrasado) {
                return {'backgroundColor':'#FFE5E5'};
            }
            return null;
        }
        """,
    )

    gridOptions = gb.build()
    AgGrid(
        df_abertos,
        gridOptions=gridOptions,
        enable_enterprise_modules=False,
        theme="streamlit",
        height=300,
        fit_columns_on_grid_load=True,
    )


def _render_tabela_fechados(df_fechados: pd.DataFrame):
    """
    Exibe a tabela de chamados fechados com colunas 'Protocolo', 'UBS', 'Setor',
    'Tipo Defeito', 'Hora Abertura' e 'Hora Fechamento'.
    """
    df_fechados["Hora Abertura"] = df_fechados["hora_abertura"]
    df_fechados["Hora Fechamento"] = df_fechados["hora_fechamento"]
    gb = GridOptionsBuilder.from_dataframe(df_fechados)
    gb.configure_column("protocolo", header_name="Protocolo", width=120)
    gb.configure_column("ubs", header_name="UBS", width=150)
    gb.configure_column("setor", header_name="Setor", width=150)
    gb.configure_column("tipo_defeito", header_name="Tipo de Defeito", width=200)
    gb.configure_column("Hora Abertura", header_name="Abertura", width=150)
    gb.configure_column("Hora Fechamento", header_name="Fechamento", width=150)
    gb.configure_default_column(filter=True, sortable=True, resizable=True, wrapText=True)
    gb.configure_pagination(paginationAutoPageSize=False, paginationPageSize=10)
    gb.configure_grid_options(domLayout="normal")

    gridOptions = gb.build()
    AgGrid(
        df_fechados,
        gridOptions=gridOptions,
        enable_enterprise_modules=False,
        theme="streamlit",
        height=300,
        fit_columns_on_grid_load=True,
    )


def _form_finalizar_chamado(df_abertos: pd.DataFrame):
    """
    Exibe formulário para finalizar apenas chamados abertos.
    """
    if df_abertos.empty:
        st.write("Nenhum chamado disponível para finalizar.")
        return

    protocolo_sel = st.selectbox(
        "Selecione Protocolo", df_abertos["protocolo"].tolist()
    )
    chamado = df_abertos[df_abertos["protocolo"] == protocolo_sel].iloc[0]

    st.markdown("#### Detalhes do Chamado")
    a1, a2 = st.columns(2)
    with a1:
        st.write(f"**ID:** {chamado['id']}")
        st.write(f"**UBS:** {chamado['ubs']}")
        st.write(f"**Setor:** {chamado['setor']}")
    with a2:
        st.write(f"**Tipo Defeito:** {chamado['tipo_defeito']}")
        st.write(f"**Abertura:** {chamado['hora_abertura']}")

    st.markdown("---")
    solucao = st.text_area(
        "Solução Aplicada", placeholder="Descreva em detalhes o que foi feito", height=100
    )
    pecas = st.text_input(
        "Peças Utilizadas (separadas por vírgula)", placeholder="Ex.: Toner HP, Cabo USB"
    )

    if st.button("Finalizar Chamado"):
        if not solucao.strip():
            st.error("Informe a solução antes de finalizar.")
        else:
            pecas_lista = [p.strip() for p in pecas.split(",") if p.strip()]
            finalizar_chamado(chamado["id"], solucao, pecas_usadas=pecas_lista)
            st.success(f"Chamado {chamado['protocolo']} finalizado com sucesso!")
            st.experimental_rerun()


def _form_reabrir_chamado(df_fechados: pd.DataFrame):
    """
    Exibe formulário para reabrir apenas chamados fechados.
    """
    if df_fechados.empty:
        st.write("Nenhum chamado disponível para reabrir.")
        return

    protocolo_sel = st.selectbox(
        "Selecione Protocolo", df_fechados["protocolo"].tolist()
    )
    chamado = df_fechados[df_fechados["protocolo"] == protocolo_sel].iloc[0]

    st.markdown("#### Detalhes do Chamado")
    b1, b2 = st.columns(2)
    with b1:
        st.write(f"**ID:** {chamado['id']}")
        st.write(f"**UBS:** {chamado['ubs']}")
        st.write(f"**Setor:** {chamado['setor']}")
    with b2:
        st.write(f"**Tipo Defeito:** {chamado['tipo_defeito']}")
        st.write(f"**Abertura:** {chamado['hora_abertura']}")
        st.write(f"**Fechamento:** {chamado['hora_fechamento']}")

    remover = st.checkbox("Remover histórico de manutenção associado?", value=False)
    if st.button("Reabrir Chamado"):
        reabrir_chamado(chamado["id"], remover_historico=remover)
        st.success(f"Chamado {chamado['protocolo']} reaberto com sucesso!")
        st.experimental_rerun()


# ==================== 6) Página de Inventário ====================
def inventario_page():
    st.subheader("Inventário")
    st.markdown("Gerencie seu inventário de máquinas de forma simples.")

    tab1, tab2, tab3 = st.tabs(
        ["📋 Listar Inventário", "➕ Cadastrar Máquina", "📊 Dashboard Inventário"]
    )
    with tab1:
        st.write("")
        show_inventory_list()
    with tab2:
        st.write("")
        cadastro_maquina()
    with tab3:
        st.write("")
        dashboard_inventario()


# ==================== 7) Página de Estoque ====================
def estoque_page():
    st.subheader("Estoque de Peças")
    st.markdown("Controle o estoque de peças de informática.")
    manage_estoque()


# ==================== 8) Página de Administração ====================
def administracao_page():
    st.subheader("Administração")
    st.markdown("Gerencie usuários, UBSs e setores.")

    admin_option = st.selectbox(
        "Opções de Administração",
        ["Cadastro de Usuário", "Gerenciar UBSs", "Gerenciar Setores", "Lista de Usuários"],
    )

    if admin_option == "Cadastro de Usuário":
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

    elif admin_option == "Gerenciar UBSs":
        from ubs import manage_ubs
        manage_ubs()

    elif admin_option == "Gerenciar Setores":
        from setores import manage_setores
        manage_setores()

    elif admin_option == "Lista de Usuários":
        usuarios = list_users()
        if usuarios:
            st.table(usuarios)
        else:
            st.info("Nenhum usuário cadastrado.")


# ==================== 9) Página de Relatórios ====================
def relatorios_page():
    st.subheader("Relatórios Completos")
    st.markdown("Filtro de chamados por período e UBS.")

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
    gb = GridOptionsBuilder.from_dataframe(df_period)
    gb.configure_default_column(filter=True, sortable=True)
    gb.configure_pagination(paginationAutoPageSize=True)
    gb.configure_grid_options(domLayout="normal")
    AgGrid(df_period, gridOptions=gb.build(), height=350, fit_columns_on_grid_load=True)

    abertos = df_period["hora_fechamento"].isnull().sum()
    fechados = df_period["hora_fechamento"].notnull().sum()
    st.markdown(f"**Chamados Abertos (período):** {abertos}")
    st.markdown(f"**Chamados Fechados (período):** {fechados}")

    # Cálculo do tempo médio de resolução
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


# ==================== Roteamento das páginas ====================
if selected == "Login":
    login_page()

elif selected == "Dashboard":
    dashboard_page()

elif selected == "Abrir Chamado":
    abrir_chamado_page()

elif selected == "Buscar Chamado":
    buscar_chamado_page()

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
