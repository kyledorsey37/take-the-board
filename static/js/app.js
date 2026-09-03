window.takeTheBoard = window.takeTheBoard || {};

const ANALYTICS_CONSENT_COOKIE = "ttb_analytics_consent";
const ANALYTICS_CONSENT_MAX_AGE = 60 * 60 * 24 * 365;

function setAnalyticsConsent(value) {
  const secure = window.location.protocol === "https:" ? "; Secure" : "";
  document.cookie = `${ANALYTICS_CONSENT_COOKIE}=${value}; Max-Age=${ANALYTICS_CONSENT_MAX_AGE}; Path=/; SameSite=Lax${secure}`;
}

function clearAnalyticsConsent() {
  const secure = window.location.protocol === "https:" ? "; Secure" : "";
  document.cookie = `${ANALYTICS_CONSENT_COOKIE}=; Max-Age=0; Path=/; SameSite=Lax${secure}`;
}

document.addEventListener("DOMContentLoaded", function initializeMobileNavigation() {
  const toggle = document.querySelector("[data-nav-toggle]");
  const nav = document.querySelector(".site-nav");
  const links = document.getElementById(toggle && toggle.getAttribute("aria-controls"));
  const label = toggle && toggle.querySelector("[data-nav-toggle-label]");

  if (!toggle || !nav || !links || !label) {
    return;
  }

  document.documentElement.classList.add("nav-menu-ready");

  function setMenuOpen(isOpen) {
    nav.classList.toggle("is-open", isOpen);
    toggle.setAttribute("aria-expanded", String(isOpen));
    toggle.setAttribute("aria-label", isOpen ? "Close navigation menu" : "Open navigation menu");
    label.textContent = isOpen ? "Close" : "Menu";
  }

  toggle.addEventListener("click", function toggleMobileNavigation() {
    setMenuOpen(!nav.classList.contains("is-open"));
  });

  links.addEventListener("click", function closeNavigationAfterSelection(event) {
    if (event.target.closest("a, button")) {
      setMenuOpen(false);
    }
  });

  document.addEventListener("keydown", function closeNavigationOnEscape(event) {
    if (event.key === "Escape" && nav.classList.contains("is-open")) {
      setMenuOpen(false);
      toggle.focus();
    }
  });
});

document.addEventListener("click", function handleAnalyticsConsent(event) {
  const choiceButton = event.target.closest("[data-analytics-consent-choice]");
  const settingsButton = event.target.closest("[data-open-cookie-settings]");
  const banner = document.getElementById("analytics-consent-banner");

  if (!banner) {
    return;
  }

  if (choiceButton) {
    setAnalyticsConsent(choiceButton.dataset.analyticsConsentChoice);
    window.location.reload();
    return;
  }

  if (settingsButton) {
    clearAnalyticsConsent();
    banner.hidden = false;
    banner.focus();
  }
});

window.takeTheBoard.trackEvent = function trackEvent(name, params) {
  if (typeof window.gtag !== "function") {
    return;
  }
  window.gtag("event", name, params || {});
};

const ANALYTICS_PARAM_KEYS = [
  "surface",
  "destination",
  "schoolSlug",
  "backingSchoolSlug",
  "rivalrySlug",
  "heroVariant",
  "cta",
  "target",
  "modalId",
  "modalStep",
  "closeMethod",
  "authContext",
  "result",
  "status",
  "amountBucket",
  "shareMethod",
  "category",
  "faqId",
  "period",
  "field",
];

function analyticsParamName(key) {
  return key.replace(/[A-Z]/g, function (letter) {
    return "_" + letter.toLowerCase();
  });
}

function analyticsParams(element) {
  const dataset = element && element.dataset ? element.dataset : {};
  const params = {};

  ANALYTICS_PARAM_KEYS.forEach(function (key) {
    const datasetKey = "analytics" + key.charAt(0).toUpperCase() + key.slice(1);
    if (dataset[datasetKey]) {
      params[analyticsParamName(key)] = dataset[datasetKey];
    }
  });

  return params;
}

function trackElementEvent(element, extraParams) {
  if (!element || !element.dataset.analyticsEvent) {
    return;
  }
  window.takeTheBoard.trackEvent(
    element.dataset.analyticsEvent,
    Object.assign({}, analyticsParams(element), extraParams || {}),
  );
}

function amountBucket(value) {
  const numericAmount = Number(value);
  if (!Number.isFinite(numericAmount)) {
    return "unknown";
  }
  return numericAmount >= 100
    ? "100_plus"
    : numericAmount >= 25
      ? "25_to_99"
      : numericAmount >= 10
        ? "10_to_24"
        : numericAmount >= 5
          ? "5_to_9"
          : "1_to_4";
}

document.addEventListener("DOMContentLoaded", function trackHeroExposure() {
  const hero = document.querySelector("[data-analytics-hero-exposure]");

  if (!hero) {
    return;
  }

  window.takeTheBoard.trackEvent("hero_viewed", analyticsParams(hero));
});

document.addEventListener("DOMContentLoaded", function trackPageAnalytics() {
  document.querySelectorAll("[data-analytics-track~='page']").forEach(function (element) {
    trackElementEvent(element);
  });
});

function formatRoundRemaining(milliseconds) {
  if (milliseconds <= 0) {
    return "Now";
  }

  const totalMinutes = Math.max(1, Math.ceil(milliseconds / 60000));
  const days = Math.floor(totalMinutes / (60 * 24));
  const hours = Math.floor((totalMinutes % (60 * 24)) / 60);
  const minutes = totalMinutes % 60;

  if (days > 0) {
    return `${days}d ${hours}h`;
  }
  if (hours > 0) {
    return `${hours}h ${minutes}m`;
  }
  return `${minutes}m`;
}

window.takeTheBoard.formatRoundRemaining = formatRoundRemaining;

document.addEventListener("DOMContentLoaded", function initializeRoundStatusRails() {
  document.querySelectorAll("[data-round-status]").forEach(function (roundStatus) {
    const resetAt = Date.parse(roundStatus.dataset.roundResetAt || "");
    const serverNow = Date.parse(roundStatus.dataset.roundServerNow || "");
    const value = roundStatus.querySelector("[data-round-status-value]");

    if (!Number.isFinite(resetAt) || !Number.isFinite(serverNow) || !value) {
      return;
    }

    const clientStartedAt = Date.now();

    function updateRoundStatus() {
      const elapsed = Date.now() - clientStartedAt;
      const remaining = resetAt - (serverNow + elapsed);

      if (remaining <= 0) {
        roundStatus.classList.add("round-status-rail-due");
        value.textContent = "Now";
        return;
      }

      value.textContent = formatRoundRemaining(remaining);
    }

    updateRoundStatus();
    window.setInterval(updateRoundStatus, 30000);
  });
});

document.addEventListener("click", function trackAnalyticsClick(event) {
  const target = event.target.closest("[data-analytics-event]");

  if (!target) {
    return;
  }

  // Form submissions are tracked from the submit event below. A click on a
  // submit button also bubbles through the form, so do not count that intent
  // twice.
  if (target.matches("form")) {
    return;
  }

  trackElementEvent(target);
});

document.addEventListener("click", function trackXBoardShare(event) {
  const link = event.target.closest("[data-share-x]");

  if (!link) {
    return;
  }

  window.takeTheBoard.trackEvent("board_share_result", Object.assign({}, analyticsParams(link), {
    result: "shared",
    share_method: "x_twitter",
  }));
});

async function copyTextToClipboard(text) {
  if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
    await navigator.clipboard.writeText(text);
    return true;
  }

  const input = document.createElement("textarea");
  input.value = text;
  input.setAttribute("readonly", "");
  input.style.position = "fixed";
  input.style.opacity = "0";
  document.body.appendChild(input);
  input.select();
  let copied = false;
  try {
    copied = document.execCommand("copy");
  } finally {
    input.remove();
  }
  return copied;
}

document.addEventListener("click", async function handleBoardShare(event) {
  const button = event.target.closest("[data-share-board]");
  if (!button || button.dataset.busy === "true") {
    return;
  }

  const url = button.dataset.shareUrl || window.location.href;
  const title = button.dataset.shareTitle || document.title;
  const text = button.dataset.shareText || title;
  const status = button.parentElement.querySelector("[data-share-status]");
  const label = button.querySelector("[data-share-label]");
  button.dataset.busy = "true";

  try {
    if (typeof navigator.share === "function") {
      await navigator.share({ title: title, text: text, url: url });
      window.takeTheBoard.trackEvent("board_share_result", Object.assign({}, analyticsParams(button), {
        result: "shared",
        share_method: "native",
      }));
      if (status) {
        status.textContent = "Share sheet opened.";
        status.hidden = false;
      }
    } else if (await copyTextToClipboard(url)) {
      window.takeTheBoard.trackEvent("board_share_result", Object.assign({}, analyticsParams(button), {
        result: "copied",
        share_method: "clipboard",
      }));
      if (label) {
        label.textContent = "Copied";
      }
      if (status) {
        status.textContent = "Board link copied.";
        status.hidden = false;
      }
      window.setTimeout(function resetShareLabel() {
        if (label) {
          label.textContent = "Share";
        }
        if (status) {
          status.hidden = true;
        }
      }, 2400);
    } else {
      window.takeTheBoard.trackEvent("board_share_result", Object.assign({}, analyticsParams(button), {
        result: "unavailable",
        share_method: "clipboard",
      }));
      if (status) {
        status.textContent = "Copy the board URL from your browser to share it.";
        status.hidden = false;
      }
    }
  } catch (error) {
    // A dismissed native share sheet is not an error the user needs to see.
    window.takeTheBoard.trackEvent("board_share_result", Object.assign({}, analyticsParams(button), {
      result: error.name === "AbortError" ? "dismissed" : "error",
      share_method: typeof navigator.share === "function" ? "native" : "clipboard",
    }));
    if (error.name !== "AbortError" && status) {
      status.textContent = "We could not open sharing. Try copying the board URL.";
      status.hidden = false;
    }
  } finally {
    button.dataset.busy = "false";
  }
});

document.addEventListener("submit", function trackAnalyticsForm(event) {
  const form = event.target.closest("[data-analytics-event]");

  if (!form) {
    return;
  }

  const amount = form.querySelector("[data-bid-amount]");
  if (amount) {
    form.dataset.analyticsAmountBucket = amountBucket(amount.value);
  }
  const selectedCategory = form.querySelector("input[name='category']:checked");
  if (selectedCategory) {
    form.dataset.analyticsCategory = selectedCategory.value;
  }

  trackElementEvent(form);
});

document.addEventListener("change", function trackAgeAcknowledgement(event) {
  const input = event.target.closest("input[data-age-acknowledgement]");
  if (!input || !input.checked) {
    return;
  }
  const form = input.closest("form");
  window.takeTheBoard.trackEvent("age_acknowledgement_checked", Object.assign({}, analyticsParams(form), {
    surface: form && form.dataset.analyticsSurface ? form.dataset.analyticsSurface : "bid_modal",
  }));
});

function setModalStep(dialog, step) {
  if (dialog) {
    dialog.dataset.analyticsModalStep = step;
  }
}

document.addEventListener("cancel", function trackDialogEscape(event) {
  const dialog = event.target.closest("dialog");
  if (dialog) {
    cancelCheckoutAutoReturn(dialog);
    dialog.dataset.analyticsCloseMethod = "escape";
  }
}, true);

document.addEventListener("click", function trackDialogCloseButton(event) {
  const button = event.target.closest("form[method='dialog'] button");
  const dialog = button && button.closest("dialog");
  if (dialog) {
    cancelCheckoutAutoReturn(dialog);
    dialog.dataset.analyticsCloseMethod = "button";
  }
}, true);

document.addEventListener("close", function trackDialogClose(event) {
  const dialog = event.target.closest("dialog");
  if (!dialog) {
    return;
  }
  window.takeTheBoard.trackEvent("modal_closed", Object.assign({}, analyticsParams(dialog), {
    modal_id: dialog.dataset.analyticsModalId || dialog.id,
    close_method: dialog.dataset.analyticsCloseMethod || "programmatic",
    modal_step: dialog.dataset.analyticsModalStep || "initial",
  }));
  dialog.dataset.analyticsCloseMethod = "";
}, true);

document.addEventListener("click", function handleBidDialogClick(event) {
  const opener = event.target.closest("[data-open-dialog]");
  if (!opener) {
    return;
  }

  const dialog = document.getElementById(opener.dataset.openDialog);
  if (!dialog || typeof dialog.showModal !== "function") {
    return;
  }

  if (dialog.id === "auth-modal") {
    configureAuthDialog(dialog, opener);
  }
  ANALYTICS_PARAM_KEYS.forEach(function (key) {
    const datasetKey = "analytics" + key.charAt(0).toUpperCase() + key.slice(1);
    dialog.dataset[datasetKey] = opener.dataset[datasetKey] || "";
  });
  dialog.dataset.analyticsCloseMethod = "";
  setModalStep(dialog, dialog.id === "auth-modal" ? "email" : "form");
  dialog.showModal();
  const amountInput = dialog.querySelector("[data-bid-amount]");
  if (amountInput) {
    amountInput.focus();
  }
});

document.addEventListener("toggle", function trackFaqOpen(event) {
  const details = event.target.closest("details[data-faq-id]");
  if (!details || !details.open) {
    return;
  }
  window.takeTheBoard.trackEvent("faq_opened", {
    surface: "how_it_works",
    faq_id: details.dataset.faqId,
  });
}, true);

function closeSchoolPicker(picker, returnFocus) {
  const trigger = picker.querySelector("[data-school-picker-trigger]");
  const menu = picker.querySelector("[data-school-picker-menu]");
  trigger.setAttribute("aria-expanded", "false");
  menu.hidden = true;
  if (returnFocus) {
    trigger.focus();
  }
}

function openSchoolPicker(picker) {
  const trigger = picker.querySelector("[data-school-picker-trigger]");
  const menu = picker.querySelector("[data-school-picker-menu]");
  trigger.setAttribute("aria-expanded", "true");
  menu.hidden = false;
  const selected = menu.querySelector('[aria-selected="true"]');
  (selected || menu.querySelector("[data-school-picker-option]")).focus();
}

document.addEventListener("click", function handleSchoolPicker(event) {
  const trigger = event.target.closest("[data-school-picker-trigger]");
  const option = event.target.closest("[data-school-picker-option]");

  if (trigger) {
    const picker = trigger.closest("[data-school-picker]");
    const expanded = trigger.getAttribute("aria-expanded") === "true";
    if (expanded) {
      closeSchoolPicker(picker, false);
    } else {
      openSchoolPicker(picker);
      window.takeTheBoard.trackEvent("school_picker_opened", Object.assign({}, analyticsParams(picker.closest("dialog")), {
        target: "backing_school",
      }));
    }
    return;
  }

  if (option) {
    const picker = option.closest("[data-school-picker]");
    const nativeSelect = picker.querySelector(".school-picker-native");
    const label = picker.querySelector("[data-school-picker-label]");
    nativeSelect.value = option.dataset.schoolValue;
    nativeSelect.dispatchEvent(new Event("change", { bubbles: true }));
    label.textContent = option.dataset.schoolLabel;
    picker.querySelectorAll("[data-school-picker-option]").forEach(function (item) {
      item.setAttribute("aria-selected", item === option ? "true" : "false");
    });
    window.takeTheBoard.trackEvent("school_backing_selected", Object.assign({}, analyticsParams(picker.closest("dialog")), {
      backing_school_slug: option.dataset.schoolSlug || "unknown",
    }));
    closeSchoolPicker(picker, true);
    return;
  }

  document.querySelectorAll("[data-school-picker]").forEach(function (picker) {
    if (!picker.contains(event.target)) {
      closeSchoolPicker(picker, false);
    }
  });
});

document.addEventListener("keydown", function handleSchoolPickerKeyboard(event) {
  const trigger = event.target.closest("[data-school-picker-trigger]");
  const option = event.target.closest("[data-school-picker-option]");

  if (trigger) {
    const picker = trigger.closest("[data-school-picker]");
    if (event.key === "ArrowDown" || event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openSchoolPicker(picker);
    } else if (event.key === "Escape") {
      closeSchoolPicker(picker, false);
    }
    return;
  }

  if (!option) {
    return;
  }

  const picker = option.closest("[data-school-picker]");
  const options = Array.from(picker.querySelectorAll("[data-school-picker-option]"));
  const currentIndex = options.indexOf(option);
  let nextIndex = currentIndex;

  if (event.key === "ArrowDown") {
    nextIndex = Math.min(currentIndex + 1, options.length - 1);
  } else if (event.key === "ArrowUp") {
    nextIndex = Math.max(currentIndex - 1, 0);
  } else if (event.key === "Home") {
    nextIndex = 0;
  } else if (event.key === "End") {
    nextIndex = options.length - 1;
  } else if (event.key === "Escape") {
    event.preventDefault();
    closeSchoolPicker(picker, true);
    return;
  } else if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    option.click();
    return;
  } else {
    return;
  }

  event.preventDefault();
  options[nextIndex].focus();
});

document.addEventListener("click", function setQuickBid(event) {
  const quickBid = event.target.closest("[data-set-bid]");
  if (!quickBid) {
    return;
  }

  const dialog = quickBid.closest("dialog");
  const amountInput = dialog && dialog.querySelector("[data-bid-amount]");
  if (amountInput) {
    amountInput.value = quickBid.dataset.setBid;
    amountInput.dispatchEvent(new Event("input", { bubbles: true }));
    window.takeTheBoard.trackEvent("bid_amount_selected", Object.assign({}, analyticsParams(dialog), {
      amount_bucket: amountBucket(quickBid.dataset.setBid),
      target: "quick_bid",
    }));
  }
});

function isWholeDollarAmount(value) {
  return /^[0-9]+(?:\.0{1,2})?$/.test(value.trim());
}

function updateBidSubmitAmount(amountInput) {
  const amount = Number(amountInput.value);
  const isWholeDollar = isWholeDollarAmount(amountInput.value);
  const form = amountInput.closest("form");
  const submitButton = form && form.querySelector(".bid-submit");
  const amountLabel = form && form.querySelector("[data-bid-submit-amount]");

  if (!Number.isFinite(amount) || amount <= 0 || !isWholeDollar) {
    if (submitButton) {
      submitButton.disabled = true;
    }
    if (amountLabel) {
      amountLabel.textContent = amountInput.value || "0.00";
    }
    return;
  }

  if (submitButton) {
    submitButton.disabled = false;
  }
  if (amountLabel) {
    amountLabel.textContent = amount.toFixed(2);
  }
}

document.addEventListener("input", function updateBidCharacterCount(event) {
  const amountInput = event.target.closest("[data-bid-amount]");
  if (amountInput) {
    amountInput.setCustomValidity("");
    updateBidSubmitAmount(amountInput);
    return;
  }

  const message = event.target.closest("[data-bid-message]");
  if (!message) {
    return;
  }

  const dialog = message.closest("dialog");
  const output = dialog && dialog.querySelector("[data-character-count]");
  if (output) {
    output.value = message.value.length;
  }
});

document.addEventListener("keydown", function restrictBidAmountCharacters(event) {
  const amountInput = event.target.closest("[data-bid-amount]");
  if (!amountInput) {
    return;
  }

  if (["e", "E", "+", "-"].includes(event.key)) {
    event.preventDefault();
  }
});

document.addEventListener("change", function updateBidAmountAfterChange(event) {
  const amountInput = event.target.closest("[data-bid-amount]");
  if (amountInput) {
    amountInput.setCustomValidity("");
    updateBidSubmitAmount(amountInput);
  }
});

document.addEventListener("invalid", function explainBidAmountValidation(event) {
  const amountInput = event.target.closest("[data-bid-amount]");
  if (!amountInput || !amountInput.value.trim() || isWholeDollarAmount(amountInput.value)) {
    return;
  }

  amountInput.setCustomValidity("Enter a whole dollar amount, such as 8 or 8.00.");
}, true);

document.addEventListener("invalid", function trackFormValidationError(event) {
  const field = event.target;
  const form = field && field.closest && field.closest("form");
  if (!form || form.dataset.analyticsValidationTracked === "true") {
    return;
  }
  const surface = form.dataset.analyticsSurface || (form.closest("dialog") && "modal");
  if (!surface) {
    return;
  }
  form.dataset.analyticsValidationTracked = "true";
  window.takeTheBoard.trackEvent("form_validation_error", Object.assign({}, analyticsParams(form), {
    field: field.name || field.id || "unknown",
  }));
}, true);

function wait(milliseconds) {
  return new Promise(function (resolve) {
    window.setTimeout(resolve, milliseconds);
  });
}

const CHECKOUT_POLL_ATTEMPTS = 20;
const CHECKOUT_POLL_DELAY = 750;
const CHECKOUT_AUTO_RETURN_DELAY = 10000;

function createCheckoutElement(tagName, className, text) {
  const element = document.createElement(tagName);
  if (className) {
    element.className = className;
  }
  if (text !== undefined) {
    element.textContent = text;
  }
  return element;
}

function createDialogCloseButton(label) {
  const form = document.createElement("form");
  form.setAttribute("method", "dialog");
  const button = createCheckoutElement("button", "icon-button", "×");
  button.type = "submit";
  button.setAttribute("aria-label", label);
  form.appendChild(button);
  return form;
}

function safeBoardUrl(rawUrl) {
  const fallback = new URL(window.location.pathname, window.location.origin);
  try {
    const candidate = new URL(rawUrl || fallback.pathname, window.location.origin);
    if (candidate.origin !== window.location.origin || !candidate.pathname.startsWith("/schools/")) {
      return fallback;
    }
    return candidate;
  } catch (error) {
    return fallback;
  }
}

function boardUrlWithMove(container, move) {
  const rawUrl = container && (container.dataset.boardUrl || container.__boardUrl);
  const url = safeBoardUrl(rawUrl);
  url.searchParams.set("move", move);
  return url.toString();
}

function rememberBoardUrl(container, payload) {
  const rawUrl = payload && typeof payload.board_url === "string" ? payload.board_url : "";
  if (!rawUrl) {
    return;
  }
  const url = safeBoardUrl(rawUrl);
  container.__boardUrl = url.pathname + url.search + url.hash;
  container.dataset.boardUrl = container.__boardUrl;
}

function clearAutoReturn(containerOrDialog) {
  const container = containerOrDialog && containerOrDialog.matches && containerOrDialog.matches("[data-stripe-checkout]")
    ? containerOrDialog
    : containerOrDialog && containerOrDialog.querySelector && containerOrDialog.querySelector("[data-stripe-checkout]");
  if (!container) {
    return;
  }
  if (container.__autoReturnTimer) {
    window.clearTimeout(container.__autoReturnTimer);
    container.__autoReturnTimer = null;
  }
  container.dataset.autoReturnPending = "false";
}

function cancelCheckoutAutoReturn(dialog) {
  if (dialog) {
    const container = dialog.querySelector("[data-stripe-checkout]");
    if (container) {
      container.__statusPollingCancelled = true;
    }
    clearAutoReturn(dialog);
  }
}

function closeOutcomeDialog(container, closeMethod, modalStep) {
  const dialog = container.closest("dialog");
  if (!dialog) {
    return;
  }
  clearAutoReturn(container);
  dialog.dataset.analyticsCloseMethod = closeMethod;
  setModalStep(dialog, modalStep);
  if (dialog.open && typeof dialog.close === "function") {
    dialog.close();
  }
}

function navigateToBoard(container, move, closeMethod, modalStep) {
  closeOutcomeDialog(container, closeMethod, modalStep);
  window.location.assign(boardUrlWithMove(container, move));
}

function scheduleAutoReturn(container, move, modalStep) {
  clearAutoReturn(container);
  container.dataset.autoReturnPending = "true";
  container.__autoReturnTimer = window.setTimeout(function returnToBoard() {
    navigateToBoard(container, move, "auto_return", modalStep);
  }, CHECKOUT_AUTO_RETURN_DELAY);
}

function renderStatusActions(status, container, move, modalStep) {
  if (!move) {
    return;
  }
  const actions = createCheckoutElement("div", "stripe-checkout-status-actions");
  const viewBoard = createCheckoutElement("button", "button button-primary", "View board");
  viewBoard.type = "button";
  viewBoard.dataset.takeoverViewBoard = "true";
  viewBoard.dataset.takeoverMove = move;
  viewBoard.dataset.takeoverModalStep = modalStep || "processing";
  actions.appendChild(viewBoard);
  status.appendChild(actions);
}

function showCheckoutStatus(container, heading, message, isError, options) {
  const config = options || {};
  clearAutoReturn(container);

  const status = createCheckoutElement(
    "section",
    "stripe-checkout-status" + (isError ? " is-error" : "") + (config.delayed ? " is-delayed" : "") + (config.loading ? " is-loading" : ""),
  );
  status.setAttribute("role", isError ? "alert" : "status");
  status.setAttribute("aria-live", isError ? "assertive" : "polite");

  const header = createCheckoutElement("header", "stripe-checkout-status-header");
  const headingGroup = createCheckoutElement("div", "stripe-checkout-status-heading");
  const marker = createCheckoutElement("span", "stripe-checkout-status-marker", isError ? "!" : "");
  marker.setAttribute("aria-hidden", "true");
  headingGroup.appendChild(marker);
  const headingCopy = createCheckoutElement("div");
  headingCopy.appendChild(createCheckoutElement("p", "eyebrow", config.eyebrow || (isError ? "Try again" : "Confirming your bid")));
  headingCopy.appendChild(createCheckoutElement("h4", "", heading));
  headingGroup.appendChild(headingCopy);
  header.appendChild(headingGroup);
  header.appendChild(createDialogCloseButton("Close takeover confirmation"));
  status.appendChild(header);

  status.appendChild(createCheckoutElement("p", "stripe-checkout-status-copy", message));
  renderStatusActions(status, container, config.move, config.modalStep);
  container.replaceChildren(status);
}

function checkoutAnalyticsParams(container) {
  return Object.assign({}, analyticsParams(container), {
    modal_id: "bid",
    modal_step: "checkout",
  });
}

function trackTakeoverStatus(container, status) {
  window.takeTheBoard.trackEvent("takeover_status", Object.assign({}, checkoutAnalyticsParams(container), {
    status: status,
  }));
}

function showTakeoverSuccess(container, payload) {
  setModalStep(container.closest("dialog"), "success");
  rememberBoardUrl(container, payload);
  const boardName = payload.board_name || "this board";
  const message = payload.message || "";
  const representedEntityName = payload.represented_entity_name || "Your team";
  const amountCents = Number(payload.amount_cents);
  const amount = Number.isFinite(amountCents)
    ? `$${(amountCents / 100).toFixed(2)}`
    : "your bid";
  const boardUrl = safeBoardUrl(container.dataset.boardUrl).toString();

  const success = createCheckoutElement("section", "takeover-success");
  success.setAttribute("role", "status");
  success.setAttribute("aria-live", "polite");
  const header = createCheckoutElement("header", "takeover-success-header");
  const heading = createCheckoutElement("div", "takeover-success-heading");
  const successMarker = createCheckoutElement("span", "takeover-success-check", "✓");
  successMarker.setAttribute("aria-hidden", "true");
  heading.appendChild(successMarker);
  const headingCopy = createCheckoutElement("div");
  headingCopy.appendChild(createCheckoutElement("p", "eyebrow", "Takeover complete"));
  headingCopy.appendChild(createCheckoutElement("h3", "", "The board is yours."));
  heading.appendChild(headingCopy);
  header.appendChild(heading);
  header.appendChild(createDialogCloseButton("Close takeover confirmation"));
  success.appendChild(header);

  success.appendChild(createCheckoutElement("p", "takeover-success-copy", `You now control the ${boardName} board.`));
  const messageCard = createCheckoutElement("article", "takeover-success-message");
  messageCard.setAttribute("aria-label", "Your board message");
  messageCard.appendChild(createCheckoutElement("p", "current-message-label", "Current message"));
  messageCard.appendChild(createCheckoutElement("p", "takeover-success-message-text", message));
  messageCard.appendChild(createCheckoutElement("p", "takeover-success-message-meta", `Backing ${representedEntityName} · ${amount}`));
  success.appendChild(messageCard);

  const actions = createCheckoutElement("div", "takeover-success-actions");
  const viewBoard = createCheckoutElement("button", "button button-primary", "View board");
  viewBoard.type = "button";
  viewBoard.dataset.takeoverViewBoard = "true";
  viewBoard.dataset.takeoverMove = "live";
  viewBoard.dataset.takeoverModalStep = "success";
  actions.appendChild(viewBoard);
  const shareLink = createCheckoutElement("a", "button button-secondary", "Share on Twitter");
  shareLink.dataset.takeoverShare = "true";
  shareLink.target = "_blank";
  shareLink.rel = "noopener noreferrer";
  actions.appendChild(shareLink);
  const stayButton = createCheckoutElement("button", "button button-secondary", "Stay here");
  stayButton.type = "button";
  stayButton.dataset.takeoverStayHere = "true";
  actions.appendChild(stayButton);
  success.appendChild(actions);
  success.appendChild(createCheckoutElement("p", "takeover-success-return-notice", "Returning to the board shortly."));
  success.appendChild(createCheckoutElement("p", "takeover-success-trust", "Payment captured · Your message is live for the guaranteed display window"));

  const shareText = `I just took the ${boardName} board: “${message}”`;
  shareLink.href = `https://twitter.com/intent/tweet?text=${encodeURIComponent(shareText)}&url=${encodeURIComponent(boardUrl)}`;
  container.replaceChildren(success);
  scheduleAutoReturn(container, "live", "success");
}

function showTakeoverQueued(container, payload) {
  rememberBoardUrl(container, payload);
  setModalStep(container.closest("dialog"), "queued");
  const queued = createCheckoutElement("section", "takeover-queued");
  queued.setAttribute("role", "status");
  queued.setAttribute("aria-live", "polite");
  const header = createCheckoutElement("header", "takeover-queued-header");
  const heading = createCheckoutElement("div", "takeover-queued-heading");
  const queuedMarker = createCheckoutElement("span", "takeover-queued-marker");
  queuedMarker.setAttribute("aria-hidden", "true");
  heading.appendChild(queuedMarker);
  const headingCopy = createCheckoutElement("div");
  headingCopy.appendChild(createCheckoutElement("p", "eyebrow", "Bid received"));
  headingCopy.appendChild(createCheckoutElement("h3", "", "You’re up next."));
  heading.appendChild(headingCopy);
  header.appendChild(heading);
  header.appendChild(createDialogCloseButton("Close takeover confirmation"));
  queued.appendChild(header);
  queued.appendChild(createCheckoutElement("p", "takeover-queued-copy", "The current message is still in its guaranteed time. Your bid is queued to take the board unless a higher bid moves ahead first."));
  queued.appendChild(createCheckoutElement("p", "takeover-queued-note", "You’ll only be charged if your takeover wins."));
  const actions = createCheckoutElement("div", "takeover-queued-actions");
  const viewBoard = createCheckoutElement("button", "button button-primary", "View board");
  viewBoard.type = "button";
  viewBoard.dataset.takeoverViewBoard = "true";
  viewBoard.dataset.takeoverMove = "pending";
  viewBoard.dataset.takeoverModalStep = "queued";
  actions.appendChild(viewBoard);
  const stayButton = createCheckoutElement("button", "button button-secondary", "Stay here");
  stayButton.type = "button";
  stayButton.dataset.takeoverStayHere = "true";
  actions.appendChild(stayButton);
  queued.appendChild(actions);
  queued.appendChild(createCheckoutElement("p", "takeover-queued-return-notice", "Returning to the board shortly."));
  container.replaceChildren(queued);
  scheduleAutoReturn(container, "pending", "queued");
}

function showTakeoverDelayed(container) {
  setModalStep(container.closest("dialog"), "processing");
  showCheckoutStatus(
    container,
    "We’re confirming your bid.",
    "This is taking a little longer than usual. Check the board shortly for the latest status.",
    false,
    { delayed: true, eyebrow: "Still confirming", move: "processing", modalStep: "processing" },
  );
}

async function waitForBidStatus(container) {
  const statusUrl = container.dataset.statusUrl;
  const terminalFailures = ["payment_failed", "auth_canceled"];
  for (let attempt = 0; attempt < CHECKOUT_POLL_ATTEMPTS; attempt += 1) {
    if (container.__statusPollingCancelled) {
      return;
    }
    try {
      if (statusUrl) {
        const response = await fetch(statusUrl, {
          credentials: "same-origin",
          headers: { "X-Requested-With": "XMLHttpRequest" },
        });
        if (!response.ok) {
          await wait(CHECKOUT_POLL_DELAY);
          continue;
        }
        const payload = await response.json();
        if (container.__statusPollingCancelled) {
          return;
        }
        const status = payload && payload.status;

        if (status === "authorized") {
          trackTakeoverStatus(container, "authorized");
          showTakeoverQueued(container, payload);
          return;
        }
        if (status === "won") {
          rememberBoardUrl(container, payload);
          trackTakeoverStatus(container, "won");
          window.takeTheBoard.trackEvent("takeover_won", checkoutAnalyticsParams(container));
          showTakeoverSuccess(container, payload);
          return;
        }
        if (terminalFailures.includes(status)) {
          trackTakeoverStatus(container, status);
          showCheckoutStatus(
            container,
            "Payment not completed.",
            "Your card was not charged for this takeover. You can close this window and try again.",
            true,
            { eyebrow: "Payment not completed" },
          );
          return;
        }
      }
    } catch (error) {
      // Keep polling. Webhook processing can briefly race the status request.
    }

    await wait(CHECKOUT_POLL_DELAY);
  }

  if (container.__statusPollingCancelled) {
    return;
  }
  showTakeoverDelayed(container);
  trackTakeoverStatus(container, "processing_timeout");
}

document.addEventListener("click", function handleCheckoutOutcomeActions(event) {
  const viewBoard = event.target.closest("[data-takeover-view-board]");
  if (viewBoard) {
    const container = viewBoard.closest("[data-stripe-checkout]");
    if (container) {
      navigateToBoard(
        container,
        viewBoard.dataset.takeoverMove || "processing",
        "button",
        viewBoard.dataset.takeoverModalStep || "processing",
      );
    }
    return;
  }

  const stayHere = event.target.closest("[data-takeover-stay-here]");
  if (stayHere) {
    const container = stayHere.closest("[data-stripe-checkout]");
    if (!container) {
      return;
    }
    clearAutoReturn(container);
    const notice = container.querySelector("[class*='return-notice']");
    if (notice) {
      notice.textContent = "You’ll stay here.";
    }
    return;
  }

  const share = event.target.closest("[data-takeover-share]");
  if (share) {
    clearAutoReturn(share.closest("[data-stripe-checkout]"));
  }
});

async function mountEmbeddedCheckout(event) {
  const target = event.target;
  if (!target || typeof target.querySelector !== "function") {
    return;
  }

  const container = target.querySelector("[data-stripe-checkout]");
  if (!container || container.dataset.mounted === "true") {
    return;
  }

  const mountPoint = container.querySelector("[data-stripe-checkout-mount]");
  if (!mountPoint) {
    return;
  }
  if (typeof window.Stripe !== "function" || !window.takeTheBoardStripePublishableKey) {
    window.takeTheBoard.trackEvent("checkout_error", Object.assign({}, checkoutAnalyticsParams(container), {
      result: "unavailable",
    }));
    mountPoint.textContent = "Secure checkout is unavailable right now. Please try again.";
    return;
  }

  const dialog = container.closest("dialog");
  const bidForm = dialog && dialog.querySelector("[data-bid-form]");
  if (bidForm) {
    bidForm.hidden = true;
  }

  try {
    const stripe = window.Stripe(window.takeTheBoardStripePublishableKey);
    let checkout;
    const handleComplete = async function handleComplete() {
      checkout.destroy();
      window.takeTheBoard.trackEvent("checkout_completed", checkoutAnalyticsParams(container));
      showCheckoutStatus(
        container,
        "Confirming your bid.",
        "We’re confirming your payment and placing your bid.",
        false,
        { loading: true },
      );
      await waitForBidStatus(container);
    };

    checkout = await stripe.initEmbeddedCheckout({
      fetchClientSecret: async function fetchClientSecret() {
        return container.dataset.clientSecret;
      },
      onComplete: handleComplete,
    });
    checkout.mount(mountPoint);
    container.dataset.mounted = "true";
    setModalStep(container.closest("dialog"), "checkout");
    window.takeTheBoard.trackEvent("checkout_loaded", checkoutAnalyticsParams(container));
  } catch (error) {
    window.takeTheBoard.trackEvent("checkout_error", Object.assign({}, checkoutAnalyticsParams(container), {
      result: "load_failed",
    }));
    mountPoint.textContent = "Secure checkout could not load. Please close this window and try again.";
  }
}

document.addEventListener("htmx:afterSwap", mountEmbeddedCheckout);

document.addEventListener("htmx:afterSwap", function trackAnalyticsSwap(event) {
  const target = event.target;
  if (!target || typeof target.querySelectorAll !== "function") {
    return;
  }
  const elements = [];
  if (target.matches && target.matches("[data-analytics-track~='swap']")) {
    elements.push(target);
  }
  target.querySelectorAll("[data-analytics-track~='swap']").forEach(function (element) {
    elements.push(element);
  });
  elements.forEach(function (element) {
    if (element.dataset.analyticsTracked === "true") {
      return;
    }
    element.dataset.analyticsTracked = "true";
    trackElementEvent(element);
    setModalStep(element.closest("dialog"), element.dataset.analyticsModalStep || element.dataset.analyticsResult || "result");
  });
});

document.addEventListener("click", function returnToBidForm(event) {
  const button = event.target.closest("[data-bid-confirmation-back]");
  if (!button) {
    return;
  }
  const preview = button.closest("#takeover-result");
  if (!preview) {
    return;
  }
  preview.replaceChildren();
  const dialog = preview.closest("dialog");
  const bidForm = dialog && dialog.querySelector("[data-bid-form]");
  if (bidForm) {
    bidForm.hidden = false;
    setModalStep(dialog, "form");
    bidForm.querySelector("input[name='amount']")?.focus();
  }
});

// HTMX normally refuses to swap 4xx/5xx responses. Bid throttling and
// temporary moderation outages deliberately use those statuses, but their
// server-rendered fragments are still the user-facing result for this form.
// Allow only those expected responses for this target; leave unrelated errors
// on the default HTMX error path.
document.addEventListener("htmx:beforeSwap", function swapExpectedBidErrors(event) {
  const detail = event.detail;
  const target = detail && detail.target;
  const xhr = detail && detail.xhr;
  if (!target || target.id !== "takeover-result" || !xhr) {
    return;
  }
  if (xhr.status === 429 || xhr.status === 503) {
    detail.shouldSwap = true;
    detail.isError = false;
  }
});

document.addEventListener("htmx:afterSwap", function disableSubmittedReport(event) {
  const target = event.target;
  if (!target || typeof target.querySelector !== "function") {
    return;
  }
  const result = target.querySelector("[data-report-accepted]");
  if (!result) {
    return;
  }
  const form = target.closest("dialog") && target.closest("dialog").querySelector("form[action*='/report/']");
  if (form) {
    form.querySelectorAll("input, button[type='submit']").forEach(function (field) {
      field.disabled = true;
    });
  }
});

function csrfToken(form) {
  const token = form.querySelector("[name=csrfmiddlewaretoken]");
  return token ? token.value : "";
}

async function submitAuthForm(form) {
  const response = await fetch(form.action, {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "X-CSRFToken": csrfToken(form),
      "X-Requested-With": "XMLHttpRequest"
    },
    body: new FormData(form)
  });
  const payload = await response.json();
  return { ok: response.ok && payload.ok, payload: payload };
}

function setAuthStatus(dialog, message, isError) {
  const status = dialog.querySelector("[data-auth-status]");
  if (!status) {
    return;
  }
  status.textContent = message;
  status.classList.toggle("is-error", Boolean(isError));
}

function showAuthCodeStep(dialog, email, message) {
  const startForm = dialog.querySelector("[data-auth-start-form]");
  const verifyForm = dialog.querySelector("[data-auth-verify-form]");
  const nameForm = dialog.querySelector("[data-auth-name-form]");
  const emailLabel = dialog.querySelector("[data-auth-email]");
  const title = dialog.querySelector("[data-auth-title]");

  startForm.hidden = true;
  if (nameForm) {
    nameForm.hidden = true;
  }
  verifyForm.hidden = false;
  emailLabel.textContent = email;
  title.textContent = "Enter your code.";
  verifyForm.querySelector("[name=code]").focus();
  setModalStep(dialog, "code");
  setAuthStatus(dialog, message, false);
}

function showAuthEmailStep(dialog) {
  const startForm = dialog.querySelector("[data-auth-start-form]");
  const verifyForm = dialog.querySelector("[data-auth-verify-form]");
  const nameForm = dialog.querySelector("[data-auth-name-form]");
  const title = dialog.querySelector("[data-auth-title]");
  const emailInput = startForm.querySelector("[name=email]");

  verifyForm.hidden = true;
  verifyForm.reset();
  if (nameForm) {
    nameForm.hidden = true;
  }
  startForm.hidden = false;
  title.textContent = dialog.dataset.authFlowTitle || dialog.dataset.authDefaultTitle;
  const intro = dialog.querySelector("[data-auth-email-step]");
  if (intro) {
    intro.textContent = dialog.dataset.authFlowIntro || intro.dataset.authDefaultIntro;
  }
  setAuthStatus(dialog, "", false);
  emailInput.focus();
  emailInput.select();
  setModalStep(dialog, "email");
}

function configureAuthDialog(dialog, opener) {
  const title = dialog.querySelector("[data-auth-title]");
  const intro = dialog.querySelector("[data-auth-email-step]");
  dialog.dataset.authFlowTitle = opener.dataset.authTitle || dialog.dataset.authDefaultTitle;
  dialog.dataset.authFlowIntro = opener.dataset.authIntro || dialog.dataset.authDefaultIntro;
  if (title) {
    title.textContent = dialog.dataset.authFlowTitle;
  }
  if (intro) {
    intro.textContent = dialog.dataset.authFlowIntro;
  }
}

function showAuthNameStep(dialog) {
  const startForm = dialog.querySelector("[data-auth-start-form]");
  const verifyForm = dialog.querySelector("[data-auth-verify-form]");
  const nameForm = dialog.querySelector("[data-auth-name-form]");
  const title = dialog.querySelector("[data-auth-title]");

  startForm.hidden = true;
  verifyForm.hidden = true;
  nameForm.hidden = false;
  title.textContent = "Choose your board name.";
  setAuthStatus(dialog, "", false);
  nameForm.querySelector("[name=display_name]").focus();
  setModalStep(dialog, "name");
}

function authAnalyticsParams(dialog, result) {
  return Object.assign({}, analyticsParams(dialog), {
    result: result,
  });
}

document.addEventListener("submit", async function handleAuthStart(event) {
  const form = event.target.closest("[data-auth-start-form]");
  if (!form) {
    return;
  }
  event.preventDefault();
  const dialog = form.closest("dialog");

  if (dialog.dataset.authPreview === "true") {
    window.takeTheBoard.trackEvent("auth_code_requested", authAnalyticsParams(dialog, "preview"));
    showAuthCodeStep(dialog, form.elements.email.value, "Preview only: no email was sent.");
    return;
  }

  try {
    const result = await submitAuthForm(form);
    if (!result.ok) {
      window.takeTheBoard.trackEvent("auth_code_requested", authAnalyticsParams(dialog, "error"));
      setAuthStatus(dialog, result.payload.error || "We could not send a code.", true);
      return;
    }
    window.takeTheBoard.trackEvent("auth_code_requested", authAnalyticsParams(dialog, "success"));
    showAuthCodeStep(dialog, form.elements.email.value, result.payload.message);
  } catch (error) {
    window.takeTheBoard.trackEvent("auth_code_requested", authAnalyticsParams(dialog, "error"));
    setAuthStatus(dialog, "We could not send a code. Please try again.", true);
  }
});

document.addEventListener("submit", async function handleAuthVerify(event) {
  const form = event.target.closest("[data-auth-verify-form]");
  if (!form) {
    return;
  }
  event.preventDefault();
  const dialog = form.closest("dialog");

  if (dialog.dataset.authPreview === "true") {
    window.takeTheBoard.trackEvent("auth_code_verified", authAnalyticsParams(dialog, "preview"));
    setAuthStatus(dialog, "Preview complete. Cognito will verify this code once it is connected.", false);
    return;
  }

  try {
    const result = await submitAuthForm(form);
    if (!result.ok) {
      window.takeTheBoard.trackEvent("auth_code_verified", authAnalyticsParams(dialog, "error"));
      setAuthStatus(dialog, result.payload.error || "That code could not be verified.", true);
      return;
    }
    window.takeTheBoard.trackEvent("auth_code_verified", authAnalyticsParams(dialog, result.payload.signed_in ? "success" : "retry"));
    if (result.payload.signed_in) {
      if (result.payload.needs_display_name) {
        showAuthNameStep(dialog);
        return;
      }
      window.location.reload();
      return;
    }
    form.reset();
    form.querySelector("[name=code]").focus();
    setAuthStatus(dialog, result.payload.message, false);
  } catch (error) {
    window.takeTheBoard.trackEvent("auth_code_verified", authAnalyticsParams(dialog, "error"));
    setAuthStatus(dialog, "That code could not be verified. Please try again.", true);
  }
});

document.addEventListener("click", async function handleAuthResend(event) {
  const button = event.target.closest("[data-auth-resend]");
  if (!button) {
    return;
  }
  const dialog = button.closest("dialog");
  const form = dialog && dialog.querySelector("[data-auth-verify-form]");
  if (!form) {
    return;
  }

  if (dialog.dataset.authPreview === "true") {
    window.takeTheBoard.trackEvent("auth_code_resent", authAnalyticsParams(dialog, "preview"));
    setAuthStatus(dialog, "Preview only: no new email was sent.", false);
    return;
  }

  try {
    const response = await fetch("/api/auth/email/resend/", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "X-CSRFToken": csrfToken(form),
        "X-Requested-With": "XMLHttpRequest"
      }
    });
    const payload = await response.json();
    window.takeTheBoard.trackEvent("auth_code_resent", authAnalyticsParams(dialog, response.ok && payload.ok ? "success" : "error"));
    setAuthStatus(dialog, payload.message || payload.error, !response.ok || !payload.ok);
  } catch (error) {
    window.takeTheBoard.trackEvent("auth_code_resent", authAnalyticsParams(dialog, "error"));
    setAuthStatus(dialog, "We could not resend the code. Please try again.", true);
  }
});

document.addEventListener("click", function handleAuthChangeEmail(event) {
  const button = event.target.closest("[data-auth-change-email]");
  if (!button) {
    return;
  }
  const dialog = button.closest("dialog");
  if (dialog) {
    window.takeTheBoard.trackEvent("auth_email_changed", analyticsParams(dialog));
    showAuthEmailStep(dialog);
  }
});

document.addEventListener("submit", async function handleAuthName(event) {
  const form = event.target.closest("[data-auth-name-form]");
  if (!form) {
    return;
  }
  event.preventDefault();
  const dialog = form.closest("dialog");

  try {
    const result = await submitAuthForm(form);
    if (!result.ok) {
      window.takeTheBoard.trackEvent("display_name_submitted", authAnalyticsParams(dialog, "error"));
      setAuthStatus(dialog, result.payload.error || "We could not save that board name.", true);
      return;
    }
    window.takeTheBoard.trackEvent("display_name_submitted", authAnalyticsParams(dialog, "success"));
    window.location.reload();
  } catch (error) {
    window.takeTheBoard.trackEvent("display_name_submitted", authAnalyticsParams(dialog, "error"));
    setAuthStatus(dialog, "We could not save that board name. Please try again.", true);
  }
});
