const API_BASE = (new URLSearchParams(location.search).get("api") || "").replace(/\/$/, "");
const api = async (path, options = {}) => {
  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: { "Content-Type": "application/json", ...options.headers },
    });
  } catch {
    throw new Error("The resort service could not be reached. Please try again later.");
  }

  let data;
  try {
    data = response.status === 204 ? null : await response.json();
  } catch {
    throw new Error("The resort service returned an unreadable response. Please try again later.");
  }
  if (!response.ok) {
    const detail = Array.isArray(data?.detail)
      ? data.detail.map((error) => error.msg).join(" ")
      : data?.detail;
    throw new Error(detail || "The request could not be completed.");
  }
  return data;
};

const menuToggle = document.querySelector(".menu-toggle");
const navigation = document.querySelector(".navigation");

menuToggle.addEventListener("click", () => {
  const isExpanded = menuToggle.getAttribute("aria-expanded") === "true";
  menuToggle.setAttribute("aria-expanded", String(!isExpanded));
  menuToggle.setAttribute("aria-label", isExpanded ? "Open navigation" : "Close navigation");
  navigation.classList.toggle("is-open", !isExpanded);
});

navigation.addEventListener("click", (event) => {
  if (event.target.closest("a")) {
    menuToggle.setAttribute("aria-expanded", "false");
    menuToggle.setAttribute("aria-label", "Open navigation");
    navigation.classList.remove("is-open");
  }
});

const checkIn = document.querySelector("#check-in");
const checkOut = document.querySelector("#check-out");
const bookingFeedback = document.querySelector("#booking-feedback");
const bookingResults = document.querySelector("#booking-results");
const today = new Date();
const todayString = new Date(today.getTime() - today.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
checkIn.min = todayString;
checkOut.min = todayString;

checkIn.addEventListener("change", () => {
  if (!checkIn.value) return;
  const nextDay = new Date(`${checkIn.value}T00:00:00`);
  nextDay.setDate(nextDay.getDate() + 1);
  checkOut.min = `${nextDay.getFullYear()}-${String(nextDay.getMonth() + 1).padStart(2, "0")}-${String(nextDay.getDate()).padStart(2, "0")}`;
  if (checkOut.value && checkOut.value < checkOut.min) checkOut.value = "";
});

function formatPrice(amount) {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2,
  }).format(Number(amount));
}

function makeElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function setBookingMessage(message, isError = false) {
  bookingFeedback.textContent = message;
  bookingFeedback.dataset.state = isError ? "error" : "success";
}

function guestDetailsForm(room, search) {
  const form = makeElement("form", "guest-details-form");
  const name = makeElement("input");
  name.name = "guest_name";
  name.autocomplete = "name";
  name.required = true;
  name.maxLength = 120;
  const email = makeElement("input");
  email.type = "email";
  email.name = "guest_email";
  email.autocomplete = "email";
  email.required = true;
  email.maxLength = 254;
  const phone = makeElement("input");
  phone.type = "tel";
  phone.name = "guest_phone";
  phone.autocomplete = "tel";
  phone.required = true;
  phone.minLength = 7;
  phone.maxLength = 32;

  for (const [labelText, input] of [["Your name", name], ["Email address", email], ["Phone number", phone]]) {
    const label = makeElement("label", "", labelText);
    label.append(input);
    form.append(label);
  }

  const submit = makeElement("button", "button", "Continue to payment");
  submit.type = "submit";
  form.append(submit);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    submitBooking(room, search, new FormData(form), form);
  });
  return form;
}

function renderAvailableRooms(rooms, search) {
  bookingResults.replaceChildren();
  const heading = makeElement("h3", "", "Available for your stay");
  bookingResults.append(heading);
  if (rooms.length === 0) {
    bookingResults.append(makeElement("p", "booking-state", "No rooms are available for those dates and guest numbers. Please choose another stay or contact our team."));
    return;
  }
  for (const room of rooms) {
    const card = makeElement("article", "availability-card");
    const details = makeElement("div");
    details.append(makeElement("h4", "", room.name));
    details.append(makeElement("p", "", `${room.nights} night${room.nights === 1 ? "" : "s"} · ${room.capacity_adults} adult capacity${room.capacity_children ? ` · up to ${room.capacity_children} children` : ""}`));
    if (room.description) details.append(makeElement("p", "", room.description));
    const price = makeElement("p", "availability-price", `${formatPrice(room.total_amount)} total`);
    const choose = makeElement("button", "button", "Choose this room");
    choose.type = "button";
    choose.addEventListener("click", () => {
      card.querySelector(".guest-details-form")?.remove();
      card.append(guestDetailsForm(room, search));
      card.querySelector("input")?.focus();
    });
    card.append(details, price, choose);
    bookingResults.append(card);
  }
}

function renderBookingState(booking, message, allowCancel = true) {
  bookingResults.replaceChildren();
  const state = makeElement("div", "booking-state");
  state.append(makeElement("p", "", message));
  state.append(makeElement("p", "", `Reference: ${booking.booking_ref}`));
  state.append(makeElement("p", "", `${booking.room_name} · ${booking.check_in} to ${booking.check_out} · ${formatPrice(booking.total_amount)}`));
  if (booking.expires_at) {
    state.append(makeElement("p", "", `This unpaid room hold expires at ${new Date(`${booking.expires_at}Z`).toLocaleString()}.`));
  }
  if (allowCancel) {
    const cancel = makeElement("button", "button button-outline", "Cancel this request");
    cancel.type = "button";
    cancel.addEventListener("click", async () => {
      if (!window.confirm("Cancel this booking request?")) return;
      cancel.disabled = true;
      try {
        await api(`/api/bookings/${encodeURIComponent(booking.booking_ref)}/cancel?email=${encodeURIComponent(booking.guest_email)}`, { method: "POST" });
        state.replaceChildren(makeElement("p", "", "Your booking request has been cancelled."));
      } catch (error) {
        state.append(makeElement("p", "form-feedback", error.message));
        cancel.disabled = false;
      }
    });
    state.append(cancel);
  }
  bookingResults.append(state);
}

let razorpayScriptPromise;
function loadRazorpay() {
  if (window.Razorpay) return Promise.resolve();
  if (!razorpayScriptPromise) {
    razorpayScriptPromise = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "https://checkout.razorpay.com/v1/checkout.js";
      script.onload = resolve;
      script.onerror = () => reject(new Error("The payment checkout could not be loaded. Your booking is still pending; please contact the resort."));
      document.head.append(script);
    });
  }
  return razorpayScriptPromise;
}

async function openPaymentCheckout(booking) {
  const order = await api("/api/payments/create-order", {
    method: "POST",
    body: JSON.stringify({ booking_ref: booking.booking_ref }),
  });
  await loadRazorpay();
  const checkout = new window.Razorpay({
    key: order.key_id,
    amount: order.amount,
    currency: order.currency,
    name: order.name,
    description: order.description,
    order_id: order.order_id,
    prefill: order.prefill,
    theme: { color: "#d7ad60" },
    handler: async (response) => {
      bookingResults.replaceChildren(makeElement("p", "booking-state", "Verifying payment with the gateway…"));
      try {
        const result = await api("/api/payments/verify", {
          method: "POST",
          body: JSON.stringify({
            booking_ref: booking.booking_ref,
            razorpay_order_id: response.razorpay_order_id,
            razorpay_payment_id: response.razorpay_payment_id,
            razorpay_signature: response.razorpay_signature,
          }),
        });
        const message = result.booking_status === "confirmed"
          ? "Payment verified. Your booking is confirmed."
          : result.message || "Payment was received, but the booking is not confirmed. Please contact the resort.";
        renderBookingState({ ...booking, status: result.booking_status, payment_status: result.payment_status }, message, false);
      } catch (error) {
        bookingResults.replaceChildren(makeElement("p", "booking-state", `Payment could not be confirmed: ${error.message} Check the payment status or contact the resort with reference ${booking.booking_ref}.`));
      }
    },
    modal: {
      ondismiss: () => renderBookingState(booking, "Checkout closed. Your room is held temporarily but the booking is not confirmed until payment is verified."),
    },
  });
  checkout.on("payment.failed", (response) => {
    const description = response?.error?.description || "Payment was not completed.";
    renderBookingState(booking, `${description} Your booking is not confirmed. You can try again while the room hold remains active.`);
    const retry = makeElement("button", "button", "Try payment again");
    retry.type = "button";
    retry.addEventListener("click", async () => {
      retry.disabled = true;
      try {
        await openPaymentCheckout(booking);
      } catch (error) {
        stateError(error.message);
        retry.disabled = false;
      }
    });
    bookingResults.querySelector(".booking-state")?.append(retry);
  });
  checkout.open();
}

function stateError(message) {
  const state = bookingResults.querySelector(".booking-state");
  if (state) state.append(makeElement("p", "form-feedback", message));
}

async function submitBooking(room, search, formData, form) {
  const button = form.querySelector("button");
  button.disabled = true;
  button.textContent = "Creating your booking…";
  try {
    const booking = await api("/api/bookings", {
      method: "POST",
      body: JSON.stringify({
        ...search,
        room_id: room.id,
        guest_name: formData.get("guest_name"),
        guest_email: formData.get("guest_email"),
        guest_phone: formData.get("guest_phone"),
      }),
    });
    try {
      await openPaymentCheckout(booking);
    } catch (error) {
      renderBookingState(
        booking,
        `Your booking request is saved, but payment could not be started: ${error.message} This is not a confirmed reservation.`,
      );
    }
  } catch (error) {
    const message = makeElement("p", "form-feedback", error.message);
    form.append(message);
    button.disabled = false;
    button.textContent = "Continue to payment";
  }
}

document.querySelector("#booking").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  if (!checkIn.value || !checkOut.value || checkOut.value <= checkIn.value) {
    setBookingMessage("Choose a check-out date after your check-in date.", true);
    return;
  }
  const formData = new FormData(form);
  const search = {
    check_in: checkIn.value,
    check_out: checkOut.value,
    adults: Number(formData.get("adults")),
    children: Number(formData.get("children")),
  };
  const submit = form.querySelector(".booking-submit");
  submit.disabled = true;
  submit.textContent = "Checking…";
  bookingResults.replaceChildren(makeElement("p", "booking-state", "Checking room availability…"));
  try {
    const query = new URLSearchParams({
      check_in: search.check_in,
      check_out: search.check_out,
      adults: String(search.adults),
      children: String(search.children),
    });
    const rooms = await api(`/api/availability?${query}`);
    setBookingMessage("");
    renderAvailableRooms(rooms, search);
  } catch (error) {
    setBookingMessage(error.message, true);
    bookingResults.replaceChildren();
  } finally {
    submit.disabled = false;
    submit.innerHTML = 'Check availability <span aria-hidden="true">→</span>';
  }
});

function validImageURL(value) {
  if (!value) return "";
  try {
    const url = new URL(value, location.origin);
    return ["http:", "https:"].includes(url.protocol) ? url.href : "";
  } catch {
    return "";
  }
}

function renderRoomData(rooms) {
  const roomGrid = document.querySelector("#rooms-grid");
  const pricingGrid = document.querySelector("#pricing-grid");
  const feature = document.querySelector("#villa-detail");
  if (!rooms.length) {
    roomGrid.hidden = true;
    pricingGrid.hidden = true;
    feature.hidden = true;
    document.querySelector("#rooms-empty").hidden = false;
    document.querySelector("#pricing-empty").hidden = false;
    return;
  }
  roomGrid.hidden = false;
  pricingGrid.hidden = false;
  feature.hidden = false;
  document.querySelector("#rooms-empty").hidden = true;
  document.querySelector("#pricing-empty").hidden = true;
  const featuredRoom = rooms[0];
  const featureImage = feature.querySelector(".villa-detail-image img");
  const featureImageUrl = validImageURL(featuredRoom.image_url);
  featureImage.src = featureImageUrl || "/devantara-resort.jpg";
  featureImage.alt = featureImageUrl ? featuredRoom.name : "Devantara Resort property";
  feature.querySelector("#room-feature-caption").textContent = featureImageUrl ? featuredRoom.name : "A glimpse of the property";
  feature.querySelector("#room-feature-name").textContent = featuredRoom.name;
  const featurePrice = feature.querySelector("#room-feature-price");
  featurePrice.replaceChildren(document.createTextNode(formatPrice(featuredRoom.base_rate)));
  featurePrice.append(makeElement("small", "", " / night"));
  feature.querySelector("#room-feature-description").textContent =
    featuredRoom.description || "Contact the resort for further room details.";
  const featureDetails = feature.querySelector("#room-feature-details");
  featureDetails.replaceChildren(
    makeElement("span", "", `${featuredRoom.capacity_adults} adult capacity`),
    ...(featuredRoom.capacity_children
      ? [makeElement("span", "", `${featuredRoom.capacity_children} child capacity`)]
      : []),
    ...featuredRoom.amenities
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean)
      .map((item) => makeElement("span", "", item)),
  );
  while (roomGrid.children.length > rooms.length) roomGrid.lastElementChild.remove();
  for (let index = 0; index < rooms.length; index += 1) {
    const room = rooms[index];
    let card = roomGrid.children[index];
    if (!card) {
      card = makeElement("article", "room-card");
      const link = makeElement("a", "room-image");
      const image = makeElement("img");
      image.loading = "lazy";
      const arrow = makeElement("span", "room-arrow", "↗");
      arrow.setAttribute("aria-hidden", "true");
      link.append(image, arrow);
      const info = makeElement("div", "room-info");
      const titleWrap = makeElement("div");
      titleWrap.append(makeElement("h3"), makeElement("p"));
      const price = makeElement("p", "room-price");
      const details = makeElement("div", "room-details");
      info.append(titleWrap, price, details);
      card.append(link, info);
      roomGrid.append(card);
    }
    card.classList.toggle("featured-room", index === 1);
    const link = card.querySelector(".room-image");
    link.href = "#booking";
    link.setAttribute("aria-label", `Check availability for ${room.name}`);
    const image = card.querySelector("img");
    image.alt = room.name;
    const safeImage = validImageURL(room.image_url);
    if (safeImage) image.src = safeImage;
    const info = card.querySelector(".room-info");
    info.querySelector("h3").textContent = room.name;
    info.querySelector(".room-info > div > p").textContent = room.description || "Contact us for room details.";
    const price = info.querySelector(".room-price");
    price.replaceChildren(document.createTextNode(formatPrice(room.base_rate)));
    price.append(makeElement("small", "", "/ night"));
    const details = info.querySelector(".room-details");
    details.replaceChildren(
      makeElement("span", "", `${room.capacity_adults} adult capacity`),
      makeElement("span", "", `${room.capacity_children} child capacity`),
      makeElement("span", "", `${room.inventory} available unit${room.inventory === 1 ? "" : "s"}`),
    );
    card.querySelector(".room-tag")?.remove();
  }
  pricingGrid.replaceChildren();
  for (const room of rooms) {
    const card = makeElement("article", "pricing-card");
    card.append(makeElement("h3", "", room.name));
    const price = makeElement("p", "pricing-amount", formatPrice(room.base_rate));
    price.append(makeElement("small", "", " / night"));
    card.append(price);
    const list = makeElement("ul");
    list.append(makeElement("li", "", `${room.capacity_adults} adult capacity`));
    if (room.capacity_children) list.append(makeElement("li", "", `${room.capacity_children} child capacity`));
    for (const amenity of room.amenities.split(",").map((item) => item.trim()).filter(Boolean).slice(0, 4)) {
      list.append(makeElement("li", "", amenity));
    }
    card.append(list);
    const action = makeElement("a", "button button-outline", "Check availability");
    action.href = "#booking";
    card.append(action);
    pricingGrid.append(card);
  }
}

async function loadRooms() {
  try {
    renderRoomData(await api("/api/rooms"));
  } catch (error) {
    renderRoomData([]);
    document.querySelector("#rooms-empty").textContent = "Room details could not be loaded. Please try again later.";
    document.querySelector("#pricing-empty").textContent = "Current room rates could not be loaded. Please try again later.";
    console.error("Could not load resort rooms.", error);
  }
}

async function loadAmenities() {
  const grid = document.querySelector("#amenities-grid");
  const empty = document.querySelector("#amenities-empty");
  try {
    const amenities = await api("/api/amenities");
    grid.replaceChildren();
    grid.hidden = amenities.length === 0;
    empty.hidden = amenities.length > 0;
    for (const [index, amenity] of amenities.entries()) {
      const card = makeElement("article", "amenity-card");
      card.append(makeElement("span", "amenity-number", String(index + 1).padStart(2, "0")));
      card.append(makeElement("span", "amenity-icon", amenity.icon || "✳"));
      card.append(makeElement("h3", "", amenity.name));
      card.append(makeElement("p", "", amenity.description));
      grid.append(card);
    }
  } catch (error) {
    grid.hidden = true;
    empty.textContent = "Resort facilities could not be loaded. Please try again later.";
    empty.hidden = false;
    console.error("Could not load resort facilities.", error);
  }
}

async function loadPackages() {
  const grid = document.querySelector("#packages-grid");
  const empty = document.querySelector("#packages-empty");
  try {
    const packages = await api("/api/packages");
    grid.replaceChildren();
    grid.hidden = packages.length === 0;
    empty.hidden = packages.length > 0;
    for (const [index, item] of packages.entries()) {
      const card = makeElement("article", `offer-card${index % 2 ? " offer-card-gold" : ""}`);
      card.append(makeElement("span", "offer-index", `0${index + 1} / DEVANTARA`));
      card.append(makeElement("h3", "", item.name));
      card.append(makeElement("p", "", item.description));
      if (item.price !== null) card.append(makeElement("p", "offer-price", formatPrice(item.price)));
      const link = makeElement("a", "", "Enquire about this package ↗");
      link.href = "#contact";
      card.append(link);
      grid.append(card);
    }
  } catch (error) {
    grid.hidden = true;
    empty.textContent = "Resort packages could not be loaded. Please try again later.";
    empty.hidden = false;
    console.error("Could not load resort packages.", error);
  }
}

async function loadGallery() {
  const grid = document.querySelector(".gallery-grid");
  const empty = document.querySelector("#gallery-empty");
  try {
    const images = await api("/api/gallery");
    const visibleImages = images.filter((image) => validImageURL(image.image_url));
    grid.replaceChildren();
    grid.hidden = visibleImages.length === 0;
    empty.hidden = visibleImages.length > 0;
    for (const [index, item] of visibleImages.entries()) {
      const link = makeElement("a", `gallery-item${index === 0 ? " gallery-tall" : ""}`);
      link.dataset.category = item.category;
      link.href = "#rooms";
      link.setAttribute("aria-label", item.alt_text || item.title);
      const image = makeElement("img");
      image.src = validImageURL(item.image_url);
      image.alt = item.alt_text || item.title;
      image.loading = "lazy";
      const caption = makeElement("span", "", item.title);
      if (item.category) caption.append(makeElement("small", "", item.category));
      link.append(image, caption);
      grid.append(link);
    }
  } catch (error) {
    grid.hidden = true;
    empty.textContent = "Gallery images could not be loaded. Please try again later.";
    empty.hidden = false;
    console.error("Could not load the resort gallery.", error);
  }
}

async function loadSiteInfo() {
  try {
    const info = await api("/api/site-info");
    const phone = document.querySelector("#contact-phone");
    const email = document.querySelector("#contact-email");
    const address = document.querySelector("#contact-address");
    if (info.phone) {
      phone.href = `tel:${info.phone.replace(/[^\d+]/g, "")}`;
      phone.querySelector(".contact-value").textContent = info.phone;
      phone.hidden = false;
    }
    if (info.email) {
      email.href = `mailto:${info.email}`;
      email.querySelector(".contact-value").textContent = info.email;
      email.hidden = false;
    }
    if (info.address) {
      address.querySelector(".contact-value").textContent = info.address;
      address.hidden = false;
      document.querySelector("#footer-address").textContent = info.address;
      document.querySelector("#location-note-value").textContent = info.address;
      document.querySelector("#location-note").hidden = false;
    }
    document.querySelector("#contact-not-configured").hidden = Boolean(info.phone || info.email);
  } catch (error) {
    document.querySelector("#contact-not-configured").textContent =
      "Resort contact details could not be loaded. Please try again later.";
    document.querySelector("#contact-not-configured").hidden = false;
    console.error("Could not load resort contact details.", error);
  }
}

document.querySelectorAll(".filter-button").forEach((button) => {
  button.addEventListener("click", () => {
    const filter = button.dataset.filter;
    document.querySelectorAll(".filter-button").forEach((item) => {
      const selected = item === button;
      item.classList.toggle("active", selected);
      item.setAttribute("aria-pressed", String(selected));
    });
    document.querySelectorAll(".gallery-item").forEach((item) => {
      item.hidden = filter !== "all" && item.dataset.category !== filter;
    });
  });
});

document.querySelector("#contact-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const submit = form.querySelector('button[type="submit"]');
  const feedback = document.querySelector("#contact-feedback");
  const fields = new FormData(form);
  const payload = {
    name: fields.get("name"),
    email: fields.get("email"),
    phone: fields.get("phone"),
    subject: fields.get("subject") || "Website enquiry",
    message: fields.get("message"),
    website: fields.get("website"),
  };
  feedback.textContent = "Sending your enquiry…";
  submit.disabled = true;
  try {
    const result = await api("/api/contact", { method: "POST", body: JSON.stringify(payload) });
    feedback.textContent = result.message;
    form.reset();
  } catch (error) {
    feedback.textContent = error.message;
  } finally {
    submit.disabled = false;
  }
});

document.querySelector("#current-year").textContent = String(new Date().getFullYear());
loadRooms();
loadAmenities();
loadPackages();
loadGallery();
loadSiteInfo();
