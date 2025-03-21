import streamlit as st
import pandas as pd
from supabase_client import supabase
from setores import get_setores_list
from chamados import get_chamados_por_patrimonio  # Função que busca chamados pelo patrimônio

def get_machines_from_inventory():
    try:
        resp = supabase.table("inventario").select("*").execute()
        return resp.data if resp.data else []
    except Exception as e:
        st.error("Erro ao recuperar inventário.")
        print(f"Erro: {e}")
        return []

def edit_inventory_item(patrimonio, new_values):
    """
    Atualiza o item do inventário identificado pelo 'numero_patrimonio' com os novos valores.
    """
    try:
        supabase.table("inventario").update(new_values).eq("numero_patrimonio", patrimonio).execute()
        st.success("Item atualizado com sucesso!")
    except Exception as e:
        st.error("Erro ao atualizar o item do inventário.")
        print(f"Erro: {e}")

def add_machine_to_inventory(tipo, marca, modelo, numero_serie, status, localizacao, propria_locada, patrimonio, setor):
    try:
        # Verifica se o item já existe
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
            "setor": setor
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

def get_pecas_usadas_por_patrimonio(patrimonio):
    """
    Recupera todas as peças utilizadas associadas aos chamados técnicos da máquina identificada pelo patrimônio.
    """
    chamados = get_chamados_por_patrimonio(patrimonio)
    if not chamados:
        return []
    # Coleta os IDs dos chamados
    chamado_ids = [chamado["id"] for chamado in chamados if "id" in chamado]
    try:
        # Consulta peças utilizadas para os chamados com os IDs coletados
        resp = supabase.table("pecas_usadas").select("*").in_("chamado_id", chamado_ids).execute()
        return resp.data if resp.data else []
    except Exception as e:
        st.error("Erro ao recuperar peças utilizadas.")
        print(f"Erro: {e}")
        return []

def show_inventory_list():
    st.subheader("Inventário")
    machines = get_machines_from_inventory()
    if machines:
        df = pd.DataFrame(machines)
        st.dataframe(df)
        
        # Permite selecionar um item para edição/exclusão e para ver o histórico completo
        patrimonio_options = df["numero_patrimonio"].unique().tolist()
        selected_patrimonio = st.selectbox("Selecione o patrimônio para visualizar detalhes", patrimonio_options)
        if selected_patrimonio:
            item = df[df["numero_patrimonio"] == selected_patrimonio].iloc[0]
            
            # Expander para edição
            with st.expander("Editar Item de Inventário"):
                with st.form("editar_item"):
                    tipo = st.text_input("Tipo", value=item.get("tipo", ""))
                    marca = st.text_input("Marca", value=item.get("marca", ""))
                    modelo = st.text_input("Modelo", value=item.get("modelo", ""))
                    status_options = ["Ativo", "Em Manutenção", "Inativo"]
                    if item.get("status") in status_options:
                        status_index = status_options.index(item.get("status"))
                    else:
                        status_index = 0
                    status = st.selectbox("Status", status_options, index=status_index)
                    localizacao = st.text_input("Localização", value=item.get("localizacao", ""))
                    
                    # Para Setor, utiliza selectbox com a lista de setores
                    setores_list = get_setores_list()
                    if item.get("setor") in setores_list:
                        setor_index = setores_list.index(item.get("setor"))
                    else:
                        setor_index = 0
                    setor = st.selectbox("Setor", setores_list, index=setor_index)
                    
                    propria_opcoes = ["Própria", "Locada"]
                    if item.get("propria_locada") in propria_opcoes:
                        propria_index = própria_opcoes.index(item.get("propria_locada"))
                    else:
                        própria_index = 0
                    propria_locada = st.selectbox("Própria/Locada", própria_opcoes, index=própria_index)
                    
                    submit = st.form_submit_button("Atualizar Item")
                    if submit:
                        new_values = {
                            "tipo": tipo,
                            "marca": marca,
                            "modelo": modelo,
                            "status": status,
                            "localizacao": localizacao,
                            "setor": setor,
                            "propria_locada": propria_locada,
                        }
                        edit_inventory_item(selected_patrimonio, new_values)
            
            # Expander para exclusão
            with st.expander("Excluir Item do Inventário"):
                if st.button("Excluir este item"):
                    delete_inventory_item(selected_patrimonio)
            
            # Expander para histórico completo
            with st.expander("Histórico Completo da Máquina"):
                # Histórico de Chamados Técnicos
                st.markdown("**Chamados Técnicos:**")
                chamados = get_chamados_por_patrimonio(selected_patrimonio)
                if chamados:
                    df_chamados = pd.DataFrame(chamados)
                    st.dataframe(df_chamados)
                else:
                    st.write("Nenhum chamado técnico encontrado para este item.")
                
                # Histórico de Peças Utilizadas
                st.markdown("**Peças Utilizadas:**")
                pecas = get_pecas_usadas_por_patrimonio(selected_patrimonio)
                if pecas:
                    df_pecas = pd.DataFrame(pecas)
                    st.dataframe(df_pecas)
                else:
                    st.write("Nenhuma peça utilizada encontrada para este item.")
    else:
        st.write("Nenhum item encontrado no inventário.")

if __name__ == "__main__":
    show_inventory_list()
