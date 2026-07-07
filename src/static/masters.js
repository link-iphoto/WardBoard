function byId(id) {
  return document.getElementById(id);
}

function normalizePatientName(value) {
  return value.replace(/　/g, " ").trim().replace(/\s+/g, " ");
}

function fieldValue(input, normalizers = {}) {
  if (input.type === "checkbox") return input.checked ? "1" : "0";
  const value = input.value.trim();
  const normalizer = normalizers[input.dataset.field];
  return normalizer ? normalizer(value) : value;
}

function updateVisibility(row) {
  const checkbox = row.querySelector('[data-field="is_visible"]');
  const label = checkbox?.closest(".toggle-cell")?.querySelector("span");
  if (!checkbox) return;
  row.classList.toggle("is-hidden", !checkbox.checked);
  if (label) label.textContent = checkbox.checked ? "ON" : "OFF";
}

function showNavigationDialog(label) {
  return new Promise((resolve) => {
    const backdrop = document.createElement("div");
    backdrop.className = "unsaved-dialog-backdrop";
    backdrop.innerHTML = `
      <div class="unsaved-dialog" role="dialog" aria-modal="true" aria-labelledby="unsavedDialogTitle">
        <h2 id="unsavedDialogTitle">変更箇所があります</h2>
        <p>${label}の変更がまだ保存されていません。</p>
        <div class="unsaved-dialog-actions">
          <button class="button success" type="button" data-action="save">保存して移動</button>
          <button class="button ghost" type="button" data-action="discard">保存せず移動</button>
          <button class="button secondary" type="button" data-action="cancel">キャンセル</button>
        </div>
      </div>
    `;
    document.body.appendChild(backdrop);
    backdrop.querySelector("[data-action='save']").focus();
    backdrop.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-action]");
      if (!button) return;
      const action = button.dataset.action;
      backdrop.remove();
      resolve(action);
    });
  });
}

function setupEditableMaster(config) {
  const table = byId(config.tableId);
  if (!table) return;

  const tbody = table.querySelector("tbody");
  const addButton = byId(config.addButtonId);
  const saveButton = byId(config.saveButtonId);
  const saveState = byId(config.saveStateId);
  let nextClientId = 1;
  let isSaving = false;
  let allowLeave = false;

  function rowInputs(row) {
    return Array.from(row.querySelectorAll("[data-field]"));
  }

  function getValue(input) {
    return fieldValue(input, config.normalizers || {});
  }

  function isRowDirty(row) {
    if (row.dataset.new === "1") return true;
    return rowInputs(row).some((input) => getValue(input) !== String(input.dataset.original ?? ""));
  }

  function hasErrors() {
    return Boolean(table.querySelector(".invalid"));
  }

  function validateRow(row) {
    let ok = true;
    rowInputs(row).forEach((input) => input.classList.remove("invalid"));
    row.querySelectorAll(".field-error").forEach((error) => (error.textContent = ""));
    if (config.validateRow) {
      ok = config.validateRow(row, getValue) !== false;
    }
    return ok;
  }

  function refreshDirtyState() {
    let dirtyRows = 0;
    table.querySelectorAll("tbody tr").forEach((row) => {
      rowInputs(row).forEach((input) => {
        input.classList.toggle("cell-dirty", getValue(input) !== String(input.dataset.original ?? ""));
      });
      const dirty = isRowDirty(row);
      row.classList.toggle("row-dirty", dirty);
      if (dirty) dirtyRows += 1;
    });

    if (saveButton) saveButton.disabled = dirtyRows === 0 || hasErrors() || isSaving;
    if (saveState) {
      if (hasErrors()) {
        saveState.textContent = "入力エラーがあります";
        saveState.classList.remove("saved");
      } else if (dirtyRows > 0) {
        saveState.textContent = `${dirtyRows}件の未保存変更があります`;
        saveState.classList.remove("saved");
      } else if (!saveState.classList.contains("saved")) {
        saveState.textContent = "変更はありません";
      }
    }
  }

  function attachRow(row) {
    rowInputs(row).forEach((input) => {
      const eventName = input.tagName === "SELECT" || input.type === "checkbox" ? "change" : "input";
      input.addEventListener(eventName, () => {
        if (input.dataset.field === "is_visible") updateVisibility(row);
        input.classList.remove("invalid");
        const error = input.parentElement.querySelector(".field-error");
        if (error) error.textContent = "";
        refreshDirtyState();
      });
      input.addEventListener("blur", () => {
        if (config.normalizeOnBlur?.includes(input.dataset.field)) {
          input.value = getValue(input);
        }
        validateRow(row);
        refreshDirtyState();
      });
    });
    updateVisibility(row);
  }

  function collectDirtyRows() {
    return Array.from(table.querySelectorAll("tbody tr"))
      .filter(isRowDirty)
      .map((row) => config.collectRow(row, rowInputs(row), getValue));
  }

  function setSavedOriginals(rows, savedItems) {
    rows.forEach((row, index) => {
      const saved = savedItems[index];
      if (!saved) return;
      row.dataset.id = saved.id;
      row.dataset.new = "0";
      delete row.dataset.clientId;
      row.classList.remove("new-row", "row-dirty");
      rowInputs(row).forEach((input) => {
        const field = input.dataset.field;
        const savedValue = field === "is_visible" ? String(saved[field] ? 1 : 0) : String(saved[field] ?? "");
        if (input.type === "checkbox") input.checked = savedValue === "1";
        else input.value = savedValue;
        input.dataset.original = savedValue;
        input.classList.remove("cell-dirty", "invalid");
        const error = input.parentElement.querySelector(".field-error");
        if (error) error.textContent = "";
      });
      updateVisibility(row);
    });
  }

  function focusFirstInvalid() {
    const invalid = table.querySelector(".invalid");
    if (invalid) {
      invalid.focus();
      invalid.scrollIntoView({ block: "center", inline: "nearest" });
    }
  }

  async function saveItems(event) {
    if (typeof event?.preventDefault === "function") event.preventDefault();
    let valid = true;
    table.querySelectorAll("tbody tr").forEach((row) => {
      if (!validateRow(row)) valid = false;
    });
    refreshDirtyState();
    if (!valid || hasErrors()) {
      focusFirstInvalid();
      return false;
    }

    const dirtyRows = Array.from(table.querySelectorAll("tbody tr")).filter(isRowDirty);
    if (dirtyRows.length === 0) return true;
    const payloadItems = collectDirtyRows();

    isSaving = true;
    if (saveButton) saveButton.disabled = true;
    if (saveState) {
      saveState.textContent = "保存中...";
      saveState.classList.remove("saved");
    }
    try {
      const response = await fetch(config.apiPath, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ [config.payloadKey]: payloadItems }),
      });
      const result = await response.json();
      if (!response.ok || !result.ok) {
        throw new Error((result.errors || ["保存できませんでした。"]).join("\n"));
      }
      setSavedOriginals(dirtyRows, result[config.resultKey] || []);
      if (saveState) {
        saveState.textContent = result.message || `${config.label}を保存しました`;
        saveState.classList.add("saved");
      }
      refreshDirtyState();
      return true;
    } catch (error) {
      if (saveState) {
        saveState.textContent = error.message;
        saveState.classList.remove("saved");
      }
      const firstDirty = dirtyRows[0]?.querySelector("[data-field]");
      if (firstDirty) firstDirty.scrollIntoView({ block: "center", inline: "nearest" });
      return false;
    } finally {
      isSaving = false;
      refreshDirtyState();
    }
  }

  table.querySelectorAll("tbody tr").forEach(attachRow);
  refreshDirtyState();

  if (addButton) {
    addButton.addEventListener("click", () => {
      const row = config.newRow(`new-${nextClientId++}`);
      tbody.appendChild(row);
      attachRow(row);
      refreshDirtyState();
      row.querySelector("[data-field]")?.focus();
      row.scrollIntoView({ block: "nearest" });
    });
  }

  if (saveButton) saveButton.addEventListener("click", saveItems);

  window.addEventListener("beforeunload", (event) => {
    if (!allowLeave && !isSaving && Array.from(table.querySelectorAll("tbody tr")).some(isRowDirty)) {
      event.preventDefault();
      event.returnValue = "";
    }
  });

  document.querySelectorAll("a[href]").forEach((link) => {
    link.addEventListener("click", async (event) => {
      if (isSaving || !Array.from(table.querySelectorAll("tbody tr")).some(isRowDirty)) return;
      event.preventDefault();
      const action = await showNavigationDialog(config.label);
      if (action === "cancel") return;
      if (action === "discard") {
        allowLeave = true;
        window.location.href = link.href;
        return;
      }
      const saved = await saveItems();
      if (!saved) return;
      allowLeave = true;
      window.location.href = link.href;
    });
  });
}

function makeRow(html, clientId) {
  const row = document.createElement("tr");
  row.className = "row-dirty new-row";
  row.dataset.new = "1";
  row.dataset.clientId = clientId;
  row.innerHTML = html;
  return row;
}

setupEditableMaster({
  tableId: "patientMasterTable",
  addButtonId: "addPatientRow",
  saveButtonId: "savePatients",
  saveStateId: "patientSaveState",
  apiPath: "/api/patients/bulk",
  payloadKey: "patients",
  resultKey: "patients",
  label: "患者情報",
  normalizers: { name: normalizePatientName },
  normalizeOnBlur: ["name"],
  validateRow(row, getValue) {
    const input = row.querySelector('[data-field="name"]');
    if (!input) return true;
    const value = getValue(input);
    const ok = value.split(" ").filter(Boolean).length >= 2;
    input.value = value;
    input.classList.toggle("invalid", !ok);
    const error = input.parentElement.querySelector(".field-error");
    if (error) error.textContent = ok ? "" : "姓と名の間にスペースを入れてください。例：松本 八重子";
    return ok;
  },
  collectRow(row, inputs, getValue) {
    const values = {};
    inputs.forEach((input) => (values[input.dataset.field] = getValue(input)));
    return {
      client_id: row.dataset.clientId || "",
      id: row.dataset.new === "1" ? "" : row.dataset.id,
      group_name: values.group_name,
      room_number: values.room_number,
      bed_number: values.bed_number,
      name: values.name,
      gender: values.gender,
      memo: values.memo,
      is_visible: values.is_visible,
    };
  },
  newRow(clientId) {
    return makeRow(`
      <td><select data-field="group_name" data-original=""><option value="A" selected>A</option><option value="B">B</option></select></td>
      <td><input data-field="room_number" data-original="" value=""></td>
      <td><input data-field="bed_number" data-original="" value=""></td>
      <td><input data-field="name" data-original="" value=""><small class="field-error"></small></td>
      <td><select data-field="gender" data-original=""><option value="male">男</option><option value="female" selected>女</option></select></td>
      <td><input class="memo-input" data-field="memo" data-original="" value=""></td>
      <td><label class="toggle-cell"><input type="checkbox" data-field="is_visible" data-original="" checked><span>ON</span></label></td>
    `, clientId);
  },
});

setupEditableMaster({
  tableId: "wheelchairMasterTable",
  addButtonId: "addWheelchairRow",
  saveButtonId: "saveWheelchairs",
  saveStateId: "wheelchairSaveState",
  apiPath: "/api/wheelchairs/bulk",
  payloadKey: "wheelchairs",
  resultKey: "wheelchairs",
  label: "車椅子情報",
  collectRow(row, inputs, getValue) {
    const values = {};
    inputs.forEach((input) => (values[input.dataset.field] = getValue(input)));
    return {
      client_id: row.dataset.clientId || "",
      id: row.dataset.new === "1" ? "" : row.dataset.id,
      wheelchair_no: values.wheelchair_no,
      name: values.name,
      kind: values.kind,
      storage_location: values.storage_location,
      memo: values.memo,
      is_visible: values.is_visible,
    };
  },
  validateRow(row, getValue) {
    let ok = true;
    ["wheelchair_no", "name"].forEach((field) => {
      const input = row.querySelector(`[data-field="${field}"]`);
      if (!input) return;
      const valid = getValue(input).length > 0;
      input.classList.toggle("invalid", !valid);
      ok = ok && valid;
    });
    return ok;
  },
  newRow(clientId) {
    return makeRow(`
      <td><input data-field="wheelchair_no" data-original="" value=""></td>
      <td><input data-field="name" data-original="" value=""></td>
      <td><select data-field="kind" data-original=""><option value="shared" selected>共用</option><option value="dedicated">専用</option></select></td>
      <td><input data-field="storage_location" data-original="" value=""></td>
      <td><input class="memo-input" data-field="memo" data-original="" value=""></td>
      <td><label class="toggle-cell"><input type="checkbox" data-field="is_visible" data-original="" checked><span>ON</span></label></td>
    `, clientId);
  },
});
