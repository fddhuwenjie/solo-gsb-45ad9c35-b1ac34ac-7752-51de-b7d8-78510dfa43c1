"""无 Flask 环境下的逻辑测试: 用最小桩模块加载 app.py。"""
import json
import os
import sys
import tempfile
import types

# ---- 最小 flask 桩 ----
flask = types.ModuleType("flask")


class G:
    pass


class FakeApp:
    def __init__(self, name):
        self.routes = {}

    def route(self, path, **kw):
        def deco(fn):
            key = (tuple(kw.get("methods") or ("GET",)), path)
            self.routes[key] = fn
            return fn
        return deco

    def get(self, p, **kw):
        return self.route(p, methods=("GET",), **kw)

    def post(self, p, **kw):
        return self.route(p, methods=("POST",), **kw)

    def put(self, p, **kw):
        return self.route(p, methods=("PUT",), **kw)

    def teardown_appcontext(self, fn):
        self._teardown = fn
        return fn


class FakeRequest:
    def __init__(self):
        self._json = None

    def get_json(self, silent=False):
        return self._json


def jsonify(obj):
    return ("JSON", obj)


def render_template(name, **ctx):
    return ("HTML", name, ctx)


flask.Flask = FakeApp
flask.g = G()
flask.jsonify = jsonify
flask.render_template = render_template
flask.request = FakeRequest()
sys.modules["flask"] = flask

sys.path.insert(0, os.path.dirname(__file__))
import app  # noqa: E402

tmpdir = tempfile.mkdtemp()
app.DB_PATH = os.path.join(tmpdir, "test.db")
app.init_db()

passed = []
failed = []


def check(name, cond, detail=""):
    (passed if cond else failed).append(name + ((" — " + detail) if detail and not cond else ""))
    print(("PASS " if cond else "FAIL ") + name + (("  " + detail) if detail and not cond else ""))


def err_ids(errors):
    return {(e["node_id"], e["reason"]) for e in errors}


# ---------- 发布校验: 纯函数 ----------
def node(i, opts=()):
    return {"id": i, "title": "N" + i, "body": "", "options": [
        {"id": "o" + i + str(k), "label": "L", "target_id": t} for k, t in enumerate(opts)
    ]}


# 1. 空草稿
es = app.validate_for_publish({"entry_id": None, "nodes": []})
check("空草稿报错", len(es) == 1 and es[0]["node_id"] is None, str(es))

# 2. 无入口
es = app.validate_for_publish({"entry_id": None, "nodes": [node("a")]})
check("无入口报错", any("入口" in e["reason"] for e in es), str(es))

# 3. 正常链 a -> b -> c(末页)
draft = {"entry_id": "a", "nodes": [node("a", ["b"]), node("b", ["c"]), node("c")]}
check("正常链通过", app.validate_for_publish(draft) == [])

# 4. 分支 + 汇合 a->{b,c}, b->d, c->d, d 末页
draft = {"entry_id": "a", "nodes": [node("a", ["b", "c"]), node("b", ["d"]), node("c", ["d"]), node("d")]}
check("分支汇合无环通过", app.validate_for_publish(draft) == [])

# 5. 不可达节点
draft = {"entry_id": "a", "nodes": [node("a"), node("b")]}
es = app.validate_for_publish(draft)
check("不可达节点报错", any(e["node_id"] == "b" and "不可达" in e["reason"] for e in es), str(es))

# 6. 选项目标不存在
draft = {"entry_id": "a", "nodes": [node("a", ["zzz"])]}
es = app.validate_for_publish(draft)
check("目标不存在报错", any("zzz" in e["reason"] for e in es), str(es))

# 7. 环 a->b->a
draft = {"entry_id": "a", "nodes": [node("a", ["b"]), node("b", ["a"])]}
es = app.validate_for_publish(draft)
check("两节点环报错", all(e["node_id"] in ("a", "b") and "环" in e["reason"] for e in es) and len(es) == 2, str(es))

# 8. 自环
draft = {"entry_id": "a", "nodes": [node("a", ["a"])]}
es = app.validate_for_publish(draft)
check("自环报错", any(e["node_id"] == "a" and "环" in e["reason"] for e in es), str(es))

# 9. 大环 a->b->c->d->b
draft = {"entry_id": "a", "nodes": [node("a", ["b"]), node("b", ["c"]), node("c", ["d"]), node("d", ["b"])]}
es = app.validate_for_publish(draft)
cyc = {e["node_id"] for e in es if "环" in e["reason"]}
check("复杂环定位 b,c,d（a 为环外尾）", cyc == {"b", "c", "d"}, str(cyc))

# 10. 单节点入口无选项（合法末页）
check("单节点末页合法", app.validate_for_publish({"entry_id": "a", "nodes": [node("a")]}) == [])

# 11. 环 + 不可达同时报告
draft = {"entry_id": "a", "nodes": [node("a", ["b"]), node("b", ["a"]), node("x")]}
es = app.validate_for_publish(draft)
check("环与不可达同时报告",
      any(e["node_id"] == "x" and "不可达" in e["reason"] for e in es)
      and any("环" in e["reason"] for e in es), str(es))

print()
print("=" * 60)
print("纯函数通过 %d, 失败 %d" % (len(passed), len(failed)))
sys.exit(1 if failed else 0)
