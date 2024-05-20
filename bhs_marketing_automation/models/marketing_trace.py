# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging
import threading
import pytz

from odoo import api, fields, models, _
from odoo.fields import Datetime
from odoo.exceptions import ValidationError, AccessError, UserError


_logger = logging.getLogger(__name__)


class MarketingTrace(models.Model):
    _inherit = 'marketing.trace'

    campaign_id = fields.Many2one(
        'marketing.campaign', string='Campaign',
        index=True, related='activity_id.campaign_id', store=True)
