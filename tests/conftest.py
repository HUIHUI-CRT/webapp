"""pytest 公共装置。

* 把项目根目录加入 sys.path，使 `backend` 可作为包导入；
* 用独立的临时数据目录与上传目录，避免污染真实数据；
* 提供同步的 TestClient（内部基于 httpx）。
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 必须在导入 backend.app.* 之前设置，config 在导入时读取环境变量
_SANDBOX = ROOT / ".tmp" / "pytest-data"
shutil.rmtree(_SANDBOX, ignore_errors=True)
(_SANDBOX / "data").mkdir(parents=True, exist_ok=True)
(_SANDBOX / "uploads").mkdir(parents=True, exist_ok=True)

os.environ["APP_DATA_DIR"] = str(_SANDBOX / "data")
os.environ["APP_UPLOAD_DIR"] = str(_SANDBOX / "uploads")
os.environ["APP_DB_PATH"] = str(_SANDBOX / "data" / "test.db")

from fastapi.testclient import TestClient  # noqa: E402

from backend.app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    """已登记身份的测试客户端。

    本站的身份门禁不校验密码，测试里先以「测试用户」登记一次，
    拿到身份 Cookie 后再跑各个业务用例；需要验证「未登记」行为的用例
    自行清空 cookies。
    """
    with TestClient(app) as c:
        resp = c.post("/api/login", json={"username": "测试用户"})
        assert resp.status_code == 200, resp.text
        yield c


@pytest.fixture(scope="session")
def sandbox() -> Path:
    return _SANDBOX
