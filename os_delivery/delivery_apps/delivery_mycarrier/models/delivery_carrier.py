# -*- coding: utf-8 -*-
import json
import logging
import math
import re
import uuid as uuid_lib
from datetime import date, timedelta

import requests
from requests.auth import HTTPBasicAuth

from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Location type name → accessorial code for origin/destination stops
_MC_ORIGIN_LOCATION_CODES = {
    'Residential': 'RESPU',
    'Convention/Tradeshow': 'CNVPU',
    'Camp': 'CAMPPU',
    'Church': 'CHRCPU',
    'Club': 'CLUBPU',
    'Construction Site': 'CONPU',
    'Education': 'EDUPU',
    'Government': 'GOVPU',
    'Grocery': 'GROPU',
    'Hospital': 'HOSPU',
    'Hotel': 'HOTLPU',
    'Military': 'MILPU',
    'Mine': 'MINEPU',
    'Nursing Home': 'NURSPU',
    'Park': 'PARKPU',
    'Pier/Port': 'PIERPU',
    'Prison': 'PRISPU',
    'Resort': 'RSRTPU',
    'Self Storage': 'SSTORPU',
    'Utility': 'UTLPU',
    'Limited Access': 'LTDPU',
    'Airport': 'AIRPU',
    'Farm': 'FARMPU',
}
_MC_DEST_LOCATION_CODES = {
    'Residential': 'RESDEL',
    'Convention/Tradeshow': 'CNVDEL',
    'Camp': 'CAMPDEL',
    'Church': 'CHRCDEL',
    'Club': 'CLUBDEL',
    'Construction Site': 'CONDEL',
    'Education': 'EDUDEL',
    'Government': 'GOVDEL',
    'Grocery': 'GRODEL',
    'Hospital': 'HOSDEL',
    'Hotel': 'HOTLDEL',
    'Military': 'MILDEL',
    'Mine': 'MINEDEL',
    'Nursing Home': 'NURSDEL',
    'Park': 'PARKDEL',
    'Pier/Port': 'PIERDEL',
    'Prison': 'PRISDEL',
    'Resort': 'RSRTDEL',
    'Self Storage': 'SSTORDEL',
    'Utility': 'UTLDEL',
    'Limited Access': 'LTDDEL',
    'Airport': 'AIRDEL',
    'Farm': 'FARMDEL',
}

_MC_BASE_URLS = {
    'qa': 'https://preprod-api.mycarrier.dev',
    'prod': 'https://api.mycarriertms.com',
}

_COUNTRY_MAP = {'US': 'USA', 'CA': 'CAN', 'MX': 'MEX'}

# Valid MyCarrier shipping unit type names (must match package_type.name exactly)
_MC_SHIPPING_UNIT_TYPES = {
    'Bag', 'Bale', 'Box', 'Bucket', 'Bundle', 'Carton', 'Case', 'Crate', 'Cylinder',
    'Drums', 'Pail', 'Pallet', 'Pieces', 'Reel', 'Roll', 'Skid', 'Tote', 'Tube',
}

def _mc_unit_type_name(name):
    """Package Type name -> MyCarrier unit type: "Pallet (48*40)" is sent as "Pallet"."""
    return re.sub(r'\s*\(.*\)\s*$', '', name or '')


_LEVEL_LABELS = {
    'STD': 'Standard',
    'GUR': 'Guaranteed 5:00 PM',
    'GUR_NOON': 'Guaranteed 12:00 PM',
    'GUR_AM': 'Guaranteed A.M.',
    'GUR_EARLY': 'Guaranteed Early A.M.',
}


class MyCarrierDelivery(models.Model):
    _inherit = 'delivery.carrier'

    delivery_type = fields.Selection(
        selection_add=[('mycarrier', 'MyCarrier LTL')],
        ondelete={'mycarrier': 'set default'},
    )

    # --- Credentials ---
    mycarrier_api_key = fields.Char('API Key')
    mycarrier_username = fields.Char('Username')
    mycarrier_environment = fields.Selection(
        [('qa', 'QA / Test'), ('prod', 'Production')],
        default=False,
        string='Environment',
        help='Optional. Send only if your MyCarrier account requires it. Leave blank for most tenants.',
    )

    # --- Shipment config ---
    mycarrier_origin_location_id = fields.Many2one(
        'mycarrier.location',
        string='Origin Location',
        domain="[('carrier_id', '=', id)]",
        help='Select from synced MyCarrier shipping locations. Use "Sync Locations" first.',
    )
    mycarrier_payment_terms = fields.Selection(
        [('PREPAID', 'Prepaid'), ('COLLECT', 'Collect'), ('THIRD_PARTY', 'Third Party')],
        default='PREPAID',
        string='Payment Terms',
    )
    mycarrier_service_level = fields.Selection(
        [
            ('ALL', 'All Available'),
            ('STD', 'Standard Only'),
            ('GUR', 'Guaranteed 5:00 PM'),
        ],
        default='ALL',
        string='Service Level Filter',
    )
    mycarrier_allow_brokerage = fields.Boolean(
        'Allow Brokerage Rates',
        help='Include brokerage-priced carriers (typically more expensive than contract rates).',
    )
    mycarrier_weight_unit = fields.Selection(
        [('LB', 'Pounds (LB)'), ('KG', 'Kilograms (KG)')],
        default='LB',
        string='Product Weight Unit',
        help='Unit used when product weights are entered in Odoo. MyCarrier always receives LB.',
    )
    mycarrier_default_freight_class = fields.Char(
        'Default Freight Class',
        default='70',
        help='NMFC freight class used when a product has no class defined (50 / 55 / 60 / 65 / 70 / … / 500).',
    )
    mycarrier_location_ids = fields.One2many(
        'mycarrier.location', 'carrier_id', string='Shipping Locations',
    )
    mycarrier_create_quote = fields.Boolean(
        'Create MyCarrier Quote',
        help='Adds a Create Quote button to the Get Rate wizard on the sales order, saves the quote at MyCarrier '
             'and carries its number to the delivery. The delivery then uses Update Quote and a two-step '
             'Dispatch to MyCarrier instead of Create Order / Select Rate.',
    )
    mycarrier_quote_build_mode = fields.Selection([
        ('product', 'Product-wise (per move line, grouped by Package Type)'),
        ('package', 'Package-wise (one unit per physical package)'),
    ], default='product', string='Quote Build Mode', required=True,
        help='Product-wise: aggregates same-type packages into one quoteUnit; weight/class/NMFC '
             'from the product.\nPackage-wise: one quoteUnit per package; weight/class/NMFC '
             'from the package itself (requires Shipping Weight and MyCarrier fields on each package).',
    )

    # --- Default accessorials (applied to new pickings) ---
    mycarrier_default_origin_location_type = fields.Many2one(
        'mycarrier.location.type', string='Default Origin Location Type',
    )
    mycarrier_default_origin_inside_pickup = fields.Boolean('Default Inside Pickup')
    mycarrier_default_origin_liftgate_pickup = fields.Boolean('Default Liftgate Pickup')
    mycarrier_default_origin_protect_from_freeze = fields.Boolean('Default Protect From Freeze')
    mycarrier_default_origin_single_shipment = fields.Boolean('Default Single Shipment')
    mycarrier_default_origin_inbond_freight = fields.Boolean('Default In Bond Freight')

    mycarrier_default_dest_location_type = fields.Many2one(
        'mycarrier.location.type', string='Default Destination Location Type',
    )
    mycarrier_default_dest_delivery_appointment = fields.Boolean('Default Delivery Appointment')
    mycarrier_default_dest_inside_delivery = fields.Boolean('Default Inside Delivery')
    mycarrier_default_dest_liftgate_delivery = fields.Boolean('Default Liftgate Delivery')
    mycarrier_default_dest_notify_delivery = fields.Boolean('Default Notify Before Delivery')
    mycarrier_default_dest_sort_segregate_delivery = fields.Boolean('Default Sort/Segregate Delivery')

    # =========================================================================
    # Internal API helpers
    # =========================================================================

    def _mc_call(self, method, path, payload=None):
        self.ensure_one()
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-Mc-Api-Key': self.mycarrier_api_key or '',
            'User-Agent': 'Syncoria-Odoo/1.0',
            'Traceparent': '00-%s-%s-01' % (uuid_lib.uuid4().hex, uuid_lib.uuid4().hex[:16]),
        }
        env = self.mycarrier_environment or 'qa'
        base_url = _MC_BASE_URLS.get(env, _MC_BASE_URLS['qa'])
        url = base_url + path
        # Environment header removed — URL already differentiates qa vs prod
        try:
            resp = requests.request(
                method,
                url,
                auth=HTTPBasicAuth(self.mycarrier_username or '', self.mycarrier_api_key or ''),
                headers=headers,
                json=payload,
                timeout=60,
            )
        except requests.exceptions.RequestException as exc:
            raise UserError(_('MyCarrier API connection error: %s') % exc)
        if resp.status_code == 401:
            raise UserError(_('MyCarrier: Authentication failed. Verify API key and username.'))
        try:
            return resp.json(), resp.status_code
        except ValueError:
            raise UserError(
                _('MyCarrier: Non-JSON response (HTTP %s): %s') % (resp.status_code, resp.text[:300])
            )

    def _mc_download(self, url):
        """Download a binary file from a MyCarrier URL using carrier credentials."""
        if not url:
            return b''
        try:
            resp = requests.get(
                url,
                auth=HTTPBasicAuth(self.mycarrier_username or '', self.mycarrier_api_key or ''),
                headers={'X-Mc-Api-Key': self.mycarrier_api_key or ''},
                timeout=30,
            )
            if resp.status_code == 200:
                return resp.content
        except Exception as exc:
            _logger.warning('MC download failed for %s: %s', url, exc)
        return b''

    def _mc_to_lb(self, weight):
        if self.mycarrier_weight_unit == 'KG':
            return weight * 2.20462
        return weight

    def _mc_origin_stop(self, pickup_dt, picking=None):
        stop = {
            'stopType': 'ORIGIN',
            'addressId': self.mycarrier_origin_location_id.address_id or '',
            'appointmentDetails': {
                'pickup': {
                    'pickupDate': pickup_dt.strftime('%Y/%m/%d'),
                    'openTime': '08:00',
                    'closeTime': '16:30',
                },
            },
        }
        if picking and picking.origin_location_type:
            stop['locationType'] = picking.origin_location_type.name
        return stop

    def _mc_destination_stop(self, partner, pickup_dt, picking=None):
        country_code = (partner.country_id.code or 'US')
        country = _COUNTRY_MAP.get(country_code, country_code)
        state = (partner.state_id.code or '')[:2]
        postal = (partner.zip or '').replace(' ', '')
        name_parts = (partner.name or 'Contact').split()
        delivery_dt = pickup_dt + timedelta(days=5)

        stop = {
            'stopType': 'DESTINATION',
            'name': (partner.name or '')[:200],
            'addressLine1': (partner.street or '')[:200],
            'addressLine2': (partner.street2 or '')[:200],
            'city': (partner.city or '')[:100],
            'stateProvince': state,
            'postalCode': postal,
            'country': country,
            'contact': {
                'firstName': name_parts[0] if name_parts else 'Contact',
                'lastName': name_parts[-1] if len(name_parts) > 1 else 'NA',
                'phone': self._mc_phone(partner),
                'email': (partner.email or '')[:320],
            },
            'appointmentDetails': {
                'delivery': {
                    'deliveryDate': delivery_dt.strftime('%Y/%m/%d'),
                    'openTime': '09:00',
                    'closeTime': '17:00',
                },
            },
        }
        if picking and picking.dest_location_type:
            stop['locationType'] = picking.dest_location_type.name
        return stop

    def _mc_validate_package(self, package):
        if not package.package_type_id:
            raise UserError(_('Package "%s" has no Package Type set.') % package.name)
        pt = package.package_type_id
        if not (pt.height and pt.packaging_length and pt.width):
            raise UserError(_(
                'Package Type "%s" (on package "%s") is missing Height/Length/Width. '
                'MyCarrier requires all three dimensions.'
            ) % (pt.name, package.name))
        if _mc_unit_type_name(pt.name) not in _MC_SHIPPING_UNIT_TYPES:
            raise UserError(_(
                'Package Type "%s" (on package "%s") is not a valid MyCarrier unit type. '
                'Valid types: %s'
            ) % (pt.name, package.name, ', '.join(sorted(_MC_SHIPPING_UNIT_TYPES))))

    def _mc_picking_packages(self, picking):
        """Return assigned destination packages on a picking (non-empty)."""
        return picking.move_line_ids.mapped('result_package_id').filtered(lambda p: p.id)

    def _mc_build_units_product_wise(self, picking):
        """Rate API format: group packages by Package Type; commodities from product lines."""
        packages = self._mc_picking_packages(picking)
        if not packages:
            return []
        for pkg in packages:
            self._mc_validate_package(pkg)

        default_class = self.mycarrier_default_freight_class or '70'
        packages_by_type = {}
        for pkg in packages:
            packages_by_type.setdefault(pkg.package_type_id, []).append(pkg)

        units = []
        for pt, type_pkgs in packages_by_type.items():
            commodities = []
            for pkg in type_pkgs:
                lines = picking.move_line_ids.filtered(
                    lambda l, p=pkg: l.result_package_id == p and l.quantity > 0
                )
                for line in lines:
                    product = line.product_id
                    if not product or product.type == 'service':
                        continue
                    weight = max(1, int(math.ceil(self._mc_to_lb(product.weight or 1.0) * line.quantity)))
                    commodity = {
                        'description': (product.name or 'Goods')[:500],
                        'pieces': int(line.quantity),
                        'weight': weight,
                        'freightClass': str(product.mycarrier_commodity_class or default_class),
                        'packageType': 'BOX',
                        'hazardous': False,
                    }
                    if product.mycarrier_commodity_nmfc:
                        commodity['nmfc'] = product.mycarrier_commodity_nmfc[:6]
                    if product.mycarrier_commodity_sub:
                        commodity['nmfcSub'] = product.mycarrier_commodity_sub[:10]
                    commodities.append(commodity)
            if not commodities:
                continue
            units.append({
                'count': len(type_pkgs),
                'length': int(pt.packaging_length),
                'width': int(pt.width),
                'height': int(pt.height),
                'packageType': 'PLT',
                'stackable': False,
                'freightClass': commodities[0]['freightClass'],
                'commodities': commodities,
            })
        return units

    def _mc_build_units_package_wise(self, picking):
        """Rate API format: one quoteUnit per physical package; fields from package."""
        packages = self._mc_picking_packages(picking)
        if not packages:
            return []
        self._mc_check_all_lines_packaged(picking)
        units = []
        for pkg in packages:
            v = self._mc_package_wise_values(picking, pkg)
            commodity = {
                'description': pkg.name[:500],
                'pieces': v['pieces'],
                'weight': v['weight'],
                'freightClass': v['freight_class'],
                'packageType': 'BOX',
                'hazardous': v['hazmat'],
                'nmfc': v['nmfc'],
            }
            if v['sub']:
                commodity['nmfcSub'] = v['sub'][:10]
            units.append({
                'count': 1,
                'length': v['length'],
                'width': v['width'],
                'height': v['height'],
                'packageType': 'PLT',
                'stackable': v['stackable'],
                'freightClass': v['freight_class'],
                'commodities': [commodity],
            })
        return units

    def _mc_package_wise_values(self, picking, pkg):
        """Validate one package for package-wise mode and return its freight values.

        Weight/class/NMFC/HazMat come from the package itself (not its products). NMFC must be 4 digits.
        """
        self._mc_validate_package(pkg)
        pt = pkg.package_type_id
        if not pkg.shipping_weight:
            raise UserError(_('Package "%s" has no Shipping Weight set.') % pkg.name)
        if not pkg.mycarrier_commodity_class:
            raise UserError(_('Package "%s" has no Freight Class set.') % pkg.name)
        nmfc = (pkg.mycarrier_commodity_nmfc or '').strip()
        if not nmfc:
            raise UserError(_('Package "%s" has no NMFC set.') % pkg.name)
        if not (nmfc.isdigit() and len(nmfc) == 4):
            raise UserError(_('Package "%s" has an invalid NMFC "%s". NMFC must be exactly 4 digits.') % (pkg.name, nmfc))
        return {
            'unit': _mc_unit_type_name(pt.name),
            'length': int(pt.packaging_length), 'width': int(pt.width), 'height': int(pt.height),
            'weight': max(1, int(math.ceil(self._mc_to_lb(pkg.shipping_weight)))),
            'freight_class': pkg.mycarrier_commodity_class,
            'nmfc': nmfc,
            'sub': (pkg.mycarrier_commodity_sub or '').strip(),
            'hazmat': bool(pkg.mycarrier_hazmat),
            'stackable': bool(pkg.mycarrier_stackable),
            'pieces': pkg.mycarrier_package_count or 1,
        }

    def _mc_check_all_lines_packaged(self, picking):
        """Package-wise mode quotes packages only: a quantity line outside a package would be dropped."""
        loose = picking.move_line_ids.filtered(lambda l: l.quantity > 0 and not l.result_package_id)
        if loose:
            raise UserError(_(
                'Package-wise quoting needs every line in a package. Not packaged: %s'
            ) % ', '.join(loose.mapped('product_id.display_name')))

    def _mc_handling_units(self, order=None, picking=None):
        # Package-based build when picking has assigned packages
        if picking:
            packages = self._mc_picking_packages(picking)
            if packages:
                mode = self.mycarrier_quote_build_mode or 'product'
                if mode == 'package':
                    return self._mc_build_units_package_wise(picking)
                return self._mc_build_units_product_wise(picking)

        # Fallback: per-move-line (no packages, or SO rating)
        units = []
        if order:
            lines = order.order_line
        elif picking:
            lines = picking.move_ids
        else:
            return units

        default_class = self.mycarrier_default_freight_class or '70'

        for line in lines:
            product = line.product_id
            if not product or product.type == 'service':
                continue

            if order:
                qty = line.product_uom_qty
            else:
                qty = line.quantity or line.product_uom_qty
            qty = int(math.ceil(qty))
            if qty <= 0:
                continue

            weight_lb = max(1, int(math.ceil(self._mc_to_lb(product.weight or 1.0) * qty)))
            freight_class = str(product.mycarrier_commodity_class or default_class)

            commodity = {
                'description': (product.name or 'Goods')[:500],
                'pieces': qty,
                'weight': weight_lb,
                'freightClass': freight_class,
                'packageType': 'BOX',
                'hazardous': False,
            }
            if product.mycarrier_commodity_nmfc:
                commodity['nmfc'] = product.mycarrier_commodity_nmfc[:6]
            if product.mycarrier_commodity_sub:
                commodity['nmfcSub'] = product.mycarrier_commodity_sub[:10]

            length = max(1, int(math.ceil(product.mycarrier_length or 48)))
            width = max(1, int(math.ceil(product.mycarrier_width or 40)))
            height = max(1, int(math.ceil(product.mycarrier_height or 48)))

            units.append({
                'count': 1,
                'length': length,
                'width': width,
                'height': height,
                'packageType': 'PLT',
                'stackable': False,
                'freightClass': freight_class,
                'commodities': [commodity],
            })

        return units

    def _mc_picking_accessorial_codes(self, picking):
        codes = []
        if not picking:
            return codes
        # Location types → accessorial codes
        if picking.origin_location_type:
            code = _MC_ORIGIN_LOCATION_CODES.get(picking.origin_location_type.name)
            if code:
                codes.append(code)
        if picking.dest_location_type:
            code = _MC_DEST_LOCATION_CODES.get(picking.dest_location_type.name)
            if code:
                codes.append(code)
        # Origin accessorials
        if picking.origin_inside_pickup:
            codes.append('INPU')
        if picking.origin_liftgate_pickup:
            codes.append('LGPU')
        if picking.origin_protect_from_freeze:
            codes.append('PFZ')
        if picking.origin_single_shipment:
            codes.append('SINGSHIP')
        if picking.origin_inbond_freight:
            codes.append('BOND')
        # Destination accessorials
        if picking.dest_delivery_appointment:
            codes.append('APPTDEL')
        if picking.dest_inside_delivery:
            codes.append('INDEL')
        if picking.dest_liftgate_delivery:
            codes.append('LGDEL')
        if picking.dest_notify_delivery:
            codes.append('NOTIFY')
        if picking.dest_sort_segregate_delivery:
            codes.append('SORTDEL')
        return codes

    def _mc_rate_payload(self, action, units, origin, destination, order_ref='', picking=None):
        total_weight = sum(
            hu['count'] * sum(c['weight'] for c in hu['commodities'])
            for hu in units
        )
        level = self.mycarrier_service_level if self.mycarrier_service_level in ('ALL', 'STD', 'GUR') else 'ALL'
        accessorial_codes = self._mc_picking_accessorial_codes(picking) if picking else []
        cargo_value = (getattr(picking, 'mycarrier_cargo_value', 0.0) or 0.0) if picking else 0.0
        return {
            'action': action,
            'paymentTerms': self.mycarrier_payment_terms or 'PREPAID',
            'carpetRollSquareYards': 0,
            'identifiers': {
                'orderId': [order_ref] if (order_ref and action == 'RATE_ONLY') else None,
                'referenceId': order_ref or None,
            },
            'service': {
                'mode': ['LTL'],
                'level': [level] if level != 'ALL' else ['ALL'],
                'carriers': None,
                'equipmentType': None,
            },
            'accessorials': {'codes': accessorial_codes},
            'stops': [origin, destination],
            'shippingDetails': {
                'weightUnit': 'LB',
                'dimensionsUnit': 'IN',
                'totalWeight': total_weight,
                'totalHandlingUnitCount': sum(hu['count'] for hu in units),
                'handlingUnits': units,
            },
            'fullValueCoverageDetails': {
                'monetaryValue': str(int(cargo_value)) if cargo_value else '0',
                'currency': 0,
            },
        }

    def _mc_filter_rates(self, rates):
        usable = []
        for r in (rates or []):
            si = r.get('statusInfo') or {}
            if (si.get('status') or '').lower() == 'error':
                continue
            cost = (r.get('priceDetails') or {}).get('totalCost') or 0
            if cost <= 0:
                continue
            svc = r.get('service') or {}
            if (svc.get('pricing') or '') == 'Brokerage' and not self.mycarrier_allow_brokerage:
                continue
            usable.append(r)
        # contract first, then cheapest
        usable.sort(key=lambda r: (
            (r.get('service') or {}).get('pricing') == 'Brokerage',
            (r.get('priceDetails') or {}).get('totalCost', 0),
        ))
        return usable

    # =========================================================================
    # Standard Odoo delivery.carrier interface
    # =========================================================================

    def mycarrier_rate_shipment(self, order):
        """Called from SO 'Add Shipping' button (RATE_ONLY — no quoteId saved)."""
        try:
            partner = order.partner_shipping_id
            pickup_dt = fields.Datetime.now()
            origin = self._mc_origin_stop(pickup_dt, picking=order)
            destination = self._mc_destination_stop(partner, pickup_dt, picking=order)
            units = self._mc_handling_units(order=order)

            if not units:
                return {
                    'success': False, 'price': 0.0,
                    'error_message': _('No shippable products on this order.'),
                    'warning_message': False,
                }

            payload = self._mc_rate_payload('RATE_ONLY', units, origin, destination, order.name, picking=order)
            _logger.debug('MC SO RATE PAYLOAD:\n%s', json.dumps(payload, indent=2))
            data, code = self._mc_call('POST', '/api/v1/quote/rate', payload)
            _logger.debug('MC SO RATE RESPONSE (HTTP %s):\n%s', code, json.dumps(data, indent=2))

            if code != 200:
                errors = data.get('errors') or []
                msg = '; '.join(str(e) for e in errors) or ('HTTP %s' % code)
                si = (data.get('data') or {}).get('statusInfo') or {}
                notes = [n.get('message', '') for n in (si.get('notes') or []) if n.get('message')]
                if notes:
                    msg += ' — ' + '; '.join(notes)
                _logger.warning('MC SO RATE FAILED: %s', msg)
                return {'success': False, 'price': 0.0, 'error_message': msg, 'warning_message': False}

            rates = (data.get('data') or {}).get('rates') or []
            usable = self._mc_filter_rates(rates)

            if not usable:
                return {
                    'success': False, 'price': 0.0,
                    'error_message': _('No rates available for this shipment.'),
                    'warning_message': False,
                }

            # Store all usable rates for the SO wizard rate list
            SoRate = self.env['mycarrier.so.rate']
            SoRate.search([('order_id', '=', order.id), ('carrier_id', '=', self.id)]).unlink()
            so_rate_fields = set(SoRate._fields)
            for r in usable:
                vals = self._mc_rate_to_wizard_vals(r)
                SoRate.create({
                    k: v for k, v in vals.items() if k in so_rate_fields
                    and k not in ('is_selected', 'charge_items_json')
                } | {'order_id': order.id, 'carrier_id': self.id})

            best = usable[0]
            price = best['priceDetails']['totalCost']
            svc = best.get('service') or {}
            transit = (best.get('appointmentDetails') or {}).get('transitDays', '')
            info = '%s %s' % (svc.get('carrier', ''), svc.get('level', ''))
            if transit:
                info += _(', %s day(s) transit') % transit

            return {'success': True, 'price': price, 'carrier_price': price, 'error_message': info, 'warning_message': False}

        except UserError as exc:
            _logger.warning('MC SO RATE UserError: %s', exc)
            return {'success': False, 'price': 0.0, 'error_message': str(exc), 'warning_message': False}
        except Exception as exc:
            _logger.exception('MC SO RATE unexpected error')
            return {'success': False, 'price': 0.0, 'error_message': str(exc), 'warning_message': False}

    def mycarrier_send_shipping(self, pickings):
        """Called when delivery picking is validated. Dispatches the pre-selected rate."""
        res = []
        for picking in pickings:
            # Guard: already dispatched (e.g. user clicked Dispatch button then also clicked Validate)
            if picking.mycarrier_status == 'dispatched':
                res.append({
                    'exact_price': picking.mycarrier_total_cost or 0.0,
                    'tracking_number': picking.carrier_tracking_ref or '',
                })
                continue

            if not picking.mycarrier_selected_carrier:
                raise UserError(_(
                    'Please select a MyCarrier rate before dispatching.'
                ))
            if self.mycarrier_create_quote and picking.mycarrier_status != 'rated':
                raise UserError(_(
                    'Click Dispatch to MyCarrier and confirm a rate before validating.'
                ))

            # Build order payload with selected carrier + readyToDispatch: YES
            carrier_service = self._MC_CARRIER_SERVICE.get(
                picking.mycarrier_selected_level or '', 'Standard'
            )
            units = self._mc_order_quote_units(picking)
            payload = self._mc_build_dispatch_order_payload(picking, units, carrier_service)
            _logger.debug('MC DISPATCH ORDER PAYLOAD:\n%s', json.dumps(payload, indent=2))
            data, code = self._mc_call('POST', '/api/v1/orders', payload)
            _logger.debug('MC DISPATCH ORDER RESPONSE (HTTP %s):\n%s', code, json.dumps(data, indent=2))

            if code not in (200, 201) or not data.get('isSuccess'):
                errors = data.get('errorMessages') or data.get('errors') or [str(data)]
                raise UserError(_('MyCarrier dispatch failed: %s') % '; '.join(str(e) for e in errors))

            d = data.get('data') or {}
            orders = d.get('orders') or [{}]
            order_data = orders[0] if orders else {}
            mc_order_id = str(order_data.get('orderId') or d.get('orderId') or '')
            pro = order_data.get('proNumber') or d.get('proNumber') or ''
            bol_number = order_data.get('bolNumber') or d.get('bolNumber') or ''
            pickup_number = order_data.get('pickupNumber') or d.get('pickupNumber') or ''

            picking.write({
                'mycarrier_shipment_id': mc_order_id,
                'mycarrier_pro_number': pro,
                'mycarrier_bol_number': bol_number,
                'mycarrier_pickup_number': pickup_number,
                'mycarrier_security_key': '',
                'mycarrier_tracking_url': '',
                'mycarrier_bol_url': '',
                'carrier_tracking_ref': pro or mc_order_id or picking.name,
                'mycarrier_status': 'dispatched',
            })

            # BOL not available immediately via Order API — arrives via webhook/PRO lookup
            attachments = []
            bol_url = ''
            tracking_url = ''

            # Build rich chatter log with Markup so HTML renders correctly
            charge_items = json.loads(picking.mycarrier_charge_items or '[]')
            body = Markup('<b>✓ MyCarrier Shipment Dispatched</b><br/><br/>')
            body += Markup('<b>Carrier:</b> %s') % escape(
                picking.mycarrier_selected_carrier or '—'
            )
            if picking.mycarrier_selected_level:
                body += Markup(' &nbsp;(%s)') % escape(picking.mycarrier_selected_level)
            body += Markup('<br/>')
            if pro:
                body += Markup('<b>PRO Number:</b> %s<br/>') % escape(pro)
            if bol_number:
                body += Markup('<b>BOL Number:</b> %s<br/>') % escape(bol_number)
            if pickup_number:
                body += Markup('<b>Pickup Confirmation:</b> %s<br/>') % escape(pickup_number)
            if tracking_url:
                body += Markup('<b>Tracking:</b> <a href="%s" target="_blank">%s</a><br/>') % (
                    escape(tracking_url), escape(tracking_url)
                )
            if bol_url:
                body += Markup('<b>BOL:</b> <a href="%s" target="_blank">Download PDF</a><br/>') % escape(bol_url)

            if charge_items:
                body += Markup('<br/><b>Cost Breakdown:</b>')
                body += Markup(
                    '<table style="border-collapse:collapse;margin-top:6px;font-size:13px">'
                    '<tr style="background:#f5f5f5">'
                    '<th style="text-align:left;padding:4px 10px;border:1px solid #ddd">Code</th>'
                    '<th style="text-align:left;padding:4px 10px;border:1px solid #ddd">Description</th>'
                    '<th style="text-align:right;padding:4px 10px;border:1px solid #ddd">Amount (USD)</th>'
                    '</tr>'
                )
                for ci in charge_items:
                    body += Markup(
                        '<tr>'
                        '<td style="padding:3px 10px;border:1px solid #ddd">%s</td>'
                        '<td style="padding:3px 10px;border:1px solid #ddd">%s</td>'
                        '<td style="text-align:right;padding:3px 10px;border:1px solid #ddd">$%.2f</td>'
                        '</tr>'
                    ) % (
                        ci.get('code', ''),
                        ci.get('description') or ci.get('name') or '',
                        float(ci.get('amount', 0.0)),
                    )
                body += Markup(
                    '<tr style="font-weight:bold;background:#f5f5f5">'
                    '<td colspan="2" style="padding:4px 10px;border:1px solid #ddd">Total</td>'
                    '<td style="text-align:right;padding:4px 10px;border:1px solid #ddd">$%.2f</td>'
                    '</tr></table>'
                ) % picking.mycarrier_total_cost

            picking.message_post(body=body, attachments=attachments)

            res.append({
                'exact_price': picking.mycarrier_total_cost or 0.0,
                'tracking_number': pro or mc_order_id or '',
            })
        return res

    def mycarrier_get_tracking_link(self, picking):
        return picking.mycarrier_tracking_url or ''

    def mycarrier_cancel_shipment(self, picking):
        raise UserError(_(
            'MyCarrier does not expose a cancellation endpoint via the Public API. '
            'Please cancel the shipment manually at mycarriertms.com.'
        ))

    def mycarrier_return_shipment(self, picking, quantity=None):
        raise UserError(_(
            'Return shipments are not supported via the MyCarrier Public API. '
            'Please create a return manually at mycarriertms.com.'
        ))

    # =========================================================================
    # Dispatch payload
    # =========================================================================

    def _mc_build_dispatch_payload(self, picking):
        partner = picking.partner_id
        pickup_dt = picking.scheduled_date or fields.Datetime.now()

        origin = self._mc_origin_stop(pickup_dt, picking=picking)
        destination = self._mc_destination_stop(partner, pickup_dt, picking=picking)
        units = self._mc_handling_units(picking=picking)

        total_weight = sum(
            hu['count'] * sum(c['weight'] for c in hu['commodities'])
            for hu in units
        )
        charge_items = json.loads(picking.mycarrier_charge_items or '[]')

        return {
            'mode': 'MANUAL_DISPATCH',
            'paymentTerms': self.mycarrier_payment_terms or 'PREPAID',
            'identifiers': {
                'quoteId': int(picking.mycarrier_quote_id) if (picking.mycarrier_quote_id or '').isdigit() else None,
                'carrierQuoteNumber': picking.mycarrier_carrier_quote_number,
                'orderId': [picking.name],
                'referenceNumber': picking.name,
                'poNumber': picking.mycarrier_po_number or None,
                'bolNumber': picking.mycarrier_customer_bol_number or None,
                'shipmentId': None,
                'gS1CompanyPrefix': None,
            },
            'specialInstructions': picking.mycarrier_special_instructions or '',
            'service': {
                'carrier': picking.mycarrier_selected_carrier,
                'mode': 'LTL',
                'level': picking.mycarrier_selected_level,
                'vicsBol': False,
            },
            'priceDetails': {
                'totalCost': picking.mycarrier_total_cost,
                'chargeItems': charge_items,
            },
            'stops': [origin, destination],
            'shippingDetails': {
                'weightUnit': 'LB',
                'dimensionsUnit': 'IN',
                'totalWeight': total_weight,
                'totalHandlingUnitCount': sum(hu['count'] for hu in units),
                'handlingUnits': units,
            },
        }

    def _mc_build_dispatch_order_payload(self, picking, units, carrier_service):
        """Build POST /api/v1/orders payload with carrier selected + readyToDispatch: YES."""
        pickup_dt = picking.scheduled_date or fields.Datetime.now()
        now = fields.Datetime.now()
        hour = now.hour % 12 or 12
        ampm = 'AM' if now.hour < 12 else 'PM'
        time_created = '%s %d:%02d %s' % (now.strftime('%m/%d/%Y'), hour, now.minute, ampm)
        payment_dir = self._MC_PAYMENT_DIR.get(self.mycarrier_payment_terms or 'PREPAID', 'Prepaid')
        return {
            'orders': [{
                'quoteReferenceID': picking.name,
                'serviceType': 'LTL',
                'paymentDirection': payment_dir,
                'pickupDate': pickup_dt.strftime('%m/%d/%Y'),
                'timeCreated': time_created,
                'readyToDispatch': 'YES',
                'carrier': picking.mycarrier_selected_carrier or '',
                'carrierService': carrier_service,
                'transitDays': str(picking.mycarrier_transit_days or ''),
                'accountNumber': '',
                'cargoValue': '',
                'specialInstructions': picking.mycarrier_special_instructions or '',
                'isVicsBol': 'NO',
                'vicsBolPrefix': '',
                'proNumber': '',
                'emergencyContactPersonName': '',
                'emergencyContactPhone': '',
                'references': {
                    'poNumber': picking.mycarrier_po_number or '',
                    'referenceNumber': picking.name,
                    'customerBOLNumber': picking.mycarrier_customer_bol_number or '',
                },
                'originStop': self._mc_order_origin_stop(picking),
                'destinationStop': self._mc_order_dest_stop(picking),
                'originAccessorials': self._mc_order_origin_accessorials(picking),
                'destinationAccessorials': self._mc_order_dest_accessorials(picking),
                'quoteUnits': units,
            }]
        }

    # =========================================================================
    # Orders API helpers (/api/v1/orders format — different from rate API)
    # =========================================================================

    _MC_PAYMENT_DIR = {'PREPAID': 'Prepaid', 'COLLECT': 'Collect', 'THIRD_PARTY': 'ThirdParty'}

    _MC_CARRIER_SERVICE = {
        'STD': 'Standard',
        'GUR': 'Afternoon Guaranteed',
        'GUR_NOON': 'Morning Guaranteed',
        'GUR_AM': 'Morning Guaranteed',
    }

    @staticmethod
    def _mc_phone(partner):
        # NANP numbers -> "(703)307-8250"; anything else is passed through.
        raw = partner.phone or partner.mobile or ''
        digits = ''.join(ch for ch in raw if ch.isdigit())
        if len(digits) == 11 and digits[0] == '1':
            digits = digits[1:]
        if len(digits) == 10:
            return '(%s)%s-%s' % (digits[:3], digits[3:6], digits[6:])
        return raw[:20]

    @staticmethod
    def _mc_order_zip(partner):
        # Orders API/portal needs the Canadian "A1A 1A1" form; US zips stay as-is.
        zip_ = (partner.zip or '').replace(' ', '').upper()
        if partner.country_id.code == 'CA' and len(zip_) == 6:
            return '%s %s' % (zip_[:3], zip_[3:])
        return zip_

    def _mc_order_origin_stop(self, picking):
        warehouse = picking.picking_type_id.warehouse_id
        partner = (warehouse.partner_id if warehouse else None) or picking.company_id.partner_id
        name_parts = (partner.name or 'Shipper').split()
        return {
            'locationID': self.mycarrier_origin_location_id.location_id or '',
            'companyName': (partner.parent_id.name if partner.parent_id else partner.name) or '',
            'streetLine1': (partner.street or '')[:200],
            'streetLine2': (partner.street2 or '')[:200],
            'city': (partner.city or '')[:100],
            'state': (partner.state_id.code or '')[:2],
            'zip': self._mc_order_zip(partner),
            'country': _COUNTRY_MAP.get(partner.country_id.code or 'US', 'USA'),
            'locationType': picking.origin_location_type.name if picking.origin_location_type else 'Business',
            'contactFirstName': name_parts[0] if name_parts else 'Contact',
            'contactLastName': name_parts[-1] if len(name_parts) > 1 else 'NA',
            'contactPhone': self._mc_phone(partner),
            'ext': '',
            'contactEmail': (partner.email or '')[:320],
            'readyTime': '8:00 AM',
            'closeTime': '4:30 PM',
            'instructions': picking.mycarrier_special_instructions or '',
        }

    def _mc_order_dest_stop(self, picking):
        partner = picking.partner_id
        name_parts = (partner.name or 'Consignee').split()
        return {
            'companyName': (partner.parent_id.name if partner.parent_id else partner.name) or '',
            'streetLine1': (partner.street or '')[:200],
            'streetLine2': (partner.street2 or '')[:200],
            'city': (partner.city or '')[:100],
            'state': (partner.state_id.code or '')[:2],
            'zip': self._mc_order_zip(partner),
            'country': _COUNTRY_MAP.get(partner.country_id.code or 'US', 'USA'),
            'locationType': picking.dest_location_type.name if picking.dest_location_type else 'Business',
            'contactFirstName': name_parts[0] if name_parts else 'Contact',
            'contactLastName': name_parts[-1] if len(name_parts) > 1 else 'NA',
            'contactPhone': self._mc_phone(partner),
            'ext': '',
            'contactEmail': (partner.email or '')[:320],
            'readyTime': '9:00 AM',
            'closeTime': '5:00 PM',
            'instructions': '',
        }

    def _mc_order_origin_accessorials(self, picking):
        return {
            'liftgatePickup': 'YES' if picking.origin_liftgate_pickup else 'NO',
            'insidePickup': 'YES' if picking.origin_inside_pickup else 'NO',
            'protectFromFreeze': 'YES' if picking.origin_protect_from_freeze else 'NO',
            'singleShipment': 'YES' if picking.origin_single_shipment else 'NO',
            'inBondFreight': 'YES' if picking.origin_inbond_freight else 'NO',
            'thresholdPickup': 'NO',
            'twoPersonPickup': 'NO',
            'whiteGlovePickup': 'NO',
        }

    def _mc_order_dest_accessorials(self, picking):
        return {
            'liftgateDelivery': 'YES' if picking.dest_liftgate_delivery else 'NO',
            'deliveryAppointment': 'YES' if picking.dest_delivery_appointment else 'NO',
            'notifyBeforeDelivery': 'YES' if picking.dest_notify_delivery else 'NO',
            'insideDelivery': 'YES' if picking.dest_inside_delivery else 'NO',
            'sortOrSegregateDelivery': 'YES' if picking.dest_sort_segregate_delivery else 'NO',
            'thresholdDelivery': 'NO',
            'twoPersonDelivery': 'NO',
            'whiteGloveDelivery': 'NO',
        }

    def _mc_order_quote_units(self, picking):
        """Build quoteUnits for /api/v1/orders. Routes to package/product/line mode."""
        packages = self._mc_picking_packages(picking)
        if packages:
            mode = self.mycarrier_quote_build_mode or 'product'
            if mode == 'package':
                return self._mc_order_units_package_wise(picking)
            return self._mc_order_units_product_wise(picking)
        return self._mc_order_units_line_wise(picking)

    def _mc_order_units_package_wise(self, picking):
        """Orders API: one quoteUnit per physical package."""
        self._mc_check_all_lines_packaged(picking)
        units = []
        for pkg in self._mc_picking_packages(picking):
            v = self._mc_package_wise_values(picking, pkg)
            units.append({
                'shippingUnitType': v['unit'],
                'shippingUnitCount': '1',
                'unitLength': str(v['length']),
                'unitWidth': str(v['width']),
                'unitHeight': str(v['height']),
                'unitStackable': 'YES' if v['stackable'] else 'NO',
                'quoteCommodities': [{
                    'commodityDescription': pkg.name[:500],
                    'commodityClass': v['freight_class'],
                    'commodityWeight': str(v['weight']),
                    'commodityPieces': str(v['pieces']),
                    'commodityPackingType': 'Box',
                    'commodityNMFC': v['nmfc'],
                    'commoditySub': v['sub'],
                    'commodityHazMat': 'YES' if v['hazmat'] else 'NO',
                    'customerOrderNumber': picking.name,
                }],
            })
        return units

    def _mc_order_units_product_wise(self, picking):
        """Orders API: group packages by Package Type; commodities from product lines."""
        packages = self._mc_picking_packages(picking)
        for pkg in packages:
            self._mc_validate_package(pkg)

        default_class = self.mycarrier_default_freight_class or '70'
        packages_by_type = {}
        for pkg in packages:
            packages_by_type.setdefault(pkg.package_type_id, []).append(pkg)

        units = []
        for pt, type_pkgs in packages_by_type.items():
            commodities = []
            for pkg in type_pkgs:
                lines = picking.move_line_ids.filtered(
                    lambda l, p=pkg: l.result_package_id == p and l.quantity > 0
                )
                for line in lines:
                    product = line.product_id
                    if not product or product.type == 'service':
                        continue
                    weight = max(1, int(math.ceil(self._mc_to_lb(product.weight or 1.0) * line.quantity)))
                    commodities.append({
                        'commodityDescription': (product.name or 'Goods')[:500],
                        'commodityClass': str(product.mycarrier_commodity_class or default_class),
                        'commodityWeight': str(weight),
                        'commodityPieces': str(int(line.quantity)),
                        'commodityPackingType': 'Box',
                        'commodityNMFC': product.mycarrier_commodity_nmfc or '',
                        'commoditySub': product.mycarrier_commodity_sub or '',
                        'commodityHazMat': 'NO',
                        'customerOrderNumber': picking.name,
                    })
            if not commodities:
                continue
            units.append({
                'shippingUnitType': _mc_unit_type_name(pt.name),
                'shippingUnitCount': str(len(type_pkgs)),
                'unitLength': str(int(pt.packaging_length)),
                'unitWidth': str(int(pt.width)),
                'unitHeight': str(int(pt.height)),
                'unitStackable': 'NO',
                'quoteCommodities': commodities,
            })
        return units

    def _mc_order_units_line_wise(self, picking):
        """Orders API: fallback when no packages — one quoteUnit per move line."""
        default_class = self.mycarrier_default_freight_class or '70'
        units = []
        for move in picking.move_ids:
            product = move.product_id
            if not product or product.type == 'service':
                continue
            qty = int(math.ceil(move.quantity or move.product_uom_qty))
            if qty <= 0:
                continue
            weight_lb = max(1, int(math.ceil(self._mc_to_lb(product.weight or 1.0) * qty)))
            freight_class = str(product.mycarrier_commodity_class or default_class)
            units.append({
                'shippingUnitType': 'Pallet',
                'shippingUnitCount': str(qty),
                'unitLength': str(max(1, int(math.ceil(product.mycarrier_length or 48)))),
                'unitWidth': str(max(1, int(math.ceil(product.mycarrier_width or 40)))),
                'unitHeight': str(max(1, int(math.ceil(product.mycarrier_height or 48)))),
                'unitStackable': 'NO',
                'quoteCommodities': [{
                    'commodityDescription': (product.name or 'Goods')[:500],
                    'commodityClass': freight_class,
                    'commodityWeight': str(weight_lb),
                    'commodityPieces': str(qty),
                    'commodityPackingType': 'Box',
                    'commodityNMFC': product.mycarrier_commodity_nmfc or '',
                    'commoditySub': product.mycarrier_commodity_sub or '',
                    'commodityHazMat': 'NO',
                    'customerOrderNumber': picking.name,
                }],
            })
        return units

    # =========================================================================
    # Button 1: Create MyCarrier Order → POST /api/v1/orders
    # =========================================================================

    def mycarrier_action_create_order(self, picking):
        if not self.mycarrier_origin_location_id:
            raise UserError(_('Origin Location is not configured. Sync locations and select one on the carrier.'))

        units = self._mc_order_quote_units(picking)
        if not units:
            raise UserError(_('No shippable products found on this picking.'))

        pickup_dt = picking.scheduled_date or fields.Datetime.now()
        now = fields.Datetime.now()
        hour = now.hour % 12 or 12
        ampm = 'AM' if now.hour < 12 else 'PM'
        time_created = '%s %d:%02d %s' % (now.strftime('%m/%d/%Y'), hour, now.minute, ampm)
        payment_dir = self._MC_PAYMENT_DIR.get(self.mycarrier_payment_terms or 'PREPAID', 'Prepaid')

        payload = {
            'orders': [{
                'quoteReferenceID': picking.name,
                'serviceType': 'LTL',
                'paymentDirection': payment_dir,
                'pickupDate': pickup_dt.strftime('%m/%d/%Y'),
                'timeCreated': time_created,
                'readyToDispatch': 'NO',
                'carrier': '',
                'carrierService': '',
                'transitDays': '',
                'accountNumber': '',
                'cargoValue': '',
                'specialInstructions': picking.mycarrier_special_instructions or '',
                'isVicsBol': 'NO',
                'vicsBolPrefix': '',
                'proNumber': '',
                'emergencyContactPersonName': '',
                'emergencyContactPhone': '',
                'references': {
                    'poNumber': picking.mycarrier_po_number or '',
                    'referenceNumber': picking.name,
                    'customerBOLNumber': picking.mycarrier_customer_bol_number or '',
                },
                'originStop': self._mc_order_origin_stop(picking),
                'destinationStop': self._mc_order_dest_stop(picking),
                'originAccessorials': self._mc_order_origin_accessorials(picking),
                'destinationAccessorials': self._mc_order_dest_accessorials(picking),
                'quoteUnits': units,
            }]
        }

        data, code = self._mc_call('POST', '/api/v1/orders', payload)
        _logger.debug('MC CREATE ORDER RESPONSE (HTTP %s):\n%s', code, json.dumps(data, indent=2))

        if code not in (200, 201) or not data.get('isSuccess'):
            errors = data.get('errorMessages') or data.get('errors') or [str(data)]
            raise UserError(_('MyCarrier order creation failed: %s') % '; '.join(str(e) for e in errors))

        picking.write({
            'mycarrier_status': 'ordered',
        })
        # tracking=True on mycarrier_status auto-posts the status change to chatter;
        # returning False causes the form view to reload and show the updated status bar.
        return False

    def _mc_validate_phones(self, picking):
        dest = picking.partner_id
        if not (dest.phone or dest.mobile):
            raise UserError(_(
                'Consignee "%s" has no phone number. Add a phone on the contact before proceeding.'
            ) % dest.name)
        warehouse = picking.picking_type_id.warehouse_id
        origin_partner = (warehouse.partner_id if warehouse else None) or picking.company_id.partner_id
        if not (origin_partner.phone or origin_partner.mobile):
            raise UserError(_(
                'Origin contact "%s" has no phone number. Add a phone on the warehouse/company contact.'
            ) % origin_partner.name)

    def mycarrier_action_post_rated_order(self, picking):
        """After rate selection: POST /api/v1/orders with selected carrier, readyToDispatch: NO."""
        self._mc_validate_phones(picking)
        carrier_service = self._MC_CARRIER_SERVICE.get(
            picking.mycarrier_selected_level or '', 'Standard'
        )
        units = self._mc_order_quote_units(picking)
        payload = self._mc_build_dispatch_order_payload(picking, units, carrier_service)
        payload['orders'][0]['readyToDispatch'] = 'NO'
        _logger.debug('MC RATED ORDER PAYLOAD:\n%s', json.dumps(payload, indent=2))
        data, code = self._mc_call('POST', '/api/v1/orders', payload)
        _logger.debug('MC RATED ORDER RESPONSE (HTTP %s):\n%s', code, json.dumps(data, indent=2))
        if code not in (200, 201) or not data.get('isSuccess'):
            errors = data.get('errorMessages') or data.get('errors') or [str(data)]
            raise UserError(_('MyCarrier order post failed: %s') % '; '.join(str(e) for e in errors))

    def mycarrier_action_update_order(self, picking):
        """Re-submit order to MyCarrier with updated details, clearing any stale rate selection."""
        self.mycarrier_action_create_order(picking)
        picking.write({
            'mycarrier_carrier_quote_number': False,
            'mycarrier_selected_carrier': False,
            'mycarrier_selected_level': False,
            'mycarrier_total_cost': 0.0,
            'mycarrier_charge_items': False,
            'mycarrier_rates_json': False,
            'mycarrier_rated_at': False,
        })
        picking.message_post(body=_(
            'MyCarrier order updated. Previous rate selection cleared — '
            'click <b>Select Rate</b> for fresh quotes.'
        ))
        return False

    # =========================================================================
    # Button 2: Select Rate → POST /api/v1/quote/rate (RATE_ONLY + orderId)
    # =========================================================================

    def mycarrier_action_select_rate(self, picking):
        partner = picking.partner_id
        pickup_dt = picking.scheduled_date or fields.Datetime.now()
        origin = self._mc_origin_stop(pickup_dt, picking=picking)
        destination = self._mc_destination_stop(partner, pickup_dt, picking=picking)
        units = self._mc_handling_units(picking=picking)

        if not units:
            raise UserError(_('No shippable products found on this picking.'))

        payload = self._mc_rate_payload(
            'RATE_AND_SAVE' if self.mycarrier_create_quote else 'RATE_ONLY', units, origin, destination,
            order_ref=picking.name, picking=picking,
        )
        _logger.debug('MC RATE PAYLOAD:\n%s', json.dumps(payload, indent=2))
        data, code = self._mc_call('POST', '/api/v1/quote/rate', payload)
        _logger.debug('MC RATE RESPONSE (HTTP %s):\n%s', code, json.dumps(data, indent=2))
        _logger.debug('MC RATE top-level keys: %s', list(data.keys()))
        if data.get('data'):
            _logger.debug('MC RATE data keys: %s', list((data['data'] or {}).keys()))

        if code != 200:
            si = (data.get('data') or {}).get('statusInfo') or {}
            notes = [n.get('message', '') for n in (si.get('notes') or []) if n.get('message')]
            msg = '; '.join(str(e) for e in (data.get('errors') or [])) or ('HTTP %s' % code)
            if notes:
                msg += ' — ' + '; '.join(notes)
            raise UserError(_('MyCarrier rate request failed: %s') % msg)

        all_rates = (data.get('data') or {}).get('rates') or []
        usable = self._mc_filter_rates(all_rates)

        if not usable:
            error_lines = []
            for r in all_rates:
                svc = r.get('service') or {}
                si = r.get('statusInfo') or {}
                notes = [n.get('message', '') for n in (si.get('notes') or []) if n.get('message')]
                line = '%s %s: %s' % (svc.get('carrier', '?'), svc.get('level', ''), si.get('message', 'unknown'))
                if notes:
                    line += ' — ' + '; '.join(notes)
                error_lines.append(line)
            raise UserError(_('No usable rates returned.\n%s') % '\n'.join(error_lines))

        # Default = previous step's selection: this delivery's own earlier choice, else the SO's, else cheapest
        previous = [
            (picking.mycarrier_selected_carrier, picking.mycarrier_selected_level),
            (picking.sale_id.mycarrier_selected_carrier, picking.sale_id.mycarrier_selected_level)
            if getattr(picking, 'sale_id', None) else (False, False),
        ]
        so_match = None
        for scac, level in previous:
            so_match = next((
                r for r in usable
                if scac and (r.get('service') or {}).get('carrier') == scac
                and (r.get('service') or {}).get('level') == level
            ), None)
            if so_match:
                break

        # Try every known location for quoteId in the RATE_ONLY response
        d = data.get('data') or {}
        first_rate = (d.get('rates') or all_rates or [{}])[0]
        api_quote_id = str(
            d.get('quoteId')
            or data.get('quoteId')
            or (first_rate.get('identifiers') or {}).get('quoteId')
            or first_rate.get('quoteId')
            or picking.name
        )
        _logger.debug('MC quoteId resolved to: %r (from rate response)', api_quote_id)
        wizard = self.env['mycarrier.choose.rate'].create({
            'picking_id': picking.id,
            'carrier_id': self.id,
            'quote_id': api_quote_id,
            'rate_line_ids': [
                (0, 0, self._mc_rate_to_wizard_vals(
                    r,
                    is_default=(r is so_match) if so_match else (idx == 0),
                ))
                for idx, r in enumerate(usable)
            ],
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'mycarrier.choose.rate',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
            'name': _('Select MyCarrier Rate'),
        }

    # =========================================================================
    # Quotes (provider option "Create MyCarrier Quote")
    # =========================================================================

    def _mc_rate_and_save(self, ref, units, origin, destination, record):
        """POST /quote/rate RATE_AND_SAVE (SO or delivery as `record`): stores a quote at MyCarrier.

        Returns (quote_id, usable rates). Every call creates a new quote id.
        """
        payload = self._mc_rate_payload('RATE_AND_SAVE', units, origin, destination, ref, picking=record)
        _logger.debug('MC SAVE QUOTE PAYLOAD:\n%s', json.dumps(payload, indent=2))
        data, code = self._mc_call('POST', '/api/v1/quote/rate', payload)
        _logger.debug('MC SAVE QUOTE RESPONSE (HTTP %s):\n%s', code, json.dumps(data, indent=2))
        d = data.get('data') or {}
        if code != 200:
            notes = [n.get('message', '') for n in ((d.get('statusInfo') or {}).get('notes') or []) if n.get('message')]
            msg = '; '.join(str(e) for e in (data.get('errors') or [])) or ('HTTP %s' % code)
            raise UserError(_('MyCarrier quote request failed: %s') % (msg + (' — ' + '; '.join(notes) if notes else '')))
        usable = self._mc_filter_rates(d.get('rates') or [])
        if not usable:
            raise UserError(_('MyCarrier returned no usable rates for this quote.'))
        return str(d.get('quoteId') or ''), usable

    @staticmethod
    def _mc_find_rate(usable, scac, level):
        return next((
            r for r in usable
            if scac and (r.get('service') or {}).get('carrier') == scac and (r.get('service') or {}).get('level') == level
        ), None)

    def mycarrier_create_so_quote(self, order, scac, level):
        """Create Quote on the SO: save the quote at MyCarrier and return the selected rate's quote data."""
        pickup_dt = fields.Datetime.now()
        units = self._mc_handling_units(order=order)
        if not units:
            raise UserError(_('No shippable products on this order.'))
        quote_id, usable = self._mc_rate_and_save(
            order.name, units,
            self._mc_origin_stop(pickup_dt, picking=order),
            self._mc_destination_stop(order.partner_shipping_id, pickup_dt, picking=order), order,
        )
        rate = self._mc_find_rate(usable, scac, level)
        if not rate:
            raise UserError(_('The selected rate (%s %s) is no longer offered. Please get the rates again.') % (scac, level))
        vals = self._mc_rate_to_wizard_vals(rate)
        return {
            'quote_id': quote_id,
            'carrier_quote_number': vals['carrier_quote_number'],
            'price': vals['total_cost'],
        }

    def _mc_rate_change_message(self, picking, scac, level, price):
        """Warning text when the delivery's rate differs from what was selected on the sales order."""
        order = getattr(picking, 'sale_id', None)
        if not order or not order.mycarrier_selected_carrier:
            return ''
        notes = []
        if (scac, level) != (order.mycarrier_selected_carrier, order.mycarrier_selected_level):
            notes.append(_('carrier/service %(new)s instead of %(old)s') % {
                'new': '%s %s' % (scac, level),
                'old': '%s %s' % (order.mycarrier_selected_carrier, order.mycarrier_selected_level)})
        if abs((price or 0.0) - order.mycarrier_selected_price) > 0.005:
            notes.append(_('price %(new).2f instead of %(old).2f on the sales order') % {
                'new': price or 0.0, 'old': order.mycarrier_selected_price})
        return (_('Rate changed since the sales order: ') + '; '.join(notes)) if notes else ''

    def mycarrier_action_update_quote(self, picking):
        """Delivery: re-save the quote with the delivery's real data, keeping the previously chosen carrier/service."""
        self._mc_validate_phones(picking)
        pickup_dt = picking.scheduled_date or fields.Datetime.now()
        units = self._mc_handling_units(picking=picking)
        if not units:
            raise UserError(_('No shippable products found on this picking.'))
        quote_id, usable = self._mc_rate_and_save(
            picking.name, units,
            self._mc_origin_stop(pickup_dt, picking=picking),
            self._mc_destination_stop(picking.partner_id, pickup_dt, picking=picking), picking,
        )
        order = picking.sale_id
        rate = (
            self._mc_find_rate(usable, picking.mycarrier_selected_carrier, picking.mycarrier_selected_level)
            or self._mc_find_rate(usable, order.mycarrier_selected_carrier, order.mycarrier_selected_level)
        )
        missing = not rate
        rate = rate or usable[0]
        svc = rate.get('service') or {}
        vals = self._mc_rate_to_wizard_vals(rate)
        picking.write({
            'mycarrier_quote_id': quote_id,
            'mycarrier_carrier_quote_number': vals['carrier_quote_number'],
            'mycarrier_selected_carrier': svc.get('carrier', ''),
            'mycarrier_selected_level': svc.get('level', ''),
            'mycarrier_transit_days': vals['transit_days'],
            'mycarrier_total_cost': vals['total_cost'],
            'mycarrier_charge_items': vals['charge_items_json'],
            'mycarrier_rated_at': fields.Datetime.now(),
            # a refreshed quote has to be confirmed again in the Dispatch wizard
            'mycarrier_status': 'pending' if picking.mycarrier_status == 'rated' else picking.mycarrier_status,
        })
        warning = self._mc_rate_change_message(picking, svc.get('carrier', ''), svc.get('level', ''), vals['total_cost'])
        if missing and order.mycarrier_selected_carrier:
            warning = (_('The sales order rate (%s %s) is no longer offered; the lowest rate was used. ')
                       % (order.mycarrier_selected_carrier, order.mycarrier_selected_level)) + warning
        body = _('MyCarrier quote updated: quote %(q)s, %(c)s %(l)s, %(p).2f') % {
            'q': quote_id, 'c': svc.get('carrier', ''), 'l': svc.get('level', ''), 'p': vals['total_cost']}
        picking.message_post(body=body + (' — ' + warning if warning else ''))
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {
                'title': _('MyCarrier quote updated'),
                'message': warning or body,
                'type': 'warning' if warning else 'success',
                'sticky': bool(warning),
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    def _mc_rate_to_wizard_vals(self, rate, is_default=False):
        svc = rate.get('service') or {}
        price = rate.get('priceDetails') or {}
        appt = rate.get('appointmentDetails') or {}
        del_appt = appt.get('delivery') or {}
        ident = rate.get('identifiers') or {}
        charge_items = price.get('chargeItems') or []

        has_unkchrg = any((ci.get('code') or '') == 'UNKCHRG' for ci in charge_items)
        level = svc.get('level', '')
        guar_time = del_appt.get('guaranteedTime', '')
        if not level.startswith('GUR') or guar_time in ('', '00:00'):
            guar_time = ''

        label = _LEVEL_LABELS.get(level, level)
        if guar_time:
            label = '%s (by %s)' % (label, guar_time)

        transit_days = appt.get('transitDays') or 0
        est_delivery = ''
        if transit_days:
            est_delivery = (date.today() + timedelta(days=transit_days)).strftime('%b %d, %Y')
        return {
            'is_selected': is_default,
            'carrier_scac': svc.get('carrier', ''),
            'service_level': level,
            'service_level_label': label,
            'pricing_type': svc.get('pricing', ''),
            'total_cost': price.get('totalCost', 0.0),
            'currency_code': price.get('currency', 'USD'),
            'transit_days': transit_days,
            'estimated_delivery': est_delivery,
            'quote_expiry': appt.get('quoteExpirationDate') or '',
            'carrier_quote_number': ident.get('carrierQuoteNumber', ''),
            'charge_items_json': json.dumps(charge_items),
            'has_unknown_charge': has_unkchrg,
        }

    # =========================================================================
    # Location sync
    # =========================================================================

    def mycarrier_action_sync_locations(self):
        self.ensure_one()
        data, code = self._mc_call('GET', '/api/v1/address/shipping-locations?skip=0&take=100')
        if code != 200:
            raise UserError(_('Failed to fetch locations (HTTP %s): %s') % (code, data))

        payload_data = data.get('data') or {}
        items = payload_data.get('shippingLocations') or []

        Location = self.env['mycarrier.location']
        for loc in items:
            Location.create_or_update(loc, self.id)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Locations Synced'),
                'message': _('%d location(s) synced from MyCarrier.') % len(items),
                'type': 'success',
                'sticky': False,
            },
        }
