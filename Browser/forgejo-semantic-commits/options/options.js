const api = globalThis.browser ?? globalThis.chrome;
const $ = (id) => document.getElementById(id);

const DEFAULTS = { showScope: true, botUsers: "", timeColorScheme: "heat", extraHosts: "", disabledHosts: "" };
for (const f of RF_FEATURES) DEFAULTS[`feature:${f.id}`] = f.default;

// Extra per-feature sub-options, keyed by feature id.
const SUB_OPTIONS = {
  "semantic-commits": [{ key: "showScope", label: "Show scope inside the pill (e.g. feat · api)" }],
  "time-colors": [
    {
      key: "timeColorScheme",
      type: "select",
      label: "Colour scheme",
      choices: [
        ["heat", "Gradient: green (< 1 hour) fading to orange (6 months), then dimmed"],
        ["freshness", "Freshness: green < 1 day, amber < 1 week, faded after a month"],
      ],
    },
  ],
  "hide-bot-comments": [
    { key: "botUsers", type: "text", label: "Extra bot usernames (comma or space separated)", placeholder: "ci-runner, deploy-user" },
  ],
};

function textField(key, label, placeholder) {
  const row = document.createElement("label");
  row.className = "feature sub text";
  const text = document.createElement("span");
  text.textContent = label;
  const input = document.createElement("input");
  input.type = "text";
  input.dataset.key = key;
  input.placeholder = placeholder || "";
  row.append(text, input);
  return row;
}

function selectField(key, label, choices) {
  const row = document.createElement("label");
  row.className = "feature sub text";
  const text = document.createElement("span");
  text.textContent = label;
  const select = document.createElement("select");
  select.dataset.key = key;
  for (const [value, name] of choices) select.append(new Option(name, value));
  row.append(text, select);
  return row;
}

function checkbox(key, labelHtml, cls) {
  const row = document.createElement("label");
  row.className = cls;
  const input = document.createElement("input");
  input.type = "checkbox";
  input.dataset.key = key;
  row.append(input);
  const text = document.createElement("span");
  text.innerHTML = labelHtml;
  row.append(text);
  return row;
}

const esc = (s) => s.replace(/[&<>"]/g, (c) => `&#${c.charCodeAt(0)};`);

for (const f of RF_FEATURES) {
  $("features").append(
    checkbox(`feature:${f.id}`, `<strong>${esc(f.name)}</strong><small>${esc(f.description)}</small>`, "feature")
  );
  for (const sub of SUB_OPTIONS[f.id] || []) {
    $("features").append(
      sub.type === "text" ? textField(sub.key, sub.label, sub.placeholder)
        : sub.type === "select" ? selectField(sub.key, sub.label, sub.choices)
        : checkbox(sub.key, esc(sub.label), "feature sub")
    );
  }
}

api.storage.sync.get(DEFAULTS).then((s) => {
  for (const input of document.querySelectorAll("[data-key]")) {
    if (input.type === "checkbox") input.checked = !!s[input.dataset.key];
    else input.value = s[input.dataset.key] ?? "";
  }
  $("extraHosts").value = s.extraHosts;
  $("disabledHosts").value = s.disabledHosts;
});

$("save").addEventListener("click", async () => {
  const data = {
    extraHosts: $("extraHosts").value.trim(),
    disabledHosts: $("disabledHosts").value.trim(),
  };
  for (const input of document.querySelectorAll("[data-key]")) {
    data[input.dataset.key] = input.type === "checkbox" ? input.checked : input.value.trim();
  }
  await api.storage.sync.set(data);
  $("status").textContent = "Saved — reload Forgejo tabs to apply.";
});
