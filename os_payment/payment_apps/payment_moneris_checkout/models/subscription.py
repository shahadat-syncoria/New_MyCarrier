# -*- coding: utf-8 -*-
###############################################################################
#    License, author and contributors information in:                         #
#    __manifest__.py file at the root folder of this module.                  #
###############################################################################

from odoo import api, models, fields
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = 'account.move'

    @api.model
    def action_subscription_payment(self):
        print("action_subscription_payment")
        print("self ====>>>>", self)
        for rec in self:
            print("rec ====>>>>", rec)
            if rec.partner_id.payment_token_ids:
                token_id = rec.partner_id.payment_token_ids[-1]
                values = self.get_register_vals(token_id)
                print("values ===>>>", values)
                # Create a Account.Payment.Register
                pay_reg_id = self.env['account.payment.register'].create(values)
                # Call `action_create_payments`
                pay_reg_id.action_create_payments()
            else:
                self._send_card_email()

        # For all invoices (selected)
        #     if Customer has saved payment method
        #         Charge credit card for the invoice total
        #         If payment is successful
        #             Add payment to invoice, mark paid
        #         Else send email template: “Credit card could not be charged”**
        #     Else
        #         Send email template “Would you like to add your credit card?”

    def _send_card_email(self):
        """Send email template “Would you like to add your credit card?”"""
        print("Send email template “Would you like to add your credit card?”")
        self.ensure_one()

        # determine subject and body in the portal user's language
        template = self.env.ref(
            'payment_moneris_checkout.email_template_add_card')
        print("template ====>>>>", template)
        if not template:
            raise UserError(
                ('The template "Portal: new user" not found for sending email to the portal user.'))

        lang = self.user_id.sudo().lang
        partner = self.partner_id
        print("lang ====>>>>", lang)
        print("partner ====>>>>", partner)

        # portal_url = partner.with_context(signup_force_type_in_url='', lang=lang)._get_signup_url_for_action()[partner.id]
        partner.signup_prepare()
        # print("portal_url ====>>>>", portal_url)

        template.send_mail(self.id, force_send=True)
        print("template ====>>>>", template)
        return True

    def _send_paymentfailure_email(self):
        print("_send_paymentfailure_email")
        self.ensure_one()
        template = self.env.ref(
            'payment_moneris_checkout.email_template_subscription_invoice')
        print("template ====>>>>", template)
        if not template:
            raise UserError(
                _('The template "Portal: new user" not found for sending email to the portal user.'))

        lang = self.user_id.sudo().lang
        partner = self.partner_id
        print("lang ====>>>>", lang)
        print("partner ====>>>>", partner)

        # portal_url = partner.with_context(signup_force_type_in_url='', lang=lang)._get_signup_url_for_action()[partner.id]
        partner.signup_prepare()
        # print("portal_url ====>>>>", portal_url)

        template.send_mail(self.id, force_send=True)
        print("template ====>>>>", template)
        return True

    def get_register_vals(self, token_id):
        print("token_id ===>>>", token_id)
        journal_id = self.env['account.journal'].sudo().search(
            [('name', '=', 'Moneris Checkout')]).id
        payment_method_line_id = False
        # payment_method_line_id = self.env.ref(
        #     'payment_moneris_chekout.payment_method_monerischeckout').id
        domain = [('journal_id', '=', journal_id)]
        domain += [('payment_type', '=', 'inbound')]
        pay_method_lines = self.env['account.payment.method.line'].sudo().search(domain, limit=1)
        print("pay_method_lines ====>>>>", pay_method_lines)
        print("fields.Datetime.now() ====>>>>", fields.Datetime.now())
        vals = {
            'can_edit_wizard': False,
            'can_group_payments': False,
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'source_amount': self.amount_total,
            'source_amount_currency': self.amount_total,
            'source_currency_id': self.currency_id.id,
            'company_id': self.company_id.id,
            'partner_id': self.partner_id.id,
            'country_code': self.partner_id.country_id.code,
            'journal_id': journal_id,
            'payment_method_line_id': pay_method_lines.id,
            'payment_token_id': token_id.id,
            'partner_bank_id': False,
            'group_payment': False,
            'amount': self.amount_total,
            'currency_id': self.currency_id.id,
            'payment_date': fields.Datetime.now().date().strftime('%Y-%m-%d'), 
            'communication': self.name,
            'payment_difference_handling': 'open', 
            'writeoff_account_id': False, 
            'writeoff_label': 'Write-Off'
        
        }
        return vals
