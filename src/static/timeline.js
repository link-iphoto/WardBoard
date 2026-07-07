const SLOT_COUNT = 28;
const SLOT_MINUTES = 30;
const START_HOUR = 6;

const state = {
  day: document.querySelector(".day-tabs")?.dataset.currentDay || "monday",
  patients: [],
  wheelchairs: [],
  assignments: [],
  savedSnapshot: "[]",
  dragPatientId: null,
  action: null,
  viewRange: "daytime",
};

const board = document.getElementById("timeBoard");
const patientList = document.getElementById("patientList");
const saveState = document.getElementById("saveState");
const deleteDropZone = document.getElementById("deleteDropZone");
const timelineScroll = document.getElementById("timelineScroll");

function slotLabel(slot) {
  const minutes = START_HOUR * 60 + slot * SLOT_MINUTES;
  return `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")}`;
}

function patientById(id) {
  return state.patients.find((p) => Number(p.id) === Number(id));
}

function wheelchairById(id) {
  return state.wheelchairs.find((w) => Number(w.id) === Number(id));
}

function nameParts(name) {
  const parts = String(name || "").trim().split(/\s+/);
  return {
    last: parts[0] || "",
    first: parts.slice(1).join("") || "",
    compact: parts.join(""),
    spaced: parts.join(" "),
  };
}

function serializeAssignments() {
  return JSON.stringify(state.assignments.map((a) => ({
    patient_id: Number(a.patient_id),
    wheelchair_id: Number(a.wheelchair_id),
    start_slot: Number(a.start_slot),
    end_slot: Number(a.end_slot),
    note: a.note || "",
  })).sort((a, b) => a.wheelchair_id - b.wheelchair_id || a.start_slot - b.start_slot || a.patient_id - b.patient_id));
}

function markDirty() {
  saveState.textContent = serializeAssignments() === state.savedSnapshot ? "保存済み" : "未保存";
}

async function load() {
  const boot = await fetch("/api/bootstrap").then((r) => r.json());
  state.patients = boot.patients;
  state.wheelchairs = boot.wheelchairs;
  const dayData = await fetch(`/api/assignments/${state.day}`).then((r) => r.json());
  state.assignments = dayData.assignments;
  state.savedSnapshot = serializeAssignments();
  renderPatients();
  renderBoard();
  markDirty();
}

function renderPatients() {
  const query = document.getElementById("patientSearch").value.trim().toLowerCase();
  patientList.innerHTML = "";
  state.patients
    .filter((p) => !query || `${p.bed_label} ${p.name} ${p.memo}`.toLowerCase().includes(query))
    .forEach((patient) => {
      const card = document.createElement("div");
      card.className = `patient-card ${patient.gender}`;
      card.draggable = true;
      card.dataset.patientId = patient.id;
      const parts = nameParts(patient.name);
      card.innerHTML = `<span>${patient.bed_label}</span><strong>${parts.spaced}</strong>`;
      card.addEventListener("dragstart", (event) => {
        state.dragPatientId = Number(patient.id);
        event.dataTransfer.setData("text/plain", String(patient.id));
      });
      patientList.appendChild(card);
    });
}

function renderBoard() {
  board.innerHTML = "";
  const header = document.createElement("div");
  header.className = "time-header";
  header.innerHTML = `<div class="corner">車椅子一覧</div><div class="time-axis">${Array.from({ length: SLOT_COUNT }, (_, i) => `<div class="time-cell ${i % 2 === 0 ? "hour" : ""}">${i % 2 === 0 ? slotLabel(i) : "30"}</div>`).join("")}</div>`;
  board.appendChild(header);

  state.wheelchairs.forEach((wheelchair) => {
    const row = document.createElement("div");
    row.className = "wheel-row";
    row.innerHTML = `
      <div class="wheel-label">
        <span>${wheelchair.wheelchair_no}　${wheelchair.name}</span>
        <small>${wheelchair.storage_location || ""}</small>
        <b class="kind-tag ${wheelchair.kind}">${wheelchair.kind === "dedicated" ? "専用" : "共用"}</b>
      </div>
      <div class="row-grid" data-wheelchair-id="${wheelchair.id}"></div>
    `;
    board.appendChild(row);
    const grid = row.querySelector(".row-grid");
    grid.addEventListener("dragover", (event) => {
      event.preventDefault();
      grid.classList.add("drag-over");
    });
    grid.addEventListener("dragleave", () => grid.classList.remove("drag-over"));
    grid.addEventListener("drop", (event) => {
      event.preventDefault();
      grid.classList.remove("drag-over");
      const patientId = Number(event.dataTransfer.getData("text/plain") || state.dragPatientId);
      if (!patientId) return;
      const start = wheelchair.kind === "dedicated" ? 0 : Math.min(SLOT_COUNT - 2, slotFromEvent(event, grid));
      const end = wheelchair.kind === "dedicated" ? SLOT_COUNT : start + 2;
      const candidate = {
        temp_id: crypto.randomUUID(),
        patient_id: patientId,
        wheelchair_id: Number(wheelchair.id),
        start_slot: start,
        end_slot: end,
        note: "",
      };
      if (!canPlace(candidate, start, end)) {
        alert(wheelchair.kind === "dedicated" ? "この専用車椅子にはすでに患者が配置されています。" : "その時間帯には配置できません。");
        return;
      }
      state.assignments.push(candidate);
      renderBoard();
      markDirty();
    });
    state.assignments
      .filter((a) => Number(a.wheelchair_id) === Number(wheelchair.id))
      .forEach((assignment) => renderAssignment(grid, assignment));
  });
  highlightConflicts();
  applyViewRange(false);
}

function assignmentKey(assignment) {
  return assignment.id ? `db-${assignment.id}` : assignment.temp_id;
}

function renderAssignment(grid, assignment) {
  const patient = patientById(assignment.patient_id);
  const wheelchair = wheelchairById(assignment.wheelchair_id);
  if (!wheelchair) return;
  const patientName = patient?.name || assignment.patient_name || "未表示の患者";
  const displayName = nameParts(patientName);
  const bedLabel = patient?.bed_label || assignment.bed_label || "";
  const isDedicated = wheelchair.kind === "dedicated";
  const needsWarning = !patient || Number(assignment.patient_is_visible) === 0 || !["admitted", undefined].includes(assignment.patient_status);
  const isNarrow = Number(assignment.end_slot) - Number(assignment.start_slot) <= 2;
  const item = document.createElement("div");
  item.className = `assignment ${wheelchair.kind} ${assignment.id ? "saved" : ""} ${needsWarning ? "warning" : ""}`;
  item.dataset.key = assignmentKey(assignment);
  item.style.left = `${(assignment.start_slot / SLOT_COUNT) * 100}%`;
  item.style.width = `${((assignment.end_slot - assignment.start_slot) / SLOT_COUNT) * 100}%`;
  updateAssignmentLabelPosition(item, Number(assignment.start_slot), Number(assignment.end_slot));
  item.innerHTML = `
    ${isDedicated ? "" : '<span class="handle left"></span>'}
    <span class="label ${isNarrow ? "stacked" : ""}">${isNarrow && displayName.first ? `${displayName.last}<br>${displayName.first}` : displayName.compact}${isDedicated ? "　専用" : ""}${needsWarning ? "　要確認" : ""}</span>
    ${isDedicated ? "" : '<span class="handle right"></span>'}
  `;
  if (isDedicated) {
    item.addEventListener("pointerdown", (event) => beginPointer(event, assignment, grid, "delete-only"));
  } else {
    item.addEventListener("pointerdown", (event) => {
      const rect = item.getBoundingClientRect();
      if (event.clientX - rect.left <= 10) {
        beginPointer(event, assignment, grid, "resize-left");
      } else if (rect.right - event.clientX <= 10) {
        beginPointer(event, assignment, grid, "resize-right");
      } else {
        beginPointer(event, assignment, grid, "move");
      }
    });
    item.querySelector(".handle.left").addEventListener("pointerdown", (event) => beginPointer(event, assignment, grid, "resize-left"));
    item.querySelector(".handle.right").addEventListener("pointerdown", (event) => beginPointer(event, assignment, grid, "resize-right"));
  }
  grid.appendChild(item);
}

function beginPointer(event, assignment, grid, mode) {
  if (event.target.classList.contains("delete")) return;
  event.preventDefault();
  event.stopPropagation();
  const element = event.target.closest(".assignment");
  const gridRect = grid.getBoundingClientRect();
  const elementRect = element.getBoundingClientRect();
  state.action = {
    key: assignmentKey(assignment),
    mode,
    grid,
    element,
    row: grid.closest(".wheel-row"),
    startX: event.clientX,
    startY: event.clientY,
    elementLeft: elementRect.left,
    elementTop: elementRect.top,
    elementWidth: elementRect.width,
    elementHeight: elementRect.height,
    startSlot: Number(assignment.start_slot),
    endSlot: Number(assignment.end_slot),
    slotWidth: gridRect.width / SLOT_COUNT,
    wheelchairId: Number(grid.dataset.wheelchairId),
    draftStart: Number(assignment.start_slot),
    draftEnd: Number(assignment.end_slot),
    overDelete: false,
    lastDeleted: null,
  };
  element.classList.add("drag-active");
  grid.classList.add("dragging-row");
  state.action.row?.classList.add("dragging-row");
  document.body.classList.add("bar-dragging");
  if (deleteDropZone) deleteDropZone.textContent = "ここにドロップして削除";
  window.addEventListener("pointermove", movePointer);
  window.addEventListener("pointerup", endPointer, { once: true });
}

function movePointer(event) {
  if (!state.action) return;
  const action = state.action;
  const delta = Math.round((event.clientX - action.startX) / action.slotWidth);
  const item = state.assignments.find((a) => assignmentKey(a) === action.key);
  if (!item || !action.element) return;
  action.overDelete = isOverDeleteZone(event);
  updateDeleteZone(action.overDelete);
  if (action.mode === "delete-only") {
    updateDragPreview(action, event);
    return;
  }
  let nextStart = action.draftStart;
  let nextEnd = action.draftEnd;
  if (action.mode === "move") {
    const length = action.endSlot - action.startSlot;
    const desiredStart = clamp(action.startSlot + delta, 0, SLOT_COUNT - length);
    [nextStart, nextEnd] = boundedMove(item, action.startSlot, action.endSlot, desiredStart, action.key);
  } else if (action.mode === "resize-left") {
    const desiredStart = clamp(action.startSlot + delta, 0, action.endSlot - 1);
    nextStart = boundedResizeStart(item, action.startSlot, desiredStart, action.endSlot, action.key);
    nextEnd = action.endSlot;
  } else {
    const desiredEnd = clamp(action.endSlot + delta, action.startSlot + 1, SLOT_COUNT);
    nextStart = action.startSlot;
    nextEnd = boundedResizeEnd(item, action.startSlot, action.endSlot, desiredEnd, action.key);
  }
  action.draftStart = nextStart;
  action.draftEnd = nextEnd;
  updateAssignmentElement(action.element, nextStart, nextEnd);
  updateDragPreview(action, event);
}

function updateAssignmentElement(element, startSlot, endSlot) {
  element.style.left = `${(startSlot / SLOT_COUNT) * 100}%`;
  element.style.width = `${((endSlot - startSlot) / SLOT_COUNT) * 100}%`;
  updateAssignmentLabelPosition(element, startSlot, endSlot);
}

function visibleSlotRange() {
  return state.viewRange === "daytime" ? [6, 22] : [0, SLOT_COUNT];
}

function updateAssignmentLabelPosition(element, startSlot, endSlot) {
  const length = Math.max(1, endSlot - startSlot);
  const [viewStart, viewEnd] = visibleSlotRange();
  const visibleStart = clamp(Math.max(startSlot, viewStart), startSlot, endSlot);
  const visibleEnd = clamp(Math.min(endSlot, viewEnd), startSlot, endSlot);
  const centerSlot = visibleEnd > visibleStart ? (visibleStart + visibleEnd) / 2 : (startSlot + endSlot) / 2;
  const labelLeft = clamp(((centerSlot - startSlot) / length) * 100, 0, 100);
  element.style.setProperty("--label-left", `${labelLeft}%`);
}

function updateDragPreview(action, event) {
  if (!action.element) return;
  const deltaX = event.clientX - action.startX;
  const deltaY = event.clientY - (action.startY || event.clientY);
  const shouldFloat = Math.abs(deltaY) > 4 && ["move", "delete-only"].includes(action.mode);
  action.element.classList.toggle("drag-preview", shouldFloat);
  action.element.classList.toggle("floating-preview", shouldFloat);
  if (shouldFloat) {
    action.element.style.position = "fixed";
    action.element.style.left = `${action.elementLeft + deltaX}px`;
    action.element.style.top = `${action.elementTop + deltaY}px`;
    action.element.style.width = `${action.elementWidth}px`;
    action.element.style.height = `${action.elementHeight}px`;
    action.element.style.transform = "";
  } else {
    action.element.style.position = "";
    action.element.style.top = "";
    action.element.style.height = "";
    action.element.style.transform = "";
  }
}

function endPointer() {
  const action = state.action;
  if (!action) return;
  const item = state.assignments.find((a) => assignmentKey(a) === action.key);
  if (item && action.overDelete) {
    state.assignments = state.assignments.filter((a) => assignmentKey(a) !== action.key);
    showUndo(item);
  } else if (item) {
    item.start_slot = action.draftStart;
    item.end_slot = action.draftEnd;
  }
  if (action.element) {
    action.element.style.transform = "";
    action.element.style.position = "";
    action.element.style.top = "";
    action.element.style.height = "";
    action.element.classList.remove("drag-active", "drag-preview", "floating-preview");
  }
  action.grid?.classList.remove("dragging-row");
  action.row?.classList.remove("dragging-row");
  state.action = null;
  document.body.classList.remove("bar-dragging");
  updateDeleteZone(false);
  window.removeEventListener("pointermove", movePointer);
  renderBoard();
  markDirty();
}

function isOverDeleteZone(event) {
  if (!deleteDropZone) return false;
  const rect = deleteDropZone.getBoundingClientRect();
  return event.clientX >= rect.left && event.clientX <= rect.right && event.clientY >= rect.top && event.clientY <= rect.bottom;
}

function updateDeleteZone(isOver) {
  if (!deleteDropZone) return;
  deleteDropZone.classList.toggle("active", document.body.classList.contains("bar-dragging"));
  deleteDropZone.classList.toggle("over", isOver);
  deleteDropZone.textContent = isOver ? "離すと削除されます" : document.body.classList.contains("bar-dragging") ? "ここにドロップして削除" : "削除はこちらへドロップ";
}

function showUndo(deleted) {
  const patient = patientById(deleted.patient_id);
  const parts = nameParts(patient?.name || deleted.patient_name || "予定");
  const toast = document.createElement("div");
  toast.className = "undo-toast";
  toast.innerHTML = `${parts.compact}さんの予定を削除しました <button type="button">元に戻す</button>`;
  toast.querySelector("button").addEventListener("click", () => {
    state.assignments.push(deleted);
    renderBoard();
    markDirty();
    toast.remove();
  });
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 6000);
}

function slotFromEvent(event, grid) {
  const rect = grid.getBoundingClientRect();
  return clamp(Math.floor(((event.clientX - rect.left) / rect.width) * SLOT_COUNT), 0, SLOT_COUNT - 1);
}

function slotBoundaryFromEvent(event, grid) {
  const rect = grid.getBoundingClientRect();
  return clamp(Math.round(((event.clientX - rect.left) / rect.width) * SLOT_COUNT), 0, SLOT_COUNT);
}

function boundedMove(item, initialStart, initialEnd, desiredStart, ignoreKey) {
  const length = initialEnd - initialStart;
  const direction = Math.sign(desiredStart - initialStart);
  if (direction === 0) return [initialStart, initialEnd];
  let acceptedStart = initialStart;
  for (let nextStart = initialStart + direction; direction > 0 ? nextStart <= desiredStart : nextStart >= desiredStart; nextStart += direction) {
    const nextEnd = nextStart + length;
    if (!canPlace(item, nextStart, nextEnd, ignoreKey)) break;
    acceptedStart = nextStart;
  }
  return [acceptedStart, acceptedStart + length];
}

function boundedResizeEnd(item, fixedStart, initialEnd, desiredEnd, ignoreKey) {
  const direction = Math.sign(desiredEnd - initialEnd);
  if (direction === 0) return initialEnd;
  let acceptedEnd = initialEnd;
  for (let nextEnd = initialEnd + direction; direction > 0 ? nextEnd <= desiredEnd : nextEnd >= desiredEnd; nextEnd += direction) {
    if (nextEnd <= fixedStart) break;
    if (!canPlace(item, fixedStart, nextEnd, ignoreKey)) break;
    acceptedEnd = nextEnd;
  }
  return acceptedEnd;
}

function boundedResizeStart(item, initialStart, desiredStart, fixedEnd, ignoreKey) {
  const direction = Math.sign(desiredStart - initialStart);
  if (direction === 0) return initialStart;
  let acceptedStart = initialStart;
  for (let nextStart = initialStart + direction; direction > 0 ? nextStart <= desiredStart : nextStart >= desiredStart; nextStart += direction) {
    if (nextStart >= fixedEnd) break;
    if (!canPlace(item, nextStart, fixedEnd, ignoreKey)) break;
    acceptedStart = nextStart;
  }
  return acceptedStart;
}

function canPlace(item, startSlot, endSlot, ignoreKey = assignmentKey(item)) {
  if (endSlot <= startSlot) return false;
  return state.assignments.every((other) => {
    if (assignmentKey(other) === ignoreKey) return true;
    const related =
      Number(other.wheelchair_id) === Number(item.wheelchair_id) ||
      Number(other.patient_id) === Number(item.patient_id);
    if (!related) return true;
    return !(startSlot < Number(other.end_slot) && Number(other.start_slot) < endSlot);
  });
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function highlightConflicts() {
  document.querySelectorAll(".assignment").forEach((el) => el.classList.remove("conflict"));
  const conflicts = new Set();
  for (let i = 0; i < state.assignments.length; i += 1) {
    for (let j = i + 1; j < state.assignments.length; j += 1) {
      const a = state.assignments[i];
      const b = state.assignments[j];
      const overlap = a.start_slot < b.end_slot && b.start_slot < a.end_slot;
      if (!overlap) continue;
      if (Number(a.wheelchair_id) === Number(b.wheelchair_id) || Number(a.patient_id) === Number(b.patient_id)) {
        conflicts.add(assignmentKey(a));
        conflicts.add(assignmentKey(b));
      }
    }
  }
  conflicts.forEach((key) => {
    const el = document.querySelector(`.assignment[data-key="${CSS.escape(key)}"]`);
    if (el) el.classList.add("conflict");
  });
  return conflicts.size;
}

async function save() {
  const conflictCount = highlightConflicts();
  if (conflictCount > 0) {
    alert("時間帯の重複があります。赤い予定を修正してください。");
    return;
  }
  const response = await fetch(`/api/assignments/${state.day}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ assignments: state.assignments }),
  });
  const data = await response.json();
  if (!response.ok) {
    alert((data.errors || ["保存できませんでした。"]).join("\n"));
    return;
  }
  state.assignments = data.assignments;
  state.savedSnapshot = serializeAssignments();
  renderBoard();
  markDirty();
}

document.getElementById("patientSearch").addEventListener("input", renderPatients);
document.getElementById("saveTimeline").addEventListener("click", save);
document.getElementById("resetDay").addEventListener("click", async () => {
  const dayData = await fetch(`/api/assignments/${state.day}`).then((r) => r.json());
  state.assignments = dayData.assignments;
  renderBoard();
  markDirty();
});

document.getElementById("rangeDaytime").addEventListener("click", () => applyViewRange(true, "daytime"));
document.getElementById("rangeFull").addEventListener("click", () => applyViewRange(true, "full"));

function applyViewRange(shouldScroll = true, mode = state.viewRange) {
  state.viewRange = mode;
  if (!timelineScroll) return;
  timelineScroll.classList.toggle("range-daytime", mode === "daytime");
  timelineScroll.classList.toggle("range-full", mode === "full");
  document.getElementById("rangeDaytime").classList.toggle("active", mode === "daytime");
  document.getElementById("rangeFull").classList.toggle("active", mode === "full");
  const timeBoard = document.getElementById("timeBoard");
  const labelWidth = 140;
  const availableTimeWidth = Math.max(480, timelineScroll.clientWidth - labelWidth);
  const visibleSlots = mode === "daytime" ? 16 : SLOT_COUNT;
  const slotWidth = mode === "daytime" ? Math.max(32, availableTimeWidth / visibleSlots) : availableTimeWidth / SLOT_COUNT;
  if (timeBoard) {
    const boardWidth = labelWidth + slotWidth * SLOT_COUNT;
    timeBoard.style.width = `${boardWidth}px`;
    timeBoard.style.minWidth = `${boardWidth}px`;
  }
  document.querySelectorAll(".assignment").forEach((element) => {
    const item = state.assignments.find((assignment) => assignmentKey(assignment) === element.dataset.key);
    if (item) {
      updateAssignmentLabelPosition(element, Number(item.start_slot), Number(item.end_slot));
    }
  });
  if (shouldScroll || mode === "daytime") {
    requestAnimationFrame(() => {
      const grid = document.querySelector(".row-grid");
      if (!grid) return;
      const currentSlotWidth = grid.getBoundingClientRect().width / SLOT_COUNT;
      timelineScroll.scrollLeft = mode === "daytime" ? currentSlotWidth * 6 : 0;
    });
  }
}

load();
