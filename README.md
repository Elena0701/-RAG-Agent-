# 基于 RAG 与规则核验的商业合同初审 Agent

金融人工智能课程小组项目。基于 CUAD 合同数据，集成条款检索、模型事实抽取、证据位置与语义核验、业务政策规则、有限补查和人工复核，并提供“明契”中文合同初审工作台。

当前集成 Agent 支持 PDF / TXT 输入和 Q1–Q41 共 41 类条款，可选择部分条款执行。命令行与实时网页共用 4-agent/code/ 的审查逻辑。自动接收表示自动流程通过，不等同于合同没有法律风险；项目政策也不等同于法律结论。

## 选择使用方式

- **只看成果、演示交互：**下载 [独立展示 HTML](7-case-governance/web/showcase/dist/index.html) 的原始文件，用 Chrome / Edge 双击打开。已内置 CUAD-001、CUAD-004、CUAD-008 的合同、真实报告和回放记录，不需要 Python、API 或邀请码，原作者电脑也无需开机。支持筛选、证据定位、回放、打印和本地意见；选择 TXT 只匹配已有报告，不审查任意新合同。
- **在自己电脑审查新合同：**下载整个仓库，安装依赖、配置自己的模型服务、创建本机邀请码并启动 Python 后端，具体步骤见下文。下载源码后可以独立运行，模型调用费用由本机配置的账户承担。
- **访问组员启动的实时网站：**同一允许互访的可信局域网内，使用主机提供的 GROUP_URL 和邀请码。访问者无需安装 Python，主机需要保持开机和服务运行，模型费用由主机账户承担。

GitHub 文件预览页不是运行中的网站；上传源码不会自动部署 Python 后端。templates/index.html 是 Flask 模板，不能替代独立展示 HTML。独立 HTML 可静态托管，但托管本身不会赋予其新合同审查能力。

## 下载与本地启动实时网站（Windows / PowerShell）

安装 Python 3.12 和 Git，在准备保存项目的目录执行。也可在 GitHub 点击 **Code → Download ZIP** 并解压，然后进入解压后的仓库根目录，从创建环境步骤开始。

~~~powershell
git clone https://github.com/Elena0701/-RAG-Agent-.git
cd .\-RAG-Agent-

py -3.12 -m venv .\4-agent\code\.venv
& .\4-agent\code\.venv\Scripts\python.exe -m pip install -r .\4-agent\code\requirements-lock.txt
& .\4-agent\code\.venv\Scripts\python.exe -m pip install -r .\7-case-governance\web\requirements.txt

Copy-Item .\4-agent\code\.env.example .\4-agent\code\.env
Copy-Item .\4-agent\code\tools\rag_tool\deepseek.local.env.example .\4-agent\code\tools\rag_tool\deepseek.local.env
~~~

复制模板仅需首次执行，已有配置时直接编辑，避免覆盖。用文本编辑器填写两个本地配置文件：

- **4-agent/code/.env**：事实抽取的 OPENAI_API_KEY、OPENAI_BASE_URL、LLM_MODEL。
- **4-agent/code/tools/rag_tool/deepseek.local.env**：证据语义核验的 DEEPSEEK_API_KEY、DEEPSEEK_BASE_URL、DEEPSEEK_MODEL 等。变量前缀沿用现有实现；服务与模型兼容要求见 [Agent 配置说明](4-agent/code/README.md#4-配置两个模型服务)。

密钥由各自服务提供方取得，不随仓库提供。首次真实审查通常还需联网下载默认 Embedding 模型 sentence-transformers/multi-qa-MiniLM-L6-cos-v1，已有本地缓存后可复用。完整配置、兼容范围和依赖版本说明以 Agent 文档为准。

仍在仓库根目录执行：

~~~powershell
# 创建本机管理员邀请码，保管命令输出的邀请码
& .\4-agent\code\.venv\Scripts\python.exe -B .\7-case-governance\web\manage_access.py create --name '本机管理员' --role admin --days 30 --max-clauses 41 --daily-limit 5

# 启动实时网站
& .\4-agent\code\.venv\Scripts\python.exe -B -u .\7-case-governance\web\app.py --port 8766
~~~

浏览器打开 <http://127.0.0.1:8766>，点击“邀请码登录”，上传 PDF 或 UTF-8 TXT（单文件不超过 10 MB），选择条款后启动。建议首次选择 1–2 类验证配置。安装和配置完成后也可双击 7-case-governance/web/start_realtime.cmd 启动。终端按 Ctrl+C 停止服务。

新下载的实时网站没有预装历史报告，历史列表可能为空；独立 HTML 内置的案例不会自动导入后端。邀请码和身份数据库属于各台主机，不能跨主机直接复用。

局域网共享使用 start_shared.cmd 或在启动命令末尾添加 --lan，并按 [Web 运行说明](7-case-governance/web/README.md) 创建成员邀请码。添加 --offline 则禁止新模型任务，仅回放本机已有历史；它仍需要 Python 服务，也不会自动生成报告。

## 命令行审查与执行流程

完成上述 Agent 环境与模型配置后，在仓库根目录执行：

~~~powershell
Push-Location .\4-agent\code
& .\.venv\Scripts\python.exe main.py --list-clauses
& .\.venv\Scripts\python.exe main.py 'D:\contracts\example.txt' --clauses Q3 Q5 Q17
Pop-Location
~~~

将示例路径替换为自己的合同。省略 --clauses 默认审查全部 41 项；PDF 同样传入文件路径。流程为：解析与分块 → 混合检索 → 事实抽取 → 证据位置、语义与否定覆盖核验 → 业务政策判断 → 接收、补查或转人工。

默认每项最多补查 2 次。支持逐项断点保存及 --resume 恢复，详见 [Agent 完整说明](4-agent/code/README.md) 和 [断点恢复速查](4-agent/code/RUNNING.md)。Q1–Q5 不执行业务规则核验；其他类别的规则接口覆盖也不代表全部均有自动风险评级政策。

## 项目目录与阅读入口

- **1-problem-data/**：研究问题、CUAD 数据说明、样本草案和第一章 Word；入口为 [problem_and_data.md](1-problem-data/problem_and_data.md) 与 [来源与口径说明](1-problem-data/第一章_来源与口径说明.md)。
- **2-theory-design/**：理论、研究设计、参考文献和流程图；入口为 [theory_and_design.md](2-theory-design/theory_and_design.md)。
- **3-risk-rules/**：独立六类规则模块、政策配置和接口文档；入口为 [规则模块 README](3-risk-rules/README.md)。与 Agent 内集成规则副本分别维护，不应假定完全相同。
- **4-agent/**：41 类集成 Agent、测试、依赖、配置示例、流程图及第四部分 Word；代码入口为 [main.py](4-agent/code/main.py)。
- **5-retrieval-evidence/**：独立 RAG 模块、联调文档、检索评测脚本与历史 JSON 结果；入口为 [RAG README](5-retrieval-evidence/README.md)。Agent 使用自身 tools/rag_tool/ 副本，独立模块改动不会自动同步到集成版。
- **6-experiments/**：基准实验设计与 [第六章结果分析](6-experiments/第六章%20基准实验与结果分析.md)。
- **7-case-governance/**：完整案例、失败案例、治理局限、实时 Web 源码和独立展示 HTML；入口为 [case.md](7-case-governance/case.md) 和 [Web README](7-case-governance/web/README.md)。
- **8-slides-integration/**：已提交的 [第一组汇报 PDF](8-slides-integration/金融人工智能小组汇报-第一组.pdf)。

逐文件列表见 [文件清单](文件清单.md)；原成员分工、时间安排及当前交付核对见 [分工与 GitHub 提交清单](分工与GitHub提交清单.md)。清单区分已提交文件、历史计划名称和未随源码提交的本地材料。

## 实验结果的使用口径

当前系统支持 41 类，不代表所有实验均使用 41 类。成员 6 的完整 Agent 对照实验采用 102 份合同的 11 类条款；成员 5 的 41 类检索回顾性评估采用 102 份合同、4,182 个合同—类别组合，以 2,643 个有效标注区间计算召回与定位指标，见 [检索评测结果说明](5-retrieval-evidence/results/README.md)。检索指标不等于最终审查准确率。

检索结果目录同时保留旧 11 类、不同版本和不同统计口径的历史文件。官方 test 拆分曾在开发期间被查看，相关结果属于历史回放／回顾性评估，不应称为未见盲测；引用时须注明类别范围、版本、样本和指标口径。第六章已有结果文字，但本仓库 6-experiments/ 尚未附其对应逐条实验原始记录和脚本，不能仅凭文字宣称已可完整复现。

## 数据、输出与提交边界

- 仓库未包含完整 CUAD 原始数据、虚拟环境、模型权重、真实 API 密钥、身份数据库及大部分原生历史运行目录；复现实验需另行准备合法来源的数据。
- CLI 在 4-agent/code/outputs/ 生成报告、对话及断点；Web 新任务保存在 7-case-governance/results/web_runs/<任务ID>/，人工意见另存于 7-case-governance/web/data/reviews/。
- 独立展示 HTML 是例外：内嵌三份案例合同、报告和回放记录，随文件公开，不受实时网站的邀请码保护；本地演示意见不改写原始报告。
- 实时审查向配置的模型服务发送候选片段及核验所需全文。请按数据授权使用；密钥、上传合同、邀请码数据库及本地运行输出不应提交 GitHub。
