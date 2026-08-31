window.takeTheBoard = window.takeTheBoard || {};

window.takeTheBoard.trackEvent = function trackEvent(name, params) {
  if (typeof window.gtag !== "function") {
    return;
  }
  window.gtag("event", name, params || {});
};

document.addEventListener("DOMContentLoaded", function trackHeroExposure() {
  const hero = document.querySelector("[data-analytics-hero-exposure]");

  if (!hero) {
    return;
  }

  window.takeTheBoard.trackEvent("hero_viewed", analyticsParams(hero));
});

document.addEventListener("click", function trackAnalyticsClick(event) {
  const target = event.target.closest("[data-analytics-event]");

  if (!target) {
    return;
  }

  const dataset = target.dataset;
  const params = {};

  ["surface", "destination", "schoolSlug", "rivalrySlug", "heroVariant", "cta", "target"].forEach(function (key) {
    if (dataset["analytics" + key.charAt(0).toUpperCase() + key.slice(1)]) {
      params[key.replace(/[A-Z]/g, function (letter) {
        return "_" + letter.toLowerCase();
      })] = dataset["analytics" + key.charAt(0).toUpperCase() + key.slice(1)];
    }
  });

  window.takeTheBoard.trackEvent(dataset.analyticsEvent, params);
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
      if (status) {
        status.textContent = "Share sheet opened.";
        status.hidden = false;
      }
    } else if (await copyTextToClipboard(url)) {
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
    } else if (status) {
      status.textContent = "Copy the board URL from your browser to share it.";
      status.hidden = false;
    }
  } catch (error) {
    // A dismissed native share sheet is not an error the user needs to see.
    if (error.name !== "AbortError" && status) {
      status.textContent = "We could not open sharing. Try copying the board URL.";
      status.hidden = false;
    }
  } finally {
    button.dataset.busy = "false";
  }
});

function analyticsParams(element) {
  const dataset = element.dataset;
  const params = {};

  ["surface", "destination", "schoolSlug", "rivalrySlug", "amountBucket", "heroVariant", "cta", "target"].forEach(function (key) {
    const datasetKey = "analytics" + key.charAt(0).toUpperCase() + key.slice(1);
    if (dataset[datasetKey]) {
      params[key.replace(/[A-Z]/g, function (letter) {
        return "_" + letter.toLowerCase();
      })] = dataset[datasetKey];
    }
  });

  return params;
}

document.addEventListener("submit", function trackAnalyticsForm(event) {
  const form = event.target.closest("[data-analytics-event]");

  if (!form) {
    return;
  }

  const amount = form.querySelector("[data-bid-amount]");
  if (amount) {
    const numericAmount = Number(amount.value);
    form.dataset.analyticsAmountBucket = numericAmount >= 25 ? "25_plus" : numericAmount >= 10 ? "10_to_24" : numericAmount >= 5 ? "5_to_9" : "1_to_4";
  }

  window.takeTheBoard.trackEvent(form.dataset.analyticsEvent, analyticsParams(form));
});

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
  dialog.showModal();
  const amountInput = dialog.querySelector("[data-bid-amount]");
  if (amountInput) {
    amountInput.focus();
  }
});

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

function wait(milliseconds) {
  return new Promise(function (resolve) {
    window.setTimeout(resolve, milliseconds);
  });
}

function showCheckoutStatus(container, heading, message, isError) {
  const mountPoint = container.querySelector("[data-stripe-checkout-mount]");
  if (!mountPoint) {
    return;
  }

  mountPoint.innerHTML = "";
  const status = document.createElement("div");
  status.className = "stripe-checkout-status" + (isError ? " is-error" : "");
  status.setAttribute("role", isError ? "alert" : "status");

  const marker = document.createElement("span");
  marker.className = "stripe-checkout-status-marker";
  marker.setAttribute("aria-hidden", "true");
  marker.textContent = isError ? "!" : "";
  status.appendChild(marker);

  const eyebrow = document.createElement("p");
  eyebrow.className = "eyebrow";
  eyebrow.textContent = isError ? "Try again" : "Take the board";
  status.appendChild(eyebrow);

  const title = document.createElement("h4");
  title.textContent = heading;
  status.appendChild(title);

  const copy = document.createElement("p");
  copy.textContent = message;
  status.appendChild(copy);
  mountPoint.appendChild(status);
}

function showTakeoverSuccess(container, payload) {
  const boardName = payload.board_name || "this board";
  const message = payload.message || "";
  const representedEntityName = payload.represented_entity_name || "Your team";
  const amountCents = Number(payload.amount_cents);
  const amount = Number.isFinite(amountCents)
    ? `$${(amountCents / 100).toFixed(2)}`
    : "your bid";
  const boardUrl = new URL(payload.board_url || window.location.pathname, window.location.origin).toString();

  container.innerHTML = `
    <section class="takeover-success" role="status" aria-labelledby="takeover-success-title">
      <header class="takeover-success-header">
        <div class="takeover-success-heading">
          <span class="takeover-success-check" aria-hidden="true">✓</span>
          <div>
            <p class="eyebrow">Payment successful</p>
            <h3 id="takeover-success-title">The board is yours.</h3>
          </div>
        </div>
        <form method="dialog">
          <button class="icon-button" type="submit" aria-label="Close takeover confirmation">&times;</button>
        </form>
      </header>
      <p class="takeover-success-copy"></p>
      <article class="takeover-success-message" aria-label="Your board message">
        <p class="current-message-label"><span aria-hidden="true"></span>Your message</p>
        <p class="takeover-success-message-text"></p>
        <p class="takeover-success-message-meta"></p>
      </article>
      <div class="takeover-success-actions">
        <a class="button button-primary" data-takeover-share target="_blank" rel="noopener noreferrer">Share on Twitter</a>
        <form method="dialog"><button class="button button-secondary" type="submit">Done</button></form>
      </div>
      <p class="takeover-success-trust">Payment confirmed <span aria-hidden="true">·</span> Your message is live for the guaranteed display window</p>
    </section>
  `;

  container.querySelector(".takeover-success-copy").textContent = `You now control the ${boardName} board.`;
  container.querySelector(".takeover-success-message-text").textContent = message;
  container.querySelector(".takeover-success-message-meta").textContent = `Backing ${representedEntityName} · ${amount}`;

  const shareLink = container.querySelector("[data-takeover-share]");
  const shareText = `I just took the ${boardName} board: “${message}”`;
  shareLink.href = `https://twitter.com/intent/tweet?text=${encodeURIComponent(shareText)}&url=${encodeURIComponent(boardUrl)}`;
}

async function waitForBidStatus(container) {
  const statusUrl = container.dataset.statusUrl;
  if (!statusUrl) {
    showCheckoutStatus(
      container,
      "Payment successful.",
      "Your payment was accepted. Your takeover is still processing; you can close this window and check the board shortly.",
      false,
    );
    return;
  }

  const terminalFailures = ["payment_failed", "auth_canceled"];
  let latestStatus = "checkout_created";
  for (let attempt = 0; attempt < 20; attempt += 1) {
    try {
      const response = await fetch(statusUrl, {
        credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      if (response.ok) {
        const payload = await response.json();
        latestStatus = payload.status || latestStatus;

        if (latestStatus === "won") {
          showTakeoverSuccess(container, payload);
          return;
        }
        if (terminalFailures.includes(latestStatus)) {
          showCheckoutStatus(
            container,
            "Payment not completed.",
            "Your card was not charged for this takeover. You can close this window and try again.",
            true,
          );
          return;
        }
      }
    } catch (error) {
      // Keep polling. Webhook processing can briefly race the status request.
    }

    await wait(750);
  }

  showCheckoutStatus(
    container,
    "Payment successful.",
    latestStatus === "authorized"
      ? "Your payment was accepted. Your takeover is still processing; you can close this window and check the board shortly."
      : "Your payment was accepted and your takeover is still processing.",
    false,
  );
}

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
  if (!mountPoint || typeof window.Stripe !== "function" || !window.takeTheBoardStripePublishableKey) {
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
      showCheckoutStatus(
        container,
        "Payment received.",
        "We are updating the board now. This should only take a moment.",
        false,
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
  } catch (error) {
    mountPoint.textContent = "Secure checkout could not load. Please close this window and try again.";
  }
}

document.addEventListener("htmx:afterSwap", mountEmbeddedCheckout);

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
}

document.addEventListener("submit", async function handleAuthStart(event) {
  const form = event.target.closest("[data-auth-start-form]");
  if (!form) {
    return;
  }
  event.preventDefault();
  const dialog = form.closest("dialog");

  if (dialog.dataset.authPreview === "true") {
    showAuthCodeStep(dialog, form.elements.email.value, "Preview only: no email was sent.");
    return;
  }

  try {
    const result = await submitAuthForm(form);
    if (!result.ok) {
      setAuthStatus(dialog, result.payload.error || "We could not send a code.", true);
      return;
    }
    showAuthCodeStep(dialog, form.elements.email.value, result.payload.message);
  } catch (error) {
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
    setAuthStatus(dialog, "Preview complete. Cognito will verify this code once it is connected.", false);
    return;
  }

  try {
    const result = await submitAuthForm(form);
    if (!result.ok) {
      setAuthStatus(dialog, result.payload.error || "That code could not be verified.", true);
      return;
    }
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
    setAuthStatus(dialog, payload.message || payload.error, !response.ok || !payload.ok);
  } catch (error) {
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
      setAuthStatus(dialog, result.payload.error || "We could not save that board name.", true);
      return;
    }
    window.location.reload();
  } catch (error) {
    setAuthStatus(dialog, "We could not save that board name. Please try again.", true);
  }
});
