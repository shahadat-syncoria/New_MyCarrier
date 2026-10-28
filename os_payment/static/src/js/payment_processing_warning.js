/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { rpc } from "@web/core/network/rpc";
import paymentForm from "@payment/js/payment_form";

const WARNING_ID = "o_payment_processing_warning";
const PAYMENT_MODAL_SELECTOR = [
    "#globalpay_hosted_fields_modal",
    "#clovercheckout_payment_form_modal",
    "#monerisModal",
    "#bamboraModal",
].join(",");
const PAYMENT_MODAL_CLOSE_SELECTOR = [
    '[data-bs-dismiss="modal"]',
    '[data-dismiss="modal"]',
    "#monerisBtnCncl",
    "#bamboraCancel",
].join(",");
const PROVIDER_PAY_BUTTON_SELECTOR = [
    '[id^="clover-submit-"]',
    "#pay-button",
].join(",");
const BEFORE_UNLOAD_MESSAGE = "";
const BEFORE_UNLOAD_BOUND_FLAG = "__oPaymentProcessingBeforeUnloadBound";
const PAYMENT_RPC_PATCHED_FLAG = "__oPaymentProcessingRpcPatched";
const STRIPE_PATCHED_FLAG = "__oPaymentProcessingStripePatched";
const STRIPE_FACTORY_WATCHED_FLAG = "__oPaymentProcessingStripeFactoryWatched";
const PAYMENT_STATUS_RPC_ROUTES = new Set([
    "/payment/authorize/payment",
    "/payment/bamborachk/payment",
    "/payment/clovercheckout/payment",
    "/payment/demo/simulate_payment",
    "/payment/globalpay/payment",
    "/payment/mercado_pago/payments",
    "/payment/monerischeckout/payment",
    "/payment/paypal/complete_order",
    "/payment/xendit/payment",
]);
const STRIPE_CONFIRM_METHODS = ["confirmPayment", "confirmSetup", "confirmCardPayment"];
const PAYMENT_BEFORE_UNLOAD_HANDLER = (event) => {
    event.preventDefault();
    event.returnValue = BEFORE_UNLOAD_MESSAGE;
    return BEFORE_UNLOAD_MESSAGE;
};

function hidePaymentProcessingWarning() {
    document.getElementById(WARNING_ID)?.classList.add("d-none");
    if (window[BEFORE_UNLOAD_BOUND_FLAG]) {
        window.removeEventListener("beforeunload", PAYMENT_BEFORE_UNLOAD_HANDLER);
        window[BEFORE_UNLOAD_BOUND_FLAG] = false;
    }
}

function preparePaymentStatusNavigation() {
    hidePaymentProcessingWarning();
}

// Register this callback before payment providers register their own redirect
// callbacks on the same promise. This removes beforeunload before /payment/status.
if (!rpc[PAYMENT_RPC_PATCHED_FLAG]) {
    const originalRpc = rpc._rpc;
    rpc._rpc = function (url, ...args) {
        const request = originalRpc.call(this, url, ...args);
        if (PAYMENT_STATUS_RPC_ROUTES.has(url)) {
            request.then(preparePaymentStatusNavigation, () => {});
        }
        return request;
    };
    rpc[PAYMENT_RPC_PATCHED_FLAG] = true;
}

function patchStripeInstance(stripeJS) {
    if (!stripeJS || stripeJS[STRIPE_PATCHED_FLAG]) {
        return stripeJS;
    }
    for (const methodName of STRIPE_CONFIRM_METHODS) {
        if (typeof stripeJS[methodName] !== "function") {
            continue;
        }
        const originalMethod = stripeJS[methodName];
        stripeJS[methodName] = function (...args) {
            preparePaymentStatusNavigation();
            return originalMethod.apply(this, args);
        };
    }
    stripeJS[STRIPE_PATCHED_FLAG] = true;
    return stripeJS;
}

function setStripeFactory(stripeFactory) {
    try {
        Object.defineProperty(window, "Stripe", {
            configurable: true,
            writable: true,
            value: stripeFactory,
        });
    } catch {
        window.Stripe = stripeFactory;
    }
}

function patchStripeFactory() {
    if (typeof window.Stripe !== "function") {
        if (!window[STRIPE_FACTORY_WATCHED_FLAG]) {
            let stripeFactory;
            try {
                Object.defineProperty(window, "Stripe", {
                    configurable: true,
                    get() {
                        return stripeFactory;
                    },
                    set(value) {
                        stripeFactory = value;
                        patchStripeFactory();
                    },
                });
            } catch {
                // If the browser prevents watching the global, provider method hooks below still help.
            }
            window[STRIPE_FACTORY_WATCHED_FLAG] = true;
        }
        return;
    }
    if (window.Stripe[STRIPE_PATCHED_FLAG]) {
        return;
    }
    const originalStripe = window.Stripe;
    const patchedStripe = function (...args) {
        return patchStripeInstance(originalStripe.apply(this, args));
    };
    Object.assign(patchedStripe, originalStripe);
    patchedStripe[STRIPE_PATCHED_FLAG] = true;
    setStripeFactory(patchedStripe);
}
patchStripeFactory();

paymentForm.include({
    async _submitForm() {
        this._showPaymentProcessingWarning();
        try {
            return await this._super(...arguments);
        } catch (error) {
            this._hidePaymentProcessingWarning();
            throw error;
        }
    },

    _enableButton() {
        const result = this._super(...arguments);

        // Providers use this while opening their secure card modal. Bind the modal
        // lifecycle after its synchronous setup, but keep the warning visible.
        window.setTimeout(() => this._bindPaymentProcessingModalEvents());
        return result;
    },

    _displayErrorDialog() {
        this._hidePaymentProcessingWarning();
        return this._super(...arguments);
    },

    _processRedirectFlow() {
        this._hidePaymentProcessingWarning();
        return this._super(...arguments);
    },

    _processTokenFlow() {
        this._hidePaymentProcessingWarning();
        return this._super(...arguments);
    },

    _stripeConfirmIntent() {
        preparePaymentStatusNavigation();
        return this._super(...arguments);
    },

    _adyenOnPaymentResolved() {
        preparePaymentStatusNavigation();
        return this._super(...arguments);
    },

    _prepareRazorpayOptions() {
        const options = this._super(...arguments);
        const originalHandler = options.handler;
        options.handler = (...args) => {
            preparePaymentStatusNavigation();
            return originalHandler?.apply(this, args);
        };
        if (options.modal?.ondismiss) {
            const originalOnDismiss = options.modal.ondismiss;
            options.modal.ondismiss = (...args) => {
                this._hidePaymentProcessingWarning();
                return originalOnDismiss.apply(this, args);
            };
        }
        return options;
    },

    _globalPaySetAlert(modalElement, alertId, message, level = "info") {
        const result = this._super(...arguments);
        if (level === "danger") {
            this._hidePaymentProcessingWarning();
        } else if (level === "info" && message) {
            this._showPaymentProcessingWarning();
        }
        return result;
    },

    _cloverCheckoutDisplayAlert(modalElement, type, message) {
        const result = this._super(...arguments);
        if (type === "danger") {
            this._hidePaymentProcessingWarning();
        }
        return result;
    },

    showErrorFeedback() {
        this._hidePaymentProcessingWarning();
        return this._super(...arguments);
    },

    _showPaymentProcessingWarning() {
        let warning = document.getElementById(WARNING_ID);
        if (!warning) {
            warning = document.createElement("div");
            warning.id = WARNING_ID;
            warning.className = "o_payment_processing_warning alert alert-warning shadow";
            warning.setAttribute("role", "alert");
            warning.setAttribute("aria-live", "assertive");

            const icon = document.createElement("i");
            icon.className = "fa fa-exclamation-triangle me-2";
            icon.setAttribute("aria-hidden", "true");
            warning.appendChild(icon);

            const message = document.createElement("strong");
            message.textContent = _t(
                "Don't close the window before completing the transaction."
            );
            warning.appendChild(message);
            document.body.appendChild(warning);
        }
        warning.classList.remove("d-none");
        this._bindPaymentProcessingBeforeUnloadEvent();
        window.setTimeout(() => this._bindPaymentProcessingModalEvents());
    },

    _hidePaymentProcessingWarning() {
        hidePaymentProcessingWarning();
    },

    _bindPaymentProcessingBeforeUnloadEvent() {
        if (!window[BEFORE_UNLOAD_BOUND_FLAG]) {
            window.addEventListener("beforeunload", PAYMENT_BEFORE_UNLOAD_HANDLER);
            window[BEFORE_UNLOAD_BOUND_FLAG] = true;
        }
    },

    _unbindPaymentProcessingBeforeUnloadEvent() {
        hidePaymentProcessingWarning();
    },

    _bindPaymentProcessingModalEvents() {
        for (const modal of document.querySelectorAll(PAYMENT_MODAL_SELECTOR)) {
            if (modal.dataset.paymentWarningEventsBound) {
                continue;
            }
            modal.dataset.paymentWarningEventsBound = "true";
            modal.addEventListener(
                "hidden.bs.modal",
                () => this._hidePaymentProcessingWarning()
            );
            for (const closeButton of modal.querySelectorAll(PAYMENT_MODAL_CLOSE_SELECTOR)) {
                closeButton.addEventListener(
                    "click",
                    () => this._hidePaymentProcessingWarning()
                );
            }
            for (const payButton of modal.querySelectorAll(PROVIDER_PAY_BUTTON_SELECTOR)) {
                payButton.addEventListener(
                    "click",
                    () => this._showPaymentProcessingWarning()
                );
            }
        }
    },
});
