/** @odoo-module */

import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { patch } from "@web/core/utils/patch";


patch(PosOrder.prototype, {
    electronic_payment_in_progress() {
        const is_electronic_payment_in_progress = super.electronic_payment_in_progress();

        if (!is_electronic_payment_in_progress) {
            return false;
        }

        // If all electronic payments are Moneris, allow multiple Moneris payments that are in progress
        const is_only_electronic_payment_moneris = this.paymentlines
            .filter(paymentLine => paymentLine.payment_status)
            .every(paymentLine => paymentLine.payment_method.use_payment_terminal === 'moneris');

        if (is_only_electronic_payment_moneris) {
            return false;
        }

        return true;
    },
});
