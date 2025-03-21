# autenticacao.py

import sqlite3
import bcrypt

# Função para autenticar o usuário
def authenticate(username, password):
    try:
        with sqlite3.connect('chamados.db') as conn:
            cursor = conn.cursor()

            # Busca o hash da senha armazenada no banco de dados
            cursor.execute("SELECT password FROM usuarios WHERE username=?", (username,))
            result = cursor.fetchone()

            if result:
                stored_password = result[0]
                # Garantir que stored_password é do tipo bytes
                if isinstance(stored_password, str):
                    stored_password = stored_password.encode('utf-8')

                # Verifica a senha usando bcrypt
                if bcrypt.checkpw(password.encode('utf-8'), stored_password):
                    # print("Autenticação bem-sucedida!")  # Comentado para evitar prints desnecessários
                    return True
                else:
                    # print("Senha incorreta.")  # Comentado para evitar prints desnecessários
                    return False
            else:
                # print("Usuário não encontrado.")  # Comentado para evitar prints desnecessários
                return False
    except Exception as e:
        print(f"Erro na autenticação: {e}")
        return False

# Função para adicionar um novo usuário
def add_user(username, password, is_admin=False):
    try:
        with sqlite3.connect('chamados.db') as conn:
            cursor = conn.cursor()

            # Verifica se o usuário já existe
            cursor.execute("SELECT * FROM usuarios WHERE username=?", (username,))
            existing_user = cursor.fetchone()

            if existing_user:
                print("Usuário já existe.")
                return False
            else:
                # Hashear a senha usando bcrypt
                hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
                role = 'admin' if is_admin else 'user'
                cursor.execute("INSERT INTO usuarios (username, password, role) VALUES (?, ?, ?)",
                               (username, hashed_password, role))
                conn.commit()
                print(f"Usuário '{username}' criado com sucesso como {role}.")
                return True
    except Exception as e:
        print(f"Erro ao adicionar usuário: {e}")
        return False

# Função para verificar se o usuário é administrador
def is_admin(username):
    try:
        with sqlite3.connect('chamados.db') as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT role FROM usuarios WHERE username=?", (username,))
            user_role = cursor.fetchone()
            return user_role and user_role[0] == 'admin'
    except Exception as e:
        print(f"Erro ao verificar função do usuário: {e}")
        return False

# Função para listar todos os usuários cadastrados
def list_users():
    try:
        with sqlite3.connect('chamados.db') as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT username, role FROM usuarios')
            users = cursor.fetchall()
            return users
    except Exception as e:
        print(f"Erro ao listar usuários: {e}")
        return []

# Função para alterar a senha de um usuário
def change_password(username, old_password, new_password):
    if authenticate(username, old_password):
        try:
            with sqlite3.connect('chamados.db') as conn:
                cursor = conn.cursor()
                hashed_new_password = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt())
                cursor.execute("UPDATE usuarios SET password=? WHERE username=?", (hashed_new_password, username))
                conn.commit()
                print("Senha alterada com sucesso.")
                return True
        except Exception as e:
            print(f"Erro ao alterar a senha: {e}")
            return False
    else:
        print("Autenticação falhou. Senha antiga incorreta.")
        return False

# Função para remover um usuário (apenas para administradores)
def remove_user(admin_username, target_username):
    if is_admin(admin_username):
        try:
            with sqlite3.connect('chamados.db') as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM usuarios WHERE username=?", (target_username,))
                conn.commit()
                print(f"Usuário '{target_username}' removido com sucesso.")
                return True
        except Exception as e:
            print(f"Erro ao remover usuário: {e}")
            return False
    else:
        print("Permissão negada. Apenas administradores podem remover usuários.")
        return False
