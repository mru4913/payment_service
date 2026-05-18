"""Backend 文件存储便捷接口（绑定 settings 配置）。"""

from .local import resolve_file_ref, save_upload

__all__ = ["resolve_file_ref", "save_upload"]
