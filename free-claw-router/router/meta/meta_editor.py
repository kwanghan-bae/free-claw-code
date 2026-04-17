from __future__ import annotations
import logging
import re
from pathlib import Path
import yaml

logger = logging.getLogger(__name__)


class MetaEditor:
    def __init__(self, base_dir: Path) -> None:
        self._base = Path(base_dir)

    def apply(self, plan) -> bool:
        if plan.edit_type == "yaml":
            return self._apply_yaml(plan)
        elif plan.edit_type == "prompt_only":
            return self._apply_prompt(plan)
        elif plan.edit_type == "config_only":
            return self._apply_config(plan)
        else:
            logger.warning("Unknown edit type: %s", plan.edit_type)
            return False

    def _apply_yaml(self, plan) -> bool:
        try:
            path = Path(plan.target_file)
            if not path.is_absolute():
                path = self._base / path
            data = yaml.safe_load(path.read_text())
            match = re.match(r"^([\w.]+)\s*=\s*(.+)$", plan.proposed_diff.strip())
            if not match:
                logger.warning("Cannot parse YAML diff: %s", plan.proposed_diff)
                return False
            key_path = match.group(1).split(".")
            value_str = match.group(2).strip()
            try:
                value = yaml.safe_load(value_str)
            except yaml.YAMLError:
                value = value_str

            obj = data
            for k in key_path[:-1]:
                if isinstance(obj, dict):
                    obj = obj.get(k)
                elif isinstance(obj, list):
                    obj = obj[int(k)]
                else:
                    logger.warning("Cannot navigate YAML path: %s", plan.proposed_diff)
                    return False
                if obj is None:
                    logger.warning("YAML path not found: %s", plan.proposed_diff)
                    return False

            final_key = key_path[-1]
            if isinstance(obj, dict):
                obj[final_key] = value
            elif isinstance(obj, list):
                obj[int(final_key)] = value
            else:
                return False

            path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
            return True
        except Exception:
            logger.warning("YAML edit failed", exc_info=True)
            return False

    def _apply_prompt(self, plan) -> bool:
        try:
            path = Path(plan.target_file)
            if not path.is_absolute():
                path = self._base / path
            content = path.read_text()
            match = re.match(r'^(\w+)\s*=\s*"""(.*)"""$', plan.proposed_diff.strip(), re.DOTALL)
            if not match:
                logger.warning("Cannot parse prompt diff: %s", plan.proposed_diff[:80])
                return False
            var_name = match.group(1)
            new_value = match.group(2)
            pattern = re.compile(rf'({re.escape(var_name)}\s*=\s*""").*?(""")', re.DOTALL)
            if not pattern.search(content):
                logger.warning("Variable %s not found in %s", var_name, path)
                return False
            content = pattern.sub(rf'\g<1>{new_value}\g<2>', content, count=1)
            path.write_text(content)
            return True
        except Exception:
            logger.warning("Prompt edit failed", exc_info=True)
            return False

    def _apply_config(self, plan) -> bool:
        try:
            path = Path(plan.target_file)
            if not path.is_absolute():
                path = self._base / path
            content = path.read_text()
            match = re.match(r'^(\w+)\s*=\s*(.+)$', plan.proposed_diff.strip())
            if not match:
                return False
            var_name = match.group(1)
            new_value = match.group(2).strip()
            pattern = re.compile(rf'^({re.escape(var_name)}\s*=\s*)(.+)$', re.MULTILINE)
            if not pattern.search(content):
                logger.warning("Config var %s not found", var_name)
                return False
            content = pattern.sub(rf'\g<1>{new_value}', content, count=1)
            path.write_text(content)
            return True
        except Exception:
            logger.warning("Config edit failed", exc_info=True)
            return False
