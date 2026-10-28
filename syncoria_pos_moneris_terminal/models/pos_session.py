from odoo import models, fields


class PosSession(models.Model):
    _description = "Point of Sale Session"
    _inherit = 'pos.session'

    # region Other methods
    def _loader_params_pos_payment_method(self):
        result = super()._loader_params_pos_payment_method()
        if result and 'search_params' in result and 'fields' in result['search_params']:
            load_fields = result['search_params']['fields']
            load_fields.append('is_directly_payment')
        return result

    def action_pos_session_closing_control(self, balancing_account=False, amount_to_balance=0, bank_payment_method_diffs=None):
        result = super().action_pos_session_closing_control(balancing_account, amount_to_balance, bank_payment_method_diffs)
        self.config_id.close_session_moneris_go_payment_methods()
        return result
    # endregion Other
