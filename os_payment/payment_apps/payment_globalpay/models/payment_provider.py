# -*- coding: utf-8 -*-
# © Syncoria Inc.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

# Module: payment_globalpay
# This module contains functionality for interacting with the GlobalPay API,

import logging
import hashlib
import re

import requests

from odoo import _, fields, models
from odoo.exceptions import ValidationError, UserError
from odoo.addons.odoosync_base.utils.app_payment import AppPayment


_logger = logging.getLogger(__name__)


class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    code = fields.Selection(selection_add=[('globalpay', "GlobalPay")], ondelete={'globalpay': 'set default'})
    globalpay_api_version = fields.Char(
        string="API Version",
        default="2021-03-22",
        groups='base.group_system',
    )
    globalpay_tokenization_account = fields.Char(
        string="Tokenization Account",
        groups='base.group_system',
        help="Required when the Global Payments merchant has more than one tokenization account.",
    )
    globalpay_transaction_account = fields.Char(
        string="Transaction Processing Account",
        default="transaction_processing",
        groups='base.group_system',
    )

    #=== COMPUTE METHODS ===#

    def _compute_feature_support_fields(self):
        """ Override of `payment` to enable additional features. """
        super()._compute_feature_support_fields()
        self.filtered(lambda p: p.code == 'globalpay').update({
            'support_express_checkout': False,
            'support_manual_capture': False,
            'support_refund': 'partial',
            'support_tokenization': True,
        })

    def _globalpay_get_hosted_fields_config(self, reference):
        """Request a browser-safe Hosted Fields access token from Odoosync."""
        self.ensure_one()
        if not self.token:
            raise ValidationError(_(
                "An Odoosync service token is required before using Global Payments."
            ))
        response = self._globalpay_make_request(
            'hosted_fields_access_token',
            payload={},
        )
        access_token = response.get("access_token")
        if not access_token:
            raise ValidationError(_(
                "Odoosync returned an invalid Global Payments access-token response."
            ))

        api_version = (
            response.get("api_version")
            or self.globalpay_api_version
            or "2021-03-22"
        )
        config = {
            "access_token": access_token,
            "api_version": api_version,
            "environment": response.get("environment") or (
                "production" if self.state == "enabled" else "sandbox"
            ),
            "reference": reference,
        }
        account_name = response.get("account_name") or self.globalpay_tokenization_account
        if account_name:
            config["account_name"] = account_name
        return config

    def _globalpay_prepare_reference(self, reference):
        """Return an API-safe, stable Global Payments reference."""
        self.ensure_one()
        original_reference = str(reference or '')
        reference = re.sub(r'[^A-Za-z0-9_-]+', '-', original_reference).strip('-_')
        if not reference:
            reference = 'PAYMENT'
        if len(reference) < 8:
            reference = f'ODOO-{reference}'
        if len(reference) > 50:
            digest = hashlib.sha256(original_reference.encode()).hexdigest()[:8]
            reference = f'{reference[:41]}-{digest}'
        return reference

    def _globalpay_make_request(self, endpoint, payload=None, method='POST', token=None):
        """ Make a request to globalpay API at the specified endpoint.

        :param str endpoint: The endpoint to be reached by the request.
        :param dict payload: The payload of the request.
        :param str method: The HTTP method of the request.
        :param str token: The access token to be used for authorization.
        :return: The JSON-formatted content of the response.
        :rtype: dict
        :raise ValidationError: If an HTTP error occurs.
        """
        self.ensure_one()
        try:
            srm = AppPayment(service_name='global_payment', service_type=endpoint, service_key=self.token)
            srm.data = payload
            response = srm.payment_process(company_id=self.company_id.id)
            if not isinstance(response, dict):
                raise UserError(_("The Global Payments service returned an invalid response."))
            if response.get('error') or response.get('errors_message'):
                error = response.get('error') if 'error' in response else response.get("errors_message")
                raise UserError(error)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            _logger.exception("Unable to reach the Global Payments service")
            raise ValidationError(
                _("GlobalPay: Could not establish the connection to the API.")
            )
        except Exception as error:
            raise ValidationError(_("GlobalPay: %(error)s", error=str(error))) from error
        return response


    def _should_build_inline_form(self, is_validation=False):
        """ Return whether the inline payment form should be instantiated.

        For a provider to handle both direct payments and payments with redirection, it must
        override this method and return whether the inline payment form should be instantiated (i.e.
        if the payment should be direct) based on the operation (online payment or validation).

        :param bool is_validation: Whether the operation is a validation.
        :return: Whether the inline form should be instantiated.
        :rtype: bool
        """
        if self.code != 'globalpay':
            return super()._should_build_inline_form(is_validation=is_validation)
        return True
