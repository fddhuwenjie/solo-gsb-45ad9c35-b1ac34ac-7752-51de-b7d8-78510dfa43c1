/* 编辑页: 维护草稿节点 / 入口 / 有序选项, 保存与发布。 */
(function () {
  "use strict";

  const $list = document.getElementById("node-list");
  const $detail = document.getElementById("node-detail");
  const $status = document.getElementById("save-status");
  const $pubResult = document.getElementById("publish-result");
  const $pubInfo = document.getElementById("published-info");

  let state = { entry_id: null, nodes: [] };
  let selectedId = null;
  let publishedVersionId = null;

  function uid() {
    return (crypto.randomUUID ? crypto.randomUUID() : "n-" + Math.random().toString(16).slice(2) + Date.now().toString(16));
  }

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    if (attrs) {
      for (const k in attrs) {
        if (k === "class") node.className = attrs[k];
        else if (k === "text") node.textContent = attrs[k];
        else if (k.startsWith("on")) node.addEventListener(k.slice(2), attrs[k]);
        else if (attrs[k] !== null && attrs[k] !== undefined) node.setAttribute(k, attrs[k]);
      }
    }
    (children || []).forEach((c) => c && node.appendChild(c));
    return node;
  }

  function findNode(id) {
    return state.nodes.find((n) => n.id === id);
  }

  function setStatus(text, kind) {
    $status.textContent = text || "";
    $status.className = "save-status" + (kind ? " " + kind : "");
  }

  function showPub(html, kind) {
    $pubResult.hidden = false;
    $pubResult.className = "publish-result " + kind;
    $pubResult.textContent = "";
    if (typeof html === "string") {
      $pubResult.textContent = html;
    } else {
      $pubResult.appendChild(html);
    }
  }
  function hidePub() {
    $pubResult.hidden = true;
  }

  function renderPubInfo() {
    $pubInfo.textContent = publishedVersionId
      ? "当前公开版本: v" + publishedVersionId + "（进行中的旧访问不受编辑影响）"
      : "尚未发布任何版本，访客页会显示「暂无导览」。";
  }

  /* ---------------- 节点列表 ---------------- */
  function renderList() {
    $list.textContent = "";
    if (state.nodes.length === 0) {
      $list.appendChild(el("p", { class: "muted", text: "还没有节点，点击上方「新建节点」开始。" }));
      return;
    }
    state.nodes.forEach((n) => {
      const isEntry = n.id === state.entry_id;
      const badge = el("span", {
        class: "badge" + (isEntry ? " entry" : ""),
        text: isEntry ? "入口" : "节点",
      });
      const title = el("span", { class: "title", text: n.title || "(未命名节点)" });
      title.dataset.role = "list-title";
      const item = el(
        "div",
        {
          class: "node-item" + (n.id === selectedId ? " active" : ""),
          onclick: () => selectNode(n.id),
        },
        [title, badge]
      );
      item.dataset.nodeId = n.id;
      $list.appendChild(item);
    });
  }

  function syncListTitle(id) {
    const item = $list.querySelector('.node-item[data-node-id="' + CSS.escape(id) + '"] [data-role=list-title]');
    const n = findNode(id);
    if (item && n) item.textContent = n.title || "(未命名节点)";
  }

  /* ---------------- 节点详情 ---------------- */
  function selectNode(id) {
    selectedId = id;
    renderList();
    renderDetail();
  }

  function renderDetail() {
    $detail.textContent = "";
    const n = findNode(selectedId);
    if (!n) {
      $detail.appendChild(el("div", { class: "empty-hint", text: "从左侧选择一个节点进行编辑，或新建节点。" }));
      return;
    }

    // 标题
    const titleInput = el("input", {
      type: "text",
      value: n.title,
      placeholder: "节点标题，如：第一展厅 · 青铜鼎",
      oninput: (e) => {
        n.title = e.target.value;
        syncListTitle(n.id);
      },
    });
    const titleField = el("label", { class: "field" }, [el("span", { text: "讲解节点标题" }), titleInput]);

    // 正文
    const bodyInput = el("textarea", {
      rows: "6",
      placeholder: "讲解词正文……",
      oninput: (e) => { n.body = e.target.value; },
    });
    bodyInput.value = n.body;
    const bodyField = el("label", { class: "field" }, [el("span", { text: "讲解内容" }), bodyInput]);

    // 入口 / 删除
    const entryBtn = el("button", {
      class: "btn btn-sm" + (n.id === state.entry_id ? " btn-primary" : ""),
      text: n.id === state.entry_id ? "✓ 当前入口" : "设为入口",
      onclick: () => {
        state.entry_id = state.entry_id === n.id ? null : n.id;
        renderList();
        renderDetail();
      },
    });
    const delBtn = el("button", {
      class: "btn btn-sm btn-danger",
      text: "删除节点",
      onclick: () => deleteNode(n.id),
    });
    const headActions = el("div", { style: "display:flex;gap:8px;justify-content:flex-end;margin-bottom:12px;" }, [entryBtn, delBtn]);

    $detail.appendChild(titleField);
    $detail.appendChild(bodyField);
    $detail.appendChild(headActions);

    // 选项
    $detail.appendChild(el("h2", { text: "参观选项（按顺序展示，末页请清空选项）" }));
    if (n.options.length === 0) {
      $detail.appendChild(el("p", { class: "muted", text: "此节点没有选项，访客到达后视为末页。", style: "margin-bottom:12px;" }));
    }

    n.options.forEach((o, idx) => {
      const labelInput = el("input", {
        type: "text",
        value: o.label,
        placeholder: "选项文案，如：走进右侧展厅",
        oninput: (e) => { o.label = e.target.value; },
      });
      const targetSelect = el("select", {
        onchange: (e) => { o.target_id = e.target.value; },
      });
      state.nodes.forEach((target) => {
        const opt = el("option", { value: target.id, text: target.title || target.id });
        if (target.id === o.target_id) opt.selected = true;
        targetSelect.appendChild(opt);
      });

      const upBtn = el("button", {
        class: "btn btn-sm", text: "↑", title: "上移",
        disabled: idx === 0 ? "disabled" : null,
        onclick: () => { swapOption(n, idx, idx - 1); },
      });
      const downBtn = el("button", {
        class: "btn btn-sm", text: "↓", title: "下移",
        disabled: idx === n.options.length - 1 ? "disabled" : null,
        onclick: () => { swapOption(n, idx, idx + 1); },
      });
      const rmBtn = el("button", {
        class: "btn btn-sm btn-danger", text: "删",
        onclick: () => {
          n.options.splice(idx, 1);
          renderDetail();
        },
      });
      const row = el("div", { class: "option-row" }, [
        labelInput, targetSelect, upBtn, downBtn, rmBtn,
      ]);
      $detail.appendChild(row);
    });

    const addOptBtn = el("button", {
      class: "btn",
      text: "＋ 添加选项",
      onclick: () => {
        const other = state.nodes.find((x) => x.id !== n.id);
        n.options.push({ id: uid(), label: "", target_id: other ? other.id : n.id });
        renderDetail();
      },
    });
    $detail.appendChild(el("div", { style: "margin-top:6px;" }, [addOptBtn]));
  }

  function swapOption(node, a, b) {
    const arr = node.options;
    if (b < 0 || b >= arr.length) return;
    const t = arr[a]; arr[a] = arr[b]; arr[b] = t;
    renderDetail();
  }

  function deleteNode(id) {
    const node = findNode(id);
    if (!node) return;
    if (!confirm("确定删除节点「" + (node.title || id) + "」？指向它的选项也会一并移除。")) return;
    state.nodes = state.nodes.filter((x) => x.id !== id);
    state.nodes.forEach((x) => {
      x.options = x.options.filter((o) => o.target_id !== id);
    });
    if (state.entry_id === id) state.entry_id = state.nodes.length ? state.nodes[0].id : null;
    if (selectedId === id) selectedId = state.nodes.length ? state.nodes[0].id : null;
    renderList();
    renderDetail();
  }

  /* ---------------- 保存 / 发布 ---------------- */
  async function saveDraft(silent) {
    hidePub();
    setStatus("保存中…");
    try {
      const res = await fetch("/api/draft", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(state),
      });
      const data = await res.json();
      if (!res.ok) {
        setStatus("保存失败：" + (data.errors || []).join("；"), "err");
        return false;
      }
      state = data.draft;
      if (!selectedId || !findNode(selectedId)) selectedId = state.nodes[0] ? state.nodes[0].id : null;
      renderList();
      renderDetail();
      if (!silent) setStatus("草稿已保存于 " + new Date().toLocaleTimeString(), "ok");
      return true;
    } catch (err) {
      setStatus("保存失败：网络错误", "err");
      return false;
    }
  }

  async function publish() {
    hidePub();
    // 发布前先保存草稿, 保证校验的是编辑器最新内容
    const ok = await saveDraft(true);
    if (!ok) {
      showPub("请先修正草稿中的错误再发布。", "err");
      return;
    }
    setStatus("发布校验中…");
    try {
      const res = await fetch("/api/publish", { method: "POST" });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        setStatus("");
        renderPublishErrors(data);
        return;
      }
      publishedVersionId = data.version_id;
      renderPubInfo();
      setStatus("");
      const box = el("div");
      box.appendChild(el("div", {
        text: "发布成功！新版本 v" + data.version_id + " 已公开。",
      }));
      const link = el("a", {
        href: "/", target: "_blank",
        text: "打开访客页体验 →",
        style: "display:inline-block;margin-top:6px;",
      });
      box.appendChild(link);
      box.appendChild(el("div", {
        class: "muted",
        text: "此前已开始的访问仍沿旧版进行，之后新建的访问读取本版本。",
        style: "margin-top:6px;",
      }));
      showPub(box, "ok");
    } catch (err) {
      setStatus("发布失败：网络错误", "err");
    }
  }

  function nodeLabel(nodeId, titles) {
    if (!nodeId) return "（全局）";
    const t = titles && titles[nodeId];
    return "节点「" + (t || nodeId) + "」";
  }

  function renderPublishErrors(data) {
    const titles = data.node_titles || {};
    const box = el("div");
    box.appendChild(el("div", { text: "发布未通过校验，以下问题需修复（草稿与上一公开版本均已保留）：" }));
    const ul = el("ul");
    (data.errors || []).forEach((e) => {
      ul.appendChild(el("li", { text: nodeLabel(e.node_id, titles) + "：" + e.reason }));
    });
    box.appendChild(ul);
    showPub(box, "err");
  }

  /* ---------------- 初始化 ---------------- */
  async function init() {
    document.getElementById("btn-add-node").addEventListener("click", () => {
      const n = { id: uid(), title: "", body: "", options: [] };
      state.nodes.push(n);
      if (!state.entry_id) state.entry_id = n.id;
      selectNode(n.id);
    });
    document.getElementById("btn-save").addEventListener("click", () => saveDraft(false));
    document.getElementById("btn-publish").addEventListener("click", publish);

    try {
      const res = await fetch("/api/draft");
      const data = await res.json();
      state = data.draft;
      publishedVersionId = data.published_version_id;
      selectedId = state.entry_id || (state.nodes[0] && state.nodes[0].id) || null;
      renderPubInfo();
      renderList();
      renderDetail();
    } catch (err) {
      setStatus("草稿加载失败：网络错误", "err");
    }
  }

  init();
})();
