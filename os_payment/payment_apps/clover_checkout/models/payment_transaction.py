# -*- coding: utf-8 -*-

import logging
import re

from datetime import datetime

from werkzeug import urls

from odoo import _, api, models, fields
from odoo.exceptions import ValidationError, UserError
from odoo.tools.float_utils import float_compare
from odoo.addons.payment import utils as payment_utils
import pprint
import json
from odoo.addons.payment import utils as payment_utils
import requests

# from odoo.odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Keys whose values must never be written to the persisted Clover log.
CLOVER_LOG_SENSITIVE_KEYS = ('source', 'access_token', 'token', 'token_response', 'payment_ref')
# Warn in the server log when a Clover round-trip takes longer than this (seconds).
CLOVER_SLOW_REQUEST_THRESHOLD = 10.0
# Hard cap on the size of the persisted log so a runaway loop can't bloat a row.
CLOVER_LOG_MAX_CHARS = 20000


class CloverPaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    clover_checkout_reference = fields.Char('clover Checkout Reference')
    clover_checkout_merchant_transaction_id = fields.Char('Clover Checkout Merchant Transaction Id')
    clover_checkout_merchant_id = fields.Char('Clover Checkout Merchant Id')
    clover_checkout_refund_status = fields.Char()
    clover_checkout_id = fields.Char()
    clover_data_id = fields.Char()

    # --- Clover Checkout diagnostic logging (card decline / slow payment analysis) ---
    clover_checkout_log = fields.Text(
        string='Clover Checkout Log', readonly=True, copy=False,
        help="Append-only trail of every Clover Checkout request/response/error for this transaction.")
    clover_last_status = fields.Selection(
        [('success', 'Success'), ('error', 'Error')],
        string='Clover Last Status', readonly=True, copy=False,
        help="Outcome of the most recent Clover Checkout API call for this "
             "transaction (independent of the overall transaction state).")
    clover_last_error_code = fields.Char(
        string='Clover Last Error Code', readonly=True, copy=False,
        help="Last Clover error 'code' (e.g. card_declined).")
    clover_last_decline_code = fields.Char(
        string='Clover Last Decline Code', readonly=True, copy=False,
        help="Last Clover 'declineCode' (e.g. issuer_declined), or the error 'type' "
             "(e.g. card_error) when Clover rejected before reaching the issuer.")
    clover_last_error_message = fields.Char(
        string='Clover Last Error Message', readonly=True, copy=False)
    clover_last_charge_id = fields.Char(
        string='Clover Last Charge Id', readonly=True, copy=False)
    clover_request_duration = fields.Float(
        string='Clover API Duration (s)', readonly=True, copy=False,
        help="Server-side round-trip time of the last Clover charge request.")

    # ------------------------------------------------------------------
    # Diagnostic logging helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _clover_checkout_redact(payload):
        """ Return a copy of ``payload`` safe to persist (card sources stripped). """
        if not isinstance(payload, dict):
            return payload
        safe = {}
        for key, value in payload.items():
            if key == '__clover_duration':
                continue
            if key in CLOVER_LOG_SENSITIVE_KEYS:
                safe[key] = '***'
            elif isinstance(value, dict):
                safe[key] = CloverPaymentTransaction._clover_checkout_redact(value)
            else:
                safe[key] = value
        return safe

    @staticmethod
    def _clover_checkout_extract_error(payload):
        """ Pull the useful bits out of a Clover error payload.

        Handles the shapes seen in production, e.g.::

            {'message': '402 Payment Required',
             'error': {'code': 'card_declined', 'declineCode': 'issuer_declined',
                       'charge': 'JMKH4QAQYK58A', 'message': 'NOT ENTITLED'}}

        and token-verification failures that carry no declineCode/charge::

            {'message': '402 Payment Required',
             'error': {'type': 'card_error', 'code': 'card_declined',
                       'message': 'Token verification failed for token clv_XXXX'}}
        -> decline_code falls back to 'card_error', charge_id to 'clv_XXXX'.

        :return: dict with keys code, decline_code, charge_id, message, http_message
        """
        result = {
            'code': None, 'decline_code': None, 'charge_id': None,
            'message': None, 'http_message': None,
        }
        if not isinstance(payload, dict):
            if isinstance(payload, str):
                result['message'] = payload
            return result
        result['http_message'] = payload.get('message')
        error = payload.get('error')
        # The browser 'client_error' payload nests the real error dict as a JSON
        # string under 'error'; unwrap it so the fields still get parsed.
        if isinstance(error, str):
            stripped = error.strip()
            if stripped[:1] in ('{', '[') or stripped.startswith('"'):
                try:
                    error = json.loads(stripped)
                except (ValueError, TypeError):
                    pass
        if isinstance(error, dict):
            result['code'] = error.get('code')
            # Prefer the real issuer declineCode; fall back to the error 'type'
            # (e.g. card_error) when Clover rejected before reaching the issuer.
            result['decline_code'] = (
                error.get('declineCode') or error.get('decline_code') or error.get('type')
            )
            result['charge_id'] = (
                error.get('charge') or error.get('chargeId') or error.get('token')
            )
            result['message'] = (
                error.get('message') or error.get('detail')
                or (error.get('error') if isinstance(error.get('error'), str) else None)
            )
            if not result['http_message']:
                result['http_message'] = error.get('http_message')
            # Clover SDK field-validation errors from createToken() have no
            # code/message keys - they are {"CARD_NUMBER": "...", "CARD_DATE": "..."}.
            # Flatten them into a readable message and a synthetic code.
            if not result['message']:
                card_field_errors = {
                    k: v for k, v in error.items()
                    if isinstance(v, str) and (
                        k.upper().startswith('CARD_') or k in ('number', 'expiry', 'cvv', 'postal_code')
                    )
                }
                if card_field_errors:
                    result['message'] = "; ".join(
                        "%s: %s" % (k, v) for k, v in card_field_errors.items()
                    )
                    if not result['code']:
                        result['code'] = 'invalid_card_details'
        elif isinstance(error, str):
            result['message'] = error
        errors = payload.get('errors')
        if not result['message'] and errors:
            result['message'] = errors if isinstance(errors, str) else str(errors)
        if not result['message']:
            result['message'] = payload.get('errors_message') or payload.get('detail')
        # Some Clover errors carry no charge/token key but name the token inline
        # in the message ("... for token clv_XXXX"). Surface it so the reference
        # field is not blank.
        if not result['charge_id'] and result['message']:
            m = re.search(r'\b(clv_[A-Za-z0-9]+)\b', result['message'])
            if m:
                result['charge_id'] = m.group(1)
        return result

    def _clover_checkout_customer_message(self, err):
        """ Build a concise, customer-facing message from an extracted error dict. """
        parts = []
        base = err.get('message') or err.get('http_message') or _("Payment could not be completed.")
        if err.get('decline_code') and err['decline_code'] not in (base or ''):
            parts.append(_("Card declined (%s)", err['decline_code']))
        elif err.get('code') == 'card_declined':
            parts.append(_("Card declined"))
        parts.append(base)
        return ": ".join(p for p in parts if p)

    def _clover_checkout_append_log(self, event, payload=None, duration=None, note=None):
        """ Append one timestamped line to ``clover_checkout_log`` and refresh the
        ``clover_last_*`` summary fields. Never raises.

        :param str event: short event tag, e.g. 'charge_request', 'charge_response',
                          'charge_error', 'store_pm_error', 'client_error'.
        :param payload: dict/str logged as (redacted) JSON.
        :param float duration: round-trip seconds, when known.
        :param str note: free-text suffix.
        """
        for tx in self:
            try:
                safe_payload = tx._clover_checkout_redact(payload)
                err = tx._clover_checkout_extract_error(payload) if isinstance(payload, dict) else {}

                bits = [datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'), event]
                if err.get('http_message'):
                    bits.append(str(err['http_message']))
                summary = []
                if err.get('code'):
                    summary.append("code=%s" % err['code'])
                if err.get('decline_code'):
                    summary.append("declineCode=%s" % err['decline_code'])
                if err.get('charge_id'):
                    summary.append("charge=%s" % err['charge_id'])
                if err.get('message'):
                    summary.append('msg=%r' % err['message'])
                if summary:
                    bits.append(" ".join(summary))
                if duration is not None:
                    bits.append("%.3fs" % duration)
                if note:
                    bits.append(str(note))
                try:
                    bits.append(json.dumps(safe_payload, default=str))
                except Exception:
                    bits.append(repr(safe_payload))
                line = " | ".join(bits)

                # One entry per line, with a blank line between entries for readability.
                existing = (tx.clover_checkout_log or '').rstrip("\n")
                if existing:
                    new_log = existing + "\n\n" + line + "\n"
                else:
                    new_log = line + "\n"
                new_log = new_log[-CLOVER_LOG_MAX_CHARS:]
                vals = {'clover_checkout_log': new_log}
                if err.get('code'):
                    vals['clover_last_error_code'] = err['code']
                if err.get('decline_code'):
                    vals['clover_last_decline_code'] = err['decline_code']
                if err.get('message'):
                    vals['clover_last_error_message'] = (err['message'] or '')[:512]
                if err.get('charge_id'):
                    vals['clover_last_charge_id'] = err['charge_id']
                if duration is not None:
                    vals['clover_request_duration'] = duration
                # Last API outcome: any *_error event, or an error payload, means error.
                if event.endswith('_error') or err.get('code') or err.get('message'):
                    vals['clover_last_status'] = 'error'
                tx.sudo().write(vals)

                if duration is not None and duration >= CLOVER_SLOW_REQUEST_THRESHOLD:
                    _logger.warning(
                        "Clover Checkout slow request (%.1fs) for transaction %s (%s)",
                        duration, tx.reference, event,
                    )
            except Exception:
                _logger.exception(
                    "Clover Checkout: failed to append diagnostic log (%s) for tx %s",
                    event, tx.id,
                )

    def _clover_checkout_append_log_isolated(self, event, payload=None, duration=None, note=None):
        """ Same as :meth:`_clover_checkout_append_log` but on a fresh cursor so the
        entry survives even when the current request is about to roll back
        (e.g. a decline that then raises a ValidationError). Never raises. """
        from odoo import SUPERUSER_ID
        for tx in self:
            tx_id = tx.id
            if not tx_id:
                continue
            try:
                with self.env.registry.cursor() as new_cr:
                    new_env = api.Environment(new_cr, SUPERUSER_ID, {})
                    new_env['payment.transaction'].browse(tx_id)._clover_checkout_append_log(
                        event, payload=payload, duration=duration, note=note,
                    )
                    new_cr.commit()
            except Exception:
                _logger.exception(
                    "Clover Checkout: isolated diagnostic log failed (%s) for tx %s",
                    event, tx_id,
                )



    def _get_specific_processing_values(self, processing_values):
        """ Override of payment to return an access token as provider-specific processing values.

        Note: self.ensure_one() from `_get_processing_values`

        :param dict processing_values: The generic processing values of the transaction
        :return: The dict of provider-specific processing values
        :rtype: dict
        """
        res = super()._get_specific_processing_values(processing_values)
        if self.provider_code != 'clover_checkout':
            return res

        return {
            'access_token': payment_utils.generate_access_token(
                processing_values['reference'], processing_values['partner_id']
            )
        }



    def _get_specific_rendering_values(self, processing_values):
        """ Override of payment to return clover_checkout-specific rendering values.

        Note: self.ensure_one() from `_get_processing_values`

        :param dict processing_values: The generic and specific processing values of the transaction
        :return: The dict of provider-specific processing values
        :rtype: dict
        """
        res = super()._get_specific_rendering_values(processing_values)
        # print("Processing Values--", processing_values)
        if self.provider_code != 'clover_checkout':
            return res
        return
    
    def _get_tx_from_notification_data(self, provider_code, notification_data):
        """ Override of payment to find the transaction based on clover_checkout data.

        :param str provider_code: The code of the provider that handled the transaction
        :param dict notification_data: The notification data sent by the provider
        :return: The transaction if found
        :rtype: recordset of `payment.transaction`
        :raise: ValidationError if inconsistent data were received
        :raise: ValidationError if the data match no transaction
        """
        tx = super(CloverPaymentTransaction,self)._get_tx_from_notification_data(provider_code,notification_data)
        if provider_code != 'clover_checkout' or len(tx) == 1: # check if issue
            return tx
        reference = notification_data.get('id')
        if not reference:
            raise ValidationError("clover_checkout: " + _("Missing reference %s.", reference))
        tx = self.search([('clover_checkout_reference', '=', reference),
                          ('provider_code', '=', 'clover_checkout')])
        if not tx:
            raise ValidationError("clover_checkout: " + _("Invalid transaction reference %s.", reference))
        return tx



    def _process_notification_data(self, notification_data):
        """ Override of payment to process the transaction based on clover_checkout data.

        Note: self.ensure_one()

        :param dict notification_data: The notification data sent by the provider
        :return: None
        :raise: ValidationError if inconsistent data were received
        """
        super()._process_notification_data(notification_data)
        if self.provider_code != 'clover_checkout':
            return

        _logger.info("notification_data %s", notification_data)
        event_code = notification_data.get('status')
        _logger.info('devAp  event_code %s', event_code)

        # Duration is smuggled in by the controller / _send_payment_request.
        duration = None
        if isinstance(notification_data, dict):
            duration = notification_data.get('__clover_duration')

        if event_code:
            if event_code == 'succeeded':
                charge_id = notification_data.get('id') or notification_data.get('ref_num')
                self._clover_checkout_append_log(
                    'charge_response', notification_data, duration=duration,
                    note='status=succeeded',
                )
                # Record the successful charge id, but keep any earlier decline
                # summary (clover_last_error_code / decline_code / error_message)
                # so the record still shows what the customer hit before it went
                # through. The 'done' state itself makes clear the payment
                # ultimately succeeded; clover_checkout_log has the full order.
                write_vals = {'clover_last_status': 'success'}
                if charge_id:
                    write_vals['clover_last_charge_id'] = charge_id
                self.sudo().write(write_vals)
                # Set the transaction state to pending
                self._set_done(state_message="Transaction captured")
            # elif event_code == 'INITIATED':
            #     # Set the transaction state to initiated
            #     self._set_pending(state_message="Transaction initiated")
            # elif event_code == 'PENDING':
            #     # Set the transaction state to pending
            #     self._set_pending(state_message="Transaction pending")
            # elif event_code == 'PREAUTHORIZED':
            #     # Set the transaction state to pending
            #     self._set_pending(state_message="Transaction preauthorized")
            # elif event_code == 'CAPTURED':
            #     # Set the transaction state to pending
            #     self._set_done(state_message="Transaction captured")
            # elif event_code == 'FUNDED':
            #     # Set the transaction state to done
            #     # if self.tokenize:
            #     #     self._clover_checkout_tokenize_from_notification_data(notification_data)
            #     self._set_done(state_message="Transaction funded")
            # elif event_code == 'REVERSED':
            #     # Set the transaction state to error
            #     self._set_error(state_message="Transaction reversed")
            # elif event_code in ['DECLINED', 'FAILED', 'REJECTED']:
            #     # Set the transaction state to canceled
            #     self._set_canceled(state_message="Transaction canceled")
            else:
                # Handle other status codes if needed
                self._clover_checkout_append_log(
                    'charge_response', notification_data, duration=duration,
                    note='unhandled status=%s' % event_code,
                )
                self.sudo().write({'clover_last_status': 'error'})
                self._set_error(state_message="Unhandled transaction status: %s" % event_code)
            if self.tokenize:
                self._clover_checkout_tokenize_from_notification_data(notification_data)
                _logger.info(
                    "Received data with an unhandled transaction status (%s) for transaction with reference %s",
                    event_code, self.reference,
                )
        else:
            # No 'status' key: this is an error/decline payload from Clover.
            err = self._clover_checkout_extract_error(notification_data)
            self._clover_checkout_append_log(
                'charge_response', notification_data, duration=duration, note='declined/error',
            )
            self.sudo().write({'clover_last_status': 'error'})
            state_message = self._clover_checkout_customer_message(err)
            self._set_error(state_message=state_message)
            _logger.info(
                "clover_checkout: declined/error response (code=%s declineCode=%s charge=%s) "
                "for transaction with reference %s",
                err.get('code'), err.get('decline_code'), err.get('charge_id'), self.reference,
            )
            
            
    def _clover_checkout_tokenize_from_notification_data(self, notification_data):
        """ Create a new token based on the notification data.

        Note: self.ensure_one()

        :param dict notification_data: The notification data sent by the provider
        :return: None
        """
        self.ensure_one()

        additional_data = notification_data.get('id')
        # card = additional_data.get('card',{}).get('masked_number_last4','')
        card=  notification_data.get('source',{}).get('id',''),
        token = self.env['payment.token'].sudo().search([('partner_id','=',self.partner_id.id),('clover_checkout_id','=',card)])
        if not token:
            token = self.env['payment.token'].create({
                'provider_id': self.provider_id.id,
                'payment_method_id': self.payment_method_id.id,
                'payment_details': notification_data.get('source',{}).get('last4',''),
                'partner_id': self.partner_id.id,
                'provider_ref': notification_data.get('ref_num'),
                'clover_checkout_id': notification_data.get('source',{}).get('id',''),
                'clover_customer_id': self.clover_data_id,
                # 'global_shopper_reference': additional_data.get('id'),
                # 'payment_method_id': self.payment_method_id.id,
                # 'verified': True,  # The payment is authorized, so the payment method is valid
            })
        self.write({
            'token_id': token,
            'tokenize': False,
        })
        _logger.info(
            "created token with id %(token_id)s for partner with id %(partner_id)s from "
            "transaction with reference %(ref)s",
            {
                'token_id': token.id,
                'partner_id': self.partner_id.id,
                'ref': self.reference,
            },
        )
    
    
    def _send_payment_request(self):
        """ Override of payment to send a payment request to Adyen.

        Note: self.ensure_one()

        :return: None
        :raise: UserError if the transaction is not linked to a token
        """
        super()._send_payment_request()
        if self.provider_code != 'clover_checkout':
            return


        if not self.token_id:
            raise UserError("clover_checkout: " + _("The transaction is not linked to a token."))

        tx_sudo = self
        currency = self.currency_id

        data = {
            "ecomind": "ecom",
            "metadata": {
                "existingDebtIndicator": False
            },

            "amount":tx_sudo.amount  ,
            "currency": currency.name,
           "source": self.token_id.clover_checkout_id
        }

        response = None
        tx_sudo._clover_checkout_append_log('token_charge_request', data)
        _t0 = datetime.utcnow()
        try:
            response = self.provider_id._clover_checkout_make_request('charge_payment', payload=data)
            duration = (datetime.utcnow() - _t0).total_seconds()

            # Handle the payment request response
            _logger.info("payment request response: %s", pprint.pformat(response))

            # if the merchantOrderId already exists in clover_checkout and you try to pay again, the createInvoice return
            # So her we check, if he response is string thne
            if isinstance(response, str):
                tx_sudo._clover_checkout_append_log(
                    'token_charge_error', response, duration=duration)
                tx_sudo._set_error(response)
                raise ValidationError(
                    "clover_checkout: " + _("Create Invoice response %(ref)s.", ref=response)
                )
            if response.get('id'):
                tx_sudo.write({
                    'provider_reference': response.get('id'),
                    'clover_checkout_reference': response.get('id'),
                    'tokenize': False,
                })
            # self.write({
            #     'token_id': token,
            #     'tokenize': False,
            # })
            tx_sudo._handle_notification_data(
                'clover_checkout',
                dict(response, payment_ref=self.token_id, __clover_duration=duration),
            )
            return json.dumps(response)
        except ValidationError:
            raise
        except requests.exceptions.RequestException:
            duration = (datetime.utcnow() - _t0).total_seconds()
            _logger.exception("Error with clover_checkout service %s", json.dumps(response, default=str))
            tx_sudo._clover_checkout_append_log_isolated(
                'token_charge_error', response if response is not None else {'error': 'connection_error'},
                duration=duration, note='RequestException',
            )
            detail = response.get('detail') if isinstance(response, dict) else None
            raise ValidationError("Detail: " + (detail or _("Could not establish the connection to the API.")))
        except Exception as e:
            duration = (datetime.utcnow() - _t0).total_seconds()
            _logger.error("error during the payment: %s", str(e))
            tx_sudo._clover_checkout_append_log_isolated(
                'token_charge_error', response if isinstance(response, dict) else {'error': str(e)},
                duration=duration, note='exception: %s' % e,
            )
            raise ValidationError(str(e))
