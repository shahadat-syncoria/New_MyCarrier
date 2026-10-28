# -*- coding: utf-8 -*-
import hmac
import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class MyCarrierWebhookController(http.Controller):
    """Inbound MyCarrier webhooks (shipment.created / updated ...).

    Register https://<host>/mycarrier/shipment/webhook with MyCarrier support.
    Optional shared secret: set system parameter `mycarrier.webhook_token` and register
    the URL as .../mycarrier/shipment/webhook?token=<secret>.
    """

    @http.route(['/mycarrier/shipment/webhook', '/mycarrier/webhook'],
                type='http', auth='public', methods=['POST'], csrf=False)
    def mycarrier_webhook(self, **kw):
        env = request.env(su=True)
        secret = env['ir.config_parameter'].get_param('mycarrier.webhook_token')
        if secret and not hmac.compare_digest(secret, kw.get('token') or request.httprequest.headers.get('X-Webhook-Token', '')):
            return request.make_json_response({'status': 'forbidden'}, status=403)
        raw = request.httprequest.get_data(as_text=True)
        try:
            json.loads(raw)
        except ValueError:
            return request.make_json_response({'status': 'invalid json'}, status=400)
        event = env['mycarrier.webhook'].create({'data': raw})
        env.cr.commit()  # keep the raw event even if processing fails below
        event._process_data()
        return request.make_json_response({'status': 'ok'})
