(function () {
  const storageKey = "wardboard-theme";
  const buttons = Array.from(document.querySelectorAll("[data-theme-choice]"));

  function currentTheme() {
    return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
  }

  function applyTheme(theme) {
    const nextTheme = theme === "dark" ? "dark" : "light";
    document.documentElement.dataset.theme = nextTheme;
    localStorage.setItem(storageKey, nextTheme);
    buttons.forEach((button) => {
      const active = button.dataset.themeChoice === nextTheme;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }

  buttons.forEach((button) => {
    button.addEventListener("click", () => applyTheme(button.dataset.themeChoice));
  });

  applyTheme(localStorage.getItem(storageKey) || currentTheme());
})();
