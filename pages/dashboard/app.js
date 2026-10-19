(() => {
  "use strict";

  const PLUGIN_ID = "astrbot_plugin_qq_aivoice_bridge";

  const state = {
    catalog: [],
    entries: [],
    defaultRole: { role_id: "", name: "" },
    catalog_source: "builtin",
  };

  const el = (id) => document.getElementById(id);

  function createDevFallbackBridge() {
    const apiBase = "/api/plugin/astrbot_plugin_qq_aivoice_bridge/";
    const failure = (response, data) =>
      new Error(data.error || data.message || data.msg || `HTTP ${response.status}`);
    return {
      apiGet: async (endpoint, params = {}) => {
        const url = new URL(`${apiBase}${endpoint}`, window.location.origin);
        Object.entries(params).forEach(([key, value]) => {
          if (value !== undefined && value !== null && value !== "") {
            url.searchParams.set(key, value);
          }
        });
        const response = await fetch(url, { credentials: "same-origin" });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw failure(response, data);
        }
        return data;
      },
      apiPost: async (endpoint, body = {}) => {
        const response = await fetch(`${apiBase}${endpoint}`, {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw failure(response, data);
        }
        return data;
      },
    };
  }

  function waitForPluginBridge(timeoutMs = 8000) {
    if (window.AstrBotPluginPage) {
      return Promise.resolve(window.AstrBotPluginPage);
    }
    return new Promise((resolve, reject) => {
      const started = Date.now();
      const timer = window.setInterval(() => {
        if (window.AstrBotPluginPage) {
          window.clearInterval(timer);
          resolve(window.AstrBotPluginPage);
          return;
        }
        if (Date.now() - started >= timeoutMs) {
          window.clearInterval(timer);
          if (window.parent && window.parent !== window) {
            reject(new Error("插件页面接口没有就绪，请刷新页面重试"));
            return;
          }
          resolve(createDevFallbackBridge());
        }
      }, 50);
    });
  }

  let bridgePromise = null;

  function bridge() {
    if (!bridgePromise) {
      bridgePromise = waitForPluginBridge();
    }
    return bridgePromise;
  }

  function setStatus(text, isError = false) {
    const node = el("status");
    node.textContent = text;
    node.hidden = !text;
    node.classList.toggle("error", Boolean(isError));
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function roleOptions(selectedId, includeMissing) {
    const options = [];
    const known = state.catalog.some((role) => role.role_id === selectedId);
    if (includeMissing && selectedId && !known) {
      options.push(
        `<option value="${escapeHtml(selectedId)}" selected>${escapeHtml(
          selectedId
        )}（不在角色表）</option>`
      );
    }
    state.catalog.forEach((role) => {
      const selected = role.role_id === selectedId ? " selected" : "";
      options.push(
        `<option value="${escapeHtml(role.role_id)}"${selected}>${escapeHtml(
          role.name
        )}</option>`
      );
    });
    if (!options.length) {
      options.push('<option value="">（没有可用角色）</option>');
    }
    return options.join("");
  }

  function conversationCell(entry) {
    const name = entry.group_name || entry.label || entry.conversation;
    const detail =
      entry.kind === "private"
        ? "私聊"
        : entry.group_name
        ? entry.conversation
        : "";
    const detailLine = detail
      ? `<span class="id">${escapeHtml(detail)}</span>`
      : "";
    return `<div class="conversation"><span class="name">${escapeHtml(
      name
    )}</span>${detailLine}</div>`;
  }

  function render() {
    el("loading").hidden = true;

    const chip = el("defaultChip");
    chip.textContent = `全局默认：${state.defaultRole.name || "未设置"}`;

    const note = el("catalogNote");
    if (state.catalog_source === "builtin") {
      note.textContent =
        "当前显示的是插件内置角色表；中转群连上后刷新可拿到 QQ 实时角色列表。";
      note.hidden = false;
    } else {
      note.hidden = true;
    }

    const body = el("roleBody");
    const table = el("roleTable");
    const empty = el("empty");

    if (!state.entries.length) {
      table.hidden = true;
      empty.hidden = false;
      return;
    }

    table.hidden = false;
    empty.hidden = true;
    body.innerHTML = state.entries
      .map((entry, index) => {
        const current = entry.valid
          ? escapeHtml(entry.role_name || entry.role_id)
          : `<span class="tag invalid">已失效</span>`;
        return `<tr>
          <td><span class="platform">${escapeHtml(entry.platform_id)}</span></td>
          <td>${conversationCell(entry)}</td>
          <td>${current}</td>
          <td>
            <select data-index="${index}" class="role-select">
              ${roleOptions(entry.role_id, true)}
            </select>
          </td>
          <td>
            <div class="row-actions">
              <button type="button" data-index="${index}" class="save">保存</button>
              <button type="button" data-index="${index}" class="link-danger delete">删除</button>
            </div>
          </td>
        </tr>`;
      })
      .join("");
  }

  async function load() {
    setStatus("");
    el("loading").hidden = false;
    try {
      const data = await (await bridge()).apiGet("page/roles");
      state.catalog = data.catalog || [];
      state.entries = data.entries || [];
      state.defaultRole = data.default || { role_id: "", name: "" };
      state.catalog_source = data.catalog_source || "builtin";
      render();
    } catch (error) {
      el("loading").hidden = true;
      setStatus(`加载失败：${error.message || error}`, true);
    }
  }

  function setBusy(row, busy) {
    row.querySelectorAll("button").forEach((button) => {
      button.disabled = busy;
    });
  }

  async function saveRole(index, row) {
    const entry = state.entries[index];
    const select = row.querySelector(".role-select");
    const roleId = select ? select.value : "";
    if (!roleId) {
      setStatus("请先选择角色", true);
      return;
    }
    setBusy(row, true);
    try {
      const data = await (await bridge()).apiPost("page/roles/set", {
        platform_id: entry.platform_id,
        conversation: entry.conversation,
        role_id: roleId,
      });
      setStatus(`已把「${entry.label || entry.conversation}」设为 ${data.role_name || roleId}`);
      await load();
    } catch (error) {
      setBusy(row, false);
      setStatus(`保存失败：${error.message || error}`, true);
    }
  }

  async function deleteRole(index, row) {
    const entry = state.entries[index];
    const name = entry.group_name || entry.label || entry.conversation;
    if (!window.confirm(`确定让「${name}」改回跟随全局角色？`)) {
      return;
    }
    setBusy(row, true);
    try {
      await (await bridge()).apiPost("page/roles/delete", {
        platform_id: entry.platform_id,
        conversation: entry.conversation,
      });
      setStatus(`「${name}」已改回跟随全局角色`);
      await load();
    } catch (error) {
      setBusy(row, false);
      setStatus(`删除失败：${error.message || error}`, true);
    }
  }

  el("roleBody").addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button) {
      return;
    }
    const index = Number(button.dataset.index);
    const row = button.closest("tr");
    if (Number.isNaN(index) || !row) {
      return;
    }
    if (button.classList.contains("save")) {
      saveRole(index, row);
    } else if (button.classList.contains("delete")) {
      deleteRole(index, row);
    }
  });

  el("refreshBtn").addEventListener("click", load);

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      load();
    }
  });

  if (window.AstrBotPluginPage) {
    document.documentElement.dataset.pluginId = PLUGIN_ID;
  }

  load();
})();
