# -*- coding: utf-8 -*-
import json
import logging

import requests
from markupsafe import Markup, escape

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class MycarrierWebhook(models.Model):
    _name = 'mycarrier.webhook'
    _description = 'MyCarrier Webhook Event'
    _order = 'id desc'

    name = fields.Char(copy=False, readonly=True, default=lambda s: s.env['ir.sequence'].next_by_code('mycarrier.webhook'))
    state = fields.Selection([('draft', 'Draft'), ('done', 'Done'), ('skipped', 'Skipped'), ('error', 'Error')], default='draft')
    data = fields.Text('Raw Payload')
    error = fields.Text()
    picking_id = fields.Many2one('stock.picking', readonly=True)

    def _find_picking(self, payload):
        Picking = self.env['stock.picking']
        ref = payload.get('ReferenceNumber')
        picking = ref and Picking.search([('name', '=', ref)], limit=1)
        if not picking and payload.get('ShipmentId'):
            # Shipment IDs are only unique per MyCarrier environment/customer (QA and UAT collide), so a
            # ShipmentId-only match must also agree on the PRO number to be ours.
            picking = Picking.search([
                ('mycarrier_shipment_id', '=', str(payload['ShipmentId'])),
                ('mycarrier_pro_number', '=', payload.get('CarrierPRONumber') or False),
            ], limit=1)
        return picking

    def _download(self, url):
        if not url:
            return b''
        try:
            resp = requests.get(url, timeout=30)
            return resp.content if resp.status_code == 200 else b''
        except Exception as exc:
            _logger.warning('MC webhook download failed for %s: %s', url, exc)
            return b''

    def _process_data(self):
        for rec in self:
            try:
                body = json.loads(rec.data or '{}')
                payload = body.get('Payload') or {}
                picking = rec._find_picking(payload)
                if not picking:
                    # e.g. shipments booked directly in the MyCarrier portal: not ours, never retry
                    rec.write({'state': 'skipped', 'error': _('No picking found for ReferenceNumber %r / ShipmentId %r')
                               % (payload.get('ReferenceNumber'), payload.get('ShipmentId'))})
                    continue
                pro = payload.get('CarrierPRONumber')
                vals = {
                    'mycarrier_shipment_id': payload.get('ShipmentId'),
                    'mycarrier_pro_number': pro,
                    'mycarrier_bol_number': payload.get('BOLNumber'),
                    'mycarrier_customer_bol_number': payload.get('CustomerBOLNumber'),
                    'mycarrier_po_number': payload.get('PONumber'),
                    'mycarrier_pickup_number': payload.get('PickupNumber'),
                    'mycarrier_carrier_name': payload.get('CarrierName'),
                    'mycarrier_pickup_date': payload.get('PickupDate'),
                    'mycarrier_estimated_delivery': payload.get('EstimatedDeliveryDate'),
                    'mycarrier_bol_url': payload.get('BOLLink'),
                    'mycarrier_security_key': payload.get('SecurityKey'),
                    'mycarrier_tracking_status': payload.get('TrackingStatusDescription'),
                    'mycarrier_actual_pickup_date': payload.get('ActualPickupDate'),
                    'carrier_tracking_ref': pro,
                }
                vals = {k: str(v) for k, v in vals.items() if v not in (None, '')}
                if payload.get('TotalCost') not in (None, ''):
                    vals['mycarrier_final_cost'] = float(payload['TotalCost'])
                if str(payload.get('TransitTime') or '').isdigit():
                    vals['mycarrier_transit_days'] = int(payload['TransitTime'])
                vals['mycarrier_status'] = 'dispatched'
                vals['mycarrier_webhook_received'] = True
                vals['mycarrier_status_exception'] = str(payload.get('IsStatusException')) == 'True'
                old_tracking = picking.mycarrier_tracking_status
                picking.write(vals)
                new_tracking = payload.get('TrackingStatusDescription') or ''
                is_update = 'updated' in (body.get('Message') or '')
                if is_update and new_tracking == (old_tracking or '') and not vals['mycarrier_status_exception']:
                    # plain "updated" ping with nothing new to tell the user
                    rec.write({'state': 'done', 'picking_id': picking.id, 'error': False})
                    continue

                lines = [
                    (_('PRO Number'), pro), (_('Shipment ID'), payload.get('ShipmentId')),
                    (_('Customer BOL'), payload.get('CustomerBOLNumber')),
                    (_('Carrier'), payload.get('CarrierName')),
                    (_('Pickup Date'), payload.get('PickupDate')),
                    (_('Est. Delivery'), payload.get('EstimatedDeliveryDate')),
                ]
                body_html = Markup('<b>%s</b>') % escape(body.get('Message') or _('MyCarrier shipment update'))
                body_html += Markup('<br/>').join(
                    [Markup('')] + [Markup('<b>%s:</b> %s') % (escape(k), escape(v)) for k, v in lines if v])
                prices = payload.get('ShipmentPriceDetails') or []
                if prices:
                    body_html += Markup('<br/><b>%s</b><ul>%s<li><b>%s: $%s</b></li></ul>') % (
                        escape(_('Cost breakdown')),
                        Markup('').join(Markup('<li>%s: $%s</li>') % (escape(p.get('Description', '')), escape(p.get('Amount', '')))
                                        for p in prices),
                        escape(_('Total')), escape(payload.get('TotalCost', '')))

                ref = pro or payload.get('ShipmentId') or picking.name
                attachments = []
                for fname, key in (('BOL', 'BOLLink'), ('Label', 'LabelLink')):
                    fn = '%s-%s.pdf' % (fname, ref)
                    if payload.get(key) and not self.env['ir.attachment'].search_count(
                            [('res_model', '=', 'stock.picking'), ('res_id', '=', picking.id), ('name', '=', fn)]):
                        content = rec._download(payload[key])
                        if content:
                            attachments.append((fn, content))
                picking.message_post(body=body_html, attachments=attachments)
                rec.write({'state': 'done', 'picking_id': picking.id, 'error': False})
            except Exception as exc:
                _logger.exception('MC webhook %s failed', rec.name)
                rec.write({'state': 'error', 'error': str(exc)})

    def _process_webhooks(self):
        self.search([('state', 'in', ('draft', 'error'))])._process_data()

    @api.model
    def action_process_pending(self):
        """List-view button: run the same job as the cron right now."""
        self._process_webhooks()
        return {'type': 'ir.actions.client', 'tag': 'reload'}
