/** @odoo-module */
import {register_payment_method} from "@point_of_sale/app/store/pos_store";

import {PaymentMonerisGO} from "@pos_moneris_go_solo/js/models/payment_moneris";
import {PaymentGO} from "@pos_moneris_go_solo/js/models/Payment";

register_payment_method("moneris", PaymentMonerisGO);
register_payment_method("monerisgo", PaymentGO);
