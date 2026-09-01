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
- Traceable capability extraction verified for all three indexed papers
- Deterministic teacher research profile verified from three paper records

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

## Extract research capabilities

Preview the locally selected evidence without calling Moonshot:

```powershell
python src/extraction/capability_extractor.py
```

After reviewing and approving the displayed data scope, run the extraction with:

```powershell
python src/extraction/capability_extractor.py --send-to-moonshot
```

Each paper is saved as a UTF-8 JSON file under `data/processed/capabilities`.
Required capability fields remain separate from `evidence_map`; every non-empty
claim must reference a real source label, and `sources` retains the original Chunk
text, Chunk ID, and page range. This output directory is intentionally ignored by
Git because the records contain excerpts from the source papers.

Dataset v0.1 validation produced three local JSON records with 72 capability
claims in total. All 72 claims have validated Chunk and page evidence mappings.

## Build teacher research profiles

Aggregate the validated per-paper records locally without another LLM call:

```powershell
python src/extraction/teacher_profiler.py
```

The profile preserves the guide's teacher, research direction, core capability,
representative paper, application domain, and potential industry fields. Its
`evidence_map` links every aggregated value back to a paper, original stage-6
claim, Chunk ID, and page range. Generated profiles remain local and are ignored
by Git.
