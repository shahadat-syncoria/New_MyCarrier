/** @odoo-module */

const paymentConfigurationMoneris = {
    setup() {
        super.setup(...arguments);

        this.pos_payment_transaction = '';
        this.idempotency_key = '';
        this.card_name = '';
        this.auth_code = '';
        this.masked_pan = '';
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

    set_amount_from_moneris(amount) {
        const need_payment_amount = this.amount;
        if (need_payment_amount < amount) {
            const tip = amount - need_payment_amount;
            const new_tip = this.order.get_tip() + tip;
            this.order.set_tip(Math.round(new_tip, this.pos.currency.decimal_places));
        }
        this.set_amount(amount);
    },

    update_data_by_moneris_payment(data) {
        this.set_payment_status(data.payment_status);
        this.set_pos_payment_transaction(data.pos_payment_transaction);
        this.set_transaction_id(data.transaction_id);
        this.set_payment_terminal_transaction_id(data.payment_terminal_transaction_id);
        this.set_amount_from_moneris(data.amount);
        this.set_moneris_info(data);
    },
}
