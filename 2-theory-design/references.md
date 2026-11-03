# 参考文献与数据来源

以下文献按 [《理论框架与研究设计》](theory_and_design.md) 中首次出现的顺序编号。文献 [1]—[8]、[10]—[11] 为正式期刊或会议论文；[9] 为官方数据资源。书目信息以出版方记录和正式论文为依据，预印本仅作为同一研究的补充访问入口。

## 一、参考文献

### [1] 代理成本与监督

JENSEN M C, MECKLING W H. Theory of the firm: Managerial behavior, agency costs and ownership structure[J]. Journal of Financial Economics, 1976, 3(4): 305–360. DOI: 10.1016/0304-405X(76)90026-X.

- 原始来源：[期刊出版页面](https://www.sciencedirect.com/science/article/pii/0304405X7690026X)。
- 引用范围：代理成本的构成及监督需求，对应正文第 2.1 节。将其用于解释并购尽调的信息核查属于本文的场景延伸；原文没有验证 AI 合同审查或其成本收益。

### [2] 检索增强生成

LEWIS P, PEREZ E, PIKTUS A, et al. Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks[C]//Advances in Neural Information Processing Systems. Vol. 33. Curran Associates, Inc., 2020: 9459–9474.

- 原始来源：[NeurIPS 正式出版页面](https://proceedings.neurips.cc/paper/2020/hash/6b493230205f780e1bc26945df7481e5-Abstract.html)；[作者预印本](https://arxiv.org/abs/2005.11401)。
- 引用范围：检索材料与语言生成相结合的方法，对应正文第 2.2 节。本文使用合同内检索流程，未复现原文的联合训练架构，也不直接继承其任务表现。

### [3] 长上下文信息利用

LIU N F, LIN K, HEWITT J, et al. Lost in the Middle: How Language Models Use Long Contexts[J]. Transactions of the Association for Computational Linguistics, 2024, 12: 157–173. DOI: 10.1162/tacl_a_00638.

- 原始来源：[ACL Anthology 正式论文页](https://aclanthology.org/2024.tacl-1.9/)。
- 引用范围：原文在多文档问答与键值检索等任务中发现相关信息位置会影响模型表现，对应正文第 2.2、6.2 节。该结果提供实验动机，不证明本文模型具有相同程度的位置偏差或 RAG 必然优于全文输入。

### [4] 条件规则的形式化表达

SERGOT M J, SADRI F, KOWALSKI R A, et al. The British Nationality Act as a logic program[J]. Communications of the ACM, 1986, 29(5): 370–386. DOI: 10.1145/5689.5920.

- 原始来源：[ACM 出版记录](https://dl.acm.org/doi/10.1145/5689.5920)；[作者所在机构保存的正式论文](https://www.doc.ic.ac.uk/~rak/papers/British%20Nationality%20Act.pdf)。
- 引用范围：原文将部分成文法条文转化为逻辑程序，并讨论否定、例外与封闭世界假设的适用限制，对应正文第 2.3 节。本文借鉴规则显式表达的思想；四类状态、合同审核政策及 LLM 与规则的组合均为本文设计。

### [5] 行动与反馈的智能体机制

YAO S, ZHAO J, YU D, et al. ReAct: Synergizing Reasoning and Acting in Language Models[C]//The Eleventh International Conference on Learning Representations. 2023.

- 原始来源：[OpenReview 会议记录](https://openreview.net/forum?id=WE_vluYUL-X)；[作者提交的 ICLR 定稿版本](https://arxiv.org/abs/2210.03629v3)。
- 引用范围：信息处理、外部行动与观察交替更新的机制，对应正文第 2.4、3.3 节。有限补查预算、规则工具及人工升级条件为本文的任务化设计。
- 版本说明：2022 年为预印本首次提交年份；本条引用 2023 年正式会议论文，不将二者视为两项研究。会议记录未提供连续页码，故不补写页码。

### [6] 引用质量与证据支持评价

GAO T, YEN H, YU J, CHEN D. Enabling Large Language Models to Generate Text with Citations[C]//Proceedings of the 2023 Conference on Empirical Methods in Natural Language Processing. Singapore: Association for Computational Linguistics, 2023: 6465–6488. DOI: 10.18653/v1/2023.emnlp-main.398.

- 原始来源：[ACL Anthology 正式论文页](https://aclanthology.org/2023.emnlp-main.398/)。
- 引用范围：ALCE 将生成质量与引用质量分别评价，对应正文第 2.5、7.3 节。本文的字符定位、主体与例外核验及端到端成功率是面向合同审查的具体设计，与 ALCE 官方指标分别定义。

### [7] 法律领域生成结果的可靠性

DAHL M, MAGESH V, SUZGUN M, HO D E. Large Legal Fictions: Profiling Legal Hallucinations in Large Language Models[J]. Journal of Legal Analysis, 2024, 16(1): 64–93. DOI: 10.1093/jla/laae003.

- 原始来源：[期刊出版页面](https://academic.oup.com/jla/article/16/1/64/7699227)；[作者所在机构保存的正式论文](https://dho.stanford.edu/wp-content/uploads/Hallucinations_JLA.pdf)。
- 引用范围：对美国判例相关开放域问答中法律幻觉的实证研究，为独立核验提供领域动机，对应正文第 2.5 节。本文的封闭域合同审查任务与原文不同，不移用其错误率或将其结论解释为对本文系统的验证。

### [8] 商业合同审查数据集 CUAD

HENDRYCKS D, BURNS C, CHEN A, BALL S. CUAD: An Expert-Annotated NLP Dataset for Legal Contract Review[C]//Proceedings of the Neural Information Processing Systems Track on Datasets and Benchmarks. Vol. 1. 2021.

- 原始来源：[NeurIPS Datasets and Benchmarks 正式出版页面](https://datasets-benchmarks-proceedings.neurips.cc/paper/2021/hash/6ea9ab1baa0efb9e19094440c317e21b-Abstract.html)；[正式论文全文](https://datasets-benchmarks-proceedings.neurips.cc/paper_files/paper/2021/file/6ea9ab1baa0efb9e19094440c317e21b-Paper-round1.pdf)。
- 引用范围：合同来源、标注过程与识别任务，对应正文第 5、7.1、9 节。论文第 3 节报告 510 份合同、41 类标签及 13,101 个标注条款；第 4.1 节以词集合 Jaccard≥0.5 判定匹配，并使用 AUPR 及指定召回率下的精确率。
- 适用边界：条款标注不直接提供本文政策下的风险等级。本文字符区间匹配、样本子集及训练池覆盖统计均单独定义。正式出版物属于 Datasets and Benchmarks 第 1 卷，出版记录未提供连续页码。

### [9] CUAD 官方数据资源

THE ATTICUS PROJECT. Contract Understanding Atticus Dataset (CUAD)[DB/OL]. 2021[2026-11-03].

- 原始来源：[CUAD 官方仓库](https://github.com/The-Atticus-Project/cuad)；[Atticus 官方数据说明](https://www.atticusprojectai.org/cuad/)。
- 配套资源：[类别定义](https://github.com/The-Atticus-Project/cuad/blob/main/category_descriptions.csv)；[原项目评价代码](https://github.com/The-Atticus-Project/cuad/blob/main/evaluate.py)；[数据压缩包](https://github.com/The-Atticus-Project/cuad/blob/main/data.zip)。
- 引用范围：类别定义、数据结构和文件版本，对应正文第 5.1、5.3 节。[8] 与 [9] 分别为同一数据集的论文及实际数据来源，不构成两个独立数据集。官方页面标示数据采用 CC BY 4.0 许可。

### [10] 人工标注的一致性

COHEN J. A Coefficient of Agreement for Nominal Scales[J]. Educational and Psychological Measurement, 1960, 20(1): 37–46. DOI: 10.1177/001316446002000104.

- 原始来源：[SAGE 期刊出版页面](https://journals.sagepub.com/doi/10.1177/001316446002000104)。
- 引用范围：两名标注者对名义类别的一致性测量，对应正文第 5.4 节。本文对规则状态及证据支持标签使用未加权 Cohen’s κ，并同时报告原始一致率和类别分布；κ 不作为标签正确性的替代指标。

### [11] NLP 实验中的统计比较

DROR R, BAUMER G, SHLOMOV S, REICHART R. The Hitchhiker’s Guide to Testing Statistical Significance in Natural Language Processing[C]//Proceedings of the 56th Annual Meeting of the Association for Computational Linguistics (Volume 1: Long Papers). Melbourne, Australia: Association for Computational Linguistics, 2018: 1383–1392. DOI: 10.18653/v1/P18-1128.

- 原始来源：[ACL Anthology 正式论文页](https://aclanthology.org/P18-1128/)。
- 引用范围：统计方法需与任务、评价指标及实验结构相适应，对应正文第 7.4 节。以合同为单位的配对 bootstrap、重复次数及区间报告方式是本文针对合同内相关性的具体设计，不声称原文规定了本文的全部设置。

## 二、数据来源与统计口径

本研究使用 CUAD 官方公开数据，并保留原始训练与测试划分。数据结构核验确认完整文件包含 510 份合同，训练池与测试池分别包含 408 份和 102 份。五类覆盖统计仅使用训练池；11,180 个训练答案片段的位置校验与字段一致性检查通过。论文报告的标注条款数、JSON 问题记录数及本研究核验的答案片段数分别保留各自的统计口径。

正文中的训练池覆盖与文本长度依据原始数据计算，详见 [核验脚本](../CUAD/audit/audit_data.py) 及 [统计结果](../CUAD/audit/data_audit.json)。这些统计属于本研究的数据适配核验，不属于上述论文已经报告的实验结果。

## 三、文献依据与研究设计的对应关系

| 研究环节 | 文献依据 | 本文的具体设计与适用范围 |
| --- | --- | --- |
| 信息核查与监督需求 | [1] | 将审查成本与信息质量操作化；不以模型指标直接估计代理成本 |
| 检索与长文本输入 | [2]、[3] | 合同内检索、固定 RAG 基准与长文本分层评价 |
| 规则表达与不确定状态 | [4] | 独立制定审核政策、四类状态及版本管理 |
| 行动与反馈 | [5] | 有限补查、工具调用、停止与人工升级 |
| 证据支持与可靠性 | [6]、[7] | 区分定位、语义支持与政策判断，不外推其他任务的错误率 |
| 数据与条款识别 | [8]、[9] | 训练池核验、五类目标条款及字符位置匹配 |
| 人工参考标签 | [10] | 裁决前一致性评价与独立裁决记录 |
| 统计比较 | [11] | 合同级配对重采样、区间估计与重复运行波动 |
