# 检索质量评测

本目录记录离线检索评测的格式和流程。评测集用于回答“检索结果是否真的变准”，不替代现有的结构校验单元测试。

## 文件格式

查询文件 `queries.jsonl` 每行是一条不含答案的真实问题：

```json
{"query_id":"q001","query":"希望探测器在低剂量下仍保持高灵敏度，哪些论文有直接实验依据？"}
```

可选 `filters` 在所有检索方法运行前使用同一套候选过滤规则：

```json
{"query_id":"q002","query":"哪些结果满足灵敏度门槛？","filters":{"direction":"x_ray_detector","section_types":["results","discussion"],"metrics":[{"definition_id":"sensitivity","operator":"gte","value":1000,"unit":"μC Gyair^-1 cm^-2"}]}}
```

- `direction` 使用 `config/research_direction_taxonomy.json` 中的方向 ID；
- `section_types` 使用章节感知切块的封闭类型；
- `metrics` 支持 `eq/gte/lte/between`，输入值先按指标本体归一；
- 数值硬筛默认只接受 `measured/reported`，不会把 `inferred` 当成已达到的硬指标；
- 多个指标约束按 AND 处理，区间必须整体满足门槛，不能只取有利端点。

人工相关性标注 `qrels.jsonl` 每行对应一个 query/chunk 判断：

```json
{"query_id":"q001","chunk_id":"paper_chunk_0001","relevance":2}
```

- `0`：不相关；
- `1`：部分相关；
- `2`：直接回答问题或提供关键证据。

检索运行结果 `run.jsonl` 每行保存一个有序 Chunk 列表：

```json
{"query_id":"q001","chunk_ids":["paper_chunk_0001","paper_chunk_0042"]}
```

## 运行

```powershell
python scripts/run_retrieval_eval.py `
  --queries data/evaluation/queries.jsonl `
  --qrels data/evaluation/qrels.jsonl `
  --output-dir data/evaluation/runs/experiment-001 `
  --methods dense bm25 rrf

python scripts/evaluate_retrieval.py --qrels data/evaluation/qrels.jsonl --run data/evaluation/dense-section-v2.jsonl
```

每个方法保存独立 JSONL；`manifest.json` 记录查询文件哈希、集合版本、过滤数量、P50/P95 延迟和峰值 GPU 显存。提供 `--qrels` 时，每个方法还保存独立指标 JSON，并在同一份 qrels 上计算宏平均 `Recall@K`、`MRR@K` 和 `nDCG@K`。

可选 CrossEncoder 不随仓库下载；先自行选择并缓存有权使用的模型，再显式运行：

```powershell
python scripts/run_retrieval_eval.py `
  --queries data/evaluation/queries.jsonl `
  --qrels data/evaluation/qrels.jsonl `
  --output-dir data/evaluation/runs/experiment-rerank `
  --methods rerank `
  --reranker-model "你的 CrossEncoder 模型名或本地路径"
```

## 标注规则

1. Query 使用企业需求或工程人员提问的真实表达，不用论文原句改写答案。
2. 标注者必须打开论文页码核对，不能只看向量相似度。
3. 每条 Query 至少有一个相关 Chunk；没有答案的问题单独进入“库内无答案”集合。
4. 至少抽取一部分 Query 由第二位标注者复核，并记录分歧。
5. 真实论文题目、Chunk 和企业数据默认只保存在本地，不提交公开仓库。

在没有完成真实人工标注之前，项目只声明“评测工具已具备”，不声明检索质量已经提升。
