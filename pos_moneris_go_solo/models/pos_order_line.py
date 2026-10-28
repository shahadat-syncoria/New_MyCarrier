from odoo import models, api, _


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    @api.model
    def get_available_moneris_payments_to_refund(self, refunded_orderline_id):
        refunded_orderline = self.browse(refunded_orderline_id)
        if not refunded_orderline:
            raise ValueError(_('The refunded order line does not exist!'))
        return refunded_orderline.order_id.get_moneris_payments_to_refund()
