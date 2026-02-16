# AI Code Review Dashboard

A professional **FastAPI + HTML/CSS/JS dashboard** for performing **AI-powered enterprise code reviews**.
It allows uploading **roles PDF** and providing a **https://github.com/Muhammadwaqas1234/code-review**, then generates a **full AI review report** and scoring using LLMs and RAG (Retrieval-Augmented Generation).

---

## Features

* Upload a **Roles PDF** file for context
* Provide a **GitHub repository link**
* Automated **AI analysis**:

  * Style, bugs, architecture, security, and performance reviews
  * Scoring and risk assessment
  * Enterprise-grade report generation
* **Parallel execution** of review agents for speed
* Professional **dashboard UI**:

  * Sidebar for inputs
  * Main content area for results
  * Spinner/loading animation
* Responsive design for desktop and mobile
* Uses **FAISS vector store** for smart RAG indexing

---

## Technologies

* **Backend**: FastAPI, Python, FAISS, OpenAI API, GitPython, PyPDF
* **Frontend**: HTML, CSS, JavaScript (vanilla)
* **Dependencies**:

  * `agno` – AI agents orchestrator
  * `openai` – LLM API
  * `pypdf` – PDF reading
  * `gitpython` – Clone repositories
  * `tiktoken` – Tokenizer
  * `faiss-cpu` – Vector search
  * `python-dotenv` – Environment variable handling

---

## Installation

1. Clone this repository:

```bash
git clone https://github.com/yourusername/enterprise-ai-review.git
cd enterprise-ai-review
```

2. Create a virtual environment and activate it:

```bash
python -m venv venv
venv\Scripts\activate      
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

> **requirements.txt** should include:
>
> ```
> agno
> openai
> pypdf
> gitpython
> tiktoken
> faiss-cpu
> python-dotenv
> ```

4. Create a `.env` file with your **OpenAI API key**:

```
OPENAI_API_KEY=your_openai_api_key_here
```

---

## Usage

1. Run the **FastAPI backend**:

```bash
uvicorn main:app --reload
```

2. Open your browser at:

```
http://127.0.0.1:8000
```

3. Use the sidebar to:

   * Enter **GitHub repository URL**
   * Upload **Roles PDF**
   * Click **Start AI Review**

4. The main content area will display:

   * **Loading spinner** while processing
   * **Final score**
   * **Enterprise report**

---

## Project Structure

```
backend/
│
├── main.py
├── config.py
├── schemas.py
├── services/
│   ├── pdf_service.py
│   ├── repo_service.py
│   ├── chunk_service.py
│   ├── vector_service.py
│   ├── agent_service.py
│   └── orchestrator_service.py
│
├── static/
│   ├── style.css
│   └── script.js
│
├── templates/
│   └── index.html
│
├── requirements.txt
└── .env

```


## Notes

* Ensure your OpenAI API key is valid and has sufficient quota.
* Only public GitHub repositories are supported for now.
* PDF roles should be in **text-readable format** (not scanned images).

---

## Future Improvements

* Add **authentication/login** for enterprise users
* Add **review history and export**
* Color-coded **risk levels** in report
* Real-time **progress updates** using WebSockets

---

## License

MIT License © 2026 Waqas Abid
