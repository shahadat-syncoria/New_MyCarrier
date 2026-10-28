/** @odoo-module */

import { PosPayment } from "@point_of_sale/app/models/pos_payment";
import { patch } from "@web/core/utils/patch";
import { usePos } from "@point_of_sale/app/store/pos_hook";

patch(PosPayment.prototype, {
    //@override
     setup() {
        super.setup(...arguments);
        this.pos_payment_transaction = '';
        this.idempotency_key = '';
        this.card_name = '';
        this.auth_code = '';
        this.masked_pan = '';
        this.tip_amount = 0;
        this.payment_terminal_order_reference = '';
        this.tender_type = '';
        this.payment_terminal_transaction_id = '';
        this.refunded_idempotency_key = '';
    },

    set_pos_payment_transaction(pos_payment_transaction) {
        this.pos_payment_transaction = pos_payment_transaction;
    },

    get_pos_payment_transaction() {
        return this.pos_payment_transaction;
    },

    set_transaction_id(transaction_id) {
        this.transaction_id = transaction_id;
    },

    set_payment_terminal_transaction_id(payment_terminal_transaction_id) {
        this.payment_terminal_transaction_id = payment_terminal_transaction_id;
    },

    set_moneris_info(moneris_info) {
        this.idempotency_key = moneris_info.idempotency_key;
        this.card_name = moneris_info.card_name;
        this.tip_amount = moneris_info.tip_amount;
        this.auth_code = moneris_info.auth_code;
        this.masked_pan = moneris_info.masked_pan;
        this.payment_terminal_order_reference = moneris_info.payment_terminal_order_reference;
        this.tender_type = moneris_info.tender_type;
    },

    set_refunded_idempotency_key(refunded_idempotency_key) {
        this.refunded_idempotency_key = refunded_idempotency_key;
    },

    get_refunded_idempotency_key() {
        return this.refunded_idempotency_key;
    },

    init_from_JSON(json) {
        super.init_from_JSON(json);
        this.pos_payment_transaction = json.pos_payment_transaction;
        this.idempotency_key = json.idempotency_key;
        this.card_name = json.card_name;
        this.auth_code = json.auth_code;
        this.tip_amount = json.tip_amount;
        this.masked_pan = json.masked_pan;
        this.payment_terminal_order_reference = json.payment_terminal_order_reference;
        this.tender_type = json.tender_type;
        this.payment_terminal_transaction_id = json.payment_terminal_transaction_id;
        this.refunded_idempotency_key = json.refunded_idempotency_key;
    },

    export_as_JSON() {
        const json = super.export_as_JSON();
        json.pos_payment_transaction = this.pos_payment_transaction;
        json.idempotency_key = this.idempotency_key;
        json.card_name = this.card_name;
        json.tip_amount = this.tip_amount;
        json.auth_code = this.auth_code;
        json.masked_pan = this.masked_pan;
        json.payment_terminal_order_reference = this.payment_terminal_order_reference;
        json.tender_type = this.tender_type;
        json.payment_terminal_transaction_id = this.payment_terminal_transaction_id;
        json.refunded_idempotency_key = this.refunded_idempotency_key;
        return json;
    },

    canBeAdjusted() {
        return false;
    },

    set_amount_from_moneris(data) {
        let total_amount = data.amount + data.tip_amount;
        if(this.pos_order_id.state !== 'paid' && data.payment_status === 'done'){
            this.set_amount(total_amount);
        }
    },

    update_data_by_moneris_payment(data) {
        this.set_payment_status(data.payment_status);
        this.set_pos_payment_transaction(data.pos_payment_transaction);
        this.set_transaction_id(data.transaction_id);
        this.set_payment_terminal_transaction_id(data.payment_terminal_transaction_id);
        this.set_amount_from_moneris(data);
        this.set_moneris_info(data);
    },
});
