# 混合检索 v1 验收记录

验收日期：2026-09-02

对应分支：`feature/hybrid-retrieval`

## 1. 验收范围

本检查点覆盖工作包 7 的工程第一版：统一候选过滤、Dense 基线、BM25、RRF、可选 CrossEncoder 适配、独立运行文件、延迟/显存清单，以及同一 qrels 的自动评测入口。

本次只读取本地 3 篇论文、894 个 Chunk 和本地指标记录。没有调用 Moonshot/Kimi，没有下载 CrossEncoder，也没有把论文片段发送到外部服务。

## 2. 实现内容

- 方向过滤：使用方向 taxonomy 的封闭 ID，并保留 `unclassified`。
- 章节过滤：使用章节感知切块的封闭 `section_type`。
- 数值硬筛：输入阈值按指标本体换算到规范单位；默认只接受 `measured/reported`；多个约束按 AND 处理；区间必须整体满足门槛。
- BM25：内置中英文技术文本分词和 BM25 计算，不新增第三方依赖。
- RRF：对 Dense 与 BM25 名次做确定性融合，保留各自名次。
- 可选重排：提供 sentence-transformers CrossEncoder 适配器，但模型必须由使用者显式选择和缓存。
- 实验记录：每种方法保存独立 JSONL；manifest 保存查询文件 SHA-256、集合版本、过滤数量、P50/P95 延迟、峰值显存和质量评测状态。
- 同集评测：提供 qrels 时，全部方法使用同一份 qrels，分别保存 Recall@5/10、MRR@5/10、nDCG@5/10 和逐问题结果。

## 3. 本地真实数据工程烟测

| 项目 | 结果 |
|---|---:|
| 本地论文 | 3 篇 |
| 向量 Chunk | 894 |
| 烟测查询 | 4 条 |
| 带方向/章节/数值过滤的查询 | 3 条 |
| Dense P50 | 7.094 ms |
| Dense P95 | 120.527 ms |
| Dense 峰值 CUDA 显存 | 101.384 MB |
| BM25 P50 | 13.573 ms |
| BM25 P95 | 113.102 ms |
| BM25 峰值 CUDA 显存 | 不使用 GPU |
| RRF P50 | 20.900 ms |
| RRF P95 | 114.048 ms |
| RRF 峰值 CUDA 显存 | 101.384 MB |

耗时排除模型初次加载，包含每种方法自身的候选过滤；BM25 和 RRF 使用独立检索引擎实例，避免上一方法的词法索引缓存让后一方法虚假变快。当前样本只有 4 条，P95 实际等于最慢查询，只作为本机工程烟测，不代表规模化性能。

数值查询要求灵敏度不低于 `1000 μC Gy_air^{-1} cm^{-2}`。本地指标记录筛出 7 个满足保守硬门槛的 Chunk，Dense、BM25 和 RRF 均只在这 7 个候选内返回，未发生过滤越界。所有 run 的 Chunk ID 无重复。

## 4. 自动检查

- 117 项离线测试全部通过。
- 覆盖中英混合分词、BM25 排序、方向/章节复合 where、单位换算、默认排除 inferred、区间保守阈值、空候选短路、RRF 确定性、注入式重排和查询过滤保留。
- Python `compileall` 通过。
- `data/evaluation/` 和真实运行结果由 `.gitignore` 排除。

## 5. 质量声明与剩余人工闸门

本次 manifest 明确记录：

```json
{"status":"not_run","reason":"no_human_qrels"}
```

因此当前只能确认工作包 7 的工程管线、过滤完整性和本机性能记录可用，不能据此宣称 RRF 比 Dense 更准确。完成以下人工步骤后，才能关闭质量闸门：

1. 用真实企业/工程问题建立查询集；
2. 人工打开论文页码，对 query/chunk 标注 0/1/2；
3. 至少部分样本由第二位标注者复核；
4. 在同一 qrels 上比较 Dense、BM25、RRF 和可选 CrossEncoder；
5. 只有 Recall/MRR/nDCG 不下降且延迟/显存可接受，才启用为产品默认检索路径。

## 6. 复现命令

```powershell
conda activate industry_agent
$env:HF_HUB_OFFLINE="1"
python scripts/run_retrieval_eval.py `
  --queries data/evaluation/queries.jsonl `
  --qrels data/evaluation/qrels.jsonl `
  --output-dir data/evaluation/runs/experiment-001 `
  --methods dense bm25 rrf
python -m unittest discover -s tests -v
```
