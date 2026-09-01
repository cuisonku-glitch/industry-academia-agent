# 产学研 Agent

[中文](README.md) | [English](README_EN.md)

一个以论文证据为基础的产学研匹配原型：在本地解析论文、建立向量数据库和教师科研画像，再将企业原始需求与教师能力进行可复算匹配。Streamlit 网页同时提供企业需求匹配和带页码引用的论文问答。

> 数据说明：公开仓库不包含真实论文、教师画像、企业需求、向量数据库或 API Key。`examples/` 中的数据完全由项目维护者合成，只用于验证安装和演示流程。

## 主要功能

- 本地解析 PDF 文本并按页码切分 Chunk
- 使用 `BAAI/bge-small-zh-v1.5` 在 CPU 或 NVIDIA GPU 上生成本地 Embedding
- 使用 ChromaDB 保存和检索论文证据
- 从论文证据生成可回溯的科研能力与教师画像
- 将企业原始需求解析为结构化科研需求
- 通过固定权重计算可复现的教师匹配分数
- 由六个角色 Agent 记录完整执行和证据审查轨迹
- 使用 Moonshot/Kimi 对本地检索出的最多五个片段进行有依据问答
- 提供 Windows 一键安装、示例数据和双击启动脚本

## Windows 快速开始

要求：Windows 10/11、64 位系统和网络连接。安装器会寻找 Miniconda、Anaconda 或 Miniforge；如果均未安装，会询问是否从官方地址安装 Miniconda。

1. 下载或克隆仓库。
2. 双击 `安装环境.cmd`，等待依赖和本地 BGE 模型安装完成。
3. 首次体验可双击 `安装示例数据.cmd`。如果电脑中已有真实数据，脚本会停止而不是混入示例数据。
4. 双击 `启动网页Demo.cmd`，浏览器会自动打开 `http://127.0.0.1:8501`。
5. 不使用网页时关闭启动窗口，或在窗口中按 `Ctrl+C`。

英文文件名提供相同功能：

- `Setup-Windows.cmd`
- `Install-Sample-Data.cmd`
- `Start-Web-Demo.cmd`

CPU 电脑可以从终端运行：

```powershell
.\Setup-Windows.cmd -CpuOnly
```

完整安装、真实论文导入和故障排查参见：[Windows 与手动安装指南](docs/INSTALL.zh-CN.md)。

双端网页、企业组合方案、院校论文工作台和论文谱系版图的后续设计参见：[产品设计与开发路线图](docs/PRODUCT_ROADMAP.zh-CN.md)；按依赖执行的工程顺序见：[后续完整实施顺序](docs/IMPLEMENTATION_SEQUENCE.zh-CN.md)。

## 使用自己的数据

1. 将有权处理的论文 PDF 放入 `data/raw/papers/`。
2. 在 `config/paper_metadata.seed.json` 中填写文件名、作者、导师、年份和方向；首次同步后，本地 SQLite 目录数据库是运行时数据源。
3. 同步目录并建立当前解析版本的本地向量数据库：

```powershell
conda activate industry_agent
python scripts/sync_paper_catalog.py
python src/retrieval/vector_store.py
```

4. 能力抽取会把选中的论文片段发送到 `.env` 配置的 Moonshot 接口。先预览，确认范围后再明确执行发送：

```powershell
python src/extraction/capability_extractor.py
python src/extraction/capability_extractor.py --send-to-moonshot
python src/extraction/teacher_profiler.py
```

5. 双击网页启动脚本并输入企业真实需求。

## Moonshot/Kimi 配置

企业需求匹配完全在本地运行，不需要 API Key。只有论文问答和显式能力抽取需要 Moonshot。

安装器会在缺少 `.env` 时从 `.env.example` 创建一份本地文件：

```dotenv
MOONSHOT_API_KEY=
MOONSHOT_BASE_URL=https://api.moonshot.cn/v1
MOONSHOT_MODEL=kimi-k3
```

填写 API Key 后不要提交 `.env`。网页只有在用户勾选同意后，才会发送本地检索出的最多五个论文片段；API Key 不会显示在页面中。

## 常用命令

```powershell
# 运行全部离线测试
python -m unittest discover -s tests -v

# 运行六 Agent 工作流
python src/agents/workflow.py --text "企业需求原话"

# 运行带 Kimi 的论文 RAG
python src/retrieval/rag.py

# 手动启动网页
python -m streamlit run app/app.py
```

## 数据与隐私边界

以下内容由 `.gitignore` 排除，不会随正常 Git 提交上传：

- `.env` 与 Moonshot API Key
- `data/raw/` 中的论文原文
- `data/vector_db/` 与 Windows 用户目录中的本地 ChromaDB
- 能力记录、教师画像、企业需求、匹配结果和 Agent 运行记录
- 下载的本地模型缓存

公开前仍应执行一次敏感信息扫描，并确保拥有论文和企业数据的处理权限。

## 项目结构

```text
app/                  Streamlit 网页
examples/             完全合成的公开示例数据
scripts/              Windows 安装、启动和示例初始化逻辑
src/ingestion/        PDF 解析与 Chunk 切分
src/retrieval/        Embedding、ChromaDB 和 RAG
src/repository/       SQLite 论文目录与向量索引接口
src/evaluation/       离线检索质量指标
src/extraction/       科研能力、教师画像和企业需求解析
src/matching/         透明加权匹配
src/agents/           六 Agent 协调与报告
tests/                离线单元测试和 Streamlit 测试
docs/                 安装、验收与版本说明
```

## 当前限制

- 真实论文数据未包含在仓库中，需要使用者自行导入并确认版权和授权。
- 当前 PDF 流程主要处理文本，不解析论文图片、复杂表格或扫描页 OCR。
- 公开示例数据仅验证软件流程，不代表真实科研成果或匹配结论。
- 当前版本是本地单机原型，不包含账号权限、多租户数据库或公网部署。

## 版本

- `v0.1.0`：首次可运行的本地 MVP。
- `v0.1.1`：增加双语文档、MIT 许可证、通用 Windows 安装/启动器和合成示例数据。
- `v0.1.2`：增强 PDF 上下标保真、章节感知切块、SQLite 论文目录、版本化向量集合和检索评测。

## 许可证

代码采用 [MIT License](LICENSE)。论文、企业数据和其他第三方内容不因本代码许可证而自动获得授权。
