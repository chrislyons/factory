(function () {
  var params = new URLSearchParams(window.location.search);
  if (params.get("error")) {
    document.getElementById("error-msg").classList.add("is-visible");
  }
  var redirect = params.get("redirect");
  if (redirect && redirect.startsWith("/") && !redirect.startsWith("//")) {
    document.getElementById("redirect").value = redirect;
  }

  document.querySelector("form.login-card").addEventListener("submit", function (e) {
    e.preventDefault();
    var btn = document.querySelector(".login-btn");
    var errorEl = document.getElementById("error-msg");
    errorEl.classList.remove("is-visible");
    btn.disabled = true;
    btn.textContent = "Signing in\u2026";

    fetch("/auth/login", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: document.getElementById("username").value,
        password: document.getElementById("password").value,
        redirect: document.getElementById("redirect").value || "/"
      })
    })
      .then(function (res) {
        if (res.ok) {
          return res.json().then(function (d) {
            window.location.assign(d.redirect || "/");
          });
        }
        btn.disabled = false;
        btn.textContent = "Sign in";
        errorEl.classList.add("is-visible");
      })
      .catch(function () {
        btn.disabled = false;
        btn.textContent = "Sign in";
        errorEl.classList.add("is-visible");
      });
  });
})();
