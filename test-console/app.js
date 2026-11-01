/* Swarn Bharat — test harness JS
 * No framework, no build step. Open index.html directly in a browser.
 */
"use strict";

let inMemoryAccessToken = null;
let inMemoryRefreshToken = null;

function baseUrl() {
  return document.getElementById("baseUrl").value.replace(/\/$/, "");
}

function updateTokenUI() {
  const el = document.getElementById("bearerToken");
  el.value = inMemoryAccessToken || "";
}

async function req(method, path, targetId, body, customHeaders = {}) {
  const el = document.getElementById(targetId);
  el.className = "";
  el.textContent = "…";

  const headers = { "Content-Type": "application/json", ...customHeaders };
  if (!headers["Authorization"] && inMemoryAccessToken) {
    headers["Authorization"] = `Bearer ${inMemoryAccessToken}`;
  }

  try {
    const resp = await fetch(baseUrl() + path, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await resp.json();
    el.className = resp.ok ? "ok" : "err";
    el.textContent = `HTTP ${resp.status}\n` + JSON.stringify(data, null, 2);
    return { ok: resp.ok, status: resp.status, data };
  } catch (err) {
    el.className = "err";
    el.textContent = String(err);
    return { ok: false, error: err };
  }
}

async function doRegister() {
  const email = document.getElementById("reg-email").value;
  const password = document.getElementById("reg-password").value;
  const full_name = document.getElementById("reg-fullname").value;
  await req("POST", "/api/v1/auth/register", "auth-resp", { email, password, full_name });
}

async function doLogin() {
  const email = document.getElementById("login-email").value;
  const password = document.getElementById("login-password").value;
  const res = await req("POST", "/api/v1/auth/login", "auth-resp", { email, password });
  if (res.ok && res.data && res.data.data) {
    inMemoryAccessToken = res.data.data.access_token;
    inMemoryRefreshToken = res.data.data.refresh_token;
    updateTokenUI();
  }
}

async function doRefresh() {
  if (!inMemoryRefreshToken) {
    const el = document.getElementById("auth-resp");
    el.className = "err";
    el.textContent = "No refresh token available in memory. Please log in first.";
    return;
  }
  const res = await req("POST", "/api/v1/auth/refresh", "auth-resp", {
    refresh_token: inMemoryRefreshToken,
  });
  if (res.ok && res.data && res.data.data) {
    inMemoryAccessToken = res.data.data.access_token;
    inMemoryRefreshToken = res.data.data.refresh_token;
    updateTokenUI();
  }
}

async function doLogout() {
  if (!inMemoryRefreshToken) {
    const el = document.getElementById("auth-resp");
    el.className = "err";
    el.textContent = "No refresh token available in memory. Please log in first.";
    return;
  }
  await req("POST", "/api/v1/auth/logout", "auth-resp", {
    refresh_token: inMemoryRefreshToken,
  });
  inMemoryAccessToken = null;
  inMemoryRefreshToken = null;
  updateTokenUI();
}

async function doMe() {
  await req("GET", "/api/v1/auth/me", "auth-resp");
}
