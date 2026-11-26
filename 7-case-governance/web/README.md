# 明契 · 商业合同初审工作台

基于现有Agent的Flask后端与原生HTML/CSS/JavaScript界面，支持PDF/TXT上传、41类条款选择、真实执行进度、报告与证据定位、人工复核及已有历史回放。核心审查逻辑复用`4-agent/code/`，未重写RAG、抽取、核验或规则引擎。

本目录只提交运行必需文件和启动说明，不包含旧运行日志、测试报告、测试脚本、合同全文、人工标注、API配置、邀请码、数据库、虚拟环境、模型缓存或HTML/ZIP展示成品。请下载整个仓库并保持目录结构，不能只下载HTML模板。

## 1. 文件用途

| 文件或目录 | 作用 |
|---|---|
| `app.py` | Flask入口、网页及HTTP接口 |
| `task_manager.py`、`agent_worker.py` | 上传校验、后台调用既有Agent、真实进度与结果保存 |
| `report_store.py` | 读取真实报告、统计及证据位置，检查文本坐标 |
| `access_control.py`、`manage_access.py` | 邀请码登录、会话、额度与本机管理命令 |
| `sharing_network.py` | 局域网访问地址识别 |
| `templates/`、`static/` | 中文界面、交互、证据高亮与打印 |
| `requirements.txt` | 新增网页依赖Flask |
| `start_realtime.cmd`、`start_shared.cmd` | Windows本机与局域网启动 |
| `.gitignore` | 排除本地数据、凭据、数据库及缓存 |

## 2. 在已有环境启动

在项目根目录打开PowerShell。已有成员4虚拟环境时，仅在尚未安装Flask的情况下安装网页依赖：

```powershell
& .\4-agent\code\.venv\Scripts\python.exe -m pip install -r .\7-case-governance\web\requirements.txt
& .\4-agent\code\.venv\Scripts\python.exe -B -u .\7-case-governance\web\app.py --port 8766
```

浏览器打开`http://127.0.0.1:8766`。也可双击本目录`start_realtime.cmd`。终端按`Ctrl+C`停止，关闭浏览器不会停止服务；服务运行期间需要保持主机和终端开启。

启动与查看历史不会调用模型。上传合同并确认启动真实审查后，才使用后台配置调用API。密钥不应交给浏览器或提交GitHub。

## 3. 登录及真实审查

新下载的源码不包含现成邀请码。在项目根目录执行以下命令生成本机管理员邀请码；只显示此次生成的明文，请自行保管：

```powershell
& .\4-agent\code\.venv\Scripts\python.exe -B .\7-case-governance\web\manage_access.py create --name '本机管理员' --role admin --days 30 --max-clauses 41 --daily-limit 5
```

打开网页，点击“邀请码登录”。上传PDF或UTF-8 TXT合同，单个文件不超过10 MB；只需要合同正文，不需要人工标注。选择条款、top-k及最多补查次数，确认调用规模后启动。建议先选1—2类测试，避免直接执行全部41类。

网页展示真实后台状态，不模拟进度。完成后可查看报告、点击证据定位原文、导出JSON或打印。缺少可靠原文或位置映射时只显示引文与记录位置，不强行高亮；TXT不显示虚构PDF页码。

Q1—Q5不执行业务规则核验，其他类别的规则接口也不等于均可自动评级。候选答案、证据状态、规则结果和最终决策分别展示，自动接收不等于专业法律确认。

## 4. 在另一台电脑运行

新电脑没有现成环境时，安装Python 3.12、下载整个仓库，在项目根目录执行：

```powershell
py -3.12 -m venv .\4-agent\code\.venv
& .\4-agent\code\.venv\Scripts\python.exe -m pip install -r .\4-agent\code\requirements-lock.txt
& .\4-agent\code\.venv\Scripts\python.exe -m pip install -r .\7-case-governance\web\requirements.txt
```

按[成员4说明](../../4-agent/code/README.md)在该电脑配置事实抽取和证据语义核验服务，首次实时审查还需准备Embedding模型；然后按第2、3节启动和生成本机邀请码。不要复制其他人的密钥或虚拟环境，已有可用环境的电脑无需重建。

独立运行时，模型费用由该电脑配置的账户承担。不同电脑使用各自的身份数据库，另一台主机的邀请码不能直接复用。

## 5. 一台主机供小组访问

组员与主机在允许互访的可信网络时，双击`start_shared.cmd`，或执行：

```powershell
& .\4-agent\code\.venv\Scripts\python.exe -B -u .\7-case-governance\web\app.py --port 8766 --lan
```

组员使用终端显示的相应`GROUP_URL`访问。管理员可生成独立成员邀请码：

```powershell
& .\4-agent\code\.venv\Scripts\python.exe -B .\7-case-governance\web\manage_access.py create --name '小组成员' --days 7 --max-clauses 5 --daily-limit 3
```

通过主机访问的组员无需输入API密钥或安装Python，但主机必须保持运行，费用由主机后台账户承担。这是局域网共享，不是公网部署；仅上传GitHub源码不会生成可执行Python后端的公网网址。

## 6. 历史材料与输出

源码不预装真实报告和合同，首次下载后历史列表可以为空。有经授权的材料时，保持相对目录放置原生报告：

```text
4-agent/code/outputs/reports/*.json
7-case-governance/results/CUAD-*/reports/*.json
7-case-governance/results/web_runs/*/reports/*.json
```

CUAD合同原文放在`7-case-governance/contracts/CUAD-*.txt`。对应运行目录可另存元数据、对话和坐标映射。只有报告而没有可信原文时，不能恢复完整原文高亮。重新放置历史后可在网页中刷新历史列表；已登录管理员可查看，后续材料不会自动变成公开记录。

新增任务保存在`7-case-governance/results/web_runs/<任务ID>/`；人工意见单独保存在`web/data/reviews/`，不修改原始Agent报告。以上运行数据保持本地，不随源码上传。

若只需回放并默认禁止新审查，可添加`--offline`启动。该模式不自动生成历史报告。独立交互式HTML展示包如另行提供，可以离线回放，但不能对任意新合同执行AI审查。
