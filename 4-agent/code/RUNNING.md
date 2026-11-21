# 运行与断点恢复

在 PowerShell 中进入项目目录并激活环境：

```powershell
cd D:\agents\contract-review-agent
D:\agents\agent-env\Scripts\Activate.ps1
python main.py "合同文件.txt"
```

默认审查 41 项；可用 `--clauses Q3 Q5 Q17` 选择任务，`--list-clauses` 查看编号。

每项结束（自动接收或转人工）后，程序原子保存一个断点文件，位置在
`outputs\checkpoints\{document_id}.checkpoint.json`，终端也会显示具体路径。
按 Ctrl+C 或进程中断后，在原命令末尾添加：

```powershell
python main.py "合同文件.txt" --resume "outputs\checkpoints\实际文件名.checkpoint.json"
```

若原运行指定了 `--clauses`、`--model`、`--top-k`、`--max-retries` 或 `--policy`，
恢复时须使用相同设置。合同内容、任务范围、模型、代码或审查配置变化时会拒绝恢复。
已有的终态任务（包括转人工）会跳过，尚未完成的那一项从头运行；恢复时重新构建检索索引。
不传 `--resume` 就会开始独立的新一轮审查。

最终 JSON 报告及对话记录继续保存在 `outputs\reports`。
运行过程的用户输入和进度输出还会即时追加到 `outputs\conversations\*.jsonl`，
即使进程中断也保留已写入内容；恢复运行生成新的过程记录。

41 类的判定范围统一维护在 `tools/clause_definitions.py`，抽取和核验读取同一份定义。
单项报告中的 `stage_error` 标明异常阶段；`attempt_history` 保留各轮候选答案及核验结果。
