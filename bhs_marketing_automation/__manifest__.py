# -*- encoding: utf-8 -*-
{
    'name': "Advance Marketing Automation",
    'version': '1.0',
    'summary': 'Advance Marketing Automation',
    'category': 'Mail',
    'description': """
        A product of Bac Ha Software provides a solution to problems related to marketing automation
        and allows to manage marketing automation flexibility.
    """,
    "depends": ['marketing_automation'],
    'data': [
        'views/mailing_template_views.xml',
        'views/marketing_activity_views.xml',
        'views/marketing_automation_menus.xml',
        'views/marketing_campaign_views.xml',
        'views/marketing_trace_view.xml',
    ],
    # Author
    'author': 'Bac Ha Software',
    'website': 'https://bachasoftware.com',
    'maintainer': 'Bac Ha Software',
    'images': ['static/description/banner.gif'],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3'
}
