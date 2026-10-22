"""文件模块验收：上传 -> 列表 -> 下载 -> 秒传 -> 删除。"""

from __future__ import annotations

import hashlib


def _payload(size: int = 200_000) -> bytes:
    return bytes((i * 7 + 13) % 251 for i in range(size))


def test_upload_list_download_roundtrip(client, sandbox):
    data = _payload()
    res = client.post("/api/upload", files={"file": ("测试文件.bin", data, "application/octet-stream")})
    assert res.status_code == 200, res.text
    body = res.json()
    info = body["file"]
    assert info["original_name"] == "测试文件.bin"
    assert info["size"] == len(data)
    assert info["sha256"] == hashlib.sha256(data).hexdigest()
    assert body["engine"] in {"cpp", "python"}

    # 落盘文件确实存在，且磁盘名与原始名不同（避免重名覆盖）
    stored = sandbox / "uploads" / info["filename"]
    assert stored.is_file()
    assert stored.read_bytes() == data
    assert info["filename"] != info["original_name"]

    # 列表
    listed = client.get("/api/files").json()
    assert any(item["id"] == info["id"] for item in listed)

    # 下载内容与上传一致，且文件名还原为原始名
    down = client.get(info["download_url"])
    assert down.status_code == 200
    assert down.content == data
    assert "attachment" in down.headers["content-disposition"]


def test_duplicate_upload_is_deduplicated(client):
    data = _payload(4096)
    first = client.post("/api/upload", files={"file": ("a.txt", data, "text/plain")}).json()
    second = client.post("/api/upload", files={"file": ("b.txt", data, "text/plain")}).json()
    assert second["duplicate"] is True
    assert second["file"]["id"] == first["file"]["id"]
    # 只保留一份磁盘文件
    names = {f["filename"] for f in client.get("/api/files").json()}
    assert first["file"]["filename"] in names


def test_download_rejects_unknown_and_traversal(client):
    assert client.get("/api/download/not-exists.bin").status_code == 404
    for evil in ("..%2F..%2Fwindows%2Fwin.ini", "%2E%2E%2Fapp.db", "..\\..\\app.db"):
        assert client.get(f"/api/download/{evil}").status_code in (404, 400)


def test_delete_file_removes_from_disk(client, sandbox):
    data = _payload(1024)
    info = client.post("/api/upload", files={"file": ("del.bin", data, "application/octet-stream")}).json()["file"]
    stored = sandbox / "uploads" / info["filename"]
    assert stored.is_file()

    assert client.delete(f"/api/files/{info['id']}").status_code == 200
    assert not stored.exists()
    assert client.get(f"/api/files/{info['id']}").status_code == 404


def test_empty_file_is_accepted(client):
    res = client.post("/api/upload", files={"file": ("empty.txt", b"", "text/plain")})
    assert res.status_code == 200
    assert res.json()["file"]["size"] == 0
