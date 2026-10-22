"""博客模块验收：发布 -> 列表 -> 详情 -> 删除。"""

from __future__ import annotations

import pytest


def test_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert set(body["modules"]) == {"blog", "files", "chat", "canvas", "tasks", "polls", "search"}


def test_create_list_and_read_post(client):
    created = client.post("/api/posts", json={"title": "第一篇", "content": "正文第一行\n第二行"})
    assert created.status_code == 201
    post = created.json()
    assert post["id"] > 0
    assert post["title"] == "第一篇"

    listing = client.get("/api/posts").json()
    assert any(item["id"] == post["id"] for item in listing)
    # 列表只带摘要，不带全文
    summary = next(item for item in listing if item["id"] == post["id"])
    assert "content" not in summary
    assert summary["excerpt"]

    detail = client.get(f"/api/posts/{post['id']}").json()
    assert detail["content"] == "正文第一行\n第二行"


def test_posts_sorted_by_time_desc(client):
    first = client.post("/api/posts", json={"title": "较早", "content": "a"}).json()
    second = client.post("/api/posts", json={"title": "较晚", "content": "b"}).json()
    ids = [item["id"] for item in client.get("/api/posts").json()]
    assert ids.index(second["id"]) < ids.index(first["id"])


def test_validation_rejects_empty_title(client):
    assert client.post("/api/posts", json={"title": "", "content": "x"}).status_code == 422
    assert client.post("/api/posts", json={"title": "x", "content": ""}).status_code == 422


def test_missing_post_returns_404(client):
    assert client.get("/api/posts/999999").status_code == 404


def test_delete_post(client):
    post = client.post("/api/posts", json={"title": "临时", "content": "待删除"}).json()
    assert client.delete(f"/api/posts/{post['id']}").status_code == 200
    assert client.get(f"/api/posts/{post['id']}").status_code == 404
    assert client.delete(f"/api/posts/{post['id']}").status_code == 404
