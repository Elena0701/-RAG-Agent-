# 参考文献与数据集引用

本文件为 [《Agent、RAG、规则核验与合同初审的理论关系及研究设计》](theory_and_design.md) 提供技术定义、方法说明及数据来源的引用依据，按正文首次出现的顺序编号。[1]—[6] 为研究论文，[7] 为数据资源。

## 一、论文文献

<a id="ref-1"></a>

**[1]** LEWIS P, PEREZ E, PIKTUS A, et al. Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks[C]//Advances in Neural Information Processing Systems. Vol. 33. Curran Associates, Inc., 2020: 9459–9474.

- 来源：[NeurIPS 正式出版页面](https://proceedings.neurips.cc/paper/2020/hash/6b493230205f780e1bc26945df7481e5-Abstract.html)。
- 引用用途：检索材料与语言模型生成相结合的基本思想；本文采用这一应用思路，不声称复现原论文的训练架构。

<a id="ref-2"></a>

**[2]** SERGOT M J, SADRI F, KOWALSKI R A, et al. The British Nationality Act as a logic program[J]. Communications of the ACM, 1986, 29(5): 370–386. DOI: [10.1145/5689.5920](https://doi.org/10.1145/5689.5920).

- 来源：[ACM 出版记录](https://dl.acm.org/doi/10.1145/5689.5920)；[作者所在机构保存的正式论文](https://www.doc.ic.ac.uk/~rak/papers/British%20Nationality%20Act.pdf)。
- 引用用途：将明确条件表示为可执行规则的方法参考。本文的模拟审核政策由项目自行设定，不取自该文的法律规定。

<a id="ref-3"></a>

**[3]** YAO S, ZHAO J, YU D, et al. ReAct: Synergizing Reasoning and Acting in Language Models[C]//The Eleventh International Conference on Learning Representations. 2023.

- 来源：[OpenReview 会议记录](https://openreview.net/forum?id=WE_vluYUL-X)；[作者提交的 ICLR 定稿版本](https://arxiv.org/abs/2210.03629v3)。
- 引用用途：工具调用、观察与后续行动的组织思想。合同检查清单、补查和人工转交是本文面向初审任务的具体安排。
- 版本说明：引用 2023 年正式会议版本；2022 年预印本属于同一研究。

<a id="ref-4"></a>

**[4]** LIU N F, LIN K, HEWITT J, et al. Lost in the Middle: How Language Models Use Long Contexts[J]. Transactions of the Association for Computational Linguistics, 2024, 12: 157–173. DOI: [10.1162/tacl_a_00638](https://doi.org/10.1162/tacl_a_00638).

- 来源：[ACL Anthology 正式论文页](https://aclanthology.org/2024.tacl-1.9/)。
- 引用用途：能够接收长文本与恰当利用其中信息之间的区别。原文任务包括多文档问答和键值检索，其结果不直接代表本项目的合同审查表现。

<a id="ref-5"></a>

**[5]** GAO T, YEN H, YU J, CHEN D. Enabling Large Language Models to Generate Text with Citations[C]//Proceedings of the 2023 Conference on Empirical Methods in Natural Language Processing. Singapore: Association for Computational Linguistics, 2023: 6465–6488. DOI: [10.18653/v1/2023.emnlp-main.398](https://doi.org/10.18653/v1/2023.emnlp-main.398).

- 来源：[ACL Anthology 正式论文页](https://aclanthology.org/2023.emnlp-main.398/)。
- 引用用途：引用质量及其对回答的支持关系，为核对合同原文与模型整理的信息提供方法依据。

<a id="ref-6"></a>

**[6]** HENDRYCKS D, BURNS C, CHEN A, BALL S. CUAD: An Expert-Annotated NLP Dataset for Legal Contract Review[C]//Proceedings of the Neural Information Processing Systems Track on Datasets and Benchmarks. Vol. 1. 2021.

- 来源：[NeurIPS Datasets and Benchmarks 正式出版页面](https://datasets-benchmarks-proceedings.neurips.cc/paper/2021/hash/6ea9ab1baa0efb9e19094440c317e21b-Abstract.html)；[正式论文全文](https://datasets-benchmarks-proceedings.neurips.cc/paper_files/paper/2021/file/6ea9ab1baa0efb9e19094440c317e21b-Paper-round1.pdf)。
- 引用用途：CUAD 的建设背景与条款识别任务。论文与下列发布资源属于同一个数据集。

## 二、数据集引用及访问入口

<a id="ref-7"></a>

**[7]** THE ATTICUS PROJECT. Contract Understanding Atticus Dataset (CUAD), v1[DB/OL]. Hugging Face[2026-11-04]. [CUAD_v1 数据目录](https://huggingface.co/datasets/theatticusproject/cuad/tree/main/CUAD_v1).

- 发布账号与路径：`theatticusproject/cuad` 中的 `CUAD_v1/`。
- 官方说明：[CUAD_v1_README.txt](https://huggingface.co/datasets/theatticusproject/cuad/blob/main/CUAD_v1/CUAD%20v1%20ReadMe%20_%20Datasheet/CUAD_v1_README.txt)；[README 与 Datasheet 所在目录](https://huggingface.co/datasets/theatticusproject/cuad/tree/main/CUAD_v1/CUAD%20v1%20ReadMe%20_%20Datasheet)。
- 版本记录：[文件上传提交](https://huggingface.co/datasets/theatticusproject/cuad/commit/a3c393f5d103fd0c516374e4fdff676c8176dcb1)，完整提交号为 `a3c393f5d103fd0c516374e4fdff676c8176dcb1`。
- 许可标识：Hugging Face 页面标示为 `CC BY 4.0`，使用时保留来源与作者署名。

| 文件或目录 | 内容 |
| --- | --- |
| `CUAD_v1.json` | SQuAD 风格的合同文本与条款问答标注 |
| `full_contract_txt/` | 合同纯文本原文 |
| `full_contract_pdf/` | 合同 PDF 原文 |
| `master_clauses.csv`、`master_clauses.xlsx` | 合同、条款片段及人工整理答案的汇总材料 |
| `label_group_xlsx/` | 按标签组组织的标注材料 |
| `CUAD v1 ReadMe _ Datasheet/` | 数据组成、类别定义及说明 |

“510 份合同、41 类条款”是官方说明中的数据集概况，不是本项目已经处理的样本量。本研究设置 11 类信息识别任务，其中六类进入政策检查的候选范围。实际实验样本与评价范围在实验记录中说明；CUAD 标注不提供本项目政策下的风险等级。

现有候选清单使用官方 GitHub 数据包中的 `CUADv1.json`，与 Hugging Face 目录的 `CUAD_v1.json` 文件名不同。正式运行时应记录实际使用的文件、版本与合同标识，并核对原文及标注；不能仅凭名称相近就认定两个文件或 PDF 提取文本的偏移完全相同。

## 三、方法说明、演示与实测结果的区分

本文围绕合同初审任务解释技术的作用机制。正文与流程图使用 90 天通知期与 60 天政策阈值的演示示例；中等级和人工复核要求取自当前 `NOTICE-001` 配置。该示例不是本次实测结果。上述阈值不代表法律要求或行业惯例。

研究假设与实验设计属于待验证的研究安排，不包含本轮实验成绩。已有检索模块的局部测试不能代替完整 Agent 的四组对照结果，模型内部核验通过率也不能直接视为独立人工评价的引用正确率。
