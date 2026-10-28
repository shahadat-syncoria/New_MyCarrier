/** @odoo-module */

import {PaymentInterface} from "@point_of_sale/app/payment/payment_interface";
import { rpc } from "@web/core/network/rpc";

export class PaymentMonerisGO extends PaymentInterface {
    setup() {
        this.rpc = rpc
        super.setup(...arguments);
    }

    canBeAdjusted() {
        return false;
    }

    async send_payment_request(cid) {
        await super.send_payment_request(...arguments);
        const order_id = this.pos.get_order()
        const line = order_id.get_selected_paymentline();
        console.log('send_payment_request--', line, order_id);
        line.set_payment_status('waiting');

        // this.pos.push_single_order(order_id);
        try {
            console.log('try', line);
            this.pos.addPendingOrder([order_id.id]);
            await this.pos.push_single_order(order_id);
            if (line && !Number.isInteger(line.id)) {
                console.log('force push order',line);
                await this.pos.syncAllOrders({ orders: [order_id] });
            }
        } catch (error) {
            line.set_payment_status('retry');
            return false;
        }

        if (this.payment_method_id.is_directly_payment) {
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
    }

    async send_payment_cancel(order, uuid) {
      await super.send_payment_cancel(...arguments);
      return true;
    };

    async sync_order_to_server() {
        await this._syncTableOrdersToServer();
    }

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
    }

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
    }

    set_payment_status(value) {
        this.payment_status = value;
    }

    close() {
        super.close();
    }

}
