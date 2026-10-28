/** @odoo-module **/

import { _t } from '@web/core/l10n/translation';
import paymentForm from '@payment/js/payment_form';
import { rpc, RPCError } from '@web/core/network/rpc';
import { loadJS } from '@web/core/assets';

const CLOVER_MODAL_ID = 'clovercheckout_payment_form_modal';

paymentForm.include({
    /**
     * Fire-and-forget: persist a browser-side Clover Checkout failure or timing
     * onto its payment.transaction so declines/slowness that never reach the
     * server (or that raise before logging) are still visible on the record.
     */
    _cloverCheckoutLogClientEvent(reference, stage, error, clientDurationMs) {
        if (!reference) {
            return;
        }
        let errorPayload = error;
        if (error && typeof error !== 'string') {
            try {
                errorPayload = JSON.stringify(error);
            } catch (e) {
                errorPayload = String(error);
            }
        }
        try {
            rpc('/payment/clovercheckout/log_client_error', {
                reference,
                stage,
                error: errorPayload || false,
                client_duration_ms: clientDurationMs ?? null,
            }).catch(() => {});
        } catch (e) {
            // never let diagnostic logging break the payment flow
        }
    },

    async _prepareInlineForm(providerId, providerCode, paymentOptionId, paymentMethodCode, flow) {
        if (providerCode !== 'clover_checkout') {
            return this._super(...arguments);
        }
        if (flow === 'token') {
            return;
        }

        this._setPaymentFlow('direct');

        try {
            await this._ensureCloverCheckoutInfo(providerId || paymentOptionId);
        } catch (error) {
            if (error instanceof RPCError) {
                this._displayErrorDialog(_t("Server Error"), error.data.message);
                this._enableButton();
                return;
            }
            throw error;
        }
    },

    async _processDirectFlow(providerCode, paymentOptionId, paymentMethodCode, processingValues) {
        if (providerCode !== 'clover_checkout') {
            return this._super(...arguments);
        }
        await this._buildCloverCheckoutPopup(paymentOptionId, processingValues, { isTokenFlow: false });
    },

    async _processRedirectFlow(providerCode, paymentOptionId, paymentMethodCode, processingValues) {
        if (providerCode !== 'clover_checkout') {
            return this._super(...arguments);
        }
        await this._buildCloverCheckoutPopup(paymentOptionId, processingValues, { isTokenFlow: false });
    },

    async _processTokenFlow(providerCode, paymentOptionId, paymentMethodCode, processingValues) {
        if (providerCode !== 'clover_checkout') {
            if (typeof this._super === 'function') {
                return this._super(...arguments);
            }
            return;
        }
        if (typeof this._super === 'function') {
            return this._super(...arguments);
        }
        window.location = '/payment/status';
    },

    async _ensureCloverCheckoutInfo(providerId) {
        if (!this.cloverCheckoutData) {
            this.cloverCheckoutData = {};
        }
        const existing = this.cloverCheckoutData[providerId];
        if (existing && existing.sdkLoaded) {
            return existing;
        }

        const providerInfo = await rpc('/payment/clovercheckout/get_provider_info', {
            provider_id: providerId,
        });
        const sdkUrl = providerInfo.state === 'enabled'
            ? 'https://checkout.clover.com/sdk.js'
            : 'https://checkout.sandbox.dev.clover.com/sdk.js';

        await loadJS(sdkUrl);

        const data = {
            state: providerInfo.state,
            publicKey: providerInfo.clover_public_key,
            sdkUrl,
            sdkLoaded: true,
        };
        this.cloverCheckoutData[providerId] = data;
        return data;
    },

    _getCloverCheckoutProviderId(processingValues, paymentOptionId) {
        return (
            processingValues?.provider_id ||
            this.paymentContext?.providerId ||
            this.paymentContext?.provider_id ||
            paymentOptionId ||
            null
        );
    },

    _getCloverCheckoutAmount(processingValues) {
        if (processingValues?.amount !== undefined && processingValues?.amount !== null) {
            return processingValues.amount;
        }
        if (processingValues?.converted_amount !== undefined && processingValues?.converted_amount !== null) {
            return processingValues.converted_amount;
        }
        if (this.paymentContext?.amount !== undefined && this.paymentContext?.amount !== null) {
            return this.paymentContext.amount;
        }
        return 0;
    },

    async _buildCloverCheckoutPopup(paymentOptionId, processingValues, { isTokenFlow = false } = {}) {
        const providerId = this._getCloverCheckoutProviderId(processingValues, paymentOptionId);
        if (!providerId) {
            this._displayErrorDialog(_t("Payment Error"), _t("Missing Clover Checkout provider."));
            this._enableButton();
            return;
        }

        let info;
        try {
            info = await this._ensureCloverCheckoutInfo(providerId);
        } catch (error) {
            if (error instanceof RPCError) {
                this._displayErrorDialog(_t("Server Error"), error.data.message);
                this._enableButton();
                return;
            }
            throw error;
        }

        if (!info || !info.publicKey) {
            this._displayErrorDialog(_t("Payment Error"), _t("Missing Clover public key."));
            this._enableButton();
            return;
        }

        this._enableButton();

        const existing = document.getElementById(CLOVER_MODAL_ID);
        if (existing) {
            existing.remove();
        }

        const uid = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
        const elementIds = {
            number: `clover-card-number-${uid}`,
            numberErrors: `clover-card-number-errors-${uid}`,
            date: `clover-card-date-${uid}`,
            dateErrors: `clover-card-date-errors-${uid}`,
            cvv: `clover-card-cvv-${uid}`,
            cvvErrors: `clover-card-cvv-errors-${uid}`,
            postal: `clover-card-postal-${uid}`,
            postalErrors: `clover-card-postal-errors-${uid}`,
            submit: `clover-submit-${uid}`,
        };

        const clovercheckoutModal = `
            <div id="${CLOVER_MODAL_ID}" class="modal-gp modal fade" role="dialog" data-bs-backdrop="static" tabindex="-1">
                <div class="modal-dialog modal-lg" style="margin-top:100px;">
                    <form action="#" method="post" id="payment-form-box">
                        <div class="modal-content">
                            <div class="modal-header">
                                <h4 class="modal-title">Pay with Clover Checkout</h4>
                                <button type="button" class="close btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                            </div>
                            <div class="modal-body">
                                <div class="clover_container">
                                    <div class="form-row top-row">
                                        <div id="${elementIds.number}" class="field card-number"></div>
                                        <div class="input-errors" id="${elementIds.numberErrors}" role="alert"></div>
                                    </div>
                                    <div class="form-row">
                                        <div id="${elementIds.date}" class="field third-width"></div>
                                        <div class="input-errors" id="${elementIds.dateErrors}" role="alert"></div>
                                    </div>
                                    <div class="form-row">
                                        <div id="${elementIds.cvv}" class="field third-width"></div>
                                        <div class="input-errors" id="${elementIds.cvvErrors}" role="alert"></div>
                                    </div>
                                    <div class="form-row">
                                        <div id="${elementIds.postal}" class="field third-width"></div>
                                        <div class="input-errors" id="${elementIds.postalErrors}" role="alert"></div>
                                    </div>
                                    <div id="card-response" role="alert"></div>
                                    <div class="button-container">
                                        <button type="submit" id="${elementIds.submit}">Submit Payment</button>
                                    </div>
                                    <div class="clover-footer" style="padding: 18px 24px; background-color: #F4F5F5; border-radius: 0 0 14px 14px; text-align: center">
                                        <div class="clover-secure-payments" style="color: #B1B6B8; font-family: Roboto; font-size: 14px; font-weight: bold; line-height: 16px;">
                                            <img style="margin: -2px 8px;max-width: 12px;" src="https://checkout.sandbox.dev.clover.com/assets/icons/lock.png">Secure Payments Powered by <b>Clover</b><img style="margin: -4px 8px;max-width: 20px;" src="https://checkout.sandbox.dev.clover.com/assets/icons/clover-symbol.png">
                                        </div>
                                        <a class="clover-privacy-link" title="Privacy Policy" href="https://www.clover.com/privacy-policy" style="font-family: Roboto; font-size: 14px; font-weight: bold; line-height: 16px;">Privacy Policy</a>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </form>
                </div>
            </div>`;

        const container = document.getElementById('wrapwrap') || document.body;
        container.insertAdjacentHTML('beforeend', clovercheckoutModal);

        const $ = window.$ || window.jQuery;
        const modalEl = document.getElementById(CLOVER_MODAL_ID);
        if (!modalEl) {
            return;
        }

        const clover = window.Clover ? new window.Clover(info.publicKey) : null;
        const elements = clover ? clover.elements() : null;

        const mountCloverElements = () => {
            if (modalEl.dataset.cloverMounted === '1') {
                return;
            }
            modalEl.dataset.cloverMounted = '1';

            if (!window.Clover || !clover || !elements) {
                this._displayErrorDialog(_t("Payment Error"), _t("Clover SDK is not available."));
                return;
            }

            const cardNumber = elements.create('CARD_NUMBER');
            const cardDate = elements.create('CARD_DATE');
            const cardCvv = elements.create('CARD_CVV');
            const cardPostalCode = elements.create('CARD_POSTAL_CODE');

            cardNumber.mount(`#${elementIds.number}`);
            cardDate.mount(`#${elementIds.date}`);
            cardCvv.mount(`#${elementIds.cvv}`);
            cardPostalCode.mount(`#${elementIds.postal}`);

            const displayCardNumberError = document.getElementById(elementIds.numberErrors);
            const displayCardDateError = document.getElementById(elementIds.dateErrors);
            const displayCardCvvError = document.getElementById(elementIds.cvvErrors);
            const displayCardPostalCodeError = document.getElementById(elementIds.postalErrors);

            cardNumber.addEventListener('change', (event) => {
                displayCardNumberError.innerHTML = event.CARD_NUMBER?.error || '';
            });
            cardNumber.addEventListener('blur', (event) => {
                displayCardNumberError.innerHTML = event.CARD_NUMBER?.error || '';
            });

            cardDate.addEventListener('change', (event) => {
                displayCardDateError.innerHTML = event.CARD_DATE?.error || '';
            });
            cardDate.addEventListener('blur', (event) => {
                displayCardDateError.innerHTML = event.CARD_DATE?.error || '';
            });

            cardCvv.addEventListener('change', (event) => {
                displayCardCvvError.innerHTML = event.CARD_CVV?.error || '';
            });
            cardCvv.addEventListener('blur', (event) => {
                displayCardCvvError.innerHTML = event.CARD_CVV?.error || '';
            });

            cardPostalCode.addEventListener('change', (event) => {
                displayCardPostalCodeError.innerHTML = event.CARD_POSTAL_CODE?.error || '';
            });
            cardPostalCode.addEventListener('blur', (event) => {
                displayCardPostalCodeError.innerHTML = event.CARD_POSTAL_CODE?.error || '';
            });
        };

        if ($) {
            $(`#${CLOVER_MODAL_ID}`).on('shown.bs.modal', () => {
                mountCloverElements();
            });
            $(`#${CLOVER_MODAL_ID}`).modal('show');
        } else {
            mountCloverElements();
        }

        const submitButton = modalEl.querySelector(`#${elementIds.submit}`);
        if (submitButton) {
            submitButton.addEventListener('click', async (event) => {
                event.preventDefault();

                if (!window.Clover || !clover) {
                    this._cloverCheckoutDisplayAlert(modalEl, 'danger', _t("Clover SDK is not available."));
                    return;
                }
                mountCloverElements();

                const originalLabel = '<i class="fa fa-credit-card"></i> Pay Now';
                const verifyingLabel = '<i class="fa fa-spinner fa-spin"></i> Verifying Card Information...';
                const processingLabel = '<i class="fa fa-spinner fa-spin"></i> Processing Payment...';

                this._setCloverCheckoutButtonState(submitButton, verifyingLabel, true);
                this._setCloverCheckoutInputsDisabled(modalEl, true);
                this._clearCloverCheckoutAlert(modalEl);

                const clientReference = processingValues.reference;

                let tokenResult;
                try {
                    tokenResult = await clover.createToken();
                } catch (error) {
                    console.error('Clover tokenization failed:', error);
                    this._cloverCheckoutLogClientEvent(
                        clientReference, 'create_token', error?.message || String(error));
                    this._cloverCheckoutDisplayAlert(modalEl, 'danger', _t("Tokenization failed."));
                    this._setCloverCheckoutButtonState(submitButton, originalLabel, false);
                    this._setCloverCheckoutInputsDisabled(modalEl, false);
                    return;
                }

                if (tokenResult.errors) {
                    const errorMsg = Object.values(tokenResult.errors).join('\n');
                    this._cloverCheckoutLogClientEvent(
                        clientReference, 'create_token', tokenResult.errors);
                    this._cloverCheckoutDisplayAlert(modalEl, 'danger', errorMsg || _t("Invalid Card Information"));
                    this._setCloverCheckoutButtonState(submitButton, originalLabel, false);
                    this._setCloverCheckoutInputsDisabled(modalEl, false);
                    return;
                }

                const cloverToken = tokenResult.token;
                const shouldSaveCard = !!this.paymentContext?.tokenizationRequested;
                const isFromPaymentMethodPage = window.location.pathname === '/my/payment_method';
                const partnerId = processingValues.partner_id || this.paymentContext?.partnerId;
                const paymentMethodId = this.paymentContext?.paymentMethodId || paymentOptionId || null;
                const currencyId = processingValues.currency_id || this.paymentContext?.currencyId;
                const amount = this._getCloverCheckoutAmount(processingValues);
                const reference = processingValues.reference;

                let chargeSource = cloverToken;
                let cloverDataId = '';
                if (shouldSaveCard) {
                    let response;
                    try {
                        response = await rpc('/payment/clovercheckout/store_payment_method', {
                            reference,
                            usage_mode: 'MULTIPLE',
                            partner_id: partnerId,
                            token: cloverToken,
                            save_card: true,
                        });
                    } catch (error) {
                        if (error instanceof RPCError) {
                            this._cloverCheckoutLogClientEvent(
                                clientReference, 'store_payment_method',
                                error?.data?.message || 'RPCError');
                            this._cloverCheckoutDisplayAlert(
                                modalEl,
                                'danger',
                                error?.data?.message || _t("Payment processing failed")
                            );
                            this._setCloverCheckoutButtonState(submitButton, originalLabel, false);
                            this._setCloverCheckoutInputsDisabled(modalEl, false);
                            return;
                        }
                        console.error('Error storing payment method:', error);
                        this._cloverCheckoutLogClientEvent(
                            clientReference, 'store_payment_method', error?.message || String(error));
                        this._cloverCheckoutDisplayAlert(modalEl, 'danger', _t("Invalid Card Information"));
                        this._setCloverCheckoutButtonState(submitButton, originalLabel, false);
                        this._setCloverCheckoutInputsDisabled(modalEl, false);
                        return;
                    }

                    const hasFirstCallError = (
                        !response
                        || typeof response === 'string'
                        || !!response.error
                        || !response.id
                    );
                    if (hasFirstCallError) {
                        const firstCallError = this._getCloverCheckoutResponseErrorMessage(
                            response,
                            _t("Could not store payment method.")
                        );
                        this._cloverCheckoutDisplayAlert(
                            modalEl,
                            'danger',
                            firstCallError
                        );
                        this._setCloverCheckoutButtonState(submitButton, originalLabel, false);
                        this._setCloverCheckoutInputsDisabled(modalEl, false);
                        return;
                    }

                    chargeSource = response.id;
                    cloverDataId = response?.sources?.data?.[0] ?? '';

                    if (isFromPaymentMethodPage || isTokenFlow) {
                        try {
                            await rpc('/payment/clovercheckout/save_payment_token', {
                                token_id: response.id,
                                reference,
                                provider_id: providerId,
                                payment_method_id: paymentMethodId,
                                currency_id: currencyId,
                                partner_id: partnerId,
                                clover_checkout_id: cloverDataId,
                            });
                            this._hidePaymentProcessingWarning();
                            window.location = '/payment/status';
                            return;
                        } catch (error) {
                            console.error('Error saving payment token:', error);
                            this._cloverCheckoutLogClientEvent(
                                clientReference, 'save_payment_token',
                                error?.data?.message || error?.message || String(error));
                            this._cloverCheckoutDisplayAlert(
                                modalEl,
                                'danger',
                                _t("Error saving payment method.")
                            );
                            this._setCloverCheckoutButtonState(submitButton, originalLabel, false);
                            this._setCloverCheckoutInputsDisabled(modalEl, false);
                            return;
                        }
                    }
                }

                this._setCloverCheckoutButtonState(submitButton, processingLabel, true);
                this._setCloverCheckoutInputsDisabled(modalEl, true);
                this._clearCloverCheckoutAlert(modalEl);

                let paymentResponse;
                const chargeStartedAt = (window.performance && performance.now()) || Date.now();
                try {
                    paymentResponse = await rpc('/payment/clovercheckout/payment', {
                        reference,
                        provider_id: providerId,
                        currency_id: currencyId,
                        access_token: chargeSource,
                        partner_id: partnerId,
                        payment_ref: chargeSource,
                        amount,
                        token_response: chargeSource,
                        clover_data_id: cloverDataId,
                    });
                } catch (error) {
                    const elapsedMs = ((window.performance && performance.now()) || Date.now()) - chargeStartedAt;
                    console.error('Error initiating payment:', error);
                    this._cloverCheckoutLogClientEvent(
                        clientReference, 'charge',
                        error?.data?.message || error?.message || String(error), elapsedMs);
                    this._cloverCheckoutDisplayAlert(modalEl, 'danger', _t("Error Processing Payment."));
                    this._setCloverCheckoutButtonState(submitButton, originalLabel, false);
                    this._setCloverCheckoutInputsDisabled(modalEl, false);
                    return;
                }
                const chargeElapsedMs = ((window.performance && performance.now()) || Date.now()) - chargeStartedAt;

                let parsedResponse = paymentResponse;
                if (typeof paymentResponse === 'string') {
                    try {
                        parsedResponse = JSON.parse(paymentResponse);
                    } catch (error) {
                        parsedResponse = null;
                    }
                }

                if (parsedResponse && parsedResponse.status === 'succeeded' && parsedResponse.paid === true) {
                    // Success timing only (no error) - server already logged the charge_response.
                    this._cloverCheckoutLogClientEvent(
                        clientReference, 'charge', false, chargeElapsedMs);
                    this._setCloverCheckoutButtonState(
                        submitButton,
                        '<i class="fa fa-spinner fa-spin"></i> Payment Completed...',
                        true
                    );
                    this._hidePaymentProcessingWarning();
                    window.location = '/payment/status';
                    return;
                }

                // The server (_process_notification_data) already parsed and logged this
                // decline onto the transaction; only record the client-observed timing here
                // so the log isn't duplicated.
                this._cloverCheckoutLogClientEvent(
                    clientReference, 'charge', false, chargeElapsedMs);
                this._cloverCheckoutDisplayAlert(
                    modalEl,
                    'danger',
                    parsedResponse?.error?.message || _t("Invalid Card Information")
                );
                this._setCloverCheckoutButtonState(submitButton, originalLabel, false);
                this._setCloverCheckoutInputsDisabled(modalEl, false);
            });
        }

        if ($) {
            $(`#${CLOVER_MODAL_ID}`).on('hidden.bs.modal', () => {
                const modal = document.getElementById(CLOVER_MODAL_ID);
                if (modal) {
                    modal.remove();
                }
                const payButton = document.getElementById('o_payment_form_pay');
                if (payButton) {
                    payButton.removeAttribute('disabled');
                    const loader = payButton.querySelector('.o_loader');
                    if (loader) {
                        loader.remove();
                    }
                }
                window.location.reload();
            });
        }
    },

    _setCloverCheckoutButtonState(buttonEl, labelHtml, disabled) {
        if (!buttonEl) {
            return;
        }
        if (labelHtml) {
            buttonEl.innerHTML = labelHtml;
        }
        buttonEl.disabled = !!disabled;
    },

    _setCloverCheckoutInputsDisabled(modalEl, disabled) {
        if (!modalEl) {
            return;
        }
        const inputs = modalEl.querySelectorAll('input');
        inputs.forEach((input) => {
            input.disabled = !!disabled;
        });
    },

    _clearCloverCheckoutAlert(modalEl) {
        if (!modalEl) {
            return;
        }
        const alert = modalEl.querySelector('#payment-alert');
        if (alert) {
            alert.remove();
        }
    },

    _cloverCheckoutDisplayAlert(modalEl, type, message) {
        if (!modalEl) {
            return;
        }
        const alertHtml = `
            <div id="payment-alert" class="alert alert-${type} alert-dismissible fade show" role="alert">
                ${message}
                <button type="button" class="close btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
            </div>
        `;
        const modalBody = modalEl.querySelector('.modal-body');
        if (modalBody) {
            modalBody.insertAdjacentHTML('afterbegin', alertHtml);
        }
    },
    _getCloverCheckoutResponseErrorMessage(response, fallbackMessage = null) {
        if (!response) {
            return fallbackMessage;
        }
        if (typeof response === 'string') {
            return response || fallbackMessage;
        }
        if (response.error) {
            if (typeof response.error === 'string') {
                return response.error;
            }
            if (typeof response.error === 'object') {
                return response.error.message || response.error.detail || fallbackMessage;
            }
        }
        if (response.errors_message) {
            return response.errors_message;
        }
        return response.message || response.detail || fallbackMessage;
    },
});
