async function postJson(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.detail || JSON.stringify(data));
  }
  return data;
}

function byId(id) {
  return document.getElementById(id);
}

function parseCsv(value) {
  if (!value) return [];
  return value
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

byId("register-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.currentTarget);
  const payload = {
    handle: fd.get("handle"),
    passkey: fd.get("passkey"),
    zip_code: fd.get("zip_code"),
  };
  try {
    const data = await postJson("/api/register", payload);
    byId("register-result").textContent = JSON.stringify(data, null, 2);
  } catch (err) {
    byId("register-result").textContent = `Error: ${err.message}`;
  }
});

byId("budget-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.currentTarget);
  const payload = {
    handle: fd.get("handle"),
    passkey: fd.get("passkey"),
    budget_scope: fd.get("budget_scope"),
    budget_amount: Number(fd.get("budget_amount")),
    period_type: fd.get("period_type"),
    scope_tags: parseCsv(fd.get("scope_tags")),
  };
  try {
    const data = await postJson("/api/budgets", payload);
    byId("budget-result").textContent = JSON.stringify(data, null, 2);
  } catch (err) {
    byId("budget-result").textContent = `Error: ${err.message}`;
  }
});

byId("chat-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.currentTarget);
  const payload = {
    handle: fd.get("handle"),
    passkey: fd.get("passkey"),
    message: fd.get("message"),
    session_id: fd.get("session_id") || null,
  };
  try {
    const data = await postJson("/api/chat", payload);
    byId("chat-result").textContent = JSON.stringify(data, null, 2);
    e.currentTarget.elements.session_id.value = data.session_id;
  } catch (err) {
    byId("chat-result").textContent = `Error: ${err.message}`;
  }
});
