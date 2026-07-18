import importlib
from src.core.config import config


def __getattr__(name):
    module = importlib.import_module(
        f"src.core.prompt_templates.prompt_template_{config.prompt_template}"
    )
    return getattr(module, name)
