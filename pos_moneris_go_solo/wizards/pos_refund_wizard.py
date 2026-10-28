from odoo import models, fields, api
from odoo.exceptions import ValidationError

class POSRefundWizard(models.TransientModel):
    _name = 'pos.refund.wizard'
    _description = 'POS Refund Wizard'

    refund_amount = fields.Float("Refund Amount", required=True)
    pos_order_id = fields.Many2one('pos.order', string="POS Order")
    pos_payment_id = fields.Many2one('pos.payment', string="POS Payment")
    amount = fields.Float(string="POS Payment")

    @api.model
    def default_get(self, fields):
        record_ids = self._context.get('active_ids')
        res = super(POSRefundWizard, self).default_get(fields)
        pos_order_id = self.env.context.get('default_pos_order_id')
        print('pos_order_id',record_ids, pos_order_id)
        payment_id = self.env.context.get('default_payment_id')
        default_amount = self.env.context.get('default_amount')
        if pos_order_id:
            res['pos_order_id'] = pos_order_id
            res['pos_payment_id'] = payment_id
            res['amount'] = default_amount
        return res

    @api.constrains('refund_amount')
    def _check_refund_amount(self):
        for wizard in self:
            if wizard.refund_amount <= 0:
                raise ValidationError("Refund amount must be greater than 0.")
            if wizard.refund_amount > wizard.pos_order_id.amount_paid:
                raise ValidationError("Refund amount cannot exceed the total paid amount.")

    def confirm_refund(self):
        self.ensure_one()
        self.env['pos.payment'].create({
            'amount': -self.refund_amount,
            'payment_method_id': self.pos_order_id.payment_ids[0].payment_method_id.id,
            'pos_order_id': self.pos_order_id.id,
            'idempotency_key': self.pos_payment_id.idempotency_key,
            'payment_status': 'waiting',
            'last_payment_id': self.pos_payment_id.id,
            'is_refund': True,
        })
