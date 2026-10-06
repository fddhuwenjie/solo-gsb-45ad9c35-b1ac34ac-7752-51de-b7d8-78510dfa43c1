/* 访客页: 新建访问 / 凭链接恢复 / 沿固定版本选择选项前进。 */
(function () {
  "use strict";

  const root = document.getElementById("visit-root");
  const token = window.__TOKEN__ || null;

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

  function fmtTime(s) {
    if (!s) return "";
    try { return new Date(s).toLocaleString(); } catch (e) { return s; }
  }

  function showLoading() {
    root.textContent = "";
    root.appendChild(el("p", { class: "muted", text: "加载中…" }));
  }
  function showError(text) {
    root.textContent = "";
    root.appendChild(el("div", { class: "error-box", text: text }));
  }

  /* ---------------- 首页(无 token) ---------------- */
  async function renderHome() {
    root.textContent = "";
    try {
      const res = await fetch("/api/published");
      const info = await res.json();

      const card = el("div", { class: "visit-card", style: "text-align:center;" });
      card.appendChild(el("h1", { text: "展陈分支导览" }));

      if (!info.published) {
        card.appendChild(el("p", {
          class: "muted",
          style: "font-size:16px;padding:20px 0;",
          text: "暂无导览：展览尚未发布任何版本，请联系编辑者在后台编辑并发布。",
        }));
      } else {
        card.appendChild(el("p", {
          style: "font-size:15px;margin-bottom:8px;",
          text: "导览已就绪，全程由您的选择决定参观路线。",
        }));
        card.appendChild(el("p", { class: "muted", text: "当前版本 v" + info.version_id + " · 共 " + info.node_count + " 个讲解节点" }));
        const actions = el("div", { class: "home-actions" });
        const btn = el("button", {
          class: "btn btn-primary",
          text: "开始参观",
          onclick: startVisit,
        });
        actions.appendChild(btn);
        actions.appendChild(el("p", {
          class: "muted",
          text: "开始后请保存浏览器地址栏中的专属链接，凭它可在任意设备找回参观进度。",
        }));
        card.appendChild(actions);
      }
      root.appendChild(card);
    } catch (err) {
      showError("网络错误，请稍后重试。");
    }
  }

  async function startVisit() {
    try {
      const res = await fetch("/api/visits", { method: "POST" });
      if (res.status === 404) {
        showError("暂无导览：展览尚未发布。");
        return;
      }
      const data = await res.json();
      location.href = "/v/" + data.token;
    } catch (err) {
      showError("网络错误，无法开始参观。");
    }
  }

  /* ---------------- 访问页(有 token) ---------------- */
  async function loadVisit() {
    showLoading();
    try {
      const res = await fetch("/api/visits/" + encodeURIComponent(token));
      if (res.status === 404) {
        showError("访问不存在或链接有误。可能链接复制不全，可返回首页重新开始参观。");
        const home = el("p", { style: "text-align:center;" });
        home.appendChild(el("a", { href: "/", text: "← 返回首页" }));
        root.appendChild(home);
        return;
      }
      const data = await res.json();
      renderVisit(data);
    } catch (err) {
      showError("网络错误，请刷新重试。");
    }
  }

  function renderVisit(v) {
    root.textContent = "";
    const node = v.current_node;
    if (!node) {
      showError("当前节点状态异常，请联系管理员。");
      return;
    }

    // 版本信息 + 专属链接
    const shareUrl = location.origin + "/v/" + v.token;
    const linkInput = el("input", { type: "text", readonly: "readonly", value: shareUrl });
    const copyBtn = el("button", {
      class: "btn btn-sm",
      text: "复制",
      onclick: async () => {
        try {
          await navigator.clipboard.writeText(shareUrl);
          copyBtn.textContent = "已复制";
          setTimeout(() => { copyBtn.textContent = "复制"; }, 1500);
        } catch (e) {
          linkInput.select();
        }
      },
    });
    const share = el("div", { class: "share-link" }, [el("span", { text: "我的参观链接（刷新/换设备可继续）：" }), linkInput, copyBtn]);
    const meta = el("div", { class: "visit-meta" }, [
      el("p", { class: "muted", text: "使用版本 v" + v.version_id + "（发布于 " + fmtTime(v.published_at) + "）" }),
      share,
    ]);
    root.appendChild(meta);

    // 已选路径面包屑
    const crumbs = el("div", { class: "breadcrumb" });
    (v.path || []).forEach((p, i) => {
      if (i > 0) crumbs.appendChild(el("span", { class: "crumb-sep", text: "→" }));
      const isLast = i === v.path.length - 1;
      crumbs.appendChild(el("span", {
        text: p.title || p.node_id,
        style: isLast ? "font-weight:600;color:var(--ink);" : null,
      }));
    });
    root.appendChild(crumbs);

    // 当前节点卡片
    const card = el("div", { class: "visit-card" });
    card.appendChild(el("h1", { text: node.title || node.id }));
    if (node.body) card.appendChild(el("div", { class: "body-text", text: node.body }));

    if (v.is_terminal) {
      card.appendChild(el("div", { class: "terminal", text: "— 导览结束，感谢参观 —" }));
      const again = el("p", { style: "text-align:center;margin-top:18px;" });
      again.appendChild(el("a", { class: "btn", href: "/", text: "重新参观（基于当前公开版）" }));
      card.appendChild(again);
    } else {
      const opts = el("div", { class: "options" });
      node.options.forEach((o) => {
        opts.appendChild(el("button", {
          class: "option-btn",
          text: o.label,
          onclick: () => choose(o.id),
        }));
      });
      card.appendChild(opts);
    }
    root.appendChild(card);
  }

  async function choose(optionId) {
    try {
      const res = await fetch("/api/visits/" + encodeURIComponent(token) + "/choose", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ option_id: optionId }),
      });
      const data = await res.json();
      if (!res.ok) {
        showError(data.error || "选择失败，请重试。");
        return;
      }
      renderVisit(data);
      window.scrollTo(0, 0);
    } catch (err) {
      showError("网络错误，请重试。");
    }
  }

  /* ---------------- 启动 ---------------- */
  if (token) {
    loadVisit();
  } else {
    renderHome();
  }
})();
