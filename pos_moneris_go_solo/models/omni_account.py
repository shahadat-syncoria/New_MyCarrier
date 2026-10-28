from odoo import models, fields, api, _
from odoo.exceptions import UserError


class OmniAccount(models.Model):
    _inherit = 'omni.account'

    def get_latest_omni_account_by_company(self, company):
        if not company:
            raise UserError('The company parameter is required!')
        return self.search([('company_id', '=', company.id), ('state', '=', 'active')], order='id desc', limit=1)
