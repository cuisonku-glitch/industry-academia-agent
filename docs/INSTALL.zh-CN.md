# Windows 与手动安装指南

[English](INSTALL.en.md)

## 1. 系统要求

- Windows 10/11 64 位；Linux/macOS 可使用下文手动安装方式
- Python 3.11
- 建议至少 8 GB 内存
- 约 4 GB 可用磁盘空间，用于 Python 环境、PyTorch、本地模型和向量数据库
- GPU 模式需要受支持的 NVIDIA 显卡与可用驱动；PyTorch Wheel 自带 CUDA 运行时，不会安装到项目目录之外的系统 CUDA Toolkit

## 2. Windows 一键安装

双击项目根目录的 `安装环境.cmd`。脚本会：

1. 查找 Miniconda、Anaconda 或 Miniforge。
2. 若未找到，询问是否从 `repo.anaconda.com` 下载并为当前用户静默安装 Miniconda。
3. 创建或复用名为 `industry_agent` 的 Python 3.11 环境。
4. 检测 NVIDIA 显卡并选择 GPU 或 CPU 依赖。
5. 安装固定版本依赖。
6. 创建被 Git 忽略的 `.env` 和本地数据目录。
7. 下载或验证 `BAAI/bge-small-zh-v1.5` 模型。

可选参数：

```powershell
# 强制安装 CPU 版 PyTorch
.\Setup-Windows.cmd -CpuOnly

# 暂时跳过 BGE 模型下载
.\Setup-Windows.cmd -SkipModel

# 只检查环境，不进行安装
.\Setup-Windows.cmd -CheckOnly
```

## 3. 安装合成示例数据

在全新环境中双击 `安装示例数据.cmd`，或运行：

```powershell
.\Install-Sample-Data.cmd
```

脚本会将 `examples/sample_dataset.json` 中完全合成的数据写入本地向量库和被忽略的教师画像目录。它不会发送网络 API 请求。若检测到现有论文向量、能力记录或教师画像，脚本会立即停止，避免混入真实数据。

可以将 `examples/sample_enterprise_need.txt` 的内容复制到网页进行测试。

## 4. 启动网页

双击 `启动网页Demo.cmd`。脚本会自动寻找以下 Python 环境：

1. `INDUSTRY_AGENT_PYTHON` 指定的解释器
2. 项目 `.venv`
3. 常见 Miniconda、Anaconda、Miniforge 安装目录中的 `industry_agent`
4. Conda 已登记的 `industry_agent`
5. PATH 中依赖完整的 Python

服务就绪后浏览器会自动打开。关闭启动窗口或按 `Ctrl+C` 即可停止。

只检查解释器、入口文件和端口而不启动服务：

```powershell
.\Start-Web-Demo.cmd -CheckOnly
```

端口冲突时可以指定另一个端口：

```powershell
$env:DEMO_PORT="8502"
.\Start-Web-Demo.cmd
```

## 5. 手动安装

```powershell
conda create -n industry_agent python=3.11 pip -y
conda activate industry_agent

# CPU
python -m pip install -r requirements.txt -r requirements-cpu.txt

# 或 Windows NVIDIA GPU
python -m pip install -r requirements.txt -r requirements-gpu-windows.txt

Copy-Item .env.example .env
python -c "from src.retrieval.embedder import LocalEmbedder; print(LocalEmbedder().device)"
python -m unittest discover -s tests -v
python -m streamlit run app/app.py
```

Linux/macOS 使用对应平台的 PyTorch 安装方式，并安装 `requirements.txt`。Windows 专用 GPU Wheel 不适用于其他平台。

## 6. 导入真实论文

1. 确认拥有处理论文和发送片段到外部 API 的权限。
2. 将 PDF 放入 `data/raw/papers/`。
3. 在 `src/ingestion/chunker.py` 的 `PAPER_METADATA` 中填写每个文件的作者、教师和年份。
4. 运行文本解析与本地建库：

```powershell
python src/ingestion/pdf_parser.py
python src/ingestion/chunker.py
python src/retrieval/vector_store.py
```

5. 能力抽取先执行预览；确认屏幕显示的论文片段范围后，才执行 Moonshot 调用：

```powershell
python src/extraction/capability_extractor.py
python src/extraction/capability_extractor.py --send-to-moonshot
python src/extraction/teacher_profiler.py
```

## 7. `.env` 配置

```dotenv
MOONSHOT_API_KEY=你的密钥
MOONSHOT_BASE_URL=https://api.moonshot.cn/v1
MOONSHOT_MODEL=kimi-k3
```

企业匹配不需要 Moonshot。论文问答和能力抽取需要密钥，并会在明确同意后发送检索片段。`.env` 已被 Git 忽略。

## 8. 常见问题

### 找不到 Python

先双击 `安装环境.cmd`。如果使用自定义环境，可设置：

```powershell
$env:INDUSTRY_AGENT_PYTHON="C:\path\to\python.exe"
```

### 模型下载失败

检查网络后重新执行安装脚本。模型成功缓存后可以离线加载，不需要每次下载。

### 没有使用 GPU

运行：

```powershell
conda run -n industry_agent python -c "import torch; print(torch.__version__); print(torch.cuda.is_available())"
```

若结果为 `False`，检查 NVIDIA 驱动，然后重新执行不带 `-CpuOnly` 的安装器。

### 示例安装提示存在真实数据

这是安全保护，不是错误。不要把示例数据安装进已有真实数据库。可以在另一份全新克隆中体验示例数据。
