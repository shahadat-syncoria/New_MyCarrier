from odoo import models, fields, api
import logging
_logger = logging.getLogger(__name__)

class PosConfig(models.Model):
    _inherit = 'pos.config'

    def _get_channel_name(self):
        print('_get_channel_name', self)
        self.ensure_one()
        _logger.info('_get_channel_name %s', self.id)
        return '["{}","{}"]'.format("pos_update_moneris_payment", self.id)

    # Encapsulation Logic hidden inside methods
    def _notify_moneris_payment(self, message):
        print('_notify_moneris_payment', self, message['write_uid'], message)
        user_id = message['write_uid']
        if not isinstance(message, list):
            message = [message]
        notifications = []
        # example of abstraction (_get_channel_name), here only method name is exposed not the detail
        notifications.append(
            [self._get_channel_name(), message]
        )
        if notifications:
            _logger.info('sending notifications %s', notifications)
            pos_user = self.env['res.users'].browse(user_id)
            print('pos_user', pos_user)
            _logger.info('pos_user %s', pos_user)
            pos_user._bus_send("pos_update_moneris_payment", notifications)
            # self.env.user._bus_send("pos_update_moneris_payment", notifications)
            self.env.cr.commit()


    # Methods to open the POS || Polymorphism - Overriding methods
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
