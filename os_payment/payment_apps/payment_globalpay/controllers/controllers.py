# -*- coding: utf-8 -*-

import logging
import re
import uuid

from odoo import _, http
from odoo.addons.payment import utils as payment_utils
from odoo.exceptions import AccessError, ValidationError
from odoo.http import request


_logger = logging.getLogger(__name__)

_PAYMENT_REFERENCE_PATTERN = re.compile(r'^PMT_[A-Za-z0-9_-]+$')


class GlobalPayController(http.Controller):
    _hosted_fields_config_url = '/payment/globalpay/hosted_fields_config'
    _payment_url = '/payment/globalpay/payment'

    @staticmethod
    def _get_transaction(reference, provider_id=None):
        """Return the exact GlobalPay transaction addressed by the checkout."""
        domain = [
            ('reference', '=', reference),
            ('provider_code', '=', 'globalpay'),
        ]
        if provider_id:
            try:
                provider_id = int(provider_id)
            except (TypeError, ValueError) as error:
                raise ValidationError(_("The Global Payments provider is invalid.")) from error
            domain.append(('provider_id', '=', provider_id))
        tx_sudo = request.env['payment.transaction'].sudo().search(domain, limit=1)
        if not tx_sudo:
            raise ValidationError(_("The Global Payments transaction could not be found."))
        return tx_sudo

    @staticmethod
    def _check_transaction_access(tx_sudo, access_token):
        if not access_token or not payment_utils.check_access_token(
            access_token,
            tx_sudo.reference,
            tx_sudo.amount,
            tx_sudo.partner_id.id,
        ):
            raise AccessError(_("The Global Payments checkout session is invalid or expired."))

    # Odoo 18 JSON routes are consumed through the frontend `rpc` helper.
    @http.route(_hosted_fields_config_url, type='json', auth='public')
    def globalpay_hosted_fields_config(self, provider_id):
        """Return the browser-safe Hosted Fields configuration from Odoosync."""
        try:
            provider_id = int(provider_id)
        except (TypeError, ValueError) as error:
            raise ValidationError(_("The Global Payments provider is invalid.")) from error
        provider_sudo = request.env['payment.provider'].sudo().browse(provider_id).exists()
        if not provider_sudo or provider_sudo.code != 'globalpay':
            raise ValidationError(_("The Global Payments provider could not be found."))
        if provider_sudo.state == 'disabled':
            raise ValidationError(_("The Global Payments provider is disabled."))
        reference = f"HF-{uuid.uuid4().hex}"[:50]
        return provider_sudo._globalpay_get_hosted_fields_config(reference)

    @http.route(_payment_url, type='json', auth='public')
    def globalpay_make_payment(
        self,
        reference,
        access_token,
        payment_reference,
        expiry_month=None,
        expiry_year=None,
        card_last4=None,
        card_type=None,
    ):
        """Charge a Hosted Fields PMT and save it first when requested."""
        tx_sudo = self._get_transaction(reference)
        self._check_transaction_access(tx_sudo, access_token)

        # Serialize attempts for the same transaction. A browser double-click must
        # not consume two PMT references and create two charges.
        request.env.cr.execute(
            "SELECT id FROM payment_transaction WHERE id = %s FOR UPDATE",
            [tx_sudo.id],
        )
        tx_sudo.invalidate_recordset(['state', 'provider_reference'])
        if tx_sudo.provider_reference or tx_sudo.state == 'done':
            return {
                'ok': tx_sudo.state in ('done', 'pending'),
                'state': tx_sudo.state,
                'provider_reference': tx_sudo.provider_reference,
            }
        if tx_sudo.state in ('cancel', 'error'):
            raise ValidationError(_("This transaction can no longer accept a payment."))
        if (
            not payment_reference
            or len(payment_reference) > 200
            or not _PAYMENT_REFERENCE_PATTERN.fullmatch(payment_reference)
        ):
            raise ValidationError(_("Global Payments returned an invalid payment reference."))

        expiry_month = str(expiry_month or '').zfill(2)
        expiry_year = str(expiry_year or '')
        if len(expiry_year) == 4:
            expiry_year = expiry_year[-2:]
        valid_expiry = (
            expiry_month.isdigit()
            and 1 <= int(expiry_month) <= 12
            and len(expiry_year) == 2
            and expiry_year.isdigit()
        )
        card_last4 = str(card_last4 or '')
        if not re.fullmatch(r'\d{4}', card_last4):
            card_last4 = ''
        card_type = str(card_type or '')[:30]
        if not re.fullmatch(r'[A-Za-z0-9 _-]*', card_type):
            card_type = ''

        provider_sudo = tx_sudo.provider_id
        globalpay_reference = provider_sudo._globalpay_prepare_reference(
            tx_sudo.reference
        )
        country = (
           tx_sudo.company_id.country_id.code
        )
        if not country:
            raise ValidationError(_("A billing or company country is required for Global Payments."))
        if not provider_sudo.globalpay_transaction_account:
            raise ValidationError(_(
                "The Global Payments transaction-processing account is not configured."
            ))

        def convert_payment_method():
            conversion_payload = {'payment_method_id': payment_reference}
            if valid_expiry:
                conversion_payload.update({
                    'expiry_month': expiry_month,
                    'expiry_year': expiry_year,
                })
            reusable_payment_method = provider_sudo._globalpay_make_request(
                'convert_payment_method_to_reusable',
                payload=conversion_payload,
            )

            if (
                not isinstance(reusable_payment_method, dict)
                or reusable_payment_method.get('id') != payment_reference
                or reusable_payment_method.get('usage_mode') != 'MULTIPLE'
            ):
                raise ValidationError(_(
                    "Global Payments could not make this card reusable."
                ))
            card = reusable_payment_method.setdefault('card', {})
            if valid_expiry:
                card['expiry_month'] = card.get('expiry_month') or expiry_month
                card['expiry_year'] = card.get('expiry_year') or expiry_year
            if card_last4:
                card['masked_number_last4'] = (
                    card.get('masked_number_last4')
                    or f'XXXXXXXXXXXX{card_last4}'
                )
            if card_type:
                card['brand'] = card.get('brand') or card_type.upper()
            return reusable_payment_method

        if tx_sudo.operation == 'validation':
            if not valid_expiry:
                raise ValidationError(_(
                    "Global Payments did not return the card expiration date. "
                    "Please reload the page and enter the card again."
                ))
            verification_payload = {
                "account_name": provider_sudo.globalpay_transaction_account,
                "channel": "CNP",
                "currency": tx_sudo.currency_id.name,
                "reference": globalpay_reference,
                "country": country,
                "payment_method": {
                    "id": payment_reference,
                    "entry_mode": "ECOM",
                    "card": {
                        "expiry_month": expiry_month,
                        "expiry_year": expiry_year,
                    },
                },
            }
            verification_data = provider_sudo._globalpay_make_request(
                'payment_verification_request',
                payload=verification_payload,
            )
            if (
                not isinstance(verification_data, dict)
                or not verification_data.get('id')
                or verification_data.get('status') != 'VERIFIED'
            ):
                detail = (
                    verification_data.get('detail')
                    or verification_data.get('message')
                    if isinstance(verification_data, dict)
                    else None
                )
                raise ValidationError(
                    detail or _("Global Payments could not verify this payment method.")
                )
            # Convert only after Global Payments has successfully verified the
            # single-use PMT. The conversion endpoint expects a bodyless PATCH.
            reusable_payment_method = convert_payment_method()

            payment_method = reusable_payment_method
            card = payment_method.get("card", {})

            existing_token = request.env["payment.token"].sudo().search([
                ("provider_ref", "=", payment_method["id"]),
                ("provider_id", "=", provider_sudo.id),
            ], limit=1)

            if not existing_token:
                request.env["payment.token"].sudo().create({
                    "provider_id": provider_sudo.id,
                    "payment_method_id": tx_sudo.payment_method_id.id,
                    "partner_id": tx_sudo.partner_id.id,
                    "provider_ref": payment_method["id"],
                    "payment_details": card.get("masked_number_last4")[-4:],
                    "global_shopper_reference": payment_method["id"],
                    "globalpay_brand_reference": card.get("brand_reference"),
                })
            verification_data = {
                **verification_data,
                'globalpay_reusable_payment_method': reusable_payment_method,
            }
            tx_sudo.write({
                'provider_reference': verification_data['id'],
                'globalpay_reference': verification_data['id'],
            })
            tx_sudo._handle_notification_data('globalpay', verification_data)
            return {
                'ok': tx_sudo.state == 'done',
                'state': tx_sudo.state,
                'message': tx_sudo.state_message,
                'provider_reference': tx_sudo.provider_reference,
                'status': verification_data['status'],
            }

        payload = {
            "account_name": provider_sudo.globalpay_transaction_account,
            "type": "SALE",
            "channel": "CNP",
            "capture_mode": "AUTO",
            "amount": int(round(
                tx_sudo.amount * (10 ** tx_sudo.currency_id.decimal_places)
            )),
            "currency": tx_sudo.currency_id.name,
            "reference": globalpay_reference,
            "country": country,
            "payment_method": {
                "id": payment_reference,
                "entry_mode": "ECOM",
            },
        }
        if tx_sudo.tokenize:
            payload.update({
                "initiator": "PAYER",
                "stored_credential": {
                    "model": "UNSCHEDULED",
                    "sequence": "FIRST",
                },
            })

        response = provider_sudo._globalpay_make_request(
            'payment_transaction_request',
            payload=payload,
        )
        if not isinstance(response, dict):
            raise ValidationError(_("Global Payments returned an invalid transaction response."))
        if not response.get('id'):
            detail = response.get('detail') or response.get('message') or _(
                "The payment could not be completed."
            )
            raise ValidationError(detail)

        tx_sudo.write({
            'provider_reference': response['id'],
            'globalpay_reference': response['id'],
        })
        payment_data = dict(response)
        if tx_sudo.tokenize and response.get('status') in ('CAPTURED', 'FUNDED'):
            try:
                reusable_payment_method = convert_payment_method()
                payment_data['globalpay_reusable_payment_method'] = reusable_payment_method

                payment_method = reusable_payment_method
                card = payment_method.get("card", {})

                existing_token = request.env["payment.token"].sudo().search([
                    ("provider_ref", "=", payment_method["id"]),
                    ("provider_id", "=", provider_sudo.id),
                ], limit=1)

                if not existing_token:
                    request.env["payment.token"].sudo().create({
                        "provider_id": provider_sudo.id,
                        "payment_method_id": tx_sudo.payment_method_id.id,
                        "partner_id": tx_sudo.partner_id.id,
                        "provider_ref": payment_method["id"],
                        "payment_details": (
                                card.get("masked_number_last4", "")[-4:]
                                or card.get("masked_number", "")[-4:]
                        ),
                        "global_shopper_reference": payment_method["id"],
                        "globalpay_brand_reference": card.get("brand_reference"),
                    })
            except ValidationError:
                # The monetary transaction already succeeded. Never hide that
                # success or invite a second charge because card saving failed.
                tx_sudo.tokenize = False
                _logger.exception(
                    "Global Payments transaction %s succeeded, but its card could not be saved",
                    response['id'],
                )
        elif tx_sudo.tokenize:
            tx_sudo.tokenize = False
        tx_sudo._handle_notification_data('globalpay', payment_data)

        _logger.info(
            "Global Payments transaction %s processed with status %s",
            response['id'],
            response.get('status'),
        )
        return {
            'ok': tx_sudo.state in ('done', 'pending'),
            'state': tx_sudo.state,
            'message': tx_sudo.state_message,
            'provider_reference': tx_sudo.provider_reference,
            'status': response.get('status'),
        }
