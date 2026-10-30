/* Swarn Bharat — test harness JS
 * No framework, no build step.  Open index.html directly in a browser.
 */
"use strict";

function baseUrl() {
  return document.getElementById("baseUrl").value.replace(/\/$/, "");
}

function bearerToken() {
  return document.getElementById("bearerToken").value.trim();
}

async function req(method, path, targetId, body) {
  const el = document.getElementById(targetId);
  el.className = "";
  el.textContent = "…";

  const headers = { "Content-Type": "application/json" };
  const tok = bearerToken();
  if (tok) headers["Authorization"] = `Bearer ${tok}`;

  try {
    const resp = await fetch(baseUrl() + path, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await resp.json();
    el.className = resp.ok ? "ok" : "err";
    el.textContent = `HTTP ${resp.status}\n` + JSON.stringify(data, null, 2);
  } catch (err) {
    el.className = "err";
    el.textContent = String(err);
  }
}
