# inventario.py — organizado, sem fotos, com PDF/Excel/CSV
import io
import os
from datetime import datetime
import pandas as pd
import numpy as np
import pytz
import streamlit as st
import matplotlib.pyplot as plt
from st_aggrid import AgGrid, GridOptionsBuilder, JsCode
from fpdf import FPDF

from supabase_client import supabase
from setores import get_setores_list
from ubs import get_ubs_list

FORTALEZA_TZ = pytz.timezone("America/Fortaleza")

# =====================================================
# 1) Acesso ao banco
# =====================================================
def get_machines_from_inventory():
    """
    Lê a tabela public.inventario com os campos usados no app.
    """
    try:
        resp = supabase.table("inventario").select(
            "id,numero_patrimonio,tipo,marca,modelo,numero_serie,status,localizacao,propria_locada,setor,data_aquisicao,data_garantia_fim"
        ).execute()
        return resp.data if resp.data else []
    except Exception as e:
        st.error("Erro ao recuperar inventário.")
        print(f"Erro: {e}")
        return []

def edit_inventory_item(patrimonio, new_values):
    try:
        supabase.table("inventario").update(new_values).eq("numero_patrimonio", patrimonio).execute()
        st.success("Item atualizado com sucesso!")
    except Exception as e:
        st.error("Erro ao atualizar o item do inventário.")
        print(f"Erro: {e}")

def add_machine_to_inventory(
    tipo, marca, modelo, numero_serie, status, localizacao,
    propria_locada, patrimonio, setor,
    data_aquisicao=None, data_garantia_fim=None
):
    try:
        # evita duplicidade por patrimonio
        resp = supabase.table("inventario").select("numero_patrimonio").eq("numero_patrimonio", patrimonio).execute()
        if resp.data:
            st.error(f"Máquina com patrimônio {patrimonio} já existe no inventário.")
            return
        data = {
            "numero_patrimonio": patrimonio,
            "tipo": tipo,
            "marca": marca,
            "modelo": modelo,
            "numero_serie": numero_serie or None,
            "status": status,
            "localizacao": localizacao,
            "propria_locada": propria_locada,
            "setor": setor,
            "data_aquisicao": data_aquisicao,
            "data_garantia_fim": data_garantia_fim,
        }
        supabase.table("inventario").insert(data).execute()
        st.success("Máquina adicionada ao inventário com sucesso!")
    except Exception as e:
        st.error("Erro ao adicionar máquina ao inventário.")
        print(f"Erro: {e}")

def delete_inventory_item(patrimonio):
    try:
        supabase.table("inventario").delete().eq("numero_patrimonio", patrimonio).execute()
        st.success("Item excluído com sucesso!")
    except Exception as e:
        st.error("Erro ao excluir item do inventário.")
        print(f"Erro: {e}")

# =====================================================
# 2) Integrações com chamados / peças / manutenção
# =====================================================
def get_pecas_usadas_por_patrimonio(patrimonio):
    try:
        mod = __import__("chamados", fromlist=["get_chamados_por_patrimonio"])
        get_chamados_por_patrimonio = mod.get_chamados_por_patrimonio
    except Exception as e:
        st.error("Erro ao importar função de chamados.")
        print(f"Erro: {e}")
        return []
    chamados = get_chamados_por_patrimonio(patrimonio)
    if not chamados:
        return []
    chamado_ids = [ch["id"] for ch in chamados if "id" in ch]
    try:
        if not chamado_ids:
            return []
        resp = supabase.table("pecas_usadas").select("*").in_("chamado_id", chamado_ids).execute()
        return resp.data if resp.data else []
    except Exception as e:
        st.error("Erro ao recuperar peças utilizadas.")
        print(f"Erro: {e}")
        return []

def get_historico_manutencao_por_patrimonio(patrimonio):
    try:
        resp = supabase.table("historico_manutencao").select("*").eq("numero_patrimonio", patrimonio).execute()
        return resp.data if resp.data else []
    except Exception as e:
        st.error("Erro ao buscar histórico de manutenção.")
        print(f"Erro: {e}")
        return []

# =====================================================
# 3) Cadastro / Edição (layout limpo, sem fotos)
# =====================================================
def cadastro_maquina():
    st.subheader("Cadastrar / Atualizar Máquina")

    tab1, tab2, tab3 = st.tabs(["Básico", "Configuração", "Compra/Docs"])

    with tab1:
        c1, c2, c3 = st.columns(3)
        with c1:
            patrimonio = st.text_input("Número de Patrimônio*")
        with c2:
            tipo = st.selectbox("Tipo*", ["Computador", "Impressora", "Monitor", "Nobreak", "Outro"])
        with c3:
            status = st.selectbox("Status", ["Ativo", "Em Manutencao", "Inativo"], index=0)

        c4, c5, c6 = st.columns(3)
        with c4:
            marca = st.text_input("Marca")
        with c5:
            modelo = st.text_input("Modelo")
        with c6:
            numero_serie = st.text_input("Número de Série (Opcional)")

        c7, c8 = st.columns(2)
        with c7:
            localizacao = st.selectbox("Localização (UBS)", sorted(get_ubs_list()))
        with c8:
            setor = st.selectbox("Setor", sorted(get_setores_list()))

        propria_locada = st.selectbox("Propriedade", ["Propria", "Locada"], index=0)
        st.caption("* Campos obrigatórios")

    with tab2:
        st.caption("Campos de configuração (opcional).")
        # se no futuro quiser hostname/ip/etc., adicionar aqui
        pass

    with tab3:
        colA, colB = st.columns(2)
        with colA:
            data_aquisicao = st.date_input("Data de Aquisição", value=None, format="DD/MM/YYYY")
        with colB:
            data_garantia_fim = st.date_input("Garantia até", value=None, format="DD/MM/YYYY")

    colS, colU, colD = st.columns([1,1,1])
    salvar = colS.button("Salvar novo", type="primary")
    atualizar = colU.button("Atualizar existente")
    limpar = colD.button("Limpar formulário")

    if limpar:
        st.experimental_rerun()

    payload = {
        "numero_patrimonio": patrimonio.strip(),
        "tipo": tipo,
        "marca": (marca or "").strip() or None,
        "modelo": (modelo or "").strip() or None,
        "numero_serie": (numero_serie or "").strip() or None,
        "status": status,
        "localizacao": localizacao,
        "propria_locada": propria_locada,
        "setor": setor,
        "data_aquisicao": str(data_aquisicao) if data_aquisicao else None,
        "data_garantia_fim": str(data_garantia_fim) if data_garantia_fim else None,
    }

    if salvar:
        if not payload["numero_patrimonio"]:
            st.error("Informe o Número de Patrimônio.")
        else:
            add_machine_to_inventory(**{
                "tipo": payload["tipo"],
                "marca": payload["marca"],
                "modelo": payload["modelo"],
                "numero_serie": payload["numero_serie"],
                "status": payload["status"],
                "localizacao": payload["localizacao"],
                "propria_locada": payload["propria_locada"],
                "patrimonio": payload["numero_patrimonio"],
                "setor": payload["setor"],
                "data_aquisicao": payload["data_aquisicao"],
                "data_garantia_fim": payload["data_garantia_fim"],
            })

    if atualizar:
        if not payload["numero_patrimonio"]:
            st.error("Informe o Número de Patrimônio para atualizar.")
        else:
            edit_inventory_item(payload["numero_patrimonio"], payload)

# =====================================================
# 4) Lista com filtros + exportações + PDF
# =====================================================
def show_inventory_list():
    st.subheader("Inventário — Lista e Filtros")

    # Filtros
    filtro_texto = st.text_input("Busca (patrimônio, marca, modelo, UBS, setor...)")
    colf1, colf2, colf3 = st.columns(3)
    with colf1:
        status_filtro = st.selectbox("Status", ["Todos", "Ativo", "Em Manutencao", "Inativo"])
    with colf2:
        localizacao_filtro = st.selectbox("UBS", ["Todas"] + sorted(get_ubs_list()))
    with colf3:
        setor_filtro = st.selectbox("Setor", ["Todos"] + sorted(get_setores_list()))

    # Carrega
    machines = get_machines_from_inventory()
    if not machines:
        st.info("Nenhum item encontrado no inventário.")
        return

    df = pd.DataFrame(machines).copy()

    # Busca global
    if filtro_texto:
        q = filtro_texto.lower()
        df = df[df.apply(lambda r: q in str(r).lower(), axis=1)]

    # Filtros específicos
    if status_filtro != "Todos":
        df = df[df["status"] == status_filtro]
    if localizacao_filtro != "Todas":
        df = df[df["localizacao"] == localizacao_filtro]
    if setor_filtro != "Todos":
        df = df[df["setor"] == setor_filtro]

    # Formatação datas
    if "data_aquisicao" in df:
        df["data_aquisicao"] = pd.to_datetime(df["data_aquisicao"], errors="coerce").dt.date.astype("string")
    if "data_garantia_fim" in df:
        df["data_garantia_fim"] = pd.to_datetime(df["data_garantia_fim"], errors="coerce").dt.date.astype("string")

    st.markdown("### Resultado (filtrado)")

    if df.empty:
        st.warning("Nenhum resultado com esses filtros.")
        return

    # KPIs leves
    total = len(df)
    k1, k2, k3 = st.columns(3)
    k1.metric("Itens", total)
    if "status" in df.columns:
        k2.metric("Ativos", int((df["status"] == "Ativo").sum()))
        k3.metric("Em Manutenção", int((df["status"] == "Em Manutencao").sum()))
    else:
        k2.metric("Ativos", "-")
        k3.metric("Em Manutenção", "-")

    # Ordem de colunas
    prefer = [c for c in [
        "numero_patrimonio","tipo","marca","modelo","status","localizacao","setor",
        "propria_locada","data_aquisicao","data_garantia_fim"
    ] if c in df.columns]
    others = [c for c in df.columns if c not in prefer]
    dfv = df[prefer + others].copy()

    # Tabela com destaque por status
    gb = GridOptionsBuilder.from_dataframe(dfv)
    gb.configure_default_column(filter=True, sortable=True, resizable=True, wrapText=True, autoHeight=True, minColumnWidth=140, flex=1)
    gb.configure_column("numero_patrimonio", pinned="left", minColumnWidth=170)
    gb.configure_pagination(paginationAutoPageSize=False, paginationPageSize=20)

    row_style = JsCode("""
        function(params) {
            const s = (params.data && params.data.status) ? (''+params.data.status).toLowerCase() : '';
            if (s === 'em manutencao') return { 'background': '#fff3cd' }; // amarelo
            if (s === 'inativo') return { 'background': '#f8d7da' };      // vermelho
            return null;
        }
    """)
    gb.configure_grid_options(getRowStyle=row_style)
    grid_options = gb.build()
    grid_options["domLayout"] = "normal"

    AgGrid(
        dfv,
        gridOptions=grid_options,
        height=460,
        theme="streamlit",
        enable_enterprise_modules=False,
        allow_unsafe_jscode=True
    )

    # Exportações
    st.markdown("### Exportar")
    csv_bytes = dfv.to_csv(index=False).encode("utf-8")
    st.download_button("Baixar CSV", data=csv_bytes, file_name="inventario_filtrado.csv", mime="text/csv")

    # Excel (fallback engine)
    import importlib
    engine = None
    for cand in ("openpyxl", "xlsxwriter"):
        if importlib.util.find_spec(cand):
            engine = "openpyxl" if cand == "openpyxl" else "xlsxwriter"
            break
    if engine:
        with io.BytesIO() as buffer:
            with pd.ExcelWriter(buffer, engine=engine) as writer:
                dfv.to_excel(writer, index=False, sheet_name="Inventario")
            st.download_button(
                "Baixar Excel",
                data=buffer.getvalue(),
                file_name="inventario_filtrado.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
    else:
        st.caption("Instale openpyxl ou xlsxwriter para exportar Excel.")

    # PDF
    if st.button("Gerar PDF do Inventário"):
        pdf_bytes = gerar_relatorio_inventario_pdf(dfv)
        st.download_button(
            label="Baixar Relatório de Inventário",
            data=pdf_bytes,
            file_name="inventario.pdf",
            mime="application/pdf"
        )

    # Edição / Exclusão
    st.markdown("---")
    st.subheader("Detalhes / Edição de Item")

    patrimonio_options = dfv["numero_patrimonio"].dropna().unique().tolist()
    selected_patrimonio = st.selectbox("Selecione o patrimônio", ["—"] + patrimonio_options)
    if selected_patrimonio and selected_patrimonio != "—":
        item = dfv[dfv["numero_patrimonio"] == selected_patrimonio].fillna("").iloc[0]

        with st.expander("Editar Máquina"):
            with st.form("editar_maquina"):
                tipo_options = ["Computador", "Impressora", "Monitor", "Nobreak", "Outro"]
                tipo_index = tipo_options.index(item["tipo"]) if item.get("tipo") in tipo_options else 0
                tipo = st.selectbox("Tipo", tipo_options, index=tipo_index)

                marca = st.text_input("Marca", value=item.get("marca", ""))
                modelo = st.text_input("Modelo", value=item.get("modelo", ""))
                numero_serie = st.text_input("Número de Série", value=item.get("numero_serie", ""))

                status_opts = ["Ativo", "Em Manutencao", "Inativo"]
                status_index = status_opts.index(item["status"]) if item.get("status") in status_opts else 0
                status = st.selectbox("Status", status_opts, index=status_index)

                ubs_list_sorted = sorted(get_ubs_list())
                loc_index = ubs_list_sorted.index(item["localizacao"]) if item.get("localizacao") in ubs_list_sorted else 0
                localizacao = st.selectbox("UBS", ubs_list_sorted, index=loc_index)

                setores_list_sorted = sorted(get_setores_list())
                setor_index = setores_list_sorted.index(item["setor"]) if item.get("setor") in setores_list_sorted else 0
                setor = st.selectbox("Setor", setores_list_sorted, index=setor_index)

                propria_options = ["Propria", "Locada"]
                propria_index = propria_options.index(item["propria_locada"]) if item.get("propria_locada") in propria_options else 0
                propria_locada = st.selectbox("Propriedade", propria_options, index=propria_index)

                submit = st.form_submit_button("Salvar Alterações")
                if submit:
                    new_values = {
                        "tipo": tipo,
                        "marca": marca or None,
                        "modelo": modelo or None,
                        "numero_serie": numero_serie or None,
                        "status": status,
                        "localizacao": localizacao,
                        "setor": setor,
                        "propria_locada": propria_locada,
                    }
                    edit_inventory_item(selected_patrimonio, new_values)

        with st.expander("Excluir Máquina"):
            if st.button("Excluir este item"):
                delete_inventory_item(selected_patrimonio)

        with st.expander("Histórico da Máquina"):
            st.markdown("**Chamados Técnicos:**")
            try:
                mod = __import__("chamados", fromlist=["get_chamados_por_patrimonio"])
                get_chamados_por_patrimonio = mod.get_chamados_por_patrimonio
            except Exception as e:
                st.error("Erro ao importar função de chamados.")
                print(f"Erro: {e}")
                get_chamados_por_patrimonio = lambda x: []
            chamados_ = get_chamados_por_patrimonio(selected_patrimonio)
            if chamados_:
                st.dataframe(pd.DataFrame(chamados_))
            else:
                st.write("Nenhum chamado técnico para este item.")

            st.markdown("**Peças Utilizadas:**")
            pecas = get_pecas_usadas_por_patrimonio(selected_patrimonio)
            if pecas:
                st.dataframe(pd.DataFrame(pecas))
            else:
                st.write("Nenhuma peça registrada para este item.")

            st.markdown("**Histórico de Manutenção:**")
            historico_manut = get_historico_manutencao_por_patrimonio(selected_patrimonio)
            if historico_manut:
                st.dataframe(pd.DataFrame(historico_manut))
            else:
                st.write("Sem registros de manutenção.")

# =====================================================
# 5) Dashboard do Inventário (sem imagens)
# =====================================================
def dashboard_inventario():
    st.subheader("Dashboard do Inventário")

    data = get_machines_from_inventory()
    if not data:
        st.info("Nenhum item no inventário.")
        return
    df = pd.DataFrame(data)

    # KPIs
    total = len(df)
    k1,k2,k3 = st.columns(3)
    k1.metric("Total de Itens", total)
    if "status" in df.columns:
        k2.metric("Ativos", int((df["status"] == "Ativo").sum()))
        k3.metric("Em Manutenção", int((df["status"] == "Em Manutencao").sum()))
    else:
        k2.metric("Ativos", "-")
        k3.metric("Em Manutenção", "-")

    # Gráficos simples
    if "localizacao" in df.columns:
        by_ubs = df.groupby("localizacao").size().reset_index(name="qtd").sort_values("qtd", ascending=False).head(15)
        st.plotly_chart(
            __import__("plotly.express").express.bar(by_ubs, x="localizacao", y="qtd", title="Itens por UBS"),
            use_container_width=True
        )
    if "setor" in df.columns:
        by_setor = df.groupby("setor").size().reset_index(name="qtd").sort_values("qtd", ascending=False).head(15)
        st.plotly_chart(
            __import__("plotly.express").express.bar(by_setor, x="setor", y="qtd", title="Itens por Setor"),
            use_container_width=True
        )
    if "tipo" in df.columns:
        by_tipo = df.groupby("tipo").size().reset_index(name="qtd").sort_values("qtd", ascending=False)
        st.plotly_chart(
            __import__("plotly.express").express.pie(by_tipo, names="tipo", values="qtd", title="Distribuição por Tipo"),
            use_container_width=True
        )

# =====================================================
# 6) PDF
# =====================================================
class PDF(FPDF):
    def __init__(self, orientation="L", unit="mm", format="A4", logo_path="infocustec.png"):
        super().__init__(orientation, unit, format)
        self.logo_path = logo_path

    def header(self):
        if os.path.exists(self.logo_path):
            self.image(self.logo_path, x=10, y=8, w=30)
            self.set_xy(45, 10)
        else:
            self.set_xy(10, 10)
        self.set_font("Arial", "B", 14)
        self.cell(0, 10, "Relatório de Inventário", ln=True, align="L")
        self.set_font("Arial", "", 10)
        agora = datetime.now(FORTALEZA_TZ).strftime("%d/%m/%Y %H:%M")
        self.cell(0, 8, f"Gerado em: {agora}", ln=True)
        self.ln(2)

    def footer(self):
        self.set_y(-15)
        self.set_font("Arial", "I", 10)
        self.cell(0, 10, f"Página {self.page_no()}", 0, 0, "C")

def gerar_relatorio_inventario_pdf(df_inventario: pd.DataFrame) -> bytes:
    """
    Gera PDF com:
      - Cabeçalho (logo opcional + data)
      - Resumo (contagens por status)
      - Tabela com colunas chave
    """
    pdf = PDF(orientation="L", format="A4", logo_path="infocustec.png")
    pdf.add_page()
    pdf.set_font("Arial", "", 10)

    # Resumo
    total = len(df_inventario)
    ativos = int((df_inventario["status"] == "Ativo").sum()) if "status" in df_inventario.columns else 0
    manut = int((df_inventario["status"] == "Em Manutencao").sum()) if "status" in df_inventario.columns else 0
    inat = int((df_inventario["status"] == "Inativo").sum()) if "status" in df_inventario.columns else 0

    pdf.set_font("Arial", "", 11)
    pdf.cell(0, 8, f"Total de itens: {total} | Ativos: {ativos} | Em Manutenção: {manut} | Inativos: {inat}", ln=True)
    pdf.ln(3)

    # Tabela
    cols = [c for c in ["numero_patrimonio","tipo","marca","modelo","status","localizacao","setor","data_aquisicao","data_garantia_fim"] if c in df_inventario.columns]
    headers = {
        "numero_patrimonio":"Patrimônio","tipo":"Tipo","marca":"Marca","modelo":"Modelo",
        "status":"Status","localizacao":"Localização","setor":"Setor","data_aquisicao":"Aquisição","data_garantia_fim":"Garantia"
    }
    # larguras equilibradas (A4 landscape ~ 277mm úteis)
    base_widths = [36, 28, 28, 36, 28, 36, 32, 26, 27]
    widths = base_widths[:len(cols)]

    pdf.set_font("Arial", "B", 9)
    for i, c in enumerate(cols):
        pdf.cell(widths[i], 8, headers.get(c, c)[:18], border=1, align="C")
    pdf.ln(8)

    pdf.set_font("Arial", "", 8)
    for _, row in df_inventario.iterrows():
        for i, c in enumerate(cols):
            val = "" if pd.isna(row.get(c)) else str(row.get(c))
            pdf.cell(widths[i], 6, val[:25], border=1)
        pdf.ln(6)

    out = pdf.output(dest="S")
    # normaliza para bytes
    if hasattr(out, "getvalue"):
        out = out.getvalue()
    if isinstance(out, str):
        out = out.encode("latin-1", errors="ignore")
    elif isinstance(out, bytearray):
        out = bytes(out)
    return out

