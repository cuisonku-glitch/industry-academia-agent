# Industry–Academia Agent

[中文](README.md) | [English](README_EN.md)

An evidence-grounded industry–academia matching prototype. It parses papers locally, builds a vector database and traceable teacher research profiles, and produces reproducible matches between original enterprise requests and research capabilities. The Streamlit interface provides enterprise matching and paper Q&A with page-level citations.

> Data notice: this public repository does not include real papers, teacher profiles, enterprise requests, vector databases, or API keys. Everything under `examples/` is fully synthetic and exists only to validate installation and demonstrate the workflow.

## Features

- Local PDF text extraction and page-aware chunking
- Local `BAAI/bge-small-zh-v1.5` embeddings on CPU or NVIDIA GPU
- ChromaDB persistence and evidence retrieval
- Traceable research-capability extraction and teacher profiling
- Structured parsing of original enterprise requirements
- Reproducible teacher ranking with fixed, visible score weights
- A six-role Agent workflow with an auditable execution and evidence-review trace
- Moonshot/Kimi Q&A over at most five locally retrieved paper chunks
- One-click Windows setup, synthetic sample data, and double-click web launchers

## Windows quick start

Requirements: 64-bit Windows 10/11 and an internet connection. The installer looks for Miniconda, Anaconda, or Miniforge. If none is present, it asks before downloading official Miniconda.

1. Download or clone the repository.
2. Double-click `Setup-Windows.cmd` and wait for dependencies and the local BGE model to finish installing.
3. For a first run, double-click `Install-Sample-Data.cmd`. If existing real data is detected, the script stops instead of mixing in the sample.
4. Double-click `Start-Web-Demo.cmd`. The browser opens `http://127.0.0.1:8501` automatically.
5. Close the launcher window or press `Ctrl+C` to stop the local service.

Equivalent Chinese launcher names are included:

- `安装环境.cmd`
- `安装示例数据.cmd`
- `启动网页Demo.cmd`

On a CPU-only computer, run:

```powershell
.\Setup-Windows.cmd -CpuOnly
```

See the [full installation and data guide](docs/INSTALL.en.md) for manual setup, real-paper ingestion, and troubleshooting.

See the [product design and development roadmap (Chinese)](docs/PRODUCT_ROADMAP.zh-CN.md) for the planned dual-sided interface, enterprise solution workflow, academic paper workbench, and explainable paper lineage map. The dependency-ordered engineering plan is in the [implementation sequence (Chinese)](docs/IMPLEMENTATION_SEQUENCE.zh-CN.md).

## Use your own data

1. Put PDFs that you are authorized to process in `data/raw/papers/`.
2. Add filename, author, teacher, year, and direction metadata to `config/paper_metadata.seed.json`. After the first sync, the local SQLite catalog is the runtime source of truth.
3. Sync the catalog and build the versioned local vector database:

```powershell
conda activate industry_agent
python scripts/sync_paper_catalog.py
python src/retrieval/vector_store.py
```

4. Capability extraction sends selected paper excerpts to the Moonshot endpoint configured in `.env`. Preview first, then explicitly approve the API run:

```powershell
python src/extraction/capability_extractor.py
python src/extraction/capability_extractor.py --send-to-moonshot
python src/extraction/teacher_profiler.py
```

5. Start the web app and enter the enterprise's original wording.

## Moonshot/Kimi configuration

Enterprise matching runs locally and does not need an API key. Only paper Q&A and explicit capability extraction use Moonshot.

When `.env` is missing, the installer creates it from `.env.example`:

```dotenv
MOONSHOT_API_KEY=
MOONSHOT_BASE_URL=https://api.moonshot.cn/v1
MOONSHOT_MODEL=kimi-k3
```

Never commit `.env`. The web app sends at most five locally retrieved paper chunks only after the user checks the consent box. The API key is never rendered in the page.

## Common commands

```powershell
# Run all offline tests
python -m unittest discover -s tests -v

# Run the six-Agent workflow
python src/agents/workflow.py --text "original enterprise requirement"

# Run paper RAG with Kimi
python src/retrieval/rag.py

# Start Streamlit manually
python -m streamlit run app/app.py
```

## Data and privacy boundary

The following paths are excluded by `.gitignore` and are not uploaded by normal Git commits:

- `.env` and the Moonshot API key
- Raw papers under `data/raw/`
- ChromaDB data under `data/vector_db/` and the Windows user profile
- Capability records, teacher profiles, enterprise requests, match results, and Agent run records
- Downloaded local model caches

Always run a secret scan before publishing and confirm that you have permission to process the papers and enterprise data.

## Project layout

```text
app/                  Streamlit web interface
examples/             Fully synthetic public sample data
scripts/              Windows setup, launch, and sample bootstrap logic
src/ingestion/        PDF parsing and chunking
src/retrieval/        Embeddings, ChromaDB, and RAG
src/repository/       SQLite paper catalog and vector-index contract
src/evaluation/       Offline retrieval quality metrics
src/extraction/       Capability, teacher, and enterprise parsing
src/matching/         Transparent weighted matching
src/agents/           Six-Agent coordination and reports
tests/                Offline unit and Streamlit tests
docs/                 Installation, acceptance, and release notes
```

## Current limitations

- Real paper data is not bundled. Users must import authorized content themselves.
- The current PDF pipeline focuses on text and does not yet interpret figures, complex tables, or scanned-page OCR.
- The synthetic dataset validates software behavior only; it is not a real research result or recommendation.
- This release is a local prototype without user accounts, multi-tenant storage, or public hosting.

## Versions

- `v0.1.0`: first runnable local MVP.
- `v0.1.1`: bilingual documentation, MIT license, portable Windows setup/launchers, and synthetic sample data.
- `v0.1.2`: layout-aware PDF parsing, section-aware chunks, SQLite paper catalog, versioned vector collection, and retrieval evaluation.

## License

The code is available under the [MIT License](LICENSE). Papers, enterprise data, and third-party material are not automatically licensed by the project's code license.
