# Industry–Academia Agent

A minimal industry–academia matching Agent built from a small collection of graduate theses.

## Current status

- Project directory structure created
- Conda environment: `industry_agent`
- Python version: 3.11
- GPU: NVIDIA GeForce RTX 4070
- PyTorch: 2.13.0+cu130
- Local embeddings and ChromaDB vector retrieval verified
- Grounded RAG with `kimi-k3` verified against the Moonshot China API

Development follows the steps in the project guide. Each module is implemented and verified independently.

## Install dependencies

For the current Windows, Python 3.11, and NVIDIA GPU environment:

```powershell
python -m pip install -r requirements.txt -r requirements-gpu-windows.txt
```

The GPU requirement is kept separate so the base project remains portable to CPU-only and non-Windows systems.

## Run the RAG demo

Create `.env` from `.env.example`, add your Moonshot API key, activate the
`industry_agent` Conda environment, and run:

```powershell
python src/retrieval/rag.py
```

The demo embeds the question locally on the GPU, retrieves the top five ChromaDB
chunks, sends only those chunks to Kimi, and prints a grounded answer followed by
deterministic paper and page references. Kimi thinking mode is disabled for this
short evidence-based task so the output-token budget is reserved for the answer.

On Windows, ChromaDB is stored at
`C:\Users\<username>\.industry-academia-agent\vector_db`. This user-home location
avoids Chinese-path limitations and Microsoft Store per-app `LOCALAPPDATA`
virtualization. The project `data\vector_db` entry may be a Junction to that path.
