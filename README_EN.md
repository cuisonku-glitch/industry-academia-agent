# Industry–Academia Agent

[中文](README.md) | [English](README_EN.md)

> A product-oriented web UI is being developed in parallel. Double-click `启动新版网页Demo.cmd` to open the FastAPI paper-card library and full-page paper detail view. The existing `启动网页Demo.cmd` remains the stable Streamlit entry point.

An evidence-grounded industry–academia transfer prototype. It parses papers locally, builds a vector database and traceable teacher research profiles, decomposes original enterprise requests into confirmable technical modules, and produces evidence-gated solution packages, technical routes, transfer assessments, and phased landing plans. The Streamlit interface provides an enterprise solution workbench, an academy paper-library and tag-review workbench, and paper Q&A with page-level citations.

> Data notice: this public repository does not include real papers, teacher profiles, non-public enterprise requests, vector databases, or API keys. `examples/` contains fully synthetic installation fixtures plus a sourced public challenge summary explicitly labeled as not being a client engagement.

## Features

- Local PDF text extraction and page-aware chunking
- Local `BAAI/bge-small-zh-v1.5` embeddings on CPU or NVIDIA GPU
- ChromaDB persistence and evidence retrieval
- Research-direction routing with metadata priority, keyword rules, and an explicit unclassified outcome
- Local extraction of 13 high-frequency performance metrics with raw and canonical units, conditions, evidence levels, and page/chunk provenance
- Dense, BM25, and RRF retrieval under one direction/section/numeric filter contract, with an optional CrossEncoder reranker
- Independent runs per retrieval method with P50/P95 latency, peak GPU memory, and same-qrels evaluation results
- Traceable research-capability extraction and teacher profiling
- Recursive registration of thousands of local PDFs with SHA-256 deduplication and unchanged-file caching
- Fuzzy search by teacher, author, title, or tag with SQLite-backed pagination
- Multi-layer paper tag suggestions with provenance, confidence, and human review status
- Academy-side upload, metadata correction, tag confirmation/rejection, and Markdown catalog preview
- Local figure/caption extraction with figure labels, page provenance, and `Fxx` source IDs
- Consent-gated Kimi structured reading that combines text, figure, formula, route, and transfer-asset analysis in one report
- Validation of every non-empty Kimi claim against `Exx/Fxx/Qxx` sources plus native editable paper-route `.drawio` export
- Structured parsing of requirements, target metrics, test conditions, existing foundations, and excluded approaches
- Field-by-field correction in the web app, with immutable local JSON snapshots and history restore
- GPU retrieval only after the user confirms a saved version, with unknowns preserved as clarification items
- Module-level paper and teacher retrieval without inventing extra solution alternatives
- Technical routes with dependencies, suggested ownership, acceptance/exit criteria, and phased landing plans
- A four-dimension known-only transfer assessment with evidence completeness and five hard gates
- Downloadable Markdown reports and native, editable `.drawio` routes
- Reproducible teacher ranking with fixed, visible score weights
- An eight-role Agent workflow with auditable requirement, retrieval, solution, and evidence-review traces
- Moonshot/Kimi Q&A over at most five locally retrieved paper chunks
- One-click Windows setup, synthetic sample data, and double-click web launchers

## Windows quick start

Requirements: 64-bit Windows 10/11 and an internet connection. The installer looks for Miniconda, Anaconda, or Miniforge. If none is present, it asks before downloading official Miniconda.

1. Download or clone the repository.
2. Double-click `Setup-Windows.cmd` and wait for dependencies and the local BGE model to finish installing.
3. For a first run, double-click `Install-Sample-Data.cmd`. If existing real data is detected, the script stops instead of mixing in the sample.
4. Double-click `Start-Product-Web.cmd` for the FastAPI product UI (`http://127.0.0.1:8000`). Use `Start-Web-Demo.cmd` when you need the complete stable Streamlit UI (`http://127.0.0.1:8501`).
5. Close the launcher window or press `Ctrl+C` to stop the local service.

Equivalent Chinese launcher names are included:

- `安装环境.cmd`
- `安装示例数据.cmd`
- `启动新版网页Demo.cmd`
- `启动网页Demo.cmd`

On a CPU-only computer, run:

```powershell
.\Setup-Windows.cmd -CpuOnly
```

See the [full installation and data guide](docs/INSTALL.en.md) for manual setup, real-paper ingestion, and troubleshooting.

See the [product design and development roadmap (Chinese)](docs/PRODUCT_ROADMAP.zh-CN.md) for the planned dual-sided interface, enterprise solution workflow, academic paper workbench, and explainable paper lineage map. The dependency-ordered engineering plan is in the [implementation sequence (Chinese)](docs/IMPLEMENTATION_SEQUENCE.zh-CN.md).

## Use your own data

1. Put a small set of papers to parse under `data/raw/papers/`. An existing large library can live in a sibling `论文/teacher/*.pdf` directory or be configured with `INDUSTRY_AGENT_PAPER_LIBRARY_DIR`.
2. Register the recursive library and create reviewable tag suggestions. This reads file headers and hashes only; it does not parse full text or call an external API:

```powershell
python scripts/sync_paper_library.py --papers-dir "D:\your-paper-library"
```

3. Open “Academy · Research outputs” in the web app to search papers, correct metadata, and confirm or reject suggested tags. Rules live in `config/paper_tag_taxonomy.json`; automatic results are never confirmed by default.
4. For papers selected for full RAG ingestion, add author, teacher, year, and direction metadata to `config/paper_metadata.seed.json`, then sync the parsed catalog and build the versioned vector database:

```powershell
conda activate industry_agent
python scripts/sync_paper_catalog.py
python src/retrieval/vector_store.py
```

5. Preview and save traceable metric records locally. This step does not call Moonshot:

```powershell
python src/extraction/metric_extractor.py --preview-only
python src/extraction/metric_extractor.py
```

6. Capability extraction sends selected paper excerpts to the Moonshot endpoint configured in `.env`. Preview first, then explicitly approve the API run:

```powershell
python src/extraction/capability_extractor.py
python src/extraction/capability_extractor.py --send-to-moonshot
python src/extraction/teacher_profiler.py
```

7. Start the web app and enter the enterprise's original wording, or load the sourced public Jiangxi Cable acceptance case.
8. Complete the enterprise flow: system parse → field-by-field edit → save a version → confirm the saved version → generate the solution. Unsaved UI edits are never sent downstream.

## Moonshot/Kimi configuration

Enterprise matching runs locally and does not need an API key. Paper Q&A, explicit capability extraction, and Kimi structured paper reading use Moonshot.

When `.env` is missing, the installer creates it from `.env.example`:

```dotenv
MOONSHOT_API_KEY=
MOONSHOT_BASE_URL=https://api.moonshot.cn/v1
MOONSHOT_MODEL=kimi-k3
INDUSTRY_AGENT_PAPER_LIBRARY_DIR=
INDUSTRY_AGENT_CATALOG_PATH=
```

Never commit `.env`. Paper Q&A sends at most five retrieved chunks. A single-paper structured reading sends at most ten evidence excerpts, six formula candidates, and four extracted images. Both require a per-run consent checkbox; the API key is never rendered in the page, and the library is never submitted in bulk by default.

## Common commands

```powershell
# Run all offline tests
python -m unittest discover -s tests -v

# Preview/save local paper metrics without calling an external API
python src/extraction/metric_extractor.py --preview-only
python src/extraction/metric_extractor.py

# Generate independent Dense, BM25, and RRF runs plus an experiment manifest
python scripts/run_retrieval_eval.py --queries data/evaluation/queries.jsonl --output-dir data/evaluation/runs/experiment-001 --methods dense bm25 rrf

# Run the P1 enterprise workflow; explicit confirmation opens the solution gate
python src/agents/workflow.py --text "original enterprise requirement" --confirm-requirement

# Run paper RAG with Kimi
python src/retrieval/rag.py

# Start Streamlit manually
python -m streamlit run app/streamlit_app.py

# Start the FastAPI product UI manually
python -m uvicorn app.web_api:create_app --factory --host 127.0.0.1 --port 8000

# Register a recursive paper library and create reviewable tags (local only)
python scripts/sync_paper_library.py --papers-dir "D:\your-paper-library"

# Parse 10 full-text papers per recoverable local batch
python scripts/parse_paper_library.py --catalog data/metadata/papers.sqlite3 --limit 10 --recover-interrupted

# Incrementally chunk and index with the local GPU (local and recoverable)
$env:HF_HUB_OFFLINE="1"
python scripts/index_paper_library.py --catalog data/metadata/papers.sqlite3 --limit 10 --recover-interrupted
```

## Data and privacy boundary

The following paths are excluded by `.gitignore` and are not uploaded by normal Git commits:

- `.env` and the Moonshot API key
- Raw papers under `data/raw/`
- ChromaDB data under `data/vector_db/` and the Windows user profile
- Metric records, capability records, teacher profiles, enterprise requests, match results, and Agent run records
- Parsed paper text, local/Kimi reading reports, extracted figures, and paper routes
- Downloaded local model caches

Always run a secret scan before publishing and confirm that you have permission to process the papers and enterprise data.

## Project layout

```text
app/                  FastAPI product UI and stable Streamlit interface
examples/             Synthetic fixtures and traceable public challenge summaries
scripts/              Windows setup, launch, and sample bootstrap logic
src/ingestion/        PDF parsing and chunking
src/retrieval/        Embeddings, ChromaDB, and RAG
src/repository/       SQLite paper catalog, tags, and vector-index contract
src/library/          Local discovery, deduplication, upload, and tag suggestions
src/evaluation/       Offline retrieval quality metrics
src/extraction/       Capability, teacher, and enterprise parsing
src/matching/         Transparent weighted matching
src/solutions/        Modules, evidence-gated solutions, routes, assessment, and draw.io export
src/agents/           Eight-Agent coordination, evidence review, and reports
tests/                Offline unit, FastAPI, and Streamlit tests
docs/                 Installation, acceptance, and release notes
```

## Current limitations

- Real paper data is not bundled. Users must import authorized content themselves.
- The pipeline can now extract embedded figures or caption-adjacent page regions for consent-gated, cited Kimi interpretation. Structured values from complex tables and scanned-page OCR are not implemented yet.
- Metric extraction currently uses the deterministic rule/dictionary channel. Repeated mentions may remain as separate evidence records; complex enumerations, figure/table values, and semantic supplementation still need human review or a later optional model channel.
- Hybrid retrieval and same-set ablation tooling are available, but real Recall/MRR/nDCG numbers require page-checked human qrels. The project does not substitute model self-evaluation for a human gold standard.
- Engineering maturity, cost, IP, regulatory, and safety dimensions remain unknown until supporting investigation is available.
- The enterprise workflow emits only as many evidence-supported solutions as it can justify; it does not pad the result to three alternatives.
- The Jiangxi Cable case is a summary of a public open-challenge notice used to test software behavior. It is not a client engagement and is not a human gold-standard endorsement of any matched teacher or proposed solution.
- This release is a local prototype without user accounts, multi-tenant storage, or public hosting.

## Versions

- `v0.1.0`: first runnable local MVP.
- `v0.1.1`: bilingual documentation, MIT license, portable Windows setup/launchers, and synthetic sample data.
- `v0.1.2`: layout-aware PDF parsing, section-aware chunks, SQLite paper catalog, versioned vector collection, and retrieval evaluation.
- `v0.2.0`: the P1 enterprise loop, direction/metric foundations, and hybrid retrieval with shared filters, BM25, RRF, optional CrossEncoder reranking, and independent ablation records.

## License

The code is available under the [MIT License](LICENSE). Papers, enterprise data, and third-party material are not automatically licensed by the project's code license.
