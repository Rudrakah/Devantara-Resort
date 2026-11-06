const adminApi = async (path, options = {}) => {
  let response;
  try {
    response = await fetch(path, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(sessionStorage.getItem("devantara-admin-token")
          ? { Authorization: `Bearer ${sessionStorage.getItem("devantara-admin-token")}` }
          : {}),
        ...options.headers,
      },
    });
  } catch {
    throw new Error("The resort service could not be reached.");
  }
  let data;
  try {
    data = response.status === 204 ? null : await response.json();
  } catch {
    throw new Error("The resort service returned an unreadable response.");
  }
  if (!response.ok) {
    const detail = Array.isArray(data?.detail) ? data.detail.map((item) => item.msg).join(" ") : data?.detail;
    throw new Error(detail || "The request could not be completed.");
  }
  return data;
};

const loginPanel = document.querySelector("#login-panel");
const dashboard = document.querySelector("#dashboard");
const loginFeedback = document.querySelector("#login-feedback");
const dashboardFeedback = document.querySelector("#dashboard-feedback");
const logoutButton = document.querySelector("#logout");
const currency = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 });

function el(tag, text, className = "") {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function setFormMessage(form, message, isError = false) {
  const feedback = form.querySelector("[data-feedback]");
  if (!feedback) return;
  feedback.textContent = message;
  feedback.dataset.state = isError ? "error" : "success";
}

function setDashboardMessage(message, isError = false) {
  dashboardFeedback.textContent = message;
  dashboardFeedback.dataset.state = isError ? "error" : "success";
}

function showDashboard() {
  loginPanel.hidden = true;
  dashboard.hidden = false;
  logoutButton.hidden = false;
}

function showLogin() {
  loginPanel.hidden = false;
  dashboard.hidden = true;
  logoutButton.hidden = true;
}

async function loadOverview() {
  const data = await adminApi("/api/admin/dashboard");
  const metrics = [
    ["All bookings", data.total_bookings],
    ["Today's bookings", data.today_bookings],
    ["Awaiting payment", data.pending_bookings],
    ["Confirmed", data.confirmed_bookings],
    ["Cancelled / expired", data.cancelled_bookings],
    ["Net captured revenue", currency.format(Number(data.revenue))],
    ["New enquiries", data.new_enquiries],
  ];
  const grid = document.querySelector("#metrics");
  grid.replaceChildren();
  for (const [label, value] of metrics) {
    const card = el("article", undefined, "metric-card");
    card.append(el("span", label), el("strong", String(value)));
    grid.append(card);
  }
}

function addTableCell(row, value, strong = false) {
  const cell = document.createElement("td");
  const content = strong ? el("strong", value) : document.createTextNode(value ?? "");
  cell.append(content);
  row.append(cell);
  return cell;
}

async function loadBookings() {
  const data = await adminApi("/api/admin/bookings?limit=250");
  const table = document.querySelector("#bookings-table");
  table.replaceChildren();
  for (const booking of data) {
    const row = document.createElement("tr");
    addTableCell(row, booking.booking_ref, true);
    addTableCell(row, `${booking.guest_name}\n${booking.guest_email}`);
    addTableCell(row, `${booking.room_name}\n${booking.check_in} → ${booking.check_out}`);
    addTableCell(row, currency.format(Number(booking.total_amount)));
    addTableCell(row, `${booking.status} · ${booking.payment_status}`);
    const action = document.createElement("td");
    if (booking.status !== "cancelled" && booking.status !== "expired") {
      const cancel = el("button", "Cancel", "button button-outline");
      cancel.type = "button";
      cancel.addEventListener("click", async () => {
        const reason = window.prompt("Cancellation reason:", "Cancelled by resort administrator.");
        if (reason === null) return;
        cancel.disabled = true;
        try {
          await adminApi(`/api/admin/bookings/${encodeURIComponent(booking.booking_ref)}/cancel`, {
            method: "POST",
            body: JSON.stringify({ reason }),
          });
          await Promise.all([loadBookings(), loadOverview()]);
        } catch (error) {
          setDashboardMessage(error.message, true);
          cancel.disabled = false;
        }
      });
      action.append(cancel);
    }
    row.append(action);
    table.append(row);
  }
  if (!data.length) table.append(emptyRow(6, "No bookings have been recorded."));
}

function emptyRow(columnCount, message) {
  const row = document.createElement("tr");
  const cell = document.createElement("td");
  cell.colSpan = columnCount;
  cell.textContent = message;
  row.append(cell);
  return row;
}

async function loadCategories() {
  const data = await adminApi("/api/admin/categories");
  const roomCategory = document.querySelector('#room-form select[name="category_id"]');
  roomCategory.replaceChildren();
  for (const category of data) {
    const option = el("option", category.name);
    option.value = category.id;
    roomCategory.append(option);
  }
  return data;
}

async function loadRooms() {
  const [rooms, categories] = await Promise.all([adminApi("/api/admin/rooms"), loadCategories()]);
  const roomSelect = document.querySelector('#availability-form select[name="room_id"]');
  roomSelect.replaceChildren();
  for (const room of rooms.filter((item) => item.is_active)) {
    const option = el("option", room.name);
    option.value = room.id;
    roomSelect.append(option);
  }
  const categoryNames = new Map(categories.map((item) => [item.id, item.name]));
  const table = document.querySelector("#rooms-table");
  table.replaceChildren();
  for (const room of rooms) {
    const row = document.createElement("tr");
    addTableCell(row, room.name, true);
    addTableCell(row, categoryNames.get(room.category_id) || "—");
    addTableCell(row, currency.format(Number(room.base_rate)));
    addTableCell(row, `${room.capacity_adults} adults · ${room.capacity_children} children · ${room.inventory} units`);
    addTableCell(row, room.is_active ? "Active" : "Archived");
    const actions = document.createElement("td");
    const edit = el("button", "Edit", "button button-outline");
    edit.type = "button";
    edit.addEventListener("click", () => editRoom(room));
    actions.append(edit);
    if (room.is_active) {
      const archive = el("button", "Archive", "button button-outline");
      archive.type = "button";
      archive.addEventListener("click", async () => {
        if (!window.confirm(`Archive ${room.name}? Existing bookings are retained.`)) return;
        try {
          await adminApi(`/api/admin/rooms/${room.id}`, { method: "DELETE" });
          await loadRooms();
        } catch (error) {
          setDashboardMessage(error.message, true);
        }
      });
      actions.append(archive);
    }
    row.append(actions);
    table.append(row);
  }
  if (!rooms.length) table.append(emptyRow(6, "Create a room category, then add a room with your verified rate and capacity."));
}

function editRoom(room) {
  const form = document.querySelector("#room-form");
  form.elements.room_id.value = room.id;
  form.elements.name.value = room.name;
  form.elements.category_id.value = room.category_id;
  form.elements.base_rate.value = room.base_rate;
  form.elements.capacity_adults.value = room.capacity_adults;
  form.elements.capacity_children.value = room.capacity_children;
  form.elements.inventory.value = room.inventory;
  form.elements.description.value = room.description || "";
  form.elements.amenities.value = room.amenities || "";
  form.elements.image_url.value = room.image_url || "";
  form.querySelector("#room-form-title").textContent = `Edit ${room.name}`;
  form.querySelector("#room-submit").textContent = "Save changes";
  form.querySelector("#room-edit-cancel").hidden = false;
  form.scrollIntoView({ behavior: "smooth", block: "start" });
}

function resetRoomForm() {
  const form = document.querySelector("#room-form");
  form.reset();
  form.elements.room_id.value = "";
  form.querySelector("#room-form-title").textContent = "Add a room";
  form.querySelector("#room-submit").textContent = "Create room";
  form.querySelector("#room-edit-cancel").hidden = true;
  form.elements.capacity_adults.value = "2";
  form.elements.capacity_children.value = "0";
  form.elements.inventory.value = "1";
}

async function loadEnquiries() {
  const data = await adminApi("/api/admin/enquiries?limit=250");
  const table = document.querySelector("#enquiries-table");
  table.replaceChildren();
  for (const enquiry of data) {
    const row = document.createElement("tr");
    addTableCell(row, new Date(enquiry.created_at).toLocaleString());
    addTableCell(row, `${enquiry.name}\n${enquiry.phone || ""}`);
    addTableCell(row, enquiry.email);
    addTableCell(row, `${enquiry.subject}\n${enquiry.message}`);
    const cell = document.createElement("td");
    const select = document.createElement("select");
    select.setAttribute("aria-label", `Status for enquiry from ${enquiry.name}`);
    for (const value of ["new", "in_progress", "responded", "archived"]) {
      const option = el("option", value.replace("_", " "));
      option.value = value;
      option.selected = value === enquiry.status;
      select.append(option);
    }
    select.addEventListener("change", async () => {
      select.disabled = true;
      try {
        await adminApi(`/api/admin/enquiries/${enquiry.id}`, {
          method: "PUT",
          body: JSON.stringify({ status: select.value }),
        });
        await loadOverview();
      } catch (error) {
        setDashboardMessage(error.message, true);
        select.disabled = false;
      }
    });
    cell.append(select);
    row.append(cell);
    table.append(row);
  }
  if (!data.length) table.append(emptyRow(5, "No enquiries have been received."));
}

async function loadPayments() {
  const data = await adminApi("/api/admin/payments?limit=250");
  const table = document.querySelector("#payments-table");
  table.replaceChildren();
  for (const payment of data) {
    const row = document.createElement("tr");
    addTableCell(row, payment.payment_ref, true);
    addTableCell(row, payment.booking_ref);
    addTableCell(row, payment.guest_name);
    addTableCell(row, currency.format(Number(payment.amount)));
    addTableCell(row, `${payment.status}${Number(payment.refund_amount) ? ` · refunded ${currency.format(Number(payment.refund_amount))}` : ""}`);
    const cell = document.createElement("td");
    if (payment.status === "captured" || payment.status === "partially_refunded") {
      const refund = el("button", "Refund", "button button-outline");
      refund.type = "button";
      refund.addEventListener("click", async () => {
        const amount = window.prompt("Refund amount in INR (leave empty for the remaining amount):");
        if (amount === null) return;
        const reason = window.prompt("Reason for this refund (optional):", "") ?? "";
        refund.disabled = true;
        try {
          await adminApi(`/api/admin/payments/${encodeURIComponent(payment.payment_ref)}/refund`, {
            method: "POST",
            body: JSON.stringify({ amount: amount.trim() ? Number(amount) : null, reason }),
          });
          await loadPayments();
        } catch (error) {
          setDashboardMessage(error.message, true);
          refund.disabled = false;
        }
      });
      cell.append(refund);
    }
    row.append(cell);
    table.append(row);
  }
  if (!data.length) table.append(emptyRow(6, "No payment records have been created."));
}

async function loadActivity() {
  const data = await adminApi("/api/admin/activity?limit=250");
  const table = document.querySelector("#activity-table");
  table.replaceChildren();
  for (const activity of data) {
    const row = document.createElement("tr");
    addTableCell(row, new Date(activity.created_at).toLocaleString());
    addTableCell(row, activity.action);
    addTableCell(row, `${activity.entity_type} · ${activity.entity_id}`);
    addTableCell(row, activity.details);
    table.append(row);
  }
  if (!data.length) table.append(emptyRow(4, "No admin activity has been recorded."));
}

function contentRow(parent, name, detail, actionLabel, action) {
  const row = el("div", undefined, "admin-list-item");
  const description = el("div");
  description.append(el("strong", name), el("span", detail || ""));
  const button = el("button", actionLabel, "button button-outline");
  button.type = "button";
  button.addEventListener("click", action);
  row.append(description, button);
  parent.append(row);
}

async function loadContent() {
  const [amenities, packages, gallery, siteInfo] = await Promise.all([
    adminApi("/api/admin/amenities"),
    adminApi("/api/admin/packages"),
    adminApi("/api/admin/gallery"),
    adminApi("/api/site-info"),
  ]);
  const amenityList = document.querySelector("#amenities-list");
  const packageList = document.querySelector("#packages-list");
  const galleryList = document.querySelector("#gallery-list");
  amenityList.replaceChildren();
  packageList.replaceChildren();
  galleryList.replaceChildren();
  for (const item of amenities) {
    contentRow(amenityList, item.name, item.is_active ? "Active" : "Archived", item.is_active ? "Archive" : "Archived", async () => {
      if (!item.is_active && !window.confirm(`Re-enable ${item.name}?`)) return;
      try {
        await adminApi(`/api/admin/amenities/${item.id}`, {
          method: "PUT",
          body: JSON.stringify({ is_active: !item.is_active }),
        });
        await loadContent();
      } catch (error) {
        setDashboardMessage(error.message, true);
      }
    });
  }
  for (const item of packages) {
    contentRow(packageList, item.name, item.price === null ? "No public price" : currency.format(Number(item.price)), item.is_active ? "Archive" : "Archived", async () => {
      if (!item.is_active && !window.confirm(`Re-enable ${item.name}?`)) return;
      try {
        await adminApi(`/api/admin/packages/${item.id}`, {
          method: "PUT",
          body: JSON.stringify({ is_active: !item.is_active }),
        });
        await loadContent();
      } catch (error) {
        setDashboardMessage(error.message, true);
      }
    });
  }
  for (const item of gallery) {
    contentRow(galleryList, item.title, item.is_published ? "Published" : "Unpublished", item.is_published ? "Unpublish" : "Publish", async () => {
      try {
        await adminApi(`/api/admin/gallery/${item.id}`, {
          method: "PUT",
          body: JSON.stringify({ is_published: !item.is_published }),
        });
        await loadContent();
      } catch (error) {
        setDashboardMessage(error.message, true);
      }
    });
  }
  document.querySelector("#admin-site-info").textContent =
    [siteInfo.email, siteInfo.phone, siteInfo.address].filter(Boolean).join(" · ") || "No public contact details are configured.";
}

const panelLoaders = {
  overview: loadOverview,
  bookings: loadBookings,
  rooms: loadRooms,
  enquiries: loadEnquiries,
  payments: loadPayments,
  content: loadContent,
  activity: loadActivity,
};

async function selectPanel(name) {
  document.querySelectorAll(".admin-tabs button").forEach((button) => {
    const active = button.dataset.panel === name;
    button.classList.toggle("active", active);
    button.setAttribute("aria-current", active ? "page" : "false");
  });
  document.querySelectorAll(".admin-content-panel").forEach((panel) => {
    panel.hidden = panel.dataset.content !== name;
  });
  setDashboardMessage("");
  try {
    await panelLoaders[name]();
  } catch (error) {
    setDashboardMessage(error.message, true);
  }
}

document.querySelector("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const submit = form.querySelector('button[type="submit"]');
  submit.disabled = true;
  loginFeedback.textContent = "Signing in…";
  try {
    const result = await adminApi("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email: form.elements.email.value, password: form.elements.password.value }),
    });
    sessionStorage.setItem("devantara-admin-token", result.access_token);
    form.reset();
    showDashboard();
    await selectPanel("overview");
  } catch (error) {
    loginFeedback.textContent = error.message;
  } finally {
    submit.disabled = false;
  }
});

logoutButton.addEventListener("click", () => {
  sessionStorage.removeItem("devantara-admin-token");
  showLogin();
});

document.querySelectorAll(".admin-tabs button").forEach((button) => {
  button.addEventListener("click", () => selectPanel(button.dataset.panel));
});
document.querySelectorAll("[data-refresh]").forEach((button) => {
  button.addEventListener("click", () => {
    const panel = button.closest(".admin-content-panel").dataset.content;
    selectPanel(panel);
  });
});

document.querySelector("#category-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    const result = await adminApi("/api/admin/categories", {
      method: "POST",
      body: JSON.stringify(Object.fromEntries(new FormData(form))),
    });
    form.reset();
    setFormMessage(form, `Created category ${result.name}.`);
    await loadRooms();
  } catch (error) {
    setFormMessage(form, error.message, true);
  }
});

document.querySelector("#room-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const fields = Object.fromEntries(new FormData(form));
  const roomId = fields.room_id;
  delete fields.room_id;
  for (const key of ["category_id", "capacity_adults", "capacity_children", "inventory"]) fields[key] = Number(fields[key]);
  fields.base_rate = Number(fields.base_rate);
  try {
    const result = await adminApi(roomId ? `/api/admin/rooms/${roomId}` : "/api/admin/rooms", {
      method: roomId ? "PUT" : "POST",
      body: JSON.stringify(fields),
    });
    resetRoomForm();
    setFormMessage(form, `${roomId ? "Updated" : "Created"} ${result.name}.`);
    await loadRooms();
  } catch (error) {
    setFormMessage(form, error.message, true);
  }
});

document.querySelector("#room-edit-cancel").addEventListener("click", resetRoomForm);

document.querySelector("#availability-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const fields = Object.fromEntries(new FormData(form));
  const payload = {
    room_id: Number(fields.room_id),
    start_date: fields.start_date,
    end_date: fields.end_date,
    is_closed: form.elements.is_closed.checked,
    price_override: fields.price_override ? Number(fields.price_override) : null,
  };
  try {
    const result = await adminApi("/api/admin/availability", { method: "PUT", body: JSON.stringify(payload) });
    setFormMessage(form, `Updated ${result.updated_dates} date(s).`);
  } catch (error) {
    setFormMessage(form, error.message, true);
  }
});

document.querySelector("#amenity-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const fields = Object.fromEntries(new FormData(form));
  try {
    await adminApi("/api/admin/amenities", {
      method: "POST",
      body: JSON.stringify({ ...fields, is_active: true }),
    });
    form.reset();
    setFormMessage(form, "Amenity added.");
    await loadContent();
  } catch (error) {
    setFormMessage(form, error.message, true);
  }
});

document.querySelector("#package-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const fields = Object.fromEntries(new FormData(form));
  const payload = {
    ...fields,
    price: fields.price ? Number(fields.price) : null,
    starts_on: fields.starts_on || null,
    ends_on: fields.ends_on || null,
    is_active: true,
  };
  try {
    await adminApi("/api/admin/packages", { method: "POST", body: JSON.stringify(payload) });
    form.reset();
    setFormMessage(form, "Package added.");
    await loadContent();
  } catch (error) {
    setFormMessage(form, error.message, true);
  }
});

document.querySelector("#gallery-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const fields = Object.fromEntries(new FormData(form));
  const payload = {
    ...fields,
    is_published: form.elements.is_published.checked,
    sort_order: 0,
  };
  try {
    await adminApi("/api/admin/gallery", { method: "POST", body: JSON.stringify(payload) });
    form.reset();
    form.elements.category.value = "stay";
    setFormMessage(form, "Gallery image added.");
    await loadContent();
  } catch (error) {
    setFormMessage(form, error.message, true);
  }
});

async function restoreSession() {
  if (!sessionStorage.getItem("devantara-admin-token")) return;
  try {
    await adminApi("/api/auth/me");
    showDashboard();
    await selectPanel("overview");
  } catch {
    sessionStorage.removeItem("devantara-admin-token");
  }
}

restoreSession();
