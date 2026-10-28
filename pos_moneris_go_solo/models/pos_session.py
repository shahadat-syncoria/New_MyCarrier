from odoo import api, fields, models, _, Command
from odoo.tools import float_compare

class PosSession(models.Model):
    _description = "Point of Sale Session"
    _inherit = 'pos.session'

    # region Other methods
    def _loader_params_pos_payment_method(self):
        result = super()._loader_params_pos_payment_method()
        if result and 'search_params' in result and 'fields' in result['search_params']:
            load_fields = result['search_params']['fields']
            load_fields.append('is_directly_payment')
        return result

    def action_pos_session_closing_control(self, balancing_account=False, amount_to_balance=0, bank_payment_method_diffs=None):
        result = super().action_pos_session_closing_control(balancing_account, amount_to_balance, bank_payment_method_diffs)
        self.config_id.close_session_moneris_go_payment_methods()
        return result
    # endregion Other

    def _create_bank_payment_moves(self, data):
        # data = super()._create_bank_payment_moves(data)
        print('-===================_create_bank_payment_moves', data, self.order_ids)
        combine_receivables_bank = data.get('combine_receivables_bank')
        print('combine_receivables_bank', combine_receivables_bank)
        split_receivables_bank = data.get('split_receivables_bank')
        bank_payment_method_diffs = data.get('bank_payment_method_diffs')
        MoveLine = data.get('MoveLine')
        payment_method_to_receivable_lines = {}
        payment_to_receivable_lines = {}
        moneris_payment_id = None
        for payment_method, amounts in combine_receivables_bank.items():
            if payment_method.use_payment_terminal == 'moneris' and payment_method.moneris_payment_journal_config_ids:
                moneris_payment_id = payment_method
                continue
            combine_receivable_line = MoveLine.create(
                self._get_combine_receivable_vals(payment_method, amounts['amount'], amounts['amount_converted'],
                                                  payment_method.name))
            payment_receivable_line = self._create_combine_account_payment(payment_method, amounts,
                                                                           diff_amount=bank_payment_method_diffs.get(
                                                                               payment_method.id) or 0,
                                                                           card_name=payment_method.name,
                                                                           journal=payment_method.journal_id)
            payment_method_to_receivable_lines[payment_method] = combine_receivable_line | payment_receivable_line

        # if moneris payment available with config ids
        if moneris_payment_id:
            moneris_grouped = {}
            for order in self.order_ids:
                for payment in order.payment_ids:
                    print('payment', payment, payment.payment_status)
                    if payment.payment_method_id.use_payment_terminal == 'moneris' and payment.payment_status == 'done':
                        key = (payment.payment_method_id.id, (payment.card_name or 'Unknown').strip().lower())
                        moneris_grouped.setdefault(key, 0)
                        moneris_grouped[key] += payment.amount

            print('moneris_grouped', moneris_grouped)
            # Build card_name → journal map from your O2M config
            card_journal_map = {}
            for line in moneris_payment_id.moneris_payment_journal_config_ids:
                card_journal_map[(moneris_payment_id.id, line.card_name.strip().lower())] = {
                    'journal': line.journal_id,
                    'account': line.receivable_account_id,
                }

            print('card_journal_map', card_journal_map)

            # Now process Moneris grouped by card_name
            for (payment_method_id, card_name), total_amount in moneris_grouped.items():
                print('pm_id, cardname', card_name)
                card_name_key = card_name.strip().lower()
                map_entry = card_journal_map.get((payment_method_id, card_name_key))
                print('found journal/account:', map_entry, card_name_key)

                if not map_entry:
                    other_config = moneris_payment_id.moneris_payment_journal_config_ids.filtered(
                        lambda c: c.is_other_payment)
                    if other_config:
                        map_entry = {
                            'journal': other_config.journal_id,
                            'account': other_config.receivable_account_id,
                        }
                    else:
                        continue

                journal = map_entry['journal']
                receivable_account_id = map_entry['account']
                print('journal receivable_account_id:', journal, receivable_account_id)

                combine_receivable_line = MoveLine.create(
                    self._get_combine_receivable_vals(moneris_payment_id, total_amount, total_amount, card_name)
                )
                payment_receivable_line = self._create_combine_account_payment(
                    moneris_payment_id,
                    {'amount': total_amount, 'amount_converted': total_amount},
                    diff_amount=0, card_name=card_name, journal=journal, receivable_account_id=receivable_account_id
                )
                payment_method_to_receivable_lines[moneris_payment_id] = payment_method_to_receivable_lines.get(
                    moneris_payment_id,
                    self.env[
                        'account.move.line']) | combine_receivable_line | payment_receivable_line

        for payment, amounts in split_receivables_bank.items():
            split_receivable_line = MoveLine.create(
                self._get_split_receivable_vals(payment, amounts['amount'], amounts['amount_converted']))
            payment_receivable_line = self._create_split_account_payment(payment, amounts)
            payment_to_receivable_lines[payment] = split_receivable_line | payment_receivable_line

        for bank_payment_method in self.payment_method_ids.filtered(
                lambda pm: pm.type == 'bank' and pm.split_transactions):
            self._create_diff_account_move_for_split_payment_method(bank_payment_method, bank_payment_method_diffs.get(
                bank_payment_method.id) or 0)

        data['payment_method_to_receivable_lines'] = payment_method_to_receivable_lines
        data['payment_to_receivable_lines'] = payment_to_receivable_lines
        online_payment_to_receivable_lines = {}
        data['online_payment_to_receivable_lines'] = online_payment_to_receivable_lines
        return data

    def _create_combine_account_payment(self, payment_method, amounts, diff_amount, card_name='', journal=None,
                                        receivable_account_id=None):
        outstanding_account = payment_method.outstanding_account_id
        destination_account = self._get_receivable_account(payment_method)
        card_name = card_name or payment_method.name
        account_payment = self.env['account.payment'].with_context(pos_payment=True).create({
            'amount': abs(amounts['amount']) + diff_amount,
            'journal_id': journal.id if journal else payment_method.journal_id.id,
            'force_outstanding_account_id': outstanding_account.id,
            'destination_account_id': receivable_account_id.id if receivable_account_id else destination_account.id,
            'memo': _('%(card_name)s -- Combine %(payment_method)s POS payments from %(session)s',
                      card_name=card_name.upper(), payment_method=payment_method.name, session=self.name),
            'pos_payment_method_id': payment_method.id,
            'pos_session_id': self.id,
            'company_id': self.company_id.id,
        })

        # In community the outstanding account is computed on the creation of account.payment records
        accounting_installed = self.env['account.move']._get_invoice_in_payment_state() == 'in_payment'
        if not account_payment.outstanding_account_id and accounting_installed:
            account_payment.outstanding_account_id = account_payment._get_outstanding_account(
                account_payment.payment_type)

        if float_compare(amounts['amount'], 0, precision_rounding=self.currency_id.rounding) < 0:
            # revert the accounts because account.payment doesn't accept negative amount.
            account_payment.write({
                'outstanding_account_id': account_payment.destination_account_id,
                'destination_account_id': account_payment.outstanding_account_id,
            })

        account_payment.action_post()

        diff_amount_compare_to_zero = self.currency_id.compare_amounts(diff_amount, 0)
        if diff_amount_compare_to_zero != 0:
            self._apply_diff_on_account_payment_move(account_payment, payment_method, diff_amount)

        return account_payment.move_id.line_ids.filtered(
            lambda line: line.account_id == self._get_receivable_account(payment_method))

    def _get_combine_receivable_vals(self, payment_method, amount, amount_converted, card_name=''):
        card_name = card_name or payment_method.name
        partial_vals = {
            'account_id': self._get_receivable_account(payment_method).id,
            'move_id': self.move_id.id,
            'name': '%s -%s - %s' % (card_name.upper(), self.name, payment_method.name),
            'display_type': 'payment_term',
        }
        return self._debit_amounts(partial_vals, amount, amount_converted)
