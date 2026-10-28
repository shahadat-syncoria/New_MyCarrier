# -*- coding: utf-8 -*-

{
    'name': 'Syncoria POS Moneris Terminal',
    'summary': 'Syncoria POS Moneris Terminal',
    'description': """
        Payment method on POS with Moneris Go terminal
    """,
    'category': 'pos',
    
    "author": "Syncoria Inc.",
    "website": "https://www.syncoria.com",
    "company": "Syncoria Inc.",
    "maintainer": "Syncoria Inc.",
    "license": "OPL-1",
    "support": "support@syncoria.com",
    "price": 5000,
    "currency": "USD",
    'depends': [
        'os_payment_pos'
    ],
    'sequence': 4,

    'data': [
        # data
        'data/ir_config_parameters.xml',
        'data/pos_payment_methods.xml',

        # report

        # security

        # wizard

        # views
        'views/pos_payment_method_views.xml',

        # menu
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'syncoria_pos_moneris_terminal/static/src/js/**/*',
            'syncoria_pos_moneris_terminal/static/src/xml/**/*',
            'syncoria_pos_moneris_terminal/static/src/scss/**/*',
        ]
    },
    # 'assets': {
    #     'point_of_sale.assets': [
    #         'syncoria_pos_moneris_terminal/static/src/js/**/*',
    #         'syncoria_pos_moneris_terminal/static/src/xml/**/*',
    #         'syncoria_pos_moneris_terminal/static/src/scss/**/*',
    #     ],
    # },
    'qweb': [

    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
