# 产学研 Agent

[中文](README.md) | [English](README_EN.md)

> 新版产品网页正在并行建设：双击 `启动新版网页Demo.cmd` 打开 FastAPI 论文卡片与完整详情页；原有 `启动网页Demo.cmd` 继续保留为 Streamlit 稳定版。

一个以论文证据为基础的产学研转化原型：在本地解析论文、建立向量数据库和教师科研画像，再将企业原始需求拆成可确认的技术模块，形成有论文页码证据的组合方案、技术路线、转化评估和分阶段落地计划。Streamlit 网页同时提供企业方案工作台、院校论文库与标签审核工作台，以及带页码引用的论文问答。

> 数据说明：公开仓库不包含真实论文、教师画像、非公开企业需求、向量数据库或 API Key。`examples/` 包含完全合成的安装样例，以及带来源、明确标注为“非委托”的公开榜单需求摘要。

## 主要功能

- 本地解析 PDF 文本并按页码切分 Chunk
- 使用 `BAAI/bge-small-zh-v1.5` 在 CPU 或 NVIDIA GPU 上生成本地 Embedding
- 使用 ChromaDB 保存和检索论文证据
- 按“元数据优先、规则其次、未识别保留”的策略标注研究方向
- 在本地抽取 13 类高频性能指标，保留原值、规范单位、测试条件、证据等级和页码/Chunk
- 使用同一方向/章节/数值过滤契约运行 Dense、BM25、RRF，并可选接入 CrossEncoder 重排
- 为每种检索方法保存独立 run、P50/P95 延迟、峰值显存及同 qrels 评测结果
- 从论文证据生成可回溯的科研能力与教师画像
- 递归登记数千篇本地 PDF，以 SHA-256 去重并缓存未变化文件
- 按导师、作者、题名和标签模糊搜索，SQLite 分页返回结果
- 为每篇论文生成多层标签草稿，记录来源、置信度和人工审核状态
- 在院校端上传/选择论文、补录元数据、确认或驳回标签、预览 Markdown 目录报告
- 在本机提取论文原图与图注，并按图号、页码和 `Fxx` 标签追溯
- 经单次明确同意后，用 Kimi 生成含正文、图版、公式、技术路线和可转化资产的统一结构化精读
- 校验每个非空 Kimi 结论的 `Exx/Fxx/Qxx` 引用，并生成原生可编辑论文技术路线 `.drawio`
- 将企业原始需求解析为结构化需求、量化指标、测试条件、已有基础和排除路线
- 在网页中逐项修改解析结果，按不可覆盖的 JSON 快照保存、恢复本地历史版本
- 只有用户确认已保存版本后才进入重型检索，未知项继续保留为待澄清
- 按技术模块分别检索论文和教师证据，不强行生成无依据的多个方案
- 生成带依赖、责任建议、验收/退出条件的技术路线和分阶段落地计划
- 使用“已知维度才计分”的四维转化评估，并公开证据完整度和五项硬门槛
- 下载完整 Markdown 报告与原生可编辑 `.drawio` 技术路线
- 通过固定权重计算可复现的教师匹配分数
- 由八个角色 Agent 记录需求、检索、方案和证据审查轨迹
- 使用 Moonshot/Kimi 对本地检索出的最多五个片段进行有依据问答
- 提供 Windows 一键安装、示例数据和双击启动脚本

## Windows 快速开始

要求：Windows 10/11、64 位系统和网络连接。安装器会寻找 Miniconda、Anaconda 或 Miniforge；如果均未安装，会询问是否从官方地址安装 Miniconda。

1. 下载或克隆仓库。
2. 双击 `安装环境.cmd`，等待依赖和本地 BGE 模型安装完成。
3. 首次体验可双击 `安装示例数据.cmd`。如果电脑中已有真实数据，脚本会停止而不是混入示例数据。
4. 双击 `启动新版网页Demo.cmd` 打开 FastAPI 产品页（`http://127.0.0.1:8000`）；需要完整旧功能时双击 `启动网页Demo.cmd` 打开 Streamlit 稳定版（`http://127.0.0.1:8501`）。
5. 不使用网页时关闭启动窗口，或在窗口中按 `Ctrl+C`。

英文文件名提供相同功能：

- `Setup-Windows.cmd`
- `Install-Sample-Data.cmd`
- `Start-Product-Web.cmd`
- `Start-Web-Demo.cmd`

CPU 电脑可以从终端运行：

```powershell
.\Setup-Windows.cmd -CpuOnly
```

完整安装、真实论文导入和故障排查参见：[Windows 与手动安装指南](docs/INSTALL.zh-CN.md)。

双端网页、企业组合方案、院校论文工作台和论文谱系版图的后续设计参见：[产品设计与开发路线图](docs/PRODUCT_ROADMAP.zh-CN.md)；按依赖执行的工程顺序见：[后续完整实施顺序](docs/IMPLEMENTATION_SEQUENCE.zh-CN.md)。

## 使用自己的数据

1. 少量待解析论文可放入 `data/raw/papers/`；已有的大型论文库也可放在项目同级的 `论文/导师名/*.pdf`，或通过 `INDUSTRY_AGENT_PAPER_LIBRARY_DIR` 指定。
2. 先递归登记大型论文库并生成待审核标签；这个步骤只读取文件头与哈希，不解析全文、不调用外部 API：

```powershell
python scripts/sync_paper_library.py --papers-dir "D:\你的论文目录"
```

3. 打开网页顶部的“院校端 · 成果对接”，可以搜索论文、补充基础信息并确认/驳回自动标签。标签规则位于 `config/paper_tag_taxonomy.json`，自动结果默认均为“待确认”。
4. 对准备进入全文 RAG 的论文，在 `config/paper_metadata.seed.json` 中补充作者、导师、年份和方向，然后同步解析目录并建立当前解析版本的本地向量数据库：

```powershell
conda activate industry_agent
python scripts/sync_paper_catalog.py
python src/retrieval/vector_store.py
```

5. 在本地预览并生成可追溯指标记录；该步骤不调用 Moonshot：

```powershell
python src/extraction/metric_extractor.py --preview-only
python src/extraction/metric_extractor.py
```

6. 能力抽取会把选中的论文片段发送到 `.env` 配置的 Moonshot 接口。先预览，确认范围后再明确执行发送：

```powershell
python src/extraction/capability_extractor.py
python src/extraction/capability_extractor.py --send-to-moonshot
python src/extraction/teacher_profiler.py
```

7. 双击网页启动脚本，输入企业真实需求；也可以先载入带公开来源的“江西电缆”验收案例。
8. 按“系统解析 → 逐项修改 → 保存版本 → 确认已保存版本 → 生成方案”完成企业端流程。未保存的页面修改不会进入方案生成。

## Moonshot/Kimi 配置

企业需求匹配完全在本地运行，不需要 API Key。论文问答、显式能力抽取和 Kimi 结构化精读需要 Moonshot。

安装器会在缺少 `.env` 时从 `.env.example` 创建一份本地文件：

```dotenv
MOONSHOT_API_KEY=
MOONSHOT_BASE_URL=https://api.moonshot.cn/v1
MOONSHOT_MODEL=kimi-k3
INDUSTRY_AGENT_PAPER_LIBRARY_DIR=
INDUSTRY_AGENT_CATALOG_PATH=
```

填写 API Key 后不要提交 `.env`。论文问答最多发送五个检索片段；单篇结构化精读最多发送十个原文证据片段、六个公式候选和四张提取图像。两者都必须由用户在页面勾选本次同意；API Key 不会显示在页面中，也不会批量发送全库。

## 常用命令

```powershell
# 运行全部离线测试
python -m unittest discover -s tests -v

# 仅在本地预览/保存论文指标，不调用外部 API
python src/extraction/metric_extractor.py --preview-only
python src/extraction/metric_extractor.py

# 用同一查询集生成独立 Dense、BM25、RRF run 和实验清单
python scripts/run_retrieval_eval.py --queries data/evaluation/queries.jsonl --output-dir data/evaluation/runs/experiment-001 --methods dense bm25 rrf

# 运行企业端 P1 工作流；只有显式确认后才通过方案确认闸门
python src/agents/workflow.py --text "企业需求原话" --confirm-requirement

# 运行带 Kimi 的论文 RAG
python src/retrieval/rag.py

# 手动启动网页
python -m streamlit run app/streamlit_app.py

# 手动启动新版 FastAPI 产品页
python -m uvicorn app.web_api:create_app --factory --host 127.0.0.1 --port 8000

# 递归登记大型论文库并生成待审核标签（纯本地）
python scripts/sync_paper_library.py --papers-dir "D:\你的论文目录"

# 每次解析 10 篇正文（纯本地，可恢复）
python scripts/parse_paper_library.py --catalog data/metadata/papers.sqlite3 --limit 10 --recover-interrupted

# 用本机 GPU 增量切块并建立向量索引（纯本地，可恢复）
$env:HF_HUB_OFFLINE="1"
python scripts/index_paper_library.py --catalog data/metadata/papers.sqlite3 --limit 10 --recover-interrupted
```

## 数据与隐私边界

以下内容由 `.gitignore` 排除，不会随正常 Git 提交上传：

- `.env` 与 Moonshot API Key
- `data/raw/` 中的论文原文
- `data/vector_db/` 与 Windows 用户目录中的本地 ChromaDB
- 指标记录、能力记录、教师画像、企业需求、匹配结果和 Agent 运行记录
- 解析后的论文正文、本地/Kimi 精读报告、提取图像和论文技术路线
- 下载的本地模型缓存

公开前仍应执行一次敏感信息扫描，并确保拥有论文和企业数据的处理权限。

## 项目结构

```text
app/                  FastAPI 产品网页与 Streamlit 稳定版
examples/             合成安装样例与可追溯的公开榜单需求摘要
scripts/              Windows 安装、启动和示例初始化逻辑
src/ingestion/        PDF 解析与 Chunk 切分
src/retrieval/        Embedding、ChromaDB 和 RAG
src/repository/       SQLite 论文目录、标签与向量索引接口
src/library/          本地论文发现、去重、上传和标签建议
src/evaluation/       离线检索质量指标
src/extraction/       科研能力、教师画像和企业需求解析
src/matching/         透明加权匹配
src/solutions/        技术模块、证据约束方案、路线、评估与 draw.io 导出
src/agents/           八 Agent 协调、证据审查与报告
tests/                离线单元测试、FastAPI 和 Streamlit 测试
docs/                 安装、验收与版本说明
```

## 当前限制

- 真实论文数据未包含在仓库中，需要使用者自行导入并确认版权和授权。
- 当前可按图注提取 PDF 内嵌图像或页面区域，并交给 Kimi 做带引用的视觉解读；复杂表格数值结构化和扫描页 OCR 尚未实现。
- 当前指标抽取是规则/词典确定性通道；重复论述可能保留为多条证据，复杂并列关系、图表数值和语义补充仍需人工复核或后续可选模型通道。
- 混合检索与同集消融工具已经具备，但真实 Recall/MRR/nDCG 必须由人工核页制作 qrels 后才能报告；仓库不会用模型自评替代人工金标准。
- 工程成熟度、成本、知识产权、法规和安全在缺少调查材料时保持“未知”，需要专业人员复核。
- 当前企业端只输出证据足够支撑的方案数量；不会为了界面完整而固定凑出三个方案。
- 江西电缆案例来自公开“揭榜挂帅”榜单摘要，仅验收软件流程；不代表项目获得企业委托，也不构成对匹配教师或方案可行性的人工金标准结论。
- 当前版本是本地单机原型，不包含账号权限、多租户数据库或公网部署。

## 版本

- `v0.1.0`：首次可运行的本地 MVP。
- `v0.1.1`：增加双语文档、MIT 许可证、通用 Windows 安装/启动器和合成示例数据。
- `v0.1.2`：增强 PDF 上下标保真、章节感知切块、SQLite 论文目录、版本化向量集合和检索评测。
- `v0.2.0`：企业端 P1 核心闭环、方向/指标底座，以及带统一过滤、BM25、RRF、可选 CrossEncoder 和独立消融记录的混合检索。

## 许可证

代码采用 [MIT License](LICENSE)。论文、企业数据和其他第三方内容不因本代码许可证而自动获得授权。
