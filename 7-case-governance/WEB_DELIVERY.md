# 明契网站：GitHub提交内容与运行说明

本模块的三份分析文档之外，网站交付包含`web/`中的Python后端、HTML模板、CSS/JavaScript、依赖清单、启动脚本、测试和独立HTML展示版构建源码。网站复用`4-agent/code/`，请下载整个仓库并保留目录结构，不能只复制一个HTML模板运行实时审查。

## 1. 本次提交的内容

| 文件或目录 | 作用 |
|---|---|
| `web/app.py` | Flask入口、页面及HTTP接口 |
| `web/task_manager.py`、`web/agent_worker.py` | 上传校验、后台任务、调用现有Agent、真实进度及结果保存 |
| `web/report_store.py` | 读取真实报告、计算统计、解释证据位置及文本映射 |
| `web/access_control.py`、`web/manage_access.py` | 邀请码、会话、额度及本机管理员命令 |
| `web/sharing_network.py` | 局域网地址识别 |
| `web/templates/`、`web/static/` | 明契中文界面、证据高亮、运行过程、人工复核及打印样式 |
| `web/requirements.txt` | 新增网页依赖Flask；Agent依赖由成员4维护 |
| `web/start_realtime.cmd`、`web/start_shared.cmd` | Windows本机启动及局域网启动 |
| `web/tests/`及测试说明 | 接口、权限、任务保护及展示版检查代码；部分验收需要另行准备真实历史材料 |
| `web/showcase/`中的构建源码 | 将本地已保存的真实案例生成独立交互式HTML，不产生模型调用 |
| `scripts/prepare_contracts.py` | 从另行取得的CUAD数据中提取样本及分离人工标注 |
| `.gitignore`、`web/.gitignore` | 排除本地配置、上传数据、运行结果、数据库与缓存 |

完整功能与原有验收说明见[网页README](web/README.md)，共享方式见[共享指南](web/SHARING_GUIDE.md)。历史验收报告记录当时的测试范围，不表示本次上传重新进行了付费审查。

## 2. 不提交的本地文件

本次不提交`.env`及本机配置、API密钥、邀请码明文、登录数据库、人工复核记录、上传合同、运行日志、`results/`、完整CUAD数据、gold标注、虚拟环境、模型缓存、`web/data/`、`web/qa/`及Python缓存。

`web/showcase/dist/index.html`和`MingQi_HTML_Showcase.zip`内置三份合同全文与真实报告，继续保留在本地，不随此次公开源码提交。老师如需无需Python的交互演示，可另行接收经核对的展示包。公开源码仓库中没有预装这些历史材料，首次下载后历史列表可能为空，这不代表网站启动失败。

提交源码不会自动部署网站，也不会自动获得一个可公开实时审查的网址。GitHub静态页面服务不能执行本项目的Python Agent后端。

## 3. 在已有环境中启动

在项目根目录打开PowerShell。已有成员4虚拟环境时，只安装尚未安装的网页依赖：

```powershell
& .\4-agent\code\.venv\Scripts\python.exe -m pip install -r .\7-case-governance\web\requirements.txt
& .\4-agent\code\.venv\Scripts\python.exe -B -u .\7-case-governance\web\app.py --port 8766
```

浏览器打开`http://127.0.0.1:8766`。也可以双击`web/start_realtime.cmd`。终端按`Ctrl+C`停止；本机服务需要保持电脑及进程运行。

启动、查看界面或回放历史不调用模型；登录后上传合同、选择条款并确认启动真实审查才会调用已配置的模型服务。

## 4. 在组员的新电脑独立运行

本节仅针对没有现成环境的新电脑，不需要在已能运行的成员7电脑重建环境。

1. 下载整个仓库，安装Python 3.12，在项目根目录打开PowerShell。
2. 建立该电脑自己的环境并安装现有Agent及网页依赖：

```powershell
py -3.12 -m venv .\4-agent\code\.venv
& .\4-agent\code\.venv\Scripts\python.exe -m pip install -r .\4-agent\code\requirements-lock.txt
& .\4-agent\code\.venv\Scripts\python.exe -m pip install -r .\7-case-governance\web\requirements.txt
```

3. 按[成员4运行说明](../4-agent/code/README.md)在本机配置事实抽取和证据语义核验服务，不提交真实配置。首次实时审查还需要准备Embedding模型。仅运行网页及查看已有历史无需模型API。
4. 生成本机管理员邀请码，并启动：

```powershell
& .\4-agent\code\.venv\Scripts\python.exe -B .\7-case-governance\web\manage_access.py create --name '本机管理员' --role admin --days 30 --max-clauses 41 --daily-limit 5
& .\4-agent\code\.venv\Scripts\python.exe -B -u .\7-case-governance\web\app.py --port 8766
```

终端只在创建时显示邀请码明文，请私下保管。不同电脑的独立服务使用各自的身份数据库及API配置；不能沿用另一台主机的邀请码。模型费用由实际运行主机的后台账户承担。

网页上传只需要PDF或UTF-8 TXT合同，不需要人工标注。首次联调建议选择少量条款，避免直接执行全41类。

## 5. 通过一台主机共享

组员与主机处于允许互访的可信网络时，可双击`web/start_shared.cmd`，或使用：

```powershell
& .\4-agent\code\.venv\Scripts\python.exe -B -u .\7-case-governance\web\app.py --port 8766 --lan
```

组员使用终端显示的相应`GROUP_URL`，并领取主机生成的个人邀请码。组员无需输入API密钥，也无需在自己的电脑安装Python，但主机需要保持运行。这是局域网共享，不是公网部署。

## 6. 历史回放与独立HTML

如需在新电脑恢复已有案例，应通过经授权的独立材料包保留相对目录：原生报告放在`results/CUAD-*/reports/`，合同TXT放在`contracts/`，可选的元数据、对话、补查记录及位置映射放在对应运行目录。仅有JSON通常不足以恢复完整原文高亮；缺少可信原文时页面只展示引文及记录位置。

另行取得完整CUAD原始数据后，可先按`prepare_contracts.py --help`及[案例说明](case.md)准备三份样本。该脚本不运行Agent、不调用模型；gold仅用于事后评价。构建独立展示版还需要既有真实报告和相关阅读材料，源码不会替使用者虚构这些材料。

```powershell
& .\4-agent\code\.venv\Scripts\python.exe -B .\7-case-governance\web\showcase\build_showcase.py
```

已有完整材料时，按[展示版说明](web/showcase/README.md)生成并检查HTML及ZIP。独立HTML可离线回放真实案例，但不能对任意新合同执行AI审查。

## 7. 测试与输出

接口、任务及权限测试使用隔离目录和模拟进程，不用于代替真实模型效果评价：

```powershell
& .\4-agent\code\.venv\Scripts\python.exe -B -m unittest discover -s .\7-case-governance\web\tests -p test_tasks.py
& .\4-agent\code\.venv\Scripts\python.exe -B -m unittest discover -s .\7-case-governance\web\tests -p test_access.py
```

`test_app.py`依赖已有CUAD-004真实报告及补充分析；`test_showcase.py`还依赖已生成的展示包。没有这些本地材料时，不应将相应测试失败描述为Agent准确率下降。浏览器验收脚本另需其运行时及浏览器依赖，网页本身不需要Node或前端构建工具。

新增审查保存在`results/web_runs/<任务ID>/`；人工意见保存在`web/data/reviews/`，与原始Agent报告分开。单份合同及原始运行记录不会因上传网站源码而自动公开。

本次上传前于2026年11月26日重新执行：任务测试13项、权限测试19项、历史报告及页面接口测试16项，共48项通过，未调用模型。另核对远端仓库中的43个Agent文件与本地字节一致；此次提交不修改这些核心文件。上述软件检查不能解释为模型准确率或新的真实合同审查结果。
