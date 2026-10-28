# -*- coding: utf-8 -*-

from odoo import _, api, models
from odoo.exceptions import AccessError


class PaymentToken(models.Model):
    _inherit = 'payment.token'

    def _get_available_tokens(self, providers_ids, partner_id, is_validation=False, **kwargs):
        """Hide saved tokens from anonymous visitors (e.g. payment link in a fresh browser)."""
        if not is_validation and self._payment_portal_user_is_public():
            return self.env['payment.token']
        return super()._get_available_tokens(
            providers_ids, partner_id, is_validation=is_validation, **kwargs
        )

    @api.model
    def _payment_portal_user_is_public(self):
        """Return whether the current HTTP request is from the public (unauthenticated) user."""
        try:
            from odoo.http import request
        except ImportError:
            return False
        if not request:
            return False
        return request.env.user._is_public()


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    @api.model_create_multi
    def create(self, vals_list):
        if self.env['payment.token']._payment_portal_user_is_public():
            if any(
                vals.get('token_id') and vals.get('operation') == 'online_token'
                for vals in vals_list
            ):
                raise AccessError(_(
                    "Saved payment methods can only be used after signing in."
                ))
        return super().create(vals_list)
