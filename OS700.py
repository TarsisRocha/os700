import streamlit as st
import os
import logging
import pandas as pd
from streamlit_option_menu import option_menu

# Importação dos módulos e funções
from autenticacao import authenticate, add_user, is_admin, list_users
from chamados import add_chamado, list_chamados, list_chamados_em_aberto, finalizar_chamado, buscar_no_inventario_por_patrimonio
from inventario import show_inventory_list, cadastro_maquina  # A função cadastro_maquina será definida em inventario.py
from ubs import get_ubs_list  # Para seleção de UBS
from setores import get_setores_list

# Configuração do logging
logging.basicConfig(level=logging.INFO)

# Inicializa variáveis de sessão
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "username" not in st.session_state:
    st.session_state.username = ""

# Configuração da página
st.set_page_config(page_title="Gestão de Parque de Informática", layout="wide")
logo_path = os.getenv("LOGO_PATH", "infocustec.png")
if os.path.exists(logo_path):
    st.image(logo_path, width=300)
else:
    st.warning("Logotipo não encontrado.")

st.title("Gestão de Parque de Informática - UBS ITAPIPOCA")

# Definição do menu
if st.session_state.logged_in:
    if is_admin(st.session_state.username):
        menu_options = ["Home", "Abrir Chamado", "Chamados Técnicos", "Inventário", "Estoque", "Administração", "Relatórios", "Sair"]
    else:
        menu_options = ["Home", "Abrir Chamado", "Chamados Técnicos", "Inventário", "Estoque", "Relatórios", "Sair"]
else:
    menu_options = ["Login"]

selected = option_menu("Menu", menu_options, orientation="horizontal")

# Função de login
def login():
    st.subheader("Login")
    username = st.text_input("Usuário")
    password = st.text_input("Senha", type="password")
    if st.button("Entrar"):
        if not username or not password:
            st.error("Preencha todos os campos.")
        elif authenticate(username, password):
            st.success(f"Bem-vindo, {username}!")
            st.session_state.logged_in = True
            st.session_state.username = username
        else:
            st.error("Usuário ou senha incorretos.")

# Função de logout
def logout():
    st.session_state.logged_in = False
    st.session_state.username = ""
    st.success("Você saiu.")

# Página Home
def home():
    st.subheader("Bem-vindo!")
    st.write("Selecione uma opção no menu para começar.")

# Função para abrir chamado
def abrir_chamado():
    st.subheader("Abrir Chamado Técnico")
    patrimonio = st.text_input("Número de Patrimônio (opcional)")
    machine_info = None
    machine_type = None
    ubs_selecionada = None
    setor = None

    if patrimonio:
        machine_info = buscar_no_inventario_por_patrimonio(patrimonio)
        if machine_info:
            st.write(f"Máquina encontrada: {machine_info['tipo']} - {machine_info['marca']} {machine_info['modelo']}")
            st.write(f"UBS: {machine_info['localizacao']} | Setor: {machine_info['setor']}")
            ubs_selecionada = machine_info["localizacao"]
            setor = machine_info["setor"]
            machine_type = machine_info["tipo"]
        else:
            st.info("Patrimônio não encontrado no inventário. A máquina será cadastrada automaticamente.")
            default_ubs = st.selectbox("Selecione a UBS para cadastro automático", get_ubs_list())
            default_setor = st.selectbox("Selecione o Setor para cadastro automático", get_setores_list())
            default_tipo = "Não informado"
            default_marca = "Não informado"
            default_modelo = "Não informado"
            from inventario import add_machine_to_inventory
            add_machine_to_inventory(default_tipo, default_marca, default_modelo, None, "Ativo", default_ubs, "Não informado", patrimonio, default_setor)
            st.success("Máquina cadastrada automaticamente no inventário.")
            machine_info = buscar_no_inventario_por_patrimonio(patrimonio)
            if machine_info:
                machine_type = machine_info["tipo"]
                ubs_selecionada = machine_info["localizacao"]
                setor = machine_info["setor"]
            else:
                st.error("Erro ao recuperar os dados da máquina cadastrada.")
                st.stop()
    else:
        ubs_selecionada = st.selectbox("UBS", get_ubs_list())
        setor = st.selectbox("Setor", get_setores_list())
        machine_type = st.selectbox("Tipo de Máquina", ["Computador", "Impressora", "Outro"])

    if machine_type == "Computador":
        defect_options = [
            "Computador não liga",
            "Computador lento",
            "Tela azul",
            "Sistema travando",
            "Erro de disco",
            "Problema com atualização",
            "Desligamento inesperado",
            "Problemas de internet",
            "Problema com Wi-Fi",
            "Sem conexão de rede",
            "Mouse não funciona",
            "Teclado não funciona"
        ]
    elif machine_type == "Impressora":
        defect_options = [
            "Impressora não imprime",
            "Impressão borrada",
            "Toner vazio",
            "Troca de toner",
            "Papel enroscado",
            "Erro de conexão com a impressora"
        ]
    else:
        defect_options = [
            "Solicitação de suporte geral",
            "Outros tipos de defeito"
        ]
    
    tipo_defeito = st.selectbox("Tipo de Defeito/Solicitação", defect_options)
    problema = st.text_area("Descreva o problema ou solicitação")
    
    if st.button("Abrir Chamado"):
        protocolo = add_chamado(st.session_state.username, ubs_selecionada, setor, tipo_defeito, problema, patrimonio=patrimonio)
        if protocolo:
            st.success(f"Chamado aberto com sucesso! Protocolo: {protocolo}")
        else:
            st.error("Erro ao abrir chamado.")

# Função para exibir chamados técnicos
def chamados_tecnicos():
    st.subheader("Chamados Técnicos")
    chamados = list_chamados()
    if chamados:
        st.dataframe(pd.DataFrame(chamados))
    else:
        st.write("Nenhum chamado técnico encontrado.")

# Função para inventário (lista e cadastro)
def inventario():
    st.subheader("Inventário")
    opcao = st.radio("Selecione uma opção:", ["Listar Inventário", "Cadastrar Máquina"])
    if opcao == "Listar Inventário":
        from inventario import show_inventory_list
        show_inventory_list()
    else:
        from inventario import cadastro_maquina
        cadastro_maquina()

# Função para gerenciamento do estoque
def estoque():
    from estoque import manage_estoque
    manage_estoque()

# Função de administração (excluindo o cadastro de máquina)
def administracao():
    st.subheader("Administração")
    admin_option = st.selectbox("Opções de Administração", [
        "Cadastro de Usuário",
        "Gerenciar UBSs",
        "Gerenciar Setores",
        "Lista de Usuários"
    ])
    
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

# Função de relatórios
def relatorios():
    st.subheader("Relatórios")
    chamados = list_chamados()
    inventario_data = get_machines_from_inventory()
    if chamados:
        st.markdown("### Chamados Técnicos")
        st.dataframe(pd.DataFrame(chamados))
    else:
        st.write("Nenhum chamado técnico encontrado.")
    
    if inventario_data:
        st.markdown("### Inventário")
        st.dataframe(pd.DataFrame(inventario_data))
    else:
        st.write("Nenhum item de inventário encontrado.")
    # Expanda com gráficos e estatísticas conforme necessário

# Roteamento do menu
if selected == "Login":
    login()
elif selected == "Home":
    home()
elif selected == "Abrir Chamado":
    abrir_chamado()
elif selected == "Chamados Técnicos":
    chamados_tecnicos()
elif selected == "Inventário":
    inventario()
elif selected == "Estoque":
    estoque()
elif selected == "Administração":
    administracao()
elif selected == "Relatórios":
    relatorios()
elif selected == "Sair":
    logout()
