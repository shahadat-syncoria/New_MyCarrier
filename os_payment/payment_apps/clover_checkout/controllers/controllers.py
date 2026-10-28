# -*- coding: utf-8 -*-
from odoo import http
import base64
import binascii
import hashlib
import hmac
import logging
import pprint
import re
from werkzeug import urls
from werkzeug.exceptions import Forbidden

from odoo import _, http
from odoo.exceptions import ValidationError
from odoo.http import request, Response
from odoo.addons.payment.controllers.portal import PaymentPortal

import requests
import json
import time
from odoo.addons.payment import utils as payment_utils

_logger = logging.getLogger(__name__)


class CloverCheckoutController(http.Controller):
    _payment_url = '/payment/clovercheckout/payment'

    @staticmethod
    def _extract_clover_error_message(payload, fallback=None):
        if isinstance(payload, str):
            return payload or fallback
        if isinstance(payload, dict):
            if payload.get('errors_message'):
                return payload.get('errors_message')
            error = payload.get('error')
            if isinstance(error, str):
                return error or fallback
            if isinstance(error, dict):
                return error.get('message') or error.get('detail') or fallback
            return payload.get('message') or payload.get('detail') or fallback
        return fallback

    @http.route('/payment/clovercheckout/get_provider_info', type='json', auth='public')
    def clover_checkout_get_provider_info(self, provider_id):
        """ Return public information on the provider.

        :param int provider_id: The provider handling the transaction, as a `payment.provider` id
        :return: Information on the provider, namely: the state, payment method type, login ID, and
                 public client key
        :rtype: dict
        """
        provider_sudo = request.env['payment.provider'].sudo().browse(provider_id).exists()
        return {
            'state': provider_sudo.state,
            # The public API key solely used to identify the seller account with Authorize.Net
            # 'clover_private_key': provider_sudo.clover_private_key,
            # The public client key solely used to identify requests from the Accept.js suite
            'clover_public_key': provider_sudo.clover_public_api_key,
            # 'clover_merchant_id': provider_sudo.clover_merchant_id
        }

    @staticmethod
    def _clover_checkout_tx_by_reference(reference):
        """ Return the (sudo) transaction for ``reference`` or an empty recordset. """
        if not reference:
            return request.env['payment.transaction'].sudo()
        return request.env['payment.transaction'].sudo().search(
            [('reference', '=', reference), ('provider_code', '=', 'clover_checkout')], limit=1)

    @http.route('/payment/clovercheckout/store_payment_method', type='json', auth='public', csrf=False,
                methods=['POST'])
    def store_payment_method(self, **params):
        reference = params.get('reference')
        tx_sudo = self._clover_checkout_tx_by_reference(reference)
        try:
            # Extract parameters from the request
            usage_mode = params.get('usage_mode', 'SINGLE')  # Default to SINGLE if not provided
            card_number = params.get('card_number')
            expiry_month = params.get('expiry_month')
            expiry_year = params.get('expiry_year')
            cvv = params.get('cvv')
            accessToken = params.get('token')
            partner = request.env['res.partner'].sudo().browse(params.get('partner_id'))
            # window_location = params.get('window_location')

            payload = {
                "ecomind": "ecom",
                "shipping": {
                    "address": {
                        "city": partner.city,
                        "country": partner.country_id.code,
                        "line1": partner.street,
                        "postal_code": partner.zip,
                        "state": partner.state_id.name
                    }
                },
                "email": partner.email,
                "name": partner.name,
                "source": params.get('token')
            }
            _logger.info("payload %s", payload)
            payment_provider = request.env['payment.provider'].sudo().search([('code', '=', 'clover_checkout')],
                                                                             limit=1)
            # tx_sudo = request.env['payment.transaction'].sudo().search([('reference', '=', params.get('reference'))])

            if not params.get('save_card'):
                return {
                    'skipped': True,
                    'reason': 'tokenization_disabled',
                }

            # Make the request to Global Payments (you may need to adjust the endpoint)
            if payment_provider:
                if tx_sudo:
                    tx_sudo._clover_checkout_append_log('store_pm_request', payload)
                _t0 = time.monotonic()
                # response = payment_provider._globalpay_make_request('ucp/payment-methods', payload=payload)
                response = payment_provider._clover_checkout_make_request("create_customer", payload=payload,
                                                                          )
                duration = time.monotonic() - _t0
                _logger.info("devApp: response 1 %s", response)
                has_explicit_error = (
                    not isinstance(response, dict)
                    or bool(response.get('error'))
                    or not response.get('id')
                ) if isinstance(response, dict) else True
                error_message = self._extract_clover_error_message(response)
                if (
                    has_explicit_error
                ):
                    if tx_sudo:
                        tx_sudo._clover_checkout_append_log_isolated(
                            'store_pm_error', response, duration=duration)
                    raise ValidationError(
                        error_message or _("Failed to create Clover source token.")
                    )
                if tx_sudo:
                    tx_sudo._clover_checkout_append_log(
                        'store_pm_response', response, duration=duration, note='ok')
                # if window_location == '/my/payment_method':
                #     tx_sudo._clover_checkout_tokenize_from_notification_data(response)
                # Process the response and return it
                return response

        except ValidationError:
            raise
        except Exception as e:
            _logger.exception(
                "Error processing Clover payment method for reference %s: %s",
                reference,
                str(e),
            )
            if tx_sudo:
                tx_sudo._clover_checkout_append_log_isolated(
                    'store_pm_error', {'error': str(e)}, note='exception')
            raise ValidationError(str(e))

    @http.route('/payment/clovercheckout/save_payment_token', type='json', auth='public')
    def save_payment_token(self, **params):
        try:
            card = params.get('token_id')
            token = request.env['payment.token'].sudo().search([('clover_checkout_id', '=', card)])
            tx_sudo = request.env['payment.transaction'].sudo().search([('reference', '=', params.get('reference'))])
            finalize = params.get('finalize', True)
            if not token :
                token = request.env['payment.token'].create({
                    'provider_id': params.get('provider_id'),
                    'payment_method_id': params.get('payment_method_id'),
                    'payment_details': card[-4:],
                    'partner_id': params.get('partner_id'),
                    'provider_ref': params.get('token_id'),
                    'clover_checkout_id': params.get('token_id'),
                    'clover_customer_id': params.get('clover_checkout_id')
                    # 'payment_method_id': self.payment_method_id.id,
                    # 'verified': True,  # The payment is authorized, so the payment method is valid
                })
            tx_sudo.write({
                    'provider_reference': params.get('token_id'),
                    'clover_checkout_reference': params.get('token_id'),
                })
            if tx_sudo:
                tx_sudo._clover_checkout_append_log(
                    'save_token', {'token_id': '***', 'finalize': finalize},
                    note='token %s' % (token.id if token else False))
            if finalize:
                tx_sudo._set_done(state_message="Transaction captured")

            return {
                'saved': True,
                'finalized': finalize,
                'token_id': token.id if token else False,
            }


        except Exception as e:
            # Handle exceptions, log the error, and return an appropriate response
            _logger.exception("Clover Checkout: save_payment_token failed for %s", params.get('reference'))
            tx_err = self._clover_checkout_tx_by_reference(params.get('reference'))
            if tx_err:
                tx_err._clover_checkout_append_log_isolated(
                    'save_token_error', {'error': str(e)}, note='exception')
            error_message = f"Error saving payment method: {str(e)}"
            return Response(error_message, status=500, content_type='text/plain')

    @http.route(_payment_url, type='json', auth='public')
    def clover_checkout_make_payment(self, **params):
        # Make the payment request to clover_checkout
        provider_sudo = request.env['payment.provider'].sudo().search([('code', '=', 'clover_checkout')], limit=1)

        reference = params.get('reference')
        tx_sudo = self._clover_checkout_tx_by_reference(reference)
        currency = request.env['res.currency'].sudo().browse(params.get('currency_id'))
        partner = request.env['res.partner'].sudo().browse(params.get('partner_id'))

        data = {
            "ecomind": "ecom",
            "metadata": {
                "existingDebtIndicator": False
            },

            # "amount": 1,
            "amount": int(float(params.get('amount')) * 10 ** currency.decimal_places),
            "currency": currency.name,
            # "currency": 'USD',
            "source": params.get('access_token')
        }

        response = None
        if tx_sudo:
            tx_sudo._clover_checkout_append_log('charge_request', data)
        _t0 = time.monotonic()
        try:
            response = provider_sudo._clover_checkout_make_request("charge_payment", payload=data)
            duration = time.monotonic() - _t0

            # Handle the payment request response
            _logger.info("payment request response: %s", pprint.pformat(response))

            # if the merchantOrderId already exists in clover_checkout and you try to pay again, the createInvoice return
            # So her we check, if he response is string thne
            if isinstance(response, str):
                if tx_sudo:
                    tx_sudo._clover_checkout_append_log_isolated(
                        'charge_error', response, duration=duration)
                    tx_sudo._set_error(response)
                raise ValidationError(
                    "clover_checkout: " + _("Create Invoice response %(ref)s.", ref=response)
                )
            if tx_sudo:
                write_vals = {'clover_data_id': params.get('clover_data_id')}
                if isinstance(response, dict) and response.get('id'):
                    write_vals['provider_reference'] = response.get('id')
                    write_vals['clover_checkout_reference'] = response.get('ref_num')
                tx_sudo.write(write_vals)
                tx_sudo._handle_notification_data(
                    'clover_checkout', dict(response, __clover_duration=duration),
                )
            return json.dumps(response)
        except ValidationError:
            raise
        except requests.exceptions.RequestException:
            duration = time.monotonic() - _t0
            _logger.exception("Error with clover_checkout service %s", json.dumps(response, default=str))
            if tx_sudo:
                tx_sudo._clover_checkout_append_log_isolated(
                    'charge_error',
                    response if response is not None else {'error': 'connection_error'},
                    duration=duration, note='RequestException',
                )
            detail = response.get('detail') if isinstance(response, dict) else None
            raise ValidationError(
                "Detail: " + (detail or _("Could not establish the connection to the API.")))
        except Exception as e:
            duration = time.monotonic() - _t0
            _logger.error("error during the payment: %s", str(e))
            if tx_sudo:
                tx_sudo._clover_checkout_append_log_isolated(
                    'charge_error',
                    response if isinstance(response, dict) else {'error': str(e)},
                    duration=duration, note='exception: %s' % e,
                )
            raise ValidationError(str(e))

    @http.route('/payment/clovercheckout/log_client_error', type='json', auth='public', csrf=False)
    def clover_checkout_log_client_error(self, reference=None, stage=None, error=None,
                                         client_duration_ms=None, **kw):
        """ Persist a browser-side Clover Checkout failure/timing onto its transaction.

        Called fire-and-forget from the payment form's error/timing branches so that
        failures which never reach the server (SDK tokenization errors, aborted
        requests) are still visible on the transaction.
        """
        tx_sudo = self._clover_checkout_tx_by_reference(reference)
        if not tx_sudo:
            return {'logged': False, 'reason': 'tx_not_found'}
        payload = {'stage': stage, 'error': error}
        duration = None
        try:
            if client_duration_ms is not None:
                duration = float(client_duration_ms) / 1000.0
        except (TypeError, ValueError):
            duration = None
        tx_sudo._clover_checkout_append_log(
            'client_error' if error else 'client_timing', payload,
            duration=duration, note='browser',
        )
        return {'logged': True}
class CloverCheckoutTokenController(PaymentPortal):


    @http.route('/payment/archive_token', type='json', auth='user')
    def archive_token(self, token_id):
        """ Check that a user has write access on a token and archive the token if so.

        :param int token_id: The token to archive, as a `payment.token` id
        :return: None
        """
        token_obj = request.env['payment.token'].sudo().browse(token_id)
        provider_sudo = request.env['payment.provider'].sudo().search([('code', '=', 'clover_checkout')], limit=1)
        try:
            if token_obj.provider_id.code == 'clover_checkout':
                payload={
                    "clover_checkout_id": token_obj.clover_checkout_id,
                    "clover_customer_id": token_obj.clover_customer_id,
                }
                response = provider_sudo._clover_checkout_make_request("delete_customer",  payload=payload)
                # srm = AppPayment(service_name='bambora_checkout', service_type='profile_delete', service_key=token_obj.provider_id.token)
                # srm.data = payload
                # response = srm.payment_process(company_id=token_obj.provider_id.company_id.id)
                #
                # if  response.get('error') != None or 'errors_message'  in response:
                #     error = response.get('error') if 'error' in response else response.get("errors_message")
                #     raise Exception(f"{error}")

                # else:
                if response.get('deleted'):
                    _logger.info("Deleted Information %s", response)
                    pass
                else:
                    raise Exception(f"{response.get('message')}")

        except Exception as e:
            raise ValidationError(f"{e}")

        return super().archive_token(token_id)
