import pytest

from app.config import Settings
from tests.fakes import FakeContainer


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    """测试不受本机 .env 的影响。

    pymilvus 在导入时会把项目根目录的 .env 读进进程环境变量，这里逐项清掉，
    保证每个测试拿到的都是代码里的默认配置。
    """
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)


@pytest.fixture
def container(tmp_path):
    return FakeContainer(tmp_path)
