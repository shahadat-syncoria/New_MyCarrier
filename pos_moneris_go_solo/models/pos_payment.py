import json
import logging
from uuid import uuid4
from odoo.exceptions import ValidationError
from odoo import api, fields, models, _
from odoo.exceptions import UserError, AccessDenied

import requests

_logger = logging.getLogger(__name__)


class PosPayment(models.Model):
    _inherit = "pos.payment"

    pos_payment_transaction = fields.Char('POS Payment Transaction',
                                          help="POS Payment Transaction with payment terminal")
    idempotency_key = fields.Char('Idempotency Key', help='Use for the moneris payment when refunding')
    card_name = fields.Char('Card Name')
    auth_code = fields.Char('Auth Code')
    tip_amount = fields.Float('Tip Amount')
    masked_pan = fields.Char('Masked Pan')
    payment_terminal_order_reference = fields.Char('Order Id')
    payment_terminal_transaction_id = fields.Char('Moneris Go Transaction Id')
    tender_type = fields.Char('Tender Type')
    is_refund = fields.Boolean(default=False)
    journal_id = fields.Many2one('account.move', string='Journal')
    last_payment_id = fields.Many2one('pos.payment', string='Last Payment')
    is_moneris_payment = fields.Boolean(default=False)
    refunded_idempotency_key = fields.Char('Refunded Idempotency Key', help='Idempotency Key has been used to refund')

    # region Base methods
    @api.model_create_multi
    def create(self, vals_list):
        print('PosPayment create', vals_list)
        for vals in vals_list:
            if not vals.get('pos_payment_transaction', False):
                vals['pos_payment_transaction'] = uuid4()
        return super().create(vals_list)

    def _notify_pos(self,vals):
        """
        Send notification to POS
        """
        _logger.info('_notify_pos-------------- %s', vals)
        print('vals--------', vals)
        for pos_payment in self:
            pos_payment.pos_order_id.session_id.config_id._notify_moneris_payment(
                pos_payment._prepare_pos_payment_response(vals))
            return

    def write(self, vals):
        res = super().write(vals)
        print('payment update detaecting -------', vals)
        if not vals.get('uuid'):
            print('Moneris payment update detected -------')
            self._notify_pos(vals)

        # creating journal when refund amount received
        if self.is_refund and not self.journal_id and not self.payment_status == 'cancelled':
            refund_amount = abs(self.amount)  # ensure positive value
            journal = self.env['account.journal'].search([('code', '=', 'POSS')], limit=1)
            sale_account = self.env['account.account'].search([('account_type', '=', 'income'),], limit=1)
            customer_account = self.env['account.account'].search([('account_type', '=', 'asset_receivable'),], limit=1)

            if not journal:
                raise UserError("POS Journal not found.")

            move_vals = {
                'ref': f'Refund for POS/{self.pos_order_id.name}',
                'date': fields.Date.context_today(self),
                'journal_id': journal.id,
                'line_ids': [
                    (0, 0, {
                        'account_id': sale_account.id,
                        'name': 'Refund Sales',
                        'debit': refund_amount,
                        'credit': 0.0,
                    }),
                    (0, 0, {
                        'account_id': customer_account.id,
                        'name': self.pos_order_id.name,
                        'debit': 0.0,
                        'credit': refund_amount,
                    }),
                ],
            }

            move = self.env['account.move'].create(move_vals)
            move.action_post()
            self.journal_id = move.id
        return res

    # endregion Base

    # region Model methods
    @api.model
    def handle_directly_purchase(self, payment_data):
        print('payment_data', payment_data)
        headers = {'Content-Type': 'application/json'}
        payment_index = payment_data.get('payment_index')
        pos_reference = payment_data.get('order_name')
        payment = self.search(
            [('payment_index', '=', payment_index), ('pos_order_id.pos_reference', '=', pos_reference)])
        if not payment:
            raise ValueError(_('The payment does not exist!'))
        account = payment.payment_method_id.account_id
        moneris_device = payment.payment_method_id.moneris_device_id
        pos_config = payment.pos_order_id.config_id
        data = {
            "pos_session": pos_config.id,
            "client_id": account.client_id,
            "device_id": moneris_device.code,
            "result": {
                "result": {
                    "count": 1,
                    "data": [
                        {
                            "payment_transaction_id": payment.pos_payment_transaction,
                            "order_ref": pos_reference,
                            "amount": payment.amount,
                            "customer": payment.pos_order_id.partner_id and payment.pos_order_id.partner_id.name or '',
                            "payment_method": "Moneris"
                        }
                    ]
                }
            }
        }
        url = f"{account.server_url}/api/v1/services/payment_gateway/moneris_go/odoo/pos/order/"
        _logger.info('Request directly moneris payment.')
        # omni_account = self.env['omni.account'].sudo().get_latest_omni_account_by_company(self.env.user.company_id)
        headers['Authorization'] = f"Token {account.token}"
        response = requests.post(url, headers=headers, data=json.dumps(data), verify=False)
        if response.status_code != 200:
            _logger.error('The direct Moneris payment failed! %s' % response.text)
            raise UserError(_('The direct Moneris payment failed! %s' % response.text))
        content = json.loads(response.content)
        payment.handle_moneris_payment_response(content)
        return payment._prepare_pos_payment_response()

    @api.model
    def handle_directly_refund(self, payment_data):
        headers = {'Content-Type': 'application/json'}
        payment_index = payment_data.get('payment_index')
        pos_reference = payment_data.get('order_name')
        payment = self.search(
            [('payment_index', '=', payment_index), ('pos_order_id.pos_reference', '=', pos_reference)])
        if not payment:
            raise ValueError(_('The payment does not exist!'))
        account = payment.payment_method_id.account_id
        moneris_device = payment.payment_method_id.moneris_device_id
        pos_config = payment.pos_order_id.config_id
        data = {
            "pos_session": pos_config.id,
            "client_id": account.id,
            "device_id": moneris_device.code,
            "result": {
                "result": {
                    "count": 1,
                    "data": [
                        {
                            "payment_transaction_id": payment.pos_payment_transaction,
                            "order_ref": pos_reference,
                            "idempotency_key": payment.refunded_idempotency_key,
                            "amount": payment.amount,
                            "customer": payment.pos_order_id.partner_id and payment.pos_order_id.partner_id.name or '',
                            "payment_method": "Moneris"
                        }
                    ]
                }
            }
        }
        url = f"{account.server_url}/api/v1/services/payment_gateway/moneris_go/odoo/pos/order/"
        _logger.info('Request directly moneris refund.')
        omni_account = self.env['omni.account'].sudo().get_latest_omni_account_by_company(self.env.user.company_id)
        headers['Authorization'] = f"Token {omni_account.token}"
        response = requests.post(url, headers=headers, data=json.dumps(data), verify=False)
        if response.status_code != 200:
            _logger.error('The refund of a Moneris payment failed! %s' % response.text)
            raise UserError(_('The refund of a Moneris payment failed! %s' % response.text))
        content = json.loads(response.content)
        payment_data = {
            'payment_status': 'done' if content['result'] else 'retry'
        }
        payment.write(payment_data)
        return payment._prepare_pos_payment_response()

    # endregion Model

    # region Other methods
    def get_draft_go_payment_data(self):
        idempotency_key = ''
        order_id = ''
        payment_terminal_transaction_id = ''
        if self.amount < 0:
            idempotency_key = self.refunded_idempotency_key
            original_pos_payment = self.search([('idempotency_key', '=', idempotency_key)], limit=1)
            if original_pos_payment:
                order_id = original_pos_payment.payment_terminal_order_reference
                payment_terminal_transaction_id = original_pos_payment.payment_terminal_transaction_id
        return {
            'payment_transaction_id': self.pos_payment_transaction,
            'order_ref': self.pos_order_id.pos_reference,
            'amount': self.amount,
            'customer': self.pos_order_id.partner_id and self.pos_order_id.partner_id.name or '',
            'payment_method': self.payment_method_id.name,
            "idempotency_key": idempotency_key,
            "order_id": order_id,
            'bill_name' : '1',
            'shop_table' : '1',
            "transaction_id": payment_terminal_transaction_id
        }

    def _prepare_pos_payment_response(self, vals):
        return {
            "pos_reference": self.pos_order_id.pos_reference,
            "payment_index": 1,
            "write_uid": self.create_uid.id,
            "vals": vals,
            "pos_payment_transaction": self.pos_payment_transaction,
            "payment_status": self.payment_status,
            "transaction_id": self.payment_terminal_transaction_id,
            "payment_terminal_transaction_id": self.payment_terminal_transaction_id,
            "amount": self.amount,
            "idempotency_key": self.idempotency_key,
            "card_name": self.card_name,
            "tip_amount": self.tip_amount,
            "auth_code": self.auth_code,
            "masked_pan": self.masked_pan,
            "payment_terminal_order_reference": self.payment_terminal_order_reference,
            "tender_type": self.tender_type,
        }

    def handle_moneris_payment_response(self, data):
        _logger.info('handle_moneris_payment_response--------------', data)
        payment_data = {
            'payment_status': 'done' if data['status'] == 'success' else 'retry',
            'amount': data['amount'],
            'tip_amount': data['tip_amount'],
        }
        if data['status'] == 'success':
            try:
                moneris_response = data["moneris_response"]
            except KeyError:
                raise KeyError('The `moneris_response` is required.')
            try:
                payment_data.update({
                    'idempotency_key': moneris_response["idempotency_key"],
                    'card_type': moneris_response["card_type"],
                    'card_name': moneris_response["card_name"],
                    'auth_code': moneris_response["auth_code"],
                    'masked_pan': moneris_response["masked_pan"],
                    'payment_terminal_order_reference': moneris_response["order_id"],
                    'transaction_id': moneris_response["transaction_id"],
                    'payment_terminal_transaction_id': moneris_response["transaction_id"],
                    'tender_type': moneris_response["tender_type"]
                })
            except KeyError:
                raise KeyError('The `moneris_response` object is invalid.')
        self.write(payment_data)
    # endregion Other

    # inherited fun
    @api.constrains('amount')
    def _check_amount(self):
        for payment in self:
            if payment.amount < 0 and not payment.is_change and not payment.is_refund:
                pass
                # raise ValidationError(_('You cannot update negative amount.'))

    def open_refund_wizard(self):
        refund_pos_payment = self.search([('last_payment_id', '=', self.id), ('payment_status', '=', 'waiting')], limit=1)
        if refund_pos_payment:
            raise UserError("Already a refund payment is created from this payment.")
        self.ensure_one()
        return {
            'name': 'Refund Customer',
            'type': 'ir.actions.act_window',
            'res_model': 'pos.refund.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_payment_id': self.id,
                'default_pos_order_id': self.pos_order_id.id,
                'default_amount': self.amount,
            },
        }

    def action_cancel_payment(self):
        for record in self:
            if record.payment_status == 'waiting':
                record.payment_status = 'cancelled'
