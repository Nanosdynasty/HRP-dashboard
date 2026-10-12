"use strict";
document.getElementById("logout")?.addEventListener("click", async () => {
  const me = await fetch("/api/auth/me").then(r => r.json());
  const response = await fetch("/auth/logout", {method:"POST", headers:{"X-CSRF-Token":me.csrf || ""}});
  if (response.ok) window.location.assign("/auth/login");
});
