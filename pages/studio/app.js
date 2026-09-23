const bridge = window.AstrBotPluginPage;
const state = { platforms: [] };

function render() {
  const root = document.getElementById("platforms");
  if (!state.platforms.length) {
    root.innerHTML = "<option disabled>没有检测到平台实例</option>";
    return;
  }
  root.innerHTML = state.platforms.map((item) => `
    <option value="${escapeHtml(item.id)}" ${item.selected ? "selected" : ""}>
      ${escapeHtml(item.name || item.id)} | ${escapeHtml(item.id)} | ${escapeHtml(item.type)}
    </option>
  `).join("");
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
}

async function load() {
  const data = await bridge.apiGet("platforms");
  state.platforms = data.platforms || [];
  render();
}

async function main() {
  await bridge.ready();
  document.getElementById("save").addEventListener("click", async () => {
    const button = document.getElementById("save");
    const status = document.getElementById("status");
    const selected = [...document.getElementById("platforms").selectedOptions]
      .map((item) => item.value);
    button.disabled = true;
    status.textContent = "保存中…";
    try {
      await bridge.apiPost("config/platforms", { qq_platforms: selected });
      status.textContent = "已保存";
      await load();
    } catch (error) {
      status.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  });
  await load();
}

main().catch((error) => {
  document.getElementById("platforms").outerHTML = `<p class="hint">${escapeHtml(error.message)}</p>`;
});
