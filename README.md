# Industry–Academia Agent

A minimal industry–academia matching Agent built from a small collection of graduate theses.

## Current status

- Project directory structure created
- Conda environment: `industry_agent`
- Python version: 3.11
- GPU: NVIDIA GeForce RTX 4070
- PyTorch: 2.13.0+cu130
- Local embeddings and ChromaDB vector retrieval verified

Development follows the steps in the project guide. Each module is implemented and verified independently.

## Install dependencies

For the current Windows, Python 3.11, and NVIDIA GPU environment:

```powershell
python -m pip install -r requirements.txt -r requirements-gpu-windows.txt
```

The GPU requirement is kept separate so the base project remains portable to CPU-only and non-Windows systems.
