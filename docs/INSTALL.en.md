# Windows and manual installation

[中文](INSTALL.zh-CN.md)

## 1. Requirements

- 64-bit Windows 10/11; Linux and macOS can use the manual path below
- Python 3.11
- At least 8 GB RAM recommended
- Roughly 4 GB of free disk space for the environment, PyTorch, local model, and vector database
- GPU mode requires a supported NVIDIA GPU and driver. The PyTorch Wheel includes its CUDA runtime; it does not install a system CUDA Toolkit inside the project directory.

## 2. One-click Windows setup

Double-click `Setup-Windows.cmd`. The script:

1. Finds Miniconda, Anaconda, or Miniforge.
2. If none is found, asks before downloading official Miniconda from `repo.anaconda.com` and installing it for the current user.
3. Creates or reuses a Python 3.11 environment named `industry_agent`.
4. Detects an NVIDIA GPU and selects GPU or CPU requirements.
5. Installs pinned project dependencies.
6. Creates the Git-ignored `.env` file and local data directories.
7. Downloads or validates `BAAI/bge-small-zh-v1.5`.

Options:

```powershell
# Force CPU-only PyTorch
.\Setup-Windows.cmd -CpuOnly

# Skip the BGE model download for now
.\Setup-Windows.cmd -SkipModel

# Inspect the existing environment without changing it
.\Setup-Windows.cmd -CheckOnly
```

## 3. Install synthetic sample data

In a fresh environment, double-click `Install-Sample-Data.cmd` or run it from a terminal:

```powershell
.\Install-Sample-Data.cmd
```

The script indexes the fully synthetic content in `examples/sample_dataset.json` and creates local, Git-ignored teacher profiles. It does not call an external API. If any existing paper vectors, capability records, or teacher profiles are found, it stops immediately instead of mixing sample and real data.

Paste the content of `examples/sample_enterprise_need.txt` into the web interface for a first test.

## 4. Start the web app

Double-click `Start-Web-Demo.cmd`. It looks for Python in this order:

1. The interpreter in `INDUSTRY_AGENT_PYTHON`
2. A project `.venv`
3. Common Miniconda, Anaconda, and Miniforge locations containing `industry_agent`
4. A Conda-registered `industry_agent` environment
5. A dependency-complete Python on PATH

The browser opens after the service becomes healthy. Close the launcher window or press `Ctrl+C` to stop it.

Check Python discovery, the app entry point, and the port without starting a server:

```powershell
.\Start-Web-Demo.cmd -CheckOnly
```

To use a different port:

```powershell
$env:DEMO_PORT="8502"
.\Start-Web-Demo.cmd
```

## 5. Manual setup

```powershell
conda create -n industry_agent python=3.11 pip -y
conda activate industry_agent

# CPU
python -m pip install -r requirements.txt -r requirements-cpu.txt

# Or Windows NVIDIA GPU
python -m pip install -r requirements.txt -r requirements-gpu-windows.txt

Copy-Item .env.example .env
python -c "from src.retrieval.embedder import LocalEmbedder; print(LocalEmbedder().device)"
python -m unittest discover -s tests -v
python -m streamlit run app/streamlit_app.py
```

On Linux or macOS, install the appropriate PyTorch build for that platform together with `requirements.txt`. The Windows GPU Wheel is not portable to other systems.

## 6. Import real papers

1. Confirm that you are authorized to process the papers and send excerpts to an external API.
2. Put PDFs in `data/raw/papers/`.
3. Add filename, author, teacher, year, and direction values to `config/paper_metadata.seed.json`. After the first sync, the local SQLite catalog is the runtime source of truth.
4. Parse, sync the catalog, and index locally:

```powershell
python src/ingestion/pdf_parser.py
python src/ingestion/chunker.py
python scripts/sync_paper_catalog.py
python src/retrieval/vector_store.py
```

5. Preview capability-extraction scope first. Call Moonshot only after reviewing the displayed excerpts:

```powershell
python src/extraction/capability_extractor.py
python src/extraction/capability_extractor.py --send-to-moonshot
python src/extraction/teacher_profiler.py
```

## 7. `.env` configuration

```dotenv
MOONSHOT_API_KEY=your-key
MOONSHOT_BASE_URL=https://api.moonshot.cn/v1
MOONSHOT_MODEL=kimi-k3
```

Enterprise matching does not require Moonshot. Paper Q&A and capability extraction require the key and send retrieved excerpts only after explicit consent. `.env` is ignored by Git.

## 8. Troubleshooting

### Python is not found

Run `Setup-Windows.cmd` first. For a custom environment, set:

```powershell
$env:INDUSTRY_AGENT_PYTHON="C:\path\to\python.exe"
```

### Model download fails

Check the network and rerun the setup script. Once cached, the model loads locally and does not need to be downloaded again.

### GPU is not used

Run:

```powershell
conda run -n industry_agent python -c "import torch; print(torch.__version__); print(torch.cuda.is_available())"
```

If it prints `False`, check the NVIDIA driver and rerun setup without `-CpuOnly`.

### Sample installation reports existing real data

This is a safety check, not a failure. Do not install the synthetic sample into an existing real database. Use another fresh clone for the sample.
