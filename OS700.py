import os
import logging
import base64
from datetime import datetime, timedelta

import pytz
import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st
from fpdf import FPDF
from streamlit_option_menu import option_menu
from st_aggrid import AgGrid, GridOptionsBuilder, JsCode

# =========================
# Configs básicas
# =========================
FORTALEZA_TZ = pytz.timezone("America/Fortaleza")
logging.basicConfig(level=logging.INFO)

st.set_page_config(
    page_title="Gestão de Parque de Informática",
    page_icon="infocustec.png",
    layout="wide"
)

# =========================
# Módulos internos
# =========================
from autenticacao import authenticate, add_user, is_admin, list_users, force_change_password
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

# =========================
# Estado de sessão
# =========================
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
if "username" not in st.session_state:
    st.session_state["username"] = ""

# =========================
# CSS leve
# =========================
st.markdown(
    """
    <style>
    body { background-color: #F8FAFC; font-family: "Roboto", sans-serif; }
    h1, h2, h3 { color: #1F2937; }
    .css-1waiswl { background-color: #0275d8 !important; }
    </style>
    """,
    unsafe_allow_html=True
)

# =========================
# Logo
# =========================
logo_path = os.getenv("LOGO_PATH", "infocustec.png")
if os.path.exists(logo_path):
    with open(logo_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    st.markdown(
        f"""
        <div style="display:flex;justify-content:center;padding:10px;">
            <img src="data:image/png;base64,{b64}" style="height:80px;" />
        </div>
        """,
        unsafe_allow_html=True
    )
else:
    st.warning("Logotipo não encontrado.")

st.title("Gestão de Parque de Informática - APS ITAPIPOCA")

# =========================
# Helpers
# =========================
def exibir_chamado(chamado: dict):
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
            return ["Abrir Chamado", "Buscar Chamado", "Sair"]
    else:
        return ["Login"]

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
        "download",
        "box-arrow-right"
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

# =========================
# Página: Login
# =========================
def login_page():
    st.subheader("Login")
    username = st.text_input("Usuário")
    password = st.text_input("Senha", type="password")
    if st.button("Entrar", type="primary"):
        if not username or not password:
            st.error("Preencha todos os campos.")
        elif authenticate(username, password):
            st.success(f"Bem-vindo, {username}!")
            st.session_state["logged_in"] = True
            st.session_state["username"] = username
        else:
            st.error("Usuário ou senha incorretos.")

# =========================
# Página: Dashboard
# =========================
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

    # Atrasados (>48h úteis)
    atrasados = 0
    for c in chamados:
        if c.get("hora_fechamento") is None:
            try:
                abertura = datetime.strptime(c["hora_abertura"], '%d/%m/%Y %H:%M:%S')
                agora_local = datetime.now(FORTALEZA_TZ)
                tempo_util = calculate_working_hours(abertura, agora_local)
                if tempo_util > timedelta(hours=48):
                    atrasados += 1
            except:
                pass
    if atrasados:
        st.warning(f"Atenção: {atrasados} chamados abertos há mais de 48h úteis!")

    # Tendência Mensal
    df["mes"] = df["hora_abertura_dt"].dt.to_period("M").astype(str)
    tendencia_mensal = df.groupby("mes").size().reset_index(name="qtd_mensal")
    st.markdown("### Tendência de Chamados por Mês")
    if not tendencia_mensal.empty:
        fig_mensal = px.line(tendencia_mensal, x="mes", y="qtd_mensal", markers=True, title="Chamados por Mês")
        st.plotly_chart(fig_mensal, use_container_width=True)

    # Tendência Semanal
    df["semana"] = df["hora_abertura_dt"].dt.to_period("W").astype(str)
    tendencia_semanal = df.groupby("semana").size().reset_index(name="qtd_semanal")

    def parse_ano_semana(semana_str):
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

# =========================
# Página: Abrir Chamado
# =========================
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
    if st.button("Abrir Chamado", type="primary"):
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

# =========================
# Página: Buscar Chamado
# =========================
def buscar_chamado_page():
    st.subheader("Buscar Chamado")
    protocolo = st.text_input("Informe o número de protocolo do chamado")
    if st.button("Buscar", type="primary"):
        if protocolo:
            chamado = get_chamado_by_protocolo(protocolo)
            if chamado:
                st.write("Chamado encontrado:")
                exibir_chamado(chamado)
            else:
                st.error("Chamado não encontrado.")
        else:
            st.warning("Informe um protocolo.")

# =========================
# Página: Chamados Técnicos
# =========================
def chamados_tecnicos_page():
    st.subheader("Chamados Técnicos")

    # Filtros principais
    colf1, colf2, colf3 = st.columns([1.2, 1, 1])
    with colf1:
        mostrar = st.radio("Mostrar", ["Todos", "Somente em aberto"], index=0, horizontal=True)
    with colf2:
        apenas48 = st.toggle("Apenas >48h úteis", value=False)
    with colf3:
        priorizar48 = st.toggle("Priorizar >48h úteis", value=True)

    # Fonte de dados
    chamados = list_chamados_em_aberto() if mostrar == "Somente em aberto" else list_chamados()
    if not chamados:
        st.success("Sem chamados em aberto 🎉" if mostrar == "Somente em aberto" else "Nenhum chamado encontrado.")
        return

    df = pd.DataFrame(chamados)

    # Helpers de status/tempo
    def _eh_fechado(v):
        return (pd.notna(v)) and (str(v).strip().lower() not in ("none", ""))

    def _idade_uteis_h(row):
        try:
            ab = datetime.strptime(row["hora_abertura"], "%d/%m/%Y %H:%M:%S")
            if _eh_fechado(row.get("hora_fechamento")):
                fe = datetime.strptime(row["hora_fechamento"], "%d/%m/%Y %H:%M:%S")
                delta = calculate_working_hours(ab, fe)
            else:
                agora_local = datetime.now(FORTALEZA_TZ)
                delta = calculate_working_hours(ab, agora_local)
            return round(delta.total_seconds() / 3600.0, 2)
        except Exception:
            return None

    df["idade_uteis_h"] = df.apply(_idade_uteis_h, axis=1)

    # Flag >48h úteis
    df[">48h_uteis"] = df.apply(
        lambda r: (not _eh_fechado(r.get("hora_fechamento"))) and r.get("idade_uteis_h") is not None and r["idade_uteis_h"] > 48,
        axis=1
    )

    def _tempo_util_txt(row):
        try:
            ab = datetime.strptime(row["hora_abertura"], "%d/%m/%Y %H:%M:%S")
            if _eh_fechado(row.get("hora_fechamento")):
                fe = datetime.strptime(row["hora_fechamento"], "%d/%m/%Y %H:%M:%S")
                return str(calculate_working_hours(ab, fe))
            else:
                return "Em aberto"
        except Exception:
            return "Erro"

    df["Tempo Útil"] = df.apply(_tempo_util_txt, axis=1)

    # Filtro >48h
    if apenas48:
        df = df[df[">48h_uteis"] == True]

    # Ordenação
    if priorizar48 and not df.empty:
        df = df.sort_values(by=[">48h_uteis", "idade_uteis_h"], ascending=[False, False])
    else:
        if "hora_abertura" in df.columns:
            try:
                _ab = pd.to_datetime(df["hora_abertura"], format="%d/%m/%Y %H:%M:%S", errors="coerce")
                df = df.assign(_ab=_ab).sort_values("_ab", ascending=False).drop(columns=["_ab"])
            except Exception:
                pass

    # Métricas
    total = len(df)
    atrasados = int(df[">48h_uteis"].sum())
    c1, c2 = st.columns(2)
    c1.metric("Total listados", total)
    c2.metric("Abertos >48h úteis", atrasados)

    # Reorganiza colunas úteis primeiro
    prefer = [c for c in ["protocolo", "ubs", "setor", "tipo_defeito", "problema",
                          "hora_abertura", "Tempo Útil", "idade_uteis_h", ">48h_uteis", "hora_fechamento", "id"] if c in df.columns]
    others = [c for c in df.columns if c not in prefer]
    df = df[prefer + others].copy()

    # Tipos serializáveis pro AgGrid
    if "idade_uteis_h" in df.columns:
        df["idade_uteis_h"] = pd.to_numeric(df["idade_uteis_h"], errors="coerce")
    if ">48h_uteis" in df.columns:
        df[">48h_uteis"] = df[">48h_uteis"].fillna(False).astype(bool)
    if "Tempo Útil" in df.columns:
        df["Tempo Útil"] = df["Tempo Útil"].astype(str)

    # Grid
    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(filter=True, sortable=True, resizable=True, wrapText=True,
                                autoHeight=True, minColumnWidth=180, flex=1)
    gb.configure_column("problema", minColumnWidth=320)
    gb.configure_pagination(paginationAutoPageSize=False, paginationPageSize=10)

    # Destaque visual pra >48h
    get_row_style = JsCode("""
        function(params) {
            if (params.data && params.data[">48h_uteis"] === true) {
                return { 'background': '#ffe6e6' };
            }
            return null;
        }
    """)
    gb.configure_grid_options(getRowStyle=get_row_style)

    grid_options = gb.build()
    grid_options["domLayout"] = "normal"

    AgGrid(
        df,
        gridOptions=grid_options,
        enable_enterprise_modules=False,
        theme="streamlit",
        height=460,
        allow_unsafe_jscode=True,
    )

    # ===== Finalizar Chamado (por PROTOCOLO)
    if mostrar == "Somente em aberto":
        df_aberto = df.copy()
    else:
        df_aberto = df[df["Tempo Útil"] == "Em aberto"]

    if df_aberto.empty:
        st.write("Não há chamados abertos para finalizar.")
    else:
        st.markdown("### Finalizar Chamado Técnico")
        protos_abertos = df_aberto["protocolo"].astype(str).tolist() if "protocolo" in df_aberto.columns else []
        if protos_abertos:
            protocolo_escolhido = st.selectbox("Selecione o PROTOCOLO para finalizar", protos_abertos)
            sel = df_aberto[df_aberto["protocolo"].astype(str) == str(protocolo_escolhido)]
            if sel.empty:
                st.error("Protocolo não encontrado na lista atual.")
            else:
                row = sel.iloc[0]
                try:
                    chamado_id = int(row["id"]) if "id" in row and pd.notna(row["id"]) else None
                except Exception:
                    chamado_id = None

                st.write(f"Problema: {row.get('problema','(sem descrição)')}")

                # Opções de solução
                if "impressora" in str(row.get("tipo_defeito","")).lower():
                    solucao_options = [
                        "Limpeza e recalibração da impressora",
                        "Substituição de cartucho/toner",
                        "Verificação de conexão e drivers",
                        "Reinicialização da impressora"
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
                solucao_complementar = st.text_area("Detalhes adicionais (opcional)")
                comentarios = st.text_area("Comentários (opcional)")

                # Peças usadas
                estoque_data = get_estoque()
                pieces_list = [item["nome"] for item in estoque_data] if estoque_data else []
                pecas_selecionadas = st.multiselect("Peças utilizadas (se houver)", pieces_list)

                if st.button("Finalizar Chamado", type="primary"):
                    if not chamado_id:
                        st.error("Não foi possível identificar o ID interno do chamado.")
                    else:
                        solucao_final = solucao_selecionada + (f" - {solucao_complementar}" if solucao_complementar else "")
                        if comentarios:
                            solucao_final += f" | Comentários: {comentarios}"
                        finalizar_chamado(chamado_id, solucao_final, pecas_usadas=pecas_selecionadas)

    # ===== Reabrir Chamado (por PROTOCOLO) — somente quando mostrando “Todos”
    df_fechado = df[df["Tempo Útil"] != "Em aberto"] if mostrar == "Todos" else pd.DataFrame()
    if not df_fechado.empty and "protocolo" in df_fechado.columns:
        st.markdown("### Reabrir Chamado Técnico")
        protos_fechados = df_fechado["protocolo"].astype(str).tolist()
        protocolo_fechado = st.selectbox("Selecione o PROTOCOLO para reabrir", protos_fechados)
        sel_f = df_fechado[df_fechado["protocolo"].astype(str) == str(protocolo_fechado)]
        if not sel_f.empty:
            row_f = sel_f.iloc[0]
            try:
                chamado_fechado_id = int(row_f["id"]) if "id" in row_f and pd.notna(row_f["id"]) else None
            except Exception:
                chamado_fechado_id = None

            remover_hist = st.checkbox("Remover registro de manutenção criado no fechamento anterior?", value=False)
            if st.button("Reabrir Chamado"):
                if not chamado_fechado_id:
                    st.error("Não foi possível identificar o ID interno do chamado.")
                else:
                    reabrir_chamado(chamado_fechado_id, remover_historico=remover_hist)

# =========================
# Página: Inventário
# =========================
def inventario_page():
    st.subheader("Inventário")
    menu_inventario = st.radio("Selecione uma opção:", ["Listar Inventário", "Cadastrar Máquina", "Dashboard Inventário"])
    if menu_inventario == "Listar Inventário":
        show_inventory_list()
    elif menu_inventario == "Cadastrar Máquina":
        cadastro_maquina()
    else:
        dashboard_inventario()

# =========================
# Página: Estoque
# =========================
def estoque_page():
    manage_estoque()

# =========================
# Página: Administração
# =========================
def administracao_page():
    st.subheader("Administração")
    admin_option = st.selectbox(
        "Opções de Administração",
        ["Cadastro de Usuário", "Gerenciar UBSs", "Gerenciar Setores", "Lista de Usuários", "Redefinir Senha de Usuário"]
    )
    if admin_option == "Cadastro de Usuário":
        novo_user = st.text_input("Novo Usuário")
        nova_senha = st.text_input("Senha", type="password")
        admin_flag = st.checkbox("Administrador")
        if st.button("Cadastrar Usuário", type="primary"):
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
        usuarios = list_users()
        alvo = st.selectbox("Selecione o usuário", [u for u, _ in usuarios] if usuarios else [])
        nova = st.text_input("Nova senha", type="password")
        if st.button("Alterar senha", type="primary") and nova and alvo:
            ok = force_change_password(st.session_state["username"], alvo, nova)
            if ok:
                st.success("Senha redefinida!")
            else:
                st.error("Falha ao redefinir senha.")

# =========================
# Página: Relatórios (2.0)
# =========================
import io

def relatorios_page():
    st.subheader("Relatórios 2.0")

    # ---------- Filtros ----------
    col0, colA, colB, colC = st.columns([1,1,1,1])
    with col0:
        preset = st.selectbox(
            "Período rápido",
            ["Hoje", "Últimos 7 dias", "Últimos 30 dias", "Ano atual", "Tudo", "Personalizado"],
            index=2
        )
    with colA:
        sla_horas = st.number_input("SLA (horas úteis)", min_value=1, max_value=240, value=48, step=1)
    with colB:
        filtro_ubs = st.multiselect("UBS", get_ubs_list())
    with colC:
        try:
            filtro_setor = st.multiselect("Setor", get_setores_list())
        except Exception:
            filtro_setor = []

    hoje = datetime.now(FORTALEZA_TZ).date()
    if preset == "Hoje":
        start_date, end_date = hoje, hoje
    elif preset == "Últimos 7 dias":
        start_date, end_date = hoje - timedelta(days=6), hoje
    elif preset == "Últimos 30 dias":
        start_date, end_date = hoje - timedelta(days=29), hoje
    elif preset == "Ano atual":
        start_date, end_date = datetime(hoje.year, 1, 1).date(), hoje
    elif preset == "Tudo":
        start_date, end_date = datetime(2000, 1, 1).date(), hoje
    else:
        c1, c2 = st.columns(2)
        with c1:
            start_date = st.date_input("Data início", value=hoje - timedelta(days=29))
        with c2:
            end_date = st.date_input("Data fim", value=hoje)
        if start_date > end_date:
            st.error("Data início não pode ser maior que data fim.")
            return

    # ---------- Carrega chamados ----------
    chamados = list_chamados()
    if not chamados:
        st.info("Nenhum chamado encontrado.")
        return

    df = pd.DataFrame(chamados).copy()

    # Convertendo datas (strings dd/mm/yyyy HH:MM:SS)
    df["abertura_dt"] = pd.to_datetime(df["hora_abertura"], format="%d/%m/%Y %H:%M:%S", errors="coerce")
    df["fechamento_dt"] = pd.to_datetime(df["hora_fechamento"], format="%d/%m/%Y %H:%M:%S", errors="coerce")

    # Filtro por período (baseado na abertura)
    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date, datetime.max.time())
    df = df[(df["abertura_dt"] >= start_dt) & (df["abertura_dt"] <= end_dt)]

    # Filtros UBS/Setor
    if filtro_ubs:
        df = df[df["ubs"].isin(filtro_ubs)]
    if filtro_setor:
        df = df[df["setor"].isin(filtro_setor)]

    if df.empty:
        st.warning("Sem dados para os filtros selecionados.")
        return

    # ---------- Cálculos de SLA / tempos ----------
    def _tempo_uteis_seg(row):
        try:
            ab = datetime.strptime(row["hora_abertura"], "%d/%m/%Y %H:%M:%S")
            if pd.notna(row["fechamento_dt"]):
                fe = row["fechamento_dt"].to_pydatetime()
                delta = calculate_working_hours(ab, fe)
                return delta.total_seconds()
            return np.nan
        except Exception:
            return np.nan

    def _idade_uteis_h(row):
        try:
            ab = datetime.strptime(row["hora_abertura"], "%d/%m/%Y %H:%M:%S")
            fim = row["fechamento_dt"].to_pydatetime() if pd.notna(row["fechamento_dt"]) else datetime.now(FORTALEZA_TZ)
            delta = calculate_working_hours(ab, fim)
            return round(delta.total_seconds() / 3600.0, 2)
        except Exception:
            return np.nan

    df["tempo_uteis_seg"] = df.apply(_tempo_uteis_seg, axis=1)
    df["idade_uteis_h"] = df.apply(_idade_uteis_h, axis=1)
    df["em_aberto"] = df["fechamento_dt"].isna()
    df["dentro_sla"] = (~df["em_aberto"]) & (df["tempo_uteis_seg"] <= sla_horas * 3600)

    # ---------- KPIs ----------
    total = len(df)
    abertos = int(df["em_aberto"].sum())
    fechados = total - abertos

    tma_h = None
    mediana_h = None
    if fechados > 0:
        tma_h = (df.loc[~df["em_aberto"], "tempo_uteis_seg"].mean() or 0) / 3600
        mediana_h = (df.loc[~df["em_aberto"], "tempo_uteis_seg"].median() or 0) / 3600
    pct_sla = (df.loc[~df["em_aberto"], "dentro_sla"].mean() * 100) if fechados > 0 else 0.0
    backlog_sla = int(((df["em_aberto"]) & (df["idade_uteis_h"] > sla_horas)).sum())

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Total", total)
    k2.metric("Abertos", abertos)
    k3.metric("Fechados", fechados)
    k4.metric("TMA (média útil)", f"{tma_h:.1f} h" if tma_h is not None else "—")
    k5.metric("% dentro do SLA", f"{pct_sla:.0f}%")

    st.caption(f"Backlog acima do SLA: **{backlog_sla}** chamados (> {sla_horas}h úteis).")

    st.divider()

    # ---------- Tendências ----------
    colT1, colT2 = st.columns(2)
    with colT1:
        st.markdown("**Aberturas por semana**")
        df["semana"] = df["abertura_dt"].dt.to_period("W").astype(str)
        sem_ab = df.groupby("semana").size().reset_index(name="qtd")
        if not sem_ab.empty:
            fig1 = px.line(sem_ab, x="semana", y="qtd", markers=True)
            st.plotly_chart(fig1, use_container_width=True)
        else:
            st.info("Sem dados.")

    with colT2:
        st.markdown("**Fechamentos por semana**")
        tmp = df.dropna(subset=["fechamento_dt"]).copy()
        tmp["semana"] = tmp["fechamento_dt"].dt.to_period("W").astype(str)
        sem_fe = tmp.groupby("semana").size().reset_index(name="qtd")
        if not sem_fe.empty:
            fig2 = px.line(sem_fe, x="semana", y="qtd", markers=True)
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("Sem dados.")

    st.divider()

    # ---------- Heatmap: Dia x Hora das aberturas ----------
    st.markdown("**Heatmap de Aberturas (dia x hora)**")
    mapa = df.copy()
    mapa["dia_semana"] = mapa["abertura_dt"].dt.day_name()
    mapa["hora"] = mapa["abertura_dt"].dt.hour
    ordem = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
    nomes_pt = {
        "Monday":"Segunda","Tuesday":"Terça","Wednesday":"Quarta",
        "Thursday":"Quinta","Friday":"Sexta","Saturday":"Sábado","Sunday":"Domingo"
    }
    mapa["dia_semana"] = pd.Categorical(mapa["dia_semana"], categories=ordem, ordered=True)
    heat = mapa.pivot_table(index="dia_semana", columns="hora", values="id", aggfunc="count", fill_value=0)
    heat.index = [nomes_pt[str(x)] for x in heat.index]
    if not heat.empty:
        fig_hm = px.imshow(heat, aspect="auto", title="", labels=dict(x="Hora do dia", y="Dia da semana", color="Aberturas"))
        st.plotly_chart(fig_hm, use_container_width=True)
    else:
        st.info("Sem dados para heatmap.")

    st.divider()

    # ---------- Ranking UBS / Setor ----------
    colR1, colR2 = st.columns(2)
    with colR1:
        st.markdown("**Top UBS (aberturas)**")
        if "ubs" in df.columns:
            top_ubs = df.groupby("ubs").size().reset_index(name="qtd").sort_values("qtd", ascending=False).head(15)
            st.dataframe(top_ubs, use_container_width=True)
            fig_ubs = px.bar(top_ubs, x="ubs", y="qtd")
            fig_ubs.update_layout(xaxis_title=None, yaxis_title="Chamados")
            st.plotly_chart(fig_ubs, use_container_width=True)
        else:
            st.info("Coluna 'ubs' não encontrada.")

    with colR2:
        st.markdown("**Top Setores (aberturas)**")
        if "setor" in df.columns:
            top_setor = df.groupby("setor").size().reset_index(name="qtd").sort_values("qtd", ascending=False).head(15)
            st.dataframe(top_setor, use_container_width=True)
            fig_setor = px.bar(top_setor, x="setor", y="qtd")
            fig_setor.update_layout(xaxis_title=None, yaxis_title="Chamados")
            st.plotly_chart(fig_setor, use_container_width=True)
        else:
            st.info("Coluna 'setor' não encontrada.")

    st.divider()

    # ---------- Pivot UBS x Mês ----------
    st.markdown("**UBS x Mês (aberturas)**")
    df["mes"] = df["abertura_dt"].dt.to_period("M").astype(str)
    if "ubs" in df.columns:
        pvt = df.pivot_table(index="ubs", columns="mes", values="id", aggfunc="count", fill_value=0)
        st.dataframe(pvt, use_container_width=True)
    else:
        st.info("Coluna 'ubs' não encontrada.")

    st.divider()

    # ---------- Exportações ----------
    st.markdown("### Exportar dados filtrados")
    # CSV
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    st.download_button("Baixar CSV", data=csv_bytes, file_name="chamados_filtrados.csv", mime="text/csv")

    # Excel com abas úteis
    with io.BytesIO() as buffer:
        with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
            df.to_excel(writer, index=False, sheet_name="Chamados")
            if 'top_ubs' in locals():
                top_ubs.to_excel(writer, index=False, sheet_name="Top_UBS")
            if 'top_setor' in locals():
                top_setor.to_excel(writer, index=False, sheet_name="Top_Setores")
            if 'sem_ab' in locals():
                sem_ab.to_excel(writer, index=False, sheet_name="Aberturas_Semana")
            if 'sem_fe' in locals():
                sem_fe.to_excel(writer, index=False, sheet_name="Fechamentos_Semana")
            if 'pvt' in locals():
                pvt.to_excel(writer, sheet_name="Pivot_UBS_Mes")
        xlsx_data = buffer.getvalue()
    st.download_button("Baixar Excel", data=xlsx_data, file_name="relatorio_chamados.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# =========================
# Página: Exportar Dados
# =========================
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

# =========================
# Página: Sair
# =========================
def sair_page():
    st.session_state["logged_in"] = False
    st.session_state["username"] = ""
    st.success("Você saiu.")

# =========================
# Roteamento
# =========================
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

if selected in pages:
    pages[selected]()
else:
    st.write("Página não encontrada.")

# =========================
# Rodapé
# =========================
st.markdown("---")
st.markdown("<center>© 2025 Infocustec. Todos os direitos reservados.</center>", unsafe_allow_html=True)
