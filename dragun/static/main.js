const state = {
  user: null,
};

const messages = document.querySelector("#messages");
const singulars = {
  shirts: "shirt",
  dresses: "dress",
  pants: "pant",
  shoes: "shoes",
};

function addMessage(role, text) {
  const node = document.createElement("div");
  node.className = `message ${role}`;
  node.textContent = text;
  messages.appendChild(node);
  messages.scrollTop = messages.scrollHeight;
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { "content-type": "application/json" },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || "Dragun coughed smoke.");
  }
  return payload;
}

document.querySelector("#register-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const handle = form.get("handle");
  try {
    state.user = await request("/api/register", {
      method: "POST",
      body: JSON.stringify({
        handle,
        passkey: form.get("passkey"),
        zip_code: form.get("zip_code"),
      }),
    });
    addMessage("dragon", `Hoard opened for ${state.user.handle}.`);
  } catch (error) {
    try {
      state.user = await request(`/api/users/${encodeURIComponent(handle)}`, {
        headers: {},
      });
      addMessage("dragon", `Found ${state.user.handle}'s hoard.`);
    } catch {
      addMessage("dragon", error.message);
    }
  }
});

document.querySelector("#budget-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.user) {
    addMessage("dragon", "Register first. I need a hoard to guard.");
    return;
  }
  const form = new FormData(event.currentTarget);
  const scope = String(form.get("scope") || "all").toLowerCase();
  const payload = await request(`/api/users/${state.user.user_id}/budgets`, {
    method: "POST",
    body: JSON.stringify({
      budget_scope: scope,
      scope_tags: scope === "all" ? [] : [scope],
      budget_amount: Number(form.get("amount")),
      period_type: form.get("period_type"),
    }),
  });
  addMessage("dragon", `${scope} budget marked. $${payload.status.amount_remaining.toFixed(2)} remains.`);
});

document.querySelector("#constraint-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.user) {
    addMessage("dragon", "Register first. I need a hoard to guard.");
    return;
  }
  const form = new FormData(event.currentTarget);
  const rawItem = String(form.get("scope") || "items").toLowerCase();
  const item = singulars[rawItem] || rawItem.replace(/s$/, "");
  await request(`/api/users/${state.user.user_id}/constraints`, {
    method: "POST",
    body: JSON.stringify({
      constraint_type: "inventory_cap",
      item_normalized: item,
      operator: "count_exceeds",
      threshold_value: Number(form.get("threshold")),
    }),
  });
  addMessage("dragon", `Cap set. I will flag ${item} over ${form.get("threshold")}.`);
});

document.querySelector("#chat-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.user) {
    addMessage("dragon", "Register first. I need a hoard to guard.");
    return;
  }
  const form = new FormData(event.currentTarget);
  const message = String(form.get("message") || "");
  addMessage("user", message);
  event.currentTarget.reset();
  try {
    const payload = await request("/api/chat", {
      method: "POST",
      body: JSON.stringify({ user_id: state.user.user_id, message }),
    });
    addMessage("dragon", payload.reply);
  } catch (error) {
    addMessage("dragon", error.message);
  }
});
