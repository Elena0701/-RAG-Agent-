"""正式规则模块；从模块根目录使用 from rules import RuleTool。"""

from .rule_tool import RuleTool, load_config

__all__ = ["RuleTool", "load_config"]
