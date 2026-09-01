# 检索质量评测

本目录记录离线检索评测的格式和流程。评测集用于回答“检索结果是否真的变准”，不替代现有的结构校验单元测试。

## 文件格式

查询文件 `queries.jsonl` 每行是一条不含答案的真实问题：

```json
{"query_id":"q001","query":"希望探测器在低剂量下仍保持高灵敏度，哪些论文有直接实验依据？"}
```

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
python scripts/run_retrieval_eval.py --queries data/evaluation/queries.jsonl --output data/evaluation/dense-section-v2.jsonl
python scripts/evaluate_retrieval.py --qrels data/evaluation/qrels.jsonl --run data/evaluation/dense-section-v2.jsonl
```

输出包括宏平均 `Recall@K`、`MRR@K` 和 `nDCG@K`，并保留逐问题结果。

## 标注规则

1. Query 使用企业需求或工程人员提问的真实表达，不用论文原句改写答案。
2. 标注者必须打开论文页码核对，不能只看向量相似度。
3. 每条 Query 至少有一个相关 Chunk；没有答案的问题单独进入“库内无答案”集合。
4. 至少抽取一部分 Query 由第二位标注者复核，并记录分歧。
5. 真实论文题目、Chunk 和企业数据默认只保存在本地，不提交公开仓库。

在没有完成真实人工标注之前，项目只声明“评测工具已具备”，不声明检索质量已经提升。
