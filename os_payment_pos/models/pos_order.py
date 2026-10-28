# -*- coding: utf-8 -*-

from markupsafe import Markup, escape

from odoo import _, api, fields, models


class PosOrderCardName(models.Model):
    _inherit = 'pos.order'

    moneris_rescue_reason = fields.Text(copy=False)

    @api.model
    def _order_fields(self, ui_order):
        result = super()._order_fields(ui_order)
        result['moneris_rescue_reason'] = ui_order.get('moneris_rescue_reason') or False
        return result

    @api.model
    def _process_order(self, order, existing_order):
        rescue_reason = (order.get('moneris_rescue_reason') or '').strip()
        previous_reason = (existing_order.moneris_rescue_reason or '').strip() if existing_order else ''
        order_id = super()._process_order(order, existing_order)
        if rescue_reason and rescue_reason != previous_reason:
            self.browse(order_id).message_post(
                body=Markup("<b>%s</b><br/>%s") % (
                    escape(_("Moneris Rescue triggered ")),
                    escape(f"Reason : {rescue_reason}"),
                )
            )
        return order_id

    @api.model
    def _extract_clover_card_name_from_ui_paymentline(self, ui_paymentline):
        if not ui_paymentline:
            return False

        direct = (
            ui_paymentline.get('card_name')
            or ui_paymentline.get('card_type')
            or ui_paymentline.get('clover_card_type')
            or ui_paymentline.get('clover_type')
        )
        if direct:
            return direct

        transaction_info = ui_paymentline.get('clover_transaction_info')
        if isinstance(transaction_info, dict):
            card_transaction = transaction_info.get('cardTransaction') or {}
            return (
                card_transaction.get('cardType')
                or card_transaction.get('extra', {}).get('authorizingNetworkName')
                or card_transaction.get('type')
                or False
            )

        return False

    @api.model
    def _payment_fields(self, order, ui_paymentline):
        result = super()._payment_fields(order, ui_paymentline)
        result['card_name'] = (
            self._extract_clover_card_name_from_ui_paymentline(ui_paymentline)
            or ui_paymentline.get('moneris_cloud_cardname')
            or ui_paymentline.get('moneris_cloud_apppreferredname')
            or ui_paymentline.get('moneris_cloud_applabel')
            or ui_paymentline.get('moneris_cloud_cardtype')
            or result.get('card_type')
            or result.get('clover_card_type')
            or result.get('clover_type')
            or False
        )
        return result
