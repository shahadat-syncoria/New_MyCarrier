/** @odoo-module */

import { useListener } from "@web/core/utils/hooks";
import { useService } from "@web/core/utils/hooks";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import {onWillStart} from "@odoo/owl";
import { AlertDialog, ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";

patch(PaymentScreen.prototype, {
    setup() {
        super.setup(...arguments);
        this.rpc = rpc;
        this.printer = useService("printer");
        this.numberBuffer = useService("number_buffer");
        this.busService = useService("bus_service");
        this.notification = useService("notification");

        this.busService.subscribe("pos_update_moneris_payment", (payload) => {
            this.onPosOrderCreation(payload);
        });

        onWillStart(() => {
            const currentOrder = this.currentOrder;
            const orderCreator = currentOrder?.cashier;
            const currentCashier = this.pos.get_cashier()?.name;

            // Auto-initiate payment if order is fresh
            if (
                currentOrder.payment_ids.length === 0
            ) {
                const monerisMethod = this.pos.config.payment_method_ids.find(pm => pm.use_payment_terminal === 'moneris');
                if (monerisMethod) {
                    console.log("Auto-triggering payment with Moneris method...");
                    this.addNewPaymentLine(monerisMethod, true);
                } else {
                    console.warn("Moneris payment method not found!");
                }
            }
        });
        this.isProcessingTip = false;
    },

    async addNewPaymentLine(paymentMethod, is_auto_payment = false) {
        if (
            paymentMethod.type === "pay_later" &&
            (!this.currentOrder.to_invoice ||
                this.pos.models["ir.module.module"].find((m) => m.name === "pos_settle_due")
                    ?.state !== "installed")
        ) {
            this.notification.add(
                _t(
                    "To ensure due balance follow-up, generate an invoice or download the accounting application. "
                ),
                { autocloseDelay: 7000, title: _t("Warning") }
            );
        }
        if (this.pos.paymentTerminalInProgress && paymentMethod.use_payment_terminal) {
            this.dialog.add(AlertDialog, {
                title: _t("Error"),
                body: _t("There is already an electronic payment in progress."),
            });
            return;
        }

        // original function: click_paymentmethods
        const result = this.currentOrder.add_paymentline(paymentMethod);
        console.log('addNewPaymentLine--', result);
        if (!this.check_cash_rounding_has_been_well_applied()) {
            return;
        }
        if (result) {
            this.numberBuffer.reset();
            if (paymentMethod.use_payment_terminal) {
                const newPaymentLine = this.paymentLines.at(-1);
                console.log('newPaymentLine--', newPaymentLine);
                const mode = is_auto_payment ? undefined : 'new';
                this.sendPaymentRequest(newPaymentLine, mode, is_auto_payment);
            }
            return true;
        } else {
            this.dialog.add(AlertDialog, {
                title: _t("Error"),
                body: _t("There is already an electronic payment in progress."),
            });
            return false;
        }
    },
    
    async sendPaymentRequest(line, is_new, is_auto_payment = false) {
        if (line.payment_method_id.use_payment_terminal === "moneris") {
            // if (line.get_amount() < 0) {
            //     const refunded_orderline_ids = line.order.getHasRefundLines();
            //     if (refunded_orderline_ids.length === 0) {
            //         this.showPopup('ErrorPopup', {
            //             title: this.env._t('Refund Moneris payment failed'),
            //             body: this.env._t('This order has not the refund order line!')
            //         });
            //         return;
            //     }
            //
            //     const moneris_payment = await this.select_moneris_payment_to_refund(refunded_orderline_ids[0], line);
            //     if (!moneris_payment) {
            //         return;
            //     }
            //     line.set_refunded_idempotency_key(moneris_payment.idempotency_key);
            // }
            if(!is_new){
                const payment_terminal = line.payment_method_id.payment_terminal;
                await payment_terminal.send_payment_request(line.cid);
                if (is_auto_payment && this.pos.get_order()){
                    await this.autoClickPrintBill()
                }
            }

        } else {
            await super.sendPaymentRequest();
        }
    },

    async autoClickPrintBill() {
        try {
            const order = this.pos.get_order();
            if (!order) return;

            await this.printer.print(OrderReceipt, {
                data: this.pos.orderExportForPrinting(order),
                formatCurrency: this.env.utils.formatCurrency,
            });
        } catch (error) {
            console.warn("autoClickPrintBill failed silently:", error);
        }
    },

    async sendPaymentCancel({ detail: line }) {
        line.set_payment_status("retry");
        if (line.payment_method.use_payment_terminal === "moneris") {
            const payment_terminal = line.payment_method.payment_terminal;
            await payment_terminal.send_payment_cancel(this.currentOrder, line.cid);
        } else {
            await super.sendPaymentCancel({ detail: line });
        }
    },

    async deletePaymentLine(uuid) {
        const line = this.paymentLines.find((line) => line.uuid === uuid);
        if (line.payment_method_id.payment_method_type === "qr_code") {
            this.currentOrder.remove_paymentline(line);
            this.numberBuffer.reset();
            return;
        }
        // If a paymentline with a payment terminal linked to
        // it is removed, the terminal should get a cancel
        // request.
        if (["waiting", "waitingCard", "timeout"].includes(line.get_payment_status())) {
            line.set_payment_status("waitingCancel");
            line.payment_method_id.payment_terminal
                .send_payment_cancel(this.currentOrder, uuid)
                .then(() => {
                    this.currentOrder.remove_paymentline(line);
                    this.numberBuffer.reset();
                });
        } else if (line.get_payment_status() !== "waitingCancel") {
            this.currentOrder.remove_paymentline(line);
            this.numberBuffer.reset();
        }
        this.render(true);
        const data = {
            payment_id: line.id,
            order_id: null,
        };
        // Make an RPC call to update the pos.payment state
        if (this.currentOrder && Number.isInteger(line.id)) {
             await this.rpc('/monerisgo/update_order_info', {
            jsonrpc: '2.0',
            method: 'call',
            params: { data },
        });
        }
    },

    _getChannelName() {
        return JSON.stringify(["pos_update_moneris_payment", String(this.pos.config.id)]);
    },

    onPosOrderCreation(notifications) {
        setTimeout(() => this._handleNotification(notifications[0][1]), 100)
    },

    async _handleNotification(payloads) {
        // If we're already processing a tip, skip this notification
        if (this.isProcessingTip) {
            return;
        }
        let currentOrder = this.currentOrder;
        let payload = payloads[0]
        const all_orders = Array.from(this.pos.data.records['pos.order']);
        for (let i = all_orders.length - 1; i >= 0; i--) {
            const order = all_orders[i];
            const orderData = order[1];
            if (orderData.pos_reference === payload.pos_reference) {
                currentOrder = orderData; // Found our order
                break;
            }
        }

        console.log('payloads------11', all_orders, currentOrder, currentOrder.pos_reference, payload)
        const paymentLines = currentOrder.payment_ids;
        if (currentOrder.pos_reference === payload.pos_reference && currentOrder.state !== 'paid') {
            const payment = paymentLines.find(
                p => p.payment_status === 'waiting'
            );
            if (payment) {
                payment.tip_amount = payload.tip_amount
                try {
                    if (payload.tip_amount > 0 && payload.payment_status === 'done') {
                        this.pos.set_tip(payload.tip_amount, payload.pos_reference);
                    }
                    payment.update_data_by_moneris_payment(payload);
                    this.pos.addPendingOrder([currentOrder.id]);
                    this.pos.push_single_order(currentOrder);
                } catch (error) {
                    console.error('Error in addLineToCurrentOrder1:', error);
                }
            } else {
                console.warn("No matching payment found for this payment:");
            }
        }

        this.render(true);
    },
    //
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
    },

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
    },
});

