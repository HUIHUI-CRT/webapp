"""协作台验收：任务状态、投票更新、搜索、动态与统计。"""

from __future__ import annotations

from backend.app.services import hub


def test_task_create_update_and_activity(client):
    created = client.post("/api/tasks", json={
        "title": "整理演示稿",
        "description": "补齐最后一页",
        "assignee": "小林",
        "due_date": "2026-11-01",
        "priority": "high",
        "created_by": "阿青",
    })
    assert created.status_code == 201, created.text
    task = created.json()
    assert task["status"] == "todo"
    assert task["priority"] == "high"
    assert task["assignee"] == "小林"

    updated = client.patch(f"/api/tasks/{task['id']}", json={"status": "doing", "actor": "阿青"})
    assert updated.status_code == 200
    assert updated.json()["status"] == "doing"
    assert any(item["detail"] == "整理演示稿" for item in client.get("/api/activity").json())


def test_task_rejects_invalid_date_and_missing_update(client):
    bad = client.post("/api/tasks", json={"title": "日期校验", "due_date": "下周"})
    assert bad.status_code == 422
    assert client.patch("/api/tasks/999999", json={"status": "done"}).status_code == 404


def test_poll_vote_can_be_changed_and_results_are_counted(client):
    created = client.post("/api/polls", json={
        "title": "答辩演示主题",
        "options": ["产品介绍", "技术实现", "小组总结"],
        "created_by": "阿青",
    })
    assert created.status_code == 201, created.text
    poll = created.json()
    first = poll["options"][0]["id"]
    second = poll["options"][1]["id"]

    vote = client.post(f"/api/polls/{poll['id']}/vote", json={"option_id": first, "voter": "小林"})
    assert vote.status_code == 200
    assert vote.json()["total_votes"] == 1
    assert vote.json()["my_option_id"] == first

    changed = client.post(f"/api/polls/{poll['id']}/vote", json={"option_id": second, "voter": "小林"})
    assert changed.json()["total_votes"] == 1
    assert changed.json()["my_option_id"] == second

    listed = client.get("/api/polls", params={"voter": "小林"}).json()
    result = next(item for item in listed if item["id"] == poll["id"])
    assert result["my_option_id"] == second
    assert sum(option["votes"] for option in result["options"]) == 1


def test_poll_rejects_foreign_option(client):
    poll = client.post("/api/polls", json={"title": "范围检查", "options": ["A", "B"]}).json()
    other = client.post("/api/polls", json={"title": "另一个", "options": ["C", "D"]}).json()
    option_id = other["options"][0]["id"]
    res = client.post(f"/api/polls/{poll['id']}/vote", json={"option_id": option_id, "voter": "成员"})
    assert res.status_code == 422


def test_search_stats_and_chat_memory(client):
    post = client.post("/api/posts", json={"title": "搜索样例", "content": "包含独特关键词 nebula-2026 的正文"})
    assert post.status_code == 201
    task = client.post("/api/tasks", json={"title": "nebula-2026 整理", "description": "测试跨模块搜索"})
    assert task.status_code == 201
    hub.add_chat("workspace-test", {
        "type": "chat", "user": "成员", "text": "nebula-2026 会议记录",
        "room": "workspace-test", "ts": 1_800_000_000,
    })

    found = client.get("/api/search", params={"q": "nebula-2026"}).json()["results"]
    assert {item["type"] for item in found} >= {"post", "task", "chat"}
    assert any(item["url"].endswith(f"post={post.json()['id']}") for item in found if item["type"] == "post")

    stats = client.get("/api/stats").json()
    assert stats["posts"] >= 1
    assert stats["tasks"].get("todo", 0) >= 1
    assert stats["activity"] >= 1
    assert client.get("/api/activity", params={"limit": 5}).status_code == 200
