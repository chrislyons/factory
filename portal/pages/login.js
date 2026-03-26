const params = new URLSearchParams(window.location.search);
if (params.get("error")) {
  document.getElementById("error-msg").classList.add("is-visible");
}
const redirect = params.get("redirect");
if (redirect && redirect.startsWith("/") && !redirect.startsWith("//")) {
  document.getElementById("redirect").value = redirect;
}
