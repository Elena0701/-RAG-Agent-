# 历史报告清理说明

清理日期：2026年11月26日。按使用者指定的页面条目清理，未调用模型API。

## 保留的四份报告

| 报告 | 保留原因 |
| --- | --- |
| `CUAD-004_7afb02da` | 正式端到端案例，41类完整运行及其原生产物 |
| `CUAD-001_d0873843` | CUAD-001有完整元数据的运行，正式案例文档已引用 |
| `CUAD-008_ba9c81fe` | 五类否定答案/覆盖分析的真实运行 |
| `demo_contract_4bb14120` | 网页真实联调记录，截图中名称为demo_contract.txt；未被点名删除，保留避免扩大范围 |

两份CUAD-001使用同一合同，属于不同运行，不是同一个JSON副本。此次只保留d0873843，删除0d3c8517及其配套运行文件。没有设置以后同名合同一律删除的规则，新审查仍保存独立记录。

## 删除范围与核对方式

删除六个明确ID的运行：

```text
CUAD-001_0d3c8517
002_CENTRACKINTERNATIONALINC_10_29_1999-EX-10.3-WEB SITE HOSTING AGREEMENT_1f27ab3b
demo_contract_7a798dfd
demo_contract_e57f60d1
demo_contract_dfd465c1
demo_contract_b48b4904
```

每个ID删除原生报告、conversation、checkpoint及唯一对应的JSONL，共 **24个文件**。报告/对话/断点的内部document_id必须与文件名一致；JSONL只有在全部消息与该次conversation完全一致时才删除。每个文件的路径、角色、大小、SHA-256和匹配依据写入清理清单。

脚本先生成计划，再对所有绝对路径和哈希重新核对，逐文件删除，不递归删除目录、不按demo或CUAD等宽泛关键词删除，也没有在其他目录复制已删除原报告。清理前后对118个非目标文件进行了哈希保护检查，全部一致。

## 明确保留的其他文件

以下三个JSONL无法可靠归属到指定运行，没有删除：

```text
4-agent/code/outputs/conversations/28bce4760ab148e88831e79be4afd3a7.jsonl
4-agent/code/outputs/conversations/70528eeb72944ea18f1befbbdd3566ab.jsonl
4-agent/code/outputs/conversations/84e219d5fc4a443492d4103b0b7b1738.jsonl
```

同样保留：CUAD数据与10份上传TXT、人工标注、合同输入文件、Agent核心代码、虚拟环境、API配置、模型缓存、保留运行的全部文件、其他中断运行、受控失败测试和混合审计记录。合同输入属于源文件，不按“配套运行产物”擅自删除；demo输入还由保留的4bb14120运行及测试使用。

## 网页及文档调整

- 首页重新扫描实际报告；已删除报告请求返回404，失效缓存被清除。
- 点击历史刷新时，如果当前报告已删除，会切换到仍存在的案例；不存在的演示来源组不再显示。
- CUAD-001在当前下拉列表只出现一次。
- 测试不再依赖已删除的认证失败报告，技术异常分类改为明确标注的受控输入测试。
- 失败分析及治理文档仅补充原始证据删除说明，保留历史分析文字；不再把该认证异常作为可回放证据。CUAD正式案例内容保持不变。

详细记录位于：

```text
7-case-governance/results/history_cleanup/proposed_plan.json
7-case-governance/results/history_cleanup/cleanup_manifest.json
7-case-governance/results/history_cleanup/verification.json
```

清理脚本为`7-case-governance/scripts/cleanup_history.py`。默认仅生成计划，`--apply`才执行；已完成后重复执行不会再次删除其他文件。它不是网页上的通用删除按钮，也不会自动清理未来新增记录。

启动方式仍见[START_HERE](START_HERE.md)。更新后需停止自己启动的旧服务、重新启动并刷新浏览器，避免旧进程仍显示内存中的旧列表。


## 本次清理后验收

实际通过14项报告接口测试、11项任务测试、36项网页基础回归、131项逐页检查，以及14项删除专项浏览器检查。保留的4份报告均可打开；CUAD-001下拉项仅一份；删除项访问返回404；旧缓存选择刷新后切换到保留案例。验收调用模型0次，受控表单记录已从隔离目录清除。

验证了24个目标文件全部不存在，118个保护文件哈希未变，3个不确定JSONL仍在；case_01.md内容未改。failure_cases.md和limitations_and_governance.md仅更新旧证据已删除的说明。旧整篇文稿生成器增加缺失证据保护，会明确停止而不是补造数据或覆盖现有文档。

网页实际截图见`qa/history_cleanup_history.png`；完整机器核验见`results/history_cleanup/verification.json`。本轮验收服务已停止，请在旧服务终端按Ctrl+C后，按START_HERE中的命令重新启动并刷新浏览器。
