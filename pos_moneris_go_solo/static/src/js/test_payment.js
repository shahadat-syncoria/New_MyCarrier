import { PosPayment } from "@point_of_sale/app/models/pos_payment";
import { patch } from "@web/core/utils/patch";

patch(PosPayment.prototype, {

    async pay() {
        this.set_payment_status("waiting");

        return this.handle_payment_response(
            await this.payment_method_id.payment_terminal.send_payment_request(this.uuid)
        );
    },

    setTerminalServiceId(id) {
        this.terminalServiceId = id;
    },
});
