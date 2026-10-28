from odoo import models, fields, api


class PosConfig(models.Model):
    _inherit = 'pos.config'

    def _get_channel_name(self):
        """
        Return full channel name as combination, POS Config ID and const CHANNEL
        """
        self.ensure_one()
        return '["{}","{}"]'.format("pos_update_moneris_payment", self.id)

    def _notify_moneris_payment(self, message):
        """
        Notify POSes about moneris payment
        """
        if not isinstance(message, list):
            message = [message]
        notifications = []
        for config in self:
            notifications.append(
                [config._get_channel_name(), "pos.config/update_moneris_payment", message]
            )
        if notifications:
            self.env["bus.bus"]._sendmany(notifications)

    # Methods to open the POS
    def _action_to_open_ui(self):
        self.open_session_moneris_go_payment_methods()
        result = super()._action_to_open_ui()
        return result

    def open_session_moneris_go_payment_methods(self):
        moneris_go_payment_methods = self.payment_method_ids.filtered(
            lambda payment_method: payment_method.is_directly_moneris())
        pos_config = self
        for moneris_go_payment_method in moneris_go_payment_methods:
            moneris_go_payment_method.open_session_moneris_go(pos_config)

    def close_session_moneris_go_payment_methods(self):
        moneris_go_payment_methods = self.payment_method_ids.filtered(
            lambda payment_method: payment_method.is_directly_moneris())
        pos_config = self
        for moneris_go_payment_method in moneris_go_payment_methods:
            moneris_go_payment_method.close_session_moneris_go(pos_config)
