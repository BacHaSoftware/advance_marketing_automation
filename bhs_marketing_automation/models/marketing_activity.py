# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging
import threading
import pytz

from odoo import api, fields, models, _
from odoo.fields import Datetime
from odoo.exceptions import ValidationError, AccessError, UserError


_logger = logging.getLogger(__name__)

# put POSIX 'Etc/*' entries at the end to avoid confusing users - see bug 1086728
_tzs = [(tz, tz) for tz in sorted(pytz.all_timezones, key=lambda tz: tz if not tz.startswith('Etc/') else '_')]
def _tz_get(self):
    return _tzs

def utc_dt(dt, tz=None):
    local = pytz.timezone(tz or 'UTC')
    return local.localize(dt, is_dst=None).astimezone(pytz.utc)

def tz_dt(dt, tz=None):
    utc_yz = pytz.timezone('UTC')
    return utc_yz.localize(dt, is_dst=None).astimezone(pytz.timezone(tz))

class MarketingActivity(models.Model):
    _inherit = 'marketing.activity'

    state = fields.Selection([('draft', 'Draft'), ('in_queue', 'In Queue'),
                              ('sending', 'Sending'), ('done', 'Sent')],
                             string='Status', default='draft', required=True, tracking=True)
    limit_emails = fields.Integer(string="Number of emails limit", default=150,
                                  help="Maximum number of email to send per hour. Set to 0 for unlimited.")

    send_during_business_hours = fields.Boolean(string='Sent during business hours', default=False)
    campaign_timezone = fields.Selection(_tz_get, string='Campaign timezone', default=lambda self: self._context.get('tz') or 'UTC')
    time_start = fields.Float(string='Time start', index=True, default=8.0)
    time_stop = fields.Float(string='Time stop', default=17.0)

    def _get_default_time(self, label='start_utc'):
        time_start_utc = utc_dt(fields.Datetime.now().replace(hour=8, minute=0, second=0), self.env.user.partner_id.tz or 'UTC')
        time_stop_utc = utc_dt(fields.Datetime.now().replace(hour=17, minute=0, second=0), self.env.user.partner_id.tz or 'UTC')
        start_utc = time_start_utc.hour + (time_start_utc.minute / 60)
        stop_utc = time_stop_utc.hour + (time_stop_utc.minute / 60)

        retval = [{'start_utc': start_utc, 'stop_utc': stop_utc}]
        return retval[0][label]

    time_start_utc = fields.Float(string='Time start (UTC)', default=lambda self: self._get_default_time('start_utc'),  index=True)
    time_stop_utc = fields.Float(string='Time stop (UTC)', default=lambda self: self._get_default_time('stop_utc'))
    time_start_tz = fields.Float(string='Time start (in TZ)', index=True, default=8.0)
    time_stop_tz = fields.Float(string='Time stop (in TZ)', default=17.0)

    @api.onchange('activity_type')
    def onchange_activity_type(self):
        if self.activity_type != 'email':
            self.send_during_business_hours = False

    @api.onchange('campaign_timezone', 'time_start', 'time_stop')
    def onchange_time_run(self):
        if self.campaign_timezone and self.time_start and self.time_stop:
            hour_start = int(self.time_start)
            minute_start = int((self.time_start - hour_start) * 60)
            hour_stop = int(self.time_stop)
            minute_stop = int((self.time_stop - hour_stop) * 60)

            if (hour_stop - hour_start) < 1:
                raise ValidationError(_('The start time must be greater than the stop time and must be at least 1 hour apart'))

            time_start_utc = utc_dt(fields.Datetime.now().replace(hour=hour_start, minute=minute_start, second=0), self.campaign_timezone)
            time_stop_utc = utc_dt(fields.Datetime.now().replace(hour=hour_stop, minute=minute_stop, second=0), self.campaign_timezone)

            timezone = self._context.get('tz') or self.env.user.partner_id.tz or 'UTC'

            self.time_start_utc = time_start_utc.hour + (time_start_utc.minute / 60)
            self.time_stop_utc = time_stop_utc.hour + (time_stop_utc.minute / 60)

            time_start_tz = tz_dt(fields.Datetime.now().replace(hour=time_start_utc.hour, minute=time_start_utc.minute, second=0), timezone)
            time_stop_tz = tz_dt(fields.Datetime.now().replace(hour=time_stop_utc.hour, minute=time_stop_utc.minute, second=0), timezone)

            self.time_start_tz = time_start_tz.hour + (time_start_tz.minute / 60)
            self.time_stop_tz = time_stop_tz.hour + (time_stop_tz.minute / 60)

    @api.constrains('limit_emails')
    def _check_limit_emails(self):
        for record in self:
            if record.activity_type == 'email' and (record.limit_emails <= 0 or record.limit_emails > 500):
                raise UserError(_("You have to set limit emails between 1 and 500"))

    def execute(self, domain=None):
        # auto-commit except in testing mode
        auto_commit = not getattr(threading.current_thread(), 'testing', False)

        # organize traces by activity
        trace_domain = [
            ('schedule_date', '<=', Datetime.now()),
            ('state', '=', 'scheduled'),
            ('activity_id', 'in', self.ids),
            ('participant_id.state', '=', 'running'),
        ]
        if domain:
            trace_domain += domain

        # execute activity which is sending email on their traces
        trace_email_domain = trace_domain + [('activity_type', '=', 'email')]
        trace_to_email = {}
        for activity, traces in self.env['marketing.trace']._read_group(trace_email_domain, groupby=['activity_id'], aggregates=['id:recordset']):
            if activity.send_during_business_hours:
                hour_start = int(activity.time_start_utc)
                minute_start = int((activity.time_start_utc - hour_start) * 60)
                hour_stop = int(activity.time_stop_utc)
                minute_stop = int((activity.time_stop_utc - hour_stop) * 60)

                activity_time_start = fields.Datetime.now().replace(hour=hour_start, minute=minute_start, second=0).timestamp()
                activity_time_stop = fields.Datetime.now().replace(hour=hour_stop, minute=minute_stop, second=0).timestamp()

                current_time = fields.Datetime.now().timestamp()

                if hour_start > hour_stop:
                    if current_time >= activity_time_start or current_time <= activity_time_stop:
                        trace_to_email[activity] = traces
                else:
                    if current_time >= activity_time_start and current_time <= activity_time_stop:
                        trace_to_email[activity] = traces
            else:
                trace_to_email[activity] = traces

        # trace_to_email = {
        #     activity: traces
        #     for activity, traces in self.env['marketing.trace']._read_group(
        #         trace_email_domain, groupby=['activity_id'], aggregates=['id:recordset']
        #     )
        # }

        for activity, traces in trace_to_email.items():
            if activity.limit_emails <= 0:
                activity.execute_on_traces(traces)
            else:
                activity.execute_on_traces(traces[:activity.limit_emails])
            if auto_commit:
                self.env.cr.commit()

        # execute activity which is action server on their traces
        trace_action_domain = trace_domain + [('activity_type', '=', 'action')]
        trace_to_action = {
            activity: traces
            for activity, traces in self.env['marketing.trace']._read_group(
                trace_action_domain, groupby=['activity_id'], aggregates=['id:recordset']
            )
        }

        BATCH_SIZE = 500  # same batch size as the MailComposer
        for activity, traces in trace_to_action.items():
            for traces_batch in (traces[i:i + BATCH_SIZE] for i in range(0, len(traces), BATCH_SIZE)):
                activity.execute_on_traces(traces_batch)
                if auto_commit:
                    self.env.cr.commit()
