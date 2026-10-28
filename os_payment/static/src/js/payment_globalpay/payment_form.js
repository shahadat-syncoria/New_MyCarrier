/** @odoo-module **/

import { loadJS } from "@web/core/assets";
import { _t } from "@web/core/l10n/translation";
import { rpc, RPCError } from "@web/core/network/rpc";
import paymentForm from "@payment/js/payment_form";


const GLOBALPAY_MODAL_ID = "globalpay_hosted_fields_modal";
const GLOBALPAY_SDK_URL = "https://js.globalpay.com/4.1.11/globalpayments.js";


// Odoo 18 exposes the legacy public payment widget, which is extended with
// `include`; `@payment/interactions/payment_form` only exists in Odoo 19.
paymentForm.include({
    async _prepareInlineForm(
        providerId, providerCode, paymentOptionId, paymentMethodCode, flow
    ) {
        if (providerCode !== "globalpay") {
            return this._super(...arguments);
        }
        if (flow === "token") {
            return;
        }

        this._setPaymentFlow("direct");
        try {
            await this._loadGlobalPaySdk();
        } catch (error) {
            this._displayErrorDialog(
                _t("Payment Error"),
                _t("The Global Payments secure card form could not be loaded.")
            );
            this._enableButton();
            throw error;
        }
    },

    async _processDirectFlow(
        providerCode, paymentOptionId, paymentMethodCode, processingValues
    ) {
        if (providerCode !== "globalpay") {
            return this._super(...arguments);
        }
        await this._openGlobalPayHostedFields(paymentOptionId, processingValues);
    },

    async _initiatePaymentFlow(
        providerCode, paymentOptionId, paymentMethodCode, flow
    ) {
        if (providerCode !== "globalpay" || flow === "token") {
            return this._super(...arguments);
        }
        // Tokenize first. The Odoo transaction is created only after Hosted Fields
        // returns a PMT, so opening/closing the modal does not create draft duplicates.
        await this._openGlobalPayHostedFields(paymentOptionId, null);
    },

    async _processRedirectFlow(
        providerCode, paymentOptionId, paymentMethodCode, processingValues
    ) {
        if (providerCode !== "globalpay") {
            return this._super(...arguments);
        }
        await this._openGlobalPayHostedFields(paymentOptionId, processingValues);
    },

    async _loadGlobalPaySdk() {
        if (window.GlobalPayments?.ui?.form) {
            return;
        }
        if (!this.globalPaySdkPromise) {
            this.globalPaySdkPromise = loadJS(GLOBALPAY_SDK_URL);
        }
        await this.globalPaySdkPromise;
        if (!window.GlobalPayments?.ui?.form) {
            this.globalPaySdkPromise = null;
            throw new Error("Global Payments SDK is unavailable.");
        }
    },

    _getGlobalPayProviderId(paymentOptionId, processingValues) {
        return (
            processingValues?.provider_id
            || this.paymentContext?.providerId
            || paymentOptionId
        );
    },

    async _openGlobalPayHostedFields(paymentOptionId, processingValues) {
        const providerId = this._getGlobalPayProviderId(
            paymentOptionId, processingValues
        );
        if (!providerId) {
            this._displayErrorDialog(
                _t("Payment Error"),
                _t("The Global Payments checkout session is incomplete.")
            );
            this._enableButton();
            return;
        }

        let hostedConfig;
        try {
            await this._loadGlobalPaySdk();
            hostedConfig = await rpc("/payment/globalpay/hosted_fields_config", {
                provider_id: providerId,
            });
        } catch (error) {
            const message = error instanceof RPCError
                ? error.data?.message
                : _t("The secure card form could not be initialized.");
            this._displayErrorDialog(_t("Payment Error"), message);
            this._enableButton();
            return;
        }

        if (this.globalPayHostedForm) {
            this.globalPayHostedForm.dispose();
            this.globalPayHostedForm = null;
        }
        document.getElementById(GLOBALPAY_MODAL_ID)?.remove();
        const uid = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
        const ids = {
            number: `globalpay-card-number-${uid}`,
            expiration: `globalpay-card-expiration-${uid}`,
            cvv: `globalpay-card-cvv-${uid}`,
            holder: `globalpay-card-holder-${uid}`,
            submit: `globalpay-submit-${uid}`,
            alert: `globalpay-alert-${uid}`,
            preview: `globalpay-card-preview-${uid}`,
            brand: `globalpay-card-brand-${uid}`,
        };

        const modalMarkup = `
            <div id="${GLOBALPAY_MODAL_ID}" class="modal fade" role="dialog"
                 data-bs-backdrop="static" tabindex="-1"
                 aria-labelledby="globalpay-modal-title">
                <div class="modal-dialog modal-lg modal-dialog-centered">
                    <div class="modal-content globalpay-checkout">
                        <div class="modal-header globalpay-checkout__header">
                            <h4 id="globalpay-modal-title" class="modal-title">
                                ${_t("Pay with Global Payments")}
                            </h4>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"
                                    aria-label="${_t("Close")}"></button>
                        </div>
                        <div class="modal-body globalpay-checkout__body">
                            <div class="globalpay-checkout__layout">
                                <div class="globalpay-checkout__preview-panel">
                                    <div id="${ids.preview}"
                                         class="globalpay-card-preview globalpay-card-preview--generic"
                                         aria-hidden="true">
                                        <div class="globalpay-card-preview__shine"></div>
                                        <div class="globalpay-card-preview__top">
                                            <div class="globalpay-card-preview__chip">
                                                <span></span><span></span><span></span>
                                            </div>
                                            <div id="${ids.brand}"
                                                 class="globalpay-card-preview__brand">
                                                CARD
                                            </div>
                                        </div>
                                        <div class="globalpay-card-preview__number">
                                            ••••&nbsp;&nbsp;••••&nbsp;&nbsp;••••&nbsp;&nbsp;••••
                                        </div>
                                        <div class="globalpay-card-preview__details">
                                            <div>
                                                <span>${_t("Cardholder")}</span>
                                                <strong>${_t("YOUR NAME")}</strong>
                                            </div>
                                            <div>
                                                <span>${_t("Expires")}</span>
                                                <strong>MM/YY</strong>
                                            </div>
                                        </div>
                                    </div>
                                    <p class="globalpay-checkout__preview-copy">
                                        ${_t("Secure card payment")}
                                    </p>
                                </div>
                                <div class="globalpay-checkout__form-panel">
                                    <div id="${ids.alert}" class="d-none" role="alert"></div>
                                    <div class="mb-3">
                                        <label class="form-label">${_t("Cardholder Name")}</label>
                                        <div id="${ids.holder}" class="globalpay-hosted-field"></div>
                                    </div>
                                    <div class="mb-3">
                                        <label class="form-label">${_t("Card Number")}</label>
                                        <div id="${ids.number}" class="globalpay-hosted-field"></div>
                                    </div>
                                    <div class="row">
                                        <div class="col-7 mb-3">
                                            <label class="form-label">${_t("Expiration Date")}</label>
                                            <div id="${ids.expiration}" class="globalpay-hosted-field"></div>
                                        </div>
                                        <div class="col-5 mb-3">
                                            <label class="form-label">${_t("Security Code")}</label>
                                            <div id="${ids.cvv}" class="globalpay-hosted-field"></div>
                                        </div>
                                    </div>
                                    <div id="${ids.submit}" class="globalpay-hosted-submit"></div>
                                    <p class="globalpay-checkout__security-note">
                                        <i class="fa fa-lock me-1"></i>
                                        ${_t("Card details are securely handled by Global Payments.")}
                                    </p>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>`;
        (document.getElementById("wrapwrap") || document.body)
            .insertAdjacentHTML("beforeend", modalMarkup);

        const modalElement = document.getElementById(GLOBALPAY_MODAL_ID);
        this._globalPaySetAlert(
            modalElement,
            ids.alert,
            _t("Loading secure card form…"),
            "info"
        );
        const showModal = () => {
            if (window.bootstrap?.Modal) {
                window.bootstrap.Modal.getOrCreateInstance(modalElement).show();
                return;
            }
            const jquery = window.jQuery || window.$;
            if (jquery && typeof jquery(modalElement).modal === "function") {
                jquery(modalElement).modal("show");
                return;
            }
            modalElement.classList.add("show");
            modalElement.style.display = "block";
        };
        showModal();
        // Opening Hosted Fields replaces Odoo's normal payment submission. Release
        // its page-level block now; the Hosted Fields submit handler prevents
        // duplicate card tokenization independently.
        this._enableButton();

        const configureOptions = {
            accessToken: hostedConfig.access_token,
            apiVersion: hostedConfig.api_version,
            env: hostedConfig.environment,
            reference: hostedConfig.reference,
            requireCardHolderName: true,
            fieldValidation: { enabled: true },
        };
        if (hostedConfig.account_name) {
            configureOptions.accountName = hostedConfig.account_name;
        }
        window.GlobalPayments.configure(configureOptions);

        const hostedFields = {
            "card-number": {
                placeholder: "•••• •••• •••• ••••",
                target: `#${ids.number}`,
            },
            "card-expiration": {
                placeholder: "MM / YYYY",
                target: `#${ids.expiration}`,
            },
            "card-cvv": {
                placeholder: "•••",
                target: `#${ids.cvv}`,
            },
            "card-holder-name": {
                placeholder: _t("Cardholder name"),
                target: `#${ids.holder}`,
            },
            submit: {
                text: _t("Pay Now"),
                target: `#${ids.submit}`,
                value: _t("Pay Now"),
            },
        };
        const hostedStyles = {
            "input": {
                "box-sizing": "border-box",
                "width": "100%",
                "height": "42px",
                "padding": "10px 12px",
                "border": "1px solid #ced4da",
                "border-radius": "0.375rem",
                "font-family": "Arial, sans-serif",
                "font-size": "16px",
                "background-color": "#fff",
            },
            "input:focus": {
                "outline": "none",
                "border-color": "#86b7fe",
                "box-shadow": "0 0 0 0.2rem rgba(13, 110, 253, 0.2)",
            },
            "input.invalid": {
                "border-color": "#dc3545",
            },
            "button": {
                "width": "100%",
                "padding": "10px 16px",
                "border": "0",
                "border-radius": "0.375rem",
                "color": "#fff",
                "background-color": "#0d6efd",
                "font-size": "16px",
                "cursor": "pointer",
            },
            "button:hover": {
                "background-color": "#0b5ed7",
            },
        };
        const hostedForm = window.GlobalPayments.ui.form({
            fields: hostedFields,
            styles: hostedStyles,
        });
        this.globalPayHostedForm = hostedForm;

        const transactionCacheKey = this._getGlobalPayTransactionCacheKey(providerId);
        let activeProcessingValues = processingValues;
        if (
            !activeProcessingValues
            && this.globalPayPendingTransaction?.key === transactionCacheKey
        ) {
            activeProcessingValues = this.globalPayPendingTransaction.values;
        }
        let paymentInProgress = false;
        let formDisposed = false;
        const presentationTimers = [];
        const applyFieldPresentation = (fieldType, frame) => {
            if (formDisposed || this.globalPayHostedForm !== hostedForm) {
                return;
            }
            // Before cross-origin navigation completes, contentDocument still
            // points to the localhost about:blank document. Do not post to it.
            if (!frame?.frame || frame.frame.contentDocument) {
                return;
            }
            const fieldOptions = hostedFields[fieldType];
            if (fieldOptions?.placeholder) {
                frame.setPlaceholder(fieldOptions.placeholder);
            }
            if (fieldOptions?.text) {
                frame.setText(fieldOptions.text);
            }
            frame.addStylesheet(hostedStyles);
        };

        // Cached SDK iframes can register before the SDK's own configuration
        // listener is attached. Re-apply only to navigated GlobalPay frames.
        for (const [fieldType, frame] of Object.entries(hostedForm.frames || {})) {
            const apply = () => applyFieldPresentation(fieldType, frame);
            frame.on("register", apply);
            frame.frame?.addEventListener("load", apply, { once: false });
            for (const delay of [0, 100, 300, 750]) {
                presentationTimers.push(window.setTimeout(apply, delay));
            }
        }
        hostedForm.ready(() => {
            this._globalPaySetAlert(modalElement, ids.alert, null);
        });
        hostedForm.on("token-error", (response) => {
            paymentInProgress = false;
            this._globalPaySetAlert(
                modalElement,
                ids.alert,
                this._getGlobalPayError(response, _t("Please check the card information.")),
                "danger"
            );
        });
        hostedForm.on("card-type", (response) => {
            this._updateGlobalPayCardPreview(
                modalElement,
                ids.preview,
                ids.brand,
                response
            );
        });
        hostedForm.on("token-success", async (response) => {
            if (paymentInProgress) {
                return;
            }
            paymentInProgress = true;
            const closeButton = modalElement.querySelector(".btn-close");
            if (closeButton) {
                closeButton.disabled = true;
            }
            const paymentReference = response?.paymentReference;
            if (!paymentReference) {
                paymentInProgress = false;
                if (closeButton) {
                    closeButton.disabled = false;
                }
                this._globalPaySetAlert(
                    modalElement,
                    ids.alert,
                    _t("Global Payments did not return a payment token."),
                    "danger"
                );
                return;
            }

            this._globalPaySetAlert(
                modalElement,
                ids.alert,
                _t("Processing payment…"),
                "info"
            );
            try {
                if (!activeProcessingValues) {
                    activeProcessingValues = await rpc(
                        this.paymentContext.transactionRoute,
                        this._prepareTransactionRouteParams(
                            "globalpay",
                            paymentOptionId,
                            "direct"
                        )
                    );
                    this.globalPayPendingTransaction = {
                        key: transactionCacheKey,
                        values: activeProcessingValues,
                    };
                }
                const result = await rpc("/payment/globalpay/payment", {
                    reference: activeProcessingValues.reference,
                    access_token: activeProcessingValues.access_token,
                    payment_reference: paymentReference,
                    expiry_month: response?.details?.expiryMonth,
                    expiry_year: response?.details?.expiryYear,
                    card_last4: response?.details?.cardLast4,
                    card_type: response?.details?.cardType,
                });
                if (result?.ok && ["done", "pending"].includes(result.state)) {
                    this.globalPayPendingTransaction = null;
                    window.location = "/payment/status";
                    return;
                }
                if (["cancel", "error"].includes(result?.state)) {
                    this.globalPayPendingTransaction = null;
                    activeProcessingValues = null;
                }
                this._globalPaySetAlert(
                    modalElement,
                    ids.alert,
                    result?.message
                        || (result?.status
                            ? `${_t("Global Payments returned status")}: ${result.status}`
                            : _t("The payment could not be completed.")),
                    "danger"
                );
            } catch (error) {
                const message = error instanceof RPCError
                    ? error.data?.message
                    : _t("The payment could not be completed.");
                this._globalPaySetAlert(modalElement, ids.alert, message, "danger");
            } finally {
                paymentInProgress = false;
                if (closeButton) {
                    closeButton.disabled = false;
                }
            }
        });

        modalElement.addEventListener("hidden.bs.modal", () => {
            formDisposed = true;
            for (const timer of presentationTimers) {
                window.clearTimeout(timer);
            }
            if (this.globalPayHostedForm === hostedForm) {
                hostedForm.dispose();
                this.globalPayHostedForm = null;
            }
            modalElement.remove();
            this._enableButton();
        }, { once: true });
    },

    _globalPaySetAlert(modalElement, alertId, message, level = "info") {
        const alert = modalElement?.querySelector(`#${alertId}`);
        if (!alert) {
            return;
        }
        if (!message) {
            alert.className = "d-none";
            alert.textContent = "";
            return;
        }
        alert.className = `alert alert-${level}`;
        alert.textContent = message;
    },

    _getGlobalPayError(response, fallback) {
        if (!response) {
            return fallback;
        }
        if (typeof response === "string") {
            return response;
        }
        const error = response.error || response.reasons || response.message;
        if (typeof error === "string") {
            return error;
        }
        if (Array.isArray(error)) {
            return error.map((item) => item?.message || item).join(" ");
        }
        return error?.message || error?.detail || fallback;
    },

    _getGlobalPayTransactionCacheKey(providerId) {
        const context = this.paymentContext || {};
        return JSON.stringify([
            providerId,
            context.transactionRoute,
            context.referencePrefix,
            context.amount,
            context.currencyId,
            context.partnerId,
        ]);
    },

    _updateGlobalPayCardPreview(modalElement, previewId, brandId, response) {
        const preview = modalElement?.querySelector(`#${previewId}`);
        const brand = modalElement?.querySelector(`#${brandId}`);
        if (!preview || !brand) {
            return;
        }
        const rawType = typeof response === "string" ? response : response?.cardType;
        const cardType = String(rawType || "generic").toLowerCase();
        const brands = {
            amex: "AMEX",
            diners: "DINERS",
            dinersclub: "DINERS",
            discover: "DISCOVER",
            jcb: "JCB",
            mastercard: "mastercard",
            unionpay: "UnionPay",
            visa: "VISA",
        };
        const safeType = Object.prototype.hasOwnProperty.call(brands, cardType)
            ? cardType
            : "generic";
        preview.className = `globalpay-card-preview globalpay-card-preview--${safeType}`;
        brand.textContent = brands[safeType] || "CARD";
    },
});
