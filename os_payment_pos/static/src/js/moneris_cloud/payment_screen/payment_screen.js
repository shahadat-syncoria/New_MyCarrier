import {PaymentScreen} from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { PaymentScreenPaymentLines } from "@point_of_sale/app/screens/payment_screen/payment_lines/payment_lines";
import {patch} from "@web/core/utils/patch";
import {_t} from "@web/core/l10n/translation";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";
import { TextInputPopup } from "@point_of_sale/app/utils/input_popups/text_input_popup";
import {SelectPreauthPopup} from "./popup/select_preauth_popup";

patch(PaymentScreenPaymentLines.prototype, {
    async onClickMonerisRescue(line) {
        const reason = await makeAwaitable(this.dialog, TextInputPopup, {
            title: _t("Rescue Reason"),
            placeholder: _t("Enter rescue reason"),
            rows: 3,
            getPayload: (value) => (value || "").trim(),
        });
        if (!reason) {
            return;
        }
        line.pos_order_id.moneris_rescue_reason = reason;
        line.set_payment_status('retry');
        this.pos.paymentTerminalInProgress = false;
    },
});

patch(PaymentScreen.prototype, {
        async onClickSelectPreauthView(event) {
            const order = this.currentOrder;
            const customer = order.get_partner();
            if (!customer) {
                this.env.services.notification.add("Please select a customer before selecting a preauth.", {type: "warning"});
                return;
            }
            const allMethods = this.pos.config.payment_method_ids; // POS model cache
            const is_moneris_go = allMethods.filter(pm => pm.is_moneris_go_cloud);
            if (!is_moneris_go) {
                this.env.services.notification.add("Moneris Go is not available as payment method! Please add Syncoria Moneris Go Payment Method.", {type: "warning"});
                return;
            }
            this.dialog.add(SelectPreauthPopup, {
                customerId: customer.id,
                monerisPaymentMethodId:is_moneris_go
            });
        }
    }
)
