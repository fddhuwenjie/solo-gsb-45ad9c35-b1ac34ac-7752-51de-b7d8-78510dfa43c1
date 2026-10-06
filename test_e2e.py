"""端到端测试(无 Flask 环境, 用桩模拟请求上下文)。

覆盖:
- 草稿保存/读取、目标不存在被拒
- 发布失败(422, 草稿与旧版保留) / 发布成功冻结快照
- 访客新建访问、只能选当前节点选项、刷新恢复路径
- 修改草稿/发布新版不影响进行中的旧访问; 新访问读新版
- 未发布时访客页 404
"""
import json
import os
import sys
import tempfile
import types

flask = types.ModuleType("flask")


class G(types.SimpleNamespace):
    def __contains__(self, key):
        return key in self.__dict__

    def pop(self, key, default=None):
        return self.__dict__.pop(key, default)


class FakeApp:
    def __init__(self, name):
        pass

    def route(self, *a, **k):
        return lambda fn: fn

    def get(self, *a, **k):
        return lambda fn: fn

    def post(self, *a, **k):
        return lambda fn: fn

    def put(self, *a, **k):
        return lambda fn: fn

    def teardown_appcontext(self, fn):
        return fn


class FakeRequest:
    def __init__(self):
        self.payload = None

    def get_json(self, silent=False):
        return self.payload


class ResponseError(Exception):
    def __init__(self, code):
        self.code = code


def jsonify(obj):
    return obj


def render_template(name, **ctx):
    return name


flask.Flask = FakeApp
flask.g = G()
flask.jsonify = jsonify
flask.render_template = render_template
flask.request = FakeRequest()
sys.modules["flask"] = flask

sys.path.insert(0, os.path.dirname(__file__))
import app  # noqa: E402

tmpdir = tempfile.mkdtemp()
app.DB_PATH = os.path.join(tmpdir, "e2e.db")
app.init_db()

passed, failed = [], []


def check(name, cond, detail=""):
    (passed if cond else failed).append(name)
    print(("PASS " if cond else "FAIL ") + name + (("  " + str(detail)) if detail and not cond else ""))


def call(fn, *args, **kwargs):
    """模拟 Flask: 每个请求新建 g.db, 结束时 teardown。返回 (status, body)。"""
    # 清掉可能残留的 g.db
    if hasattr(app.g, "db"):
        app.g.pop("db", None)
    try:
        body = fn(*args, **kwargs)
        if isinstance(body, tuple) and len(body) == 2 and isinstance(body[1], int):
            return body[1], body[0]
        return 200, body
    except ResponseError:
        raise
    finally:
        app.close_db(None)


def save_draft(payload):
    flask.request.payload = payload
    return call(app.api_save_draft)


def n(i, opts=(), title=None):
    return {"id": i, "title": title or ("节点" + i), "body": "正文" + i,
            "options": [{"id": "o-%s-%s" % (i, t), "label": "去" + t, "target_id": t} for t in opts]}


# ------------------------------------------------------------------ #
# 1. 未发布状态
status, body = call(app.api_published)
check("未发布时 published=false", status == 200 and body["published"] is False)

status, body = call(app.api_create_visit)
check("未发布时新建访问 404", status == 404 and not body["published"], (status, body))

# 2. 保存指向不存在目标的草稿 -> 400
status, body = save_draft({"entry_id": "a", "nodes": [n("a", ["x"])]})
check("保存时目标不存在被拒", status == 400 and any("x" in e for e in body["errors"]), (status, body))

# 3. 合法草稿保存成功
draft_v1 = {"entry_id": "a", "nodes": [n("a", ["b", "c"]), n("b", ["c"]), n("c")]}
status, body = save_draft(draft_v1)
check("v1 草稿保存成功", status == 200 and body["ok"] is True, (status, body))

# 读回顺序: a 的选项 [b, c] 有序
status, body = call(app.api_get_draft)
a_opts = [o["target_id"] for o in body["draft"]["nodes"][0]["options"]]
check("选项顺序持久化 a->[b,c]", a_opts == ["b", "c"], a_opts)

# 4. 发布一个含环的草稿应失败且不产生版本
bad = {"entry_id": "a", "nodes": [n("a", ["b"]), n("b", ["a"])]}
save_draft(bad)
status, body = call(app.api_publish)
check("环状草稿发布 422", status == 422 and body["ok"] is False, (status, body))
check("发布失败列出节点与原因",
      len(body["errors"]) == 2 and all(e["node_id"] in ("a", "b") for e in body["errors"]),
      body["errors"])

# 恢复合法草稿
save_draft(draft_v1)
status, body = call(app.api_publish)
check("合法草稿发布成功", status == 200 and body["version_id"] == 1, (status, body))

status, body = call(app.api_published)
check("发布后可查到 v1", body["published"] and body["version_id"] == 1 and body["node_count"] == 3, body)

# 5. 访客新建访问 -> 固定在 v1
status, visit = call(app.api_create_visit)
check("新建访问 201 且从入口 a 开始", status == 201 and visit["current_node"]["id"] == "a", status)
check("路径初始含入口", [p["node_id"] for p in visit["path"]] == ["a"], visit["path"])
check("v1 访问版本号=1", visit["version_id"] == 1)
token_v1 = visit["token"]

# 当前节点 a 的选项
check("访客看到当前节点两个选项",
      [o["target_id"] for o in visit["current_node"]["options"]] == ["b", "c"])

# 6. 不能选择别的节点的选项: a 处用 b->c 的 option id (o-b-c)
flask.request.payload = {"option_id": "o-b-c"}
status, body = call(app.api_choose, token_v1)
check("不能选择非当前节点选项 -> 400", status == 400, (status, body))

# 选 a->c(末页): option id o-a-c
flask.request.payload = {"option_id": "o-a-c"}
status, visit = call(app.api_choose, token_v1)
check("选择 a->c 后到达末页 c", status == 200 and visit["current_node"]["id"] == "c" and visit["is_terminal"], (status, visit.get("current_node")))
check("路径记录 [a,c]", [p["node_id"] for p in visit["path"]] == ["a", "c"], visit["path"])

# 末页不能再选
flask.request.payload = {"option_id": "whatever"}
status, body = call(app.api_choose, token_v1)
check("末页无选项可选 -> 400", status == 400)

# 7. 凭链接刷新恢复
status, visit = call(app.api_get_visit, token_v1)
check("刷新后凭 token 恢复到 c 与路径", visit["current_node"]["id"] == "c"
      and [p["node_id"] for p in visit["path"]] == ["a", "c"]
      and visit["version_id"] == 1, visit)

# ------------------------------------------------------------------ #
# 8. 第二个访客: 先走 a->b, 然后编辑者改草稿并发布 v2
status, visit2 = call(app.api_create_visit)
token2 = visit2["token"]
flask.request.payload = {"option_id": "o-a-b"}
status, visit2 = call(app.api_choose, token2)
check("访客2 走到 b(路径 a,b)", [p["node_id"] for p in visit2["path"]] == ["a", "b"], visit2["path"])

# 编辑者把草稿改成全新的两个节点(删光旧节点), 发布 v2
draft_v2 = {"entry_id": "x", "nodes": [
    {"id": "x", "title": "新展厅", "body": "X", "options": [{"id": "o-x-y", "label": "去Y", "target_id": "y"}]},
    {"id": "y", "title": "新末页", "body": "Y", "options": []},
]}
status, body = save_draft(draft_v2)
check("替换为全新结构的草稿成功", status == 200 and body["ok"], (status, body))
status, body = call(app.api_publish)
check("发布 v2 成功", status == 200 and body["version_id"] == 2, (status, body))

# 旧访问1(已在末页)和旧访问2(进行中)仍读 v1 快照
status, v1_reload = call(app.api_get_visit, token_v1)
check("旧访问1 仍固定 v1", v1_reload["version_id"] == 1
      and v1_reload["current_node"]["title"] == "节点c", (v1_reload["version_id"], v1_reload["current_node"]["title"]))

status, v2_old = call(app.api_get_visit, token2)
check("进行中的旧访问2 仍固定 v1, 节点 b 选项仍在",
      v2_old["version_id"] == 1 and v2_old["current_node"]["id"] == "b"
      and [o["target_id"] for o in v2_old["current_node"]["options"]] == ["c"],
      (v2_old["version_id"], v2_old["current_node"]))

# 旧访问2 继续沿 v1 前进到 c(v1 已在快照中, 即使草稿里该节点已删除)
flask.request.payload = {"option_id": "o-b-c"}
status, v2_old = call(app.api_choose, token2)
check("旧访问2 沿 v1 走到 c 结束",
      v2_old["current_node"]["id"] == "c" and v2_old["is_terminal"],
      (status, v2_old["current_node"]))

# 新访问读 v2
status, visit3 = call(app.api_create_visit)
check("新访问读 v2 并从 x 开始", visit3["version_id"] == 2
      and visit3["current_node"]["id"] == "x", (visit3["version_id"], visit3["current_node"]))
check("v2 选项是新结构", [o["target_id"] for o in visit3["current_node"]["options"]] == ["y"])

# 9. 不存在 token
status, body = call(app.api_get_visit, "deadbeef")
check("未知 token 404", status == 404)

# 10. 草稿独立于版本: 再改草稿不影响任何东西
save_draft({"entry_id": "x", "nodes": [
    {"id": "x", "title": "未发布改动", "body": "", "options": []}]})
status, v3_reload = call(app.api_get_visit, visit3["token"])
check("改草稿不影响 v2 进行中的访问",
      v3_reload["current_node"]["title"] == "新展厅", v3_reload["current_node"])

print()
print("=" * 60)
print("端到端通过 %d, 失败 %d" % (len(passed), len(failed)))
if failed:
    print("FAILED:", failed)
sys.exit(1 if failed else 0)
