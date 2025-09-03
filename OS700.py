# os700.py — App de Itapipoca (layout moderno + IA + mapa + "Aguardando peça")

import os
import io
import base64
from datetime import datetime, timedelta

import pytz
import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder, JsCode
from streamlit_option_menu import option_menu

# =========================
# Configurações básicas
# =========================
FORTALEZA_TZ = pytz.timezone("America/Fortaleza")

st.set_page_config(
    page_title="OS700 - Itapipoca",
    page_icon="🛠️",
    layout="wide"
)

# Remove a barra azul do cabeçalho padrão do Streamlit
st.markdown("""
<style>
[data-testid="stHeader"] { background: transparent !important; }
body { background:#F5F7FB !important; }
.glass {
  background: rgba(255,255,255,0.65);
  border-radius: 18px;
  box-shadow: 0 10px 30px rgba(31,41,55,0.08);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border: 1px solid rgba(255,255,255,0.4);
  padding: 26px 22px;
}
.h-title { font-weight:800; color:#1F2937; letter-spacing:.2px; }
.stTextInput>div>div>input, .stPassword>div>div>input { height:46px; border-radius:12px; }
.stButton>button[kind="primary"] { border-radius:12px; height:44px; font-weight:700; }
ul[role="tablist"] li a { border-radius:10px !important; }
</style>
""", unsafe_allow_html=True)

# =========================
# Imports dos seus módulos
# =========================
# Autenticação
from autenticacao import authenticate, add_user, is_admin, list_users, force_change_password

# Chamados e utilidades
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

# Inventário
from inventario import (
    show_inventory_list,
    cadastro_maquina,
    get_machines_from_inventory,
    dashboard_inventario
)

# Cadastros auxiliares
from ubs import get_ubs_list  # se sua tabela tiver lat/lon, o mapa usa via Supabase diretamente
from setores import get_setores_list

# Estoque
from estoque import manage_estoque, get_estoque

# IA (NLQ)
from ai_nlq_ai import answer_question, ia_available

# Fallback Supabase direto (usado apenas para "aguardando peça" se chamados.py não tiver as funções)
try:
    from chamados import marcar_aguardando_peca, remover_aguardando_peca, atribuir_tecnico
    _has_waiting_api = True
except Exception:
    _has_waiting_api = False
    try:
        from supabase_client import supabase
    except Exception:
        supabase = None

# =========================
# Estado de sessão
# =========================
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
if "username" not in st.session_state:
    st.session_state["username"] = ""

# =========================
# Logo (opcional)
# =========================
logo_path = os.getenv("LOGO_PATH", "infocustec.png")
if os.path.exists(logo_path):
    with open(logo_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    st.markdown(
        f"""
        <div style="display:flex;justify-content:center;padding:8px 0 2px;">
            <img src="data:image/png;base64,{b64}" style="height:64px;" />
        </div>
        """,
        unsafe_allow_html=True
    )

st.title("OS700 — Gestão de Chamados • Itapipoca")

# =========================
# Helpers
# =========================
def _navbar_items():
    if st.session_state["logged_in"]:
        items = [
            {"label":"Pergunte com IA","icon":"question-circle"},
            {"label":"Dashboard","icon":"speedometer"},
            {"label":"Abrir Chamado","icon":"plus-circle"},
            {"label":"Buscar Chamado","icon":"search"},
            {"label":"Chamados Técnicos","icon":"card-list"},
            {"label":"Inventário","icon":"display"},
            {"label":"Relatórios","icon":"bar-chart"},
            {"label":"Exportar Dados","icon":"download"},
            {"label":"Estoque","icon":"box-seam"},
            {"label":"Administração","icon":"gear"},
            {"label":"Sair","icon":"box-arrow-right"}
        ]
        # Se quiser esconder itens para não-admins, ajuste aqui usando is_admin(st.session_state["username"])
        return items
    else:
        return [{"label":"Login","icon":"person-circle"}]

def _navbar_render():
    items = _navbar_items()
    options = [i["label"] for i in items]
    icons = [i["icon"] for i in items]
    styles_optionmenu = {
        "container": {"padding":"5!important","background-color":"#F5F7FB"},
        "icon": {"color":"#6B7280","font-size":"18px"},
        "nav-link": {"font-size":"16px","text-align":"center","margin":"0px","color":"#111827","padding":"10px"},
        "nav-link-selected": {"background-color":"#E5E7EB","color":"#111827","font-weight":"bold"},
    }
    selected = option_menu(
        menu_title=None,
        options=options,
        icons=icons,
        orientation="horizontal",
        styles=styles_optionmenu,
    )
    return selected or ("Login" if not st.session_state.get("logged_in") else "Abrir Chamado")

def _eh_fechado(v):
    return (pd.notna(v)) and (str(v).strip().lower() not in ("none", ""))

def _parse_dt(s):
    return pd.to_datetime(s, format="%d/%m/%Y %H:%M:%S", errors="coerce")

def _lista_tecnicos():
    # tenta derivar técnicos dos usuários; ajuste conforme sua realidade
    try:
        users = list_users()  # [(username, is_admin_bool), ...] — se for diferente, ajuste
        nomes = [u for u, _ in users] if users else []
        # opcional: filtrar por algum padrão (ex: prefixo "tec_")
        return nomes
    except Exception:
        return []

def _get_ubs_geo_dict():
    """
    Busca lat/lon das UBS direto na tabela 'ubs' do Supabase (se disponível).
    Retorna dict: { "UBS Nome": {"lat": -3.12, "lon": -39.58}, ... }
    """
    if supabase is None:
        return {}
    try:
        resp = supabase.table("ubs").select("*").execute()
        out = {}
        for r in resp.data or []:
            name = r.get("nome") or r.get("ubs") or r.get("descricao")
            lat = r.get("lat") or r.get("latitude")
            lon = r.get("lon") or r.get("longitude")
            if name and lat and lon:
                out[str(name).strip()] = {"lat": float(lat), "lon": float(lon)}
        return out
    except Exception:
        return {}

# Fallbacks "Aguardando peça" caso chamados.py ainda não tenha as funções
def _fallback_marcar_aguardando_peca(chamado_id: int, peca: str, tecnico: str):
    if supabase is None:
        st.error("Supabase indisponível para marcar 'Aguardando peça'.")
        return False
    try:
        supabase.table("chamados").update({
            "aguardando_peca": True,
            "peca_necessaria": peca,
            "tecnico_atribuido": tecnico
        }).eq("id", chamado_id).execute()
        return True
    except Exception as e:
        st.error(f"Não foi possível marcar 'Aguardando peça' (crie as colunas aguardando_peca, peca_necessaria, tecnico_atribuido na tabela chamados). Erro: {e}")
        return False

def _fallback_remover_aguardando_peca(chamado_id: int):
    if supabase is None:
        st.error("Supabase indisponível para atualizar 'Aguardando peça'.")
        return False
    try:
        supabase.table("chamados").update({
            "aguardando_peca": False,
            "peca_necessaria": None
        }).eq("id", chamado_id).execute()
        return True
    except Exception as e:
        st.error(f"Não foi possível remover 'Aguardando peça'. Erro: {e}")
        return False

def _fallback_atribuir_tecnico(chamado_id: int, tecnico: str):
    if supabase is None:
        st.error("Supabase indisponível para atribuir técnico.")
        return False
    try:
        supabase.table("chamados").update({
            "tecnico_atribuido": tecnico
        }).eq("id", chamado_id).execute()
        return True
    except Exception as e:
        st.error(f"Não foi possível atribuir técnico. Erro: {e}")
        return False

# =========================
# Páginas
# =========================
def login_page():
    st.markdown('<h2 class="h-title">Login</h2>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1,1.2,1])
    with c2:
        st.markdown('<div class="glass">', unsafe_allow_html=True)
        with st.form("form_login", clear_on_submit=False):
            username = st.text_input("Usuário")
            password = st.text_input("Senha", type="password")
            colA, colB = st.columns([1,1])
            entrar = colA.form_submit_button("Entrar", type="primary")
            lembrar = colB.checkbox("Lembrar-me", value=False)
        if entrar:
            if not username or not password:
                st.error("Preencha todos os campos.")
            elif authenticate(username, password):
                st.success(f"Bem-vindo, {username}!")
                st.session_state["logged_in"] = True
                st.session_state["username"] = username
                st.experimental_rerun()
            else:
                st.error("Usuário ou senha incorretos.")
        st.markdown('</div>', unsafe_allow_html=True)

def pergunte_com_ia_page():
    st.subheader("Pergunte com IA")
    st.caption(("🟢 IA disponível" if ia_available() else "⚪ IA não configurada — respostas padrão ativas"))
    st.caption("Exemplos: 'qual chamado em aberto mais antigo?', 'abertos acima de 72h', 'abertos por ubs', 'buscar toner na SEDE II', 'resuma os chamados'.")

    q = st.text_input("Sua pergunta")
    col1, col2 = st.columns(2)
    if col1.button("Responder", type="primary") and q:
        chamados = list_chamados()
        if not chamados:
            st.info("Sem dados.")
        else:
            r = answer_question(chamados, q)
            st.markdown(r.get("markdown",""))
            tb = r.get("table")
            if isinstance(tb, pd.DataFrame) and not tb.empty:
                # novo API do Streamlit: width="stretch"
                st.dataframe(tb, width="stretch")

    if col2.button("Resumo IA dos dados atuais"):
        chamados = list_chamados()
        if not chamados:
            st.info("Sem dados.")
        else:
            r = answer_question(chamados, "resuma os chamados")
            st.markdown(r.get("markdown",""))

def dashboard_page():
    st.subheader("Dashboard — Itapipoca")
    agora_fortaleza = datetime.now(FORTALEZA_TZ)
    st.caption(f"Horário local: {agora_fortaleza.strftime('%d/%m/%Y %H:%M:%S')}")

    chamados = list_chamados()
    if not chamados:
        st.info("Nenhum chamado.")
        return

    df = pd.DataFrame(chamados)
    df["abertura_dt"] = _parse_dt(df["hora_abertura"])
    df["fechamento_dt"] = _parse_dt(df["hora_fechamento"]) if "hora_fechamento" in df.columns else pd.NaT

    total = len(df)
    abertos = df["fechamento_dt"].isna().sum()
    fechados = total - abertos

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total", total)
    c2.metric("Abertos", int(abertos))
    c3.metric("Fechados", int(fechados))

    # Atrasados (>48h úteis)
    atrasados = 0
    for _, c in df[df["fechamento_dt"].isna()].iterrows():
        try:
            ab = datetime.strptime(c["hora_abertura"], "%d/%m/%Y %H:%M:%S")
            tempo_util = calculate_working_hours(ab, agora_fortaleza)
            if tempo_util > timedelta(hours=48):
                atrasados += 1
        except Exception:
            pass
    c4.metric(">48h úteis (abertos)", atrasados)

    st.divider()

    # Tendência mensal
    try:
        df["mes"] = df["abertura_dt"].dt.to_period("M").astype(str)
        trend = df.groupby("mes").size().reset_index(name="qtd")
        if not trend.empty:
            fig = px.line(trend, x="mes", y="qtd", markers=True, title="Chamados por mês")
            st.plotly_chart(fig, width="stretch")
    except Exception:
        pass

    st.divider()

    # Mapa de chamados em aberto (usa lat/lon da tabela ubs se disponível)
    st.markdown("### Chamados em aberto no mapa")
    geo = _get_ubs_geo_dict()
    df_open = df[df["fechamento_dt"].isna()].copy()
    if not df_open.empty and geo:
        def _coord_row(row):
            u = str(row.get("ubs","")).strip()
            return pd.Series(geo.get(u, {}))
        df_open[["lat","lon"]] = df_open.apply(_coord_row, axis=1)
        df_map = df_open.dropna(subset=["lat","lon"])
        if not df_map.empty:
            st.map(df_map[["lat","lon"]], size=10, use_container_width=True)
            st.caption("Pinos baseados em lat/lon cadastrados na tabela 'ubs'.")
        else:
            st.info("Sem coordenadas para as UBS dos chamados em aberto.")
    else:
        st.info("Para ver o mapa, cadastre colunas 'lat' e 'lon' na tabela 'ubs'.")

def abrir_chamado_page():
    st.subheader("Abrir Chamado Técnico")
    patrimonio = st.text_input("Número de Patrimônio (opcional)")
    data_agendada = st.date_input("Data agendada (opcional)")
    machine_info = None
    ubs_sel = None
    setor_sel = None
    tipo_maquina = None

    if patrimonio:
        machine_info = buscar_no_inventario_por_patrimonio(patrimonio)
        if machine_info:
            st.info(f"Máquina: {machine_info['tipo']} • {machine_info['marca']} {machine_info['modelo']} • "
                    f"UBS: {machine_info['localizacao']} • Setor: {machine_info['setor']}")
            ubs_sel = machine_info["localizacao"]
            setor_sel = machine_info["setor"]
            tipo_maquina = machine_info["tipo"]
        else:
            st.error("Patrimônio não encontrado no inventário.")
            st.stop()
    else:
        ubs_sel = st.selectbox("UBS", get_ubs_list())
        setor_sel = st.selectbox("Setor", get_setores_list())
        tipo_maquina = st.selectbox("Tipo de Máquina", ["Computador", "Impressora", "Outro"])

    if tipo_maquina == "Computador":
        defect_options = [
            "Computador não liga", "Computador lento", "Tela azul", "Sistema travando",
            "Erro de disco", "Problema com atualização", "Desligamento inesperado",
            "Problema com internet", "Problema com Wi-Fi", "Sem conexão de rede",
            "Mouse não funciona", "Teclado não funciona"
        ]
    elif tipo_maquina == "Impressora":
        defect_options = [
            "Impressora não imprime", "Impressão borrada", "Toner vazio",
            "Troca de toner", "Papel enroscado", "Erro de conexão com a impressora"
        ]
    else:
        defect_options = ["Solicitação de suporte geral", "Outro"]

    tipo_defeito = st.selectbox("Tipo de Defeito/Solicitação", defect_options)
    problema = st.text_area("Descreva o problema")
    if st.button("Abrir Chamado", type="primary"):
        ag = data_agendada.strftime('%d/%m/%Y') if data_agendada else None
        txt = problema + (f" | Agendamento: {ag}" if ag else "")
        protocolo = add_chamado(
            st.session_state["username"],
            ubs_sel,
            setor_sel,
            tipo_defeito,
            txt,
            patrimonio=patrimonio
        )
        if protocolo:
            st.success(f"Chamado criado. Protocolo: {protocolo}")

def buscar_chamado_page():
    st.subheader("Buscar Chamado")
    protocolo = st.text_input("Protocolo")
    if st.button("Buscar", type="primary") and protocolo:
        ch = get_chamado_by_protocolo(protocolo)
        if not ch:
            st.error("Chamado não encontrado.")
            return
        _exibir_chamado(ch)

def _exibir_chamado(chamado: dict):
    st.markdown("### Detalhes do Chamado")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"**ID:** {chamado.get('id','')}")
        st.markdown(f"**Usuário:** {chamado.get('username','')}")
        st.markdown(f"**UBS:** {chamado.get('ubs','')}")
        st.markdown(f"**Setor:** {chamado.get('setor','')}")
        st.markdown(f"**Protocolo:** {chamado.get('protocolo','')}")
    with c2:
        st.markdown(f"**Tipo de Defeito:** {chamado.get('tipo_defeito','')}")
        st.markdown(f"**Problema:** {chamado.get('problema','')}")
        st.markdown(f"**Abertura:** {chamado.get('hora_abertura','')}")
        st.markdown(f"**Fechamento:** {chamado.get('hora_fechamento','Em aberto')}")
    # campos opcionais (se existirem)
    aguard = chamado.get("aguardando_peca")
    if aguard is True:
        st.warning(f"Aguardando peça: {chamado.get('peca_necessaria','(não informado)')} • Técnico: {chamado.get('tecnico_atribuido','(não informado)')}")

def chamados_tecnicos_page():
    st.subheader("Chamados Técnicos")

    colf1, colf2, colf3 = st.columns([1.2, 1, 1])
    with colf1:
        mostrar = st.radio("Mostrar", ["Todos", "Somente em aberto"], horizontal=True, index=0)
    with colf2:
        apenas48 = st.toggle("Apenas >48h úteis", value=False)
    with colf3:
        priorizar48 = st.toggle("Priorizar >48h úteis", value=True)

    chamados = list_chamados_em_aberto() if mostrar == "Somente em aberto" else list_chamados()
    if not chamados:
        st.success("Sem chamados para exibir.")
        return

    df = pd.DataFrame(chamados)
    df["idade_uteis_h"] = _calc_idade_uteis_h_df(df)
    df[">48h_uteis"] = df.apply(
        lambda r: (not _eh_fechado(r.get("hora_fechamento"))) and pd.notna(r.get("idade_uteis_h")) and r["idade_uteis_h"] > 48,
        axis=1
    )
    df["Tempo Útil"] = df.apply(_tempo_util_txt_row, axis=1)

    if apenas48:
        df = df[df[">48h_uteis"] == True]

    if priorizar48 and not df.empty:
        df = df.sort_values(by=[">48h_uteis", "idade_uteis_h"], ascending=[False, False])
    else:
        if "hora_abertura" in df.columns:
            _ab = _parse_dt(df["hora_abertura"])
            df = df.assign(_ab=_ab).sort_values("_ab", ascending=False).drop(columns=["_ab"])

    total = len(df)
    atrasados = int(df[">48h_uteis"].sum())
    c1, c2 = st.columns(2)
    c1.metric("Total listados", total)
    c2.metric("Abertos >48h úteis", atrasados)

    prefer = [c for c in ["protocolo","ubs","setor","tipo_defeito","problema","hora_abertura","Tempo Útil","idade_uteis_h",">48h_uteis","hora_fechamento","id","aguardando_peca","peca_necessaria","tecnico_atribuido"] if c in df.columns]
    others = [c for c in df.columns if c not in prefer]
    df = df[prefer + others].copy()

    if "idade_uteis_h" in df.columns:
        df["idade_uteis_h"] = pd.to_numeric(df["idade_uteis_h"], errors="coerce")
    if ">48h_uteis" in df.columns:
        df[">48h_uteis"] = df[">48h_uteis"].fillna(False).astype(bool)
    if "Tempo Útil" in df.columns:
        df["Tempo Útil"] = df["Tempo Útil"].astype(str)

    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(filter=True, sortable=True, resizable=True, wrapText=True, autoHeight=True, minColumnWidth=180, flex=1)
    gb.configure_column("problema", minColumnWidth=320)
    gb.configure_pagination(paginationAutoPageSize=False, paginationPageSize=10)
    get_row_style = JsCode("""
        function(params) {
            if (params.data && params.data[">48h_uteis"] === true) {
                return { 'background': '#ffe6e6' };
            }
            if (params.data && params.data["aguardando_peca"] === true) {
                return { 'background': '#fff6e5' };
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

    # ---- Ações de item único (por PROTOCOLO) ----
    st.markdown("### Ações em Chamado")
    df_abertos = df[df["Tempo Útil"] == "Em aberto"] if mostrar == "Todos" else df.copy()
    protos = df_abertos["protocolo"].astype(str).tolist() if "protocolo" in df_abertos.columns else []
    if not protos:
        st.info("Nenhum chamado em aberto para ação.")
        return

    protocolo_escolhido = st.selectbox("Selecione o PROTOCOLO", protos)
    row_sel = df_abertos[df_abertos["protocolo"].astype(str) == str(protocolo_escolhido)]
    if row_sel.empty:
        st.error("Protocolo não encontrado.")
        return
    row = row_sel.iloc[0]
    chamado_id = int(row["id"]) if "id" in row and pd.notna(row["id"]) else None
    if not chamado_id:
        st.error("ID interno do chamado não identificado.")
        return

    st.write(f"**Problema:** {row.get('problema','(sem descrição)')}")

    # Atribuir técnico
    st.markdown("#### Atribuir técnico")
    tecs = _lista_tecnicos()
    tecnico_escolhido = st.selectbox("Técnico responsável", tecs, index=tecs.index(row.get("tecnico_atribuido")) if row.get("tecnico_atribuido") in tecs else 0 if tecs else None)
    if st.button("Atribuir", key="btn_atribuir"):
        ok = False
        if _has_waiting_api:
            try:
                ok = atribuir_tecnico(chamado_id, tecnico_escolhido)
            except Exception as e:
                st.error(f"Falha ao atribuir técnico via chamados.py: {e}")
        if not ok:
            ok = _fallback_atribuir_tecnico(chamado_id, tecnico_escolhido)
        if ok:
            st.success("Técnico atribuído.")

    # Marcar/Desmarcar Aguardando peça
    st.markdown("#### Status de peça")
    estoque_data = get_estoque()
    peca_opts = [item["nome"] for item in estoque_data] if estoque_data else []
    colp1, colp2 = st.columns(2)
    with colp1:
        peca_sel = st.selectbox("Peça necessária", peca_opts, index=peca_opts.index(row.get("peca_necessaria")) if row.get("peca_necessaria") in peca_opts else 0 if peca_opts else None)
    with colp2:
        aguardando_atual = bool(row.get("aguardando_peca")) if "aguardando_peca" in row else False
        st.write(f"Status atual: {'Aguardando peça' if aguardando_atual else 'Sem pendência de peça'}")

    cbtn1, cbtn2 = st.columns(2)
    if cbtn1.button("Marcar 'Aguardando peça'"):
        ok = False
        if _has_waiting_api:
            try:
                ok = marcar_aguardando_peca(chamado_id, peca_sel, tecnico_escolhido)
            except Exception as e:
                st.error(f"Falha via chamados.py: {e}")
        if not ok:
            ok = _fallback_marcar_aguardando_peca(chamado_id, peca_sel, tecnico_escolhido)
        if ok:
            st.success("Status atualizado para 'Aguardando peça'.")

    if cbtn2.button("Remover status 'Aguardando peça'"):
        ok = False
        if _has_waiting_api:
            try:
                ok = remover_aguardando_peca(chamado_id)
            except Exception as e:
                st.error(f"Falha via chamados.py: {e}")
        if not ok:
            ok = _fallback_remover_aguardando_peca(chamado_id)
        if ok:
            st.success("Status 'Aguardando peça' removido.")

    st.markdown("#### Finalizar chamado")
    if "impressora" in str(row.get("tipo_defeito","")).lower():
        solucao_options = [
            "Limpeza e recalibração da impressora",
            "Substituição de cartucho/toner",
            "Verificação de conexão e drivers",
            "Reinicialização da impressora",
            "Placa em curto/Sem conserto",
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
    solucao_selecionada = st.selectbox("Solução aplicada", solucao_options)
    solucao_complementar = st.text_area("Detalhes adicionais (opcional)")
    comentarios = st.text_area("Comentários (opcional)")
    # peças usadas no fechamento (estoque)
    pecas_list = [item["nome"] for item in get_estoque()] if get_estoque() else []
    pecas_usadas = st.multiselect("Peças utilizadas no fechamento", pecas_list)

    if st.button("Finalizar", type="primary"):
        solucao_final = solucao_selecionada + (f" - {solucao_complementar}" if solucao_complementar else "")
        if comentarios:
            solucao_final += f" | Comentários: {comentarios}"
        try:
            finalizar_chamado(chamado_id, solucao_final, pecas_usadas=pecas_usadas)
        except Exception as e:
            st.error(f"Falha ao finalizar: {e}")

    # Reabrir (se fechado)
    df_fechado = df[df["Tempo Útil"] != "Em aberto"]
    if not df_fechado.empty and "protocolo" in df_fechado.columns:
        st.markdown("#### Reabrir chamado")
        protos_fechados = df_fechado["protocolo"].astype(str).tolist()
        proto_f = st.selectbox("Protocolo fechado", protos_fechados)
        if st.button("Reabrir"):
            row_f = df_fechado[df_fechado["protocolo"].astype(str) == str(proto_f)].iloc[0]
            try:
                id_f = int(row_f["id"]) if pd.notna(row_f["id"]) else None
            except Exception:
                id_f = None
            if not id_f:
                st.error("ID interno não identificado.")
            else:
                try:
                    reabrir_chamado(id_f, remover_historico=False)
                except Exception as e:
                    st.error(f"Falha ao reabrir: {e}")

def _calc_idade_uteis_h_df(df: pd.DataFrame):
    def _calc(row):
        try:
            ab = datetime.strptime(row["hora_abertura"], "%d/%m/%Y %H:%M:%S")
            if _eh_fechado(row.get("hora_fechamento")):
                fe = datetime.strptime(row["hora_fechamento"], "%d/%m/%Y %H:%M:%S")
                delta = calculate_working_hours(ab, fe)
            else:
                delta = calculate_working_hours(ab, datetime.now(FORTALEZA_TZ))
            return round(delta.total_seconds() / 3600.0, 2)
        except Exception:
            return np.nan
    return df.apply(_calc, axis=1)

def _tempo_util_txt_row(row):
    try:
        ab = datetime.strptime(row["hora_abertura"], "%d/%m/%Y %H:%M:%S")
        if _eh_fechado(row.get("hora_fechamento")):
            fe = datetime.strptime(row["hora_fechamento"], "%d/%m/%Y %H:%M:%S")
            return str(calculate_working_hours(ab, fe))
        else:
            return "Em aberto"
    except Exception:
        return "Erro"

def inventario_page():
    st.subheader("Inventário")
    menu = st.radio("Escolha:", ["Listar Inventário", "Cadastrar Máquina", "Dashboard Inventário"], horizontal=True)
    if menu == "Listar Inventário":
        show_inventory_list()
    elif menu == "Cadastrar Máquina":
        cadastro_maquina()
    else:
        dashboard_inventario()

def relatorios_page():
    st.subheader("Relatórios")
    hoje = datetime.now(FORTALEZA_TZ).date()
    preset = st.selectbox("Período", ["Hoje","Últimos 7 dias","Últimos 30 dias","Ano atual","Tudo","Personalizado"], index=2)
    if preset == "Hoje":
        start_date, end_date = hoje, hoje
    elif preset == "Últimos 7 dias":
        start_date, end_date = hoje - timedelta(days=6), hoje
    elif preset == "Últimos 30 dias":
        start_date, end_date = hoje - timedelta(days=29), hoje
    elif preset == "Ano atual":
        start_date, end_date = datetime(hoje.year,1,1).date(), hoje
    elif preset == "Tudo":
        start_date, end_date = datetime(2000,1,1).date(), hoje
    else:
        c1, c2 = st.columns(2)
        with c1: start_date = st.date_input("Início", value=hoje - timedelta(days=29))
        with c2: end_date   = st.date_input("Fim", value=hoje)
        if start_date > end_date:
            st.error("Data início não pode ser maior que data fim.")
            return

    sla_horas = st.number_input("SLA (horas úteis)", min_value=1, max_value=240, value=48, step=1)
    filtro_ubs = st.multiselect("UBS", get_ubs_list())
    try:
        filtro_setor = st.multiselect("Setor", get_setores_list())
    except Exception:
        filtro_setor = []

    data = list_chamados()
    if not data:
        st.info("Sem dados.")
        return

    df = pd.DataFrame(data)
    df["abertura_dt"] = _parse_dt(df["hora_abertura"])
    df["fechamento_dt"] = _parse_dt(df["hora_fechamento"]) if "hora_fechamento" in df.columns else pd.NaT

    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt   = datetime.combine(end_date,   datetime.max.time())
    df = df[(df["abertura_dt"] >= start_dt) & (df["abertura_dt"] <= end_dt)]

    if filtro_ubs:
        df = df[df["ubs"].isin(filtro_ubs)]
    if filtro_setor:
        df = df[df["setor"].isin(filtro_setor)]

    if df.empty:
        st.warning("Sem dados para os filtros.")
        return

    def _tempo_uteis_seg(row):
        try:
            ab = datetime.strptime(row["hora_abertura"], "%d/%m/%Y %H:%M:%S")
            if pd.notna(row["fechamento_dt"]):
                fe = row["fechamento_dt"].to_pydatetime()
                return calculate_working_hours(ab, fe).total_seconds()
            return np.nan
        except Exception:
            return np.nan

    def _idade_uteis_h(row):
        try:
            ab = datetime.strptime(row["hora_abertura"], "%d/%m/%Y %H:%M:%S")
            fim = row["fechamento_dt"].to_pydatetime() if pd.notna(row["fechamento_dt"]) else datetime.now(FORTALEZA_TZ)
            return round(calculate_working_hours(ab, fim).total_seconds()/3600.0, 2)
        except Exception:
            return np.nan

    df["tempo_uteis_seg"] = df.apply(_tempo_uteis_seg, axis=1)
    df["idade_uteis_h"]   = df.apply(_idade_uteis_h, axis=1)
    df["em_aberto"]       = df["fechamento_dt"].isna()
    df["dentro_sla"]      = (~df["em_aberto"]) & (df["tempo_uteis_seg"] <= sla_horas * 3600)

    total = len(df)
    abertos = int(df["em_aberto"].sum())
    fechados = total - abertos
    tma_h = (df.loc[~df["em_aberto"], "tempo_uteis_seg"].mean() or 0) / 3600 if fechados > 0 else None
    pct_sla = (df.loc[~df["em_aberto"], "dentro_sla"].mean() * 100) if fechados > 0 else 0.0
    backlog_sla = int(((df["em_aberto"]) & (df["idade_uteis_h"] > sla_horas)).sum())

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Total", total)
    k2.metric("Abertos", abertos)
    k3.metric("Fechados", fechados)
    k4.metric("TMA (útil)", f"{tma_h:.1f} h" if tma_h is not None else "—")
    k5.metric("% dentro do SLA", f"{pct_sla:.0f}%")
    st.caption(f"Backlog acima do SLA: **{backlog_sla}** chamados (> {sla_horas}h úteis).")

    st.divider()
    st.markdown("**Aberturas por semana**")
    df["semana"] = df["abertura_dt"].dt.to_period("W").astype(str)
    sem_ab = df.groupby("semana").size().reset_index(name="qtd")
    if not sem_ab.empty:
        st.plotly_chart(px.line(sem_ab, x="semana", y="qtd", markers=True), width="stretch")

    st.markdown("**Fechamentos por semana**")
    tmp = df.dropna(subset=["fechamento_dt"]).copy()
    tmp["semana"] = tmp["fechamento_dt"].dt.to_period("W").astype(str)
    sem_fe = tmp.groupby("semana").size().reset_index(name="qtd")
    if not sem_fe.empty:
        st.plotly_chart(px.line(sem_fe, x="semana", y="qtd", markers=True), width="stretch")

    st.divider()
    st.markdown("**Top UBS**")
    if "ubs" in df.columns:
        top_ubs = df.groupby("ubs").size().reset_index(name="qtd").sort_values("qtd", ascending=False).head(15)
        st.dataframe(top_ubs, width="stretch")
        st.plotly_chart(px.bar(top_ubs, x="ubs", y="qtd"), width="stretch")

    st.markdown("**Top Setores**")
    if "setor" in df.columns:
        top_setor = df.groupby("setor").size().reset_index(name="qtd").sort_values("qtd", ascending=False).head(15)
        st.dataframe(top_setor, width="stretch")
        st.plotly_chart(px.bar(top_setor, x="setor", y="qtd"), width="stretch")

    st.divider()
    st.markdown("**Exportar dados filtrados**")
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    st.download_button("Baixar CSV", data=csv_bytes, file_name="chamados_filtrados.csv", mime="text/csv")

    # Excel (openpyxl/xlsxwriter)
    import importlib
    engine = None
    for cand in ("openpyxl", "xlsxwriter"):
        if importlib.util.find_spec(cand):
            engine = "openpyxl" if cand == "openpyxl" else "xlsxwriter"
            break
    if engine:
        with io.BytesIO() as buffer:
            with pd.ExcelWriter(buffer, engine=engine) as writer:
                df.to_excel(writer, index=False, sheet_name="Chamados")
                if 'top_ubs' in locals():
                    top_ubs.to_excel(writer, index=False, sheet_name="Top_UBS")
                if 'top_setor' in locals():
                    top_setor.to_excel(writer, index=False, sheet_name="Top_Setores")
                if 'sem_ab' in locals():
                    sem_ab.to_excel(writer, index=False, sheet_name="Aberturas_Semana")
                if 'sem_fe' in locals():
                    sem_fe.to_excel(writer, index=False, sheet_name="Fechamentos_Semana")
            xlsx_data = buffer.getvalue()
        st.download_button("Baixar Excel", data=xlsx_data, file_name="relatorio_chamados.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        st.caption("Instale openpyxl ou xlsxwriter para exportar Excel. CSV já disponível.")

def exportar_dados_page():
    st.subheader("Exportar Dados")
    st.markdown("### Chamados")
    data = list_chamados()
    if data:
        df = pd.DataFrame(data)
        st.dataframe(df.head(200), width="stretch")
        st.download_button("Baixar CSV", df.to_csv(index=False).encode("utf-8"), "chamados.csv", "text/csv")
    else:
        st.info("Sem chamados.")

    st.markdown("### Inventário")
    inv = get_machines_from_inventory()
    if inv:
        df2 = pd.DataFrame(inv)
        st.dataframe(df2.head(200), width="stretch")
        st.download_button("Baixar CSV", df2.to_csv(index=False).encode("utf-8"), "inventario.csv", "text/csv")
    else:
        st.info("Sem inventário.")

def inventario_wrapper_page():
    inventario_page()

def estoque_page():
    manage_estoque()

def administracao_page():
    st.subheader("Administração")
    admin_option = st.selectbox(
        "Opções",
        ["Cadastro de Usuário", "Lista de Usuários", "Redefinir Senha de Usuário"]
    )
    if admin_option == "Cadastro de Usuário":
        novo_user = st.text_input("Novo Usuário")
        nova_senha = st.text_input("Senha", type="password")
        admin_flag = st.checkbox("Administrador")
        if st.button("Cadastrar Usuário", type="primary"):
            if add_user(novo_user, nova_senha, admin_flag):
                st.success("Usuário cadastrado.")
            else:
                st.error("Erro ao cadastrar ou usuário já existe.")
    elif admin_option == "Lista de Usuários":
        usuarios = list_users()
        if usuarios:
            st.table(usuarios)
        else:
            st.info("Nenhum usuário.")
    elif admin_option == "Redefinir Senha de Usuário":
        usuarios = list_users()
        alvo = st.selectbox("Usuário", [u for u, _ in usuarios] if usuarios else [])
        nova = st.text_input("Nova senha", type="password")
        if st.button("Alterar senha", type="primary") and nova and alvo:
            ok = force_change_password(st.session_state["username"], alvo, nova)
            if ok:
                st.success("Senha redefinida.")
            else:
                st.error("Falha ao redefinir.")

def sair_page():
    st.session_state["logged_in"] = False
    st.session_state["username"] = ""
    st.success("Você saiu.")

# =========================
# Roteamento por NavBar
# =========================
label_to_func = {
    "Login": login_page,
    "Pergunte com IA": pergunte_com_ia_page,
    "Dashboard": dashboard_page,
    "Abrir Chamado": abrir_chamado_page,
    "Buscar Chamado": buscar_chamado_page,
    "Chamados Técnicos": chamados_tecnicos_page,
    "Inventário": inventario_wrapper_page,
    "Relatórios": relatorios_page,
    "Exportar Dados": exportar_dados_page,
    "Estoque": estoque_page,
    "Administração": administracao_page,
    "Sair": sair_page
}

selected_label = _navbar_render()
label_to_func.get(selected_label, login_page)()

# =========================
# Rodapé
# =========================
st.markdown("---")
st.markdown("<center>© 2025 APS Itapipoca — OS700</center>", unsafe_allow_html=True)
