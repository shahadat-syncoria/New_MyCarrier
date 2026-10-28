# -*- coding: utf-8 -*-
# © Syncoria Inc.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

# Module: payment_globalpay
# This module contains functionality for interacting with the GlobalPay API,


import logging
import json
import pprint

import requests

from odoo import fields, models
from odoo.addons.payment import utils as payment_utils
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    globalpay_reference = fields.Char('globalpay Reference')
    globalpay_merchant_transaction_id = fields.Char('globalpay Merchant Transaction Id')
    globalpay_merchant_id = fields.Char('globalpay Merchant Id')
    click2pay_refund_status = fields.Char()
    demo_success_failed = fields.Selection([('CAPTURED', 'Success'), ('DECLINED', 'Failed')])

    # groups = "base.group_no_one"

    # === BUSINESS METHODS ===#
    def _get_specific_processing_values(self, processing_values):
        """ Override of payment to return globalpay-specific processing values.

        Note: self.ensure_one() from `_get_processing_values`

        :param dict processing_values: The generic processing values of the transaction
        :return: The dict of provider-specific processing values
        :rtype: dict
        """
        res = super()._get_specific_processing_values(processing_values)
        if self.provider_code != 'globalpay':
            return res
        return {
            **res,
            # Kept for compatibility with existing callers. Global Payments is charged
            # in the Odoo transaction currency; checkout must not silently force CAD.
            'converted_amount': self.amount,
            'access_token': payment_utils.generate_access_token(
                processing_values['reference'],
                self.amount,
                processing_values['partner_id']
            )
        }

    def _get_specific_rendering_values(self, processing_values):
        """ Override of payment to return globalpay-specific rendering values.

        Note: self.ensure_one() from `_get_processing_values`

        :param dict processing_values: The generic and specific processing values of the transaction
        :return: The dict of provider-specific processing values
        :rtype: dict
        """
        res = super()._get_specific_rendering_values(processing_values)
        # print("Processing Values--", processing_values)
        if self.provider_code != 'globalpay':
            return res
        return

    def _get_tx_from_notification_data(self, provider_code, notification_data):
        """ Override of payment to find the transaction based on globalpay data.

        :param str provider_code: The code of the provider that handled the transaction
        :param dict notification_data: The notification data sent by the provider
        :return: The transaction if found
        :rtype: recordset of `payment.transaction`
        :raise: ValidationError if inconsistent data were received
        :raise: ValidationError if the data match no transaction
        """
        tx = super()._get_tx_from_notification_data(provider_code, notification_data)
        if provider_code != 'globalpay' or len(tx) == 1:
            return tx
        reference = (
            notification_data.get('id')
            or notification_data.get('resource', {}).get('id')
        )
        if not reference:
            raise ValidationError("globalpay: " + ("Missing transaction reference."))
        tx = self.search([('globalpay_reference', '=', reference),
                          ('provider_code', '=', 'globalpay')])
        if not tx:
            raise ValidationError(
                "globalpay: " + f"Invalid transaction reference {reference}."
            )
        return tx

    def _extract_amount_data(self, payment_data):
        """Override of `payment` to extract the amount and currency from the payment data."""
        if self.provider_code != 'globalpay':
            return super()._extract_amount_data(payment_data)


        return {
            'amount': self.amount,
            'currency_code': self.currency_id.name,
        }

    def _process_notification_data(self, notification_data):
        """ Override of payment to process the transaction based on globalpay data.

        Note: self.ensure_one()

        :param dict notification_data: The notification data sent by the provider
        :return: None
        :raise: ValidationError if inconsistent data were received
        """
        super()._process_notification_data(notification_data)
        if self.provider_code != 'globalpay':
            return
        _logger.info("notification_data_global_pay %s", notification_data)
        event_code = str(
            notification_data.get('status')
            or notification_data.get('transaction_status')
            or notification_data.get('result')
            or ''
        ).upper()
        _logger.info('devAp globalpay event_code %s', event_code)

        if event_code:
            if event_code in {
                'CAPTURED', 'FUNDED', 'VERIFIED', 'SUCCESS', 'SUCCEEDED',
                'APPROVED', 'PAID', 'SETTLED', 'COMPLETED',
            }:
                self._set_done(state_message="Transaction captured")
            elif event_code in {
                'FOR_REVIEW', 'INITIATED', 'PENDING', 'PREAUTHORIZED',
                'AUTHORIZED', 'AUTHORISED', 'PROCESSING',
            }:
                self._set_pending(state_message="Transaction pending")
            elif event_code == 'REVERSED':
                # Set the transaction state to error
                self._set_error(state_message="Transaction reversed")
            elif event_code in ['DECLINED', 'FAILED', 'REJECTED', 'CANCELED', 'CANCELLED']:
                # Set the transaction state to canceled
                self._set_canceled(state_message="Transaction canceled")
            else:
                # Handle other status codes if needed
                self._set_error(state_message="Unhandled transaction status")
        else:
            self._set_error(state_message="Unhandled transaction status")
            _logger.info(
                "received data with invalid transaction status (%s) for transaction with reference %s",
                notification_data.get('status'), self.reference,
            )

    def _get_post_processing_values(self):
        data = super()._get_post_processing_values()
        if self.provider_code != 'globalpay':
            return data
        return data

    def _handel_refund_status(self, status, response_content=None):
        detail = (response_content or {}).get('detailed_error_description') or ''
        prefix = f"Globalpay Response: {detail} — " if detail else ''
        if status in ['INITIATED', 'PREAUTHORIZED']:
            self._set_pending(state_message=prefix + "Payment created but pending")
        elif status == 'REVERSED':
            self._set_canceled(state_message=prefix + "Payment canceled")
        elif status in ['FUNDED', 'CAPTURED']:
            self._set_done(state_message="Payment settled")
        elif status in ['DECLINED', 'REJECTED']:
            self._set_canceled(state_message=prefix + "Payment canceled")
        else:
            self._set_error(state_message=prefix + f"Payment {status.lower()}")
        return

    def _send_refund_request(self, amount_to_refund=None):
        """ Override of payment to send a refund request to globalpay.

        Note: self.ensure_one()

        :param float amount_to_refund: The amount to refund
        :return: The refund transaction created to process the refund request.
        :rtype: recordset of `payment.transaction`
        """
        if self.provider_code != 'globalpay':
            return super()._send_refund_request(amount_to_refund=amount_to_refund)

        # Let core create the child refund tx first.
        refund_tx = super()._send_refund_request(amount_to_refund=amount_to_refund)

        payload = {
            "payment_request_id": self.provider_reference or self.globalpay_reference,
            "amount": abs(int(round(
                (amount_to_refund or self.amount) * 10 ** self.currency_id.decimal_places
            ))),
        }
        response_content = None
        try:
            response_content = self.provider_id._globalpay_make_request(
                'refund_payment_request', payload=payload
            )
            _logger.info(
                "refund request response for transaction with reference %s:\n%s",
                self.reference, pprint.pformat(response_content)
            )
            if response_content:
                refund_tx.globalpay_reference = response_content.get('id')
                refund_tx.provider_reference = response_content.get('id')
                refund_tx._handel_refund_status(
                    response_content.get('status') or 'FAILED', response_content
                )
            else:
                refund_tx._set_error("Empty response from GlobalPay")
        except requests.exceptions.RequestException as e:
            _logger.exception("Error with globalpay service: %s", e)
            raise ValidationError("GlobalPay: Could not establish the connection to the API.")
        except Exception as e:
            _logger.error("Error during refund: %s", e)
            raise ValidationError("Globalpay: " + str(e))

        return refund_tx

    def action_globalpay_void(self):
        """Void/reverse a GlobalPay captured (done) transaction via GP's reverse endpoint."""
        self.ensure_one()
        data = {
            "transaction_request_id": self.provider_reference or self.globalpay_reference
        }
        response_content = self.provider_id._globalpay_make_request(
            endpoint="cancel_payment_request",
            payload=data,
        )
        _logger.info("GlobalPay void response for %s:\n%s", self.reference, pprint.pformat(response_content))

        status = (response_content.get('status') or '').upper()
        msg = (response_content.get('detailed_error_description')
               or "Transaction voided (reversed by GlobalPay)")
        if status == 'REVERSED':
            self._set_canceled(state_message=msg, extra_allowed_states=('done',))
        else:
            raise ValidationError(
                "Globalpay Response: " + (response_content.get("detailed_error_description")
                or f"Void failed — GlobalPay status: {status or 'unknown'}")
            )

    def _send_void_request(self, amount_to_void=None):
        """ Override of payment to send a void request to globalpay.

        Note: self.ensure_one(). self = the authorized parent tx.

        :param float amount_to_void: The amount to be voided.
        :return: The child transaction created for a partial void, if any.
        :rtype: payment.transaction
        """
        if self.provider_code != 'globalpay':
            return super()._send_void_request(amount_to_void=amount_to_void)

        # For partial voids, core creates a child transaction.
        child_tx = super()._send_void_request(amount_to_void=amount_to_void)

        data = {
            "transaction_request_id": self.provider_reference or self.globalpay_reference
        }
        response_content = self.provider_id._globalpay_make_request(
            endpoint="cancel_payment_request",
            payload=data,
        )
        _logger.info("void request response:\n%s", pprint.pformat(response_content))

        status = (response_content.get('status') or '').upper()
        msg = (response_content.get('detailed_error_description')
               or "Transaction voided (reversed by GlobalPay)")
        if status == 'REVERSED':
            self._set_canceled(state_message=msg)
        else:
            raise ValidationError(
                "Globalpay Response: " + (response_content.get("detailed_error_description")
                or f"Void failed — GlobalPay status: {status or 'unknown'}")
            )
        return child_tx

    def update_payment_refund_status(self):

        # last_payment_request_id = self.globalpay_reference

        for refund in self.child_transaction_ids or self:
            refund_id = refund.globalpay_reference
            url = f"/ucp/transactions/{refund_id}"

            payload = {
                "transaction_request_id":refund_id
            }
            try:
                response_content = refund.provider_id._globalpay_make_request("get_transaction_request_status",payload=payload)
                _logger.info(
                    "refund request response for transaction with reference %s:\n%s",
                    refund.reference, pprint.pformat(response_content)
                )
                if response_content:
                    refund.click2pay_refund_status = response_content.get('status')
                else:
                    _logger.exception("Error wit globalpay service %s", json.dumps(response_content))
                if refund.demo_success_failed and refund.provider_id.state in ['test']:
                    refund._handel_refund_status(refund.demo_success_failed)
                else:
                    refund._handel_refund_status(refund.click2pay_refund_status or 'FAILED')

            except requests.exceptions.RequestException as e:
                _logger.exception("Error wit globalpay service %s", e)
                raise ValidationError(
                    "Detail: " + response_content.get('detail', ("Could not establish the connection to the API.")))
            except Exception as e:
                _logger.error("error during the payment: %s", e)
                raise ValidationError("Globalpay: " + str(e))

        return

    def sync_refund(self):
        transictions = self.env['payment.transaction'].sudo().search(
            [('provider_code', '=', 'globalpay'), ('child_transaction_ids', '!=', False)])
        for tranc in transictions:
            tranc.update_payment_refund_status()

    def _extract_token_values(self, payment_data):
        """Extract Odoo token values from the reusable Global Payments PMT."""
        if self.provider_code != 'globalpay':
            return super()._extract_token_values(payment_data)

        payment_method = payment_data.get('globalpay_reusable_payment_method') or {}
        payment_method_id = payment_method.get('id')
        if not payment_method_id or payment_method.get('usage_mode') != 'MULTIPLE':
            raise ValidationError(
                "GlobalPay: The reusable payment method response is missing or invalid."
            )

        card = payment_method.get('card') or {}
        masked_number = str(
            card.get('masked_number_last4')
            or card.get('masked_number')
            or ''
        )
        last4 = ''.join(character for character in masked_number if character.isdigit())[-4:]
        brand = card.get('brand') or card.get('brand_reference')
        transaction_card = (payment_data.get('payment_method') or {}).get('card') or {}
        return {
            'provider_ref': payment_method_id,
            # Keep the legacy field populated for previously written integrations.
            'global_shopper_reference': payment_method_id,
            'globalpay_brand_reference': transaction_card.get('brand_reference'),
            'payment_details': last4 or str(brand or 'Saved card'),
        }

    def _send_payment_request(self):
        """Charge a reusable Global Payments PMT stored in an Odoo token."""
        if self.provider_code != 'globalpay':
            return super()._send_payment_request()

        if not self.token_id:
            raise UserError("globalpay: " + ("The transaction is not linked to a token."))

        payment_method_id = (
            self.token_id.provider_ref
            or self.token_id.global_shopper_reference
        )
        if not payment_method_id:
            raise UserError("globalpay: " + ("The saved card has no payment method reference."))
        if not self.company_id.country_id.code:
            raise ValidationError(
                "GlobalPay: A company country is required to process the payment."
            )
        if not self.provider_id.globalpay_transaction_account:
            raise ValidationError(
                "GlobalPay: The transaction-processing account is not configured."
            )

        is_merchant_initiated = self.operation == 'offline'
        if is_merchant_initiated and not self.token_id.globalpay_brand_reference:
            raise ValidationError(
                "GlobalPay: This saved card cannot be used for a merchant-initiated payment "
                "because its brand reference is missing."
            )

        payment_method = {
            "id": payment_method_id,
            "entry_mode": "ECOM",
        }
        if is_merchant_initiated:
            payment_method["card"] = {
                "brand_reference": self.token_id.globalpay_brand_reference,
            }

        data = {
            "account_name": self.provider_id.globalpay_transaction_account,
            "type": "SALE",
            "channel": "CNP",
            "capture_mode": "AUTO",
            "amount": int(round(
                self.amount * (10 ** self.currency_id.decimal_places)
            )),
            "currency": self.currency_id.name,
            "reference": self.provider_id._globalpay_prepare_reference(self.reference),
            "country": self.company_id.country_id.code,
            "initiator": "MERCHANT" if is_merchant_initiated else "PAYER",
            "stored_credential": {
                "model": "UNSCHEDULED",
                "sequence": "SUBSEQUENT",
            },
            "payment_method": payment_method,
        }

        response = self.provider_id._globalpay_make_request(
            'payment_transaction_request',
            payload=data,
        )
        if not isinstance(response, dict) or not response.get('id'):
            detail = (
                response.get('detail') or response.get('message')
                if isinstance(response, dict)
                else None
            )
            raise ValidationError(
                detail or "GlobalPay: The payment could not be completed."
            )

        self.write({
            'provider_reference': response['id'],
            'globalpay_reference': response['id'],
        })
        self._handle_notification_data('globalpay', response)
