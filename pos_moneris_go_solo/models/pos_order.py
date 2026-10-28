from odoo import api, fields, models,_
from odoo.tools import float_compare
from odoo.tools import float_is_zero, float_round, float_repr, float_compare, formatLang

class PosOrder(models.Model):
    _inherit = 'pos.order'

    payment_ids = fields.One2many('pos.payment', 'pos_order_id', inverse='_check_duplicate_payments')
    refund_total = fields.Float(string="Refund Total", compute='_compute_refund_total', store=True)
    total_tip_amount = fields.Float(string='Tip Amount', digits=0, readonly=True, compute='_compute_tip_amount',store=True)
    total_amount_without_tip = fields.Float(string='Total without Tip', digits=0, readonly=True, compute='_compute_tip_amount',store=True)

    @api.depends('payment_ids.is_refund', 'payment_ids.amount')
    def _compute_refund_total(self):
        for order in self:
            refund_sum = abs(sum(payment.amount for payment in order.payment_ids if payment.is_refund))
            order.refund_total = refund_sum

    def _check_duplicate_payments(self):
        print('_check_duplicate_payments', self)
        """Inverse method: Remove duplicate payments for the same bill_number, keeping the latest."""
        # for order in self:
        #     bill_numbers = order.payment_ids.mapped('bill_number')
        #     for bill_number in bill_numbers:
        #         duplicate_payments = order.payment_ids.filtered(lambda p: p.bill_number == bill_number).sorted('id', reverse=True)
        #         if len(duplicate_payments) > 1:
        #             for dup in duplicate_payments[0]:
        #                 dup.sudo().unlink()

            # Tip amount update for non moneris go payment line
            # if order.total_tip_amount > 0:
            #     valid_payments = order.payment_ids.filtered(lambda p: not p.payment_status or p.payment_status == '')
            #     all_bill_zero = all(p.bill_number <= 1 for p in valid_payments)
            #     if all_bill_zero and valid_payments:
            #         last_payment = valid_payments.sorted('id')[-1]
            #         tip_total = order.total_tip_amount
            #         last_payment.tip_amount = tip_total

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
                    'card_name': moneris_payment.card_name,
                    'order_name': self.pos_reference,
                    'amount': moneris_payment.amount - refunded_amount
                })
        return result

    def _process_payment_lines(self, pos_order, order, pos_session, draft):
        prec_acc = order.currency_id.decimal_places
        # Recompute amount paid because we don't trust the client
        amount_paid = sum(payment.amount for payment in order.payment_ids if payment.payment_status != 'cancel')
        order.with_context(backend_recomputation=True).write({
            'amount_paid': amount_paid if amount_paid > 0 else 0,
        })

        if not draft and not float_is_zero(pos_order['amount_return'], prec_acc):
            cash_payment_method = pos_session.payment_method_ids.filtered('is_cash_count')[:1]
            if not cash_payment_method:
                raise UserError(_("No cash statement found for this session. Unable to record returned cash."))
            return_payment_vals = {
                'name': _('return'),
                'pos_order_id': order.id,
                'amount': -pos_order['amount_return'],
                'payment_date': fields.Datetime.now(),
                'payment_method_id': cash_payment_method.id,
                'is_change': True,
            }
            order.add_payment(return_payment_vals)
            order._compute_prices()


    def get_moneris_payments(self):
        return self.mapped('payment_ids').filtered(lambda payment: payment.payment_method_id.is_moneris())
    # endregion Other
    @api.depends('amount_total','lines')
    def _compute_tip_amount(self):
        for order in self.search([]):
            tip_product = order.config_id.tip_product_id
            if tip_product:
                tip_lines = order.lines.filtered(lambda line: line.product_id.id == tip_product.id)
                order.total_tip_amount = sum(tip_lines.mapped('price_subtotal_incl'))
                order.total_amount_without_tip = order.amount_total - order.total_tip_amount
