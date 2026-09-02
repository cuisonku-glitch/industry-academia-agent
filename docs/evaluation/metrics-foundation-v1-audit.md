# 指标底座 v1 验收记录

验收日期：2026-09-02

对应分支：`feature/metrics-extraction`

## 1. 验收范围

本检查点覆盖工作包 4～6 的第一段：研究方向分流、指标本体、单位归一、证据等级、确定性规则抽取和结果校验。它不包含 Kimi 语义补充、图像/表格理解，也不宣称已完成人工金标准准确率验收。

本次只读取本地 Chroma 向量库并将结构化结果写入被 Git 忽略的 `data/processed/metrics/`。没有调用 Moonshot/Kimi，没有把论文片段发送到外部服务。

## 2. 实现产物

- `config/research_direction_taxonomy.json`：方向标签、别名和关键词。
- `config/metric_ontology.json`：13 个指标定义、适用方向、别名、规范单位和显式换算。
- `src/extraction/direction_classifier.py`：元数据优先、关键词规则其次、可选模型兜底，并保留 `unclassified`。
- `src/extraction/metric_ontology.py`：单位字形归一、数值换算和测试条件可比性判断。
- `src/extraction/metric_extractor.py`：本地规则抽取、点值/区间保留、证据等级、页码/章节/Chunk/摘录定位、稳定 ID、结构校验和原子保存。

## 3. 本地真实样本运行结果

| 项目 | 结果 |
|---|---:|
| 本地论文 | 3 篇 |
| 已有向量 Chunk | 894 |
| 指标本体定义 | 13 |
| 本次实际命中的指标定义 | 12 |
| 生成指标记录 | 160 |
| 唯一指标 ID | 160 |
| 点值记录 | 154 |
| 区间记录 | 6 |
| `measured` | 34 |
| `reported` | 126 |
| `inferred` | 0 |
| 明确记录测试条件 | 4 |
| 负数区间端点异常 | 0 |

3 篇论文的方向均来自已有人工元数据，来源为 `metadata`，置信度为 1.0。该结果验证了来源记录和分流链路，不代表规则分类器已经达到某个准确率。

## 4. 已通过的质量检查

- 全部 107 项离线测试通过，包含方向优先级、未知方向、单位字形、单位换算、测试条件隔离、区间、千位分隔符和单位前缀误匹配等用例。
- 160 条记录 ID 全部唯一；每个文件的汇总计数与实际记录数一致。
- `20–40 keV`、`100–600 μm` 等区间保留上下界，不再被解析成负值。
- `12,028`、`16,994` 等千位数保留完整数值。
- `eV s` 等复合单位不会被截断并误认成 X 射线能量 `eV`。
- 规则通道只产生 `measured/reported`，不会把规则命中冒充为 `inferred`。
- 无测试条件或条件不同的指标不会被 `comparable_metrics` 判为可直接比较。
- 本地输出目录由 `.gitignore` 排除，不会随正常提交上传。

## 5. 已知限制与下一闸门

- 当前记录的是“可定位的证据出现位置”，同一指标在摘要、正文或文献回顾重复出现时可能保留多条，尚未做跨段落主张消歧。
- “分别为 A 和 B”一类复杂并列关系可能只捕获紧邻单位的数值；后续语义通道应补实体关系，而不是绕过校验器。
- 只有 4 条记录在近邻文本中带明确测试条件，其余记录不应被直接横向排名。
- 图表中的纯视觉数值、复杂表格和扫描页 OCR 不在本检查点范围内。
- `measured/reported` 是保守规则判断，必须抽样人工复核后才能报告证据等级准确率。
- 下一步应建立人工标注小集，分别统计抽取、单位归一和证据定位准确率；之后才接入可选 Kimi 语义补充，并进入工作包 7 的同集检索消融评测。

## 6. 复现命令

```powershell
conda activate industry_agent
$env:HF_HUB_OFFLINE="1"
python src/extraction/metric_extractor.py --preview-only
python src/extraction/metric_extractor.py
python -m unittest discover -s tests -v
```
