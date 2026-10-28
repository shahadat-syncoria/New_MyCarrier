/** @odoo-module */
import {register_payment_method} from "@point_of_sale/app/store/pos_store";
import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { patch } from "@web/core/utils/patch";

import {PaymentMonerisCloud} from "@os_payment_pos/js/moneris_cloud/payment_moneris";

register_payment_method("moneris_cloud", PaymentMonerisCloud);

patch(PosOrder.prototype, {
    setup(vals) {
        super.setup(...arguments);
        this.moneris_rescue_reason = vals.moneris_rescue_reason || "";
    },

    serialize() {
        const data = super.serialize(...arguments);
        data.moneris_rescue_reason = this.moneris_rescue_reason || "";
        return data;
    },
});
