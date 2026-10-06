"""本地展陈分支导览 Web 应用。

功能概述:
- 编辑者维护草稿(讲解节点、入口、有序选项), 发布后生成不可变的公开版本快照。
- 发布前校验: 入口可达所有节点、选项目标存在、无环。
- 访客从当前公开版新建访问; 访问一经创建即固定版本, 编辑/重新发布不影响进行中的访问。
- 凭访问 token(链接)可找回版本与已选路径, 刷新后继续。
"""

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone

from flask import Flask, g, jsonify, render_template, request

DB_PATH = os.environ.get("DB_PATH", "/data/guide.db")

app = Flask(__name__)


# --------------------------------------------------------------------------- #
# 数据库
# --------------------------------------------------------------------------- #
SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS draft_meta (
    id        INTEGER PRIMARY KEY CHECK (id = 1),
    entry_id  TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS draft_nodes (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    body       TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS draft_options (
    id         TEXT PRIMARY KEY,
    node_id    TEXT NOT NULL REFERENCES draft_nodes(id) ON DELETE CASCADE,
    label      TEXT NOT NULL,
    target_id  TEXT NOT NULL,
    position   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS versions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at   TEXT NOT NULL,
    entry_id     TEXT NOT NULL,
    snapshot     TEXT NOT NULL  -- {entry_id, nodes:[{id,title,body,options:[...]}]}
);

CREATE TABLE IF NOT EXISTS visits (
    token           TEXT PRIMARY KEY,
    version_id      INTEGER NOT NULL REFERENCES versions(id),
    started_at      TEXT NOT NULL,
    current_node_id TEXT NOT NULL,
    path            TEXT NOT NULL DEFAULT '[]'
    -- path: [{"node_id","title"}, ...] 已访问节点(含当前节点), 来自版本快照
);
"""


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """启动时建库建表并写入草稿默认行。数据持久化在 DB_PATH。"""
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    try:
        db.executescript(SCHEMA)
        exists = db.execute("SELECT id FROM draft_meta WHERE id = 1").fetchone()
        if exists is None:
            db.execute(
                "INSERT INTO draft_meta (id, entry_id, updated_at) VALUES (1, NULL, ?)",
                (now_iso(),),
            )
        db.commit()
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# 草稿读写
# --------------------------------------------------------------------------- #
def get_draft(db):
    meta = db.execute("SELECT entry_id FROM draft_meta WHERE id = 1").fetchone()
    nodes = db.execute("SELECT id, title, body FROM draft_nodes").fetchall()
    options = db.execute(
        "SELECT id, node_id, label, target_id, position "
        "FROM draft_options ORDER BY node_id, position, id"
    ).fetchall()

    opts_by_node = {}
    for o in options:
        opts_by_node.setdefault(o["node_id"], []).append(
            {
                "id": o["id"],
                "label": o["label"],
                "target_id": o["target_id"],
            }
        )
    node_list = [
        {
            "id": n["id"],
            "title": n["title"],
            "body": n["body"],
            "options": opts_by_node.get(n["id"], []),
        }
        for n in nodes
    ]
    return {"entry_id": meta["entry_id"], "nodes": node_list}


def draft_payload(db):
    published = db.execute(
        "SELECT id, created_at FROM versions ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return {
        "draft": get_draft(db),
        "published_version_id": published["id"] if published else None,
        "published_at": published["created_at"] if published else None,
    }


def _validate_draft_payload(data):
    """保存草稿时的结构校验, 返回 (clean_data, errors)。"""
    errors = []
    if not isinstance(data, dict):
        return None, ["请求体必须是 JSON 对象"]

    raw_nodes = data.get("nodes", [])
    if not isinstance(raw_nodes, list):
        return None, ["nodes 必须是数组"]

    nodes = []
    seen_ids = set()
    for i, n in enumerate(raw_nodes):
        if not isinstance(n, dict):
            errors.append(f"第 {i + 1} 个节点格式错误")
            continue
        nid = str(n.get("id") or "").strip()
        title = str(n.get("title") or "").strip()
        body = str(n.get("body") or "")
        if not nid:
            errors.append(f"第 {i + 1} 个节点缺少 id")
            continue
        if nid in seen_ids:
            errors.append(f"节点 {nid} 的 id 重复")
            continue
        seen_ids.add(nid)

        raw_options = n.get("options", [])
        if not isinstance(raw_options, list):
            errors.append(f"节点 {nid} 的选项必须是数组")
            raw_options = []
        options = []
        for pos, o in enumerate(raw_options):
            if not isinstance(o, dict):
                errors.append(f"节点 {nid} 的第 {pos + 1} 个选项格式错误")
                continue
            label = str(o.get("label") or "").strip()
            target_id = str(o.get("target_id") or "").strip()
            if not label:
                errors.append(f"节点 {nid} 的第 {pos + 1} 个选项缺少文案")
            if not target_id:
                errors.append(f"节点 {nid} 的选项「{label or pos + 1}」缺少目标节点")
            options.append(
                {
                    "id": str(o.get("id") or "").strip() or str(uuid.uuid4()),
                    "label": label,
                    "target_id": target_id,
                }
            )
        nodes.append({"id": nid, "title": title or "(未命名节点)", "body": body, "options": options})

    entry_id = data.get("entry_id")
    entry_id = str(entry_id).strip() if entry_id else None
    if entry_id is not None and entry_id not in seen_ids:
        errors.append(f"入口节点 {entry_id} 不存在")

    for n in nodes:
        for o in n["options"]:
            if o["target_id"] and o["target_id"] not in seen_ids:
                errors.append(
                    f"节点 {n['id']} 的选项「{o['label']}」指向不存在的节点 {o['target_id']}"
                )

    return {"entry_id": entry_id, "nodes": nodes}, errors


# --------------------------------------------------------------------------- #
# 发布校验
# --------------------------------------------------------------------------- #
def validate_for_publish(draft):
    """发布校验: 入口存在、所有节点可达、选项目标存在、无环。

    返回错误列表 [{"node_id": str|None, "reason": str}], 空列表表示通过。
    """
    errors = []
    nodes = draft["nodes"]
    node_map = {n["id"]: n for n in nodes}
    entry_id = draft.get("entry_id")

    if not nodes:
        return [{"node_id": None, "reason": "草稿为空，请先添加讲解节点"}]
    if not entry_id:
        return [{"node_id": None, "reason": "尚未设置入口节点"}]
    if entry_id not in node_map:
        return [{"node_id": entry_id, "reason": "入口节点不存在"}]

    # 1) 选项目标存在(保存时也校验, 发布再兜底)
    adjacency = {}
    for n in nodes:
        targets = []
        for o in n["options"]:
            if o["target_id"] not in node_map:
                errors.append(
                    {
                        "node_id": n["id"],
                        "reason": f"选项「{o['label']}」指向不存在的节点 {o['target_id']}",
                    }
                )
            else:
                targets.append(o["target_id"])
        adjacency[n["id"]] = targets

    # 2) 从入口做 BFS, 检查可达性
    reachable = set()
    queue = [entry_id]
    while queue:
        cur = queue.pop(0)
        if cur in reachable:
            continue
        reachable.add(cur)
        queue.extend(adjacency.get(cur, []))

    for n in nodes:
        if n["id"] not in reachable:
            errors.append({"node_id": n["id"], "reason": "从入口不可达"})

    # 3) 有向图环检测(迭代 DFS, 三色标记), 只遍历可达部分
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {nid: WHITE for nid in node_map}
    cycle_nodes = set()
    start = entry_id  # 只在入口可达子图内检测环, 不可达节点已单列错误
    if color.get(start) == WHITE:
        # 栈元素: (节点, 下一邻接下标)
        stack = [(start, 0)]
        color[start] = GRAY
        while stack:
            cur, idx = stack[-1]
            neighbors = adjacency.get(cur, [])
            if idx < len(neighbors):
                nxt = neighbors[idx]
                stack[-1] = (cur, idx + 1)
                if color.get(nxt) == GRAY:
                    # 回边: 仅环上节点(从 nxt 在栈中的位置到栈顶)属于该环
                    pos = next((i for i, (nd, _) in enumerate(stack) if nd == nxt), 0)
                    for node, _ in stack[pos:]:
                        cycle_nodes.add(node)
                elif color.get(nxt) == WHITE:
                    color[nxt] = GRAY
                    stack.append((nxt, 0))
            else:
                color[cur] = BLACK
                stack.pop()

    for nid in sorted(cycle_nodes):
        errors.append({"node_id": nid, "reason": "选项构成了环路，访客无法走到末页"})

    return errors


def build_snapshot(draft):
    return {
        "entry_id": draft["entry_id"],
        "nodes": [
            {
                "id": n["id"],
                "title": n["title"],
                "body": n["body"],
                "options": [
                    {"id": o["id"], "label": o["label"], "target_id": o["target_id"]}
                    for o in n["options"]
                ],
            }
            for n in draft["nodes"]
        ],
    }


# --------------------------------------------------------------------------- #
# 版本与访问
# --------------------------------------------------------------------------- #
def latest_version(db):
    return db.execute(
        "SELECT id, created_at, entry_id, snapshot FROM versions ORDER BY id DESC LIMIT 1"
    ).fetchone()


def load_snapshot(version_row):
    snap = json.loads(version_row["snapshot"])
    snap["version_id"] = version_row["id"]
    snap["published_at"] = version_row["created_at"]
    return snap


def visit_payload(db, visit_row, snapshot=None):
    version_row = db.execute(
        "SELECT id, created_at, snapshot FROM versions WHERE id = ?",
        (visit_row["version_id"],),
    ).fetchone()
    if version_row is None:
        return None
    snap = snapshot if snapshot is not None and snapshot.get("version_id") == version_row["id"] else load_snapshot(version_row)
    node_map = {n["id"]: n for n in snap["nodes"]}
    cur = node_map.get(visit_row["current_node_id"])
    path = json.loads(visit_row["path"])
    return {
        "token": visit_row["token"],
        "version_id": version_row["id"],
        "published_at": version_row["created_at"],
        "started_at": visit_row["started_at"],
        "path": path,
        "current_node": cur,
        "is_terminal": cur is not None and len(cur["options"]) == 0,
    }


# --------------------------------------------------------------------------- #
# 页面路由
# --------------------------------------------------------------------------- #
@app.route("/")
def page_home():
    return render_template("visit.html")


@app.route("/v/<token>")
def page_visit(token):
    return render_template("visit.html", token=token)


@app.route("/editor")
def page_editor():
    return render_template("editor.html")


# --------------------------------------------------------------------------- #
# API: 编辑 / 发布
# --------------------------------------------------------------------------- #
@app.get("/api/draft")
def api_get_draft():
    return jsonify(draft_payload(get_db()))


@app.put("/api/draft")
def api_save_draft():
    """整存整取保存草稿。不影响任何已发布版本与进行中的访问。"""
    clean, errors = _validate_draft_payload(request.get_json(silent=True))
    if errors:
        return jsonify({"ok": False, "errors": errors}), 400

    db = get_db()
    ts = now_iso()
    with db:
        db.execute("DELETE FROM draft_options")
        db.execute("DELETE FROM draft_nodes")
        for n in clean["nodes"]:
            db.execute(
                "INSERT INTO draft_nodes (id, title, body, updated_at) VALUES (?, ?, ?, ?)",
                (n["id"], n["title"], n["body"], ts),
            )
            for pos, o in enumerate(n["options"]):
                db.execute(
                    "INSERT INTO draft_options (id, node_id, label, target_id, position) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (o["id"], n["id"], o["label"], o["target_id"], pos),
                )
        db.execute(
            "UPDATE draft_meta SET entry_id = ?, updated_at = ? WHERE id = 1",
            (clean["entry_id"], ts),
        )
    return jsonify({"ok": True, "draft": draft_payload(db)["draft"]})


@app.post("/api/publish")
def api_publish():
    """校验草稿并冻结为新公开版本。校验失败只返回问题, 草稿与旧版本均保留。"""
    db = get_db()
    draft = get_draft(db)
    errors = validate_for_publish(draft)
    if errors:
        titles = {n["id"]: n["title"] for n in draft["nodes"]}
        return (
            jsonify(
                {
                    "ok": False,
                    "errors": errors,
                    "node_titles": titles,
                    "draft": draft,
                }
            ),
            422,
        )

    snapshot = build_snapshot(draft)
    ts = now_iso()
    with db:
        cur = db.execute(
            "INSERT INTO versions (created_at, entry_id, snapshot) VALUES (?, ?, ?)",
            (ts, draft["entry_id"], json.dumps(snapshot, ensure_ascii=False)),
        )
        version_id = cur.lastrowid
    return jsonify(
        {"ok": True, "version_id": version_id, "published_at": ts, "draft": draft}
    )


# --------------------------------------------------------------------------- #
# API: 公开版与访客
# --------------------------------------------------------------------------- #
@app.get("/api/published")
def api_published():
    row = latest_version(get_db())
    if row is None:
        return jsonify({"published": False})
    return jsonify(
        {
            "published": True,
            "version_id": row["id"],
            "published_at": row["created_at"],
            "entry_id": row["entry_id"],
            "node_count": len(json.loads(row["snapshot"])["nodes"]),
        }
    )


@app.post("/api/visits")
def api_create_visit():
    """基于当前公开版新建一次访问并固定该版本。"""
    db = get_db()
    version = latest_version(db)
    if version is None:
        return jsonify({"published": False, "error": "暂无已发布的导览"}), 404

    token = uuid.uuid4().hex
    snap = load_snapshot(version)
    now = now_iso()
    entry = next((n for n in snap["nodes"] if n["id"] == snap["entry_id"]), None)
    with db:
        db.execute(
            "INSERT INTO visits (token, version_id, started_at, current_node_id, path) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                token,
                version["id"],
                now,
                snap["entry_id"],
                json.dumps([{"node_id": entry["id"], "title": entry["title"]}], ensure_ascii=False),
            ),
        )
    row = db.execute("SELECT * FROM visits WHERE token = ?", (token,)).fetchone()
    return jsonify(visit_payload(db, row, snap)), 201


@app.get("/api/visits/<token>")
def api_get_visit(token):
    db = get_db()
    row = db.execute("SELECT * FROM visits WHERE token = ?", (token,)).fetchone()
    if row is None:
        return jsonify({"error": "访问不存在或链接有误"}), 404
    return jsonify(visit_payload(db, row))


@app.post("/api/visits/<token>/choose")
def api_choose(token):
    """访客只能在当前节点的选项中选择, 沿访问创建时固定的版本前进。"""
    data = request.get_json(silent=True) or {}
    option_id = str(data.get("option_id") or "")

    db = get_db()
    visit = db.execute("SELECT * FROM visits WHERE token = ?", (token,)).fetchone()
    if visit is None:
        return jsonify({"error": "访问不存在或链接有误"}), 404

    version = db.execute(
        "SELECT id, created_at, entry_id, snapshot FROM versions WHERE id = ?",
        (visit["version_id"],),
    ).fetchone()
    snap = load_snapshot(version)
    node_map = {n["id"]: n for n in snap["nodes"]}
    cur = node_map.get(visit["current_node_id"])
    if cur is None:
        return jsonify({"error": "当前节点状态异常"}), 500

    option = next((o for o in cur["options"] if o["id"] == option_id), None)
    if option is None:
        return jsonify({"error": "该选项不属于当前节点，不能选择"}), 400

    target = node_map.get(option["target_id"])
    path = json.loads(visit["path"])
    path.append({"node_id": target["id"], "title": target["title"]})
    with db:
        db.execute(
            "UPDATE visits SET current_node_id = ?, path = ? WHERE token = ?",
            (target["id"], json.dumps(path, ensure_ascii=False), token),
        )
    row = db.execute("SELECT * FROM visits WHERE token = ?", (token,)).fetchone()
    return jsonify(visit_payload(db, row, snap))


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000)
