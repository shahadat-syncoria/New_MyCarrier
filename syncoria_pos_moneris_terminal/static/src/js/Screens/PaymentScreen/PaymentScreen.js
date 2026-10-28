/** @odoo-module */

import { useListener } from "@web/core/utils/hooks";
// import { NumberBuffer } from "@point_of_sale/app/utils/number_buffer";
import { useService } from "@web/core/utils/hooks";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { rpc } from "@web/core/network/rpc";

export class SyncoriaPosMonerisTerminalPaymentScreen extends PaymentScreen {
    setup() {
        super.setup(...arguments);
        this.NumberBuffer = useService("number_buffer");
        this.env.bus.addChannel(this._getChannelName());
        this.env.bus.addEventListener("notification", this._onNotification.bind(this));
    }


    async _sendPaymentRequest({ detail: line }) {
        if (line.payment_method.use_payment_terminal === "moneris") {
            if (line.get_amount() < 0) {
                const refunded_orderline_ids = line.order.get_refunded_orderline_ids();
                if (refunded_orderline_ids.length === 0) {
                    this.showPopup("ErrorPopup", {
                        title: this.env._t("Refund Moneris payment failed"),
                        body: this.env._t("This order has no refund order line!"),
                    });
                    return;
                }

                const moneris_payment = await this.select_moneris_payment_to_refund(refunded_orderline_ids[0], line);
                if (!moneris_payment) {
                    return;
                }
                line.set_refunded_idempotency_key(moneris_payment.idempotency_key);
            }

            const payment_terminal = line.payment_method.payment_terminal;
            super.send_payment_request(...arguments);
            // await payment_terminal.send_payment_request(line.cid);
            await super._sendPaymentRequest({ detail: line });
        } else {
            await super._sendPaymentRequest({ detail: line });
        }
    }

    async _sendPaymentCancel({ detail: line }) {
        if (line.payment_method.use_payment_terminal === "moneris") {
            const payment_terminal = line.payment_method.payment_terminal;
            await payment_terminal.send_payment_cancel(this.currentOrder, line.cid);
        } else {
            await super._sendPaymentCancel({ detail: line });
        }
    }

    async deletePaymentLine(event) {
        const { cid } = event.detail;
        const line = this.paymentLines.find((line) => line.cid === cid);

        if (line.payment_method.use_payment_terminal === "moneris") {
            this.currentOrder.remove_paymentline(line);
            this.env.pos._onReactiveOrderUpdated(this.currentOrder);
            this.currentOrder.save_to_db();
            await this.env.pos.sync_order_to_server();
            this.NumberBuffer.reset();
            this.render(true);
        } else {
            super.deletePaymentLine(event);
        }
    }

    _getChannelName() {
        return JSON.stringify(["pos_update_moneris_payment", String(this.env.pos.config.id)]);
    }

    _onNotification({ detail: notifications }) {
        const payloads = notifications
            .filter(({ type }) => type === "pos.config/update_moneris_payment")
            .map(({ payload }) => payload);

        if (payloads.length > 0) {
            this._handleNotification(payloads);
        }
    }

    async _handleNotification(payloads) {
        if (this.env.isDebug()) {
            console.log("Payloads:", payloads);
        }

        const order = this.currentOrder;
        const paymentLines = order.get_paymentlines();

        for (const payload of payloads) {
            for (const message of payload) {
                if (order.get_name() === message.pos_reference) {
                    const paymentLine = paymentLines.find(
                        (paymentLine) => paymentLine.get_payment_index() === message.payment_index
                    );
                    paymentLine?.update_data_by_moneris_payment(message);
                }
            }
        }

        this.render(true);
    }

    async select_moneris_payment_to_refund(refunded_orderline_id, paymentline) {
        const moneris_payments = await this.get_moneris_payments(refunded_orderline_id);

        if (moneris_payments.length === 0) {
            this.showPopup("ErrorPopup", {
                title: this.env._t("Refund Moneris payment failed"),
                body: this.env._t("The refund order has no Moneris payments that can be refunded!"),
            });
            return null;
        }

        if (moneris_payments.length === 1 && moneris_payments[0].amount >= paymentline.get_amount()) {
            return moneris_payments[0];
        }

        const { confirmed, payload } = await this.showPopup("RefundMonerisPaymentPopupWidget", {
            moneris_payments: moneris_payments,
            paymentline: paymentline,
        });

        return confirmed ? payload : null;
    }

    async get_moneris_payments(refunded_orderline_id) {
        try {
            return await rpc({
                model: "pos.order.line",
                method: "get_available_moneris_payments_to_refund",
                args: [refunded_orderline_id],
            });
        } catch (error) {
            console.error("Error fetching Moneris payments:", error);
            return [];
        }
    }
}

