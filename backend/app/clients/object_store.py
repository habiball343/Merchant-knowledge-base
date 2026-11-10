"""文件存储：保存上传的原始文件和资料中的图片，并给出可在页面上访问的地址。

默认实现把文件放在本地磁盘，由后端的 /api/files 路由对外提供；
替换成 S3 兼容的对象存储时，实现同样的四个方法即可。
"""
import shutil
from pathlib import Path, PurePosixPath


class LocalObjectStore:
    def __init__(self, root: Path, public_prefix: str = "/api/files"):
        self.root = Path(root).resolve()
        self.public_prefix = public_prefix.rstrip("/")
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, key: str) -> Path:
        """把对象键解析为本地路径，拒绝任何跳出存储根目录的键。"""
        parts = PurePosixPath(key.replace("\\", "/")).parts
        if not parts or any(part in ("..", "/", "") for part in parts) or PurePosixPath(key).is_absolute():
            raise ValueError(f"非法的文件路径：{key}")
        path = self.root.joinpath(*parts).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError(f"非法的文件路径：{key}")
        return path

    def save_bytes(self, key: str, data: bytes) -> str:
        path = self.resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return self.url(key)

    def save_file(self, key: str, source: Path) -> str:
        path = self.resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        if Path(source).resolve() != path:
            shutil.copyfile(source, path)
        return self.url(key)

    def url(self, key: str) -> str:
        return f"{self.public_prefix}/{key}"

    def delete_prefix(self, prefix: str) -> None:
        path = self.resolve(prefix)
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists():
            path.unlink()
