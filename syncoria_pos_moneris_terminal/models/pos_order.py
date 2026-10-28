from odoo import api, fields, models
from odoo.tools import float_compare


class PosOrder(models.Model):
    _inherit = 'pos.order'

    # region Model methods
    @api.model
    def _payment_fields(self, order, ui_paymentline):
        result = super()._payment_fields(order, ui_paymentline)
        result['pos_payment_transaction'] = ui_paymentline['pos_payment_transaction'] or False
        result['idempotency_key'] = ui_paymentline['idempotency_key'] or False
        result['card_name'] = ui_paymentline['card_name'] or False
        result['auth_code'] = ui_paymentline['auth_code'] or False
        result['masked_pan'] = ui_paymentline['masked_pan'] or False
        result['payment_terminal_order_reference'] = ui_paymentline['payment_terminal_order_reference'] or False
        result['tender_type'] = ui_paymentline['tender_type'] or False
        result['payment_terminal_transaction_id'] = ui_paymentline['payment_terminal_transaction_id'] or False

        result['refunded_idempotency_key'] = ui_paymentline['refunded_idempotency_key'] or False
        return result

    # endregion Model

    # region Other methods
    def _get_fields_for_payment_lines(self):
        """ Override method

        Get fields for the payment lines in the POS FE
        :return: Field name list
        """
        fields = super()._get_fields_for_payment_lines()
        fields.append('pos_payment_transaction')
        fields.append('idempotency_key')
        fields.append('card_name')
        fields.append('auth_code')
        fields.append('masked_pan')
        fields.append('payment_terminal_order_reference')
        fields.append('tender_type')
        fields.append('payment_terminal_transaction_id')
        
        fields.append('refunded_idempotency_key')
        return fields

    def get_moneris_payments_to_refund(self):
        moneris_payments = self.get_moneris_payments().filtered(lambda moneris_payment: moneris_payment.idempotency_key)
        refunded_order_ids = self.mapped('lines.refund_orderline_ids.order_id')
        refunded_moneris_payments = refunded_order_ids.get_moneris_payments().filtered(
            lambda moneris_payment: moneris_payment.refunded_idempotency_key)
        result = []
        for moneris_payment in moneris_payments:
            refunded_amount = abs(sum(refunded_moneris_payments.filtered(lambda refunded_moneris_payment: refunded_moneris_payment.refunded_idempotency_key == moneris_payment.idempotency_key).mapped('amount')))
            if float_compare(moneris_payment.amount, refunded_amount, precision_digits=2) > 0:
                result.append({
                    'id': moneris_payment.id,
                    'idempotency_key': moneris_payment.idempotency_key,
                    'bill_name': moneris_payment.bill_name,
                    'card_name': moneris_payment.card_name,
                    'order_name': self.pos_reference,
                    'amount': moneris_payment.amount - refunded_amount
                })
        return result

    def get_moneris_payments(self):
        return self.mapped('payment_ids').filtered(lambda payment: payment.payment_method_id.is_moneris())
    # endregion Other
