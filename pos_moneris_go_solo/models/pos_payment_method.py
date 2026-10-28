import requests
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.addons.pos_moneris_go_solo.exceptions.MonerisGo import OpenSessionFailed, CloseSessionFailed
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)
MONERIS = 'moneris'


class PosPaymentMethod(models.Model):
    _inherit = 'pos.payment.method'

    is_directly_payment = fields.Boolean('Is Directly Payment')
    moneris_device_id = fields.Many2one("moneris.device", ondelete='restrict',
                                        domain=lambda self: [('journal_id', '=', self.id)], )
    account_id = fields.Many2one(
        string='account',
        comodel_name='omni.account',
        ondelete='restrict',
    )
    moneris_payment_journal_config_ids = fields.One2many('pos.moneris.payment.journal.config', 'pos_payment_id')


    # region Onchange methods
    @api.onchange('is_directly_payment')
    def _onchange_is_directly_payment(self):
        self.account_id = False
        self.moneris_device_id = False

    @api.onchange('use_payment_terminal')
    def _onchange_use_payment_terminal(self):
        super(PosPaymentMethod, self)._onchange_use_payment_terminal()
        self.is_directly_payment = False

    # endregion Onchange

    # region Other methods
    def _get_payment_terminal_selection(self):
        return super(PosPaymentMethod, self)._get_payment_terminal_selection() + [(MONERIS, 'Moneris')]

    def get_moneris(self, device_id):
        if device_id:
            return self.search([
                ('use_payment_terminal', '=', MONERIS),
                ('moneris_device_id.code', '=', device_id),
                ('active', '=', True)
            ])
        else:
            return self.search([
                ('use_payment_terminal', '=', MONERIS),
                # ('moneris_device_id.code', '=', device_id),
                ('active', '=', True)
            ])

    def is_moneris(self):
        return self.use_payment_terminal == MONERIS

    def is_directly_moneris(self):
        return self.is_moneris() and self.is_directly_payment

    def open_session_moneris_go(self, pos_config):
        if not pos_config:
            raise UserError(_('The pos_config parameter is required!'))
        if not self.account_id:
            raise UserError(_("Please select an omni account in the %s payment method" % self.name))
        if not self.moneris_device_id:
            raise UserError(_("Please select a moneris device in the %s payment method" % self.name))
        url = f"{self.account_id.server_url}/api/v1/services/payment_gateway/moneris_go/odoo/pos/session/"
        omni_account = self.env['omni.account'].sudo().get_latest_omni_account_by_company(self.env.user.company_id)
        params = {
            "pos_session": pos_config.id,
            "client_id": omni_account.client_id,
            "device_id": self.moneris_device_id.code,
        }
        headers = {
            "Authorization": f"Token {omni_account.token}"
        }
        _logger.info(f"Request open session moneris go with headers: {headers}")
        _logger.info(f"Request open session moneris go with params: {params}")
        response = requests.post(url, data=params, headers=headers)
        if not response.ok:
            _logger.info(f'Open session failed. {response.text}')
            raise OpenSessionFailed(f'Open session failed. {response.text}')
        _logger.info(f'Open session success. {response.text}')
        return response.content

    def close_session_moneris_go(self, pos_config):
        if not pos_config:
            raise UserError(_('The pos_config parameter is required!'))
        if not self.account_id:
            raise UserError(_("Please select an omni account in the %s payment method" % self.name))
        if not self.moneris_device_id:
            raise UserError(_("Please select a moneris device in the %s payment method" % self.name))
        url = f"{self.account_id.server_url}/api/v1/services/payment_gateway/moneris_go/odoo/pos/session/{pos_config.id}/"
        omni_account = self.env['omni.account'].sudo().get_latest_omni_account_by_company(self.env.user.company_id)
        data = {
            "pos_session": pos_config.id,
            "client_id": omni_account.client_id,
            "device_id": self.moneris_device_id.code,
        }
        headers = {
            "Authorization": f"Token {omni_account.token}"
        }
        _logger.info(f"Request close session moneris go with headers: {headers}")
        _logger.info(f"Request close session moneris go with data: {data}")
        response = requests.delete(url, headers=headers)
        if not response.ok:
            _logger.info(f'Close session failed. {response.text}')
            raise CloseSessionFailed(f'Close session failed. {response.text}')
        _logger.info(f'Close session success. {response.text}')
        return response.content
    # endregion Other


class PosMonerisPaymentJournalConfig(models.Model):
    _name = 'pos.moneris.payment.journal.config'

    # region Fields
    card_name = fields.Char(required=True, copy=False)
    is_other_payment = fields.Boolean(copy=False)
    pos_payment_id = fields.Many2one('pos.payment.method', required=True)
    receivable_account_id = fields.Many2one('account.account', required=True)
    journal_id = fields.Many2one('account.journal', string='Journal', ondelete='cascade', required=True)

    @api.constrains('is_other_payment', 'pos_payment_id')
    def _check_single_other_flag(self):
        for rec in self:
            if rec.is_other_payment:
                others = self.search([
                    ('pos_payment_id', '=', rec.pos_payment_id.id),
                    ('is_other_payment', '=', True),
                    ('id', '!=', rec.id)
                ])
                if others:
                    raise ValidationError(
                        _('Only one line can be marked as "Is Other Payment" per POS payment method.'))
