/** @odoo-module */

import { PaymentInterface } from '@point_of_sale/app/payment/payment_interface';
import { patch } from '@web/core/utils/patch';
import { useService } from '@web/core/utils/hooks';
import { _t } from '@web/core/l10n/translation';

patch(PaymentInterface.prototype, {
    setup() {
        super.setup(...arguments);
        // this.gui = useService('gui');
    },

    canBeAdjusted() {
        return false;
    },

    async send_payment_request(cid) {
        await super.send_payment_request(cid);

        const order = this.pos.get_order();
        const line = order.selected_paymentline;

        line.set_payment_status('waiting');

        // Ensure the order is marked as updated and synced
        this.pos._onReactiveOrderUpdated(order);
        order.save_to_db();
        await this.sync_order_to_server();

        if (this.payment_method.is_directly_payment) {
            let response;

            if (line.get_refunded_idempotency_key()) {
                response = await this.handle_directly_refund(line);
            } else {
                response = await this.handle_directly_purchase(line);
            }

            if (response) {
                line.update_data_by_moneris_payment(response);
            }
        }
        return true;
    },

    async send_payment_cancel(order, cid) {
        await super.send_payment_cancel(order, cid);

        const line = order.selected_paymentline;
        line.set_payment_status('retry');

        order.save_to_db();
        await this.sync_order_to_server();

        return true;
    },

        async sync_order_to_server() {
        await this._syncTableOrdersToServer();
    },

    async handle_directly_purchase(paymentline) {
        const data = {
            order_name: paymentline.order.get_name(),
            payment_index: paymentline.get_payment_index(),
        };

        return await this.rpc('/pos/payment/handle_directly_purchase', {
            jsonrpc: '2.0',
            method: 'call',
            params: { data },
        });
    },

    async handle_directly_refund(paymentline) {
        const data = {
            order_name: paymentline.order.get_name(),
            payment_index: paymentline.get_payment_index(),
        };

        return await this.rpc('/pos/payment/handle_directly_refund', {
            jsonrpc: '2.0',
            method: 'call',
            params: { data },
        });
    },

    close() {
        super.close();
    },

});
