# 📊 ContabilBS — Sistema de Controle Financeiro

Sistema web de **controle financeiro mensal** para empresa de táxi: lançamentos, categorias, fechamento de meses, relatórios de saldos e exportação de dados.

---

## ✨ Funcionalidades

### 💵 Lançamentos e Categorias
- Cadastro de **lançamentos** (entradas e saídas) por categoria.
- **Gestão de categorias** para organização das despesas.
- Edição e exclusão de lançamentos com registro de logs.

### 📅 Controle Mensal
- Abertura e **fechamento de meses** com reabertura quando necessário.
- Detalhamento de cada mês com totais de entrada, saída e saldo.
- Histórico de meses encerrados.

### 📈 Dashboard e Relatórios
- **Dashboard com gráficos** de evolução mensal e por categoria.
- Relatórios de **saldos** (simplificado e discriminado).
- **Exportação para CSV** dos relatórios e lançamentos.
- Versão otimizada para **impressão**.

### 🔐 Segurança
- **Login com autenticação** e níveis de acesso (usuário e administrador).
- Registro de **logs de ações** no sistema.
- Interface com **modo escuro**.

---

## 🛠️ Tecnologias Utilizadas

| Tecnologia | Uso |
|---|---|
| **Python** | Linguagem principal |
| **Flask** | Framework web |
| **SQLite** | Banco de dados |
| **Bootstrap + Chart.js** | Interface e gráficos |

---

## 🚀 Como rodar localmente

```bash
# 1. Clonar
git clone https://github.com/luizaugusto2006/ContabilBS.git
cd ContabilBS

# 2. Ambiente virtual
python -m venv venv
venv\Scripts\activate      # Windows
source venv/bin/activate   # Linux/macOS

# 3. Dependências
pip install -r requirements.txt

# 4. Rodar
python app.py
```

Acesse `http://127.0.0.1:5000`.

---

## 📄 Licença

Este projeto é de uso pessoal e está licenciado sob a [MIT License](LICENSE).
