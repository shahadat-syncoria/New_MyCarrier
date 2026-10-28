/** @odoo-module */

import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { DebugWidget } from "@point_of_sale/app/debug/debug_widget";
import { patch } from "@web/core/utils/patch";
import { Component, useState } from "@odoo/owl";

export class RefundMonerisPaymentPopupWidget extends DebugWidget {
    setup() {
        super.setup();
        this.state = useState({
            selected_moneris_payment: this.props.moneris_payments[0],
        });
    }

    get item_selected() {
        return this.state.selected_moneris_payment;
    }

    onClick(item) {
        this.state.selected_moneris_payment = item;
    }

    async confirm() {
        let title = _t('Confirmation');
        let body = '';
        const selected_moneris_payment = this.state.selected_moneris_payment;
        const paymentline = this.props.paymentline;

        let refund_amount = 0;
        if (selected_moneris_payment.amount <= Math.abs(paymentline.get_amount())) {
            refund_amount = selected_moneris_payment.amount;
            body = _t('Are you sure you want to refund ') + selected_moneris_payment.bill_name + ': ' + this.env.pos.format_currency(refund_amount) + ' ?';
        } else {
            refund_amount = Math.abs(paymentline.get_amount());
            body = _t('Are you sure you want to refund partial amount ') + selected_moneris_payment.bill_name + ': ' + this.env.pos.format_currency(refund_amount) + ' ?';
        }

        const { confirmed } = await this.popup.add('ConfirmPopup', {
            title: title,
            body: body,
        });

        if (!confirmed) {
            return;
        }

        paymentline.set_amount(-refund_amount);
        super.confirm();
    }

    async getPayload() {
        return this.state.selected_moneris_payment;
    }
}
