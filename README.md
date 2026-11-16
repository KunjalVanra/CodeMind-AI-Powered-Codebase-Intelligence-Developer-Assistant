# CodeMind — AI-Powered Codebase Intelligence & Developer Assistant

<p align="center">
  <strong>Understand. Analyze. Search. Improve.</strong>
</p>

CodeMind is an AI-powered codebase intelligence platform that helps developers understand, analyze, search, and interact with large software repositories using Artificial Intelligence, semantic search, and Retrieval-Augmented Generation (RAG).

Instead of manually navigating thousands of lines of code, developers can connect a GitHub repository and use CodeMind to explore its architecture, understand code relationships, identify potential security issues, generate documentation, and ask questions about their codebase.

---

## 🚀 Key Features

- **GitHub Repository Integration:** Connect and clone GitHub repositories for analysis.
- **Automated Source Code Scanning:** Detect supported programming languages, files, and code metrics.
- **Multi-Language Code Parsing:** Analyze source code using Python AST and Tree-sitter.
- **Semantic Code Search:** Find relevant code using natural-language queries and vector embeddings.
- **AI Codebase Assistant:** Ask questions about a repository and receive contextual answers with source citations using RAG.
- **Dependency Graph:** Explore relationships and dependencies between code components.
- **Security Analysis:** Identify potential security issues using Semgrep integration when available.
- **AI Documentation Generation:** Generate documentation based on repository source code.
- **AI Test Generation:** Generate Python unit-test suggestions for existing code.
- **Architecture Analytics:** Explore codebase metrics, complexity, language distribution, and structural insights.
- **Authentication:** Secure user registration, login, and repository ownership controls.

## 🛠️ Technology Stack

| Layer | Technologies |
|---|---|
| Frontend | React.js, TypeScript, Vite |
| Styling | CSS |
| Backend | Python, FastAPI |
| Database | MySQL, SQLAlchemy |
| Authentication | JWT, OAuth2 |
| Code Parsing | Python AST, Tree-sitter |
| AI / LLM | Groq API |
| Embeddings | Sentence Transformers |
| Vector Database | ChromaDB |
| Repository Integration | GitHub API, GitPython |
| Testing | Pytest |
| Security Analysis | Semgrep (optional) |
| Version Control | Git, GitHub |

## 🏗️ Project Architecture

```text
CodeMind/
│
├── backend/
│   ├── app/
│   │   ├── api/          # REST API endpoints
│   │   ├── core/         # Configuration, database, security
│   │   ├── models/       # Database models
│   │   ├── schemas/      # Pydantic schemas
│   │   └── services/     # AI, parsing, scanning and analysis
│   │
│   ├── tests/            # Backend test suite
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   │   ├── api/          # Backend API integration
│   │   ├── app/          # Application routing
│   │   ├── auth/         # Authentication
│   │   ├── components/   # Reusable UI components
│   │   └── pages/        # Application pages
│   │
│   └── package.json
│
├── docs/
├── docker-compose.yml
├── .env.example
├── .gitignore
└── README.md
```

## ⚙️ Getting Started

### Prerequisites

Install the following before running CodeMind locally:

- Python 3.10+
- Node.js and npm
- MySQL 8.0+
- Git

### 1. Clone the Repository

```bash
git clone https://github.com/KunjalVanra/CodeMind-AI-Powered-Codebase-Intelligence-Developer-Assistant.git

cd CodeMind-AI-Powered-Codebase-Intelligence-Developer-Assistant
```

### 2. Backend Setup

Open a terminal:

```bash
cd backend
```

Create a virtual environment:

```bash
python -m venv .venv
```

Activate it on Windows:

```powershell
.venv\Scripts\Activate.ps1
```

Install dependencies:

```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Create a `.env` file inside the `backend` directory using `.env.example` as a reference.

Configure your own values for:

```env
DATABASE_URL=your_mysql_database_url
SECRET_KEY=your_secure_secret_key
GROQ_API_KEY=your_groq_api_key
```

Use the actual environment variable names expected by the backend configuration. Never commit
