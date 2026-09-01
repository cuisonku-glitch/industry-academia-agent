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
- Evidence-grounded enterprise need parsing verified with the guide example
- Transparent hybrid research-industry matching verified with local paper evidence
- Six-role Agent workflow verified with an auditable Coordinator trace
- Streamlit matching and paper-QA interface verified in a real local browser

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
Broad questions such as “这个老师研究什么？” are expanded only with local teacher
and paper-title metadata, then retrieve at least one best Chunk from every indexed
paper before the remaining Top-K positions are filled globally. This prevents one
paper from dominating a teacher-overview answer.

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

## Parse enterprise needs

Run the guide's industrial X-ray inspection example only in explicit demo mode:

```powershell
python src/extraction/enterprise_parser.py --demo
```

For another requirement, pass the original product-language description:

```powershell
python src/extraction/enterprise_parser.py --text "我们开发工业 X 射线探伤设备，希望寻找低成本、高灵敏度的探测材料。"
```

The parser separates industry, product, technical problems, required research
capabilities, constraints, and keywords. Every non-empty derived field retains
the exact phrase that triggered it in `evidence_map`. Generated enterprise need
profiles remain local and are ignored by Git.

## Match enterprise needs to teacher research

After stages 5-8 have produced the vector database, teacher profile, and enterprise
need profile, run:

```powershell
python src/matching/matcher.py
```

The stage-9 score is deterministic and reproducible: overall semantic similarity
contributes 45%, required-capability coverage 25%, application-domain matching
15%, and relevant paper-evidence count 15%. The output exposes every raw value,
weight, and point contribution instead of asking an LLM for a subjective score.
It also includes the recommended teacher, core matching technologies, relevant
papers, Chunk/page evidence, matching reasons, technology gaps, and potential
collaboration directions. This stage uses only the local BGE model and ChromaDB;
it does not call Moonshot. Generated matching results remain local and are ignored
by Git.

## Run the Agent workflow

Stage 10 coordinates the verified modules through Requirement, Research, Paper,
Matching, Evidence, and Report agents. The Coordinator records each handoff and
stops the report from presenting unreviewed evidence as verified.

Run the guide example only when you explicitly want a demonstration:

```powershell
python src/agents/workflow.py --demo
```

Run a real enterprise request by passing its original wording:

```powershell
python src/agents/workflow.py --text "企业需求原话"
```

There is deliberately no silent default request. Structured run state and the
Markdown report are saved under `data/processed/agent_runs`, remain local, and
are ignored by Git. The workflow uses the local BGE model and ChromaDB and does
not call Moonshot.

## Run the Streamlit demo

Activate the Conda environment, enter the project directory, and start the local
web interface with the environment's Python executable:

```powershell
python -m streamlit run app/app.py
```

Open `http://127.0.0.1:8501` if the browser does not open automatically. The
**Enterprise Need Matching** tab accepts only text entered by the user and runs
the local six-agent workflow. It displays the recommended teacher, matching
score, core technologies, relevant papers, Chunk/page evidence, matching reasons,
technology gaps, collaboration directions, and reproducible score details.

The **Paper Q&A** tab performs local retrieval and then uses Kimi for the grounded
answer. It will not make the API call until the user explicitly checks the consent
box allowing up to five retrieved paper chunks to be sent to the Moonshot endpoint
configured in `.env`. The API key remains local and is never rendered by the page.
