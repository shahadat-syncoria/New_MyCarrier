import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { browser } from "@web/core/browser/browser";

patch(PosStore.prototype, {
    async setup() {
        await super.setup(...arguments);
    },

    async set_tip(tip, order_name = null) {
        let currentOrder = this.get_order();

        const shouldSearchOrder =
        (!currentOrder && order_name && this.data?.records?.['pos.order']) ||
        (currentOrder && order_name && currentOrder.pos_reference !== order_name);

        if (shouldSearchOrder) {
            const orders = Array.from(this.data.records['pos.order']);
            for (let i = orders.length - 1; i >= 0; i--) {
                const order = orders[i];
                const orderData = order[1];
                // Check if this is the order we're looking for
                if (orderData.pos_reference === order_name) {
                    currentOrder = orderData; // Found our order
                    break;
                }
            }
        }
        const tipProduct = this.config.tip_product_id;
        try {
            let line = currentOrder.lines.find( (line) => line.product_id.id === tipProduct.id);
            if (line) {
                line.set_unit_price(tip);
            } else {
                line = await this.addLineToCurrentOrder({
                    product_id: tipProduct,
                    price_unit: tip,
                    order_name: order_name,
                    currentOrder: currentOrder,
                }, {});
            }
            currentOrder.is_tipped = true;
            currentOrder.tip_amount = tip;

            if(!order_name){
                let paymentLine = currentOrder.payment_ids[0];
                console.log('single paymentLines', paymentLine)
                paymentLine.update({
                    tip_amount: tip,
                });
                this.pos.addPendingOrder([currentOrder.id]);
                this.pos.push_single_order(currentOrder);
            }

            return line;
            }
        catch (error) {
            console.error('Error in addLineToCurrentOrder2:', error);
        }
    }

});
