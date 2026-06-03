# AI Copilot for Support Agents with Mem0
+
+An intelligent support ticket management system and AI copilot designed to help support agents respond faster and more accurately. It leverages **Mem0** for long-term customer memory, **ChromaDB** for knowledge base (RAG), and **LangChain** with **Groq** for high-speed agentic workflows.
+
+## 🚀 Features
+
+- **Automated Draft Generation**: Automatically generates response drafts for new tickets using customer context and knowledge base.
+- **Long-term Customer Memory**: Uses [Mem0](https://github.com/mem0ai/mem0) to remember customer preferences, past issues, and specific details across different tickets.
+- **RAG-powered Knowledge Base**: Extracts information from a local knowledge base (markdown/text files) using ChromaDB to provide accurate technical answers.
+- **Agentic Tool Use**: The AI can look up customer subscription plans and current ticket loads to personalize responses and prioritize work.
+- **Agent Dashboard**: A Streamlit-based interface for agents to manage tickets, review AI drafts, and probe customer memory.
+- **FastAPI Backend**: A robust REST API managing tickets, customers, and AI interactions.
+
+## 🛠️ Tech Stack
+
+- **Framework**: LangChain
+- **LLM**: Groq (Llama 3.1)
+- **Memory**: Mem0
+- **Vector Store**: ChromaDB (for RAG)
+- **Database**: SQLite (for ticket/customer metadata)
+- **API**: FastAPI
+- **Frontend**: Streamlit
+- **Package Manager**: [uv](https://github.com/astral-sh/uv)
+
+## 📋 Prerequisites
+
+- Python 3.11
+- [uv](https://github.com/astral-sh/uv) (recommended) or pip
+- Groq API Key
+- Google AI API Key (for Gemini embeddings)
+
+## ⚙️ Configuration
+
+Create a `.env` file in the root directory:
+
+```env
+GROQ_API_KEY=your_groq_api_key
+GOOGLE_API_KEY=your_google_api_key
+
+# Optional overrides
+GROQ_MODEL=llama-3.1-8b-instant
+GOOGLE_EMBEDDING_MODEL=gemini-embedding-001
+API_HOST=0.0.0.0
+API_PORT=8000
+```
+
+## 🏃 Running the Application
+
+### Using Docker (Recommended)
+
+The easiest way to run the full stack is using Docker Compose:
+
+```bash
+docker-compose up --build
+```
+
+- **API**: http://localhost:8000
+- **Dashboard**: http://localhost:8501
+- **API Docs**: http://localhost:8000/docs
+
+### Local Development
+
+1. **Install dependencies**:
+   ```bash
+   uv sync
+   ```
+
+2. **Run the API**:
+   ```bash
+   uv run main.py
+   ```
+
+3. **Run the Dashboard**:
+   ```bash
+   uv run streamlit run app.py
+   ```
+
+## 📂 Project Structure
+
+- `customer_support_agent/`: Core application logic.
+    - `api/`: FastAPI routes and application factory.
+    - `integrations/`: Mem0, ChromaDB, and LangChain tool definitions.
+    - `repositories/`: SQLite data access layer for tickets and customers.
+    - `services/`: Business logic for drafts, knowledge ingestion, and memory.
+- `knowledge_base/`: Place your technical docs (.md, .txt) here for RAG.
+- `app.py`: Streamlit dashboard code.
+- `main.py`: FastAPI entry point.
+- `data/`: Local storage for SQLite and ChromaDB (created automatically).
+
+## 🧠 How it Works
+
+1. **Ticket Creation**: When a ticket is created, the system triggers the `CopilotService`.
+2. **Context Retrieval**:
+   - **Mem0** is queried for the specific `customer_id` to get historical context.
+   - **ChromaDB** is searched for relevant technical documentation.
+   - **Tools** are called to check the customer's plan and current system load.
+3. **Drafting**: LangChain uses the retrieved context to prompt the LLM (via Groq) to write a helpful, personalized response.
+4. **Memory Update**: When an agent accepts or edits a draft, the finalized response is sent back to **Mem0** to update the customer's long-term memory profile.