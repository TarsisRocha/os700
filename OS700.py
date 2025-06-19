import os
import logging
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import pytz
import base64
import streamlit as st
from streamlit_option_menu import option_menu
from st_aggrid import AgGrid, GridOptionsBuilder
from fpdf import FPDF
from io import BytesIO

# Define o fuso horário de Fortaleza
FORTALEZA_TZ = pytz.timezone("America/Fortaleza")

# Importação dos módulos internos (mantidos sem alterações)
from autenticacao import authenticate, add_user, is_admin, list_users
from chamados import (
    add_chamado,
    get_chamado_by_protocolo,
    list_chamados,
    list_chamados_em_aberto,
    buscar_no_inventario_por_patrimonio,
    finalizar_chamado,
    calculate_working_hours,
    reabrir_chamado
)
from inventario import (
    show_inventory_list,
    cadastro_maquina,
    get_machines_from_inventory,
    dashboard_inventario
)
from ubs import get_ubs_list
from setores import get_setores_list
from estoque import manage_estoque, get_estoque

# Configuração de logging
logging.basicConfig(level=logging.INFO)

# Inicialização da sessão (variáveis de login)
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
if "username" not in st.session_state:
    st.session_state["username"] = ""

# Configuração da página (layout wide, favicon customizado)
st.set_page_config(
    page_title="Gestão de Parque de Informática",
    page_icon="infocustec.png",
    layout="wide"
)

# Injeção de CSS Customizado (cores, fontes, estilos)
st.markdown(
    """
    <style>
    body {
      background-color: #F8FAFC;
      font-family: "Roboto", sans-serif;
    }
    .css-18e3th9 {
      padding: 1.5rem 1.5rem 2rem 1.5rem; /* Ajuste de padding do container principal */
    }
    h1, h2, h3 {
      color: #1F2937; /* Um cinza escuro */
    }
    .css-1waiswl {
      background-color: #0275d8 !important; /* Azul do menu selecionado */
    }
    </style>
    """,
    unsafe_allow_html=True
)

logo_path = os.getenv("LOGO_PATH", "infocustec.png")
if os.path.exists(logo_path):
    with open(logo_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    st.markdown(
        f"""
        <div style="display: flex; justify-content: center; padding: 10px;">
            <img src="data:image/png;base64,{b64}" style="height:80px;" />
        </div>
        """,
        unsafe_allow_html=True
    )
else:
    st.warning("Logotipo não encontrado.")



st.title("Gestão de Parque de Informática - APS ITAPIPOCA")

####################################
# Função Auxiliar para Exibir Chamado
####################################
def exibir_chamado(chamado):
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

####################################
# Monta o Menu Principal
####################################
def build_menu():
    if st.session_state["logged_in"]:
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
                "Exportar Dados",
                "Sair"
            ]
        else:
            return [
                "Abrir Chamado",
                "Buscar Chamado",
                "Sair"
            ]
    else:
        return ["Login"]

menu_options = build_menu()

# Cria menu horizontal com streamlit-option-menu
selected = option_menu(
    menu_title=None,
    options=menu_options,
    icons=[
        "speedometer",  # Dashboard
        "chat-left-text",  # Abrir Chamado
        "search",           # Buscar Chamado
        "card-list",        # Chamados Técnicos
        "clipboard-data",   # Inventário
        "box-seam",         # Estoque
        "gear",             # Administração
        "bar-chart-line",   # Relatórios
        "download",         # Exportar Dados
        "box-arrow-right"   # Sair
    ],
    menu_icon="cast",
    default_index=0,
    orientation="horizontal",
    styles={
        "container": {"padding": "5!important", "background-color": "#F8FAFC"},
        "icon": {"color": "black", "font-size": "18px"},
        "nav-link": {"font-size": "16px", "text-align": "center", "margin": "0px", "color": "black", "padding": "10px"},
        "nav-link-selected": {"background-color": "#0275d8", "color": "white"},
    }
)

####################################
# 1) Página de Login
####################################
def login_page():
    st.subheader("Login")
    username = st.text_input("Usuário")
    password = st.text_input("Senha", type="password")
    if st.button("Entrar"):
        if not username or not password:
            st.error("Preencha todos os campos.")
        elif authenticate(username, password):
            st.success(f"Bem-vindo, {username}!")
            st.session_state["logged_in"] = True
            st.session_state["username"] = username
        else:
            st.error("Usuário ou senha incorretos.")

####################################
# 2) Página de Dashboard (Tendência Mensal e Semanal)
####################################
def dashboard_page():
    st.subheader("Dashboard - Administrativo")
    agora_fortaleza = datetime.now(FORTALEZA_TZ)
    st.markdown(f"**Horário local (Fortaleza):** {agora_fortaleza.strftime('%d/%m/%Y %H:%M:%S')}")

    chamados = list_chamados()
    if not chamados:
        st.info("Nenhum chamado registrado.")
        return

    df = pd.DataFrame(chamados)
    df["hora_abertura_dt"] = pd.to_datetime(df["hora_abertura"], format='%d/%m/%Y %H:%M:%S', errors='coerce')

    total_chamados = len(df)
    abertos = df["hora_fechamento"].isnull().sum()
    fechados = df["hora_fechamento"].notnull().sum()
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Chamados", total_chamados)
    col2.metric("Em Aberto", abertos)
    col3.metric("Fechados", fechados)

    # Identifica chamados atrasados (mais de 48h úteis)
    atrasados = []
    for c in chamados:
        if c.get("hora_fechamento") is None:
            try:
                abertura = datetime.strptime(c["hora_abertura"], '%d/%m/%Y %H:%M:%S')
                agora_local = datetime.now(FORTALEZA_TZ)
                tempo_util = calculate_working_hours(abertura, agora_local)
                if tempo_util > timedelta(hours=24):
                    atrasados.append(c)
            except:
                pass
    if atrasados:
        st.warning(f"Atenção: {len(atrasados)} chamados abertos há mais de 48h úteis!")

    # Tendência Mensal
    df["mes"] = df["hora_abertura_dt"].dt.to_period("M").astype(str)
    tendencia_mensal = df.groupby("mes").size().reset_index(name="qtd_mensal")
    st.markdown("### Tendência de Chamados por Mês")
    if not tendencia_mensal.empty:
        fig_mensal = px.line(tendencia_mensal, x="mes", y="qtd_mensal", markers=True, title="Chamados por Mês")
        st.plotly_chart(fig_mensal, use_container_width=True)
    else:
        st.info("Sem dados suficientes para exibir tendência mensal.")

    # Tendência Semanal
    df["semana"] = df["hora_abertura_dt"].dt.to_period("W").astype(str)
    tendencia_semanal = df.groupby("semana").size().reset_index(name="qtd_semanal")

    # Para ordenar corretamente no eixo X (semana = '2023-23' etc.), criamos col auxiliar "ano_semana"
    def parse_ano_semana(semana_str):
        # '2023-23' -> (2023, 23)
        # Se der erro, retorna (9999, 9999) p/ não travar
        try:
            ano, wk = semana_str.split("-")
            return (int(ano), int(wk))
        except:
            return (9999, 9999)

    tendencia_semanal["ano_semana"] = tendencia_semanal["semana"].apply(parse_ano_semana)
    tendencia_semanal.sort_values("ano_semana", inplace=True)
    st.markdown("### Tendência de Chamados por Semana")
    if not tendencia_semanal.empty:
        fig_semanal = px.line(tendencia_semanal, x="semana", y="qtd_semanal", markers=True, title="Chamados por Semana")
        st.plotly_chart(fig_semanal, use_container_width=True)
    else:
        st.info("Sem dados suficientes para exibir tendência semanal.")

####################################
# 3) Página de Abrir Chamado
####################################
def abrir_chamado_page():
    st.subheader("Abrir Chamado Técnico")
    patrimonio = st.text_input("Número de Patrimônio (opcional)")
    data_agendada = st.date_input("Data Agendada para Manutenção (opcional)")
    machine_info = None
    machine_type = None
    ubs_selecionada = None
    setor = None

    if patrimonio:
        machine_info = buscar_no_inventario_por_patrimonio(patrimonio)
        if machine_info:
            st.write(f"Máquina: {machine_info['tipo']} - {machine_info['marca']} {machine_info['modelo']}")
            st.write(f"UBS: {machine_info['localizacao']} | Setor: {machine_info['setor']}")
            ubs_selecionada = machine_info["localizacao"]
            setor = machine_info["setor"]
            machine_type = machine_info["tipo"]
        else:
            st.error("Patrimônio não encontrado. Cadastre a máquina antes.")
            st.stop()
    else:
        ubs_selecionada = st.selectbox("UBS", get_ubs_list())
        setor = st.selectbox("Setor", get_setores_list())
        machine_type = st.selectbox("Tipo de Máquina", ["Computador", "Impressora", "Outro"])

    if machine_type == "Computador":
        defect_options = [
            "Computador não liga", "Computador lento", "Tela azul", "Sistema travando",
            "Erro de disco", "Problema com atualização", "Desligamento inesperado",
            "Problema com internet", "Problema com Wi-Fi", "Sem conexão de rede",
            "Mouse não funciona", "Teclado não funciona"
        ]
    elif machine_type == "Impressora":
        defect_options = [
            "Impressora não imprime", "Impressão borrada", "Toner vazio",
            "Troca de toner", "Papel enroscado", "Erro de conexão com a impressora"
        ]
    else:
        defect_options = ["Solicitação de suporte geral", "Outros tipos de defeito"]

    tipo_defeito = st.selectbox("Tipo de Defeito/Solicitação", defect_options)
    problema = st.text_area("Descreva o problema ou solicitação")
    if st.button("Abrir Chamado"):
        agendamento = data_agendada.strftime('%d/%m/%Y') if data_agendada else None
        protocolo = add_chamado(
            st.session_state["username"],
            ubs_selecionada,
            setor,
            tipo_defeito,
            problema + (f" | Agendamento: {agendamento}" if agendamento else ""),
            patrimonio=patrimonio
        )
        if protocolo:
            st.success(f"Chamado aberto com sucesso! Protocolo: {protocolo}")
        else:
            st.error("Erro ao abrir chamado.")

####################################
# 4) Página de Buscar Chamado
####################################
def buscar_chamado_page():
    st.subheader("Buscar Chamado")
    protocolo = st.text_input("Informe o número de protocolo do chamado")
    if st.button("Buscar"):
        if protocolo:
            chamado = get_chamado_by_protocolo(protocolo)
            if chamado:
                st.write("Chamado encontrado:")
                exibir_chamado(chamado)
            else:
                st.error("Chamado não encontrado.")
        else:
            st.warning("Informe um protocolo.")

####################################
# 5) Página de Chamados Técnicos (Finalizar e Reabrir)
####################################
def chamados_tecnicos_page():
    st.subheader("Chamados Técnicos")
    chamados = list_chamados()
    if not chamados:
        st.write("Nenhum chamado técnico encontrado.")
        return

    df = pd.DataFrame(chamados)
    # Reordena colunas para mostrar protocolo antes de id
    if "protocolo" in df.columns and "id" in df.columns:
        nova_ordem = ["protocolo", "id"] + [col for col in df.columns if col not in ["protocolo", "id"]]
        df = df[nova_ordem]

    def calcula_tempo(row):
        if pd.notnull(row.get("hora_fechamento")):
            try:
                abertura = datetime.strptime(row["hora_abertura"], '%d/%m/%Y %H:%M:%S')
                fechamento = datetime.strptime(row["hora_fechamento"], '%d/%m/%Y %H:%M:%S')
                tempo_util = calculate_working_hours(abertura, fechamento)
                return str(tempo_util)
            except:
                return "Erro"
        else:
            return "Em aberto"

    df["Tempo Util"] = df.apply(calcula_tempo, axis=1)

    # Reordena para que "Tempo Util" apareça logo após "patrimonio"
    if "patrimonio" in df.columns:
        cols = list(df.columns)
        if "Tempo Util" in cols:
            cols.remove("Tempo Util")
        idx = cols.index("patrimonio")
        cols.insert(idx+1, "Tempo Util")
        df = df[cols]

    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(filter=True, sortable=True, resizable=True, wrapText=True, autoHeight=True, minColumnWidth=250, flex=1)
    gb.configure_column("problema", minColumnWidth=300)
    gb.configure_pagination(paginationAutoPageSize=False, paginationPageSize=10)
    grid_options = gb.build()
    grid_options['domLayout'] = 'normal'
    AgGrid(df, gridOptions=grid_options, enable_enterprise_modules=False, theme='streamlit', height=400)
    
    # Finalizar Chamado (para chamados em aberto)
    df_aberto = df[df["hora_fechamento"].isnull()]
    if df_aberto.empty:
        st.write("Não há chamados abertos para finalizar.")
    else:
        st.markdown("### Finalizar Chamado Técnico")
        chamado_id = st.selectbox("Selecione o ID do chamado para finalizar", df_aberto["id"].tolist())
        chamado = df_aberto[df_aberto["id"] == chamado_id].iloc[0]
        st.write(f"Problema: {chamado['problema']}")

        if "impressora" in chamado.get("tipo_defeito", "").lower():
            solucao_options = [
                "Limpeza e recalibração da impressora", "Substituição de cartucho/toner",
                "Verificação de conexão e drivers", "Reinicialização da impressora"
            ]
        else:
            solucao_options = [
                "Reinicialização do sistema",
                "Atualização de drivers/software",
                "Substituição de componente (ex.: SSD, Fonte, Memória)",
                "Verificação de vírus/malware",
                "Limpeza física e manutenção preventiva",
                "Reinstalação do sistema operacional",
                "Atualização do BIOS/firmware",
                "Verificação e limpeza de superaquecimento",
                "Otimização de configurações do sistema",
                "Reset da BIOS"
            ]
        solucao_selecionada = st.selectbox("Selecione a solução", solucao_options)
        solucao_complementar = st.text_area("Detalhes adicionais da solução (opcional)")
        solucao_final = solucao_selecionada + ((" - " + solucao_complementar) if solucao_complementar else "")
        comentarios = st.text_area("Comentários adicionais (opcional)")

        estoque_data = get_estoque()
        pieces_list = [item["nome"] for item in estoque_data] if estoque_data else []
        pecas_selecionadas = st.multiselect("Selecione as peças utilizadas (se houver)", pieces_list)

        if st.button("Finalizar Chamado"):
            if solucao_final:
                solucao_completa = solucao_final + (f" | Comentários: {comentarios}" if comentarios else "")
                finalizar_chamado(chamado_id, solucao_completa, pecas_usadas=pecas_selecionadas)
            else:
                st.error("Informe a solução para finalizar o chamado.")

    # Reabrir Chamado (para chamados fechados)
    df_fechado = df[df["hora_fechamento"].notnull()]
    if not df_fechado.empty:
        st.markdown("### Reabrir Chamado Técnico")
        chamado_fechado_id = st.selectbox("Selecione o ID do chamado para reabrir", df_fechado["id"].tolist())
        remover_hist = st.checkbox("Remover registro de manutenção criado no fechamento anterior?", value=False)
        if st.button("Reabrir Chamado"):
            reabrir_chamado(chamado_fechado_id, remover_historico=remover_hist)

####################################
# 6) Página de Inventário
####################################
def inventario_page():
    st.subheader("Inventário")
    menu_inventario = st.radio("Selecione uma opção:", ["Listar Inventário", "Cadastrar Máquina", "Dashboard Inventário"])
    if menu_inventario == "Listar Inventário":
        show_inventory_list()
    elif menu_inventario == "Cadastrar Máquina":
        cadastro_maquina()
    else:
        dashboard_inventario()

####################################
# 7) Página de Estoque
####################################
def estoque_page():
    manage_estoque()

####################################
# 8) Página de Administração
####################################
def administracao_page():
    st.subheader("Administração")
    admin_option = st.selectbox(
        "Opções de Administração",
        ["Cadastro de Usuário", "Gerenciar UBSs", "Gerenciar Setores", "Lista de Usuários" "Redefinir Senha de Usuário"]
    )
    if admin_option == "Cadastro de Usuário":
        novo_user = st.text_input("Novo Usuário")
        nova_senha = st.text_input("Senha", type="password")
        admin_flag = st.checkbox("Administrador")
        if st.button("Cadastrar Usuário"):
            if add_user(novo_user, nova_senha, admin_flag):
                st.success("Usuário cadastrado com sucesso!")
            else:
                st.error("Erro ao cadastrar usuário ou usuário já existe.")
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
            st.write("Nenhum usuário cadastrado.")
    elif admin_option == "Redefinir Senha de Usuário":
    alvo = st.selectbox("Selecione o usuário", [u for u, _ in list_users()])
    nova = st.text_input("Nova senha", type="password")
    if st.button("Alterar senha") and nova:
        ok = force_change_password(st.session_state["username"], alvo, nova)
        st.success("Senha redefinida!") if ok else st.error("Falha ao redefinir senha.")

####################################
# 9) Página de Relatórios
####################################
def relatorios_page():
    st.subheader("Relatórios Completos - Estatísticas")
    st.markdown("### Filtros para Chamados")
    col1, col2, col3 = st.columns(3)
    with col1:
        start_date = st.date_input("Data Início")
    with col2:
        end_date = st.date_input("Data Fim")
    with col3:
        filtro_ubs = st.multiselect("Filtrar por UBS", get_ubs_list())

    if start_date > end_date:
        st.error("Data Início não pode ser maior que Data Fim")
        return

    agora_fortaleza = datetime.now(FORTALEZA_TZ)
    st.markdown(f"**Horário local (Fortaleza):** {agora_fortaleza.strftime('%d/%m/%Y %H:%M:%S')}")

    chamados = list_chamados()
    if not chamados:
        st.write("Nenhum chamado técnico encontrado.")
        return

    df = pd.DataFrame(chamados)
    df["hora_abertura_dt"] = pd.to_datetime(df["hora_abertura"], format='%d/%m/%Y %H:%M:%S', errors='coerce')
    start_datetime = datetime.combine(start_date, datetime.min.time())
    end_datetime = datetime.combine(end_date, datetime.max.time())
    df_period = df[(df["hora_abertura_dt"] >= start_datetime) & (df["hora_abertura_dt"] <= end_datetime)]
    if filtro_ubs:
        df_period = df_period[df_period["ubs"].isin(filtro_ubs)]

    st.markdown("### Chamados Técnicos no Período")
    gb = GridOptionsBuilder.from_dataframe(df_period)
    gb.configure_default_column(filter=True, sortable=True)
    gb.configure_pagination(paginationAutoPageSize=True)
    gb.configure_grid_options(domLayout='normal')
    grid_options = gb.build()
    AgGrid(df_period, gridOptions=grid_options, height=400, fit_columns_on_grid_load=True)

    df_period["mes"] = df_period["hora_abertura_dt"].dt.to_period("M").astype(str)

    chamados_abertos = df_period[df_period["hora_fechamento"].isnull()].shape[0]
    chamados_fechados = df_period[df_period["hora_fechamento"].notnull()].shape[0]
    st.markdown(f"**Chamados Abertos (período):** {chamados_abertos}")
    st.markdown(f"**Chamados Fechados (período):** {chamados_fechados}")

    def tempo_resolucao(row):
        if pd.notnull(row["hora_fechamento"]):
            try:
                ab = datetime.strptime(row["hora_abertura"], '%d/%m/%Y %H:%M:%S')
                fe = datetime.strptime(row["hora_fechamento"], '%d/%m/%Y %H:%M:%S')
                delta = calculate_working_hours(ab, fe)
                return delta.total_seconds()
            except:
                return None
        else:
            return None

    df_period["tempo_resolucao_seg"] = df_period.apply(tempo_resolucao, axis=1)
    df_resolvidos = df_period.dropna(subset=["tempo_resolucao_seg"])
    if not df_resolvidos.empty:
        media_seg = df_resolvidos["tempo_resolucao_seg"].mean()
        horas = int(media_seg // 3600)
        minutos = int((media_seg % 3600) // 60)
        st.markdown(f"**Tempo Médio de Resolução (horas úteis):** {horas}h {minutos}m")
    else:
        st.write("Nenhum chamado finalizado no período para calcular tempo médio de resolução.")

    # Chamados por Tipo de Defeito
    if "tipo_defeito" in df_period.columns:
        chamados_tipo = df_period.groupby("tipo_defeito").size().reset_index(name="qtd")
        st.markdown("#### Chamados por Tipo de Defeito")
        st.dataframe(chamados_tipo)
        fig_tipo = px.bar(chamados_tipo, x="tipo_defeito", y="qtd", title="Chamados por Tipo de Defeito")
        fig_tipo.update_layout(xaxis_title="Tipo de Defeito", yaxis_title="Quantidade")
        st.plotly_chart(fig_tipo, use_container_width=True)

    # Chamados por UBS e Setor
    chamados_ubs_setor = df_period.groupby(["ubs", "setor"]).size().reset_index(name="qtd_chamados")
    st.markdown("#### Chamados por UBS e Setor")
    st.dataframe(chamados_ubs_setor)

    # Chamados por Dia da Semana (em português)
    if not df_period.empty:
        df_period["dia_semana_en"] = df_period["hora_abertura_dt"].dt.day_name()
        day_map = {
            'Monday': 'Segunda-feira',
            'Tuesday': 'Terça-feira',
            'Wednesday': 'Quarta-feira',
            'Thursday': 'Quinta-feira',
            'Friday': 'Sexta-feira',
            'Saturday': 'Sábado',
            'Sunday': 'Domingo'
        }
        df_period["dia_semana"] = df_period["dia_semana_en"].map(day_map)
        df_period.drop(columns=["dia_semana_en"], inplace=True)
        chamados_por_dia = df_period.groupby("dia_semana").size().reset_index(name="qtd")
        st.markdown("#### Chamados por Dia da Semana")
        st.dataframe(chamados_por_dia)

    # Chamados por UBS por Mês
    chamados_ubs_mes = df_period.groupby(["ubs", "mes"]).size().reset_index(name="qtd_chamados")
    st.markdown("#### Chamados por UBS por Mês")
    st.dataframe(chamados_ubs_mes)
    if not chamados_ubs_mes.empty:
        fig1 = px.line(chamados_ubs_mes, x="mes", y="qtd_chamados", color="ubs", markers=True,
                       title="Chamados por UBS por Mês")
        fig1.update_layout(xaxis_title="Mês", yaxis_title="Quantidade")
        st.plotly_chart(fig1, use_container_width=True)

    # Geração do PDF completo de chamados
    if st.button("Gerar Relatório Completo de Chamados em PDF"):
        df_chamados = df_period.copy()
        pdf = FPDF()
        pdf.add_page()
        pdf.image("infocustec.png", x=10, y=8, w=30)
        pdf.ln(35)
        pdf.set_font("Arial", "B", 16)
        pdf.cell(0, 10, "Relatório Completo de Chamados Técnicos", ln=True, align="C")
        pdf.ln(10)
        pdf.set_font("Arial", "", 10)
        for idx, row in df_chamados.iterrows():
            for col in df_chamados.columns:
                pdf.cell(0, 8, f'{col}: {row[col]}', ln=True)
            pdf.ln(5)

        pdf_output = pdf.output(dest="S")
        if isinstance(pdf_output, str):
            pdf_output = pdf_output.encode("latin-1")
        elif isinstance(pdf_output, bytearray):
            pdf_output = bytes(pdf_output)
        st.download_button(
            label="Baixar Relatório Completo de Chamados",
            data=pdf_output,
            file_name="relatorio_chamados_completo.pdf",
            mime="application/pdf"
        )

####################################
# 10) Página de Exportar Dados
####################################
def exportar_dados_page():
    st.subheader("Exportar Dados")
    st.markdown("### Exportar Chamados em CSV")
    chamados = list_chamados()
    if chamados:
        df_chamados = pd.DataFrame(chamados)
        csv_chamados = df_chamados.to_csv(index=False).encode("utf-8")
        st.download_button("Baixar Chamados CSV", data=csv_chamados, file_name="chamados.csv", mime="text/csv")
    else:
        st.write("Nenhum chamado para exportar.")

    st.markdown("### Exportar Inventário em CSV")
    inventario_data = get_machines_from_inventory()
    if inventario_data:
        df_inv = pd.DataFrame(inventario_data)
        csv_inv = df_inv.to_csv(index=False).encode("utf-8")
        st.download_button("Baixar Inventário CSV", data=csv_inv, file_name="inventario.csv", mime="text/csv")
    else:
        st.write("Nenhum item de inventário para exportar.")

####################################
# 11) Função Sair
####################################
def sair_page():
    st.session_state["logged_in"] = False
    st.session_state["username"] = ""
    st.success("Você saiu.")

####################################
# Mapeamento das Páginas
####################################
pages = {
    "Login": login_page,
    "Dashboard": dashboard_page,
    "Abrir Chamado": abrir_chamado_page,
    "Buscar Chamado": buscar_chamado_page,
    "Chamados Técnicos": chamados_tecnicos_page,
    "Inventário": inventario_page,
    "Estoque": estoque_page,
    "Administração": administracao_page,
    "Relatórios": relatorios_page,
    "Exportar Dados": exportar_dados_page,
    "Sair": sair_page
}

# Chama a página selecionada
if selected in pages:
    pages[selected]()
else:
    st.write("Página não encontrada.")

# Rodapé
st.markdown("---")
st.markdown("<center>© 2025 Infocustec. Todos os direitos reservados.</center>", unsafe_allow_html=True)
